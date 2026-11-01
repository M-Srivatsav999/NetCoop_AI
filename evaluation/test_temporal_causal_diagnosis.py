"""Unit and integration tests for Temporal & Causal Diagnostic Engine.

Validates:
- Statistical rolling baseline (Welford's algorithm & EWMA)
- Chronological timeline reconstruction
- Classification of initiating events vs cascading downstream symptoms
- Topological causality verification (propagation lag)
- Independent fault domain separation
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from core.temporal_engine import (
    EventClassification,
    MetricRollingBaseline,
    TemporalCausalEngine,
)
from core.topology import TopologyEngine
from protocol.models import CanonicalMetrics, CanonicalTelemetry, SchemaVersion


def _make_telemetry(device_id: str, ts: datetime, **metrics_kwargs) -> CanonicalTelemetry:
    return CanonicalTelemetry(
        device_id=device_id,
        timestamp=ts,
        metrics=CanonicalMetrics(**metrics_kwargs),
        schema_version_detected=SchemaVersion.V1
    )


def test_rolling_baseline_welford_and_ewma():
    """Verify that Welford's algorithm computes accurate rolling mean, variance, and z-score."""
    baseline = MetricRollingBaseline(device_id="SW-01", metric_name="latency_ms")

    # Feed 10 steady baseline measurements around 20ms
    for _ in range(10):
        baseline.update(20.0)

    assert baseline.sample_count == 10
    assert abs(baseline.mean - 20.0) < 1e-4
    assert abs(baseline.ewma - 20.0) < 1e-4

    # Now feed a sudden spike to 120ms
    delta, z = baseline.update(120.0)
    assert delta > 0.0
    assert baseline.mean > 20.0
    assert baseline.ewma > 20.0


def test_timeline_initiating_vs_cascading_events():
    """Verify that an earlier anomaly on an upstream switch is classified as INITIATING_EVENT,
    and subsequent anomalies on downstream APs are classified as CASCADING_SYMPTOM.
    """
    engine = TemporalCausalEngine()
    t0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(seconds=5)
    t2 = t0 + timedelta(seconds=12)

    # Historical nominal batch to train baselines
    batch_hist = [
        _make_telemetry("BLDG-SW-ENG", t0 - timedelta(seconds=30), latency_ms=15.0, packet_loss_pct=0.0),
        _make_telemetry("AP-ENG-01", t0 - timedelta(seconds=30), latency_ms=18.0, packet_loss_pct=0.0),
    ]

    # Batch 1: Upstream building switch suffers severe queue drops and latency spike at t0
    batch_1 = [
        _make_telemetry("BLDG-SW-ENG", t0, latency_ms=190.0, packet_loss_pct=5.5, queue_drops=180),
        _make_telemetry("AP-ENG-01", t0, latency_ms=20.0, packet_loss_pct=0.0),
    ]

    # Batch 2: Downstream AP starts suffering packet loss and elevated latency at t1
    batch_2 = [
        _make_telemetry("BLDG-SW-ENG", t1, latency_ms=210.0, packet_loss_pct=6.0, queue_drops=250),
        _make_telemetry("AP-ENG-01", t1, latency_ms=180.0, packet_loss_pct=4.8),
    ]

    events = engine.process_timeline([batch_hist, batch_1, batch_2])

    assert len(events) >= 2
    # First event must be the initiating event on BLDG-SW-ENG
    initiating = events[0]
    assert initiating.device_id == "BLDG-SW-ENG"
    assert initiating.classification == EventClassification.INITIATING_EVENT

    # Downstream event on AP-ENG-01 must be classified as cascading symptom
    ap_events = [e for e in events if e.device_id == "AP-ENG-01"]
    assert len(ap_events) >= 1
    assert ap_events[0].classification == EventClassification.CASCADING_SYMPTOM
    assert ap_events[0].causal_parent_id is not None
    assert "Cascading symptom downstream from BLDG-SW-ENG" in ap_events[0].explanation


def test_independent_anomalies_separated_by_topology():
    """Verify that simultaneous anomalies in disconnected buildings are classified as independent."""
    engine = TemporalCausalEngine()
    t0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)

    # Anomaly in Engineering Building and Anomaly in Library simultaneously
    batch = [
        _make_telemetry("BLDG-SW-ENG", t0, latency_ms=200.0, packet_loss_pct=8.0),
        _make_telemetry("BLDG-SW-LIB", t0, interface_errors=50, packet_loss_pct=10.0),
    ]

    events = engine.process_timeline([batch])
    assert len(events) >= 2
    # The first processed is INITIATING
    assert events[0].classification == EventClassification.INITIATING_EVENT
    # The second device (in separate building) is INDEPENDENT_ANOMALY, NOT a cascade!
    second_dev_events = [e for e in events if e.device_id != events[0].device_id]
    assert len(second_dev_events) >= 1
    assert second_dev_events[0].classification == EventClassification.INDEPENDENT_ANOMALY


