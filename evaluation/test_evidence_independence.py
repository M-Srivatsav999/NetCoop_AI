"""Evidence Independence, Provenance Lineage, and Copycat De-biasing Tests.

Validates that:
1. EvidenceItem supports full provenance tracking (telemetry_source_id, derivation_method, source_lineage, independence_group).
2. Multiple agents observing the EXACT SAME underlying telemetry datum are clustered into the same independence group
   and heavily discounted, preventing artificial confidence inflation by copycat agents.
3. Truly independent evidence from distinct metrics or distinct devices receives full corroborative weighting.
4. Arbitration correctly balances supporting vs contradicting signals with independence weighting.
"""

import pytest
from datetime import datetime, timezone
from core.evidence_engine import EvidenceEngine
from protocol.models import (
    CanonicalMetrics,
    CanonicalTelemetry,
    EvidenceItem,
    EvidencePolarity,
    HypothesisType,
    SeverityLevel,
)
from agents.telemetry_agent import TelemetryAgent
from agents.infrastructure_agent import InfrastructureAgent


def test_evidence_item_lineage_and_default_grouping():
    """Verify that EvidenceItem tracks full provenance and defaults independence group."""
    item = EvidenceItem(
        evidence_id="EV-1",
        source_agent="TelemetryAgent",
        device_id="SW-CORE-1",
        metric_name="latency_ms",
        observed_value=120.5,
        severity=SeverityLevel.CRITICAL,
        polarity=EvidencePolarity.SUPPORTS,
        hypothesis_target="LINK_CONGESTION",
        weight=0.85,
        description="High latency on core",
        telemetry_source_id="SNAP-999"
    )

    assert item.telemetry_source_id == "SNAP-999"
    assert item.derivation_method == "DIRECT_MEASUREMENT"
    assert item.source_lineage == ["TelemetryAgent"]
    assert item.independence_group == "SW-CORE-1:latency_ms:SNAP-999"


def test_copycat_agent_discounting_prevents_inflation():
    """Verify that copycat agents reporting on the exact same underlying datum do not inflate confidence."""
    engine = EvidenceEngine()

    # Agent 1 reports high latency on SW-1 from telemetry snapshot SNAP-001
    ev_agent1 = EvidenceItem(
        evidence_id="EV-TEL-1",
        source_agent="TelemetryAgent",
        device_id="SW-1",
        metric_name="latency_ms",
        observed_value=150.0,
        severity=SeverityLevel.CRITICAL,
        polarity=EvidencePolarity.SUPPORTS,
        hypothesis_target="LINK_CONGESTION",
        weight=0.85,
        description="High latency observed",
        telemetry_source_id="SNAP-001"
    )

    # Agent 2 (copycat / proxy) re-reports the exact same latency datum from SNAP-001
    ev_copycat = EvidenceItem(
        evidence_id="EV-COPYCAT-1",
        source_agent="ShadowWatcherAgent",
        device_id="SW-1",
        metric_name="latency_ms",
        observed_value=150.0,
        severity=SeverityLevel.CRITICAL,
        polarity=EvidencePolarity.SUPPORTS,
        hypothesis_target="LINK_CONGESTION",
        weight=0.85,
        description="High latency also seen by watcher",
        telemetry_source_id="SNAP-001"
    )

    # 1. Single agent evaluation
    engine.clear()
    engine.add_evidence([ev_agent1])
    score_single = engine.evaluate_hypotheses()["LINK_CONGESTION"]["support_weight"]
    assert score_single == 0.85

    # 2. Both agents added (shared independence group)
    engine.clear()
    engine.add_evidence([ev_agent1, ev_copycat])
    scores_both = engine.evaluate_hypotheses()["LINK_CONGESTION"]
    score_both = scores_both["support_weight"]

    # Without de-biasing it would be 0.85 + 0.85 = 1.70.
    # With de-biasing, redundant observation receives 90% discount: 0.85 + 0.10 * 0.85 = 0.935
    assert score_both < 1.0, f"Expected discounted weight under 1.0, got {score_both}"
    assert score_both == pytest.approx(0.85 + 0.085, rel=1e-3)
    assert scores_both["independent_groups_count"] == 1
    assert scores_both["supporting_count"] == 2


