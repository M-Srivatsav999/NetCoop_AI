"""Evaluation test validating official Google Colab telemetry generator payload ingestion.

Verifies:
1. Single dictionary ingestion (NOT in a list).
2. Aliased metric keys: cpu_utilization_pct, link_utilization_pct.
3. Arbitrary device identifier: SW_CAMPUS_4 (unmapped to static IIT BBS core).
4. Timestamp parsing: ISO8601 with fractional seconds and 'Z' suffix.
5. Reference time anchoring avoiding false staleness penalty.
6. Export endpoints: export_diagnostic_report and export_input_telemetry.
"""

from __future__ import annotations

import json
from web.server import (
    DiagnoseRequest,
    run_diagnosis,
    get_topology,
    get_device_blast_radius,
    export_diagnostic_report,
    export_input_telemetry,
)

COLAB_PAYLOAD = {
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


def test_colab_single_dictionary_ingestion_api():
    """Verify that posting the official Colab payload directly or wrapped succeeds."""
    req = DiagnoseRequest(
        incident_id="INC-COLAB-TEST-01",
        telemetry=COLAB_PAYLOAD,
        input_source="UPLOADED_JSON"
    )
    data = run_diagnosis(req)

    assert data["input_source"] == "UPLOADED_JSON"
    assert "RUN-" in data["run_id"]
    report = data["report"]

    assert report["suspected_root_cause"] == "HARDWARE_FAILURE"
    assert report["confidence"] >= 0.50
    assert "SW_CAMPUS_4" in report["affected_devices"]
    assert len(report["supporting_evidence"]) >= 2

    # Verify metrics preserved and normalized
    ev_metrics = [e["metric"] for e in report["supporting_evidence"]]
    assert "interface_errors" in ev_metrics


def test_colab_direct_body_ingestion():
    """Verify posting the raw Colab dictionary directly as the request body."""
    req = DiagnoseRequest(**COLAB_PAYLOAD)
    data = run_diagnosis(req)
    assert "SW_CAMPUS_4" in data["report"]["affected_devices"]


def test_colab_topology_and_blast_radius():
    """Verify that newly diagnosed device SW_CAMPUS_4 is visible in topology and blast radius."""
    req = DiagnoseRequest(telemetry=COLAB_PAYLOAD)
    run_diagnosis(req)

    # Topology query
    topo = get_topology()
    node_ids = [n["id"] for n in topo["nodes"]]
    assert "SW_CAMPUS_4" in node_ids

    # Blast radius query
    br = get_device_blast_radius("SW_CAMPUS_4")
    assert br["root_device_id"] == "SW_CAMPUS_4"
    assert "total_downstream_count" in br


def test_colab_exports_and_remediation():
    """Verify downloadable JSON exports for report and telemetry."""
    req = DiagnoseRequest(telemetry=COLAB_PAYLOAD, incident_id="INC-COLAB-EXP")
    run_diagnosis(req)

    # Export report
    rep_res = export_diagnostic_report()
    assert rep_res.status_code == 200
    assert "attachment" in rep_res.headers.get("content-disposition", "")
    rep_json = json.loads(rep_res.body.decode("utf-8"))
    assert rep_json["suspected_root_cause"] == "HARDWARE_FAILURE"
    assert "SW_CAMPUS_4" in rep_json["affected_devices"]

    # Export input telemetry
    tel_res = export_input_telemetry()
    assert tel_res.status_code == 200
    assert "attachment" in tel_res.headers.get("content-disposition", "")
    tel_json = json.loads(tel_res.body.decode("utf-8"))
    assert isinstance(tel_json, list)
    assert tel_json[0]["device_id"] == "SW_CAMPUS_4"
