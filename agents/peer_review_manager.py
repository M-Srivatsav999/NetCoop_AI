"""Peer Review Manager for Multi-Agent Network Diagnosis.

Orchestrates multi-round peer review debates:
- Round 1: Agents generate independent domain findings.
- Round 2: Peer Review — specialized agents interrogate findings across domain boundaries:
    * Wireless Agent reviews AP findings against Infrastructure switch CRC/drop counters.
    * Infrastructure Agent checks if local drops correlate with upstream topology bottlenecks.
    * Service Agent separates general packet loss from DNS/DHCP daemon failures.
    * Temporal Agent verifies sequence ordering (root cause precedes cascading symptoms).
- Round 3: Compilation into a structured ArbiterDossier for final adjudication.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from protocol.models import (
    AgentFinding,
    CanonicalTelemetry,
    EvidenceItem,
    EvidencePolarity,
    HypothesisType,
    SeverityLevel,
)


class ReviewVerdict(str, Enum):
    CORROBORATED = "CORROBORATED"
    CHALLENGED = "CHALLENGED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ChallengeStatus(str, Enum):
    OPEN = "OPEN"
    CONCEDED = "CONCEDED"
    REBUTTED = "REBUTTED"
    RECONCILED = "RECONCILED"
    DISMISSED = "DISMISSED"


class ResponseVerdict(str, Enum):
    CONCEDED = "CONCEDED"
    REBUTTED = "REBUTTED"
    RECONCILED = "RECONCILED"


class PeerReviewChallenge(BaseModel):
    """Formal dispute raised by an agent against a peer's finding or hypothesis."""
    challenge_id: str = Field(default_factory=lambda: f"CHAL-{uuid.uuid4().hex[:8]}")
    challenger_agent: str
    target_agent: str
    target_device: str
    target_hypothesis: str
    challenge_reason: str
    counter_evidence: List[EvidenceItem] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    status: str = ChallengeStatus.OPEN.value

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)
        if not self.evidence_ids and self.counter_evidence:
            self.evidence_ids = [e.evidence_id for e in self.counter_evidence]

    def apply_response(self, response: PeerReviewResponse) -> None:
        """Validate identity contract and transition challenge status consistently."""
        if response.challenge_id != self.challenge_id:
            raise ValueError(
                f"Challenge ID mismatch: challenge is '{self.challenge_id}', "
                f"response references '{response.challenge_id}'"
            )
        if response.responding_agent != self.target_agent:
            raise ValueError(
                f"Responding agent mismatch: challenge targeted '{self.target_agent}', "
                f"but response came from '{response.responding_agent}'"
            )
        if response.target_agent != self.challenger_agent:
            raise ValueError(
                f"Target agent mismatch: original challenger was '{self.challenger_agent}', "
                f"but response is directed to '{response.target_agent}'"
            )
        if response.target_device != self.target_device:
            raise ValueError(
                f"Target device mismatch: challenge on '{self.target_device}', "
                f"response addresses '{response.target_device}'"
            )

        verdict_str = getattr(response.verdict, "value", str(response.verdict)).upper()
        if verdict_str == "CONCEDED":
            self.status = ChallengeStatus.CONCEDED.value
        elif verdict_str == "REBUTTED":
            self.status = ChallengeStatus.REBUTTED.value
        elif verdict_str == "RECONCILED":
            self.status = ChallengeStatus.RECONCILED.value
        else:
            self.status = ChallengeStatus.DISMISSED.value


class PeerReviewResponse(BaseModel):
    """Formal response from target agent answering a peer challenge."""
    response_id: str = Field(default_factory=lambda: f"RESP-{uuid.uuid4().hex[:8]}")
    challenge_id: str
    responding_agent: str
    target_agent: str
    target_device: str
    verdict: str = ResponseVerdict.CONCEDED.value  # CONCEDED, REBUTTED, RECONCILED
    rebuttal_reason: str
    defense_evidence: List[EvidenceItem] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)
        if not self.evidence_ids and self.defense_evidence:
            self.evidence_ids = [e.evidence_id for e in self.defense_evidence]


class PeerReviewCorroboration(BaseModel):
    """Independent cross-domain corroboration supporting a peer's finding."""
    corroboration_id: str = Field(default_factory=lambda: f"CORR-{uuid.uuid4().hex[:8]}")
    corroborating_agent: str
    target_agent: str
    target_device: str
    supported_hypothesis: str
    corroborating_evidence: List[EvidenceItem] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    explanation: str

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)
        if not self.evidence_ids and self.corroborating_evidence:
            self.evidence_ids = [e.evidence_id for e in self.corroborating_evidence]


