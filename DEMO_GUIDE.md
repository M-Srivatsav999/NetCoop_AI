# NetCoop AI — Official Demonstration Guide (Release 6.0)

## Overview & Architecture Context
NetCoop AI is an autonomous, evidence-driven, multi-agent fault diagnosis and intelligence platform engineered specifically for complex campus networks like IIT Bhubaneswar.

This guide provides a reproducible, step-by-step demonstration walkthrough for hackathon judges, systems architects, and NOC operators.

---

## Prerequisites & Quickstart
```bash
# Verify Python environment (Python 3.10+)
python --version

# Run the 11-step automated terminal demonstration
python evaluation/run_demo.py

# Launch the interactive Web Operations Console (NOC)
python web_ui.py
# Open http://127.0.0.1:8000 in your browser
```

---

## The 11-Step Demonstration Sequence

### Step 1 — Healthy Network Baseline Verification
- **Objective**: Prove the system accurately identifies nominal campus operating envelopes without generating false alarms.
- **Input**: Fresh telemetry on `CORE-SW-01` and `DIST-SW-NORTH` with 12ms latency, 0% loss, 0 queue drops, 0 CRC errors.
- **Observed Result**:
  - Diagnosed Status: `HEALTHY`
  - Root Cause: `NORMAL_OPERATION`
  - Calibrated Confidence: `100.0%`
  - Affected Devices: `[]` (None)

### Step 2 — Inject Controlled Network Fault
- **Objective**: Simulate a realistic core uplink buffer congestion incident.
- **Signature**: Egress queue buffer overflow (340 tail drops), elevated RTT (178.5ms), and 5.4% packet loss on `CORE-SW-01`.
- **Truthful Labeling**: Explicitly marked as `SIMULATED ENVIRONMENT (CAMPUS TESTBED)`.

### Step 3 — Multi-Agent Ingestion & Independent Analysis
- **Objective**: Demonstrate that specialized agents harvest domain-specific findings independently without manufactured consensus.
- **Observations**:
  - `TelemetryAgent`: Flags critical latency, jitter, and packet loss on both switches.
  - `InfrastructureAgent`: Flags critical CPU utilization and 340 egress queue drops on `CORE-SW-01`; reports `DIST-SW-NORTH` as healthy at the physical layer.
  - `ConnectivityAgent`: Evaluates topological adjacency and confirms aggregation uplink dependency.

### Step 4 — Multi-Agent Peer Review (Interrogation & Corroboration)
- **Objective**: Cross-examine findings across domain boundaries.
- **Mechanism**:
  - `InfrastructureAgent` independently corroborates `LINK_CONGESTION` on `CORE-SW-01` because buffer queue drops exist in the absence of physical CRC errors.
  - Physical errors would trigger a formal `PeerReviewChallenge` contesting congestion in favor of hardware transceiver damage.

### Step 5 — Temporal Causal Reasoning & Propagation Sequence
- **Objective**: Differentiate the root cause from subsequent downstream symptoms.
- **Timeline Analysis**:
  - `[INITIATING_EVENT]`: Packet loss and queue buildup at $t_0$ on `CORE-SW-01`.
  - `[CASCADING_SYMPTOM]`: Co-occurring latency on downstream `DIST-SW-NORTH` at $t_0 + 3.0\text{s}$.
  - Causal Direction: Upstream core initiates; downstream distribution switch experiences secondary propagation.

### Step 6 — Campus Topology Impact & Blast Radius Mapping
- **Objective**: Determine affected devices, topological dependencies, and single points of failure.
- **Output**:
  - Single Point of Failure: `CORE-SW-01` (Core Switch).
  - Blast Radius: 18 downstream devices across academic and administrative clusters (`DIST-SW-NORTH`, `DIST-SW-SOUTH`, `SRV-DNS-01`, `SRV-DHCP-01`, `BLDG-SW-ENG`, etc.).

### Step 7 — Supreme Arbiter Adjudication & Confidence Calibration
- **Objective**: Synthesize all evidence, score candidate hypotheses, and calibrate confidence.
- **Adjudication**:
  - Winner: `LINK_CONGESTION` (Net Score: 11.50, Calibrated Confidence: 100.0%).
  - Rejected Alternatives:
    - `RESOURCE_EXHAUSTION`: Subordinate score (1.45 vs 11.50).
    - `UPSTREAM_SWITCH_FAILURE`: Subordinate score (0.95 vs 11.50).
    - `HARDWARE_FAILURE`: Contradicted by clean interface error counters.

### Step 8 — Evidence Graph DAG Verification & Lineage
- **Objective**: Verify that every finding is linked through an acyclic lineage graph conforming to mathematical DAG properties.
- **Audit**:
  - Graph Nodes: 12
  - Graph Edges: 15
  - Cycle-Free: `True` (Valid Directed Acyclic Graph; passes topological sort).

### Step 9 — Grounded Corrective Recommendations
- **Objective**: Deliver practical, actionable remediation guidance grounded in the diagnosed fault.
- **Output**:
  - Action #1: Apply QoS rate-limiting policy and dynamically prioritize interactive DSCP traffic on `CORE-SW-01`.
  - Action #2: Re-route non-critical bulk transfer VLANs to redundant distribution uplink.

### Step 10 — Safe Remediation Simulation & Projected KPI Recovery
- **Objective**: Safe sandbox projection without live infrastructure risk.
- **Projection**:
  - Execution State: `SIMULATED` (Live production mutation disabled).
  - Dry-Run CLI: `switch(config-if)# qos policy rate-limit 800mbps dscp-priority ef burst 64k`
  - Rollback CLI: `switch(config-if)# no qos policy rate-limit`
  - Projected KPI Deltas: Drops $145 \to 0$, Latency $185\text{ms} \to 18.5\text{ms}$, Loss $5.2\% \to 0.0\%$.

### Step 11 — Principled Diagnostic Abstention
- **Objective**: Prove the system refuses to hallucinate a root cause when evidence is incomplete.
- **Input**: Incomplete payload for `BLDG-SW-ENG` with all physical performance counters omitted.
- **Result**:
  - Status: `insufficient_evidence`
  - Primary Root Cause: `INSUFFICIENT_EVIDENCE`
  - Confidence: `0.0%`
  - Safety Guarantee: Zero hallucination; system abstains and explicitly demands missing telemetry counters.

---

## Interactive Browser Demonstration Walkthrough

1. **Start the Web UI**: `python web_ui.py`
2. **Access**: Navigate to `http://localhost:8000`.
3. **Overview View**:
   - Check the **SIMULATED ENVIRONMENT** badge in the navigation bar.
   - Observe authentic health score dynamically calculated from monitored node inventory.
4. **Topology Explorer**:
   - Expand the tree view to inspect Core $\to$ Distribution $\to$ Access layers.
   - Click any node to compute instant downstream blast radius.
5. **Honeycomb Multi-Agent Dialogue**:
   - Inspect AMP/2.0 protocol message sequence numbers and audit lineage.
6. **Incident Investigation**:
   - Select any pre-built scenario from the dropdown (e.g., `scenario_2_congestion.json` or `scenario_6_schema_interop_failure.json`).
   - Click **Run Diagnosis** and observe evidence cards, temporal sequence, and Arbiter adjudication.
7. **Remediation Center**:
   - Click **Simulate Corrective Action** to generate dry-run commands and projected KPI deltas.
   - Authorize action using cryptographic HMAC-SHA256 signature.
   - Execute remediation to receive an atomic, single-use, anti-replay receipt.
