# Operations Dashboard — Full Integration Report

## 1. Overview & 5-View Architecture
The NetCoop AI Operations Dashboard provides a high-fidelity, real-time command center interface for campus network operators. It is served via FastAPI (`web/server.py`) and a modern HTML5/CSS3/JavaScript interface (`web/index.html`).

---

## 2. The 5 Interactive Views

### View 1: NOC Overview
- Real-time campus health score gauge (0-100%).
- Device health status distribution (Healthy, Warning, Critical).
- Active alerts panel with EWMA drift indicators.
- Campus device inventory table with roles, locations, and IPs.

### View 2: Interactive Topology Explorer
- Campus core-to-edge hierarchical network visualization.
- Node inspection showing device role, tier, and live metrics.
- Blast radius highlighting displaying dependent downstream nodes.

### View 3: Agent Activity Timeline
- Honeycomb-style multi-agent swimlanes.
- Real-time display of AMP/2.0 messages from the live `orchestrator.message_bus`.
- Chronological breakdown of dispatches, domain findings, peer challenges, and corroborations.

### View 4: Incident Investigation & Evidence Graph
- Diagnostic summary card with root cause, calibrated confidence, and accepted rationale.
- Reasoning drawer displaying rejected alternatives and specific counter-evidence.
- Interactive Evidence Lineage DAG powered by Cytoscape/Vis.js elements.

### View 5: Remediation Simulation & Recovery Gate
- Interactive dry-run CLI window showing simulated switch commands and rollback plans.
- Before vs projected-after KPI comparison cards (queue drops, latency, packet loss).
- Cryptographic operator approval gate requiring HMAC token authorization.

---

## 3. Live API Binding

The dashboard is directly bound to the production orchestrator:
- `GET /api/health`: Calibration model and agent status.
- `GET /api/overview`: Campus inventory and operational health.
- `GET /api/topology`: Hierarchical campus graph.
- `GET /api/agent-activity`: Live AMP/2.0 message bus audit trail.
- `POST /api/diagnose`: Full end-to-end diagnosis and DAG generation.
- `POST /api/simulate-remediation`: Remediation action simulation.
- `POST /api/verify-recovery`: Post-action recovery verification.

---

## 4. Verification Evidence

- 8/8 tests pass in `test_dashboard_api.py`.
- Verified live integration with `OrchestrationResult.evidence_graph` and `OrchestrationResult.protocol_audit_trail`.
