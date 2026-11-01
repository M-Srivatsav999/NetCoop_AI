"""Integration and endpoint validation test suite for Operations Dashboard API.

Validates:
- GET /api/health (direct & routed)
- GET /api/overview
- GET /api/topology
- GET /api/agent-activity
- POST /api/diagnose
- POST /api/simulate-remediation
- POST /api/verify-recovery
- GET / (UI Dashboard HTML delivery)
"""

from __future__ import annotations

import pytest
from web.server import (
    app,
    get_health,
    get_overview,
    get_topology,
    get_agent_activity,
    run_diagnosis,
    simulate_remediation,
    verify_recovery,
    serve_dashboard,
    DiagnoseRequest,
    RemediationSimulateRequest,
    VerifyRecoveryRequest,
)


def test_api_health():
    """Verify health endpoint returns operational status and loaded calibration model."""
    data = get_health()
    assert data["status"] == "HEALTHY"
    assert "TelemetryAgent" in data["active_agents"]
    assert "ArbiterAgent" in data["active_agents"]
    assert data["calibration_model_loaded"] is True
    assert "V1" in data["supported_schemas"]


def test_api_overview():
    """Verify overview endpoint returns campus metrics, alerts, and inventory."""
    data = get_overview()
    assert "campus_health_score" in data
    assert data["campus_health_score"] >= 90.0
    assert data["total_monitored_devices"] >= 10
    assert len(data["inventory"]) >= 10
    assert len(data["active_alerts"]) >= 1
    assert data["inventory"][0]["role"] != ""


def test_api_topology():
    """Verify topology endpoint exports nodes, links, and core reference."""
    data = get_topology()
    assert data["topology_id"] == "IIT-BBS-CAMPUS-CORE-v4"
    assert len(data["nodes"]) >= 10
    assert len(data["links"]) >= 10
    assert data["core_node"] in ("CORE-SW-01", "SW-CORE-01")


def test_api_agent_activity():
    """Verify agent activity endpoint returns message traces and peer reviews."""
    data = get_agent_activity()
    assert "agent_messages" in data or "audit_entries" in data


def test_api_diagnose():
    """Verify diagnose endpoint runs end-to-end orchestration and returns evidence graph."""
    req = DiagnoseRequest(
        incident_id="INC-DASH-TEST-01",
        telemetry=[
            {
                "device_id": "BLDG-SW-ENG",
                "latency_ms": 190.0,
                "packet_loss_pct": 5.0,
                "queue_drops": 160,
                "interface_errors": 0
            }
        ]
    )
    data = run_diagnosis(req)
    assert data["report"]["suspected_root_cause"] == "LINK_CONGESTION"
    assert data["report"]["confidence"] > 0.0
    assert "evidence_graph" in data
    assert len(data["evidence_graph"]["nodes"]) >= 3
    assert len(data["evidence_graph"]["cytoscape_elements"]) >= 3


def test_api_simulate_remediation():
    """Verify remediation simulation projects before/after KPIs and generates dry-run CLI."""
    req = RemediationSimulateRequest(
        incident_id="INC-DASH-TEST-02",
        root_cause="LINK_CONGESTION",
        target_devices=["BLDG-SW-ENG"]
    )
    data = simulate_remediation(req)
    assert data["status"] == "SIMULATED_SUCCESS"
    assert len(data["cli_commands_dry_run"]) >= 1
    assert "projected_kpis" in data


def test_api_verify_recovery():
    """Verify recovery endpoint validates post-remediation physical telemetry counters."""
    req = VerifyRecoveryRequest(
        incident_id="INC-DASH-TEST-03",
        operator_token="TEST-OPERATOR-HMAC-TOKEN",
        target_devices=["BLDG-SW-ENG"]
    )
    data = verify_recovery(req)
    assert data["verification_status"] == "REAL_RECOVERY_VERIFIED"
    assert data["telemetry_counters"]["active_alarms_cleared"] is True


