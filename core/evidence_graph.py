"""Evidence Graph & Lineage DAG Engine.

Constructs an auditable, directed acyclic graph (DAG) tracing every diagnostic conclusion
from the final Arbiter decision back through peer reviews, agent findings, and down to
the raw physical sensor telemetry.
Exports graph topologies in Cytoscape/D3-compliant format for front-end visualization.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field

from protocol.models import CanonicalTelemetry, EvidenceItem, SeverityLevel


class EvidenceNodeType(str, Enum):
    RAW_TELEMETRY = "RAW_TELEMETRY"
    NORMALIZED_OBSERVATION = "NORMALIZED_OBSERVATION"
    AGENT_FINDING = "AGENT_FINDING"
    HYPOTHESIS = "HYPOTHESIS"
    PEER_REVIEW = "PEER_REVIEW"
    PEER_CHALLENGE = "PEER_CHALLENGE"
    PEER_CORROBORATION = "PEER_CORROBORATION"
    ARBITRATION = "ARBITRATION"
    ARBITER_DECISION = "ARBITER_DECISION"
    FINAL_DIAGNOSIS = "FINAL_DIAGNOSIS"
    RECOMMENDATION = "RECOMMENDATION"
    SIMULATION = "SIMULATION"
    RECOVERY_VERIFICATION = "RECOVERY_VERIFICATION"


class EvidenceRelationship(str, Enum):
    DERIVED_FROM = "DERIVED_FROM"
    MEASURES = "MEASURES"
    PRODUCES = "PRODUCES"
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    CORROBORATES = "CORROBORATES"
    CHALLENGES = "CHALLENGES"
    DEPENDS_ON = "DEPENDS_ON"
    AFFECTS = "AFFECTS"
    RESOLVES = "RESOLVES"
    INFORMS_ARBITRATION = "INFORMS_ARBITRATION"
    ADJUDICATES = "ADJUDICATES"
    ADJUDICATED_BY = "ADJUDICATED_BY"


class EvidenceGraphNode(BaseModel):
    """A node in the evidence lineage DAG."""
    id: str
    node_type: str  # RAW_TELEMETRY, AGENT_FINDING, PEER_REVIEW, HYPOTHESIS, ARBITER_DECISION
    label: str
    device_id: Optional[str] = None
    severity: str = "INFO"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EvidenceGraphEdge(BaseModel):
    """A directed causal or evidentiary link in the DAG."""
    id: str
    source: str
    target: str
    relationship: str  # MEASURES, PRODUCES, CHALLENGES, CORROBORATES, ADJUDICATES, RESOLVES, etc.
    weight: float = 1.0


class EvidenceGraph(BaseModel):
    """The complete Evidence Lineage Graph."""
    graph_id: str = Field(default_factory=lambda: f"EVDAG-{uuid.uuid4().hex[:8]}")
    incident_id: str
    status: str = "DIAGNOSED"  # DIAGNOSED, INSUFFICIENT_EVIDENCE, CONFLICTING_EVIDENCE, INCONCLUSIVE
    nodes: List[EvidenceGraphNode] = Field(default_factory=list)
    edges: List[EvidenceGraphEdge] = Field(default_factory=list)

    @classmethod
    def build_from_orchestration_result(cls, result: Any) -> EvidenceGraph:
        """Construct graph from an OrchestrationResult instance."""
        graph = cls(
            incident_id=result.report.incident_id,
            status=result.report.status
        )

        decision_node_id = f"NODE-DECISION-{result.report.incident_id}"
        graph.nodes.append(EvidenceGraphNode(
            id=decision_node_id,
            node_type="ARBITER_DECISION",
            label=f"Diagnosis: {result.report.suspected_root_cause} ({result.report.confidence:.1%})",
            severity="CRITICAL" if result.report.confidence >= 0.70 else "WARNING",
            metadata={
                "suspected_root_cause": result.report.suspected_root_cause,
                "confidence": result.report.confidence,
                "status": result.report.status,
                "affected_devices": result.report.affected_devices
            }
        ))

        # Add nodes for each affected device / telemetry record
        for record in result.canonical_telemetry:
            dev_id = record.device_id
            raw_node_id = f"NODE-RAW-{dev_id}"
            graph.nodes.append(EvidenceGraphNode(
                id=raw_node_id,
                node_type="RAW_TELEMETRY",
                label=f"Device: {dev_id}",
                device_id=dev_id,
                metadata={
                    "latency_ms": record.metrics.latency_ms,
                    "loss_pct": record.metrics.packet_loss_pct,
                    "queue_drops": record.metrics.queue_drops,
                    "interface_errors": record.metrics.interface_errors
                }
            ))

        # Add agent findings
        for f_idx, finding in enumerate(result.agent_findings):
            f_node_id = f"NODE-FINDING-{finding.agent_name}-{finding.device_id}-{f_idx}"
            graph.nodes.append(EvidenceGraphNode(
                id=f_node_id,
                node_type="AGENT_FINDING",
                label=f"{finding.agent_name}: {finding.overall_severity.value}",
                device_id=finding.device_id,
                severity=finding.overall_severity.value,
                metadata={"issues": finding.suspected_issues}
            ))

            # Edge from raw telemetry to agent finding
            graph.edges.append(EvidenceGraphEdge(
                id=f"EDGE-RAW-FINDING-{f_idx}",
                source=f"NODE-RAW-{finding.device_id}",
                target=f_node_id,
                relationship="PRODUCES"
            ))

            # Edge from agent finding to decision
            graph.edges.append(EvidenceGraphEdge(
                id=f"EDGE-FINDING-DECISION-{f_idx}",
                source=f_node_id,
                target=decision_node_id,
                relationship="INFORMS_ARBITRATION"
            ))

        # Add peer review interactions if dossier exists
        if getattr(result, "peer_review_dossier", None):
            dossier = result.peer_review_dossier
            for c_idx, chal in enumerate(dossier.challenges):
                c_node_id = f"NODE-CHAL-{chal.challenge_id}"
                graph.nodes.append(EvidenceGraphNode(
                    id=c_node_id,
                    node_type="PEER_CHALLENGE",
                    label=f"Challenge: {chal.challenger_agent} -> {chal.target_agent}",
                    device_id=chal.target_device,
                    severity="WARNING",
                    metadata={"reason": chal.challenge_reason}
                ))
                graph.edges.append(EvidenceGraphEdge(
                    id=f"EDGE-CHAL-{c_idx}",
                    source=c_node_id,
                    target=decision_node_id,
                    relationship="ADJUDICATED_BY"
                ))

            for r_idx, corr in enumerate(dossier.corroborations):
                corr_node_id = f"NODE-CORR-{corr.corroboration_id}"
                graph.nodes.append(EvidenceGraphNode(
                    id=corr_node_id,
                    node_type="PEER_CORROBORATION",
                    label=f"Corroboration: {corr.corroborating_agent}",
                    device_id=corr.target_device,
                    severity="INFO",
                    metadata={"explanation": corr.explanation}
                ))
                graph.edges.append(EvidenceGraphEdge(
                    id=f"EDGE-CORR-{r_idx}",
                    source=corr_node_id,
                    target=decision_node_id,
                    relationship="CORROBORATES"
                ))

        # Add safe remediation recommendations
        safe_actions = getattr(result, "safe_remediation_actions", []) or []
        for a_idx, action in enumerate(safe_actions):
            act_id = getattr(action, "action_id", f"ACT-{a_idx}")
            act_node_id = f"NODE-ACTION-{act_id}"
            graph.nodes.append(EvidenceGraphNode(
                id=act_node_id,
                node_type="RECOMMENDATION",
                label=f"Action: {getattr(action, 'action_type', 'REMEDIATE')}",
                device_id=getattr(action, "target_device", None),
                severity="INFO",
                metadata={"description": getattr(action, "description", "")}
            ))
            graph.edges.append(EvidenceGraphEdge(
                id=f"EDGE-RESOLVES-{a_idx}",
                source=decision_node_id,
                target=act_node_id,
                relationship="RESOLVES"
            ))

        return graph

    def export_cytoscape_elements(self) -> List[Dict[str, Any]]:
        """Export elements formatted for Cytoscape.js or Vis.js canvas."""
        elements: List[Dict[str, Any]] = []
        for n in self.nodes:
            elements.append({
                "data": {
                    "id": n.id,
                    "label": n.label,
                    "node_type": n.node_type,
                    "device_id": n.device_id,
                    "severity": n.severity,
                    **n.metadata
                }
            })
        for e in self.edges:
            elements.append({
                "data": {
                    "id": e.id,
                    "source": e.source,
                    "target": e.target,
                    "relationship": e.relationship,
                    "weight": e.weight
                }
            })
        return elements

    def is_acyclic(self) -> bool:
        """Verify the graph contains no cycles (strict DAG property)."""
        adjacency: Dict[str, List[str]] = {n.id: [] for n in self.nodes}
        for e in self.edges:
            if e.source in adjacency:
                adjacency[e.source].append(e.target)

        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbor in adjacency.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            rec_stack.remove(node)
            return False

        for node in adjacency:
            if node not in visited:
                if dfs(node):
                    return False
        return True