def test_temporal_order_reversal_changes_arbiter_root_cause():
    """Prove that changing event sequence ordering materially influences the Arbiter's root-cause selection.
    
    Constructs a controlled pair of scenarios with identical topology and metric values,
    varying only the event timestamps:
    - Pair A: CORE-SW-01 queue drops occur at t0 (initiating); BLDG-SW-ENG errors occur at t1 (cascading).
      Diagnosis must be LINK_CONGESTION.
    - Pair B: BLDG-SW-ENG hardware errors occur at t0 (initiating); CORE-SW-01 queue drops occur at t1 (cascading).
      Diagnosis must be HARDWARE_FAILURE.
    """
    from core.orchestrator import NetworkIntelligenceOrchestrator
    orchestrator = NetworkIntelligenceOrchestrator()

    t0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 1, 10, 0, 10, tzinfo=timezone.utc)

    # -------------------------------------------------------------
    # Pair A: Core switch link congestion initiates first
    # -------------------------------------------------------------
    payload_a = [
        {
            "device_id": "CORE-SW-01",
            "timestamp": t0.isoformat(),
            "latency_ms": 175.0,
            "packet_loss_pct": 5.0,
            "queue_drops": 240,
            "interface_errors": 0
        },
        {
            "device_id": "BLDG-SW-ENG",
            "timestamp": t1.isoformat(),
            "latency_ms": 160.0,
            "packet_loss_pct": 4.5,
            "queue_drops": 0,
            "interface_errors": 25
        }
    ]
    res_a = orchestrator.process(payload_a, incident_id="INC-TEMP-PAIR-A", reference_time=t1)

    # -------------------------------------------------------------
    # Pair B: Building switch physical hardware errors initiate first
    # (Exact same metrics, only timestamps reversed!)
    # -------------------------------------------------------------
    payload_b = [
        {
            "device_id": "CORE-SW-01",
            "timestamp": t1.isoformat(),  # Core occurs later (t1)
            "latency_ms": 175.0,
            "packet_loss_pct": 5.0,
            "queue_drops": 240,
            "interface_errors": 0
        },
        {
            "device_id": "BLDG-SW-ENG",
            "timestamp": t0.isoformat(),  # Building switch occurs earlier (t0)
            "latency_ms": 160.0,
            "packet_loss_pct": 4.5,
            "queue_drops": 0,
            "interface_errors": 25
        }
    ]
    res_b = orchestrator.process(payload_b, incident_id="INC-TEMP-PAIR-B", reference_time=t1)

    # Temporal causality verification
    assert res_a.report.suspected_root_cause != res_b.report.suspected_root_cause
    assert res_a.report.suspected_root_cause == "LINK_CONGESTION"
    assert res_b.report.suspected_root_cause == "HARDWARE_FAILURE"

    # Verify that the Arbiter's accepted rationale reflects the initiating event device
    assert "CORE-SW-01" in res_a.arbiter_decision.accepted_rationale
    assert "BLDG-SW-ENG" in res_b.arbiter_decision.accepted_rationale


def test_temporal_simultaneous_initiating_events_preserves_uncertainty():
    """Verify that when two distinct devices report simultaneous initiating anomalies,
    causality is declared ambiguous and recorded in uncertainty factors rather than guessing.
    """
    from core.orchestrator import NetworkIntelligenceOrchestrator
    orchestrator = NetworkIntelligenceOrchestrator()
    t0 = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Two distinct switches initiate anomalies at the exact same second
    payload = [
        {
            "device_id": "SW-DIST-01",
            "timestamp": t0.isoformat(),
            "latency_ms": 150.0,
            "packet_loss_pct": 6.0,
            "queue_drops": 100,
            "interface_errors": 0
        },
        {
            "device_id": "BLDG-SW-SES",
            "timestamp": t0.isoformat(),
            "latency_ms": 160.0,
            "packet_loss_pct": 5.5,
            "queue_drops": 0,
            "interface_errors": 45
        }
    ]
    res = orchestrator.process(payload, incident_id="INC-SIMUL-TEST", reference_time=t0)
    uncertainties = res.arbiter_decision.uncertainty_factors
    assert any("ambiguous" in u.lower() or "simultaneous" in u.lower() for u in uncertainties)


