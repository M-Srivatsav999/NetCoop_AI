# Evidence Graph & Lineage DAG — Integration Report

## 1. Overview & Forensic Auditability
To satisfy strict operational safety requirements and hackathon explainability benchmarks, every diagnosis produced by NetCoop AI is backed by an auditable, directed acyclic graph (DAG). The **Evidence Graph** traces the entire diagnostic lifecycle:
$$\text{Raw Telemetry} \longrightarrow \text{Domain Findings} \longrightarrow \text{Candidate Hypotheses} \longrightarrow \text{Peer Reviews} \longrightarrow \text{Arbiter Adjudication} \longrightarrow \text{Remediation Actions}$$

---

## 2. Relational Taxonomy & Node Types

### Node Types (`EvidenceNodeType`)
- `RAW_TELEMETRY`: Physical device metric observations.
- `NORMALIZED_OBSERVATION`: Schema-standardized CIM records.
- `AGENT_FINDING`: Specialized domain analysis.
- `HYPOTHESIS`: Evaluated failure modes.
- `PEER_CHALLENGE`: Formal inter-agent disputes.
- `PEER_CORROBORATION`: Cross-domain corroborations.
- `ARBITER_DECISION`: Supreme Arbiter ruling.
- `RECOMMENDATION`: Safe operational checks and remediation actions.
- `SIMULATION`: Dry-run CLI execution projections.
- `RECOVERY_VERIFICATION`: Measured post-action physical verification.

### Relationships (`EvidenceRelationship`)
- `DERIVED_FROM`: Provenance lineage link.
- `MEASURES`: Telemetry counter extraction.
- `PRODUCES`: Agent finding output.
- `SUPPORTS`: Corroborating evidence link.
- `CONTRADICTS`: Contradictory evidence link.
- `CHALLENGES`: Peer dispute link.
- `CORROBORATES`: Independent confirmation link.
- `DEPENDS_ON`: Topological or causal predecessor link.
- `AFFECTS`: Blast radius link.
- `RESOLVES`: Corrective action link.
- `INFORMS_ARBITRATION`: Finding submitted to Arbiter.
- `ADJUDICATES`: Arbiter ruling on challenge or hypothesis.

---

## 3. Strict Acyclicity Guarantee (`is_acyclic()`)

Every generated Evidence Graph is validated via Depth-First Search (DFS) cycle detection:
- Uses three-color recursion stack tracking.
- Guarantees $O(V + E)$ cycle verification.
- **Verification Invariant**: `graph.is_acyclic() == True` is validated on 100% of generated graphs.

---

## 4. UI & Cytoscape.js Export

The engine natively exports elements formatted for front-end graph visualizers (Cytoscape.js, D3.js, Vis.js):
```python
elements = graph.export_cytoscape_elements()
```
Exposed via the `/api/diagnose` REST endpoint and rendered in the NOC Dashboard's Interactive Evidence DAG tab.
