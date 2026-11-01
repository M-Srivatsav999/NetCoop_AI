"""Unit and integration test suite for Peer Review Manager and Arbiter Agent.

Validates:
- Peer review challenge generation (Hardware CRC vs Congestion)
- Peer review corroboration generation (Queue drops without errors)
- Service domain corroboration (DNS latency isolation)
- Untrusted label contradiction reconciliation
- Dedicated Arbiter ranking, accepted rationale, and rejected alternatives
- Full pipeline backward compatibility through ArbiterDecision.to_arbitration_result()
- Explicit abstention when telemetry is insufficient
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from agents.arbiter_agent import ArbiterAgent, ArbiterDecision
from agents.peer_review_manager import (
    ChallengeStatus,
    PeerReviewChallenge,
    PeerReviewDossier,
    PeerReviewManager,
    PeerReviewResponse,
    ResponseVerdict,
)
from agents.telemetry_agent import TelemetryAgent
from agents.infrastructure_agent import InfrastructureAgent
from protocol.models import (
    CanonicalMetrics,
    CanonicalTelemetry,
    SchemaVersion,
    SeverityLevel,
)


def _make_telemetry(device_id: str, **kwargs) -> CanonicalTelemetry:
    metrics = CanonicalMetrics(**kwargs)
    return CanonicalTelemetry(
        device_id=device_id,
        timestamp=datetime.now(timezone.utc),
        reported_status=kwargs.get("reported_status", "UP"),
        metrics=metrics,
        schema_version_detected=SchemaVersion.V1
    )


def test_peer_review_challenge_hardware_vs_congestion():
    """Verify InfrastructureAgent challenges TelemetryAgent's congestion hypothesis when CRC errors exist."""
    # Device with high latency and packet loss (triggering congestion suspicion) AND high CRC errors
    rec = _make_telemetry("SW-CORE-01", latency_ms=85.0, packet_loss_pct=8.0, crc_errors=35, interface_errors=40)
    
    tel_agent = TelemetryAgent()
    infra_agent = InfrastructureAgent()
    prm = PeerReviewManager()

    findings = tel_agent.analyze_batch([rec]) + infra_agent.analyze_batch([rec])
    dossier = prm.conduct_peer_review(
        incident_id="INC-PEER-1",
        telemetry_records=[rec],
        agent_findings=findings
    )

    assert len(dossier.challenges) >= 1
    chal = dossier.challenges[0]
    assert chal.challenger_agent == "InfrastructureAgent"
    assert chal.target_agent == "TelemetryAgent"
    assert chal.target_hypothesis == "LINK_CONGESTION"
    assert "physical layer" in chal.challenge_reason.lower()


def test_peer_review_corroboration_queue_drops_without_crc():
    """Verify InfrastructureAgent corroborates Link Congestion when queue drops exist without CRC errors."""
    rec = _make_telemetry("SW-DIST-01", latency_ms=65.0, packet_loss_pct=4.0, queue_drops=45, crc_errors=0, interface_errors=0)
    
    tel_agent = TelemetryAgent()
    infra_agent = InfrastructureAgent()
    prm = PeerReviewManager()

    findings = tel_agent.analyze_batch([rec]) + infra_agent.analyze_batch([rec])
    dossier = prm.conduct_peer_review(
        incident_id="INC-PEER-2",
        telemetry_records=[rec],
        agent_findings=findings
    )

    assert len(dossier.corroborations) >= 1
    corr = dossier.corroborations[0]
    assert corr.corroborating_agent == "InfrastructureAgent"
    assert corr.supported_hypothesis == "LINK_CONGESTION"
    assert "queue drops" in corr.explanation.lower()


