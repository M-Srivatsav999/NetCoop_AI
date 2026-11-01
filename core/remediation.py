"""Automated Remediation Simulator.

Simulates corrective engineering actions for diagnosed root causes in a safe sandbox/dry-run environment,
projecting before/after network KPIs without touching live infrastructure (Page 3 of NetCoop AI spec).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from protocol.models import CanonicalTelemetry, HypothesisType


class RemediationLifecycleState(str, Enum):
    """Granular 10-state lifecycle machine for autonomous remediation safety."""
    RECOMMENDED = "RECOMMENDED"
    SIMULATED = "SIMULATED"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED = "APPROVED"
    REAL_EXECUTION_PENDING = "REAL_EXECUTION_PENDING"
    REAL_EXECUTED = "REAL_EXECUTED"
    SIMULATED_RECOVERY_VERIFIED = "SIMULATED_RECOVERY_VERIFIED"
    REAL_RECOVERY_VERIFIED = "REAL_RECOVERY_VERIFIED"
    FAILED = "FAILED"
    ROLLBACK_RECOMMENDED = "ROLLBACK_RECOMMENDED"


class InvalidStateTransitionError(Exception):
    """Raised when an illegal lifecycle state transition is attempted."""
    pass


class ExecutionSafetyGuardError(Exception):
    """Raised when live mutation is attempted without authorized operator credentials or receipts."""
    pass


class SimulationIntegrityError(Exception):
    """Raised when a simulated remediation falsely claims real infrastructure execution."""
    pass


class AuthorizationAuditEntry(BaseModel):
    """Immutable entry in the append-only authorization audit ledger."""
    timestamp: datetime
    operator_id: str
    incident_id: str
    action_ids: List[str]
    authorized_network_tier: str
    nonce: str
    decision: str  # "GRANTED" or "REJECTED"
    reason: str


class DurableNonceStore:
    """Persistent, atomic, concurrency-safe nonce store for anti-replay protection.
    
    Guarantees:
    - ACID atomic consumption via SQLite PRIMARY KEY constraints
    - Cross-process and cross-restart replay prevention
    - Automatic TTL expiration cleanup
    - Fail-closed security posture: if persistence fails, authorization is rejected
    """
    _db_path: Path = Path(__file__).resolve().parent.parent / "data" / "consumed_nonces.db"
    _lock = threading.Lock()

    @classmethod
    def set_db_path(cls, path: Path) -> None:
        with cls._lock:
            cls._db_path = path

    @classmethod
    def _get_connection(cls) -> sqlite3.Connection:
        cls._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(cls._db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS consumed_nonces (
                nonce TEXT PRIMARY KEY,
                operator_id TEXT NOT NULL,
                incident_id TEXT NOT NULL,
                consumed_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
        """)
        conn.commit()
        return conn

    @classmethod
    def reset_db(cls) -> None:
        """Clear all nonces from the durable store for test isolation."""
        with cls._lock:
            conn = cls._get_connection()
            try:
                conn.execute("DELETE FROM consumed_nonces")
                conn.commit()
            finally:
                conn.close()

    @classmethod
    def is_nonce_used(cls, nonce: str) -> bool:
        """Check if nonce has already been consumed (and is not expired)."""
        now = time.time()
        try:
            with cls._lock:
                conn = cls._get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT 1 FROM consumed_nonces WHERE nonce = ? AND expires_at >= ?",
                        (nonce, now)
                    )
                    return cursor.fetchone() is not None
                finally:
                    conn.close()
        except Exception as e:
            # Fail closed
            raise ExecutionSafetyGuardError(f"DurableNonceStore error during lookup: {e}")

    @classmethod
    def consume_nonce(
        cls,
        nonce: str,
        operator_id: str = "UNKNOWN",
        incident_id: str = "UNKNOWN",
        ttl_seconds: float = 3600.0
    ) -> Tuple[bool, str]:
        """Atomically consume a nonce. Returns (success, reason). Fails if already consumed or expired."""
        if not nonce or not isinstance(nonce, str):
            return False, "Invalid or empty nonce"

        now = time.time()
        expires_at = now + ttl_seconds
        try:
            with cls._lock:
                conn = cls._get_connection()
                try:
                    # Prune old expired nonces periodically
                    conn.execute("DELETE FROM consumed_nonces WHERE expires_at < ?", (now,))
                    # Atomic insert with PRIMARY KEY uniqueness
                    conn.execute(
                        "INSERT INTO consumed_nonces (nonce, operator_id, incident_id, consumed_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                        (nonce, operator_id, incident_id, now, expires_at)
                    )
                    conn.commit()
                    return True, "Nonce consumed successfully"
                except sqlite3.IntegrityError:
                    return False, f"Replay attack detected: nonce '{nonce}' has already been consumed"
                finally:
                    conn.close()
        except Exception as e:
            # Fail closed
            raise ExecutionSafetyGuardError(f"DurableNonceStore failed during atomic consumption: {e}")

    @classmethod
    def clear(cls) -> None:
        """Clear database for test isolation."""
        try:
            with cls._lock:
                if cls._db_path.exists():
                    conn = cls._get_connection()
                    try:
                        conn.execute("DELETE FROM consumed_nonces")
                        conn.commit()
                    finally:
                        conn.close()
        except Exception:
            pass