def test_independent_measurements_receive_full_corroboration():
    """Verify that distinct physical metrics on the same device or different devices receive full weight."""
    engine = EvidenceEngine()

    # Metric 1: Ping latency (Transport layer)
    ev_lat = EvidenceItem(
        evidence_id="EV-LAT",
        source_agent="TelemetryAgent",
        device_id="SW-1",
        metric_name="latency_ms",
        observed_value=180.0,
        severity=SeverityLevel.CRITICAL,
        polarity=EvidencePolarity.SUPPORTS,
        hypothesis_target="LINK_CONGESTION",
        weight=0.85,
        description="Transport RTT high",
        telemetry_source_id="SNAP-001"
    )

    # Metric 2: Hardware Queue Drops (Interface buffer layer - distinct metric)
    ev_drops = EvidenceItem(
        evidence_id="EV-DROPS",
        source_agent="InfrastructureAgent",
        device_id="SW-1",
        metric_name="queue_drops",
        observed_value=150,
        severity=SeverityLevel.CRITICAL,
        polarity=EvidencePolarity.SUPPORTS,
        hypothesis_target="LINK_CONGESTION",
        weight=0.90,
        description="Buffer queue drops high",
        telemetry_source_id="SNAP-001"
    )

    # Metric 3: Upstream neighbor switch latency (Distinct physical device)
    ev_neighbor = EvidenceItem(
        evidence_id="EV-NEIGHBOR",
        source_agent="TelemetryAgent",
        device_id="SW-2",
        metric_name="latency_ms",
        observed_value=175.0,
        severity=SeverityLevel.CRITICAL,
        polarity=EvidencePolarity.SUPPORTS,
        hypothesis_target="LINK_CONGESTION",
        weight=0.80,
        description="Neighbor switch also congested",
        telemetry_source_id="SNAP-002"
    )

    engine.add_evidence([ev_lat, ev_drops, ev_neighbor])
    scores = engine.evaluate_hypotheses()["LINK_CONGESTION"]

    # All 3 belong to different independence groups!
    assert scores["independent_groups_count"] == 3
    # Full sum = 0.85 + 0.90 + 0.80 = 2.55
    assert scores["support_weight"] == pytest.approx(2.55, rel=1e-3)


def test_canonical_telemetry_source_id_deterministic():
    """Verify that CanonicalTelemetry generates consistent source hashes."""
    t1 = CanonicalTelemetry(
        device_id="SW-A",
        timestamp=datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc),
        metrics=CanonicalMetrics(latency_ms=50.0, packet_loss_pct=2.0)
    )
    t2 = CanonicalTelemetry(
        device_id="SW-A",
        timestamp=datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc),
        metrics=CanonicalMetrics(latency_ms=50.0, packet_loss_pct=2.0)
    )
    t3 = CanonicalTelemetry(
        device_id="SW-A",
        timestamp=datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc),
        metrics=CanonicalMetrics(latency_ms=90.0, packet_loss_pct=2.0)
    )

    assert t1.get_telemetry_source_id() == t2.get_telemetry_source_id()
    assert t1.get_telemetry_source_id() != t3.get_telemetry_source_id()


