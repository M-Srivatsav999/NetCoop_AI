"""Remediation Lifecycle State Machine and Execution Safety Guard Tests.

Verifies:
1. Complete 10-state lifecycle progression using dynamic HMAC-based operator authorization.
2. Rejection of illegal transitions via InvalidStateTransitionError.
3. Execution safety guard: live mutation disabled by default and requires valid operator token.
4. Failure and rollback recommendation pathway.
"""

from datetime import datetime, timezone
import pytest
from core.remediation import (
    ExecutionReceipt,
    ExecutionSafetyGuardError,
    InvalidStateTransitionError,
    OperatorAuthorizationRecord,
    RemediationLifecycleState,
    RemediationLifecycleStateMachine,
    RemediationSimulator,
    generate_operator_token,
)
from protocol.models import CanonicalMetrics, CanonicalTelemetry


def test_remediation_lifecycle_valid_complete_progression(monkeypatch):
    """Verify valid step-by-step lifecycle flow from recommendation to verified execution."""
    test_secret = "test-ephemeral-secret-key-12345"
    monkeypatch.setenv("NETCOOP_ENABLE_LIVE_EXECUTION", "1")
    monkeypatch.setenv("NETCOOP_OPERATOR_SECRET_KEY", test_secret)

    sm = RemediationLifecycleStateMachine(RemediationLifecycleState.RECOMMENDED, incident_id="INC-TEST-001")

    # 1. RECOMMENDED -> SIMULATED
    assert sm.transition_to(RemediationLifecycleState.SIMULATED) == RemediationLifecycleState.SIMULATED

    # 2. SIMULATED -> SIMULATED_RECOVERY_VERIFIED
    assert sm.transition_to(RemediationLifecycleState.SIMULATED_RECOVERY_VERIFIED) == RemediationLifecycleState.SIMULATED_RECOVERY_VERIFIED

    # 3. SIMULATED_RECOVERY_VERIFIED -> APPROVAL_PENDING
    assert sm.transition_to(RemediationLifecycleState.APPROVAL_PENDING) == RemediationLifecycleState.APPROVAL_PENDING

    # 4. APPROVAL_PENDING -> APPROVED
    assert sm.transition_to(RemediationLifecycleState.APPROVED) == RemediationLifecycleState.APPROVED

    # 5. APPROVED -> REAL_EXECUTION_PENDING
    assert sm.transition_to(RemediationLifecycleState.REAL_EXECUTION_PENDING) == RemediationLifecycleState.REAL_EXECUTION_PENDING

    # 6. REAL_EXECUTION_PENDING -> REAL_EXECUTED
    # Priority 2 Requirement: prove authorization alone is rejected without genuine execution receipt
    auth_token = generate_operator_token(
        "NOC_OPERATOR", "INC-TEST-001", test_secret, action_ids=["ACT-DEFAULT"]
    )
    with pytest.raises(ExecutionSafetyGuardError) as exc_receipt:
        sm.transition_to(RemediationLifecycleState.REAL_EXECUTED, authorization=auth_token)
    assert "ExecutionReceipt from a registered execution adapter is mandatory" in str(exc_receipt.value)

    # Provide genuine execution receipt from registered adapter
    receipt = ExecutionReceipt(
        execution_adapter_id="CISCO-IOSXE-SSH-ADAPTER",
        execution_id="EXEC-777",
        incident_id="INC-TEST-001",
        action_id="ACT-DEFAULT",
        operator_id="NOC_OPERATOR",
        authorization_ref=auth_token,
        target_device="IITBBS-SW-MHR-01",
        execution_result="SUCCESS",
        adapter_response={"exit_code": 0, "status": "CONFIG_APPLIED"},
        audit_reference="AUDIT-LOG-777"
    )
    assert sm.transition_to(
        RemediationLifecycleState.REAL_EXECUTED,
        authorization=auth_token,
        execution_receipt=receipt
    ) == RemediationLifecycleState.REAL_EXECUTED

    # 7. REAL_EXECUTED -> REAL_RECOVERY_VERIFIED
    # Priority 2 Requirement: prove real recovery verification requires actual post-execution telemetry!
    with pytest.raises(ExecutionSafetyGuardError) as exc_telemetry:
        sm.transition_to(RemediationLifecycleState.REAL_RECOVERY_VERIFIED)
    assert "requires measured post-execution telemetry" in str(exc_telemetry.value)

    # Provide measured nominal physical telemetry
    post_telemetry = [
        CanonicalTelemetry(
            device_id="IITBBS-SW-MHR-01",
            timestamp=datetime.now(timezone.utc),
            metrics=CanonicalMetrics(
                latency_ms=18.0,
                packet_loss_pct=0.0,
                interface_errors=0
            )
        )
    ]
    assert sm.transition_to(
        RemediationLifecycleState.REAL_RECOVERY_VERIFIED,
        post_execution_telemetry=post_telemetry
    ) == RemediationLifecycleState.REAL_RECOVERY_VERIFIED

    # Check history contains all states
    assert len(sm.state_history) == 8


