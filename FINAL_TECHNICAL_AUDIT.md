# NetCoop AI — Pre-Implementation Technical Audit

**Audit Date**: 2026-11-01  
**Project**: NetCoop AI (Autonomous Multi-Agent Campus Network Fault Diagnosis)  
**Baseline Test Suite**: 79/79 passed in 2.03s  
**Working Tree Status**: Clean (Git commit `ee2054b`)  

---

## 1. Executive Summary

This independent technical audit was conducted on the active NetCoop AI codebase prior to making modifications. While the system demonstrates exceptional engineering foundations (79 unit tests, 15 scenarios, multi-agent arbitration, cryptographically chained evidence ledger, PAVA isotonic confidence calibration, and deterministic conflict resolution), several critical weaknesses remain that would be flagged by expert judges in a rigorous hackathon evaluation.

---

## 2. Priority 1: MCP Server & External Interoperability Audit

### Current Findings:
1. **Mocked/Direct-Invocation Testing**: `evaluation/test_independent_protocol_client.py` does not spawn an external process. It instantiates `NetCoopMCPServer()` in-process and calls `server.handle_json_rpc(...)` directly.
2. **Missing Subprocess Transport Validation**: Standard MCP operates over asynchronous stdio (or SSE). The stdio communication loop in `mcp_server.py:run_stdio()` has never been tested against an independent external client subprocess sending JSON-RPC 2.0 frames over `stdin` and reading `stdout`.
3. **MCP Protocol Conformance**:
   - `initialize` handshake returns `protocolVersion: "2024-11-05"`, but does not handle client capability negotiation or notifications (e.g., `notifications/initialized`).
   - Tool call outputs wrap responses in `{"content": [{"type": "text", "text": "..."}]}`, which conforms to standard MCP, but tool schemas lack strict input validation for invalid or missing types on raw stdin.
4. **Clean Process Termination**: There is no automated test confirming the server process shuts down cleanly when stdin EOF is sent or SIGTERM is delivered.

### Required Upgrades:
- Create an end-to-end integration test (`evaluation/test_mcp_real_subprocess.py`) that uses Python's `subprocess.Popen` to launch `mcp_server.py` in a separate process with non-blocking pipes.
- Implement full handshake (`initialize` -> `notifications/initialized` -> `tools/list` -> `tools/call` -> shutdown).
- Validate response parsing, error codes (`-32600`, `-32601`, `-32602`), and structured telemetry diagnosis through true IPC.

---

## 3. Priority 2: Benchmark Independence & Generalization Audit

### Current Findings:
1. **Procedural Generation Confounding**: Both `evaluation/dataset_generator.py` (700 cases) and `evaluation/held_out_benchmark.py` (210 cases) rely on synthetic parametric generators with fixed metric boundaries (e.g. `latency > 40`, `queue_drops > 20`).
2. **Shared Generator Assumptions**: Although `held_out_benchmark.py` uses seed `9999` and new campus facility names, the underlying fault generation templates match the diagnostic rules of the `EvidenceEngine`.
3. **Lack of Hand-Authored Challenge Cases**: The test suite lacks a curated, human-authored edge-case suite designed specifically to challenge the rule engine (e.g. bufferbloat vs speed-of-light propagation delay, asymmetric routing, high-utilization streaming without loss, and transient flaps).
4. **Reporting Completeness**: The current benchmark reports Top-1 accuracy, Macro-F1, Brier, and ECE, but omits Top-3 accuracy, per-class false-positive/false-negative distributions, and incident clustering F1.

### Required Upgrades:
- Author a dedicated, frozen challenge suite (`data/challenge_dataset.json` and `evaluation/challenge_benchmark.py`) with 50 manually crafted adversarial scenarios reviewed independently of rule thresholds.
- Add comprehensive metric evaluation: Top-1 vs Top-3 accuracy, FPR, FNR, clustering F1, and abstention precision/recall.

---

## 4. Priority 3: Evidence Independence & Lineage Audit

### Current Findings:
1. **Evidence Duplication Vulnerability**: In `core/orchestrator.py` and `agents/correlation_agent.py`, findings from multiple agents analyzing the *exact same* raw telemetry record (e.g. `BLDG-SW-ENG` packet loss observed by `TelemetryAgent` and CPU analyzed by `InfrastructureAgent`) can be treated as separate corroborating signals for a fault domain.
2. **Missing Evidence Lineage Metadata**: While `EvidenceItem` has `source_agent`, `device_id`, and `metric_name`, it lacks:
   - `telemetry_source_id` (the raw sample hash/ID it was derived from)
   - `derivation_method` (direct threshold, trend, correlation)
   - `source_lineage` (upstream device vs endpoint)
   - `independence_group`
