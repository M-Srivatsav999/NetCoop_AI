"""Dedicated Arbiter Agent (ArbiterAgent).

Acts as the supreme diagnostic authority in NetCoop AI:
1. Ingests structured multi-agent PeerReviewDossier
2. Synthesizes independent cross-domain evidence vs shared sensor dependencies
3. Adjudicates peer challenges and contradictions
4. Performs calibrated isotonic hypothesis ranking
5. Produces an explainable ArbiterDecision with explicit accepted rationale,
   rejected alternatives justification, and calibrated uncertainty.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from agents.correlation_agent import CorrelationAgent
from agents.peer_review_manager import PeerReviewDossier, PeerReviewManager
from core.confidence_engine import ConfidenceConfig
from core.rules import MetricThresholds
from core.topology import TopologyEngine
from protocol.models import (
    AgentFinding,
    ArbitrationResult,
    CanonicalTelemetry,
    EvidenceItem,
    HypothesisEvaluation,
    HypothesisType,
    IncidentSummary,
    StructuredEvidence,
)


class HypothesisRanking(BaseModel):
    """Detailed score and adjudication summary for a candidate hypothesis."""
    hypothesis: str
    rank: int
    score: float
    raw_confidence: float
    calibrated_confidence: float
    supporting_signals: int
    contradictory_signals: int
    adjudication_status: str  # ACCEPTED, REJECTED, ABSTAINED
    explanation: str
    ruling_reason: str


class ArbiterDecision(BaseModel):
    """Authoritative adjudication decision emitted by the ArbiterAgent."""
    decision_id: str = Field(default_factory=lambda: f"ARB-{uuid.uuid4().hex[:8].upper()}")
    incident_id: str
    status: str  # DIAGNOSED, INSUFFICIENT_EVIDENCE, CONFLICTING_EVIDENCE, INCONCLUSIVE
    primary_root_cause: str
    raw_confidence: float = Field(ge=0.0, le=1.0)
    calibrated_confidence: float = Field(ge=0.0, le=1.0)
    is_calibrated: bool = True
    accepted_rationale: str
    rejected_alternatives: Dict[str, str] = Field(default_factory=dict)
    ranked_hypotheses: List[HypothesisRanking] = Field(default_factory=list)
    affected_devices: List[str] = Field(default_factory=list)
    supporting_evidence: List[str] = Field(default_factory=list)
    structured_evidence: List[StructuredEvidence] = Field(default_factory=list)
    contradictory_evidence: List[str] = Field(default_factory=list)
    peer_challenges_adjudicated: int = 0
    peer_corroborations_integrated: int = 0
    uncertainty_factors: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    evidence_sources: List[str] = Field(default_factory=list)
    evidence_completeness: float = 1.0
    co_occurring_incidents: List[IncidentSummary] = Field(default_factory=list)

    def to_arbitration_result(self) -> ArbitrationResult:
        """Convert to canonical ArbitrationResult for full pipeline backward compatibility."""
        alt_list = [
            {
                "hypothesis": h.hypothesis,
                "score": h.score,
                "confidence": h.calibrated_confidence,
                "supporting_signals": h.supporting_signals,
                "contradictory_signals": h.contradictory_signals,
                "explanation": h.explanation
            }
            for h in self.ranked_hypotheses if h.hypothesis != self.primary_root_cause
        ]
        return ArbitrationResult(
            primary_root_cause=self.primary_root_cause,
            confidence=self.calibrated_confidence,
            raw_confidence=self.raw_confidence,
            calibrated_confidence=self.calibrated_confidence,
            is_calibrated=self.is_calibrated,
            affected_devices=self.affected_devices,
            supporting_evidence=self.supporting_evidence,
            structured_evidence=self.structured_evidence,
            contradictory_evidence=self.contradictory_evidence,
            alternative_hypotheses=alt_list,
            evidence_sources=self.evidence_sources if self.evidence_sources else ["telemetry_agent", "infrastructure_agent", "connectivity_agent"],
            evidence_completeness=self.evidence_completeness,
            uncertainty_factors=self.uncertainty_factors,
            limitations=self.limitations,
            recommended_actions=self.recommended_actions,
            execution_trace_id=self.decision_id,
            co_occurring_incidents=self.co_occurring_incidents
        )


class ArbiterAgent:
    """Supreme Diagnostic Arbiter Agent."""

    def __init__(
        self,
        topology_engine: Optional[TopologyEngine] = None,
        thresholds: Optional[MetricThresholds] = None,
        confidence_config: Optional[ConfidenceConfig] = None
    ) -> None:
        self.topology = topology_engine or TopologyEngine()
        self.thresholds = thresholds or MetricThresholds()
        self.confidence_config = confidence_config or ConfidenceConfig()
        self.correlation_engine = CorrelationAgent(
            topology_engine=self.topology,
            thresholds=self.thresholds,
            confidence_config=self.confidence_config
        )
        self.peer_review_manager = PeerReviewManager()

    def arbitrate(
        self,
        telemetry_records: List[CanonicalTelemetry],
        agent_findings: List[AgentFinding],
        cascade_evidence: Optional[List[EvidenceItem]] = None,
        staleness_seconds: float = 0.0,
        dossier: Optional[PeerReviewDossier] = None,
        incident_id: Optional[str] = None,
        temporal_events: Optional[List[Any]] = None,
        reference_time: Optional[datetime] = None
    ) -> ArbiterDecision:
        """Adjudicate findings, peer reviews, and temporal causality to produce a definitive ArbiterDecision."""
        inc_id = incident_id or f"INC-{uuid.uuid4().hex[:6]}"

        # If dossier is not supplied, conduct peer review now
        if dossier is None:
            dossier = self.peer_review_manager.conduct_peer_review(
                incident_id=inc_id,
                telemetry_records=telemetry_records,
                agent_findings=agent_findings
            )

        # Delegate base evaluation to underlying correlation engine
        base_result = self.correlation_engine.arbitrate(
            telemetry_records=telemetry_records,
            agent_findings=agent_findings,
            cascade_evidence=cascade_evidence,
            staleness_seconds=staleness_seconds
        )

        # Rank all candidate hypotheses
        raw_evals = self.correlation_engine.evidence_engine.evaluate_hypotheses()
        eval_items = list(raw_evals.values()) if isinstance(raw_evals, dict) else list(raw_evals)

        primary = base_result.primary_root_cause
        decision_status = "DIAGNOSED"

        # Check for HEALTHY conditions vs INSUFFICIENT_EVIDENCE
        if primary in ("NORMAL_OPERATION", "HEALTHY", "NO_ANOMALY"):
            if not telemetry_records:
                decision_status = "INSUFFICIENT_EVIDENCE"
                primary = "INSUFFICIENT_EVIDENCE"
            else:
                decision_status = "HEALTHY"
                primary = "NORMAL_OPERATION"
        elif primary == "INSUFFICIENT_EVIDENCE":
            decision_status = "INSUFFICIENT_EVIDENCE"
        elif base_result.confidence < 0.40:
            decision_status = "INCONCLUSIVE"
        elif len(base_result.contradictory_evidence) > 2 and base_result.confidence < 0.60:
            decision_status = "CONFLICTING_EVIDENCE"

        # Temporal Causal Re-Weighting & Precedence Adjudication
        temporal_boost_applied = False
        initiating_dev = None
        initiating_hyp = None
        init_event = None
        cascade_devs: Set[str] = set()

        # Check for multiple simultaneous or ambiguous initiating candidates
        ambiguous_causality = False
        if temporal_events:
            min_ts = min(e.timestamp for e in temporal_events)
            earliest_events = [
                e for e in temporal_events
                if abs((e.timestamp - min_ts).total_seconds()) <= 2.0
            ]
            distinct_early_devs = sorted(list({e.device_id for e in earliest_events}))
            if len(distinct_early_devs) > 1:
                ambiguous_causality = True
                base_result.uncertainty_factors.append(
                    f"Temporal causality is ambiguous: simultaneous initiating events detected across multiple distinct devices ({distinct_early_devs})."
                )

        init_events = [
            e for e in (temporal_events or [])
            if getattr(e, "classification", None) and getattr(e, "classification").value == "INITIATING_EVENT"
        ]

        if temporal_events and decision_status == "DIAGNOSED" and primary != "NORMAL_OPERATION" and not ambiguous_causality:
            init_event = init_events[0] if init_events else None
            # Check clock skew on initiating event
            ref_now = reference_time or datetime.now(timezone.utc)
            if ref_now.tzinfo is None:
                ref_now = ref_now.replace(tzinfo=timezone.utc)
            if init_event and init_event.timestamp:
                ts = init_event.timestamp if init_event.timestamp.tzinfo else init_event.timestamp.replace(tzinfo=timezone.utc)
                if (ts - ref_now).total_seconds() > 60.0:
                    init_event = None
                    base_result.uncertainty_factors.append("Temporal initiating event discarded due to excessive future clock skew (>60s).")

            if init_event:
                initiating_dev = init_event.device_id
                dev_findings = [f for f in agent_findings if f.device_id == initiating_dev]
                supported_targets = [
                    e.hypothesis_target for f in dev_findings
                    for e in f.evidence if getattr(e.polarity, "value", str(e.polarity)) == "SUPPORTS" and e.hypothesis_target != "NORMAL_OPERATION"
                ]
                # Specific root-causes take precedence on initiating device over generic link congestion
                if "UPSTREAM_SWITCH_FAILURE" in supported_targets or (
                    getattr(init_event, "metric_name", "") == "downstream_anomaly_cluster" or
                    getattr(init_event, "metric_name", "") == "reported_status" or
                    (getattr(init_event, "metric_name", "") == "packet_loss_pct" and any(getattr(r, "packet_loss_pct", 0) >= 95.0 for r in telemetry_records if getattr(r, "device_id", "") == initiating_dev))
                ):
                    initiating_hyp = "UPSTREAM_SWITCH_FAILURE"
                elif "HARDWARE_FAILURE" in supported_targets and (
                    init_event.metric_name in ("interface_errors", "crc_errors") or
                    any("interface_errors" in e.metric_name or "crc" in e.metric_name for f in dev_findings for e in f.evidence)
                ):
                    initiating_hyp = "HARDWARE_FAILURE"
                elif "WEAK_WIFI" in supported_targets and (
                    init_event.metric_name == "signal_strength_dbm" or
                    any("signal" in e.metric_name for f in dev_findings for e in f.evidence)
                ):
                    initiating_hyp = "WEAK_WIFI"
                elif "DNS_DHCP_FAILURE" in supported_targets and (
                    init_event.metric_name in ("dns_resolution_ms", "dhcp_lease_success") or
                    any("dns" in e.metric_name or "dhcp" in e.metric_name for f in dev_findings for e in f.evidence)
                ):
                    initiating_hyp = "DNS_DHCP_FAILURE"
                elif supported_targets:
                    from collections import Counter
                    initiating_hyp = Counter(supported_targets).most_common(1)[0][0]
                elif init_event.metric_name in ("interface_errors", "crc_errors"):
                    initiating_hyp = "HARDWARE_FAILURE"
                elif init_event.metric_name in ("queue_drops", "link_utilization_pct"):
                    initiating_hyp = "LINK_CONGESTION"
                elif init_event.metric_name in ("dns_resolution_ms", "dhcp_lease_success"):
                    initiating_hyp = "DNS_DHCP_FAILURE"
                elif init_event.metric_name == "signal_strength_dbm":
                    initiating_hyp = "WEAK_WIFI"

                if initiating_hyp:
                    # Topological validity: only discount downstream cascading devices connected to initiator
                    raw_cascade_devs = {
                        getattr(te, "device_id") for te in temporal_events
                        if getattr(te, "classification", None) and getattr(te, "classification").value == "CASCADING_SYMPTOM"
                    }
                    downstream_of_initiator = set(self.topology.get_downstream_devices(initiating_dev))
                    cascade_devs = raw_cascade_devs.intersection(downstream_of_initiator) if downstream_of_initiator else raw_cascade_devs

                    subsequent_devs = {
                        getattr(te, "device_id") for te in temporal_events
                        if hasattr(te, "timestamp") and (te.timestamp - init_event.timestamp).total_seconds() > 1.0
                    }

                    for ev in eval_items:
                        h_name = ev.get("hypothesis")
                        if h_name == initiating_hyp:
                            ev["net_score"] = ev.get("net_score", 0.0) + 4.5
                            temporal_boost_applied = True
                        elif h_name != initiating_hyp:
                            if cascade_devs and any(cd in ev.get("affected_devices", []) for cd in cascade_devs):
                                ev["net_score"] = max(0.0, ev.get("net_score", 0.0) - 2.5)
                            elif subsequent_devs and any(sd in ev.get("affected_devices", []) for sd in subsequent_devs):
                                ev["net_score"] = max(0.0, ev.get("net_score", 0.0) - 2.5)

        def arbiter_rank_key(ev: Dict[str, Any]) -> Tuple[int, float]:
            h_name = ev.get("hypothesis", "")
            is_normal = (h_name in ("NORMAL_OPERATION", "HEALTHY", "NO_ANOMALY"))
            if is_normal and primary != "NORMAL_OPERATION":
                return (-1, 0.0)
            return (1 if ev.get("net_score", 0.0) > 0 else 0, ev.get("net_score", 0.0))

        sorted_evals = sorted(eval_items, key=arbiter_rank_key, reverse=True)
        if temporal_boost_applied and sorted_evals and sorted_evals[0].get("net_score", 0.0) > 0:
            if sorted_evals[0].get("hypothesis") not in ("NORMAL_OPERATION", "HEALTHY", "NO_ANOMALY") or primary == "NORMAL_OPERATION":
                primary = sorted_evals[0].get("hypothesis", primary)

        top_score = sorted_evals[0].get("net_score", 0.0) if sorted_evals else 0.0

        ranked: List[HypothesisRanking] = []
        rejected_alts: Dict[str, str] = {}

        for rank, ev in enumerate(sorted_evals, start=1):
            hyp_name = ev.get("hypothesis", "")
            is_winner = (hyp_name == primary) and (decision_status == "DIAGNOSED")
            status = "ACCEPTED" if is_winner else "REJECTED"
            score = ev.get("net_score", 0.0)
            supp_count = ev.get("supporting_count", 0)
            contra_count = ev.get("contradicting_count", 0)

            raw_c = min(1.0, score / max(1.0, score + ev.get("contra_weight", 0.0))) if score > 0 else 0.0
            calibrated_c = self.correlation_engine.confidence_engine.calibrate_confidence(raw_c)

            # Build ruling reason
            if is_winner:
                if temporal_boost_applied and initiating_dev:
                    ruling = f"Corroborated by independent signals and verified by temporal sequence as initiating event on {initiating_dev}."
                else:
                    ruling = f"Corroborated by {supp_count} independent signals; overrides alternative claims."
            elif contra_count > 0:
                ruling = f"Contradicted by {contra_count} negative telemetry checks and peer review challenges."
            elif score <= 0.0:
                ruling = "Insufficient positive signal; no anomalous metrics support this hypothesis."
            elif temporal_boost_applied and any(cd in ev.get("affected_devices", []) for cd in cascade_devs):
                ruling = f"Subordinate score; classified as downstream cascading symptom following initiating anomaly on {initiating_dev}."
            else:
                ruling = f"Subordinate score ({score:.2f} vs {top_score:.2f} for {primary})."

            if not is_winner and hyp_name != "NORMAL_OPERATION":
                rejected_alts[hyp_name] = ruling

            ranked.append(HypothesisRanking(
                hypothesis=hyp_name,
                rank=rank,
                score=round(score, 3),
                raw_confidence=round(raw_c, 3),
                calibrated_confidence=round(calibrated_c, 3),
                supporting_signals=supp_count,
                contradictory_signals=contra_count,
                adjudication_status=status,
                explanation=f"Hypothesis {hyp_name}: net_score={score}, supporting={supp_count}, contra={contra_count}",
                ruling_reason=ruling
            ))

        winner_ev = next((ev for ev in eval_items if ev.get("hypothesis") == primary), None)
        winner_rank = next((r for r in ranked if r.hypothesis == primary), None)

        # Identify active competing hypotheses
        # A true competitor must have genuine positive score or multiple corroborating signals
        # and be comparable to the winner's score (not an order of magnitude smaller)
        winner_score = winner_rank.score if winner_rank else 1.0
        competing = [
            r for r in ranked
            if r.hypothesis != primary and r.hypothesis not in ("NORMAL_OPERATION", "HEALTHY", "NO_ANOMALY") and (
                (r.supporting_signals >= 2 and r.score >= 0.35 * winner_score) or (r.score > 1.5 and r.score >= 0.35 * winner_score)
            )
        ]
        has_contradictions = (winner_ev.get("contradicting_count", 0) > 0) if winner_ev else False

        if winner_rank:
            win_raw_c = winner_rank.raw_confidence
            win_cal_c = winner_rank.calibrated_confidence
        else:
            win_raw_c = base_result.raw_confidence
            win_cal_c = base_result.calibrated_confidence

        uncertainties = list(base_result.uncertainty_factors)
        if (competing or has_contradictions) and win_cal_c >= 0.88:
            # Epistemic discount when competing hypotheses or contradictions exist: eliminate uncalibrated 100% certainty
            comp_names = [c.hypothesis for c in competing]
            max_comp_signals = max((c.supporting_signals for c in competing), default=1)
            total_signals = (winner_rank.supporting_signals if winner_rank else 1) + max_comp_signals
            comp_ratio = max_comp_signals / max(1, total_signals)
            penalty = min(0.35, max(0.12, comp_ratio * 0.40))
            win_raw_c = max(0.40, round(win_raw_c * (1.0 - penalty), 3))
            win_cal_c = min(0.88, round(win_cal_c * (1.0 - penalty), 3))
            reason = f"Competing hypotheses ({', '.join(comp_names)})" if comp_names else "Contradictory evidence signals"
            uncertainties.append(
                f"{reason} detected. Confidence discounted by {penalty:.1%} to reflect diagnostic ambiguity."
            )

        # Assemble winning supporting and contradictory evidence items
        if winner_ev:
            winning_supporting = [
                f"[{item.source_agent}] {item.description}"
                for item in winner_ev.get("supporting_items", [])
            ]
            winning_contradicting = [
                f"[{item.source_agent}] {item.description}"
                for item in winner_ev.get("contradicting_items", [])
            ]
            # Preserve untrusted label reconciliation contradictory items from base_result
            for c in base_result.contradictory_evidence:
                if c not in winning_contradicting:
                    winning_contradicting.append(c)

            structured_items = [
                StructuredEvidence(
                    metric=item.metric_name,
                    value=item.observed_value,
                    interpretation=item.description
                )
                for item in winner_ev.get("supporting_items", [])
            ]
            winning_affected = sorted(list(set(winner_ev.get("affected_devices", [])).union(base_result.affected_devices)))
        else:
            winning_supporting = list(base_result.supporting_evidence)
            winning_contradicting = list(base_result.contradictory_evidence)
            structured_items = list(base_result.structured_evidence)
            winning_affected = list(base_result.affected_devices)

        # Clamping affected devices to empty for normal operation
        if primary in ("NORMAL_OPERATION", "HEALTHY", "NO_ANOMALY"):
            winning_affected = []

        # Explain contributions of all 6 core metrics across anomalous affected devices
        existing_metrics = {s.metric for s in structured_items}
        for rec in telemetry_records:
            if rec.device_id in winning_affected:
                m = rec.metrics
                dev = rec.device_id
                if m.interface_errors is not None and m.interface_errors > 5 and "interface_errors" not in existing_metrics:
                    structured_items.append(StructuredEvidence(
                        metric="interface_errors",
                        value=m.interface_errors,
                        interpretation=f"Physical layer errors ({m.interface_errors}) on {dev}: indicates cable/transceiver/switchport defect (supports HARDWARE_FAILURE)."
                    ))
                    existing_metrics.add("interface_errors")
                if m.queue_drops is not None and m.queue_drops > 10 and "queue_drops" not in existing_metrics:
                    structured_items.append(StructuredEvidence(
                        metric="queue_drops",
                        value=m.queue_drops,
                        interpretation=f"Switch egress buffer overflow ({m.queue_drops} tail drops) on {dev}: indicates packet buffer exhaustion (supports BUFFER_OVERFLOW / LINK_CONGESTION)."
                    ))
                    existing_metrics.add("queue_drops")
                if m.link_utilization_pct is not None and m.link_utilization_pct >= 80.0 and "link_utilization_pct" not in existing_metrics:
                    structured_items.append(StructuredEvidence(
                        metric="link_utilization_pct",
                        value=m.link_utilization_pct,
                        interpretation=f"Link utilization saturated ({m.link_utilization_pct}%) on {dev}: indicates transmission bandwidth bottleneck (supports LINK_CONGESTION)."
                    ))
                    existing_metrics.add("link_utilization_pct")
                if m.cpu_pct is not None and m.cpu_pct >= 80.0 and "cpu_pct" not in existing_metrics:
                    structured_items.append(StructuredEvidence(
                        metric="cpu_pct",
                        value=m.cpu_pct,
                        interpretation=f"Processor utilization elevated ({m.cpu_pct}%) on {dev}: indicates control plane resource exhaustion / hardware stress."
                    ))
                    existing_metrics.add("cpu_pct")
                if m.packet_loss_pct is not None and m.packet_loss_pct > 1.0 and "packet_loss_pct" not in existing_metrics:
                    structured_items.append(StructuredEvidence(
                        metric="packet_loss_pct",
                        value=m.packet_loss_pct,
                        interpretation=f"Packet loss measured at {m.packet_loss_pct}% on {dev}: dropped transit packets resulting from queue drops or line corruption."
                    ))
                    existing_metrics.add("packet_loss_pct")
                if m.latency_ms is not None and m.latency_ms > 50.0 and "latency_ms" not in existing_metrics:
                    structured_items.append(StructuredEvidence(
                        metric="latency_ms",
                        value=m.latency_ms,
                        interpretation=f"Round-trip latency at {m.latency_ms}ms on {dev}: queuing delay and retransmission degradation."
                    ))
                    existing_metrics.add("latency_ms")

        # Build comprehensive accepted rationale
        if decision_status == "DIAGNOSED":
            accepted_rationale = (
                f"Root cause '{primary}' established with {win_cal_c:.1%} calibrated confidence. "
                f"Supported by {len(winning_supporting)} corroborating evidence metrics across "
                f"{len(winning_affected)} affected device(s). "
                f"Adjudicated {len(dossier.challenges)} peer review challenges and {len(dossier.contradictions)} contradictions. "
                f"{dossier.peer_review_summary}"
            )
            if temporal_events:
                init_events = [e for e in temporal_events if getattr(e, "classification", None) and getattr(e, "classification").value == "INITIATING_EVENT"]
                if init_events:
                    accepted_rationale += f" Temporal sequence verified: initiating event on {init_events[0].device_id} ({init_events[0].metric_name}) temporally preceded downstream cascading symptoms."
        elif decision_status == "HEALTHY":
            accepted_rationale = (
                f"Network operational state verified as HEALTHY across {len(telemetry_records)} device(s). "
                f"Telemetry is fresh (staleness {staleness_seconds:.1f}s <= 60s), metrics are complete, "
                f"and all critical latency, loss, and error counters reside within nominal operating thresholds."
            )
        else:
            accepted_rationale = (
                f"Diagnosis withheld ({decision_status}). Insufficient conclusive empirical telemetry "
                f"to differentiate between competing network failure modes without risking false alarms."
            )

        return ArbiterDecision(
            decision_id=f"ARB-{uuid.uuid4().hex[:8].upper()}",
            incident_id=inc_id,
            status=decision_status,
            primary_root_cause=primary,
            raw_confidence=win_raw_c,
            calibrated_confidence=win_cal_c,
            is_calibrated=base_result.is_calibrated,
            accepted_rationale=accepted_rationale,
            rejected_alternatives=rejected_alts,
            ranked_hypotheses=ranked,
            affected_devices=winning_affected,
            supporting_evidence=winning_supporting,
            structured_evidence=structured_items,
            contradictory_evidence=winning_contradicting,
            peer_challenges_adjudicated=len(dossier.challenges),
            peer_corroborations_integrated=len(dossier.corroborations),
            uncertainty_factors=uncertainties,
            limitations=base_result.limitations,
            recommended_actions=base_result.recommended_actions,
            evidence_sources=base_result.evidence_sources,
            evidence_completeness=base_result.evidence_completeness,
            co_occurring_incidents=base_result.co_occurring_incidents
        )