def test_same_physical_sensor_correlated_metrics_diminishing_returns():
    """Verify that multiple metrics from the exact same physical sensor receive diminishing returns (50%)."""
    engine = EvidenceEngine()

    # Metric A: CRC errors on physical port GigabitEthernet0/0/1
    ev_crc = EvidenceItem(
        evidence_id="EV-CRC-1",
        source_agent="InfrastructureAgent",
        device_id="SW-CORE-1",
        metric_name="interface_errors",
        observed_value=250,
        severity=SeverityLevel.CRITICAL,
        polarity=EvidencePolarity.SUPPORTS,
        hypothesis_target="HARDWARE_FAILURE",
        weight=0.80,
        description="High CRC errors on physical port Gi0/0/1",
        physical_source_id="SW-CORE-1:phy-port-Gi0/0/1",
        telemetry_source_id="SNAP-CRC"
    )

    # Metric B: Interface drops on the SAME physical port Gi0/0/1
    ev_drops = EvidenceItem(
        evidence_id="EV-DROPS-1",
        source_agent="InfrastructureAgent",
        device_id="SW-CORE-1",
        metric_name="queue_drops",
        observed_value=120,
        severity=SeverityLevel.WARNING,
        polarity=EvidencePolarity.SUPPORTS,
        hypothesis_target="HARDWARE_FAILURE",
        weight=0.60,
        description="Correlated queue drops on same physical port Gi0/0/1",
        physical_source_id="SW-CORE-1:phy-port-Gi0/0/1",
        telemetry_source_id="SNAP-DROPS"
    )

    engine.add_evidence([ev_crc, ev_drops])
    scores = engine.evaluate_hypotheses()["HARDWARE_FAILURE"]

    # Both belong to the same physical sensor cluster:
    # Primary weight: 0.80. Secondary weight: 0.60 discounted by 50% = 0.30
    # Expected total support weight = 0.80 + 0.30 = 1.10
    # Without physical sensor de-biasing, it would be 0.80 + 0.60 = 1.40
    assert scores["independent_groups_count"] == 1
    assert scores["support_weight"] == pytest.approx(1.10, rel=1e-3)
    assert scores["raw_support_weight"] == pytest.approx(1.40, rel=1e-3)


def test_downstream_cascade_sharing_upstream_dependency_discounting():
    """Verify that multiple downstream devices sharing an upstream root cause receive cascade discount (75% off)."""
    engine = EvidenceEngine()

    # Access Switch 1 experiences high latency due to core aggregator link bottleneck
    ev_sw1 = EvidenceItem(
        evidence_id="EV-CASCADE-1",
        source_agent="TelemetryAgent",
        device_id="SW-ACCESS-01",
        metric_name="latency_ms",
        observed_value=160.0,
        severity=SeverityLevel.CRITICAL,
        polarity=EvidencePolarity.SUPPORTS,
        hypothesis_target="LINK_CONGESTION",
        weight=0.80,
        description="Downstream access 1 slow",
        upstream_dependency_id="CORE-AGG-DIST-01",
        telemetry_source_id="SNAP-SW1"
    )

    # Access Switch 2 also experiences high latency due to the SAME upstream aggregator bottleneck
    ev_sw2 = EvidenceItem(
        evidence_id="EV-CASCADE-2",
        source_agent="TelemetryAgent",
        device_id="SW-ACCESS-02",
        metric_name="latency_ms",
        observed_value=155.0,
        severity=SeverityLevel.CRITICAL,
        polarity=EvidencePolarity.SUPPORTS,
        hypothesis_target="LINK_CONGESTION",
        weight=0.80,
        description="Downstream access 2 slow due to shared upstream core link",
        upstream_dependency_id="CORE-AGG-DIST-01",
        telemetry_source_id="SNAP-SW2"
    )

    # Access Switch 3 also experiences high latency from same upstream bottleneck
    ev_sw3 = EvidenceItem(
        evidence_id="EV-CASCADE-3",
        source_agent="TelemetryAgent",
        device_id="SW-ACCESS-03",
        metric_name="latency_ms",
        observed_value=170.0,
        severity=SeverityLevel.CRITICAL,
        polarity=EvidencePolarity.SUPPORTS,
        hypothesis_target="LINK_CONGESTION",
        weight=0.80,
        description="Downstream access 3 slow due to shared upstream core link",
        upstream_dependency_id="CORE-AGG-DIST-01",
        telemetry_source_id="SNAP-SW3"
    )

    engine.add_evidence([ev_sw1, ev_sw2, ev_sw3])
    scores = engine.evaluate_hypotheses()["LINK_CONGESTION"]

    # 3 separate switches -> raw support weight = 0.80 + 0.80 + 0.80 = 2.40
    # Because all 3 share upstream_dependency_id="CORE-AGG-DIST-01":
    # Lead indicator: 0.80
    # Remaining cascade symptoms (0.80 + 0.80 = 1.60) discounted by 75% (multiplier 0.25): 1.60 * 0.25 = 0.40
    # Total de-biased support weight = 0.80 + 0.40 = 1.20
    assert scores["raw_support_weight"] == pytest.approx(2.40, rel=1e-3)
    assert scores["support_weight"] == pytest.approx(1.20, rel=1e-3)