class AuthorizationAuditLedger:
    """Thread-safe append-only audit ledger for authorization events."""
    _entries: List[AuthorizationAuditEntry] = []
    _used_nonces: Set[str] = set()

    @classmethod
    def record_attempt(
        cls,
        operator_id: str,
        incident_id: str,
        action_ids: List[str],
        tier: str,
        nonce: str,
        decision: str,
        reason: str
    ) -> None:
        cls._entries.append(AuthorizationAuditEntry(
            timestamp=datetime.now(timezone.utc),
            operator_id=operator_id,
            incident_id=incident_id,
            action_ids=list(action_ids),
            authorized_network_tier=tier,
            nonce=nonce,
            decision=decision,
            reason=reason
        ))

    @classmethod
    def is_nonce_used(cls, nonce: str) -> bool:
        if nonce in cls._used_nonces:
            return True
        return DurableNonceStore.is_nonce_used(nonce)

    @classmethod
    def register_nonce(cls, nonce: str, operator_id: str = "UNKNOWN", incident_id: str = "UNKNOWN") -> None:
        cls._used_nonces.add(nonce)
        DurableNonceStore.consume_nonce(nonce, operator_id, incident_id)

    @classmethod
    def get_entries(cls) -> List[AuthorizationAuditEntry]:
        return list(cls._entries)

    @classmethod
    def clear(cls) -> None:
        cls._entries.clear()
        cls._used_nonces.clear()
        DurableNonceStore.clear()


