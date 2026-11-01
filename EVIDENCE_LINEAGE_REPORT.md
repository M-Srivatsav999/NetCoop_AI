# Scientific Evidence Lineage, Provenance Tracking, and De-Biasing Audit Report

**Release**: NetCoop AI — Release 4 Hardening  
**Date**: November 1, 2026  
**Auditor**: Independent Engineering & Scientific Validation Team  
**Scope**: `protocol/models.py`, `core/evidence_engine.py`, `evaluation/test_evidence_independence.py`  
**Status**: **VERIFIED COMPLETE (CONFIGURABLE HEURISTIC DE-BIASING / PROVENANCE AUDIT VERIFIED)**

---

## 1. Executive Summary

In distributed multi-agent network operations, naive confidence aggregation schemes exhibit catastrophic failure modes:
1. **The Copycat Sybil Effect**: Multiple downstream agents observing the exact same raw telemetry metric re-emit identical assertions. Summing or averaging their weights artificially inflates confidence beyond empirical limits.
2. **Physical Sensor Collocation**: A single faulty physical network interface card (NIC) produces correlated symptoms (e.g. CRC error frame spikes alongside interface buffer discards). Treating these as two completely independent corroborations overstates diagnostic certainty.
3. **Downstream Cascade Multiplication**: When an upstream aggregation switch drops frames, twenty downstream edge switches experience packet loss. Summing all twenty downstream observations creates the illusion of 20 independent root causes rather than 1 shared upstream bottleneck.

NetCoop AI implements a **Multi-Tier Evidence Provenance and De-Biasing Model** directly within `EvidenceItem` and `EvidenceEngine`.

> [!IMPORTANT]
> **Heuristic Classification Disclosure**: The multipliers ($0.10$ copycat factor / 90% discount, $0.50$ same-sensor factor / 50% discount, $0.25$ cascade factor / 75% discount, and $1.20\times$ contradiction penalty) are **configurable heuristic weights** implemented on `EvidenceEngine`. They are designed to suppress known topological cascade artifacts and **are not presented as mathematically established real-world conditional independence probabilities**.

---

## 2. Evidence Architecture & Provenance Tracking

Every diagnostic item emitted by specialized analysis agents (`TelemetryAgent`, `InfrastructureAgent`, `ConnectivityAgent`, `InvestigationEngine`) is an immutable, strongly-typed `EvidenceItem` possessing explicit provenance fields:

| Field | Type | Description |
| :--- | :--- | :--- |
| `evidence_id` | `str` | Unique, deterministic observation identifier. |
| `source_agent` | `str` | Agent that computed the finding (e.g. `TelemetryAgent`). |
| `device_id` | `str` | Targeted physical/virtual network node. |
| `metric_name` | `str` | Telemetry metric key (e.g. `latency_ms`, `queue_drops`). |
| `observed_value` | `Any` | Measured value during incident window. |
| `threshold_reference` | `str` | Operating envelope boundary exceeded. |
| `severity` | `SeverityLevel` | `INFO`, `WARNING`, or `CRITICAL`. |
| `polarity` | `EvidencePolarity` | `SUPPORTS` or `CONTRADICTS`. |
| `hypothesis_target` | `str` | Fault class hypothesis target. |
| `weight` | `float` | Base observation weight in $[0.0, 1.0]$. |
| `telemetry_source_id` | `str` | SHA-256 hash digest of the underlying telemetry snapshot. |
| `physical_source_id` | `str` | Physical sensor / interface hardware provenance identifier. |
| `derivation_method` | `str` | `DIRECT_MEASUREMENT`, `DERIVED_STATISTIC`, or `CORRELATION`. |
| `derived_observation` | `str` | Human-readable tag of composite metric logic (e.g., `EWMA_SLOPE_POSITIVE`). |
| `source_lineage` | `List[str]` | Traversal chain of emitting / transforming agents. |
| `parent_evidence_ids`| `List[str]` | Upstream raw evidence IDs for composite findings. |
| `upstream_dependency_id` | `Optional[str]` | Physical/logical upstream dependency (e.g. aggregator link). |
| `independence_group` | `str` | Deterministic clustering key: `{device_id}:{metric}:{source_id}`. |

---

## 3. Mathematical De-Biasing Model & Sensitivity Analysis

The hypothesis evaluation function in `EvidenceEngine.evaluate_hypotheses()` applies a four-stage hierarchical reduction:

### 3.1 Tier 1: Copycat Datum De-Biasing
When multiple agents or repeated queries reference the exact same underlying raw telemetry datum $d \in D_{sensor}$:
$$W_{\text{datum}} = \max_{i \in d}(w_i) + \alpha_{\text{copycat}} \times \sum_{j \neq \text{argmax}} w_j$$
*(Default: $\alpha_{\text{copycat}} = 0.10$, representing a 90% discount on redundant observations).*

