# NetCoop AI — Evidence Graph & Uncertainty Calibration Report

## Executive Summary

To ensure complete diagnostic defensibility against expert hackathon scrutiny, NetCoop AI implements an **interactive Evidence Graph DAG engine** (`core/evidence_graph.py`) paired with an **isotonic probability calibration pipeline** (`core/confidence_engine.py`).

Every diagnostic claim issued by the Arbiter is traceable back through peer reviews, domain agent findings, and normalized physical sensor metrics, eliminating the "black-box" risk of generative LLMs or heuristic guesses.

---

## 1. Evidence Lineage Graph Architecture (`core/evidence_graph.py`)

### 1.1 Structural Invariants (Strict DAG)
The evidence lineage graph forms a directed acyclic graph (DAG):
$$\mathcal{G} = (\mathcal{V}, \mathcal{E})$$
where $\mathcal{V}$ consists of 5 typed node classes:
1. `RAW_TELEMETRY`: Hardware counters (latency, queue drops, CRC errors, dBm, CPU).
2. `AGENT_FINDING`: Domain observations produced by specialized agents.
3. `PEER_CHALLENGE`: Formal disputes raised across domain boundaries.
4. `PEER_CORROBORATION`: Corroborating physical observations from independent domains.
5. `ARBITRATION_DECISION`: The supreme diagnostic ruling issued by the ArbiterAgent.

The method `is_acyclic()` uses depth-first cycle detection to guarantee that evidence cannot depend circularity upon itself.

### 1.2 Interactive Frontend Export
The graph exports directly to standard Cytoscape.js and Vis.js JSON elements via `export_cytoscape_elements()`, allowing dynamic rendering in Screen 4 of the Network Operations Dashboard.

---

## 2. Confidence Calibration & Uncertainty Handling

### 2.1 Raw vs. Calibrated Probability
NetCoop AI explicitly separates:
- **Raw Heuristic Confidence**: Composite metric calculation reflecting signal-to-noise ratio:
  $$\text{RawConfidence} = \min\left(1.0, \frac{\text{SupportWeight}}{\max(1.0, \text{SupportWeight} + \text{ContraWeight})}\right)$$
- **Calibrated Probability**: Evaluated through Pool Adjacent Violators Algorithm (PAVA) fitted monotonic splines, correcting for heuristic overconfidence:
  $$P(\text{Correct} \mid \text{RawConfidence}) = f_{\text{isotonic}}(\text{RawConfidence})$$

### 2.2 Formal Abstention Thresholds
To avoid catastrophic false alarms, the Arbiter enforces 4 explicit diagnostic statuses:

| Status | Trigger Condition | Operational Action |
|:---|:---|:---|
| `DIAGNOSED` | Calibrated confidence $\ge 0.50$ with $\ge 2$ independent supporting signals. | Issue automated remediation plan and alerts. |
| `INCONCLUSIVE` | Confidence between $0.20$ and $0.49$; weak anomaly signals. | Trigger active diagnostic probes (ping, trace, SNMP re-poll). |
| `CONFLICTING_EVIDENCE` | Multiple strong competing signals with $\ge 2$ contradictory metrics. | Escalate to Tier-3 NOC engineer with peer review dossier. |
| `INSUFFICIENT_EVIDENCE` | Empty or non-anomalous telemetry ($< 0.20$ confidence). | Explicitly abstain; report 0.0% confidence to prevent false positive. |

---

## 3. Test Verification Suite (`evaluation/test_evidence_graph_and_uncertainty.py`)

1. `test_evidence_graph_construction_and_dag_invariants`: Verifies complete DAG generation from orchestration output and confirms cycle absence.
2. `test_evidence_graph_cytoscape_export`: Verifies schema compliance of exported node and edge elements for frontend rendering.

### Test Execution Result:
```
============================== 2 passed in 0.90s ==============================
```