def test_peer_review_service_domain_corroboration():
    """Verify Service domain isolates DNS failure when general transport packet loss is negligible."""
    rec = _make_telemetry("SRV-DNS-01", dns_resolution_ms=350.0, packet_loss_pct=0.2, latency_ms=12.0)
    
    prm = PeerReviewManager()
    dossier = prm.conduct_peer_review(
        incident_id="INC-PEER-3",
        telemetry_records=[rec],
        agent_findings=[]
    )

    assert len(dossier.corroborations) >= 1
    corr = dossier.corroborations[0]
    assert corr.corroborating_agent == "ServiceAgent"
    assert corr.supported_hypothesis == "DNS_DHCP_FAILURE"
    assert "isolated to dns" in corr.corroborating_evidence[0].description.lower()


def test_peer_review_untrusted_label_contradiction():
    """Verify PeerReviewManager flags contradiction when reported status is HEALTHY despite severe packet loss."""
    rec = _make_telemetry("RTR-GW-01", packet_loss_pct=15.0, latency_ms=90.0)
    rec.reported_status = "HEALTHY"

    prm = PeerReviewManager()
    dossier = prm.conduct_peer_review(
        incident_id="INC-PEER-4",
        telemetry_records=[rec],
        agent_findings=[]
    )

    assert len(dossier.contradictions) >= 1
    contra = dossier.contradictions[0]
    assert contra.agent_b == "GeneratorLabel"
    assert contra.conflict_rule == "PHYSICAL_METRIC_SUPREMACY"


def test_arbiter_agent_ranking_and_rejected_alternatives():
    """Verify ArbiterAgent generates ranked hypotheses, accepted rationale, and rejected alternatives."""
    # Link congestion scenario: high latency, moderate packet loss, high queue drops, zero CRC
    rec = _make_telemetry("SW-ACCESS-01", latency_ms=75.0, packet_loss_pct=6.0, queue_drops=80, crc_errors=0)
    
    tel_agent = TelemetryAgent()
    infra_agent = InfrastructureAgent()
    arbiter = ArbiterAgent()

    findings = tel_agent.analyze_batch([rec]) + infra_agent.analyze_batch([rec])
    decision: ArbiterDecision = arbiter.arbitrate(
        telemetry_records=[rec],
        agent_findings=findings,
        incident_id="INC-ARB-1"
    )

    assert decision.status == "DIAGNOSED"
    assert decision.primary_root_cause == "LINK_CONGESTION"
    assert decision.calibrated_confidence > 0.0
    assert len(decision.accepted_rationale) > 20
    assert "LINK_CONGESTION" in decision.accepted_rationale

    # Verify ranked hypotheses
    assert len(decision.ranked_hypotheses) > 1
    rank1 = decision.ranked_hypotheses[0]
    assert rank1.hypothesis == "LINK_CONGESTION"
    assert rank1.rank == 1
    assert rank1.adjudication_status == "ACCEPTED"

    # Verify rejected alternatives contain justifications
    assert len(decision.rejected_alternatives) > 0
    assert "HARDWARE_FAILURE" in decision.rejected_alternatives

    # Verify conversion to backward-compatible ArbitrationResult
    arb_result = decision.to_arbitration_result()
    assert arb_result.primary_root_cause == "LINK_CONGESTION"
    assert arb_result.confidence == decision.calibrated_confidence
    assert len(arb_result.alternative_hypotheses) > 0


def test_arbiter_agent_abstention_on_insufficient_evidence():
    """Verify ArbiterAgent explicitly abstains when telemetry has no anomalous signals or is empty."""
    rec = _make_telemetry("DEV-CLEAN-01")  # No metrics populated
    arbiter = ArbiterAgent()

    decision = arbiter.arbitrate(
        telemetry_records=[rec],
        agent_findings=[],
        incident_id="INC-ARB-2"
    )

    assert decision.status in ("INSUFFICIENT_EVIDENCE", "INCONCLUSIVE")
    assert decision.primary_root_cause == "INSUFFICIENT_EVIDENCE"
    assert "withheld" in decision.accepted_rationale.lower()