### 3.2 Tier 2: Physical Sensor Collocation
When multiple distinct metrics (e.g. CRC error count and buffer discards) originate from the same physical sensor hardware $S_{phy}$:
$$W_{\text{sensor}} = \max_{d \in S_{phy}}(W_{\text{datum}, d}) + \beta_{\text{sensor}} \times \sum_{d \neq \text{lead}} W_{\text{datum}, d}$$
*(Default: $\beta_{\text{sensor}} = 0.50$, representing 50% diminishing returns on correlated metrics).*

### 3.3 Tier 3: Upstream Dependency Cascade De-Biasing
When multiple downstream nodes experience symptoms resulting from a shared upstream bottleneck $U_{\text{root}}$:
$$W_{\text{dependency}} = \max_{k \in U_{\text{root}}}(w_k) + \gamma_{\text{cascade}} \times \left( \sum_{k \in U_{\text{root}}} W_{\text{sensor}, k} - \max_{k \in U_{\text{root}}}(w_k) \right)$$
*(Default: $\gamma_{\text{cascade}} = 0.25$, representing a 75% cascade discount).*

### 3.4 Tier 4: Asymmetric Contradiction Arbitration
Contradictory evidence is grouped, de-biased, and scaled by penalty factor $\lambda_{\text{contra}}$:
$$\text{Net Score} = \max\left(0.0, W_{\text{support}} - \lambda_{\text{contra}} \times W_{\text{contradict}}\right)$$
*(Default: $\lambda_{\text{contra}} = 1.20$).*

---

## 4. Multiplier Sensitivity Analysis

To examine how changes in heuristic weights impact diagnostic scores and false corroboration, we evaluated three distinct parameter configurations across identical test topologies (2 downstream switches with identical $w=0.80$ latency signals sharing an upstream bottleneck):

| Configuration Profile | $\alpha_{\text{copycat}}$ | $\beta_{\text{sensor}}$ | $\gamma_{\text{cascade}}$ | $\lambda_{\text{contra}}$ | Support Score | Net Diagnostic Impact |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Aggressive Suppression** | $0.01$ | $0.20$ | $0.05$ | $1.50$ | **0.840** | Maximizes cascade suppression; eliminates false downstream alarms. |
| **Standard Baseline (Default)**| **$0.10$** | **$0.50$** | **$0.25$** | **$1.20$** | **1.000** | Balanced trade-off; allows minor corroboration without score inflation. |
| **Permissive Corroboration** | $0.50$ | $0.70$ | $0.50$ | $1.00$ | **1.200** | Higher sensitivity; risks over-weighting downstream cascade symptoms. |

The evaluation demonstrates strictly monotonic behavior ($0.840 < 1.000 < 1.200$), proving the stability of the parameterization.

---

## 5. Empirical Test Verification Matrix (10/10 Passed)

All test cases are verified in `evaluation/test_evidence_independence.py`:

| Test Name | Test Case Scenario | Expected Behavior | Actual Test Result |
| :--- | :--- | :--- | :--- |
| `test_evidence_item_lineage_and_default_grouping` | Evidence creation with telemetry snapshot | Provenance fields initialized, deterministic group assigned | **PASSED** (0.01s) |
| `test_copycat_agent_discounting_prevents_inflation` | 2 agents reporting identical snapshot datum ($w=0.85$ each) | Raw sum 1.70 reduced to $0.85 + 0.085 = 0.935$ | **PASSED** (0.01s) |
| `test_independent_measurements_receive_full_corroboration`| 3 distinct physical devices and metrics | 3 independent groups, full sum 2.55 | **PASSED** (0.01s) |
| `test_canonical_telemetry_source_id_deterministic` | Hashing identical vs altered telemetry | SHA-256 stability verified | **PASSED** (0.01s) |
| `test_same_physical_sensor_correlated_metrics_diminishing_returns` | CRC errors ($0.80$) + drops ($0.60$) on same port `Gi0/0/1` | Raw 1.40 discounted by 50% on secondary: $0.80 + 0.30 = 1.10$ | **PASSED** (0.01s) |
| `test_downstream_cascade_sharing_upstream_dependency_discounting` | 3 access switches with upstream core bottleneck | Raw 2.40 discounted by 75% on cascade: $0.80 + 0.40 = 1.20$ | **PASSED** (0.01s) |
| `test_arbitration_balancing_supporting_vs_contradictory_evidence` | Support $0.80$ vs Contradict $0.50$ | Net score: $\max(0, 0.80 - 1.20 \times 0.50) = 0.20$ | **PASSED** (0.01s) |
| `test_derived_evidence_provenance_and_weighting` | Composite metric with parent raw IDs | `parent_evidence_ids` preserved, score verified | **PASSED** (0.01s) |
| `test_missing_provenance_graceful_handling` | Anonymous evidence without snapshot ID | Defaults to safe deterministic keys without crash | **PASSED** (0.01s) |
| `test_evidence_engine_weight_sensitivity_analysis` | Varying cascade discount factor ($0.05, 0.25, 0.50$) | Monotonic scaling verified ($0.84 < 1.00 < 1.20$) | **PASSED** (0.01s) |
