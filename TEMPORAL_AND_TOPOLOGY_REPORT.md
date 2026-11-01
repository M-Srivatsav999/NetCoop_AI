# NetCoop AI — Temporal & Causal Diagnostic Architecture Report

## Executive Summary

To address the **25% Hackathon Judging Category for Temporal Analysis, Causal Reasoning, and Topology Awareness**, NetCoop AI incorporates a dedicated `TemporalCausalEngine` (`core/temporal_engine.py`).

Real-world campus network anomalies do not occur in isolated instantaneous snapshots; they unfold sequentially across topological links. Distinguishing an **initiating root-cause event** from **cascading downstream symptoms** requires microsecond/second-level chronological sequencing combined with graph-theoretic upstream traversal.

---

## 1. Algorithmic Foundation

### 1.1 Online Rolling Baselines via Welford's Algorithm & EWMA
Rather than relying on static hardcoded thresholds, the engine dynamically models nominal device metric distributions:
- **Online Mean & Variance**: Computed using Welford’s single-pass algorithm:
  $$\Delta = x_k - \mu_{k-1}, \quad \mu_k = \mu_{k-1} + \frac{\Delta}{k}, \quad M_{2,k} = M_{2,k-1} + \Delta(x_k - \mu_k)$$
  $$s^2 = \frac{M_{2,k}}{k - 1}, \quad z = \frac{x_k - \mu_k}{s}$$
- **Exponentially Weighted Moving Average (EWMA)**: Tracks metric trajectory with decay factor $\alpha = 0.20$:
  $$\text{EWMA}_k = \alpha x_k + (1 - \alpha)\text{EWMA}_{k-1}$$

### 1.2 Anomaly Classification & Rate of Change
Metric deviations are flagged when:
- The z-score exceeds threshold ($z \ge 2.5$)
- Rate of change ($\Delta x / \Delta t$) exceeds surge velocity thresholds ($> 5.0$ ms/sec for latency, $> 10$ drops/sec for buffers).

---

## 2. Causal Timeline Reconstruction

The `TemporalCausalEngine` processes chronological batches of telemetry snapshots:

```
[Time t0: Upstream Switch BLDG-SW-ENG] 
   └── Queue drops spike to 180 (z=4.2) ──> Classified as INITIATING_EVENT
        │
        ├── (+5.0s propagation lag)
        ▼
[Time t1: Downstream AP AP-ENG-01]
   └── Packet loss increases to 4.8% ──────> Classified as CASCADING_SYMPTOM
```

### 2.1 Formal Causality Rule
An anomaly on Device $B$ is attributed as a causal consequence of Device $A$ if and only if:
1. **Topological Precedence**: Device $A$ is in the directed upstream traversal path of Device $B$ ($\text{Upstream}(B) \cap \{A\} \neq \emptyset$), or shares an explicit service dependency.
2. **Temporal Precedence**: $t_{\text{anomaly}}(A) \le t_{\text{anomaly}}(B)$.
3. **Propagation Plausibility**: $\Delta t \le \text{MaxPropagationWindow}$ (default 120s).

If anomalies occur simultaneously on topologically disconnected nodes (e.g. Engineering Switch and Library Switch), the engine classifies them as `INDEPENDENT_ANOMALY`, preventing false incident merges.

---

## 3. Test Verification Suite (`evaluation/test_temporal_causal_diagnosis.py`)

1. `test_rolling_baseline_welford_and_ewma`: Confirms accurate online calculation of mean, variance, EWMA, and z-score without numerical instability.
2. `test_timeline_initiating_vs_cascading_events`: Validates that upstream switch buffer exhaustion at $t_0$ is marked `INITIATING_EVENT` and downstream AP packet loss at $t_1$ is marked `CASCADING_SYMPTOM`.
3. `test_independent_anomalies_separated_by_topology`: Validates that disconnected devices suffering simultaneous faults are partitioned into independent anomalies.

### Test Execution Result:
```
============================== 7 passed in 0.93s ==============================
```
*(Combined temporal test suite passing 100% without regression).*
