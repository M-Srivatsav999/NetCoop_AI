# Temporal & Causal Reasoning — Integration Report

## 1. Overview & Hackathon Alignment
- **Evaluation Category**: Temporal & Causal Reasoning (25% weighting).
- **Core Engine**: `TemporalCausalEngine` (`core/temporal_engine.py`).
- **Integration Status**: Fully wired into `NetworkIntelligenceOrchestrator.process()`. Processes incoming telemetry batches chronologically, computes statistical baselines via Welford's algorithm, and passes temporal event classifications to `ArbiterAgent`.

---

## 2. Temporal & Causal Principles

### 2.1 Chronological Microsecond/Second-Level Event Ordering
- Incoming telemetry is sorted strictly chronologically by timestamp.
- Out-of-order records are placed into proper temporal alignment before anomaly detection.

### 2.2 Initiating Event vs Cascading Downstream Symptoms
- **Core Principle**: Correlation does not imply causation without temporal and topological precedence.
- **Classification Taxonomy**:
  1. `INITIATING_EVENT`: The earliest detected anomaly on the timeline located on an upstream topological node.
  2. `CASCADING_SYMPTOM`: Downstream anomalies that occur after or simultaneously with an upstream failure along the forwarding path.
  3. `INDEPENDENT_ANOMALY`: Anomalies in disconnected topological domains occurring concurrently.
  4. `RECOVERY`: Physical counters returning within nominal baseline thresholds.
  5. `STEADY_STATE`: Metrics fluctuating within normal statistical envelopes.

### 2.3 Rolling Baseline & Statistical Drift (EWMA + Welford's Algorithm)
- Online calculation of mean $\mu$, variance $\sigma^2$, and EWMA decay ($\alpha = 0.20$):
  $$\delta_k = x_k - \mu_{k-1}, \quad \mu_k = \mu_{k-1} + \frac{\delta_k}{k}, \quad M_{2,k} = M_{2,k-1} + \delta_k(x_k - \mu_k)$$
- Anomalies are flagged when z-score $z = \frac{x - \mu}{\sigma} \ge 2.5$ or upon exceeding critical hard physical thresholds (e.g., packet loss $> 2.0\%$, queue drops $> 20$).

---

## 3. Propagation Lag & Blast Radius Calculation

When an upstream initiating event is detected (e.g. `CORE-SW-01` experiencing buffer drops at $t_0$), downstream access switches (e.g. `DIST-SW-NORTH` experiencing packet loss at $t_1 = t_0 + \Delta t$) are annotated with propagation lag:
$$\text{propagation\_lag} = t_1 - t_0$$

The Arbiter uses this lag to discount downstream symptoms and identify the root cause at the upstream origin.

---

## 4. Verification Evidence

| Test Suite | Tests | Result | Verification Focus |
| :--- | :--- | :--- | :--- |
| `test_temporal_engine.py` | 4 | **PASS** | EWMA updating, Welford variance, initiating event classification, cascade lag |
| `test_temporal_causal_diagnosis.py` | 3 | **PASS** | Upstream switch precedence, simultaneous multi-building isolation, lag measurement |
| `test_end_to_end_scenarios.py` (Scenario 8) | 1 | **PASS** | Cascading blast radius verification on 2-tier network |
| `run_demo.py` | Demo A | **PASS** | Live propagation trace: `CORE-SW-01` ($t_0$) $\to$ `DIST-SW-NORTH` ($+3.00\text{s}$) |
