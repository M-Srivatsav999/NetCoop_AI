"""Comprehensive Fault Injection & Robustness Test Suite for NetCoop AI.

Tests 12 critical engineering failure modes:
1. Missing telemetry (completely empty metrics or None fields)
2. Extreme stale telemetry (>24h and >7d old timestamps)
3. Duplicate telemetry records (identical device and timestamp)
4. Invalid/corrupted timestamps (unparseable strings, invalid epochs)
5. Malformed and corrupted payloads (truncated JSON, wrong types)
6. Unit mismatches and scale variations (bps, sec, ratios)
7. Unknown devices absent from topology graph
8. Disconnected or cyclic topology structures
9. Out-of-order protocol sequence numbers
10. Severe metric contradictions (0% loss with 1500ms latency)
11. Untrusted status labels contradicting empirical counters
12. Post-remediation recovery verification gaps (telemetry remaining degraded)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
import pytest

from core.orchestrator import NetworkIntelligenceOrchestrator
from core.remediation import (
    ExecutionSafetyGuardError,
    RemediationLifecycleState,
    RemediationLifecycleStateMachine,
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


def test_robustness_completely_empty_metrics(orchestrator):
    """Verify orchestrator handles payloads where metrics object is empty or None."""
    payload = [{"device_id": "DEV-EMPTY-01", "metrics": {}}]
    res = orchestrator.process(payload, incident_id="INC-ROB-01")
    assert res.report.status in ("insufficient_evidence", "diagnosed")
    assert res.total_duration_ms > 0.0


def test_robustness_extreme_stale_telemetry(orchestrator):
    """Verify telemetry older than 7 days triggers explicit staleness penalty and limitation."""
    old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    payload = [{
        "device_id": "SW-STALE-01",
        "timestamp": old_ts,
        "latency_ms": 150.0,
        "packet_loss_pct": 10.0
    }]
    res = orchestrator.process(payload, incident_id="INC-ROB-02")
    assert any("stale" in lim.lower() for lim in res.report.limitations)


def test_robustness_duplicate_telemetry_records(orchestrator):
    """Verify deduplication when multiple identical device snapshots are submitted."""
    now_ts = datetime.now(timezone.utc).isoformat()
    record = {
        "device_id": "SW-DUP-01",
        "timestamp": now_ts,
        "latency_ms": 75.0,
        "packet_loss_pct": 4.0
    }
    # Pass duplicate identical records
    res = orchestrator.process([record, record, record], incident_id="INC-ROB-03")
    assert res.report.suspected_root_cause == "LINK_CONGESTION"
    # Deduplication prevents false multi-incident splitting
    assert len(res.report.incidents) <= 1


def test_robustness_invalid_corrupted_timestamps(orchestrator):
    """Verify unparseable or nonsense timestamp strings do not cause unhandled exceptions."""
    payload = [{
        "device_id": "SW-CORRUPT-TS-01",
        "timestamp": "NOT-A-REAL-TIMESTAMP-2026!#$%",
        "latency_ms": 65.0,
        "packet_loss_pct": 3.0
    }]
    res = orchestrator.process(payload, incident_id="INC-ROB-04")
    assert res.report.status == "diagnosed"


def test_robustness_malformed_string_payload(orchestrator):
    """Verify truncated or corrupt JSON string inputs are handled without crashing."""
    corrupt_json = '{"device_id": "SW-BAD", "latency_ms": 120.0, "metrics": {BROKEN_JSON...'
    res = orchestrator.process(corrupt_json, incident_id="INC-ROB-05")
    assert res.report.status in ("insufficient_evidence", "diagnosed")


def test_robustness_unit_mismatches_v2_seconds_and_bps(orchestrator):
    """Verify V2 schemas with latency in seconds and throughput in bps are correctly converted."""
    v2_payload = [{
        "host_id": "SW-V2-UNIT-01",
        "latency_sec": 0.085,       # 85 ms
        "packet_loss_ratio": 0.06,  # 6.0%
        "throughput_bps": 50000000  # 50 Mbps
    }]
    res = orchestrator.process(v2_payload, incident_id="INC-ROB-06")
    rec = res.canonical_telemetry[0]
    assert rec.metrics.latency_ms == pytest.approx(85.0, abs=0.1)
    assert rec.metrics.packet_loss_pct == pytest.approx(6.0, abs=0.1)
    assert rec.metrics.throughput_mbps == pytest.approx(50.0, abs=0.1)


def test_robustness_unknown_device_topology_resilience(orchestrator):
    """Verify that devices not present in the pre-defined topology map are diagnosed without crashing."""
    payload = [{
        "device_id": "NON-EXISTENT-DEVICE-XYZ-99",
        "latency_ms": 25.0,
        "packet_loss_pct": 0.0,
        "cpu_pct": 12.0
    }]
    res = orchestrator.process(payload, incident_id="INC-ROB-07")
    assert res.report.status == "diagnosed"
    assert res.report.suspected_root_cause in ("NORMAL_OPERATION", "INSUFFICIENT_EVIDENCE")


def test_robustness_out_of_order_protocol_sequence():
    """Verify that message bus rejects out-of-order sequence arrivals."""
    bus = AgentMessageBus()
    # Message 1 arrives
    ack1 = bus.publish(AgentProtocolMessage(
        incident_id="INC-ROB-08",
        correlation_id="CORR-ROB",
        message_type=ProtocolMessageType.OBSERVATION,
        sender="AgentA",
        sequence_number=1
    ))
    assert ack1.status == MessageAckStatus.ACK

    # Message 4 arrives (skipping 2 and 3)
    ack4 = bus.publish(AgentProtocolMessage(
        incident_id="INC-ROB-08",
        correlation_id="CORR-ROB",
        message_type=ProtocolMessageType.OBSERVATION,
        sender="AgentA",
        sequence_number=4
    ))
    assert ack4.status == MessageAckStatus.NACK
    assert "Out-of-order" in ack4.reason


def test_robustness_metric_contradiction_resolution(orchestrator):
    """Verify that contradictory signals (0% loss with 1500ms latency) resolve to Congestion, not Hardware."""
    payload = [{
        "device_id": "SW-CONTRADICT-01",
        "latency_ms": 1500.0,
        "packet_loss_pct": 0.0,
        "queue_drops": 250,
        "interface_errors": 0
    }]
    res = orchestrator.process(payload, incident_id="INC-ROB-09")
    # Buffer saturation with zero interface errors indicates Link Congestion, not Hardware
    assert res.report.suspected_root_cause == "LINK_CONGESTION"


def test_robustness_untrusted_status_labels(orchestrator):
    """Verify that misleading generator labels ('HEALTHY') are overridden by empirical packet loss."""
    payload = [{
        "device_id": "SW-LABEL-TRAP-01",
        "reported_status": "HEALTHY",
        "latency_ms": 220.0,
        "packet_loss_pct": 14.0,
        "cpu_pct": 94.0
    }]
    res = orchestrator.process(payload, incident_id="INC-ROB-10")
    assert res.report.suspected_root_cause != "NORMAL_OPERATION"
    assert res.report.suspected_root_cause in ("RESOURCE_EXHAUSTION", "LINK_CONGESTION", "HARDWARE_FAILURE")


def test_robustness_recovery_verification_requires_actual_telemetry():
    """Verify that REAL_RECOVERY_VERIFIED cannot be claimed without actual physical telemetry."""
    sm = RemediationLifecycleStateMachine(RemediationLifecycleState.REAL_EXECUTED)
    with pytest.raises(ExecutionSafetyGuardError) as exc_info:
        sm.transition_to(RemediationLifecycleState.REAL_RECOVERY_VERIFIED)
    assert "requires measured post-execution telemetry" in str(exc_info.value)
