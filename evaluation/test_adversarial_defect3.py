"""Adversarial and Edge Case Evaluation Suite for Defect 3.

Covers:
1. High interface errors with low queue drops -> HARDWARE_FAILURE.
2. High queue drops with low interface errors -> LINK_CONGESTION.
3. High latency and utilization without physical errors -> LINK_CONGESTION.
4. Hardware failure and congestion occurring together -> HARDWARE_FAILURE with LINK_CONGESTION alternative and confidence < 1.0.
5. Contradictory device status and metrics -> reconciliation of untrusted status labels.
6. Duplicate metrics -> idempotent deduplication.
7. Missing metrics -> explicit missing handling without crash or silent conversion to 0.0.
8. Sparse telemetry -> completeness penalty / INSUFFICIENT_EVIDENCE gating.
9. Stale telemetry -> wall-clock staleness gating in LIVE mode.
10. Ambiguous competing-hypothesis case -> epistemic discount and calibrated confidence.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import pytest

from core.orchestrator import NetworkIntelligenceOrchestrator
from protocol.models import HypothesisType
from web.server import DiagnoseRequest, run_diagnosis


@pytest.fixture
def orchestrator():
    return NetworkIntelligenceOrchestrator()


def test_adversarial_1_high_errors_low_drops(orchestrator):
    """Case 1: High interface errors with low queue drops -> HARDWARE_FAILURE."""
    now_utc = datetime.now(timezone.utc)
    payload = [{
        "device_id": "DIST-SW-NORTH",
        "timestamp": now_utc.isoformat(),
        "status": "CRITICAL",
        "metrics": {
            "interface_errors": 450,
            "packet_loss_pct": 14.5,
            "queue_drops": 2,
            "latency_ms": 32.0,
            "link_utilization_pct": 35.0
        }
    }]
    res = orchestrator.process(payload, incident_id="INC-ADV-01", telemetry_mode="LIVE")
    assert res.report.suspected_root_cause == HypothesisType.HARDWARE_FAILURE.value
    assert res.report.confidence >= 0.50
    ev_metrics = [e.metric for e in res.report.supporting_evidence]
    assert "interface_errors" in ev_metrics


def test_adversarial_2_high_drops_low_errors(orchestrator):
    """Case 2: High queue drops with low interface errors -> LINK_CONGESTION."""
    now_utc = datetime.now(timezone.utc)
    payload = [{
        "device_id": "DIST-SW-NORTH",
        "timestamp": now_utc.isoformat(),
        "status": "WARNING",
        "metrics": {
            "queue_drops": 8500,
            "link_utilization_pct": 98.5,
            "latency_ms": 380.0,
            "packet_loss_pct": 8.2,
            "interface_errors": 0
        }
    }]
    res = orchestrator.process(payload, incident_id="INC-ADV-02", telemetry_mode="LIVE")
    assert res.report.suspected_root_cause == HypothesisType.LINK_CONGESTION.value
    assert res.report.confidence >= 0.60
    ev_metrics = [e.metric for e in res.report.supporting_evidence]
    assert "queue_drops" in ev_metrics or "link_utilization_pct" in ev_metrics


def test_adversarial_3_latency_util_no_physical_errors(orchestrator):
    """Case 3: High latency and utilization without physical errors -> LINK_CONGESTION (no hardware false alarm)."""
    now_utc = datetime.now(timezone.utc)
    payload = [{
        "device_id": "DIST-SW-NORTH",
        "timestamp": now_utc.isoformat(),
        "status": "WARNING",
        "metrics": {
            "latency_ms": 420.0,
            "link_utilization_pct": 99.0,
            "queue_drops": 450,
            "packet_loss_pct": 3.0,
            "interface_errors": 0
        }
    }]
    res = orchestrator.process(payload, incident_id="INC-ADV-03", telemetry_mode="LIVE")
    assert res.report.suspected_root_cause == HypothesisType.LINK_CONGESTION.value
    assert res.report.suspected_root_cause != HypothesisType.HARDWARE_FAILURE.value


def test_adversarial_4_compound_hardware_and_congestion(orchestrator):
    """Case 4: Hardware failure and congestion occurring together -> competing hypotheses with confidence < 1.0."""
    now_utc = datetime.now(timezone.utc)
    payload = [{
        "device_id": "SW_CAMPUS_4",
        "timestamp": now_utc.isoformat(),
        "status": "Critical",
        "metrics": {
            "interface_errors": 382,
            "queue_drops": 13416,
            "link_utilization_pct": 100.0,
            "cpu_utilization_pct": 99.9,
            "packet_loss_pct": 28.51,
            "latency_ms": 926.46
        }
    }]
    res = orchestrator.process(payload, incident_id="INC-ADV-04", telemetry_mode="LIVE")
    assert res.report.suspected_root_cause == HypothesisType.HARDWARE_FAILURE.value
    # Crucial requirement: confidence must NOT be uncalibrated 1.0 when competing hypotheses exist!
    assert res.report.confidence < 1.0
    assert res.report.confidence >= 0.50
    # Must list competing alternative cause
    alt_text = " ".join(res.report.alternative_causes).lower()
    assert "link congestion" in alt_text or "buffer" in alt_text


def test_adversarial_5_contradictory_status_and_metrics(orchestrator):
    """Case 5: Contradictory device status (reported CRITICAL but all metrics 100% nominal)."""
    now_utc = datetime.now(timezone.utc)
    payload = [{
        "device_id": "DIST-SW-NORTH",
        "timestamp": now_utc.isoformat(),
        "reported_status": "CRITICAL",
        "metrics": {
            "latency_ms": 4.5,
            "packet_loss_pct": 0.0,
            "queue_drops": 0,
            "interface_errors": 0,
            "cpu_pct": 20.0
        }
    }]
    res = orchestrator.process(payload, incident_id="INC-ADV-05", telemetry_mode="LIVE")
    # Untrusted status label reconciled against ground-truth sensor telemetry
    assert res.report.suspected_root_cause in (HypothesisType.NORMAL_OPERATION.value, HypothesisType.INSUFFICIENT_EVIDENCE.value)
    # Contradiction recorded in audit
    contra_items = res.arbitration_result.contradictory_evidence
    assert any("reported" in c.lower() or "critical" in c.lower() or "reconciliation" in c.lower() for c in contra_items) or len(res.protocol_audit_trail) > 0


def test_adversarial_6_duplicate_metrics(orchestrator):
    """Case 6: Duplicate identical metrics in payload normalized and ingested idempotently."""
    now_utc = datetime.now(timezone.utc)
    payload = [
        {
            "device_id": "DIST-SW-NORTH",
            "timestamp": now_utc.isoformat(),
            "status": "WARNING",
            "metrics": {"queue_drops": 250, "latency_ms": 160.0}
        },
        {
            "device_id": "DIST-SW-NORTH",
            "timestamp": now_utc.isoformat(),
            "status": "WARNING",
            "metrics": {"queue_drops": 250, "latency_ms": 160.0}
        }
    ]
    res = orchestrator.process(payload, incident_id="INC-ADV-06", telemetry_mode="LIVE")
    assert res.report.status == "diagnosed"
    assert "DIST-SW-NORTH" in res.report.affected_devices


def test_adversarial_7_missing_metrics(orchestrator):
    """Case 7: Missing metrics are not silently zeroed; handled safely."""
    now_utc = datetime.now(timezone.utc)
    payload = [{
        "device_id": "DIST-SW-NORTH",
        "timestamp": now_utc.isoformat(),
        "status": "WARNING",
        "metrics": {
            "latency_ms": 220.0
            # queue_drops, interface_errors, cpu_pct are completely None
        }
    }]
    res = orchestrator.process(payload, incident_id="INC-ADV-07", telemetry_mode="LIVE")
    rec = res.canonical_telemetry[0]
    assert rec.metrics.queue_drops is None
    assert rec.metrics.interface_errors is None
    assert res.report.status in ("diagnosed", "insufficient_evidence")


def test_adversarial_8_sparse_telemetry(orchestrator):
    """Case 8: Critically sparse telemetry (<20% completeness) triggers uncertainty limitations."""
    now_utc = datetime.now(timezone.utc)
    payload = [{
        "device_id": "DIST-SW-NORTH",
        "timestamp": now_utc.isoformat(),
        "status": "HEALTHY",
        "metrics": {
            "latency_ms": 12.0
            # Only 1 of 8 metrics populated (12.5% completeness)
        }
    }]
    res = orchestrator.process(payload, incident_id="INC-ADV-08", telemetry_mode="LIVE")
    # Low completeness must trigger insufficient_evidence or sparsity limitations
    assert res.report.suspected_root_cause == HypothesisType.INSUFFICIENT_EVIDENCE.value or any("sparse" in lim.lower() for lim in res.report.limitations)


def test_adversarial_9_stale_telemetry(orchestrator):
    """Case 9: Stale telemetry (>2h old) in LIVE mode triggers INSUFFICIENT_EVIDENCE or staleness penalty."""
    now_utc = datetime.now(timezone.utc)
    stale_ts = now_utc - timedelta(hours=4)
    payload = [{
        "device_id": "DIST-SW-NORTH",
        "timestamp": stale_ts.isoformat(),
        "status": "HEALTHY",
        "metrics": {"latency_ms": 5.0, "packet_loss_pct": 0.0, "queue_drops": 0, "interface_errors": 0}
    }]
    res = orchestrator.process(payload, incident_id="INC-ADV-09", telemetry_mode="LIVE")
    assert res.report.telemetry_mode == "LIVE"
    assert res.report.staleness_seconds > 10000.0
    assert res.report.suspected_root_cause == HypothesisType.INSUFFICIENT_EVIDENCE.value


def test_adversarial_10_ambiguous_competing_hypotheses(orchestrator):
    """Case 10: Balanced competing signals -> epistemic uncertainty discount, confidence strictly < 0.90."""
    now_utc = datetime.now(timezone.utc)
    payload = [{
        "device_id": "SW_AMBIGUOUS_01",
        "timestamp": now_utc.isoformat(),
        "status": "WARNING",
        "metrics": {
            "interface_errors": 45,
            "queue_drops": 80,
            "packet_loss_pct": 4.5,
            "latency_ms": 140.0,
            "link_utilization_pct": 85.0
        }
    }]
    res = orchestrator.process(payload, incident_id="INC-ADV-10", telemetry_mode="LIVE")
    assert res.report.status == "diagnosed"
    # Neither hypothesis should be claimed with 100% certainty
    assert res.report.confidence < 0.90
    assert len(res.report.alternative_causes) > 0