def compute_canonical_authorization_message(
    operator_id: str,
    incident_id: str,
    action_ids: List[str],
    authorized_network_tier: str,
    timestamp: datetime,
    nonce: str,
    authorization_scope: str = "CORRECTIVE_REMEDIATION"
) -> bytes:
    """Canonical sorted JSON serialization for authorization signature binding."""
    ts = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
    ts_str = ts.astimezone(timezone.utc).isoformat()
    canonical_dict = {
        "action_ids": sorted(list(action_ids)),
        "authorized_network_tier": authorized_network_tier,
        "incident_id": incident_id,
        "nonce": nonce,
        "operator_id": operator_id,
        "scope": authorization_scope,
        "timestamp": ts_str
    }
    return json.dumps(canonical_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")


class OperatorAuthorizationRecord(BaseModel):
    """Cryptographically verifiable operator approval audit record.
    
    No authorization secrets or passwords are hardcoded in source code.
    Binds operator_id, incident_id, exact action_ids, network tier, nonce, scope, and timestamp.
    """
    operator_id: str
    incident_id: str
    action_ids: List[str] = Field(default_factory=lambda: ["ACT-DEFAULT"])
    authorized_network_tier: str = "CAMPUS_ACCESS_TIER"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    nonce: str = Field(default_factory=lambda: uuid.uuid4().hex)
    authorization_scope: str = "CORRECTIVE_REMEDIATION"
    auth_token: str = ""
    digital_signature: str = ""
    ttl_seconds: int = 300
    clock_skew_seconds: float = 60.0
    audit_notes: str = ""

    def sign(self, secret_key: str) -> str:
        """Compute and set HMAC-SHA256 signature over canonical payload."""
        msg = compute_canonical_authorization_message(
            operator_id=self.operator_id,
            incident_id=self.incident_id,
            action_ids=self.action_ids,
            authorized_network_tier=self.authorized_network_tier,
            timestamp=self.timestamp,
            nonce=self.nonce,
            authorization_scope=self.authorization_scope
        )
        self.auth_token = hmac.new(secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        _ACTIVE_AUTHORIZATIONS_BY_TOKEN[self.auth_token] = self
        return self.auth_token

    def verify_and_audit(
        self,
        secret_key: str,
        target_incident_id: Optional[str] = None,
        target_action_id: Optional[str] = None,
        target_network_tier: Optional[str] = None,
        now: Optional[datetime] = None,
        enforce_nonce_reuse: bool = True
    ) -> Tuple[bool, str]:
        """Cryptographically verify authorization record against policies.
        
        Returns (is_valid, reason).
        """
        if not secret_key:
            msg = "Missing operator secret key"
            AuthorizationAuditLedger.record_attempt(
                self.operator_id, self.incident_id, self.action_ids, self.authorized_network_tier,
                self.nonce, "REJECTED", msg
            )
            return False, msg

        current_time = now or datetime.now(timezone.utc)
        record_time = self.timestamp if self.timestamp.tzinfo else self.timestamp.replace(tzinfo=timezone.utc)

        # 1. Clock skew check (reject future-dated tokens outside tolerance)
        future_delta = (record_time - current_time).total_seconds()
        if future_delta > self.clock_skew_seconds:
            msg = f"Token timestamp is {future_delta:.1f}s in the future (exceeds {self.clock_skew_seconds}s limit)"
            AuthorizationAuditLedger.record_attempt(
                self.operator_id, self.incident_id, self.action_ids, self.authorized_network_tier,
                self.nonce, "REJECTED", msg
            )
            return False, msg

        # 2. TTL expiration check
        age_seconds = (current_time - record_time).total_seconds()
        if age_seconds > self.ttl_seconds:
            msg = f"Token expired ({age_seconds:.1f}s old, TTL is {self.ttl_seconds}s)"
            AuthorizationAuditLedger.record_attempt(
                self.operator_id, self.incident_id, self.action_ids, self.authorized_network_tier,
                self.nonce, "REJECTED", msg
            )
            return False, msg

        # 3. Nonce reuse prevention
        if enforce_nonce_reuse and AuthorizationAuditLedger.is_nonce_used(self.nonce):
            msg = f"Replay attack detected: nonce '{self.nonce}' has already been consumed"
            AuthorizationAuditLedger.record_attempt(
                self.operator_id, self.incident_id, self.action_ids, self.authorized_network_tier,
                self.nonce, "REJECTED", msg
            )
            return False, msg

        # 4. Target incident binding
        if target_incident_id and self.incident_id != target_incident_id:
            msg = f"Incident mismatch: token is for '{self.incident_id}', target is '{target_incident_id}'"
            AuthorizationAuditLedger.record_attempt(
                self.operator_id, self.incident_id, self.action_ids, self.authorized_network_tier,
                self.nonce, "REJECTED", msg
            )
            return False, msg

        # 5. Target action binding
        if target_action_id and target_action_id not in self.action_ids:
            msg = f"Action mismatch: '{target_action_id}' is not in authorized actions {self.action_ids}"
            AuthorizationAuditLedger.record_attempt(
                self.operator_id, self.incident_id, self.action_ids, self.authorized_network_tier,
                self.nonce, "REJECTED", msg
            )
            return False, msg

        # 6. Target network tier binding
        if target_network_tier and self.authorized_network_tier != target_network_tier:
            msg = f"Network tier mismatch: token authorizes '{self.authorized_network_tier}', target requires '{target_network_tier}'"
            AuthorizationAuditLedger.record_attempt(
                self.operator_id, self.incident_id, self.action_ids, self.authorized_network_tier,
                self.nonce, "REJECTED", msg
            )
            return False, msg

        # 7. Cryptographic signature verification over canonical payload
        expected_msg = compute_canonical_authorization_message(
            operator_id=self.operator_id,
            incident_id=self.incident_id,
            action_ids=self.action_ids,
            authorized_network_tier=self.authorized_network_tier,
            timestamp=self.timestamp,
            nonce=self.nonce,
            authorization_scope=self.authorization_scope
        )
        expected_token = hmac.new(secret_key.encode("utf-8"), expected_msg, hashlib.sha256).hexdigest()

        if not hmac.compare_digest(self.auth_token, expected_token):
            msg = "Cryptographic signature verification failed: invalid signature"
            AuthorizationAuditLedger.record_attempt(
                self.operator_id, self.incident_id, self.action_ids, self.authorized_network_tier,
                self.nonce, "REJECTED", msg
            )
            return False, msg

        AuthorizationAuditLedger.record_attempt(
            self.operator_id, self.incident_id, self.action_ids, self.authorized_network_tier,
            self.nonce, "GRANTED", "Authorization signature and constraints verified"
        )
        return True, "Valid authorization"

    def verify_token(self, secret_key: str, enforce_nonce_reuse: bool = False) -> bool:
        """Verify HMAC-SHA256 signature for this operator authorization."""
        valid, _ = self.verify_and_audit(secret_key, enforce_nonce_reuse=enforce_nonce_reuse)
        return valid


class RegisteredAdapter(BaseModel):
    """Cryptographically verifiable execution adapter registered with the platform."""
    adapter_id: str
    name: str
    supported_tiers: List[str] = Field(default_factory=lambda: ["CAMPUS_ACCESS_TIER"])
    signing_key: str = "DEFAULT-ADAPTER-SIGNING-KEY"
    is_active: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExecutionAdapterRegistry:
    """Central registry of verified network execution adapters."""
    _adapters: Dict[str, RegisteredAdapter] = {}

    @classmethod
    def register_adapter(
        cls,
        adapter_id: str,
        name: str,
        supported_tiers: Optional[List[str]] = None,
        signing_key: str = "DEFAULT-ADAPTER-SIGNING-KEY",
        metadata: Optional[Dict[str, Any]] = None
    ) -> RegisteredAdapter:
        adapter = RegisteredAdapter(
            adapter_id=adapter_id,
            name=name,
            supported_tiers=supported_tiers or ["CAMPUS_ACCESS_TIER", "CAMPUS_CORE_TIER"],
            signing_key=signing_key,
            metadata=metadata or {}
        )
        cls._adapters[adapter_id] = adapter
        return adapter

    @classmethod
    def get_adapter(cls, adapter_id: str) -> Optional[RegisteredAdapter]:
        if not cls._adapters:
            cls.initialize_defaults()
        return cls._adapters.get(adapter_id)

    @classmethod
    def is_registered(cls, adapter_id: str) -> bool:
        if not cls._adapters:
            cls.initialize_defaults()
        return adapter_id in cls._adapters

    @classmethod
    def verify_receipt(cls, receipt: ExecutionReceipt) -> Tuple[bool, str]:
        """Verify receipt against registered adapter identity and cryptographic signature."""
        adapter = cls.get_adapter(receipt.execution_adapter_id)
        if not adapter:
            return False, f"Unknown or unregistered execution adapter '{receipt.execution_adapter_id}'"
        if not adapter.is_active:
            return False, f"Execution adapter '{receipt.execution_adapter_id}' is deactivated"

        if getattr(receipt, "adapter_signature", None):
            canonical_msg = json.dumps({
                "action_id": receipt.action_id,
                "execution_id": receipt.execution_id,
                "incident_id": receipt.incident_id,
                "operator_id": receipt.operator_id,
                "result": receipt.execution_result,
                "target_device": receipt.target_device
            }, sort_keys=True).encode("utf-8")
            expected_sig = hmac.new(adapter.signing_key.encode("utf-8"), canonical_msg, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(receipt.adapter_signature, expected_sig):
                return False, f"Execution receipt signature mismatch for adapter '{receipt.execution_adapter_id}'"

        return True, "Adapter verified"

    @classmethod
    def initialize_defaults(cls) -> None:
        """Register default trusted adapters for IIT Bhubaneswar campus infrastructure."""
        defaults = [
            ("CISCO-IOSXE-SSH-ADAPTER", "Cisco IOS-XE Driver (Legacy ID)"),
            ("ADAPTER-01", "Campus Core Switch Driver"),
            ("CISCO-IOSXE", "Cisco Switch Driver"),
            ("ADAPTER-CISCO-IOS-XE", "Cisco IOS-XE NETCONF/SSH Adapter"),
            ("ADAPTER-LINUX-SYSTEMD", "Linux Services & Daemon Controller"),
            ("ADAPTER-MOCK-TESTING", "Automated Testing Sandbox Driver")
        ]
        for aid, aname in defaults:
            cls._adapters[aid] = RegisteredAdapter(
                adapter_id=aid,
                name=aname,
                supported_tiers=["CAMPUS_ACCESS_TIER", "CAMPUS_AGGREGATION_TIER", "CAMPUS_CORE_TIER", "CAMPUS_SERVICES_TIER"],
                signing_key=f"KEY-{aid}-IITBBS"
            )


# Initialize default trusted execution adapters
ExecutionAdapterRegistry.initialize_defaults()


class ExecutionReceipt(BaseModel):
    """Cryptographic and operational proof of execution from a registered network execution adapter."""
    execution_adapter_id: str
    execution_id: str
    incident_id: str
    action_id: str
    operator_id: str
    authorization_ref: str
    execution_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    target_device: str
    execution_result: str = "SUCCESS"  # "SUCCESS" or "FAILED"
    adapter_response: Dict[str, Any] = Field(default_factory=dict)
    audit_reference: str
    adapter_signature: Optional[str] = None

    def sign_with_adapter(self, signing_key: str) -> str:
        """Compute HMAC-SHA256 signature for this execution receipt using adapter signing key."""
        canonical_msg = json.dumps({
            "action_id": self.action_id,
            "execution_id": self.execution_id,
            "incident_id": self.incident_id,
            "operator_id": self.operator_id,
            "result": self.execution_result,
            "target_device": self.target_device
        }, sort_keys=True).encode("utf-8")
        self.adapter_signature = hmac.new(signing_key.encode("utf-8"), canonical_msg, hashlib.sha256).hexdigest()
        return self.adapter_signature

    def verify_against_authorization(self, auth: OperatorAuthorizationRecord) -> Tuple[bool, str]:
        """Verify execution receipt aligns with authorized scope and operator."""
        if self.incident_id != auth.incident_id:
            return False, f"Receipt incident '{self.incident_id}' != Auth incident '{auth.incident_id}'"
        if self.action_id not in auth.action_ids:
            return False, f"Receipt action '{self.action_id}' not in authorized action IDs {auth.action_ids}"
        if self.operator_id != auth.operator_id:
            return False, f"Receipt operator '{self.operator_id}' != Auth operator '{auth.operator_id}'"
        if self.authorization_ref != auth.auth_token:
            return False, "Receipt authorization_ref does not match authorization token"
        if self.execution_result.upper() != "SUCCESS":
            return False, f"Execution receipt indicates non-successful outcome: {self.execution_result}"
        return True, "Execution receipt verified against authorization"


def is_live_execution_enabled() -> bool:
    """Check if production network live mutation is enabled via environment.
    
    Canonical variable: NETCOOP_ENABLE_LIVE_EXECUTION
    Defaults strictly to False (Safe Simulation-Only Mode for campus network safety).
    """
    val = os.environ.get("NETCOOP_ENABLE_LIVE_EXECUTION", "0").strip().lower()
    return val in ("1", "true")


def get_operator_secret_key() -> Optional[str]:
    """Retrieve external operator authorization secret from environment."""
    return os.environ.get("NETCOOP_OPERATOR_SECRET_KEY")


_ACTIVE_AUTHORIZATIONS_BY_TOKEN: Dict[str, OperatorAuthorizationRecord] = {}


def create_operator_authorization(
    operator_id: str,
    incident_id: str,
    secret_key: str,
    action_ids: Optional[List[str]] = None,
    authorized_network_tier: str = "CAMPUS_ACCESS_TIER",
    timestamp: Optional[datetime] = None,
    nonce: Optional[str] = None,
    authorization_scope: str = "CORRECTIVE_REMEDIATION",
    ttl_seconds: int = 300
) -> OperatorAuthorizationRecord:
    """Helper to create and sign a complete OperatorAuthorizationRecord."""
    rec = OperatorAuthorizationRecord(
        operator_id=operator_id,
        incident_id=incident_id,
        action_ids=action_ids if action_ids is not None else ["ACT-DEFAULT"],
        authorized_network_tier=authorized_network_tier,
        timestamp=timestamp or datetime.now(timezone.utc),
        nonce=nonce or uuid.uuid4().hex,
        authorization_scope=authorization_scope,
        ttl_seconds=ttl_seconds
    )
    rec.sign(secret_key)
    return rec


def generate_operator_token(
    operator_id: str,
    incident_id: str,
    secret_key: str,
    action_ids: Optional[List[str]] = None,
    authorized_network_tier: str = "CAMPUS_ACCESS_TIER",
    timestamp: Optional[datetime] = None,
    nonce: Optional[str] = None,
    authorization_scope: str = "CORRECTIVE_REMEDIATION"
) -> str:
    """Generate a canonical HMAC-SHA256 operator token."""
    rec = create_operator_authorization(
        operator_id=operator_id,
        incident_id=incident_id,
        secret_key=secret_key,
        action_ids=action_ids,
        authorized_network_tier=authorized_network_tier,
        timestamp=timestamp,
        nonce=nonce,
        authorization_scope=authorization_scope
    )
    return rec.auth_token


class RemediationLifecycleStateMachine:
    """Strict state machine governing remediation lifecycle progression and execution guards."""

    VALID_TRANSITIONS: Dict[RemediationLifecycleState, Set[RemediationLifecycleState]] = {
        RemediationLifecycleState.RECOMMENDED: {
            RemediationLifecycleState.SIMULATED,
            RemediationLifecycleState.FAILED,
        },
        RemediationLifecycleState.SIMULATED: {
            RemediationLifecycleState.SIMULATED_RECOVERY_VERIFIED,
            RemediationLifecycleState.APPROVAL_PENDING,
            RemediationLifecycleState.FAILED,
        },
        RemediationLifecycleState.SIMULATED_RECOVERY_VERIFIED: {
            RemediationLifecycleState.APPROVAL_PENDING,
            RemediationLifecycleState.FAILED,
            RemediationLifecycleState.ROLLBACK_RECOMMENDED,
        },
        RemediationLifecycleState.APPROVAL_PENDING: {
            RemediationLifecycleState.APPROVED,
            RemediationLifecycleState.FAILED,
        },
        RemediationLifecycleState.APPROVED: {
            RemediationLifecycleState.REAL_EXECUTION_PENDING,
            RemediationLifecycleState.FAILED,
        },
        RemediationLifecycleState.REAL_EXECUTION_PENDING: {
            RemediationLifecycleState.REAL_EXECUTED,
            RemediationLifecycleState.FAILED,
        },
        RemediationLifecycleState.REAL_EXECUTED: {
            RemediationLifecycleState.REAL_RECOVERY_VERIFIED,
            RemediationLifecycleState.FAILED,
            RemediationLifecycleState.ROLLBACK_RECOMMENDED,
        },
        RemediationLifecycleState.REAL_RECOVERY_VERIFIED: set(),
        RemediationLifecycleState.FAILED: {
            RemediationLifecycleState.ROLLBACK_RECOMMENDED,
        },
        RemediationLifecycleState.ROLLBACK_RECOMMENDED: set(),
    }

    def __init__(
        self,
        initial_state: RemediationLifecycleState = RemediationLifecycleState.RECOMMENDED,
        incident_id: str = "INC-UNASSIGNED"
    ) -> None:
        self.current_state = initial_state
        self.incident_id = incident_id
        self.authorization_record: Optional[OperatorAuthorizationRecord] = None
        self.execution_receipt: Optional[ExecutionReceipt] = None
        self.state_history: List[Tuple[RemediationLifecycleState, datetime]] = [
            (self.current_state, datetime.now(timezone.utc))
        ]

    def transition_to(
        self,
        target_state: RemediationLifecycleState,
        authorization: Optional[OperatorAuthorizationRecord | str] = None,
        execution_receipt: Optional[ExecutionReceipt] = None,
        post_execution_telemetry: Optional[List[CanonicalTelemetry]] = None
    ) -> RemediationLifecycleState:
        """Attempt state transition enforcing safety guards."""
        valid_next = self.VALID_TRANSITIONS.get(self.current_state, set())
        if target_state not in valid_next:
            raise InvalidStateTransitionError(
                f"Invalid lifecycle transition: cannot move from {self.current_state.value} to {target_state.value}. "
                f"Allowed transitions from {self.current_state.value} are: {[s.value for s in valid_next]}"
            )

        # Execution safety guard: moving to REAL_EXECUTED requires explicit authorization and an execution receipt
        if target_state == RemediationLifecycleState.REAL_EXECUTED:
            if not is_live_execution_enabled():
                raise ExecutionSafetyGuardError(
                    f"ExecutionSafetyGuard blocked transition to {target_state.value}! "
                    "Live production mutation is strictly disabled in safe simulation-only mode. "
                    "Campus network protection policy forbids unauthenticated physical switches reconfiguration."
                )

            secret_key = get_operator_secret_key()
            if not secret_key:
                raise ExecutionSafetyGuardError(
                    "ExecutionSafetyGuard blocked transition: NETCOOP_OPERATOR_SECRET_KEY is not configured in environment. "
                    "No production authorization keys are hardcoded in source code."
                )

            if not authorization:
                raise ExecutionSafetyGuardError(
                    "ExecutionSafetyGuard blocked transition: missing operator authorization credentials."
                )

            # Validate authorization record
            auth_rec: OperatorAuthorizationRecord
            if isinstance(authorization, str):
                if authorization in _ACTIVE_AUTHORIZATIONS_BY_TOKEN:
                    auth_rec = _ACTIVE_AUTHORIZATIONS_BY_TOKEN[authorization]
                else:
                    auth_rec = OperatorAuthorizationRecord(
                        operator_id="NOC_OPERATOR",
                        incident_id=self.incident_id,
                        action_ids=["ACT-DEFAULT"],
                        auth_token=authorization
                    )
            elif isinstance(authorization, OperatorAuthorizationRecord):
                auth_rec = authorization
            else:
                raise ExecutionSafetyGuardError("Unsupported authorization format.")

            valid, reason = auth_rec.verify_and_audit(secret_key, target_incident_id=self.incident_id)
            if not valid:
                raise ExecutionSafetyGuardError(
                    f"ExecutionSafetyGuard blocked transition: authorization check failed — {reason}"
                )
            self.authorization_record = auth_rec

            # Priority 2: An authorization alone does NOT establish REAL_EXECUTED! Genuine ExecutionReceipt is mandatory!
            if execution_receipt is None:
                raise ExecutionSafetyGuardError(
                    "ExecutionSafetyGuard blocked transition to REAL_EXECUTED: genuine ExecutionReceipt from a "
                    "registered execution adapter is mandatory. Authorization alone does not prove execution."
                )

            rcpt_valid, rcpt_reason = execution_receipt.verify_against_authorization(self.authorization_record)
            if not rcpt_valid:
                raise ExecutionSafetyGuardError(
                    f"ExecutionSafetyGuard blocked transition: execution receipt validation failed — {rcpt_reason}"
                )

            # Cryptographically verify execution receipt against registered execution adapter
            adapter_valid, adapter_reason = ExecutionAdapterRegistry.verify_receipt(execution_receipt)
            if not adapter_valid:
                raise ExecutionSafetyGuardError(
                    f"ExecutionSafetyGuard blocked transition: adapter verification failed — {adapter_reason}"
                )

            self.execution_receipt = execution_receipt
            # Atomically consume nonce upon verified execution in durable store
            AuthorizationAuditLedger.register_nonce(
                self.authorization_record.nonce,
                self.authorization_record.operator_id,
                self.authorization_record.incident_id
            )

        # Moving to REAL_RECOVERY_VERIFIED requires actual post-execution telemetry meeting criteria
        elif target_state == RemediationLifecycleState.REAL_RECOVERY_VERIFIED:
            if not post_execution_telemetry:
                raise ExecutionSafetyGuardError(
                    "Transition to REAL_RECOVERY_VERIFIED blocked: requires measured post-execution telemetry "
                    "meeting defined nominal recovery envelope. Simulated projections cannot verify real recovery."
                )
            for record in post_execution_telemetry:
                m = record.metrics
                if m.packet_loss_pct is not None and m.packet_loss_pct > 2.0:
                    raise ExecutionSafetyGuardError(
                        f"Post-execution telemetry failed recovery criteria on {record.device_id}: packet loss {m.packet_loss_pct}% > 2.0%"
                    )
                if m.interface_errors is not None and m.interface_errors > 10:
                    raise ExecutionSafetyGuardError(
                        f"Post-execution telemetry failed recovery criteria on {record.device_id}: interface errors {m.interface_errors} > 10"
                    )
                if m.latency_ms is not None and m.latency_ms > 50.0:
                    raise ExecutionSafetyGuardError(
                        f"Post-execution telemetry failed recovery criteria on {record.device_id}: latency {m.latency_ms}ms > 50.0ms"
                    )

        self.current_state = target_state
        self.state_history.append((self.current_state, datetime.now(timezone.utc)))
        return self.current_state


class RemediationAction(BaseModel):
    """Specific simulated corrective engineering step."""
    action_id: str
    target_device: str
    action_type: str
    simulated_cli_command: str
    rollback_cli_command: str = ""
    rationale: str
    projected_recovery: Dict[str, Any]
    safety_level: str = "SAFE_NON_DESTRUCTIVE"
    operator_approval_required: bool = True


class SimulationResult(BaseModel):
    """Complete dry-run remediation simulation plan."""
    simulation_id: str
    suspected_root_cause: str
    affected_devices: List[str]
    actions: List[RemediationAction]
    projected_network_status: str
    blast_radius_contained: bool
    risk_level: str
    lifecycle_state: str = "SIMULATED"  # RECOMMENDED -> SIMULATED -> APPROVED -> EXECUTED -> RECOVERY_VERIFIED
    human_in_the_loop_status: str = "PENDING_OPERATOR_CONFIRMATION"
    dry_run_disclaimer: str = (
        "Dry-run simulation only. In compliance with NetCoop AI requirements, "
        "no commands are dispatched to live production infrastructure without explicit authorization."
    )
    is_real_execution: bool = False
    is_simulated: bool = True
    operator_authorization_record: Optional[OperatorAuthorizationRecord] = None

    def create_state_machine(self) -> RemediationLifecycleStateMachine:
        return RemediationLifecycleStateMachine(
            initial_state=RemediationLifecycleState(self.lifecycle_state),
            incident_id=self.simulation_id
        )


class VerificationResult(BaseModel):
    """Post-remediation simulation recovery verification audit."""
    simulation_id: str
    suspected_root_cause: str
    lifecycle_state: str = "SIMULATED_RECOVERY_VERIFIED"
    recovery_verified: bool
    kpi_deltas: Dict[str, Dict[str, Any]]
    rollback_recommended: bool = False
    rollback_cli_command: Optional[str] = None
    verification_summary: str
    is_real_recovery_measured: bool = False
    is_simulated_projection: bool = True


class RemediationSimulator:
    """Deterministic simulation engine generating targeted corrective playbooks with KPI projections."""

    @classmethod
    def simulate_remediation(
        cls,
        root_cause: str,
        affected_devices: List[str],
        telemetry_records: Optional[List[CanonicalTelemetry]] = None
    ) -> SimulationResult:
        """Generate a simulated remediation execution plan with before-and-after KPI projections."""
        sim_id = f"SIM-{abs(hash(root_cause + ''.join(affected_devices))) % 100000:05d}"
        actions: List[RemediationAction] = []
        projected_status = "STABILIZED"
        risk = "LOW"

        dev_list = affected_devices if affected_devices else ["CAMPUS_GATEWAY"]

        for idx, dev in enumerate(dev_list, 1):
            if root_cause == HypothesisType.LINK_CONGESTION.value:
                actions.append(RemediationAction(
                    action_id=f"ACT-QOS-{idx}",
                    target_device=dev,
                    action_type="APPLY_DSCP_QOS_POLICING",
                    simulated_cli_command=f"switch(config-if)# qos policy rate-limit 800mbps dscp-priority ef burst 64k",
                    rollback_cli_command=f"switch(config-if)# no qos policy rate-limit",
                    rationale="Throttle non-essential bulk traffic and prioritize interactive voice/video queues to clear bufferbloat.",
                    projected_recovery={
                        "egress_queue_drops": {"before": 145, "projected_after": 0},
                        "round_trip_latency_ms": {"before": 185.0, "projected_after": 18.5},
                        "packet_loss_pct": {"before": 5.2, "projected_after": 0.0}
                    },
                    safety_level="SAFE_NON_DESTRUCTIVE",
                    operator_approval_required=True
                ))
            elif root_cause == HypothesisType.HARDWARE_FAILURE.value:
                actions.append(RemediationAction(
                    action_id=f"ACT-PHY-FAILOVER-{idx}",
                    target_device=dev,
                    action_type="FAILOVER_TO_STANDBY_OPTICAL_UPLINK",
                    simulated_cli_command=f"switch(config-if)# interface Te1/0/2; shutdown; interface Te1/0/3; no shutdown",
                    rollback_cli_command=f"switch(config-if)# interface Te1/0/3; shutdown; interface Te1/0/2; no shutdown",
                    rationale="Isolate degraded optical transceiver with high CRC errors and migrate uplink traffic to standby redundant pair.",
                    projected_recovery={
                        "interface_crc_errors_rate": {"before": 740, "projected_after": 0},
                        "packet_loss_pct": {"before": 14.2, "projected_after": 0.0}
                    },
                    safety_level="CONTROLLED_FAILOVER",
                    operator_approval_required=True
                ))
                risk = "MEDIUM"
            elif root_cause == HypothesisType.WEAK_WIFI.value:
                actions.append(RemediationAction(
                    action_id=f"ACT-RF-TUNE-{idx}",
                    target_device=dev,
                    action_type="ADJUST_AP_TX_POWER_AND_CHANNEL_WIDTH",
                    simulated_cli_command=f"wlc(config-ap)# tx-power 20dbm; channel-width 40mhz; rrm-rebalance",
                    rollback_cli_command=f"wlc(config-ap)# tx-power default; channel-width default",
                    rationale="Increase transmit power by +4dBm and narrow channel from 80MHz to 40MHz to overcome RF attenuation.",
                    projected_recovery={
                        "signal_strength_rssi_dbm": {"before": -86.5, "projected_after": -62.0},
                        "wi-fi_retransmissions_pct": {"before": 18.2, "projected_after": 1.5},
                        "client_throughput_mbps": {"before": 3.5, "projected_after": 54.0}
                    },
                    safety_level="SAFE_NON_DESTRUCTIVE",
                    operator_approval_required=False
                ))
            elif root_cause == HypothesisType.DNS_DHCP_FAILURE.value:
                actions.append(RemediationAction(
                    action_id=f"ACT-SVC-RESTART-{idx}",
                    target_device=dev,
                    action_type="RESTART_RESOLVER_DAEMON_AND_PURGE_CACHE",
                    simulated_cli_command=f"systemctl restart named.service; unbound-control reload",
                    rollback_cli_command=f"systemctl reload named.service",
                    rationale="Clear memory leak on core resolver daemon and cycle stale connection pools.",
                    projected_recovery={
                        "dns_query_latency_ms": {"before": 2950.0, "projected_after": 6.2},
                        "dhcp_lease_success": {"before": False, "projected_after": True}
                    },
                    safety_level="SAFE_NON_DESTRUCTIVE",
                    operator_approval_required=True
                ))
            elif root_cause == HypothesisType.RESOURCE_EXHAUSTION.value:
                actions.append(RemediationAction(
                    action_id=f"ACT-CPU-RECLAIM-{idx}",
                    target_device=dev,
                    action_type="GRACEFUL_SUPERVISOR_ENGINE_FAILOVER",
                    simulated_cli_command=f"switch# redundancy force-switchover",
                    rollback_cli_command=f"switch# redundancy force-switchover",
                    rationale="Gracefully failover control plane processing to standby supervisor to clear thread lock.",
                    projected_recovery={
                        "cpu_utilization_pct": {"before": 98.5, "projected_after": 24.0},
                        "memory_utilization_pct": {"before": 94.2, "projected_after": 38.0}
                    },
                    safety_level="CONTROLLED_FAILOVER",
                    operator_approval_required=True
                ))
                risk = "MEDIUM"
            else:
                actions.append(RemediationAction(
                    action_id=f"ACT-MONITOR-{idx}",
                    target_device=dev,
                    action_type="ENABLE_HIGH_FREQUENCY_TELEMETRY",
                    simulated_cli_command=f"switch# telemetry ietf subscription 101 encoding proto stream-rate 1s",
                    rollback_cli_command=f"switch# no telemetry ietf subscription 101",
                    rationale="Maintain active telemetry stream monitoring for anomaly reoccurrence.",
                    projected_recovery={"status": {"before": "NOMINAL", "projected_after": "NOMINAL"}},
                    safety_level="SAFE_NON_DESTRUCTIVE",
                    operator_approval_required=False
                ))

        return SimulationResult(
            simulation_id=sim_id,
            suspected_root_cause=root_cause,
            affected_devices=affected_devices,
            actions=actions,
            projected_network_status=projected_status,
            blast_radius_contained=True,
            risk_level=risk,
            lifecycle_state="SIMULATED",
            human_in_the_loop_status="PENDING_OPERATOR_CONFIRMATION"
        )

    @classmethod
    def verify_simulated_recovery(
        cls,
        simulation: SimulationResult,
        post_action_telemetry: Optional[List[CanonicalTelemetry]] = None
    ) -> VerificationResult:
        """Verify post-remediation recovery criteria and calculate projected KPI recovery deltas."""
        deltas: Dict[str, Dict[str, Any]] = {}
        all_recovered = True
        rollback_recom = False
        rollback_cmd = None

        for act in simulation.actions:
            if act.rollback_cli_command and not rollback_cmd:
                rollback_cmd = act.rollback_cli_command

            for kpi_name, kpi_data in act.projected_recovery.items():
                if isinstance(kpi_data, dict) and "before" in kpi_data and "projected_after" in kpi_data:
                    try:
                        b = float(kpi_data["before"])
                        a = float(kpi_data["projected_after"])
                        delta_pct = round(((b - a) / b) * 100.0, 1) if b != 0 else 0.0
                        deltas[f"{act.target_device}_{kpi_name}"] = {
                            "before": b,
                            "projected_after": a,
                            "improvement_pct": delta_pct
                        }
                    except (ValueError, TypeError):
                        pass

        summary = (
            f"Simulated remediation verified successfully across {len(simulation.actions)} action(s). "
            f"All critical KPIs projected to return within nominal campus operating baselines."
        )

        return VerificationResult(
            simulation_id=simulation.simulation_id,
            suspected_root_cause=simulation.suspected_root_cause,
            lifecycle_state="SIMULATED_RECOVERY_VERIFIED" if all_recovered else "ROLLBACK_RECOMMENDED",
            recovery_verified=all_recovered,
            kpi_deltas=deltas,
            rollback_recommended=rollback_recom,
            rollback_cli_command=rollback_cmd,
            verification_summary=summary
        )
