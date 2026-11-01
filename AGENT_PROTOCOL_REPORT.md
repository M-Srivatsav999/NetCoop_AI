# NetCoop AI — Agent Message Protocol (AMP/2.0) Architecture & Verification Report

## Executive Summary

As required by the **30% Hackathon Weight for Agent Communication Protocol and Interoperability**, NetCoop AI implements an enterprise-grade, cryptographically verifiable, strictly typed Agent Message Protocol (**AMP/2.0**).

This protocol ensures that autonomous agents do not communicate via free-form unstructured text or lossy ad-hoc dictionaries. Instead, all inter-agent dialogues, cross-agent peer reviews, telemetry dispatches, evidence challenges, and arbitration decisions conform to a strict schema contract with monotonic sequence tracking, clock-skew protection, and tamper-evident cryptographic chaining.

---

## 1. Protocol Architecture & Specification

The AMP/2.0 protocol is defined in `protocol/agent_message_protocol.py`.

### 1.1 Canonical Protocol Message Schema (`AgentProtocolMessage`)

```python
class AgentProtocolMessage(BaseModel):
    message_id: str          # Deterministic unique message ID (e.g., MSG-38b4f2...)
    incident_id: str         # Global incident correlation identifier
    correlation_id: str      # Dialogue or review thread identifier
    schema_version: str      # Protocol version ("AMP/1.0", "AMP/2.0")
    message_type: ProtocolMessageType  # One of 9 canonical message types
    sender: str              # Specialized agent or controller name
    recipient: str           # Targeted recipient agent or "ALL" for broadcast
    sequence_number: int     # Monotonic sequence counter per (sender, incident_id)
    created_at: datetime     # Explicit UTC timestamp
    payload: Dict[str, Any]  # Typed payload data
    evidence_ids: List[str]  # Atomic evidence identifiers referenced
    confidence: Optional[float] # Confidence score (0.0 to 1.0)
    limitations: List[str]   # Self-reported caveats or diagnostic boundaries
```

### 1.2 Canonical Message Types (`ProtocolMessageType`)

The protocol supports exactly 9 purpose-driven message types covering the full diagnostic lifecycle:

| Message Type | Direction | Semantic Purpose |
|:---|:---|:---|
| `OBSERVATION` | Specialized Agent $\to$ Orchestrator / Peers | Dissemination of raw or normalized metric observations. |
| `HYPOTHESIS` | Specialized Agent $\to$ Arbiter | Initial candidate root-cause proposal with rationale. |
| `EVIDENCE` | Specialized Agent $\to$ Evidence Ledger | Registered atomic evidence items bound to physical sensors. |
| `CHALLENGE` | Peer Reviewer $\to$ Peer Agent | Direct inquiry or challenge regarding conflicting telemetry or missing metrics. |
| `RESPONSE` | Peer Agent $\to$ Peer Reviewer | Clarification, metric re-check, or concession in response to challenge. |
| `CORROBORATION` | Peer Reviewer $\to$ Arbiter | Corroborating physical telemetry from independent domain. |
| `CONTRADICTION` | Peer Reviewer $\to$ Arbiter | Flagged conflicting evidence invalidating a candidate hypothesis. |
| `ARBITRATION` | Arbiter $\to$ Specialized Agents | Synthesis of competing hypotheses, de-biasing, and score ranking. |
| `FINAL_DECISION` | Arbiter $\to$ Orchestrator / NOC | Authoritative diagnosis or justified abstention report. |

---

## 2. Integrity and Delivery Guarantees

### 2.1 Monotonic Sequence Tracking & Gap Detection
To prevent out-of-order execution in asynchronous multi-agent coordination:
- The `AgentMessageBus` maintains a sequence tracker keyed by `(sender, incident_id)`.
- If an agent publishes sequence $N$ while the bus expects sequence $K \neq N$, the message is rejected with a `MessageAck(status=NACK, reason="Out-of-order sequence number...")`.

### 2.2 Replay Protection & Deduplication
- Every processed `message_id` is recorded in an in-memory set.
- Duplicate message IDs are immediately rejected with `NACK` ("replay detected").

### 2.3 Clock Skew & TTL Staleness Validation
- Future-dated messages exceeding allowed clock skew (default 60 seconds) are rejected with `NACK`.
- Messages exceeding maximum allowed time-to-live (default 3600 seconds) are flagged as expired and rejected with `NACK`.

### 2.4 Cryptographic Append-Only Audit Ledger
Every accepted message is chained into a tamper-evident cryptographic log:
$$\text{ChainHash}_i = \text{SHA256}(i \parallel \text{message\_id} \parallel \text{PayloadDigest} \parallel \text{ChainHash}_{i-1})$$
Any alteration to past messages, payloads, or indices causes `verify_ledger_integrity()` to fail immediately with an explicit error identifying the exact tampered index.

---

## 3. Test Verification Suite (`evaluation/test_agent_message_protocol.py`)

A comprehensive 8-test verification suite confirms all protocol invariants:

1. `test_protocol_all_message_types_supported`: Validates all 9 `ProtocolMessageType` variants pass end-to-end through the bus.
2. `test_protocol_sequence_monotonicity_and_out_of_order_rejection`: Confirms sequential delivery succeeds and sequence gaps (e.g. seq 3 before seq 2) are rejected.
3. `test_protocol_replay_and_duplicate_message_id_rejection`: Confirms duplicate message IDs are detected and blocked.
4. `test_protocol_version_negotiation`: Confirms `AMP/1.0` and `AMP/2.0` are accepted while unsupported schemas (`AMP/99.0`) are rejected.
5. `test_protocol_clock_skew_and_ttl_staleness`: Verifies rejection of future-dated and expired messages.
6. `test_protocol_cryptographic_ledger_and_tamper_detection`: Verifies tamper detection when audit logs are modified.
7. `test_protocol_pub_sub_routing`: Confirms targeted routing and broadcast dispatch.
8. `test_protocol_canonical_json_determinism`: Confirms canonical serialization generates identical SHA-256 hashes regardless of dictionary key ordering.

### Test Execution Result:
```
============================== 8 passed in 0.74s ==============================
```
