# NetCoop AI — Agent Message Protocol (AMP/2.0) & MCP Interoperability Validation

**Protocol Standard**: Agent Message Protocol (AMP) — Version 2.0  
**Specification Files**: `protocol/agent_message_protocol.py`, `agents/peer_review_manager.py`, `mcp_server.py`  
**Test Suites**: 
- `evaluation/test_agent_message_protocol.py` (14/14 Passed)
- `evaluation/test_peer_review_and_arbiter.py` (16/16 Passed)
- `evaluation/test_mcp_real_subprocess.py` (7/7 Passed)
- `evaluation/test_official_mcp_sdk.py` (Passed/Verified)  
**Hackathon Alignment**: 30% System Architecture & Communication Protocol Evaluation Category

---

## 1. AMP/2.0 Specification & Message Architecture

AMP/2.0 provides a strictly typed, versioned, multi-agent protocol contract governing all inter-agent dialogues, dispatches, and deliberations:

```python
class AgentProtocolMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: f"MSG-{uuid.uuid4().hex[:12]}")
    incident_id: str
    correlation_id: str
    schema_version: str = "AMP/2.0"
    message_type: ProtocolMessageType
    sender: str
    recipient: str = "ALL"
    sequence_number: int  # Strictly monotonic counter >= 1 per (sender, incident_id)
    created_at: datetime
    payload: Dict[str, Any]
    evidence_ids: List[str]  # Atomic evidence references
    confidence: Optional[float]
    limitations: List[str]
```

### Canonical Message Types
1. `OBSERVATION`: Raw metric ingestion and anomaly alerts.
2. `HYPOTHESIS`: Diagnostic proposition with preliminary confidence.
3. `EVIDENCE`: Direct measurement or derived counter-evidence.
4. `CHALLENGE`: Cross-domain dispute raised against a peer agent.
5. `RESPONSE`: Formal rebuttal, concession, or defense responding to a challenge.
6. `CORROBORATION`: Cross-domain confirmation from independent telemetry.
7. `CONTRADICTION`: Incompatible telemetry observations flagged for arbitration.
8. `ARBITRATION`: Final synthesized adjudication by the Arbiter Agent.
9. `AGENT_DISAGREEMENT`: Formal dispute record when physical metrics override untrusted status labels.
10. `DISPATCH_*`: Orchestrator dispatch envelopes (`DISPATCH_TELEMETRY`, `DISPATCH_INFRASTRUCTURE`, `DISPATCH_CONNECTIVITY`).
11. `REQUEST_CLARIFICATION` / `CLARIFICATION_RESPONSE`: Conflict negotiation dialogue.

---

## 2. Peer-Review Identity & Lifecycle Enforcement

Peer-review deliberation between diagnostic agents enforces a bi-directional verification lifecycle:

```
[ Challenger Agent ]                                 [ Target Agent ]
         │                                                  │
         │ ─── 1. Raise Challenge (PeerReviewChallenge) ──► │
         │        • target_agent = TargetAgent              │
         │        • counter_evidence = [EvidenceItem]       │
         │        • status = OPEN                           │
         │                                                  │
         │ ◄── 2. Deliver Response (PeerReviewResponse) ────│
         │        • responding_agent = TargetAgent          │
         │        • verdict = CONCEDED | REBUTTED           │
         │        • defense_evidence = [EvidenceItem]       │
         ▼                                                  ▼
     [ Challenge Status: CONCEDED / REBUTTED / RECONCILED ]
```

### 8 Mandatory Lifecycle Conditions Verified:
1. **Agreement / Corroboration**: Independent verification of queue drops confirming buffer exhaustion without CRC errors.
2. **Disagreement / Challenge**: Physical layer CRC errors directly contesting link buffer congestion.
3. **Valid Rebuttal**: Challenged agent presents empirical defense evidence, transitioning challenge to `REBUTTED`.
4. **Valid Concession**: Challenged agent concedes to superior physical counter-evidence, transitioning challenge to `CONCEDED`.
5. **Invalid Response Identity**: Rejection of imposter responding agents, mismatched target agents, wrong challenge IDs, or wrong target devices.
6. **Missing Evidence Handling**: Structured aggregation gracefully handles sparse evidence without raising unhandled null exceptions.
7. **Conflicting Evidence Reconciled**: Incompatible generator labels vs physical metric counters resolved via `PHYSICAL_METRIC_SUPREMACY`.
8. **Unresolved Disagreement**: Unanswered disputes remain in `OPEN` status and are explicitly penalized during Arbiter confidence calculation.

---

## 3. Model Context Protocol (MCP) Interoperability

NetCoop AI exposes an official Model Context Protocol (MCP) server (`mcp_server.py`) operating over stdio JSON-RPC 2.0:

### Registered MCP Tools:
1. `diagnose_telemetry`: Ingests multi-device network telemetry and returns structured root-cause diagnoses.
2. `get_blast_radius`: Calculates topological downstream impact and blast radius for any campus node.
3. `simulate_remediation`: Projects before/after KPI deltas and dry-run CLI remediation playbooks.
4. `get_campus_topology`: Exports campus network hierarchy, links, and node metadata.

### Verification Integrity:
- **Wire Protocol Stdio Subprocess Tests** (`test_mcp_real_subprocess.py`):
  - Validates JSON-RPC 2.0 handshake, initialize request, tool listing, tool execution, invalid argument rejection, and error handling over real standard input/output pipes.
- **Official Anthropic MCP SDK Client Integration** (`test_official_mcp_sdk.py`):
  - Spawns server under official `ClientSession` via `stdio_client`.
  - Enforces strict 8.0-second async execution timeout with automated process tree cleanup to eliminate Windows anonymous pipe deadlocks.