def test_arbitration_balancing_supporting_vs_contradictory_evidence():
    """Verify that contradicting evidence applies a 1.2x penalty against support weight."""
    engine = EvidenceEngine()

    ev_support = EvidenceItem(
        evidence_id="EV-SUPP",
        source_agent="TelemetryAgent",
        device_id="SW-BORDER-1",
        metric_name="packet_loss_pct",
        observed_value=6.5,
        severity=SeverityLevel.CRITICAL,
        polarity=EvidencePolarity.SUPPORTS,
        hypothesis_target="LINK_CONGESTION",
        weight=0.80,
        description="High packet loss on border router",
        telemetry_source_id="SNAP-LOSS"
    )

    # Contradicting: Queue depth is nominal (0 drops)
    ev_contra = EvidenceItem(
        evidence_id="EV-CONTRA",
        source_agent="InfrastructureAgent",
        device_id="SW-BORDER-1",
        metric_name="queue_drops",
        observed_value=0,
        severity=SeverityLevel.INFO,
        polarity=EvidencePolarity.CONTRADICTS,
        hypothesis_target="LINK_CONGESTION",
        weight=0.50,
        description="Queue depth zero contradicted link congestion buffer fill",
        telemetry_source_id="SNAP-QUEUE"
    )

    engine.add_evidence([ev_support, ev_contra])
    scores = engine.evaluate_hypotheses()["LINK_CONGESTION"]

    # Support weight = 0.80
    # Contra weight = 0.50
    # Net score = max(0.0, 0.80 - (1.20 * 0.50)) = max(0.0, 0.80 - 0.60) = 0.20
    assert scores["support_weight"] == pytest.approx(0.80, rel=1e-3)
    assert scores["contra_weight"] == pytest.approx(0.50, rel=1e-3)
    assert scores["net_score"] == pytest.approx(0.20, rel=1e-3)


def test_derived_evidence_provenance_and_weighting():
    """Verify that derived/composite evidence retains parent lineage and scores accurately."""
    engine = EvidenceEngine()

    ev_derived = EvidenceItem(
        evidence_id="EV-DERIVED-EWMA",
        source_agent="TelemetryAgent",
        device_id="SW-CORE-01",
        metric_name="latency_ms",
        observed_value=175.0,
        severity=SeverityLevel.CRITICAL,
        polarity=EvidencePolarity.SUPPORTS,
        hypothesis_target="LINK_CONGESTION",
        weight=0.85,
        description="EWMA 5-minute latency trend exceeds baseline by 400%",
        derivation_method="DERIVED_STATISTIC",
        derived_observation="EWMA_SLOPE_POSITIVE",
        parent_evidence_ids=["EV-RAW-001", "EV-RAW-002"],
        telemetry_source_id="SNAP-COMPOSITE-01"
    )

    assert ev_derived.derivation_method == "DERIVED_STATISTIC"
    assert ev_derived.derived_observation == "EWMA_SLOPE_POSITIVE"
    assert len(ev_derived.parent_evidence_ids) == 2

    engine.add_evidence([ev_derived])
    scores = engine.evaluate_hypotheses()["LINK_CONGESTION"]
    assert scores["support_weight"] == pytest.approx(0.85, rel=1e-3)


