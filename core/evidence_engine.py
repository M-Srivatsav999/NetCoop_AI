"""Deterministic Evidence Aggregation and Conflict Resolution Engine.

Reconciles untrusted generator-provided labels, cross-correlates multi-agent telemetry findings,
and evaluates supporting vs contradictory evidence for all candidate hypotheses.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from protocol.models import (
    AgentFinding,
    CanonicalTelemetry,
    EvidenceItem,
    EvidencePolarity,
    HypothesisType,
    SeverityLevel,
)


class EvidenceEngine:
    """Aggregates atomic evidence items, enforces conflict-resolution rules,

    and computes net evidentiary support for diagnostic hypotheses using configurable
    heuristic multi-tier de-biasing weights.
    """

    def __init__(
        self,
        copycat_discount_factor: float = 0.10,
        same_sensor_discount_factor: float = 0.50,
        cascade_discount_factor: float = 0.25,
        contradiction_penalty_factor: float = 1.20
    ) -> None:
        self.all_evidence: List[EvidenceItem] = []
        # Configurable heuristic de-biasing multipliers (Page 2-3 of audit specifications):
        self.copycat_discount_factor = copycat_discount_factor
        self.same_sensor_discount_factor = same_sensor_discount_factor
        self.cascade_discount_factor = cascade_discount_factor
        self.contradiction_penalty_factor = contradiction_penalty_factor

    def clear(self) -> None:
        self.all_evidence.clear()

    def add_evidence(self, items: List[EvidenceItem]) -> None:
        self.all_evidence.extend(items)

    def reconcile_untrusted_labels(
        self,
        telemetry_records: List[CanonicalTelemetry]
    ) -> List[EvidenceItem]:
        """Verify generator-provided status labels against actual computed metrics.
        
        Generates contradiction or validation evidence items.
        """
        reconciliation_evidence: List[EvidenceItem] = []

        for record in telemetry_records:
            if not record.reported_status:
                continue

            status = record.reported_status.upper()
            m = record.metrics
            
            # Check for false HEALTHY: reported HEALTHY but severe anomalies present
            severe_indicators = []
            if m.packet_loss_pct is not None and m.packet_loss_pct > 5.0:
                severe_indicators.append(f"packet loss of {m.packet_loss_pct}%")
            if m.interface_errors is not None and m.interface_errors > 10:
                severe_indicators.append(f"{m.interface_errors} interface errors")
            if m.latency_ms is not None and m.latency_ms > 100.0:
                severe_indicators.append(f"high latency of {m.latency_ms}ms")
            if m.cpu_pct is not None and m.cpu_pct > 90.0:
                severe_indicators.append(f"CPU at {m.cpu_pct}%")
            if m.queue_drops is not None and m.queue_drops > 50:
                severe_indicators.append(f"{m.queue_drops} queue drops")

            if status in ("HEALTHY", "OK", "NORMAL") and severe_indicators:
                ev = EvidenceItem(
                    evidence_id=f"LABEL-CONFLICT-{record.device_id}",
                    source_agent="EvidenceEngine",
                    device_id=record.device_id,
                    metric_name="reported_status",
                    observed_value=record.reported_status,
                    threshold_reference="Nominal operating envelope",
                    severity=SeverityLevel.CRITICAL,
                    polarity=EvidencePolarity.CONTRADICTS,
                    hypothesis_target=HypothesisType.NORMAL_OPERATION.value,
                    weight=0.95,
                    description=(
                        f"Untrusted generator label '{record.reported_status}' contradicted by "
                        f"observed telemetry: {', '.join(severe_indicators)} on {record.device_id}."
                    )
                )
                reconciliation_evidence.append(ev)

            # Check for false CRITICAL: reported CRITICAL/ERROR but all metrics nominal
            if status in ("CRITICAL", "ERROR", "DOWN"):
                has_any_severe = bool(severe_indicators)
                is_all_nominal = (
                    (m.packet_loss_pct is None or m.packet_loss_pct == 0.0) and
                    (m.interface_errors is None or m.interface_errors == 0) and
                    (m.latency_ms is None or m.latency_ms < 35.0) and
                    (m.cpu_pct is None or m.cpu_pct < 70.0)
                )
                if is_all_nominal and not has_any_severe:
                    ev = EvidenceItem(
                        evidence_id=f"LABEL-FALSE-ALARM-{record.device_id}",
                        source_agent="EvidenceEngine",
                        device_id=record.device_id,
                        metric_name="reported_status",
                        observed_value=record.reported_status,
                        threshold_reference="Nominal operating envelope",
                        severity=SeverityLevel.WARNING,
                        polarity=EvidencePolarity.CONTRADICTS,
                        hypothesis_target=HypothesisType.HARDWARE_FAILURE.value,
                        weight=0.8,
                        description=(
                            f"Untrusted generator label '{record.reported_status}' dismissed as false alarm; "
                            f"all physical and network metrics on {record.device_id} are nominal."
                        )
                    )
                    reconciliation_evidence.append(ev)

        return reconciliation_evidence

    def apply_conflict_resolution_rules(
        self,
        telemetry_records: List[CanonicalTelemetry]
    ) -> List[EvidenceItem]:
        """Apply deterministic cross-metric conflict resolution logic.
        
        Rules:
          1. Extreme latency + packet loss + low interface errors -> Congestion SUPPORTS, Hardware CONTRADICTS.
          2. High interface errors + packet loss -> Hardware SUPPORTS, Congestion CONTRADICTS.
          3. High CPU/Memory + drops -> Resource Exhaustion SUPPORTS.
          4. Poor signal strength + loss isolated to Wi-Fi -> Weak Wi-Fi SUPPORTS, Switch Failure CONTRADICTS.
          5. High DNS latency / DHCP failure + nominal link -> DNS/DHCP Failure SUPPORTS.
        """
        resolution_evidence: List[EvidenceItem] = []

        for record in telemetry_records:
            m = record.metrics
            dev = record.device_id

            # Rule 1 & 2: Congestion vs Hardware Physical Link Failure
            if m.packet_loss_pct is not None and m.packet_loss_pct > 1.0:
                has_interface_errors = (m.interface_errors is not None and m.interface_errors > 10)
                has_clean_interfaces = (m.interface_errors is not None and m.interface_errors == 0)

                if has_interface_errors:
                    # Physical layer issue dominates
                    resolution_evidence.append(EvidenceItem(
                        evidence_id=f"RESOLVE-HW-{dev}",
                        source_agent="EvidenceEngine",
                        device_id=dev,
                        metric_name="interface_errors_and_loss",
                        observed_value={"errors": m.interface_errors, "loss_pct": m.packet_loss_pct},
                        threshold_reference="errors > 10 with loss",
                        severity=SeverityLevel.CRITICAL,
                        polarity=EvidencePolarity.SUPPORTS,
                        hypothesis_target=HypothesisType.HARDWARE_FAILURE.value,
                        weight=0.9,
                        description=(
                            f"High physical interface errors ({m.interface_errors}) correlated with packet loss "
                            f"({m.packet_loss_pct}%) indicates physical layer / transceiver degradation."
                        )
                    ))
                    # Contradicts pure congestion
                    resolution_evidence.append(EvidenceItem(
                        evidence_id=f"CONTRADICT-CONGEST-{dev}",
                        source_agent="EvidenceEngine",
                        device_id=dev,
                        metric_name="interface_errors",
                        observed_value=m.interface_errors,
                        threshold_reference="errors > 0 contradicts congestion",
                        severity=SeverityLevel.WARNING,
                        polarity=EvidencePolarity.CONTRADICTS,
                        hypothesis_target=HypothesisType.LINK_CONGESTION.value,
                        weight=0.85,
                        description=(
                            f"Link congestion hypothesis contradicted by {m.interface_errors} physical layer "
                            f"CRC/FCS interface errors on {dev}."
                        )
                    ))

                    # If severe queue drops co-occur, buffer congestion is also present, contradicting pure hardware failure
                    if m.queue_drops is not None and m.queue_drops > 20:
                        resolution_evidence.append(EvidenceItem(
                            evidence_id=f"CONTRADICT-PURE-HW-{dev}",
                            source_agent="EvidenceEngine",
                            device_id=dev,
                            metric_name="queue_drops",
                            observed_value=m.queue_drops,
                            threshold_reference="queue_drops > 20 indicates concurrent buffer congestion",
                            severity=SeverityLevel.WARNING,
                            polarity=EvidencePolarity.CONTRADICTS,
                            hypothesis_target=HypothesisType.HARDWARE_FAILURE.value,
                            weight=0.85,
                            description=(
                                f"Hardware physical failure certainty reduced by concurrent severe queue drops "
                                f"({m.queue_drops}) on {dev}, indicating active buffer congestion."
                            )
                        ))
                        resolution_evidence.append(EvidenceItem(
                            evidence_id=f"COMPETE-CONGEST-{dev}",
                            source_agent="EvidenceEngine",
                            device_id=dev,
                            metric_name="queue_drops",
                            observed_value=m.queue_drops,
                            threshold_reference="queue_drops > 20",
                            severity=SeverityLevel.CRITICAL,
                            polarity=EvidencePolarity.SUPPORTS,
                            hypothesis_target=HypothesisType.LINK_CONGESTION.value,
                            weight=0.90,
                            description=f"Severe queue drops ({m.queue_drops}) confirm active buffer overflow / congestion."
                        ))
                elif has_clean_interfaces:
                    # Distinguish total link cut / upstream switch down from buffer queue congestion
                    rep_stat = getattr(record, "reported_status", "") or ""
                    is_total_outage = (m.packet_loss_pct is not None and m.packet_loss_pct >= 95.0) or (rep_stat == "DOWN")

                    if is_total_outage:
                        resolution_evidence.append(EvidenceItem(
                            evidence_id=f"RESOLVE-UPSTREAM-{dev}",
                            source_agent="EvidenceEngine",
                            device_id=dev,
                            metric_name="total_network_outage",
                            observed_value={"loss": m.packet_loss_pct, "status": rep_stat},
                            threshold_reference="packet_loss >= 95% or status DOWN",
                            severity=SeverityLevel.CRITICAL,
                            polarity=EvidencePolarity.SUPPORTS,
                            hypothesis_target=HypothesisType.UPSTREAM_SWITCH_FAILURE.value,
                            weight=0.95,
                            description=f"Total link cut or node outage on {dev} (loss {m.packet_loss_pct}%, status {rep_stat}) indicates upstream switch or physical link failure."
                        ))
                        resolution_evidence.append(EvidenceItem(
                            evidence_id=f"CONTRADICT-CONGEST-OUTAGE-{dev}",
                            source_agent="EvidenceEngine",
                            device_id=dev,
                            metric_name="total_outage",
                            observed_value=m.packet_loss_pct,
                            threshold_reference=">= 95% loss contradicts mere queue congestion",
                            severity=SeverityLevel.CRITICAL,
                            polarity=EvidencePolarity.CONTRADICTS,
                            hypothesis_target=HypothesisType.LINK_CONGESTION.value,
                            weight=0.90,
                            description=f"Link congestion hypothesis contradicted by total node outage / link cut on {dev}."
                        ))
                    else:
                        # Zero interface errors + high latency/loss indicates bufferbloat / queue congestion,
                        # UNLESS device has severe Wi-Fi RF attenuation which explains the latency/loss.
                        is_weak_wifi = (m.signal_strength_dbm is not None and m.signal_strength_dbm <= -75.0)
                        if not is_weak_wifi:
                            if (m.latency_ms is not None and m.latency_ms > 40.0) or (m.queue_drops is not None and m.queue_drops > 0):
                                resolution_evidence.append(EvidenceItem(
                                    evidence_id=f"RESOLVE-CONGEST-{dev}",
                                    source_agent="EvidenceEngine",
                                    device_id=dev,
                                    metric_name="clean_interfaces_high_latency",
                                    observed_value={"latency": m.latency_ms, "queue_drops": m.queue_drops},
                                    threshold_reference="zero errors with latency/drops",
                                    severity=SeverityLevel.CRITICAL,
                                    polarity=EvidencePolarity.SUPPORTS,
                                    hypothesis_target=HypothesisType.LINK_CONGESTION.value,
                                    weight=0.9,
                                    description=(
                                        f"Zero interface errors with elevated latency ({m.latency_ms}ms) and queue drops "
                                        f"({m.queue_drops or 0}) confirms buffer congestion rather than physical cable damage."
                                    )
                                ))
                                resolution_evidence.append(EvidenceItem(
                                    evidence_id=f"CONTRADICT-HW-{dev}",
                                    source_agent="EvidenceEngine",
                                    device_id=dev,
                                    metric_name="interface_errors",
                                    observed_value=0,
                                    threshold_reference="0 interface errors",
                                    severity=SeverityLevel.WARNING,
                                    polarity=EvidencePolarity.CONTRADICTS,
                                    hypothesis_target=HypothesisType.HARDWARE_FAILURE.value,
                                    weight=0.8,
                                    description=(
                                        f"Hardware physical failure contradicted by zero recorded interface errors on {dev}."
                                    )
                                ))

            # Rule 3: Resource Exhaustion
            if (m.cpu_pct is not None and m.cpu_pct >= 85.0) or (m.memory_pct is not None and m.memory_pct >= 90.0):
                resolution_evidence.append(EvidenceItem(
                    evidence_id=f"RESOLVE-SATURATION-{dev}",
                    source_agent="EvidenceEngine",
                    device_id=dev,
                    metric_name="cpu_or_memory",
                    observed_value={"cpu": m.cpu_pct, "mem": m.memory_pct},
                    threshold_reference="cpu >= 85% or mem >= 90%",
                    severity=SeverityLevel.CRITICAL,
                    polarity=EvidencePolarity.SUPPORTS,
                    hypothesis_target=HypothesisType.RESOURCE_EXHAUSTION.value,
                    weight=0.95,
                    description=(
                        f"System resource saturation on {dev}: CPU {m.cpu_pct}%, Memory {m.memory_pct}%."
                    )
                ))

            # Rule 4: Weak Wi-Fi Signal
            if m.signal_strength_dbm is not None and m.signal_strength_dbm <= -72.0:
                resolution_evidence.append(EvidenceItem(
                    evidence_id=f"RESOLVE-WIFI-{dev}",
                    source_agent="EvidenceEngine",
                    device_id=dev,
                    metric_name="signal_strength_dbm",
                    observed_value=m.signal_strength_dbm,
                    threshold_reference="<= -75 dBm",
                    severity=SeverityLevel.CRITICAL,
                    polarity=EvidencePolarity.SUPPORTS,
                    hypothesis_target=HypothesisType.WEAK_WIFI.value,
                    weight=0.95,
                    description=(
                        f"Degraded RF signal strength ({m.signal_strength_dbm} dBm) on {dev} indicates "
                        f"free-space path loss or co-channel interference."
                    )
                ))
                # Wi-Fi attenuation causes transport frame loss and latency, which contradicts pure wired link congestion
                resolution_evidence.append(EvidenceItem(
                    evidence_id=f"CONTRADICT-CONGEST-WIFI-{dev}",
                    source_agent="EvidenceEngine",
                    device_id=dev,
                    metric_name="signal_strength_dbm",
                    observed_value=m.signal_strength_dbm,
                    threshold_reference="signal <= -75 dBm contradicts wired congestion",
                    severity=SeverityLevel.WARNING,
                    polarity=EvidencePolarity.CONTRADICTS,
                    hypothesis_target=HypothesisType.LINK_CONGESTION.value,
                    weight=0.90,
                    description=(
                        f"Packet loss and latency on {dev} is driven by RF signal degradation "
                        f"({m.signal_strength_dbm} dBm), contradicting wired link congestion."
                    )
                ))

            # Rule 5: DNS/DHCP Services
            dns_failed = (m.dns_resolution_ms is not None and m.dns_resolution_ms >= 500.0)
            dhcp_failed = (m.dhcp_lease_success is False)
            if dns_failed or dhcp_failed:
                resolution_evidence.append(EvidenceItem(
                    evidence_id=f"RESOLVE-SERVICES-{dev}",
                    source_agent="EvidenceEngine",
                    device_id=dev,
                    metric_name="dns_or_dhcp",
                    observed_value={"dns_ms": m.dns_resolution_ms, "dhcp_success": m.dhcp_lease_success},
                    threshold_reference="dns >= 500ms or dhcp == False",
                    severity=SeverityLevel.CRITICAL,
                    polarity=EvidencePolarity.SUPPORTS,
                    hypothesis_target=HypothesisType.DNS_DHCP_FAILURE.value,
                    weight=0.95,
                    description=(
                        f"Core network services outage on {dev}: DNS resolution {m.dns_resolution_ms}ms, "
                        f"DHCP lease success {m.dhcp_lease_success}."
                    )
                ))
                # If physical link is clean, DNS failure contradicts Link Congestion
                if m.packet_loss_pct is not None and m.packet_loss_pct == 0.0:
                    resolution_evidence.append(EvidenceItem(
                        evidence_id=f"CONTRADICT-CONGEST-DNS-{dev}",
                        source_agent="EvidenceEngine",
                        device_id=dev,
                        metric_name="packet_loss_pct",
                        observed_value=0.0,
                        threshold_reference="0.0% loss",
                        severity=SeverityLevel.INFO,
                        polarity=EvidencePolarity.CONTRADICTS,
                        hypothesis_target=HypothesisType.LINK_CONGESTION.value,
                        weight=0.8,
                        description="Zero packet loss contradicts link congestion; fault is localized to application service."
                    ))

        return resolution_evidence

    def evaluate_hypotheses(self) -> Dict[str, Dict[str, Any]]:
        """Score each hypothesis target across supporting and contradictory evidence."""
        scores: Dict[str, Dict[str, Any]] = {}
        all_targets = [h.value for h in HypothesisType]

        for target in all_targets:
            supporting: List[EvidenceItem] = []
            contradicting: List[EvidenceItem] = []
            distinct_agents: Set[str] = set()
            affected_devices: Set[str] = set()

            for item in self.all_evidence:
                if item.hypothesis_target == target:
                    if item.polarity == EvidencePolarity.SUPPORTS:
                        supporting.append(item)
                        distinct_agents.add(item.source_agent)
                        affected_devices.add(item.device_id)
                    elif item.polarity == EvidencePolarity.CONTRADICTS:
                        contradicting.append(item)

            # Multi-Tier Scientific Evidence Lineage & De-Biasing Model:
            # 1. Distinguish copycat identical datum repetition (90% discount)
            # 2. Distinguish physically correlated symptoms from the same sensor (50% diminishing return)
            # 3. Distinguish downstream cascading symptoms sharing an upstream root dependency (75% cascade discount)
            # 4. Grant full corroborative credit to independent devices and distinct physical sensors

            # Step A: Group by upstream dependency to prevent cascade inflation
            upstream_groups: Dict[str, List[EvidenceItem]] = {}
            for item in supporting:
                dep_key = item.upstream_dependency_id or item.shared_dependency or f"INDEPENDENT:{item.device_id}"
                upstream_groups.setdefault(dep_key, []).append(item)

            support_weight = 0.0
            total_independent_groups = 0

            for dep_key, dep_items in upstream_groups.items():
                # Step B: Within each dependency domain, cluster by physical sensor / device metric
                sensor_clusters: Dict[str, List[EvidenceItem]] = {}
                for it in dep_items:
                    # Sensor key incorporates physical source or device metric
                    sensor_key = it.physical_source_id or f"{it.device_id}:{it.metric_name}"
                    sensor_clusters.setdefault(sensor_key, []).append(it)

                total_independent_groups += len(sensor_clusters)
                dep_weight = 0.0

                for s_key, s_items in sensor_clusters.items():
                    # Step C: Cluster by exact telemetry datum (copycat repetition)
                    datum_clusters: Dict[str, List[EvidenceItem]] = {}
                    for it in s_items:
                        datum_key = it.independence_group or f"{it.device_id}:{it.metric_name}:{it.telemetry_source_id or 'src'}"
                        datum_clusters.setdefault(datum_key, []).append(it)

                    sensor_datum_weight = 0.0
                    for d_key, d_items in datum_clusters.items():
                        max_d_w = max(it.weight for it in d_items)
                        # Case 1: Exact copycat repetitions discounted by heuristic copycat factor (default 90% discount)
                        redundant_copycats = sum(it.weight for it in d_items) - max_d_w
                        sensor_datum_weight += max_d_w + (self.copycat_discount_factor * redundant_copycats)

                    # Case 2: Physically correlated symptoms from the exact same physical sensor (default 50% diminishing return)
                    # When multiple distinct datums/metrics arise from the same physical sensor, primary symptom takes lead
                    if len(datum_clusters) > 1:
                        primary_weight = max(max(it.weight for it in d_items) for d_items in datum_clusters.values())
                        secondary_weight = sensor_datum_weight - primary_weight
                        sensor_weight = primary_weight + (self.same_sensor_discount_factor * secondary_weight)
                    else:
                        sensor_weight = sensor_datum_weight

                    dep_weight += sensor_weight

                # Case 3: If multiple downstream items share an upstream dependency, apply cascade diminishing returns
                if dep_key.startswith("INDEPENDENT:"):
                    support_weight += dep_weight
                else:
                    # Upstream bottleneck: first downstream indicator contributes full weight, subsequent share cascade factor (default 25%)
                    max_dep = max(it.weight for it in dep_items)
                    rem_dep = dep_weight - max_dep
                    support_weight += max_dep + (self.cascade_discount_factor * rem_dep)

            # Contradicting evidence evaluated with identical anti-copycat clustering
            contra_by_group: Dict[str, List[EvidenceItem]] = {}
            for item in contradicting:
                group_key = item.independence_group or f"{item.device_id}:{item.metric_name}:{item.telemetry_source_id or 'src'}"
                contra_by_group.setdefault(group_key, []).append(item)

            contra_weight = 0.0
            for group_key, group_items in contra_by_group.items():
                max_w = max(it.weight for it in group_items)
                redundant_w = sum(it.weight for it in group_items) - max_w
                contra_weight += max_w + (self.copycat_discount_factor * redundant_w)

            net_score = max(0.0, support_weight - (self.contradiction_penalty_factor * contra_weight))

            scores[target] = {
                "hypothesis": target,
                "support_weight": round(support_weight, 3),
                "raw_support_weight": round(sum(item.weight for item in supporting), 3),
                "contra_weight": round(contra_weight, 3),
                "net_score": round(net_score, 3),
                "supporting_count": len(supporting),
                "independent_groups_count": total_independent_groups,
                "contradicting_count": len(contradicting),
                "supporting_agents": list(distinct_agents),
                "affected_devices": list(affected_devices),
                "supporting_items": supporting,
                "contradicting_items": contradicting,
            }

        return scores
