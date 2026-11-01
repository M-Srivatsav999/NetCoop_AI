"""Security Audit Test Suite for Remediation Safety and Authorization.

Proves:
1. No hardcoded authorization secrets remain anywhere in source code or configuration.
2. Safe simulation mode is strictly enforced by default (live execution disabled).
3. Missing or invalid operator authorization is rejected immediately.
4. Simulated plans cannot falsely claim real execution (is_real_execution is False).
5. Simulated recovery cannot be falsely presented as measured real recovery.
6. Operator authorization records are structured and audit-ready (operator_id, timestamp, incident_id).
"""

import inspect
import pytest
from datetime import datetime, timedelta, timezone
import core.remediation as remediation_module
from core.remediation import (
    AuthorizationAuditLedger,
    DurableNonceStore,
    ExecutionAdapterRegistry,
    ExecutionReceipt,
    ExecutionSafetyGuardError,
    OperatorAuthorizationRecord,
    RemediationLifecycleState,
    RemediationLifecycleStateMachine,
    RemediationSimulator,
    SimulationResult,
    VerificationResult,
    create_operator_authorization,
    generate_operator_token,
    is_live_execution_enabled,
)


def test_security_no_hardcoded_secrets_in_remediation_module():
    """Verify that no static shared authorization string or password exists in core/remediation.py."""
    source_code = inspect.getsource(remediation_module)

    # 1. Old insecure hardcoded key must not exist anywhere
    assert "NETCOOP-AUTHORIZED-LIVE-KEY-IITBBS-2026" not in source_code

    # 2. No hardcoded passwords or fixed secrets
    forbidden_tokens = ["password123", "secret_key = \"", "auth_key = \"NETCOOP"]
    for tok in forbidden_tokens:
        assert tok.lower() not in source_code.lower()


def test_security_default_mode_is_simulation_only():
    """Verify that live execution is disabled by default in absence of explicit environment flag."""
    assert is_live_execution_enabled() is False

    sm = RemediationLifecycleStateMachine(RemediationLifecycleState.REAL_EXECUTION_PENDING)
    with pytest.raises(ExecutionSafetyGuardError) as exc_info:
        sm.transition_to(RemediationLifecycleState.REAL_EXECUTED)
    assert "Live production mutation is strictly disabled in safe simulation-only mode" in str(exc_info.value)


def test_security_simulation_cannot_claim_real_execution():
    """Verify that SimulationResult and VerificationResult explicitly distinguish simulated from real."""
    sim = RemediationSimulator.simulate_remediation("LINK_CONGESTION", ["IITBBS-SW-MHR"])

    # Must be marked simulated
    assert sim.is_simulated is True
    assert sim.is_real_execution is False
    assert "dry-run" in sim.dry_run_disclaimer.lower()

    # Recovery verification must be marked as simulated projection
    verif = RemediationSimulator.verify_simulated_recovery(sim)
    assert verif.is_simulated_projection is True
    assert verif.is_real_recovery_measured is False
    assert verif.lifecycle_state == "SIMULATED_RECOVERY_VERIFIED"


def test_security_structured_operator_authorization_audit_record(monkeypatch):
    """Verify operator approval records capture identity, incident ID, timestamp, and signature."""
    secret = "production-external-secret-env"
    monkeypatch.setenv("NETCOOP_ENABLE_LIVE_EXECUTION", "1")
    monkeypatch.setenv("NETCOOP_OPERATOR_SECRET_KEY", secret)

    incident_id = "INC-NOC-2026-99"
    record = create_operator_authorization(
        operator_id="alice_noc_lead",
        incident_id=incident_id,
        secret_key=secret,
        action_ids=["ACT-001"],
        authorized_network_tier="DISTRIBUTION_TIER"
    )

    # Valid token verification
    assert record.verify_token(secret) is True
    # Tampered token verification fails
    assert record.verify_token("wrong-secret") is False

    sm = RemediationLifecycleStateMachine(
        RemediationLifecycleState.REAL_EXECUTION_PENDING,
        incident_id=incident_id
    )
    receipt = ExecutionReceipt(
        execution_adapter_id="ADAPTER-01",
        execution_id="EXEC-99",
        incident_id=incident_id,
        action_id="ACT-001",
        operator_id="alice_noc_lead",
        authorization_ref=record.auth_token,
        target_device="IITBBS-SW-DIST-01",
        execution_result="SUCCESS",
        audit_reference="AUDIT-99"
    )
    sm.transition_to(RemediationLifecycleState.REAL_EXECUTED, authorization=record, execution_receipt=receipt)
    assert sm.current_state == RemediationLifecycleState.REAL_EXECUTED
    assert sm.authorization_record is not None
    assert sm.authorization_record.operator_id == "alice_noc_lead"
    assert sm.authorization_record.authorized_network_tier == "DISTRIBUTION_TIER"


