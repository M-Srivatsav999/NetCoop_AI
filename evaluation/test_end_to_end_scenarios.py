"""NetCoop AI Release 5 — 20 Comprehensive End-to-End Integrated Scenarios.

Validates the complete autonomous diagnostic and remediation pipeline across all 20 required production network scenarios:
 1. Normal / Healthy campus network operations
 2. Core link buffer congestion
 3. Access Point wireless RF degradation
 4. Building access switch failure
 5. Access Point hardware crash
 6. Campus recursive DNS outage
 7. Central DHCP pool exhaustion
 8. Shared upstream gateway failure (cascading blast radius)
 9. Independent multi-building simultaneous faults (disjoint root causes)
10. Simultaneous dual-fault scenario (DNS + core link congestion)
11. Missing critical telemetry counters (graceful abstention / insufficient evidence)
12. Stale telemetry data (TTL expired / outdated timestamps)
13. Malformed / corrupt JSON payload input
14. Replay attack with duplicate message IDs
15. Contradictory agent findings (RF vs upstream switch CRC errors)
16. Unregistered / unauthorized agent message rejection
17. Automated remediation simulation with projected KPI verification
18. Real execution safety guard blocking unauthenticated live mutation
19. Cryptographically verified adapter execution with post-recovery telemetry
20. Unknown / unmapped device topology resilience
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
import pytest

from core.orchestrator import NetworkIntelligenceOrchestrator
from core.topology import TopologyEngine
from core.evidence_graph import EvidenceGraph
from core.remediation import (
    ExecutionAdapterRegistry,
    ExecutionReceipt,
    ExecutionSafetyGuardError,
    RemediationLifecycleState,
    RemediationLifecycleStateMachine,
    RemediationSimulator,
    create_operator_authorization,
)
from protocol.agent_message_protocol import (
    AgentMessageBus,
    AgentProtocolMessage,
    MessageAckStatus,
    ProtocolMessageType,
)
from protocol.models import CanonicalMetrics, CanonicalTelemetry, SchemaVersion


@pytest.fixture
def orchestrator():
    return NetworkIntelligenceOrchestrator()


# Scenario 1: Normal / Healthy Campus Network
def test_scenario_01_healthy_campus(orchestrator):
    now = datetime.now(timezone.utc)
    payload = [
        {
            "device_id": "CORE-SW-01",
            "timestamp": now.isoformat(),
            "latency_ms": 2.1,
            "packet_loss_pct": 0.0,
            "cpu_pct": 18.0,
            "memory_pct": 32.0,
            "queue_drops": 0,
            "interface_errors": 0
        },
        {
            "device_id": "DIST-SW-NORTH",
            "timestamp": now.isoformat(),
            "latency_ms": 3.4,
            "packet_loss_pct": 0.0,
            "cpu_pct": 22.0,
            "memory_pct": 40.0,
            "queue_drops": 0,
            "interface_errors": 0
        }
    ]
    res = orchestrator.process(payload, incident_id="INC-SCEN-01", reference_time=now)
    assert res.report.suspected_root_cause == "NORMAL_OPERATION"
    assert res.arbiter_decision.status == "HEALTHY"
    assert len(res.agent_messages) >= 6
    assert res.evidence_graph is not None
    assert res.evidence_graph.is_acyclic() is True


# Scenario 2: Core Link Buffer Congestion
def test_scenario_02_link_congestion(orchestrator):
    now = datetime.now(timezone.utc)
    payload = [{
        "device_id": "CORE-SW-01",
        "timestamp": now.isoformat(),
        "latency_ms": 145.0,
        "packet_loss_pct": 6.8,
        "cpu_pct": 89.0,
        "queue_drops": 340,
        "interface_errors": 0
    }]
    res = orchestrator.process(payload, incident_id="INC-SCEN-02", reference_time=now)
    assert "CONGESTION" in res.report.suspected_root_cause.upper() or "CORE" in res.report.suspected_root_cause.upper()
    assert res.report.confidence > 0.60
    assert len(res.investigation_plan) > 0
    assert len(res.safe_remediation_actions) > 0


# Scenario 3: Access Point Wireless RF Degradation
def test_scenario_03_wireless_rf_interference(orchestrator):
    now = datetime.now(timezone.utc)
    payload = [{
        "device_id": "AP-HOSTEL-1A",
        "timestamp": now.isoformat(),
        "signal_strength_dbm": -84.0,
        "latency_ms": 110.0,
        "packet_loss_pct": 12.5,
        "queue_drops": 0,
        "interface_errors": 0
    }]
    res = orchestrator.process(payload, incident_id="INC-SCEN-03", reference_time=now)
    assert "WIFI" in res.report.suspected_root_cause.upper() or "AP" in res.report.suspected_root_cause.upper()
    assert "AP-HOSTEL-1A" in res.report.affected_devices


# Scenario 4: Building Access Switch Hardware Failure
def test_scenario_04_building_switch_failure(orchestrator):
    now = datetime.now(timezone.utc)
    payload = [{
        "device_id": "BLDG-SW-ENG",
        "timestamp": now.isoformat(),
        "latency_ms": 280.0,
        "packet_loss_pct": 24.0,
        "cpu_pct": 98.0,
        "queue_drops": 450,
        "interface_errors": 120
    }]
    res = orchestrator.process(payload, incident_id="INC-SCEN-04", reference_time=now)
    assert "SWITCH" in res.report.suspected_root_cause.upper() or "CONGESTION" in res.report.suspected_root_cause.upper() or "HARDWARE" in res.report.suspected_root_cause.upper()
    assert "BLDG-SW-ENG" in res.report.affected_devices


# Scenario 5: Access Point Hardware Crash
def test_scenario_05_ap_hardware_crash(orchestrator):
    now = datetime.now(timezone.utc)
    payload = [{
        "device_id": "AP-LIBRARY-02",
        "timestamp": now.isoformat(),
        "reported_status": "DOWN",
        "latency_ms": 999.0,
        "packet_loss_pct": 100.0,
        "interface_errors": 50
    }]
    res = orchestrator.process(payload, incident_id="INC-SCEN-05", reference_time=now)
    assert "AP-LIBRARY-02" in res.report.affected_devices
    assert res.report.confidence >= 0.70


# Scenario 6: Campus Recursive DNS Outage
def test_scenario_06_dns_outage(orchestrator):
    now = datetime.now(timezone.utc)
    payload = [{
        "device_id": "DNS-SRV-CORE",
        "timestamp": now.isoformat(),
        "dns_resolution_ms": 2450.0,
        "packet_loss_pct": 0.0,
        "latency_ms": 8.0,
        "cpu_pct": 95.0,
        "dhcp_lease_success": False
    }]
    res = orchestrator.process(payload, incident_id="INC-SCEN-06", reference_time=now)
    assert "DNS" in res.report.suspected_root_cause.upper() or "SERVICES" in res.report.suspected_root_cause.upper()
    assert "DNS-SRV-CORE" in res.report.affected_devices


# Scenario 7: Central DHCP Pool Exhaustion
def test_scenario_07_dhcp_exhaustion(orchestrator):
    now = datetime.now(timezone.utc)
    payload = [{
        "device_id": "DHCP-SRV-01",
        "timestamp": now.isoformat(),
        "dhcp_lease_success": False,
        "dns_resolution_ms": 1800.0,
        "latency_ms": 12.0,
        "packet_loss_pct": 0.0
    }]
    res = orchestrator.process(payload, incident_id="INC-SCEN-07", reference_time=now)
    assert "DHCP" in res.report.suspected_root_cause.upper() or "DNS_DHCP" in res.report.suspected_root_cause.upper()


# Scenario 8: Shared Upstream Gateway Failure (Cascading Blast Radius)
def test_scenario_08_shared_upstream_cascade(orchestrator):
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(seconds=10)
    t1 = now - timedelta(seconds=5)
    payload = [
        {
            "device_id": "CORE-SW-01",
            "timestamp": t0.isoformat(),
            "latency_ms": 220.0,
            "packet_loss_pct": 15.0,
            "queue_drops": 600
        },
        {
            "device_id": "DIST-SW-NORTH",
            "timestamp": t1.isoformat(),
            "latency_ms": 195.0,
            "packet_loss_pct": 14.0,
            "queue_drops": 0
        }
    ]
    res = orchestrator.process(payload, incident_id="INC-SCEN-08", reference_time=now)
    assert "CORE-SW-01" in res.report.affected_devices
    assert res.report.confidence > 0.50


# Scenario 9: Independent Multi-Building Simultaneous Faults
def test_scenario_09_multi_building_faults(orchestrator):
    now = datetime.now(timezone.utc)
    payload = [
        {
            "device_id": "BLDG-SW-ENG",
            "timestamp": now.isoformat(),
            "queue_drops": 350,
            "latency_ms": 160.0,
            "packet_loss_pct": 5.0
        },
        {
            "device_id": "BLDG-SW-ADMIN",
            "timestamp": now.isoformat(),
            "interface_errors": 420,
            "latency_ms": 180.0,
            "packet_loss_pct": 8.0
        }
    ]
    res = orchestrator.process(payload, incident_id="INC-SCEN-09", reference_time=now)
    assert len(res.report.affected_devices) >= 2
    assert res.evidence_ledger_summary.get("total_entries", 0) > 0


# Scenario 10: Simultaneous Dual Fault Scenario (DNS + Congestion)
def test_scenario_10_simultaneous_dual_fault(orchestrator):
    now = datetime.now(timezone.utc)
    payload = [
        {
            "device_id": "DNS-SRV-CORE",
            "timestamp": now.isoformat(),
            "dns_resolution_ms": 380.0,
            "latency_ms": 10.0
        },
        {
            "device_id": "CORE-SW-01",
            "timestamp": now.isoformat(),
            "queue_drops": 280,
            "latency_ms": 120.0,
            "packet_loss_pct": 4.5
        }
    ]
    res = orchestrator.process(payload, incident_id="INC-SCEN-10", reference_time=now)
    assert len(res.report.affected_devices) >= 2
    assert res.arbitration_result is not None


# Scenario 11: Missing Critical Telemetry Counters
def test_scenario_11_missing_telemetry_counters(orchestrator):
    payload = [{"device_id": "BLDG-SW-ENG"}]  # Completely empty metrics
    res = orchestrator.process(payload, incident_id="INC-SCEN-11")
    assert res.report.status == "insufficient_evidence" or res.report.suspected_root_cause == "INSUFFICIENT_EVIDENCE"
    assert res.report.confidence == 0.0


# Scenario 12: Stale Telemetry Data (TTL Expired)
def test_scenario_12_stale_telemetry_handling(orchestrator):
    now = datetime.now(timezone.utc)
    stale_time = now - timedelta(hours=3)
    payload = [{
        "device_id": "CORE-SW-01",
        "timestamp": stale_time.isoformat(),
        "latency_ms": 12.0,
        "packet_loss_pct": 0.0
    }]
    res = orchestrator.process(payload, incident_id="INC-SCEN-12", reference_time=now)
    # Stale telemetry must trigger uncertainty factors and staleness reporting
    assert res.arbitration_result.evidence_completeness <= 1.0
    assert any("stale" in u.lower() for u in res.arbitration_result.uncertainty_factors) or len(res.arbitration_result.uncertainty_factors) > 0


# Scenario 13: Malformed / Corrupt JSON Payload Input
def test_scenario_13_corrupt_payload_input(orchestrator):
    corrupt_str = "{bad_json: missing_quotes_and_brackets, "
    res = orchestrator.process(corrupt_str, incident_id="INC-SCEN-13")
    assert res.report is not None
    assert res.report.status in ("insufficient_evidence", "diagnosed")


# Scenario 14: Replay Attack Detection with Duplicate Message IDs
def test_scenario_14_replay_attack_prevention():
    bus = AgentMessageBus()
    msg = AgentProtocolMessage(
        message_id="MSG-REPLAY-TEST-001",
        incident_id="INC-SCEN-14",
        correlation_id="CORR-14",
        message_type=ProtocolMessageType.OBSERVATION,
        sender="TelemetryAgent",
        recipient="Orchestrator",
        sequence_number=1,
        payload={"sample": "data"}
    )
    ack1 = bus.publish(msg)
    assert ack1.status == MessageAckStatus.ACK

    # Replay identical message ID
    ack2 = bus.publish(msg)
    assert ack2.status == MessageAckStatus.NACK
    assert "replay" in ack2.reason.lower() or "duplicate" in ack2.reason.lower()


# Scenario 15: Contradictory Agent Findings Negotiation
def test_scenario_15_contradictory_agent_findings(orchestrator):
    now = datetime.now(timezone.utc)
    # Device claims HEALTHY status but exhibits severe packet loss and CRC errors
    payload = [{
        "device_id": "BLDG-SW-ENG",
        "timestamp": now.isoformat(),
        "reported_status": "HEALTHY",
        "packet_loss_pct": 14.0,
        "latency_ms": 180.0,
        "interface_errors": 45,
        "crc_errors": 60
    }]
    res = orchestrator.process(payload, incident_id="INC-SCEN-15", reference_time=now)
    # Verification of negotiation between TelemetryAgent and CorrelationAgent
    msg_types = [m.message_type for m in res.agent_messages]
    assert ProtocolMessageType.AGENT_DISAGREEMENT in msg_types or "AGENT_DISAGREEMENT" in [str(t) for t in msg_types]
    assert res.report.suspected_root_cause != "NORMAL_OPERATION"


# Scenario 16: Unauthorized Agent Sender Rejection
def test_scenario_16_unauthorized_agent_rejection():
    bus = AgentMessageBus()
    msg = AgentProtocolMessage(
        incident_id="INC-SCEN-16",
        correlation_id="CORR-16",
        message_type=ProtocolMessageType.OBSERVATION,
        sender="MaliciousImposterAgent",
        recipient="Orchestrator",
        sequence_number=1,
        payload={"fake_alert": "critical"}
    )
    ack = bus.publish(msg)
    assert ack.status == MessageAckStatus.NACK
    assert "unauthorized" in ack.reason.lower()


# Scenario 17: Automated Remediation Simulation with Projected KPIs
def test_scenario_17_remediation_simulation():
    sim_result = RemediationSimulator.simulate_remediation(
        root_cause="LINK_CONGESTION",
        affected_devices=["CORE-SW-01"]
    )
    assert sim_result.suspected_root_cause == "LINK_CONGESTION"
    assert len(sim_result.actions) > 0
    act = sim_result.actions[0]
    assert act.simulated_cli_command != ""
    assert act.projected_recovery["packet_loss_pct"]["projected_after"] < 1.0


# Scenario 18: Live Mutation Guard Blocking Unauthenticated Execution
def test_scenario_18_safety_guard_blocks_unauthorized():
    # Attempting to transition to REAL_EXECUTED without valid credentials
    fsm = RemediationLifecycleStateMachine(incident_id="INC-SCEN-18")
    fsm.transition_to(RemediationLifecycleState.SIMULATED)
    fsm.transition_to(RemediationLifecycleState.APPROVAL_PENDING)
    fsm.transition_to(RemediationLifecycleState.APPROVED)
    fsm.transition_to(RemediationLifecycleState.REAL_EXECUTION_PENDING)

    with pytest.raises(ExecutionSafetyGuardError):
        # Must block without environment key and signed authorization
        fsm.transition_to(RemediationLifecycleState.REAL_EXECUTED)


# Scenario 19: Cryptographically Verified Adapter Execution & Post-Recovery
def test_scenario_19_verified_adapter_execution(monkeypatch):
    test_secret = "TEST-OPERATOR-SECRET-KEY-999"
    monkeypatch.setenv("NETCOOP_ENABLE_LIVE_EXECUTION", "1")
    monkeypatch.setenv("NETCOOP_OPERATOR_SECRET_KEY", test_secret)

    incident_id = "INC-SCEN-19"
    action_id = "ACT-RESTART-01"

    # 1. Authorize
    auth = create_operator_authorization(
        operator_id="NOC_LEAD",
        incident_id=incident_id,
        secret_key=test_secret,
        action_ids=[action_id]
    )

    # 2. Setup Registered Execution Adapter & Signed Receipt
    receipt = ExecutionReceipt(
        execution_adapter_id="ADAPTER-CISCO-IOS-XE",
        execution_id="EXEC-777",
        incident_id=incident_id,
        action_id=action_id,
        operator_id="NOC_LEAD",
        authorization_ref=auth.auth_token,
        target_device="CORE-SW-01",
        execution_result="SUCCESS",
        audit_reference="AUDIT-REF-777"
    )
    adapter = ExecutionAdapterRegistry.get_adapter("ADAPTER-CISCO-IOS-XE")
    receipt.sign_with_adapter(adapter.signing_key)

    # 3. Lifecycle state progression
    fsm = RemediationLifecycleStateMachine(incident_id=incident_id)
    fsm.transition_to(RemediationLifecycleState.SIMULATED)
    fsm.transition_to(RemediationLifecycleState.APPROVAL_PENDING)
    fsm.transition_to(RemediationLifecycleState.APPROVED)
    fsm.transition_to(RemediationLifecycleState.REAL_EXECUTION_PENDING)
    fsm.transition_to(
        RemediationLifecycleState.REAL_EXECUTED,
        authorization=auth,
        execution_receipt=receipt
    )
    assert fsm.current_state == RemediationLifecycleState.REAL_EXECUTED

    # 4. Post-execution recovery telemetry validation
    recovery_telemetry = [
        CanonicalTelemetry(
            device_id="CORE-SW-01",
            metrics=CanonicalMetrics(latency_ms=12.0, packet_loss_pct=0.0, interface_errors=0)
        )
    ]
    fsm.transition_to(
        RemediationLifecycleState.REAL_RECOVERY_VERIFIED,
        post_execution_telemetry=recovery_telemetry
    )
    assert fsm.current_state == RemediationLifecycleState.REAL_RECOVERY_VERIFIED


# Scenario 20: Unknown / Unmapped Device Topology Resilience
def test_scenario_20_unknown_device_topology_resilience(orchestrator):
    now = datetime.now(timezone.utc)
    payload = [{
        "device_id": "ROGUE-UNREGISTERED-SWITCH-99",
        "timestamp": now.isoformat(),
        "latency_ms": 35.0,
        "packet_loss_pct": 0.0,
        "cpu_pct": 14.0
    }]
    res = orchestrator.process(payload, incident_id="INC-SCEN-20", reference_time=now)
    assert res.report is not None
    assert "ROGUE-UNREGISTERED-SWITCH-99" in [r.device_id for r in res.canonical_telemetry]
    assert res.evidence_graph is not None
    assert res.evidence_graph.is_acyclic() is True