def test_dashboard_ui_html_served():
    """Verify that serve_dashboard() returns the 5-view professional NOC dashboard HTML."""
    response = serve_dashboard()
    assert response.status_code == 200
    html_text = response.body.decode("utf-8")
    assert "NetCoop AI Operations Console" in html_text
    assert "Topology Explorer" in html_text
    assert "Honeycomb Multi-Agent Dialogue" in html_text
    assert "Operator Approval Gate" in html_text


def test_api_remediation_authorize_and_execute_lifecycle():
    """Verify cryptographic authorization, atomic execution receipt, and anti-replay protection."""
    from web.server import (
        authorize_remediation_token,
        execute_remediation,
        AuthorizeRemediationRequest,
        ExecuteRemediationRequest,
    )
    auth_req = AuthorizeRemediationRequest(
        operator_id="NOC-ADMIN-01",
        incident_id="INC-EXEC-TEST-01",
        action_ids=["ACT-QOS-01", "ACT-BUFF-02"],
        secret_key="TEST-OPERATOR-SECRET-KEY-123456"
    )
    auth_data = authorize_remediation_token(auth_req)
    assert auth_data["operator_id"] == "NOC-ADMIN-01"
    assert "auth_token" in auth_data
    assert "nonce" in auth_data

    # Execute remediation
    exec_req = ExecuteRemediationRequest(
        auth_record=auth_data,
        secret_key="TEST-OPERATOR-SECRET-KEY-123456",
        execution_mode="SIMULATED"
    )
    exec_data = execute_remediation(exec_req)
    assert exec_data["status"] == "EXECUTED_SUCCESS"
    assert "receipt_id" in exec_data
    assert exec_data["execution_mode"] == "SIMULATED"
    assert exec_data["replay_protection"] == "ACTIVE"

    # Replay attack: Re-using the same consumed nonce must fail
    with pytest.raises(Exception) as exc:
        execute_remediation(exec_req)
    assert "Anti-replay" in str(exc.value) or "consumed" in str(exc.value) or "409" in str(exc.value)


def test_api_verify_recovery_truthfulness_modes():
    """Verify that recovery verification distinguishes measured telemetry from missing data."""
    # 1. Missing telemetry returns NOT_VERIFIED
    req_missing = VerifyRecoveryRequest(
        incident_id="INC-REC-TEST-MISSING",
        operator_token="LIVE-OPERATOR-TOKEN",
        target_devices=["BLDG-SW-ENG"],
        post_action_telemetry=None
    )
    data_missing = verify_recovery(req_missing)
    assert data_missing["verification_status"] == "NOT_VERIFIED"
    assert data_missing["is_real_recovery_measured"] is False

    # 2. Measured telemetry with lingering packet loss returns RECOVERY_FAILED_ANOMALIES_PERSIST
    req_failing = VerifyRecoveryRequest(
        incident_id="INC-REC-TEST-FAIL",
        operator_token="LIVE-OPERATOR-TOKEN",
        target_devices=["BLDG-SW-ENG"],
        post_action_telemetry=[
            {
                "device_id": "BLDG-SW-ENG",
                "metrics": {
                    "latency_ms": 120.0,
                    "packet_loss_pct": 8.0,
                    "queue_drops": 45
                }
            }
        ]
    )
    data_failing = verify_recovery(req_failing)
    assert data_failing["verification_status"] == "RECOVERY_FAILED_ANOMALIES_PERSIST"
    assert data_failing["telemetry_counters"]["active_alarms_cleared"] is False

    # 3. Measured telemetry with nominal counters returns REAL_RECOVERY_VERIFIED
    req_nominal = VerifyRecoveryRequest(
        incident_id="INC-REC-TEST-SUCCESS",
        operator_token="LIVE-OPERATOR-TOKEN",
        target_devices=["BLDG-SW-ENG"],
        post_action_telemetry=[
            {
                "device_id": "BLDG-SW-ENG",
                "metrics": {
                    "latency_ms": 12.5,
                    "packet_loss_pct": 0.0,
                    "queue_drops": 0
                }
            }
        ]
    )
    data_nominal = verify_recovery(req_nominal)
    assert data_nominal["verification_status"] == "REAL_RECOVERY_VERIFIED"
    assert data_nominal["telemetry_counters"]["active_alarms_cleared"] is True
    assert data_nominal["is_real_recovery_measured"] is True