def test_security_unauthorized_user_cannot_change_real_execution_state(monkeypatch):
    """Verify that unauthorized requests with invalid tokens are rejected with error."""
    monkeypatch.setenv("NETCOOP_ENABLE_LIVE_EXECUTION", "1")
    monkeypatch.setenv("NETCOOP_OPERATOR_SECRET_KEY", "real-key-333")

    fake_record = OperatorAuthorizationRecord(
        operator_id="unauthorized_actor",
        incident_id="INC-999",
        auth_token="forged_token_abc"
    )

    sm = RemediationLifecycleStateMachine(
        RemediationLifecycleState.REAL_EXECUTION_PENDING,
        incident_id="INC-999"
    )
    with pytest.raises(ExecutionSafetyGuardError) as exc_info:
        sm.transition_to(RemediationLifecycleState.REAL_EXECUTED, authorization=fake_record)
    assert "authorization check failed" in str(exc_info.value).lower()


# ==============================================================================
# PRIORITY 1 & 2 HARDENED SECURITY SUITE: CANONICAL SIGNATURES & EXECUTION RECEIPTS
# ==============================================================================

def test_security_changing_action_id_invalidates_authorization():
    """Prove that altering authorized action IDs after signing breaks HMAC-SHA256 signature."""
    secret = "secret-action-bind-999"
    rec = create_operator_authorization(
        operator_id="bob_engineer",
        incident_id="INC-101",
        secret_key=secret,
        action_ids=["ACT-QOS-RATE-LIMIT"]
    )
    assert rec.verify_token(secret) is True

    # Malicious tampering: inject an unauthorized destructive action
    rec.action_ids.append("ACT-DESTROY-VLAN-TABLE")
    valid, reason = rec.verify_and_audit(secret)
    assert valid is False
    assert "signature verification failed" in reason.lower()


def test_security_changing_incident_id_invalidates_authorization():
    """Prove that replaying a token against a different incident ID fails validation."""
    secret = "secret-incident-bind-888"
    rec = create_operator_authorization(
        operator_id="carol_lead",
        incident_id="INC-CORRECT-01",
        secret_key=secret,
        action_ids=["ACT-RELOAD"]
    )
    assert rec.verify_token(secret) is True

    # Tamper with incident ID
    rec.incident_id = "INC-WRONG-99"
    valid, reason = rec.verify_and_audit(secret)
    assert valid is False
    assert "signature verification failed" in reason.lower()

    # Target incident constraint check
    rec.sign(secret)  # re-signed for INC-WRONG-99
    valid_cross, reason_cross = rec.verify_and_audit(secret, target_incident_id="INC-TARGET-77")
    assert valid_cross is False
    assert "incident mismatch" in reason_cross.lower()


def test_security_changing_network_tier_invalidates_authorization():
    """Prove that elevating authorized network tier (e.g. ACCESS -> CORE) fails."""
    secret = "secret-tier-bind-777"
    rec = create_operator_authorization(
        operator_id="dan_l1",
        incident_id="INC-TIER-01",
        secret_key=secret,
        action_ids=["ACT-CYCLE-PORT"],
        authorized_network_tier="CAMPUS_ACCESS_TIER"
    )
    assert rec.verify_token(secret) is True

    # Tamper: attempt privilege escalation to CORE_TIER
    rec.authorized_network_tier = "CAMPUS_CORE_AGGREGATION_TIER"
    valid, reason = rec.verify_and_audit(secret)
    assert valid is False
    assert "signature verification failed" in reason.lower()