def test_peer_review_identity_enforcement():
    """Verify that PeerReviewChallenge.apply_response enforces strict agent and device identity."""
    chal = PeerReviewChallenge(
        challenger_agent="InfrastructureAgent",
        target_agent="TelemetryAgent",
        target_device="SW-CORE-01",
        target_hypothesis="LINK_CONGESTION",
        challenge_reason="High CRC errors indicate transceiver fault"
    )
    assert chal.status == "OPEN"

    # 1. Invalid responding_agent rejected
    bad_responder = PeerReviewResponse(
        challenge_id=chal.challenge_id,
        responding_agent="WirelessAgent",  # Wrong responder!
        target_agent="InfrastructureAgent",
        target_device="SW-CORE-01",
        verdict="CONCEDED",
        rebuttal_reason="Conceded"
    )
    with pytest.raises(ValueError) as exc1:
        chal.apply_response(bad_responder)
    assert "Responding agent mismatch" in str(exc1.value)

    # 2. Invalid target_agent rejected
    bad_target = PeerReviewResponse(
        challenge_id=chal.challenge_id,
        responding_agent="TelemetryAgent",
        target_agent="ConnectivityAgent",  # Wrong target!
        target_device="SW-CORE-01",
        verdict="CONCEDED",
        rebuttal_reason="Conceded"
    )
    with pytest.raises(ValueError) as exc2:
        chal.apply_response(bad_target)
    assert "Target agent mismatch" in str(exc2.value)

    # 3. Invalid challenge_id rejected
    bad_id = PeerReviewResponse(
        challenge_id="CHAL-OTHER-99",
        responding_agent="TelemetryAgent",
        target_agent="InfrastructureAgent",
        target_device="SW-CORE-01",
        verdict="CONCEDED",
        rebuttal_reason="Conceded"
    )
    with pytest.raises(ValueError) as exc3:
        chal.apply_response(bad_id)
    assert "Challenge ID mismatch" in str(exc3.value)

    # 4. Invalid target_device rejected
    bad_dev = PeerReviewResponse(
        challenge_id=chal.challenge_id,
        responding_agent="TelemetryAgent",
        target_agent="InfrastructureAgent",
        target_device="AP-ENG-02",  # Wrong device!
        verdict="CONCEDED",
        rebuttal_reason="Conceded"
    )
    with pytest.raises(ValueError) as exc4:
        chal.apply_response(bad_dev)
    assert "Target device mismatch" in str(exc4.value)


def test_peer_review_rebuttal_and_concession_status_transitions():
    """Verify that CONCEDED, REBUTTED, and RECONCILED produce consistent challenge status transitions."""
    chal1 = PeerReviewChallenge(
        challenger_agent="ConnectivityAgent",
        target_agent="WirelessAgent",
        target_device="AP-HOSTEL-01",
        target_hypothesis="WEAK_WIFI",
        challenge_reason="Upstream switch down"
    )
    resp1 = PeerReviewResponse(
        challenge_id=chal1.challenge_id,
        responding_agent="WirelessAgent",
        target_agent="ConnectivityAgent",
        target_device="AP-HOSTEL-01",
        verdict="CONCEDED",
        rebuttal_reason="Conceded: Upstream failure causes AP client loss"
    )
    chal1.apply_response(resp1)
    assert chal1.status == "CONCEDED"

    # Rebuttal case
    chal2 = PeerReviewChallenge(
        challenger_agent="InfrastructureAgent",
        target_agent="TelemetryAgent",
        target_device="SW-ENG-02",
        target_hypothesis="LINK_CONGESTION",
        challenge_reason="Speculative error claim"
    )
    resp2 = PeerReviewResponse(
        challenge_id=chal2.challenge_id,
        responding_agent="TelemetryAgent",
        target_agent="InfrastructureAgent",
        target_device="SW-ENG-02",
        verdict="REBUTTED",
        rebuttal_reason="Rebutted: Zero CRC errors observed; buffer saturation verified by 98% utilization"
    )
    chal2.apply_response(resp2)
    assert chal2.status == "REBUTTED"