def test_remediation_execution_safety_guard_blocks_unauthorized(monkeypatch):
    """Verify ExecutionSafetyGuardError is raised when trying to execute live without key."""
    # 1. Live execution disabled by default
    monkeypatch.delenv("NETCOOP_ENABLE_LIVE_EXECUTION", raising=False)
    sm1 = RemediationLifecycleStateMachine(RemediationLifecycleState.REAL_EXECUTION_PENDING, incident_id="INC-TEST-002")
    with pytest.raises(ExecutionSafetyGuardError) as exc_info1:
        sm1.transition_to(RemediationLifecycleState.REAL_EXECUTED)
    assert "Live production mutation is strictly disabled in safe simulation-only mode" in str(exc_info1.value)

    # 2. Live execution enabled but secret key missing
    monkeypatch.setenv("NETCOOP_ENABLE_LIVE_EXECUTION", "1")
    monkeypatch.delenv("NETCOOP_OPERATOR_SECRET_KEY", raising=False)
    sm2 = RemediationLifecycleStateMachine(RemediationLifecycleState.REAL_EXECUTION_PENDING, incident_id="INC-TEST-002")
    with pytest.raises(ExecutionSafetyGuardError) as exc_info2:
        sm2.transition_to(RemediationLifecycleState.REAL_EXECUTED)
    assert "NETCOOP_OPERATOR_SECRET_KEY is not configured" in str(exc_info2.value)

    # 3. Secret key set but invalid authorization token provided
    monkeypatch.setenv("NETCOOP_OPERATOR_SECRET_KEY", "real-secret-key-123")
    sm3 = RemediationLifecycleStateMachine(RemediationLifecycleState.REAL_EXECUTION_PENDING, incident_id="INC-TEST-002")
    with pytest.raises(ExecutionSafetyGuardError) as exc_info3:
        sm3.transition_to(RemediationLifecycleState.REAL_EXECUTED, authorization="INVALID-WRONG-TOKEN")
    assert "ExecutionSafetyGuard blocked transition" in str(exc_info3.value)


def test_remediation_invalid_transitions_rejected():
    """Verify illegal jumps across states raise InvalidStateTransitionError."""
    sm = RemediationLifecycleStateMachine(RemediationLifecycleState.RECOMMENDED)

    # Cannot jump directly from RECOMMENDED to REAL_EXECUTED
    with pytest.raises(InvalidStateTransitionError):
        sm.transition_to(RemediationLifecycleState.REAL_EXECUTED)

    # Move to SIMULATED
    sm.transition_to(RemediationLifecycleState.SIMULATED)

    # Cannot jump from SIMULATED directly to REAL_RECOVERY_VERIFIED
    with pytest.raises(InvalidStateTransitionError):
        sm.transition_to(RemediationLifecycleState.REAL_RECOVERY_VERIFIED)


def test_remediation_failure_and_rollback_flow(monkeypatch):
    """Verify failure during execution triggers rollback recommendation."""
    test_secret = "test-secret-456"
    monkeypatch.setenv("NETCOOP_ENABLE_LIVE_EXECUTION", "1")
    monkeypatch.setenv("NETCOOP_OPERATOR_SECRET_KEY", test_secret)

    sm = RemediationLifecycleStateMachine(RemediationLifecycleState.REAL_EXECUTION_PENDING, incident_id="INC-FAIL-01")
    auth_token = generate_operator_token("NOC_OPERATOR", "INC-FAIL-01", test_secret, action_ids=["ACT-DEFAULT"])
    receipt = ExecutionReceipt(
        execution_adapter_id="ADAPTER-01",
        execution_id="EXEC-FAIL-01",
        incident_id="INC-FAIL-01",
        action_id="ACT-DEFAULT",
        operator_id="NOC_OPERATOR",
        authorization_ref=auth_token,
        target_device="SW-CORE",
        execution_result="SUCCESS",
        audit_reference="AUDIT-1"
    )
    sm.transition_to(RemediationLifecycleState.REAL_EXECUTED, authorization=auth_token, execution_receipt=receipt)

    # Execution fails post-check
    sm.transition_to(RemediationLifecycleState.FAILED)
    assert sm.current_state == RemediationLifecycleState.FAILED

    # Trigger rollback recommendation
    sm.transition_to(RemediationLifecycleState.ROLLBACK_RECOMMENDED)
    assert sm.current_state == RemediationLifecycleState.ROLLBACK_RECOMMENDED