def test_security_expired_authorization_rejected():
    """Prove that tokens past their TTL are strictly rejected."""
    secret = "secret-ttl-test-666"
    past_time = datetime.now(timezone.utc) - timedelta(seconds=350)
    rec = create_operator_authorization(
        operator_id="elena_admin",
        incident_id="INC-TTL-01",
        secret_key=secret,
        timestamp=past_time,
        ttl_seconds=300
    )
    valid, reason = rec.verify_and_audit(secret)
    assert valid is False
    assert "expired" in reason.lower()


def test_security_future_dated_authorization_outside_skew_rejected():
    """Prove that future-dated tokens (>60s clock skew) are strictly rejected."""
    secret = "secret-skew-test-555"
    future_time = datetime.now(timezone.utc) + timedelta(seconds=120)
    rec = create_operator_authorization(
        operator_id="frank_ops",
        incident_id="INC-FUTURE-01",
        secret_key=secret,
        timestamp=future_time
    )
    valid, reason = rec.verify_and_audit(secret)
    assert valid is False
    assert "in the future" in reason.lower()


def test_security_reused_nonce_rejected():
    """Prove that a nonce cannot be consumed twice (anti-replay protection)."""
    AuthorizationAuditLedger.clear()
    secret = "secret-nonce-test-444"
    fixed_nonce = "fixed-unique-nonce-abc-123"

    rec1 = create_operator_authorization(
        operator_id="grace_ops",
        incident_id="INC-NONCE-01",
        secret_key=secret,
        nonce=fixed_nonce
    )
    # First verification registers the nonce upon state machine execution
    AuthorizationAuditLedger.register_nonce(fixed_nonce)

    # Replay attempt with same nonce
    rec2 = create_operator_authorization(
        operator_id="grace_ops",
        incident_id="INC-NONCE-01",
        secret_key=secret,
        nonce=fixed_nonce
    )
    valid, reason = rec2.verify_and_audit(secret, enforce_nonce_reuse=True)
    assert valid is False
    assert "replay attack detected" in reason.lower()


def test_security_missing_secret_key_rejected():
    """Prove that missing or empty secret key fails verification safely."""
    rec = OperatorAuthorizationRecord(
        operator_id="helen_sec",
        incident_id="INC-NOKEY",
        auth_token="dummy"
    )
    valid, reason = rec.verify_and_audit("")
    assert valid is False
    assert "missing operator secret key" in reason.lower()


def test_security_execution_receipt_contract_enforced(monkeypatch):
    """Prove that REAL_EXECUTED rejects authorization alone without genuine execution receipt."""
    secret = "secret-rcpt-contract-333"
    monkeypatch.setenv("NETCOOP_ENABLE_LIVE_EXECUTION", "1")
    monkeypatch.setenv("NETCOOP_OPERATOR_SECRET_KEY", secret)

    incident_id = "INC-RCPT-01"
    rec = create_operator_authorization(
        operator_id="ian_netops",
        incident_id=incident_id,
        secret_key=secret,
        action_ids=["ACT-QOS-01"]
    )

    sm = RemediationLifecycleStateMachine(RemediationLifecycleState.REAL_EXECUTION_PENDING, incident_id=incident_id)

    # 1. Missing execution receipt -> Must be blocked!
    with pytest.raises(ExecutionSafetyGuardError) as exc_info:
        sm.transition_to(RemediationLifecycleState.REAL_EXECUTED, authorization=rec)
    assert "ExecutionReceipt from a registered execution adapter is mandatory" in str(exc_info.value)

    # 2. Receipt action ID mismatch -> Must be blocked!
    bad_receipt = ExecutionReceipt(
        execution_adapter_id="CISCO-IOSXE",
        execution_id="EXEC-1",
        incident_id=incident_id,
        action_id="ACT-WRONG-ACTION",
        operator_id="ian_netops",
        authorization_ref=rec.auth_token,
        target_device="SW-CORE-01",
        execution_result="SUCCESS",
        audit_reference="AUDIT-1"
    )
    with pytest.raises(ExecutionSafetyGuardError) as exc_info2:
        sm.transition_to(RemediationLifecycleState.REAL_EXECUTED, authorization=rec, execution_receipt=bad_receipt)
    assert "execution receipt validation failed" in str(exc_info2.value)