# ==============================================================================
# Comprehensive Peer Review Lifecycle Regression Suite (8 Mandatory Conditions)
# ==============================================================================

def test_peer_review_lifecycle_1_agreement():
    """Condition 1: Agreement / Independent Corroboration across agents."""
    prm = PeerReviewManager()
    rec = _make_telemetry("SW-DIST-01", latency_ms=85.0, packet_loss_pct=4.0, queue_drops=60, crc_errors=0)
    dossier = prm.conduct_peer_review(
        incident_id="INC-AGREE-01",
        telemetry_records=[rec],
        agent_findings=[
            TelemetryAgent().analyze_batch([rec])[0],
            InfrastructureAgent().analyze_batch([rec])[0]
        ]
    )
    # Corroboration confirmed without contradiction
    assert len(dossier.corroborations) >= 1
    corr = dossier.corroborations[0]
    assert corr.supported_hypothesis == "LINK_CONGESTION"
    assert corr.corroborating_agent == "InfrastructureAgent"
    assert "queue drops" in corr.explanation.lower()


def test_peer_review_lifecycle_2_disagreement():
    """Condition 2: Disagreement / Formal challenge raised when domain signals collide."""
    prm = PeerReviewManager()
    rec = _make_telemetry("SW-CORE-01", latency_ms=90.0, packet_loss_pct=7.5, crc_errors=50, interface_errors=60)
    dossier = prm.conduct_peer_review(
        incident_id="INC-DISAGREE-02",
        telemetry_records=[rec],
        agent_findings=[
            TelemetryAgent().analyze_batch([rec])[0],
            InfrastructureAgent().analyze_batch([rec])[0]
        ]
    )
    assert len(dossier.challenges) >= 1
    chal = dossier.challenges[0]
    assert chal.challenger_agent == "InfrastructureAgent"
    assert chal.target_agent == "TelemetryAgent"
    assert chal.target_hypothesis == "LINK_CONGESTION"
    assert chal.status in ("CONCEDED", "OPEN")


def test_peer_review_lifecycle_3_valid_rebuttal():
    """Condition 3: Valid Rebuttal / Challenged agent defends hypothesis with empirical counters."""
    chal = PeerReviewChallenge(
        challenger_agent="InfrastructureAgent",
        target_agent="TelemetryAgent",
        target_device="SW-CORE-01",
        target_hypothesis="LINK_CONGESTION",
        challenge_reason="Suspect hardware fault due to intermittent frame drop"
    )
    resp = PeerReviewResponse(
        challenge_id=chal.challenge_id,
        responding_agent="TelemetryAgent",
        target_agent="InfrastructureAgent",
        target_device="SW-CORE-01",
        verdict=ResponseVerdict.REBUTTED.value,
        rebuttal_reason="Rebutted: CRC counters strictly zero; buffer queue depth is 100% full, proving congestion.",
        evidence_ids=["EV-QUEUE-FULL-01"]
    )
    chal.apply_response(resp)
    assert chal.status == ChallengeStatus.REBUTTED.value


def test_peer_review_lifecycle_4_valid_concession():
    """Condition 4: Valid Concession / Challenged agent yields to superior physical layer evidence."""
    chal = PeerReviewChallenge(
        challenger_agent="InfrastructureAgent",
        target_agent="TelemetryAgent",
        target_device="SW-CORE-01",
        target_hypothesis="LINK_CONGESTION",
        challenge_reason="Physical interface CRC error count exceeds 50"
    )
    resp = PeerReviewResponse(
        challenge_id=chal.challenge_id,
        responding_agent="TelemetryAgent",
        target_agent="InfrastructureAgent",
        target_device="SW-CORE-01",
        verdict=ResponseVerdict.CONCEDED.value,
        rebuttal_reason="Conceded: Physical CRC errors dominate; relinquishing congestion hypothesis.",
        evidence_ids=chal.evidence_ids
    )
    chal.apply_response(resp)
    assert chal.status == ChallengeStatus.CONCEDED.value