def test_missing_provenance_graceful_handling():
    """Verify that evidence with missing provenance fields defaults deterministically without crashing."""
    item_empty = EvidenceItem(
        evidence_id="EV-ANON",
        source_agent="UnknownWatcher",
        device_id="SW-UNPROVISIONED",
        metric_name="interface_errors",
        observed_value=99,
        severity=SeverityLevel.WARNING,
        polarity=EvidencePolarity.SUPPORTS,
        hypothesis_target="HARDWARE_FAILURE",
        weight=0.70,
        description="Anonymous error count without snapshot ID"
    )

    assert item_empty.physical_source_id == "SW-UNPROVISIONED:interface_errors"
    assert item_empty.independence_group == "SW-UNPROVISIONED:interface_errors:src0"
    assert item_empty.source_lineage == ["UnknownWatcher"]

    engine = EvidenceEngine()
    engine.add_evidence([item_empty])
    scores = engine.evaluate_hypotheses()["HARDWARE_FAILURE"]
    assert scores["support_weight"] == pytest.approx(0.70, rel=1e-3)
    assert scores["independent_groups_count"] == 1


def test_evidence_engine_weight_sensitivity_analysis():
    """Verify that configurable heuristic multipliers correctly alter net score sensitivity."""
    ev1 = EvidenceItem(
        evidence_id="EV-1",
        source_agent="Agent1",
        device_id="SW-A",
        metric_name="latency_ms",
        observed_value=150.0,
        severity=SeverityLevel.CRITICAL,
        polarity=EvidencePolarity.SUPPORTS,
        hypothesis_target="LINK_CONGESTION",
        weight=0.80,
        description="High latency observed on downstream switch A",
        upstream_dependency_id="CORE-UPLINK",
        telemetry_source_id="SNAP-A"
    )
    ev2 = EvidenceItem(
        evidence_id="EV-2",
        source_agent="Agent2",
        device_id="SW-B",
        metric_name="latency_ms",
        observed_value=145.0,
        severity=SeverityLevel.CRITICAL,
        polarity=EvidencePolarity.SUPPORTS,
        hypothesis_target="LINK_CONGESTION",
        weight=0.80,
        description="High latency observed on downstream switch B",
        upstream_dependency_id="CORE-UPLINK",
        telemetry_source_id="SNAP-B"
    )

    # Configuration A: Standard default (cascade multiplier = 0.25)
    # Expected: 0.80 + 0.25 * 0.80 = 1.00
    engine_std = EvidenceEngine(cascade_discount_factor=0.25)
    engine_std.add_evidence([ev1, ev2])
    score_std = engine_std.evaluate_hypotheses()["LINK_CONGESTION"]["support_weight"]
    assert score_std == pytest.approx(1.00, rel=1e-3)

    # Configuration B: Aggressive cascade discount (cascade multiplier = 0.05)
    # Expected: 0.80 + 0.05 * 0.80 = 0.84
    engine_aggr = EvidenceEngine(cascade_discount_factor=0.05)
    engine_aggr.add_evidence([ev1, ev2])
    score_aggr = engine_aggr.evaluate_hypotheses()["LINK_CONGESTION"]["support_weight"]
    assert score_aggr == pytest.approx(0.84, rel=1e-3)

    # Configuration C: Permissive cascade discount (cascade multiplier = 0.50)
    # Expected: 0.80 + 0.50 * 0.80 = 1.20
    engine_perm = EvidenceEngine(cascade_discount_factor=0.50)
    engine_perm.add_evidence([ev1, ev2])
    score_perm = engine_perm.evaluate_hypotheses()["LINK_CONGESTION"]["support_weight"]
    assert score_perm == pytest.approx(1.20, rel=1e-3)

    # Verify monotonic ordering: aggr < std < perm
    assert score_aggr < score_std < score_perm
