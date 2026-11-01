# NetCoop AI — Peer Review & Dedicated Arbiter Agent Report

## Executive Summary

To satisfy the **15% Hackathon Judging Category for Peer Review, Cross-Agent Collaboration, and Conflict Resolution**, NetCoop AI implements a structured multi-round debate and adjudication architecture:
1. **Round 1 (Independent Analysis)**: Domain-specialized agents (`TelemetryAgent`, `InfrastructureAgent`, `ConnectivityAgent`, etc.) generate initial findings and hypotheses without cross-agent groupthink.
2. **Round 2 (Cross-Domain Peer Review)**: `PeerReviewManager` facilitates targeted inquiries, empirical challenges, and cross-domain corroborations between agents to challenge assumptions across domain boundaries.
3. **Round 3 (Authoritative Adjudication)**: The dedicated `ArbiterAgent` synthesizes the `PeerReviewDossier`, resolves contradictions, balances independent vs shared evidence, performs isotonic confidence calibration, ranks candidate hypotheses, and outputs an explainable `ArbiterDecision`.

---

## 1. Peer Review Architecture (`agents/peer_review_manager.py`)

### 1.1 Cross-Domain Verification Rules

The `PeerReviewManager` executes automated cross-examination across 4 primary engineering vectors:

| Rule Name | Challenging Agent | Target Agent | Interrogation Condition | Adjudication Outcome |
|:---|:---|:---|:---|:---|
| **Hardware vs. Congestion** | `InfrastructureAgent` | `TelemetryAgent` | Telemetry reports high latency/loss (suspecting Congestion), but physical switch counters reveal elevated CRC or interface errors ($>10$). | **CHALLENGE**: Physical layer cable or transceiver defect supersedes pure queue congestion. |
| **Buffer Saturation Corroboration** | `InfrastructureAgent` | `TelemetryAgent` | Telemetry reports latency/loss while switch reports egress queue tail drops ($>20$) with zero interface/CRC errors. | **CORROBORATION**: Confirms buffer starvation without physical cable defect. |
| **Service Domain Separation** | `ServiceAgent` | `TelemetryAgent` | High DNS resolution latency ($>150$ms) or DHCP lease failure occurring while transport-layer packet loss is near zero ($<2.0\%$). | **CORROBORATION**: Eliminates wired transport failure; localizes root cause strictly to DNS/DHCP control-plane services. |
| **Physical Metric Supremacy** | `PeerReviewManager` | `GeneratorLabel` | Untrusted generator metadata reports `HEALTHY` or `OK`, but physical metrics indicate severe packet loss, latency spikes, or resource exhaustion. | **CONTRADICTION**: Invokes physical metric supremacy to disregard misleading status labels. |

### 1.2 Structured Peer Review Data Contracts
All peer reviews are compiled into an immutable `PeerReviewDossier`:
- `PeerReviewChallenge`: records challenger, target agent, contested hypothesis, and counter-evidence.
- `PeerReviewCorroboration`: records independent supporting domain observations.
- `PeerReviewContradiction`: logs irreconcilable signals and the deterministic resolution rule applied.

---

## 2. Dedicated Arbiter Agent (`agents/arbiter_agent.py`)

### 2.1 Adjudication Contract (`ArbiterDecision`)
The `ArbiterAgent` serves as the final authority, issuing an `ArbiterDecision` containing:
- `primary_root_cause`: Authoritative diagnosed fault.
- `status`: One of `DIAGNOSED`, `INSUFFICIENT_EVIDENCE`, `CONFLICTING_EVIDENCE`, or `INCONCLUSIVE`.
- `raw_confidence` vs `calibrated_confidence`: Preserves raw heuristic confidence alongside the PAVA isotonic-calibrated probability.
- `ranked_hypotheses`: Strict ranking of all candidates with scores, independent supporting signals, contradictory signals, and ruling explanations.
- `accepted_rationale`: Multi-sentence evidentiary narrative explaining why the leading hypothesis was accepted.
- `rejected_alternatives`: Explicit mapping of why each competing alternative was eliminated.
- `to_arbitration_result()`: Provides 100% backward compatibility with all downstream report generation and remediation engines.

---

## 3. Test Verification Suite (`evaluation/test_peer_review_and_arbiter.py`)

Six rigorous tests validate the peer review and arbitration lifecycle:

1. `test_peer_review_challenge_hardware_vs_congestion`: Verifies CRC errors trigger a formal challenge against link congestion.
2. `test_peer_review_corroboration_queue_drops_without_crc`: Verifies clean interfaces with queue drops corroborate link congestion.
3. `test_peer_review_service_domain_corroboration`: Verifies isolation of DNS/DHCP faults from general network transport.
4. `test_peer_review_untrusted_label_contradiction`: Verifies untrusted labels contradicting telemetry are logged and overridden.
5. `test_arbiter_agent_ranking_and_rejected_alternatives`: Confirms candidate ranking, accepted rationale, and alternative rejection reasons.
6. `test_arbiter_agent_abstention_on_insufficient_evidence`: Verifies explicit abstention when telemetry signals are absent.

### Test Execution Result:
```
============================= 13 passed in 0.95s ==============================
```
*(Combined suite: 7 multi-incident clustering tests + 6 peer review & arbiter tests passing without regression).*
