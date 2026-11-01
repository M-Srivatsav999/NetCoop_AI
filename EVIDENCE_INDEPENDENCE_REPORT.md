# NetCoop AI — Evidence Independence, Provenance Lineage & De-Biasing Report

## Executive Summary
In multi-agent diagnostic platforms, an insidious failure mode is **evidence double-counting** and **confidence inflation caused by copycat agents**. If multiple specialized agents observe the exact same underlying telemetry datum (e.g. packet loss on an access switch) and independently submit supportive evidence items, a naive weighted-sum arbitrator treats them as separate independent confirmations, artificially inflating diagnostic confidence.

NetCoop AI implements an evidential provenance and independence engine that:
1. Tracks full evidentiary lineage (`telemetry_source_id`, `derivation_method`, `source_lineage`, `independence_group`).
2. Clusters corroborating signals by physical measurement source.
3. Discounts redundant derivative observations by **90%**, enforcing strict evidential de-biasing.

---

## 1. Provenance Lineage Architecture

Every atomic finding in NetCoop AI is represented by an immutable `EvidenceItem` possessing four explicit provenance attributes:

```python
class EvidenceItem(BaseModel):
    evidence_id: str
    source_agent: str
    device_id: str
    metric_name: str
    observed_value: Any
    severity: SeverityLevel
    polarity: EvidencePolarity
    hypothesis_target: str
    weight: float                     # Baseline expert rule weight (0.0 to 1.0)
    description: str
    telemetry_source_id: str          # Cryptographic SHA-256 fingerprint of source telemetry
    derivation_method: str            # DIRECT_MEASUREMENT | DERIVED_STATISTIC | CROSS_DEVICE_INFERENCE
    source_lineage: List[str]         # Processing chain (e.g., ['SW-MHR.metrics', 'TelemetryAgent'])
    independence_group: str           # Unique clustering key: {device_id}:{metric_name}:{source_id}
```

### Derivation Taxonomy
- `DIRECT_MEASUREMENT`: Raw physical sensor counter (e.g., interface drops, optic dBm, CPU tick counters).
- `DERIVED_STATISTIC`: Computed time-series moving averages or percentiles.
- `CROSS_DEVICE_INFERENCE`: Downstream path propagation or topology neighbor correlation.
- `AGENT_REPRESENTATION`: Normalized interoperability schema interpretation.

---

## 2. Mathematical De-Biasing Formulation

Let $\mathcal{E}_H = \{e_1, e_2, \dots, e_n\}$ be the set of all supporting evidence items for hypothesis $H$.

We partition $\mathcal{E}_H$ into disjoint **Independence Groups** $\mathcal{G}_1, \mathcal{G}_2, \dots, \mathcal{G}_k$ such that all evidence items within group $\mathcal{G}_j$ share the same physical sensor source:
$$\mathcal{G}_j = \{e \in \mathcal{E}_H \mid \text{independence\_group}(e) = \text{key}_j\}$$

For each group $\mathcal{G}_j$, the primary observation contributes its full weight, while duplicate or derivative observations receive a severe diminishing return discount factor $\alpha = 0.10$:

$$w^*(\mathcal{G}_j) = \max_{e \in \mathcal{G}_j}(w_e) + \alpha \sum_{e \in \mathcal{G}_j \setminus \{e_{\max}\}} w_e$$

The net evidentiary support for hypothesis $H$ is computed strictly across independent groups:

$$W_{\text{support}}(H) = \sum_{j=1}^k w^*(\mathcal{G}_j)$$

$$S_{\text{net}}(H) = \max\left(0, W_{\text{support}}(H) - 1.20 \cdot W_{\text{contra}}(H)\right)$$

### Evidential Proof
1. **Case A (Copycat Inflation Attack)**:
   - Agent 1 reports `latency_ms = 180.0` with weight $0.85$.
   - Copycat Agent 2 re-reports `latency_ms = 180.0` with weight $0.85$ from identical `telemetry_source_id`.
   - Both belong to $\mathcal{G} = \{\text{SW-MHR:latency\_ms:SNAP-001}\}$.
   - Naive Support Weight: $0.85 + 0.85 = 1.70$ (False confidence inflation).
   - **NetCoop AI De-Biased Support Weight**: $0.85 + 0.10 \times 0.85 = \mathbf{0.935}$ (Inflation neutralized).

2. **Case B (Truly Independent Corroboration)**:
   - Metric 1: Ping RTT latency on `SW-MHR` ($w = 0.85$, Group: `SW-MHR:latency_ms:SNAP-001`).
   - Metric 2: Hardware Queue Drops on `SW-MHR` ($w = 0.90$, Group: `SW-MHR:queue_drops:SNAP-001`).
   - Metric 3: Upstream neighbor switch latency on `CORE-SW-01` ($w = 0.80$, Group: `CORE-SW-01:latency_ms:SNAP-002`).
   - All 3 items belong to **distinct independence groups**.
   - **NetCoop AI De-Biased Support Weight**: $0.85 + 0.90 + 0.80 = \mathbf{2.55}$ (Full corroborative credit granted).

---

## 3. Verification & Acceptance
All four test suites in `evaluation/test_evidence_independence.py` pass with 100% compliance:
- `test_evidence_item_lineage_and_default_grouping`: **PASS**
- `test_copycat_agent_discounting_prevents_inflation`: **PASS**
- `test_independent_measurements_receive_full_corroboration`: **PASS**
- `test_canonical_telemetry_source_id_deterministic`: **PASS**