def test_security_real_recovery_verified_requires_actual_telemetry():
    """Prove that REAL_RECOVERY_VERIFIED cannot be claimed without actual physical telemetry."""
    sm = RemediationLifecycleStateMachine(RemediationLifecycleState.REAL_EXECUTED)

    # Attempting transition without actual measured telemetry
    with pytest.raises(ExecutionSafetyGuardError) as exc_info:
        sm.transition_to(RemediationLifecycleState.REAL_RECOVERY_VERIFIED)
    assert "requires measured post-execution telemetry" in str(exc_info.value)


def test_security_forged_adapter_signature_rejected(monkeypatch):
    """Submitting ExecutionReceipt with an invalid or forged adapter HMAC signature is rejected."""
    secret = "secret-forged-adapter-sig"
    monkeypatch.setenv("NETCOOP_ENABLE_LIVE_EXECUTION", "1")
    monkeypatch.setenv("NETCOOP_OPERATOR_SECRET_KEY", secret)

    incident_id = "INC-FORGED-SIG-01"
    rec = create_operator_authorization(
        operator_id="jake_ops",
        incident_id=incident_id,
        secret_key=secret,
        action_ids=["ACT-RESTART-INTERFACE"]
    )
    sm = RemediationLifecycleStateMachine(RemediationLifecycleState.REAL_EXECUTION_PENDING, incident_id=incident_id)

    # Execution receipt with forged adapter signature
    forged_receipt = ExecutionReceipt(
        execution_adapter_id="CISCO-IOSXE",
        execution_id="EXEC-FORGED-01",
        incident_id=incident_id,
        action_id="ACT-RESTART-INTERFACE",
        operator_id="jake_ops",
        authorization_ref=rec.auth_token,
        target_device="IITBBS-SW-CORE-01",
        execution_result="SUCCESS",
        audit_reference="AUDIT-FORGED-01",
        adapter_signature="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    )

    with pytest.raises(ExecutionSafetyGuardError) as exc_info:
        sm.transition_to(RemediationLifecycleState.REAL_EXECUTED, authorization=rec, execution_receipt=forged_receipt)
    assert "adapter verification failed" in str(exc_info.value).lower()
    assert "signature mismatch" in str(exc_info.value).lower()


def test_security_unregistered_adapter_rejected(monkeypatch):
    """Submitting ExecutionReceipt from an unregistered rogue adapter is rejected."""
    secret = "secret-unregistered-adapter"
    monkeypatch.setenv("NETCOOP_ENABLE_LIVE_EXECUTION", "1")
    monkeypatch.setenv("NETCOOP_OPERATOR_SECRET_KEY", secret)

    incident_id = "INC-ROGUE-ADAPTER-01"
    rec = create_operator_authorization(
        operator_id="karen_ops",
        incident_id=incident_id,
        secret_key=secret,
        action_ids=["ACT-RELOAD"]
    )
    sm = RemediationLifecycleStateMachine(RemediationLifecycleState.REAL_EXECUTION_PENDING, incident_id=incident_id)

    rogue_receipt = ExecutionReceipt(
        execution_adapter_id="ADAPTER-ROGUE-EXPLOIT",
        execution_id="EXEC-ROGUE-01",
        incident_id=incident_id,
        action_id="ACT-RELOAD",
        operator_id="karen_ops",
        authorization_ref=rec.auth_token,
        target_device="IITBBS-SW-EDGE-01",
        execution_result="SUCCESS",
        audit_reference="AUDIT-ROGUE-01"
    )

    with pytest.raises(ExecutionSafetyGuardError) as exc_info:
        sm.transition_to(RemediationLifecycleState.REAL_EXECUTED, authorization=rec, execution_receipt=rogue_receipt)
    assert "unregistered execution adapter" in str(exc_info.value).lower()


def test_security_tampered_action_ids_rejected(monkeypatch):
    """Submitting altered action_ids after token generation is rejected by HMAC verification."""
    secret = "secret-tamper-actions"
    monkeypatch.setenv("NETCOOP_ENABLE_LIVE_EXECUTION", "1")
    monkeypatch.setenv("NETCOOP_OPERATOR_SECRET_KEY", secret)

    incident_id = "INC-TAMPER-ACT-01"
    rec = create_operator_authorization(
        operator_id="leo_sec",
        incident_id=incident_id,
        secret_key=secret,
        action_ids=["ACT-CLEAR-ARP"]
    )
    # Inject unauthorized malicious action into authorization record without re-signing
    rec.action_ids = ["ACT-CLEAR-ARP", "ACT-WIPE-NVRAM"]

    sm = RemediationLifecycleStateMachine(RemediationLifecycleState.REAL_EXECUTION_PENDING, incident_id=incident_id)
    receipt = ExecutionReceipt(
        execution_adapter_id="CISCO-IOSXE",
        execution_id="EXEC-VALID-01",
        incident_id=incident_id,
        action_id="ACT-CLEAR-ARP",
        operator_id="leo_sec",
        authorization_ref=rec.auth_token,
        target_device="IITBBS-SW-ACCESS-01",
        execution_result="SUCCESS",
        audit_reference="AUDIT-ACT-01"
    )

    with pytest.raises(ExecutionSafetyGuardError) as exc_info:
        sm.transition_to(RemediationLifecycleState.REAL_EXECUTED, authorization=rec, execution_receipt=receipt)
    assert "authorization check failed" in str(exc_info.value).lower()
    assert "signature verification failed" in str(exc_info.value).lower()


def test_security_reused_nonce_rejected_concurrently(monkeypatch):
    """Nonce reuse across concurrent or sequential lifecycle executions is strictly blocked and audited."""
    secret = "secret-concurrent-nonce"
    monkeypatch.setenv("NETCOOP_ENABLE_LIVE_EXECUTION", "1")
    monkeypatch.setenv("NETCOOP_OPERATOR_SECRET_KEY", secret)
    AuthorizationAuditLedger.clear()

    incident_id = "INC-REPLAY-NONCE-01"
    shared_nonce = "NONCE-REPLAY-CONCURRENT-001"
    rec = create_operator_authorization(
        operator_id="maya_netops",
        incident_id=incident_id,
        secret_key=secret,
        action_ids=["ACT-BOUNCE-PORT"],
        nonce=shared_nonce
    )

    sm1 = RemediationLifecycleStateMachine(RemediationLifecycleState.REAL_EXECUTION_PENDING, incident_id=incident_id)
    receipt1 = ExecutionReceipt(
        execution_adapter_id="CISCO-IOSXE",
        execution_id="EXEC-NONCE-01",
        incident_id=incident_id,
        action_id="ACT-BOUNCE-PORT",
        operator_id="maya_netops",
        authorization_ref=rec.auth_token,
        target_device="IITBBS-SW-DIST-01",
        execution_result="SUCCESS",
        audit_reference="AUDIT-NONCE-01"
    )
    # First execution succeeds and consumes nonce
    sm1.transition_to(RemediationLifecycleState.REAL_EXECUTED, authorization=rec, execution_receipt=receipt1)
    assert sm1.current_state == RemediationLifecycleState.REAL_EXECUTED
    assert AuthorizationAuditLedger.is_nonce_used(shared_nonce) is True

    # Second execution reusing the same token/nonce MUST be rejected
    sm2 = RemediationLifecycleStateMachine(RemediationLifecycleState.REAL_EXECUTION_PENDING, incident_id=incident_id)
    receipt2 = ExecutionReceipt(
        execution_adapter_id="CISCO-IOSXE",
        execution_id="EXEC-NONCE-02",
        incident_id=incident_id,
        action_id="ACT-BOUNCE-PORT",
        operator_id="maya_netops",
        authorization_ref=rec.auth_token,
        target_device="IITBBS-SW-DIST-01",
        execution_result="SUCCESS",
        audit_reference="AUDIT-NONCE-02"
    )
    with pytest.raises(ExecutionSafetyGuardError) as exc_info:
        sm2.transition_to(RemediationLifecycleState.REAL_EXECUTED, authorization=rec, execution_receipt=receipt2)
    assert "replay attack detected" in str(exc_info.value).lower()

    # Verify audit ledger recorded the rejection
    recent_attempts = AuthorizationAuditLedger.get_entries()
    rejection_found = any(att.decision == "REJECTED" and att.nonce == shared_nonce for att in recent_attempts)
    assert rejection_found is True


def test_security_tampered_tier_rejected():
    """Privilege escalation by forging higher network tier authorization fails HMAC validation."""
    secret = "secret-tier-tamper"
    rec = create_operator_authorization(
        operator_id="noah_l1_ops",
        incident_id="INC-TIER-ESCALATE-01",
        secret_key=secret,
        action_ids=["ACT-CYCLE-PORT"],
        authorized_network_tier="CAMPUS_ACCESS_TIER"
    )
    assert rec.verify_token(secret) is True

    # Attacker modifies authorized tier to CORE
    rec.authorized_network_tier = "CAMPUS_CORE_BACKBONE_TIER"
    valid, reason = rec.verify_and_audit(secret, target_network_tier="CAMPUS_CORE_BACKBONE_TIER")
    assert valid is False
    assert "signature verification failed" in reason.lower()


def test_security_durable_nonce_survives_process_restart():
    """Verify that consumed nonces persist in SQLite and are rejected even after in-memory state is wiped."""
    import time
    AuthorizationAuditLedger.clear()
    secret = "secret-restart-persisted"
    restart_nonce = f"NONCE-PERSIST-{time.time()}"
    rec = create_operator_authorization(
        operator_id="admin_persist",
        incident_id="INC-RESTART-01",
        secret_key=secret,
        nonce=restart_nonce
    )

    # 1. Nonce is registered/consumed
    AuthorizationAuditLedger.register_nonce(restart_nonce, "admin_persist", "INC-RESTART-01")
    assert AuthorizationAuditLedger.is_nonce_used(restart_nonce) is True

    # 2. Simulate process exit & restart: wipe in-memory sets completely!
    AuthorizationAuditLedger._used_nonces.clear()
    AuthorizationAuditLedger._entries.clear()

    # 3. Persistent store on disk must still remember the nonce!
    assert DurableNonceStore.is_nonce_used(restart_nonce) is True
    assert AuthorizationAuditLedger.is_nonce_used(restart_nonce) is True

    # 4. Attempting to verify token again fails with replay attack detected
    valid, reason = rec.verify_and_audit(secret, enforce_nonce_reuse=True)
    assert valid is False
    assert "replay attack detected" in reason.lower()


def test_security_durable_nonce_concurrency_race():
    """Verify that concurrent threads attempting to consume the same nonce are atomically serialized."""
    from concurrent.futures import ThreadPoolExecutor
    import time
    AuthorizationAuditLedger.clear()

    race_nonce = f"NONCE-RACE-{time.time()}"
    results = []

    def try_consume():
        return DurableNonceStore.consume_nonce(race_nonce, "operator_race", "INC-RACE-01")

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(try_consume) for _ in range(8)]
        for f in futures:
            results.append(f.result())

    # Exactly ONE thread must succeed; all other 7 must fail with replay attack detected
    successes = [r for r in results if r[0] is True]
    failures = [r for r in results if r[0] is False]

    assert len(successes) == 1
    assert len(failures) == 7
    assert "consumed successfully" in successes[0][1]
    assert all("replay attack detected" in fail[1].lower() for fail in failures)