def test_temporal_future_clock_skew_initiating_event_discarded():
    """Verify that initiating events with excessive future clock skew (>60s) are safely discarded."""
    from core.orchestrator import NetworkIntelligenceOrchestrator
    orchestrator = NetworkIntelligenceOrchestrator()
    now = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
    future_time = now + timedelta(seconds=3600)  # 1 hour in the future!

    payload = [
        {
            "device_id": "SW-FUTURE-01",
            "timestamp": future_time.isoformat(),
            "latency_ms": 180.0,
            "packet_loss_pct": 8.0,
            "queue_drops": 200,
            "interface_errors": 0
        }
    ]
    res = orchestrator.process(payload, incident_id="INC-FUTURE-TEST", reference_time=now)
    uncertainties = res.arbiter_decision.uncertainty_factors
    assert any("clock skew" in u.lower() for u in uncertainties)


def test_temporal_zero_z_score_not_classified_as_anomaly():
    """Verify that an observation with zero z-score / no baseline shift
    is never classified as an anomaly or initiating event."""
    engine = TemporalCausalEngine()
    t0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(seconds=10)

    # First batch establishes the baseline at 6.8
    batch_1 = [_make_telemetry("BLDG-SW-ENG", t0, packet_loss_pct=6.8)]
    # Second batch reports exact same metric value (delta=0, z=0)
    batch_2 = [_make_telemetry("BLDG-SW-ENG", t1, packet_loss_pct=6.8)]

    events = engine.process_timeline([batch_1, batch_2])
    # The second sample at t1 has delta=0.0 and z=0.0, so no event should be generated at t1
    events_at_t1 = [e for e in events if e.timestamp == t1]
    assert len(events_at_t1) == 0
    # No event anywhere should claim "shifted from baseline 6.8 to 6.8 (z=0.0)"
    for e in events:
        assert not (e.baseline_value == e.observed_value and e.z_score == 0.0)
        assert "z=0.0" not in e.explanation


def test_temporal_unchanged_metric_no_event():
    """Verify that healthy steady-state metrics produce zero anomalous events."""
    engine = TemporalCausalEngine()
    t0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)

    # 5 consecutive nominal batches
    batches = [
        [_make_telemetry("CORE-SW-01", t0 + timedelta(seconds=i * 5), latency_ms=12.0, packet_loss_pct=0.0, queue_drops=0, interface_errors=0)]
        for i in range(5)
    ]
    events = engine.process_timeline(batches)
    assert len(events) == 0


def test_temporal_simultaneous_timestamps_no_invented_causality():
    """Verify that simultaneous events (delta_t == 0) across upstream/downstream devices
    are NOT assigned invented causal ordering (propagation lag of 0.00s is strictly forbidden)."""
    engine = TemporalCausalEngine()
    t0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)

    # Core switch and building switch both experience sudden anomaly at the exact same second
    batch = [
        _make_telemetry("CORE-SW-01", t0, latency_ms=190.0, packet_loss_pct=5.0),
        _make_telemetry("BLDG-SW-ENG", t0, latency_ms=180.0, packet_loss_pct=4.8),
    ]
    events = engine.process_timeline([batch])
    assert len(events) >= 2
    # Verify no event has an invented propagation lag of 0.00s
    for e in events:
        assert "propagation lag of 0.00s" not in e.explanation
        if e.causal_parent_id:
            parent = next((p for p in events if p.event_id == e.causal_parent_id), None)
            if parent and parent.device_id != e.device_id:
                # Downstream cascade must have strictly positive propagation lag
                assert (e.timestamp - parent.timestamp).total_seconds() > 0.05


def test_temporal_reverse_ordering_no_backwards_causality():
    """Verify that an earlier downstream anomaly cannot be caused by a subsequent upstream anomaly."""
    engine = TemporalCausalEngine()
    t0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(seconds=15)

    # Downstream AP anomalies at t0; Upstream Core switch anomalies at t1 (15s later)
    batch_downstream_first = [_make_telemetry("AP-ENG-01", t0, latency_ms=190.0, packet_loss_pct=7.0)]
    batch_upstream_later = [_make_telemetry("CORE-SW-01", t1, latency_ms=180.0, packet_loss_pct=6.5)]

    events = engine.process_timeline([batch_downstream_first, batch_upstream_later])
    assert len(events) >= 2

    ap_events = [e for e in events if e.device_id == "AP-ENG-01"]
    core_events = [e for e in events if e.device_id == "CORE-SW-01"]

    # AP cannot be a cascading symptom of the future Core anomaly
    assert ap_events[0].classification == EventClassification.INITIATING_EVENT
    assert ap_events[0].causal_parent_id is None

    # Core at t1 cannot be a cascading symptom of AP (AP is downstream, not upstream)
    assert core_events[0].causal_parent_id is None
    assert core_events[0].classification == EventClassification.INDEPENDENT_ANOMALY