3. **Correlation Agent Aggregation**: If two agents report findings on the same metric from the same snapshot, the weight should be de-duplicated or discounted to prevent artificial confidence inflation.

### Required Upgrades:
- Enhance `EvidenceItem` in `protocol/models.py` with explicit lineage fields (`telemetry_source_id`, `derivation_method`, `source_lineage`, `independence_group`).
- Update `CorrelationAgent` to group evidence by `(device_id, telemetry_source_id)` and calculate an *Evidence Independence Discount Factor*, preventing circular corroboration from inflating calibrated confidence.

---

## 5. Priority 4: Confidence Calibration & Model Provenance Audit

### Current Findings:
1. **Single Application Verification**: We verified that `CorrelationAgent` applies `calibrate_confidence()` and benchmark runners consume `report.confidence`. However, there is no explicit runtime assertion preventing double-calibration if an external caller calls `calibrate_confidence(report.confidence)`.
2. **Provenance Documentation**: `data/calibration_dataset.json` (200 samples) and `data/calibration_model.json` were generated, but the system needs an explicit fallback policy if the JSON model file is missing or corrupted on disk, raising an auditable warning rather than silently reverting to uncalibrated defaults.
3. **Synthetic Limitation Notice**: Confidence calibration maps heuristic scores to empirical frequencies *within the synthetic generator distribution*, which may differ from real-world campus traffic dynamics. This limitation must be explicitly exposed in the API and reports.

### Required Upgrades:
- Add double-calibration protection flag on `ArbitrationResult` / `UnifiedIncidentReport`.
- Add explicit error logging and fallback transparency when `calibration_model.json` is missing.
- Exclude calibrated scores from being described as "ground-truth Bayesian real-world probabilities", framing them defensibly as "PAVA-calibrated empirical validation confidences".

---

## 6. Priority 5: Remediation Safety & Lifecycle State Machine Audit

### Current Findings:
1. **Simplified Lifecycle States**: `core/remediation.py` currently has `SIMULATED`, `SIMULATED_RECOVERY_VERIFIED`, and `ROLLBACK_RECOMMENDED`.
2. **Missing Granular States**: It lacks the full production safety lifecycle requested:
   - `RECOMMENDED`
   - `SIMULATED`
   - `APPROVAL_PENDING`
   - `APPROVED`
   - `REAL_EXECUTION_PENDING`
   - `REAL_EXECUTED`
   - `SIMULATED_RECOVERY_VERIFIED`
   - `REAL_RECOVERY_VERIFIED`
   - `FAILED`
   - `ROLLBACK_RECOMMENDED`
3. **Execution Boundary**: In an academic prototype, `REAL_EXECUTED` must be strictly disabled with an explicit safety guard (`ExecutionSafetyGuardError`) to prevent accidental command dispatch to real campus infrastructure.

### Required Upgrades:
- Implement a formal `RemediationLifecycleStateMachine` with explicit valid/invalid state transitions.
- Enforce strict separation between simulated dry-run projections and real measured telemetry recovery.

---

## 7. Priority 6: Verification Pipeline & Runner Audit

### Current Findings:
1. **Report Cache Dependency**: In `verify_all.py`, if a benchmark runner fails silently or produces malformed JSON, the script could potentially read an older pre-existing report on disk.
2. **Run-Time Freshness Check**: The audit does not verify that the timestamp inside `benchmark_report.json` was generated within the active execution window of `verify_all.py`.
3. **Test Result Distinctions**: Skipped tests are not explicitly tracked separately from passing tests in the audit output table.

### Required Upgrades:
- Update `verify_all.py` to remove stale JSON reports prior to execution, generate fresh timestamped reports, verify execution UUIDs, and enforce that timestamps match the current execution run.

---

## 8. Prioritized Implementation Roadmap

1. **Phase 1**: True External Process MCP Subprocess Integration & Conformance Test.
2. **Phase 2**: Evidence Provenance, Lineage Tracking, and Shared-Source De-biasing.
3. **Phase 3**: Strict Remediation Lifecycle State Machine & Execution Safety Guard.
4. **Phase 4**: Curated Hand-Authored Challenge Benchmark (50 scenarios) & Independence Analysis.
5. **Phase 5**: Verification Pipeline Hardening (Freshness, Non-Cached Execution).
6. **Phase 6**: Comprehensive Regression Testing (ensure 79/79 existing tests pass + new test suites).
7. **Phase 7**: Final Technical & Benchmark Documentation Reports.