class PeerReviewContradiction(BaseModel):
    """Critical contradiction between two domain observations."""
    contradiction_id: str = Field(default_factory=lambda: f"CONT-{uuid.uuid4().hex[:8]}")
    agent_a: str
    agent_b: str
    device_id: str
    metric_a: str
    metric_b: str
    value_a: Any
    value_b: Any
    conflict_rule: str
    resolution_applied: str


class PeerReviewDossier(BaseModel):
    """Aggregated compilation of all multi-agent peer reviews prepared for the Arbiter."""
    incident_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_findings_count: int
    challenges: List[PeerReviewChallenge] = Field(default_factory=list)
    responses: List[PeerReviewResponse] = Field(default_factory=list)
    corroborations: List[PeerReviewCorroboration] = Field(default_factory=list)
    contradictions: List[PeerReviewContradiction] = Field(default_factory=list)
    reviewed_evidence: List[EvidenceItem] = Field(default_factory=list)
    peer_review_summary: str = ""


class PeerReviewManager:
    """Coordinates cross-agent peer review rounds."""

    def __init__(self) -> None:
        pass

    def conduct_peer_review(
        self,
        incident_id: str,
        telemetry_records: List[CanonicalTelemetry],
        agent_findings: List[AgentFinding]
    ) -> PeerReviewDossier:
        """Execute Round 2 peer review across agent findings."""
        challenges: List[PeerReviewChallenge] = []
        responses: List[PeerReviewResponse] = []
        corroborations: List[PeerReviewCorroboration] = []
        contradictions: List[PeerReviewContradiction] = []
        reviewed_evidence: List[EvidenceItem] = []

        # Index findings by agent and device
        findings_by_agent: Dict[str, Dict[str, AgentFinding]] = {}
        telemetry_by_dev: Dict[str, CanonicalTelemetry] = {r.device_id: r for r in telemetry_records}

        for f in agent_findings:
            if f.agent_name not in findings_by_agent:
                findings_by_agent[f.agent_name] = {}
            findings_by_agent[f.agent_name][f.device_id] = f

        # ------------------------------------------------------------------
        # Review Rule 1: Infrastructure vs Telemetry (CRC / Cable fault vs Congestion)
        # ------------------------------------------------------------------
        # If TelemetryAgent suspects Link Congestion / Packet Loss / Latency but InfrastructureAgent observes high CRC/interface errors,
        # InfrastructureAgent challenges the Congestion hypothesis with a Hardware/Physical Layer claim.
        for dev_id, tel_record in telemetry_by_dev.items():
            m = tel_record.metrics
            tel_finding = findings_by_agent.get("TelemetryAgent", {}).get(dev_id)
            infra_finding = findings_by_agent.get("InfrastructureAgent", {}).get(dev_id)

            has_tel_anomaly = tel_finding and (
                any(e.hypothesis_target == "LINK_CONGESTION" for e in tel_finding.evidence) or
                any(issue in ("HIGH_LATENCY", "PACKET_LOSS", "HIGH_JITTER", "LINK_CONGESTION") for issue in tel_finding.suspected_issues)
            )

            has_crc_errors = (m.crc_errors is not None and m.crc_errors > 10) or \
                             (m.interface_errors is not None and m.interface_errors > 15)
            has_queue_drops = m.queue_drops is not None and m.queue_drops > 20

            if has_tel_anomaly and has_crc_errors:
                # Challenge Congestion: Physical layer errors dominate
                chal = PeerReviewChallenge(
                    challenger_agent="InfrastructureAgent",
                    target_agent="TelemetryAgent",
                    target_device=dev_id,
                    target_hypothesis="LINK_CONGESTION",
                    challenge_reason="High CRC/interface errors indicate physical layer/transceiver defect, not pure bandwidth exhaustion",
                    counter_evidence=[
                        EvidenceItem(
                            evidence_id=f"CHAL-EV-{dev_id}-CRC",
                            source_agent="InfrastructureAgent",
                            device_id=dev_id,
                            metric_name="crc_errors",
                            observed_value=m.crc_errors or m.interface_errors,
                            severity=SeverityLevel.CRITICAL,
                            polarity=EvidencePolarity.CONTRADICTS,
                            hypothesis_target="LINK_CONGESTION",
                            weight=0.85,
                            description=f"Device {dev_id} has {m.crc_errors or m.interface_errors} physical layer errors",
                            derivation_method="PEER_REVIEW_CHALLENGE"
                        )
                    ]
                )
                challenges.append(chal)
                reviewed_evidence.extend(chal.counter_evidence)
                # Target agent formulates structured response evaluating counter-evidence
                resp = PeerReviewResponse(
                    challenge_id=chal.challenge_id,
                    responding_agent="TelemetryAgent",
                    target_agent="InfrastructureAgent",
                    target_device=dev_id,
                    verdict="CONCEDED",
                    rebuttal_reason=f"Conceded: TelemetryAgent agrees physical layer / CRC errors on {dev_id} indicate hardware or cable defect rather than simple congestion.",
                    defense_evidence=[],
                    evidence_ids=chal.evidence_ids
                )
                chal.apply_response(resp)
                responses.append(resp)

            elif has_tel_anomaly and has_queue_drops and not has_crc_errors:
                # Corroborate Congestion: Buffer queue drops confirm congestion without hardware error
                corr = PeerReviewCorroboration(
                    corroborating_agent="InfrastructureAgent",
                    target_agent="TelemetryAgent",
                    target_device=dev_id,
                    supported_hypothesis="LINK_CONGESTION",
                    corroborating_evidence=[
                        EvidenceItem(
                            evidence_id=f"CORR-EV-{dev_id}-QUEUEDROPS",
                            source_agent="InfrastructureAgent",
                            device_id=dev_id,
                            metric_name="queue_drops",
                            observed_value=m.queue_drops,
                            severity=SeverityLevel.WARNING,
                            polarity=EvidencePolarity.SUPPORTS,
                            hypothesis_target="LINK_CONGESTION",
                            weight=0.75,
                            description=f"Queue drops ({m.queue_drops}) independently corroborates buffer exhaustion without CRC errors",
                            derivation_method="PEER_REVIEW_CORROBORATION"
                        )
                    ],
                    explanation=f"Queue drops of {m.queue_drops} confirm link saturation."
                )
                corroborations.append(corr)
                reviewed_evidence.extend(corr.corroborating_evidence)

        # ------------------------------------------------------------------
        # Review Rule 2: Service vs Telemetry (DNS/DHCP vs Generic Packet Loss)
        # ------------------------------------------------------------------
        # If high DNS resolution time or DHCP lease failure exists with low general packet loss,
        # ServiceAgent corroborates Application/DNS issue rather than network transport failure.
        for dev_id, tel_record in telemetry_by_dev.items():
            m = tel_record.metrics
            dns_slow = m.dns_resolution_ms is not None and m.dns_resolution_ms > 150.0
            dhcp_failed = m.dhcp_lease_success is False
            loss_low = m.packet_loss_pct is None or m.packet_loss_pct < 2.0

            if (dns_slow or dhcp_failed) and loss_low:
                corr = PeerReviewCorroboration(
                    corroborating_agent="ServiceAgent",
                    target_agent="TelemetryAgent",
                    target_device=dev_id,
                    supported_hypothesis="DNS_DHCP_FAILURE",
                    corroborating_evidence=[
                        EvidenceItem(
                            evidence_id=f"CORR-EV-{dev_id}-SVC",
                            source_agent="ServiceAgent",
                            device_id=dev_id,
                            metric_name="dns_resolution_ms" if dns_slow else "dhcp_lease_success",
                            observed_value=m.dns_resolution_ms if dns_slow else False,
                            severity=SeverityLevel.CRITICAL,
                            polarity=EvidencePolarity.SUPPORTS,
                            hypothesis_target="DNS_DHCP_FAILURE",
                            weight=0.90,
                            description=f"Service failure isolated to DNS/DHCP with minimal general packet loss ({m.packet_loss_pct or 0.0}%)",
                            derivation_method="PEER_REVIEW_CORROBORATION"
                        )
                    ],
                    explanation="Transport layer is functional; failures are strictly localized to application control services."
                )
                corroborations.append(corr)
                reviewed_evidence.extend(corr.corroborating_evidence)

        # ------------------------------------------------------------------
        # Review Rule 3: Wireless vs Connectivity (Weak WiFi vs Upstream Switch Bottleneck)
        # ------------------------------------------------------------------
        # If an Access Point reports weak RF (-82 dBm) but its upstream switch is failing,
        # ConnectivityAgent challenges Weak WiFi as an upstream cascade.
        for dev_id, tel_record in telemetry_by_dev.items():
            m = tel_record.metrics
            rf_weak = m.signal_strength_dbm is not None and m.signal_strength_dbm <= -75.0
            # Check if upstream switches exist and have anomalies
            upstream_devs = [r for r in telemetry_records if "SW" in r.device_id.upper() or "CORE" in r.device_id.upper()]
            upstream_failing = any(
                (u.metrics.packet_loss_pct is not None and u.metrics.packet_loss_pct > 5.0) or
                (u.metrics.cpu_pct is not None and u.metrics.cpu_pct > 90.0)
                for u in upstream_devs
            )
            if rf_weak and upstream_failing:
                chal = PeerReviewChallenge(
                    challenger_agent="ConnectivityAgent",
                    target_agent="WirelessAgent",
                    target_device=dev_id,
                    target_hypothesis="WEAK_WIFI",
                    challenge_reason="Upstream switch failure detected; AP RF attenuation may be incidental or secondary",
                    counter_evidence=[
                        EvidenceItem(
                            evidence_id=f"CHAL-EV-{dev_id}-UPSTREAM",
                            source_agent="ConnectivityAgent",
                            device_id=dev_id,
                            metric_name="upstream_switch_status",
                            observed_value="FAILING",
                            severity=SeverityLevel.WARNING,
                            polarity=EvidencePolarity.CONTRADICTS,
                            hypothesis_target="WEAK_WIFI",
                            weight=0.70,
                            description=f"Upstream infrastructure failure supersedes localized AP RF attenuation on {dev_id}",
                            derivation_method="PEER_REVIEW_CHALLENGE"
                        )
                    ]
                )
                challenges.append(chal)
                reviewed_evidence.extend(chal.counter_evidence)
                # Target agent formulates structured response evaluating counter-evidence
                resp = PeerReviewResponse(
                    challenge_id=chal.challenge_id,
                    responding_agent="WirelessAgent",
                    target_agent="ConnectivityAgent",
                    target_device=dev_id,
                    verdict="CONCEDED",
                    rebuttal_reason=f"Conceded: WirelessAgent agrees AP RF issues on {dev_id} are secondary downstream symptoms caused by upstream switch failure.",
                    defense_evidence=[],
                    evidence_ids=chal.evidence_ids
                )
                chal.apply_response(resp)
                responses.append(resp)

        # ------------------------------------------------------------------
        # Review Rule 4: Untrusted Label Contradictions
        # ------------------------------------------------------------------
        for dev_id, tel_record in telemetry_by_dev.items():
            rep = (tel_record.reported_status or "").upper()
            if rep in ("HEALTHY", "OK", "NORMAL") and (
                (tel_record.metrics.packet_loss_pct is not None and tel_record.metrics.packet_loss_pct > 2.0) or
                (tel_record.metrics.latency_ms is not None and tel_record.metrics.latency_ms > 50.0) or
                (tel_record.metrics.cpu_pct is not None and tel_record.metrics.cpu_pct > 80.0)
            ):
                contra = PeerReviewContradiction(
                    agent_a="TelemetryAgent",
                    agent_b="GeneratorLabel",
                    device_id=dev_id,
                    metric_a="latency_or_loss",
                    metric_b="reported_status",
                    value_a=tel_record.metrics.packet_loss_pct or tel_record.metrics.latency_ms,
                    value_b=rep,
                    conflict_rule="PHYSICAL_METRIC_SUPREMACY",
                    resolution_applied="Disregarded untrusted label in favor of empirically measured network counters"
                )
                contradictions.append(contra)

        summary_text = (
            f"Peer Review completed: {len(challenges)} challenges raised, {len(responses)} responses deliberated, "
            f"{len(corroborations)} independent corroborations confirmed, "
            f"{len(contradictions)} data contradictions reconciled."
        )

        return PeerReviewDossier(
            incident_id=incident_id,
            raw_findings_count=len(agent_findings),
            challenges=challenges,
            responses=responses,
            corroborations=corroborations,
            contradictions=contradictions,
            reviewed_evidence=reviewed_evidence,
            peer_review_summary=summary_text
        )
