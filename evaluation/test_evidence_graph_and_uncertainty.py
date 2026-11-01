"""Unit and integration tests for Evidence Graph DAG and Uncertainty Handling.

Validates:
- End-to-end evidence graph generation from OrchestrationResult
- Strict Directed Acyclic Graph (DAG) cycle absence
- Cytoscape.js export compatibility for NOC frontend
- Uncertainty status and lineage traceability
"""

from __future__ import annotations

import pytest
from core.evidence_graph import EvidenceGraph
from core.orchestrator import NetworkIntelligenceOrchestrator


def test_evidence_graph_construction_and_dag_invariants():
    """Verify that an orchestration cycle generates a valid acyclic evidence graph."""
    orch = NetworkIntelligenceOrchestrator()
    sample_payload = [
        {
            "device_id": "SW-ACCESS-01",
            "latency_ms": 78.0,
            "packet_loss_pct": 5.0,
            "queue_drops": 65,
            "interface_errors": 0
        }
    ]

    result = orch.process(sample_payload, incident_id="INC-DAG-01")
    graph = EvidenceGraph.build_from_orchestration_result(result)

    assert graph.incident_id == "INC-DAG-01"
    assert graph.status == "diagnosed"
    assert len(graph.nodes) >= 3  # Raw telemetry, Agent finding(s), Arbiter decision
    assert len(graph.edges) >= 2

    # Verify DAG invariant: must be strictly acyclic
    assert graph.is_acyclic() is True

    # Verify node types exist
    node_types = {n.node_type for n in graph.nodes}
    assert "RAW_TELEMETRY" in node_types
    assert "AGENT_FINDING" in node_types
    assert "ARBITER_DECISION" in node_types


def test_evidence_graph_cytoscape_export():
    """Verify that export_cytoscape_elements() produces elements ready for front-end rendering."""
    orch = NetworkIntelligenceOrchestrator()
    sample_payload = [
        {
            "device_id": "AP-WIFI-01",
            "latency_ms": 120.0,
            "packet_loss_pct": 12.0,
            "signal_strength_dbm": -82.0
        }
    ]

    result = orch.process(sample_payload, incident_id="INC-DAG-02")
    graph = EvidenceGraph.build_from_orchestration_result(result)

    elements = graph.export_cytoscape_elements()
    assert len(elements) == len(graph.nodes) + len(graph.edges)

    # Check node element structure
    node_elements = [el for el in elements if "node_type" in el.get("data", {})]
    assert len(node_elements) == len(graph.nodes)
    first_node_data = node_elements[0]["data"]
    assert "id" in first_node_data
    assert "label" in first_node_data
    assert "node_type" in first_node_data

    # Check edge element structure
    edge_elements = [el for el in elements if "source" in el.get("data", {})]
    assert len(edge_elements) == len(graph.edges)
    first_edge_data = edge_elements[0]["data"]
    assert "source" in first_edge_data
    assert "target" in first_edge_data
    assert "relationship" in first_edge_data