def test_peer_review_lifecycle_5_invalid_response_identity():
    """Condition 5: Invalid response identity rejected fail-closed."""
    chal = PeerReviewChallenge(
        challenger_agent="ConnectivityAgent",
        target_agent="WirelessAgent",
        target_device="AP-ENG-01",
        target_hypothesis="WEAK_WIFI",
        challenge_reason="Upstream switch outage"
    )
    # 1. Imposter agent
    imposter = PeerReviewResponse(
        challenge_id=chal.challenge_id,
        responding_agent="InfrastructureAgent",  # Invalid
        target_agent="ConnectivityAgent",
        target_device="AP-ENG-01",
        verdict="CONCEDED",
        rebuttal_reason="Imposter response"
    )
    with pytest.raises(ValueError) as exc1:
        chal.apply_response(imposter)
    assert "Responding agent mismatch" in str(exc1.value)

    # 2. Imposter device
    wrong_dev = PeerReviewResponse(
        challenge_id=chal.challenge_id,
        responding_agent="WirelessAgent",
        target_agent="ConnectivityAgent",
        target_device="SW-OTHER-99",  # Invalid
        verdict="CONCEDED",
        rebuttal_reason="Wrong device response"
    )
    with pytest.raises(ValueError) as exc2:
        chal.apply_response(wrong_dev)
    assert "Target device mismatch" in str(exc2.value)


def test_peer_review_lifecycle_6_missing_evidence():
    """Condition 6: Missing evidence items handling in challenge/response."""
    chal = PeerReviewChallenge(
        challenger_agent="InfrastructureAgent",
        target_agent="TelemetryAgent",
        target_device="SW-CORE-01",
        target_hypothesis="HARDWARE_FAILURE",
        challenge_reason="Asserting hardware failure without supplied counter-evidence",
        counter_evidence=[]
    )
    assert len(chal.evidence_ids) == 0
    # Dossier aggregates reviewed evidence cleanly even when items are sparse
    prm = PeerReviewManager()
    dossier = prm.conduct_peer_review("INC-SPARSE", [], [])
    assert dossier.challenges == []
    assert dossier.reviewed_evidence == []


def test_peer_review_lifecycle_7_conflicting_evidence():
    """Condition 7: Conflicting cross-domain observations captured as formal contradictions."""
    prm = PeerReviewManager()
    rec = _make_telemetry("SW-EDGE-01", packet_loss_pct=12.0, latency_ms=110.0)
    rec.reported_status = "HEALTHY"  # Conflicting generator label

    dossier = prm.conduct_peer_review(
        incident_id="INC-CONFLICT-07",
        telemetry_records=[rec],
        agent_findings=[]
    )
    assert len(dossier.contradictions) >= 1
    contra = dossier.contradictions[0]
    assert contra.conflict_rule == "PHYSICAL_METRIC_SUPREMACY"
    assert contra.agent_b == "GeneratorLabel"
    assert "empirically measured" in contra.resolution_applied


def test_peer_review_lifecycle_8_unresolved_disagreement():
    """Condition 8: Unresolved disagreement remains in OPEN status."""
    chal = PeerReviewChallenge(
        challenger_agent="ConnectivityAgent",
        target_agent="WirelessAgent",
        target_device="AP-LIB-01",
        target_hypothesis="WEAK_WIFI",
        challenge_reason="Unresolved dispute regarding whether loss is RF or backhaul link"
    )
    # Challenge remains open when no response has been delivered
    assert chal.status == ChallengeStatus.OPEN.value
    assert chal.status != ChallengeStatus.CONCEDED.value
    assert chal.status != ChallengeStatus.REBUTTED.value

