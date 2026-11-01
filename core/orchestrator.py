"""Central Network Intelligence Orchestrator.

Coordinates schema normalization, specialized agent dispatch, typed inter-agent messaging,
evidence aggregation, arbitration, report generation, and explainable trace logging.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

from agents.connectivity_agent import ConnectivityAgent
from agents.correlation_agent import CorrelationAgent
from agents.infrastructure_agent import InfrastructureAgent
from agents.reporter_agent import ReporterAgent
from agents.telemetry_agent import TelemetryAgent
from agents.peer_review_manager import PeerReviewManager, PeerReviewDossier
from agents.arbiter_agent import ArbiterAgent, ArbiterDecision
from core.confidence_engine import ConfidenceConfig
from core.rules import MetricThresholds
from core.topology import TopologyEngine
from core.hypothesis_engine import HypothesisEngine, HypothesisScore
from core.evidence_ledger import EvidenceLedger
from core.evidence_graph import EvidenceGraph
from core.temporal_engine import TemporalCausalEngine, TemporalEvent
from core.investigation_engine import InvestigationEngine, DiagnosticCheck, OperationalAction
from protocol.agent_message_protocol import (
    AgentMessageBus,
    AgentProtocolMessage,
    MessageAckStatus,
    ProtocolAuditEntry,
    ProtocolMessageType,
    ProtocolValidationError,
)
from protocol.interop_gateway import InteroperabilityGateway, InteroperabilityReport
from protocol.models import (
    AgentFinding,
    AgentMessage,
    ArbitrationResult,
    CanonicalTelemetry,
    SchemaVersion,
    UnifiedIncidentReport,
)
from protocol.validator import TelemetryNormalizer


class OrchestrationResult(BaseModel):
    """Complete, self-contained output of an orchestration cycle."""
    report: UnifiedIncidentReport
    markdown_summary: str
    canonical_telemetry: List[CanonicalTelemetry]
    agent_findings: List[AgentFinding]
    agent_messages: List[Union[AgentProtocolMessage, AgentMessage]]
    arbitration_result: ArbitrationResult
    execution_trace: List[Dict[str, Any]]
    total_duration_ms: float
    interoperability_report: Optional[InteroperabilityReport] = None
    investigation_plan: List[DiagnosticCheck] = Field(default_factory=list)
    safe_remediation_actions: List[OperationalAction] = Field(default_factory=list)
    hypothesis_evaluations: List[HypothesisScore] = Field(default_factory=list)
    evidence_ledger_summary: Dict[str, Any] = Field(default_factory=dict)
    peer_review_dossier: Optional[PeerReviewDossier] = None
    arbiter_decision: Optional[ArbiterDecision] = None
    protocol_audit_trail: List[ProtocolAuditEntry] = Field(default_factory=list)
    temporal_events: List[TemporalEvent] = Field(default_factory=list)
    evidence_graph: Optional[EvidenceGraph] = None


class NetworkIntelligenceOrchestrator:
    """Production-grade deterministic multi-agent coordinator."""

    def __init__(
        self,
        topology_engine: Optional[TopologyEngine] = None,
        thresholds: Optional[MetricThresholds] = None,
        confidence_config: Optional[ConfidenceConfig] = None,
        strict_protocol_mode: bool = False
    ) -> None:
        self.topology = topology_engine or TopologyEngine()
        self.thresholds = thresholds or MetricThresholds()
        self.confidence_config = confidence_config or ConfidenceConfig()
        self.strict_protocol_mode = strict_protocol_mode

        # Instantiate specialized agents & engines
        self.telemetry_agent = TelemetryAgent(self.thresholds)
        self.infrastructure_agent = InfrastructureAgent(self.thresholds)
        self.connectivity_agent = ConnectivityAgent(self.topology)
        self.correlation_agent = CorrelationAgent(
            topology_engine=self.topology,
            thresholds=self.thresholds,
            confidence_config=self.confidence_config
        )
        self.peer_review_manager = PeerReviewManager()
        self.arbiter_agent = ArbiterAgent(
            topology_engine=self.topology,
            thresholds=self.thresholds,
            confidence_config=self.confidence_config
        )
        self.reporter_agent = ReporterAgent()
        self.message_bus = AgentMessageBus()
        self.temporal_engine = TemporalCausalEngine(topology_engine=self.topology)

    def process(
        self,
        raw_input: Union[Dict[str, Any], List[Dict[str, Any]], str],
        incident_id: Optional[str] = None,
        explicit_version: Optional[SchemaVersion] = None,
        reference_time: Optional[datetime] = None,
        telemetry_mode: str = "LIVE"
    ) -> OrchestrationResult:
        """Execute full end-to-end deterministic diagnostic pipeline with AMP/2.0 messaging, temporal reasoning, and evidence lineage."""
        start_time = datetime.now(timezone.utc)
        trace: List[Dict[str, Any]] = []
        inc_id = incident_id or f"INC-{uuid.uuid4().hex[:8].upper()}"
        corr_id = f"CORR-{inc_id}"
        messages: List[Union[AgentProtocolMessage, AgentMessage]] = []
        protocol_limitations: List[str] = []

        def log_trace(step: str, detail: str, data: Optional[Dict[str, Any]] = None) -> None:
            trace.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "step": step,
                "detail": detail,
                "data": data or {}
            })

        def emit_protocol_message(
            sender: str,
            recipient: str,
            message_type: Union[ProtocolMessageType, str],
            payload: Dict[str, Any],
            evidence_ids: Optional[List[str]] = None,
            confidence: Optional[float] = None,
            limitations: Optional[List[str]] = None
        ) -> AgentProtocolMessage:
            msg, ack = self.message_bus.create_and_publish(
                sender=sender,
                recipient=recipient,
                message_type=message_type,
                incident_id=inc_id,
                correlation_id=corr_id,
                payload=payload,
                evidence_ids=evidence_ids or [],
                confidence=confidence,
                limitations=limitations or [],
                current_time=reference_time or datetime.now(timezone.utc)
            )
            messages.append(msg)
            if ack.status == MessageAckStatus.NACK:
                log_trace(
                    "PROTOCOL_NACK",
                    f"Message rejected by MessageBus: {ack.reason}",
                    {"message_id": msg.message_id, "reason": ack.reason}
                )
                protocol_limitations.append(
                    f"Protocol NACK for message {msg.message_id} ({msg.message_type}): {ack.reason}"
                )
                if self.strict_protocol_mode:
                    raise ProtocolValidationError(
                        f"Protocol validation failed for {msg.message_id}: {ack.reason}"
                    )
            return msg

        # 1. Input parsing
        log_trace("INGESTION", "Parsing raw payload input.")
        if isinstance(raw_input, str):
            try:
                parsed_input = json.loads(raw_input)
            except Exception as e:
                log_trace("INGESTION_ERROR", f"JSON deserialization failed: {e}")
                parsed_input = [{"corrupt_payload": raw_input}]
        else:
            parsed_input = raw_input

        # 2. Schema Normalization & Interoperability Gateway
        log_trace("INTEROP_GATEWAY", "Invoking InteroperabilityGateway and SchemaFingerprinter across raw payload.")
        canonical_records, interop_report = InteroperabilityGateway.process_and_audit(
            parsed_input, explicit_version=explicit_version
        )
        detected_versions = list({r.schema_version_detected.value for r in canonical_records})
        total_warnings = sum(len(r.normalization_warnings) for r in canonical_records)

        log_trace(
            "CIM_GENERATION",
            f"Normalized {len(canonical_records)} devices. Detected schema: {interop_report.schema_detected} (valid={interop_report.schema_valid}).",
            {"schema_detected": interop_report.schema_detected, "unit_conversions": interop_report.unit_conversions, "warnings_count": total_warnings}
        )

        # 2b. Temporal & Causal Event Reconstruction
        log_trace("TEMPORAL_ANALYSIS", "Executing TemporalCausalEngine for chronological event sequencing.")
        self.temporal_engine = TemporalCausalEngine(topology_engine=self.topology)
        temporal_events = self.temporal_engine.process_timeline([[r for r in canonical_records]])

        # Initialize Central Diagnostic Evidence Ledger
        ledger = EvidenceLedger(correlation_id=corr_id)

        # 3. Freshness, Staleness & Clock Skew Assessment
        now = reference_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        staleness_seconds = 0.0
        timestamps = [r.timestamp for r in canonical_records if r.timestamp is not None]

        freshness_status = "FRESH"
        if not timestamps:
            freshness_status = "MISSING_TIMESTAMPS"
            protocol_limitations.append("Missing timestamps: no valid ISO8601 or epoch timestamps present in telemetry batch.")
        else:
            most_recent = max(timestamps)
            oldest = min(timestamps)
            if most_recent.tzinfo is None:
                most_recent = most_recent.replace(tzinfo=timezone.utc)
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=timezone.utc)

            delta = (now - most_recent).total_seconds()
            batch_spread = (most_recent - oldest).total_seconds()

            if delta < -5.0:
                future_skew = abs(delta)
                freshness_status = "FUTURE_CLOCK_SKEW"
                protocol_limitations.append(
                    f"Clock skew anomaly detected: telemetry timestamp {most_recent.isoformat()} is {round(future_skew, 1)}s in future relative to reference time ({now.isoformat()})."
                )
            elif delta > 7200.0:  # > 2 hours
                staleness_seconds = delta
                freshness_status = "CRITICALLY_STALE"
                protocol_limitations.append(
                    f"Critically stale telemetry: timestamp {most_recent.isoformat()} is {round(delta/3600.0, 1)}h old relative to evaluation reference time ({now.isoformat()})."
                )
            elif delta > 1800.0:  # > 30 minutes
                staleness_seconds = delta
                freshness_status = "AGED_WARNING"
                protocol_limitations.append(
                    f"Aged telemetry warning: timestamp {most_recent.isoformat()} is {round(delta/60.0, 1)}m old relative to evaluation reference time ({now.isoformat()})."
                )
            elif delta > 0:
                staleness_seconds = delta
                freshness_status = "FRESH"

            if batch_spread > 300.0:  # > 5 minutes spread between devices in same batch
                protocol_limitations.append(
                    f"Mixed timestamp anomaly: batch exhibits a {round(batch_spread, 1)}s timestamp spread between oldest ({oldest.isoformat()}) and newest ({most_recent.isoformat()}) records."
                )

        # 4. Dispatch to specialized agents with canonical AMP/2.0 messaging
        all_findings: List[AgentFinding] = []

        # TelemetryAgent dispatch
        emit_protocol_message(
            sender="Orchestrator",
            recipient="TelemetryAgent",
            message_type=ProtocolMessageType.DISPATCH_TELEMETRY,
            payload={
                "device_count": len(canonical_records),
                "schema_versions": detected_versions,
                "normalization_warnings": total_warnings
            }
        )
        log_trace("DISPATCH_TELEMETRY_AGENT", "Dispatching canonical records to TelemetryAgent.")
        tel_findings = self.telemetry_agent.analyze_batch(canonical_records)
        all_findings.extend(tel_findings)
        tel_anomalous = [f for f in tel_findings if f.overall_severity.value not in ("HEALTHY", "UNKNOWN")]
        tel_ev_ids = [e.evidence_id for f in tel_findings for e in f.evidence]

        emit_protocol_message(
            sender="TelemetryAgent",
            recipient="Orchestrator",
            message_type=ProtocolMessageType.FINDINGS_READY,
            payload={
                "findings_count": len(tel_findings),
                "anomalous_devices": [f.device_id for f in tel_anomalous],
                "issues_detected": [issue for f in tel_anomalous for issue in f.suspected_issues],
                "missing_metrics": {f.device_id: f.missing_metrics for f in tel_findings if f.missing_metrics}
            },
            evidence_ids=tel_ev_ids
        )

        # InfrastructureAgent dispatch
        emit_protocol_message(
            sender="Orchestrator",
            recipient="InfrastructureAgent",
            message_type=ProtocolMessageType.DISPATCH_INFRASTRUCTURE,
            payload={
                "device_count": len(canonical_records),
                "telemetry_anomalies": [f.device_id for f in tel_anomalous]
            }
        )
        log_trace("DISPATCH_INFRASTRUCTURE_AGENT", "Dispatching canonical records to InfrastructureAgent.")
        infra_findings = self.infrastructure_agent.analyze_batch(canonical_records)
        all_findings.extend(infra_findings)
        infra_anomalous = [f for f in infra_findings if f.overall_severity.value not in ("HEALTHY", "UNKNOWN")]
        infra_ev_ids = [e.evidence_id for f in infra_findings for e in f.evidence]

        emit_protocol_message(
            sender="InfrastructureAgent",
            recipient="Orchestrator",
            message_type=ProtocolMessageType.FINDINGS_READY,
            payload={
                "findings_count": len(infra_findings),
                "anomalous_devices": [f.device_id for f in infra_anomalous],
                "issues_detected": [issue for f in infra_anomalous for issue in f.suspected_issues]
            },
            evidence_ids=infra_ev_ids
        )

        # ConnectivityAgent dispatch
        emit_protocol_message(
            sender="Orchestrator",
            recipient="ConnectivityAgent",
            message_type=ProtocolMessageType.DISPATCH_CONNECTIVITY,
            payload={
                "device_count": len(canonical_records),
                "known_anomalous": [f.device_id for f in tel_anomalous + infra_anomalous]
            }
        )
        log_trace("DISPATCH_CONNECTIVITY_AGENT", "Evaluating topology mapping and blast radius.")
        conn_findings = [self.connectivity_agent.analyze(r) for r in canonical_records]
        all_findings.extend(conn_findings)
        cascade_evidence = self.connectivity_agent.analyze_topology_cascade(canonical_records)
        conn_anomalous = [f for f in conn_findings if f.overall_severity.value not in ("HEALTHY", "UNKNOWN")]
        conn_ev_ids = [e.evidence_id for f in conn_findings for e in f.evidence]

        emit_protocol_message(
            sender="ConnectivityAgent",
            recipient="Orchestrator",
            message_type=ProtocolMessageType.FINDINGS_READY,
            payload={
                "findings_count": len(conn_findings),
                "cascade_items": len(cascade_evidence),
                "blast_radius_devices": [f.device_id for f in conn_anomalous]
            },
            evidence_ids=conn_ev_ids
        )

        # Record structured agent findings in central Diagnostic Evidence Ledger
        ledger.record_agent_findings("TelemetryAgent", tel_findings)
        ledger.record_agent_findings("InfrastructureAgent", infra_findings)
        ledger.record_agent_findings("ConnectivityAgent", conn_findings)

        # 5a. Label-vs-Metrics Conflict Negotiation (REQUEST_CLARIFICATION pattern)
        conflicted_devices = []
        for record in canonical_records:
            reported = (record.reported_status or "").upper()
            is_labeled_healthy = reported in ("HEALTHY", "OK", "NORMAL", "UP")
            tel_f = next((f for f in tel_findings if f.device_id == record.device_id), None)
            infra_f = next((f for f in infra_findings if f.device_id == record.device_id), None)
            tel_bad = tel_f and tel_f.overall_severity.value not in ("HEALTHY", "UNKNOWN")
            infra_bad = infra_f and infra_f.overall_severity.value not in ("HEALTHY", "UNKNOWN")
            if is_labeled_healthy and (tel_bad or infra_bad):
                conflicted_devices.append(record.device_id)

        if conflicted_devices:
            for c_dev in conflicted_devices:
                tel_f = next((f for f in tel_findings if f.device_id == c_dev), None)
                infra_f = next((f for f in infra_findings if f.device_id == c_dev), None)
                record = next((r for r in canonical_records if r.device_id == c_dev), None)
                rep_label = record.reported_status if record else "HEALTHY"

                tel_issues = tel_f.suspected_issues if tel_f else []
                infra_issues = infra_f.suspected_issues if infra_f else []
                supporting_ev = [
                    {"metric": e.metric_name, "value": e.observed_value, "desc": e.description}
                    for f in (tel_f, infra_f) if f for e in f.evidence if e.polarity == "SUPPORTS"
                ]

                emit_protocol_message(
                    sender="CorrelationAgent",
                    recipient="TelemetryAgent",
                    message_type=ProtocolMessageType.AGENT_DISAGREEMENT,
                    payload={
                        "disagreement_id": f"DISAGREE-{c_dev}",
                        "device_id": c_dev,
                        "reported_generator_claim": rep_label,
                        "telemetry_agent_findings": tel_issues,
                        "infrastructure_agent_findings": infra_issues,
                        "competing_evidence": supporting_ev[:4],
                        "resolution_strategy": "DETERMINISTIC_METRIC_SUPREMACY",
                        "resolution_rule": "Physical telemetry signals override untrusted status labels",
                        "status": "OPEN"
                    }
                )

            emit_protocol_message(
                sender="CorrelationAgent",
                recipient="TelemetryAgent",
                message_type=ProtocolMessageType.REQUEST_CLARIFICATION,
                payload={
                    "reason": "Status label contradicts empirical metric observations",
                    "devices": conflicted_devices,
                    "action": "Empirical metrics override label — untrusted label reconciliation active"
                }
            )
            emit_protocol_message(
                sender="TelemetryAgent",
                recipient="CorrelationAgent",
                message_type=ProtocolMessageType.CLARIFICATION_RESPONSE,
                payload={
                    "devices": conflicted_devices,
                    "resolution": "Label overridden by metric evidence",
                    "override_justification": "Observed metrics contradict reported status; deterministic rules take precedence",
                    "status": "RESOLVED"
                }
            )
            log_trace(
                "LABEL_CONFLICT_NEGOTIATION",
                f"CorrelationAgent↔TelemetryAgent negotiation completed for {len(conflicted_devices)} device(s).",
                {"conflicted": conflicted_devices}
            )

        # 5b. Multi-Agent Peer Review Round
        log_trace("PEER_REVIEW", "Conducting cross-agent peer review round.")
        peer_dossier = self.peer_review_manager.conduct_peer_review(
            incident_id=inc_id,
            telemetry_records=canonical_records,
            agent_findings=all_findings
        )
        for chal in peer_dossier.challenges:
            emit_protocol_message(
                sender=chal.challenger_agent,
                recipient=chal.target_agent,
                message_type=ProtocolMessageType.CHALLENGE,
                payload={
                    "challenge_id": chal.challenge_id,
                    "target_device": chal.target_device,
                    "target_hypothesis": chal.target_hypothesis,
                    "reason": chal.challenge_reason
                },
                evidence_ids=chal.evidence_ids
            )
        for resp in peer_dossier.responses:
            emit_protocol_message(
                sender=resp.responding_agent,
                recipient=resp.target_agent,
                message_type=ProtocolMessageType.RESPONSE,
                payload={
                    "challenge_id": resp.challenge_id,
                    "target_device": resp.target_device,
                    "verdict": resp.verdict,
                    "rebuttal_reason": resp.rebuttal_reason,
                    "defense_evidence": [e.description for e in resp.defense_evidence] if resp.defense_evidence else []
                },
                evidence_ids=resp.evidence_ids
            )
        for corr in peer_dossier.corroborations:
            emit_protocol_message(
                sender=corr.corroborating_agent,
                recipient="ArbiterAgent",
                message_type=ProtocolMessageType.CORROBORATION,
                payload={
                    "corroboration_id": corr.corroboration_id,
                    "supported_hypothesis": corr.supported_hypothesis,
                    "target_device": corr.target_device,
                    "explanation": corr.explanation
                },
                evidence_ids=corr.evidence_ids
            )

        # 5c. Correlation & Dedicated Arbiter Adjudication
        emit_protocol_message(
            sender="Orchestrator",
            recipient="ArbiterAgent",
            message_type=ProtocolMessageType.ARBITRATE_REQUEST,
            payload={
                "total_findings": len(all_findings),
                "staleness_s": staleness_seconds,
                "label_conflicts_resolved": len(conflicted_devices),
                "peer_challenges_count": len(peer_dossier.challenges),
                "peer_corroborations_count": len(peer_dossier.corroborations),
                "temporal_events_count": len(temporal_events)
            }
        )
        log_trace("ARBITRATION", "Invoking ArbiterAgent for multi-agent evidence synthesis, peer review adjudication, and isotonic calibration.")
        arbiter_decision = self.arbiter_agent.arbitrate(
            telemetry_records=canonical_records,
            agent_findings=all_findings,
            cascade_evidence=cascade_evidence,
            staleness_seconds=staleness_seconds,
            dossier=peer_dossier,
            incident_id=inc_id,
            temporal_events=temporal_events,
            reference_time=now
        )
        arbitration = arbiter_decision.to_arbitration_result()
        emit_protocol_message(
            sender="ArbiterAgent",
            recipient="Orchestrator",
            message_type=ProtocolMessageType.ARBITRATION_COMPLETE,
            payload={
                "decision_id": arbiter_decision.decision_id,
                "root_cause": arbitration.primary_root_cause,
                "confidence": arbitration.confidence,
                "affected_count": len(arbitration.affected_devices),
                "accepted_rationale": arbiter_decision.accepted_rationale
            },
            confidence=arbitration.confidence
        )

        # 6. Active Investigation & Multi-Signal Hypothesis Evaluation
        log_trace("ACTIVE_INVESTIGATION", "Generating ranked diagnostic follow-up checks and safe remediation plan.")
        investigation_plan = InvestigationEngine.generate_investigation_plan(
            root_cause=arbitration.primary_root_cause,
            competing_hypotheses=arbitration.alternative_hypotheses,
            affected_devices=arbitration.affected_devices
        )
        safe_actions = InvestigationEngine.generate_safe_remediation_actions(
            root_cause=arbitration.primary_root_cause,
            affected_devices=arbitration.affected_devices
        )
        hypothesis_evaluations = HypothesisEngine.evaluate_hypotheses(
            telemetry_records=canonical_records,
            completeness=arbitration.evidence_completeness
        )

        # 7. Report Generation
        log_trace("REPORTING", "Generating UnifiedIncidentReport and Executive Markdown Summary.")
        report = self.reporter_agent.generate_json_report(
            arbitration,
            incident_id=inc_id,
            telemetry_mode=telemetry_mode,
            reference_time=now.isoformat(),
            staleness_seconds=staleness_seconds,
            freshness_status=freshness_status
        )
        if protocol_limitations:
            report.limitations.extend(protocol_limitations)
        md_summary = self.reporter_agent.generate_markdown_summary(
            report,
            evidence_completeness=arbitration.evidence_completeness
        )

        end_time = datetime.now(timezone.utc)
        duration_ms = round((end_time - start_time).total_seconds() * 1000.0, 2)
        log_trace("COMPLETE", f"Orchestration completed in {duration_ms}ms.", {"incident_id": report.incident_id})

        res = OrchestrationResult(
            report=report,
            markdown_summary=md_summary,
            canonical_telemetry=canonical_records,
            agent_findings=all_findings,
            agent_messages=messages,
            arbitration_result=arbitration,
            execution_trace=trace,
            total_duration_ms=duration_ms,
            interoperability_report=interop_report,
            investigation_plan=investigation_plan,
            safe_remediation_actions=safe_actions,
            hypothesis_evaluations=hypothesis_evaluations,
            evidence_ledger_summary=ledger.get_ledger_summary(),
            peer_review_dossier=peer_dossier,
            arbiter_decision=arbiter_decision,
            protocol_audit_trail=self.message_bus.get_audit_trail(incident_id=inc_id),
            temporal_events=temporal_events,
            evidence_graph=None
        )
        res.evidence_graph = EvidenceGraph.build_from_orchestration_result(res)
        return res
