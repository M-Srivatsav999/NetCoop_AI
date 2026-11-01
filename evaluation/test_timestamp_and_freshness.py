"""Evaluation and regression suite for Release 6.2.

Verifies:
1. Telemetry mode separation: LIVE vs HISTORICAL_REPLAY vs BENCHMARK.
2. Stale live telemetry is NEVER automatically classified as fresh.
3. Historical timestamps permitted in explicit replay mode.
4. Future and clock-skewed timestamps trigger explicit uncertainty/limitations.
5. Reference time is recorded in the diagnostic report alongside original timestamps.
6. Unknown devices (e.g. SW_CAMPUS_4) have None parent and 0 downstream descendants (no fabricated links).
7. Competing hypothesis evaluation between HARDWARE_FAILURE and LINK_CONGESTION.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import pytest
from core.orchestrator import NetworkIntelligenceOrchestrator
from core.topology import TopologyEngine
from protocol.models import HypothesisType
from web.server import DiagnoseRequest, run_diagnosis, get_topology, get_device_blast_radius


def test_fresh_live_telemetry_evaluation():
    """Verify that live telemetry with current timestamp is processed cleanly in LIVE mode."""
    orch = NetworkIntelligenceOrchestrator()
    now_utc = datetime.now(timezone.utc)
    fresh_payload = [
        {
            "device_id": "DIST-SW-NORTH",
            "timestamp": now_utc.isoformat(),
            "status": "WARNING",
            "metrics": {
                "latency_ms": 195.0,
                "packet_loss_pct": 5.5,
                "queue_drops": 180,
                "interface_errors": 0,
                "cpu_pct": 65.0
            }
        }
    ]
    res = orch.process(fresh_payload, incident_id="INC-TEST-LIVE-FRESH", telemetry_mode="LIVE")
    assert res.report.telemetry_mode == "LIVE"
    assert res.report.staleness_seconds < 10.0
    assert res.report.status == "diagnosed"
    assert res.report.suspected_root_cause == HypothesisType.LINK_CONGESTION.value


def test_stale_live_telemetry_never_classified_as_fresh():
    """Verify that stale telemetry (>2h old) in LIVE mode is flagged with staleness and abstains."""
    orch = NetworkIntelligenceOrchestrator()
    stale_ts = datetime.now(timezone.utc) - timedelta(hours=5)
    stale_payload = [
        {
            "device_id": "DIST-SW-NORTH",
            "timestamp": stale_ts.isoformat(),
            "status": "HEALTHY",
            "metrics": {
                "latency_ms": 12.0,
                "packet_loss_pct": 0.0,
                "queue_drops": 0,
                "interface_errors": 0,
                "cpu_pct": 25.0
            }
        }
    ]
    # In LIVE mode, reference time is wall-clock time
    res = orch.process(stale_payload, incident_id="INC-TEST-LIVE-STALE", telemetry_mode="LIVE")
    assert res.report.telemetry_mode == "LIVE"
    assert res.report.staleness_seconds > 14000.0  # > 4 hours
    assert res.report.status == "insufficient_evidence"
    assert res.report.suspected_root_cause == HypothesisType.INSUFFICIENT_EVIDENCE.value
    assert res.report.confidence == 0.0


def test_historical_replay_mode_permits_historical_timestamps():
    """Verify that historical timestamps are permitted in explicit HISTORICAL_REPLAY mode."""
    orch = NetworkIntelligenceOrchestrator()
    hist_ts = datetime(2026, 10, 14, 7, 5, 49, tzinfo=timezone.utc)
    ref_time = hist_ts + timedelta(seconds=60)
    payload = [
        {
            "device_id": "DIST-SW-NORTH",
            "timestamp": hist_ts.isoformat(),
            "status": "WARNING",
            "metrics": {
                "latency_ms": 180.0,
                "packet_loss_pct": 5.0,
                "queue_drops": 120,
                "interface_errors": 0
            }
        }
    ]
    res = orch.process(
        payload,
        incident_id="INC-TEST-REPLAY",
        reference_time=ref_time,
        telemetry_mode="HISTORICAL_REPLAY"
    )
    assert res.report.telemetry_mode == "HISTORICAL_REPLAY"
    assert res.report.reference_time == ref_time.isoformat()
    assert res.report.staleness_seconds == 60.0
    assert res.report.status == "diagnosed"


def test_future_clock_skew_detection():
    """Verify that future timestamps (>5s) trigger clock skew anomaly limitations."""
    orch = NetworkIntelligenceOrchestrator()
    now_utc = datetime.now(timezone.utc)
    future_ts = now_utc + timedelta(seconds=120)  # 2 minutes in future
    future_payload = [
        {
            "device_id": "DIST-SW-NORTH",
            "timestamp": future_ts.isoformat(),
            "status": "WARNING",
            "metrics": {
                "latency_ms": 150.0,
                "packet_loss_pct": 4.0,
                "queue_drops": 90,
                "interface_errors": 0
            }
        }
    ]
    res = orch.process(
        future_payload,
        incident_id="INC-TEST-FUTURE-SKEW",
        reference_time=now_utc,
        telemetry_mode="LIVE"
    )
    # Check that clock skew anomaly was detected and recorded in report limitations
    clock_skew_limits = [lim for lim in res.report.limitations if "Clock skew anomaly" in lim]
    assert len(clock_skew_limits) > 0
    assert "in future relative to reference time" in clock_skew_limits[0]


def test_stale_warning_30m_live_telemetry():
    """Verify that live telemetry aged between 30m and 2h triggers AGED_WARNING and staleness penalty."""
    orch = NetworkIntelligenceOrchestrator()
    aged_ts = datetime.now(timezone.utc) - timedelta(minutes=45)
    payload = [
        {
            "device_id": "DIST-SW-NORTH",
            "timestamp": aged_ts.isoformat(),
            "status": "WARNING",
            "metrics": {
                "latency_ms": 190.0,
                "packet_loss_pct": 5.0,
                "queue_drops": 140,
                "interface_errors": 0,
                "cpu_pct": 60.0
            }
        }
    ]
    res = orch.process(payload, incident_id="INC-TEST-AGED-30M", telemetry_mode="LIVE")
    assert res.report.telemetry_mode == "LIVE"
    assert res.report.staleness_seconds > 2400.0  # > 40 minutes
    assert res.report.freshness_status in ("AGED_WARNING", "STALE_WARNING")
    # Staleness uncertainty factor must be present
    stale_uncert = [u for u in res.arbitration_result.uncertainty_factors if "Stale telemetry timestamp" in u]
    assert len(stale_uncert) > 0


def test_missing_timestamps_telemetry():
    """Verify that payloads completely lacking timestamps are handled gracefully with MISSING_TIMESTAMPS status."""
    orch = NetworkIntelligenceOrchestrator()
    payload = [
        {
            "device_id": "DIST-SW-NORTH",
            "status": "WARNING",
            "metrics": {
                "latency_ms": 160.0,
                "packet_loss_pct": 4.5,
                "queue_drops": 110,
                "interface_errors": 0
            }
        }
    ]
    res = orch.process(payload, incident_id="INC-TEST-MISSING-TS", telemetry_mode="LIVE")
    assert res.report.freshness_status == "MISSING_TIMESTAMPS"
    missing_limits = [lim for lim in res.report.limitations if "missing timestamp" in lim.lower()]
    assert len(missing_limits) > 0


def test_mixed_timestamps_telemetry():
    """Verify that batches with wide timestamp spread (>300s) trigger timestamp spread warning."""
    orch = NetworkIntelligenceOrchestrator()
    now_utc = datetime.now(timezone.utc)
    ts1 = now_utc - timedelta(seconds=600)  # 10 min ago
    ts2 = now_utc  # now
    payload = [
        {
            "device_id": "DIST-SW-NORTH",
            "timestamp": ts1.isoformat(),
            "status": "WARNING",
            "metrics": {"latency_ms": 140.0, "queue_drops": 80}
        },
        {
            "device_id": "BLDG-SW-ENG",
            "timestamp": ts2.isoformat(),
            "status": "WARNING",
            "metrics": {"latency_ms": 180.0, "queue_drops": 150}
        }
    ]
    res = orch.process(payload, incident_id="INC-TEST-MIXED-TS", telemetry_mode="LIVE")
    spread_limits = [lim for lim in res.report.limitations if "spread" in lim.lower()]
    assert len(spread_limits) > 0


def test_explicit_benchmark_reference_time():
    """Verify that explicit BENCHMARK mode evaluates freshness strictly against supplied reference time."""
    orch = NetworkIntelligenceOrchestrator()
    bench_ref = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
    sample_ts = datetime(2026, 10, 31, 11, 59, 30, tzinfo=timezone.utc)
    payload = [
        {
            "device_id": "DIST-SW-NORTH",
            "timestamp": sample_ts.isoformat(),
            "status": "HEALTHY",
            "metrics": {"latency_ms": 10.0, "packet_loss_pct": 0.0, "queue_drops": 0, "interface_errors": 0}
        }
    ]
    res = orch.process(payload, incident_id="INC-TEST-BENCH", reference_time=bench_ref, telemetry_mode="BENCHMARK")
    assert res.report.telemetry_mode == "BENCHMARK"
    assert res.report.reference_time == bench_ref.isoformat()
    assert res.report.staleness_seconds == 30.0
    assert res.report.freshness_status == "FRESH"


def test_unknown_devices_no_fabricated_parent_or_descendants():
    """Verify all 4 classes of unknown device IDs: switches, APs, servers, and custom IDs.
    
    Enforces:
    - parentage_status == 'UNKNOWN'
    - parent_id is None
    - is_confirmed_topology is False
    - total_downstream_count == 0
    - downstream_device_ids == []
    """
    topo = TopologyEngine()
    test_devices = [
        "SW-UNKNOWN-99",     # Unknown switch
        "AP-UNKNOWN-01",     # Unknown AP
        "SRV-STORAGE-01",    # Unknown server
        "CUSTOM-IOT-XYZ"     # Arbitrary device ID
    ]
    for dev_id in test_devices:
        node = topo.get_node(dev_id)
        assert node.parent_id is None, f"{dev_id} must have parent_id=None"
        assert node.is_confirmed_topology is False, f"{dev_id} must not be confirmed topology"
        assert node.is_observed is True

        node_dict = node.to_dict()
        assert node_dict["parentage_status"] == "UNKNOWN"
        assert node_dict["parent"] is None

        br = topo.get_blast_radius(dev_id)
        assert br["root_device_id"] == dev_id
        assert br["parent"] is None
        assert br["parentage_status"] == "UNKNOWN"
        assert br["parent_status"] in ("UNKNOWN", "UNMAPPED_PARENT")
        assert br["is_confirmed_topology"] is False
        assert br["total_downstream_count"] == 0
        assert br["downstream_device_ids"] == []


def test_unknown_device_topology_no_fabricated_parent_or_descendants():
    """Verify that unknown devices have parent=None, is_confirmed_topology=False, and 0 descendants."""
    topo = TopologyEngine()
    node = topo.get_node("SW_CAMPUS_4")
    assert node.parent_id is None
    assert node.is_confirmed_topology is False
    assert node.is_observed is True

    br = topo.get_blast_radius("SW_CAMPUS_4")
    assert br["root_device_id"] == "SW_CAMPUS_4"
    assert br["parent"] is None
    assert br["parent_status"] in ("UNKNOWN", "UNMAPPED_PARENT")
    assert br["is_confirmed_topology"] is False
    assert br["total_downstream_count"] == 0
    assert br["downstream_device_ids"] == []


def test_colab_competing_hypotheses_and_alternative_causes():
    """Verify that Colab payload with both interface errors (382) and queue drops (13416)

    diagnoses HARDWARE_FAILURE with LINK_CONGESTION / BUFFER_OVERFLOW as active alternative cause.
    """
    colab_payload = {
        "timestamp": "2026-10-14T07:05:49.619791Z",
        "device_id": "SW_CAMPUS_4",
        "metrics": {
            "cpu_utilization_pct": 99.9,
            "link_utilization_pct": 100.0,
            "packet_loss_pct": 28.51,
            "latency_ms": 926.46,
            "queue_drops": 13416,
            "interface_errors": 382
        },
        "status": "Critical"
    }
    req = DiagnoseRequest(
        telemetry=colab_payload,
        input_source="UPLOADED_JSON",
        telemetry_mode="HISTORICAL_REPLAY",
        incident_id="INC-COLAB-COMPETE-AUDIT"
    )
    data = run_diagnosis(req)
    rep = data["report"]

    assert rep["suspected_root_cause"] == "HARDWARE_FAILURE"
    assert "SW_CAMPUS_4" in rep["affected_devices"]
    # Verify alternative causes list contains Link Congestion
    alt_text = " ".join(rep["alternative_causes"]).lower()
    assert "link congestion" in alt_text or "buffer" in alt_text
    # Verify report records replay mode and reference time
    assert rep["telemetry_mode"] == "HISTORICAL_REPLAY"
    assert rep["reference_time"] is not None
