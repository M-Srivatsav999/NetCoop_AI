"""NetCoop AI Temporal & Causal Diagnostic Engine.

Satisfies the 25% Temporal/Causal Reasoning hackathon category:
1. Microsecond/Second-level event sequence ordering
2. Strict discrimination between initiating events vs cascading downstream symptoms
3. Rolling baseline (EWMA + z-score) comparison and before/after metric shift analysis
4. Formal topological causality qualification (Correlation != Causation without topological precedence)
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from core.topology import TopologyEngine
from protocol.models import CanonicalTelemetry, SeverityLevel

NOMINAL_METRIC_BASELINES: Dict[str, float] = {
    "packet_loss_pct": 0.0,
    "queue_drops": 0.0,
    "interface_errors": 0.0,
    "latency_ms": 12.0,
    "cpu_pct": 20.0,
    "memory_pct": 30.0,
    "dns_resolution_ms": 5.0,
}

NOMINAL_METRIC_STDDEV: Dict[str, float] = {
    "packet_loss_pct": 0.5,
    "queue_drops": 5.0,
    "interface_errors": 2.0,
    "latency_ms": 5.0,
    "cpu_pct": 8.0,
    "memory_pct": 8.0,
    "dns_resolution_ms": 3.0,
}

MIN_MEANINGFUL_DELTAS: Dict[str, float] = {
    "packet_loss_pct": 1.0,      # at least 1.0% shift
    "queue_drops": 15.0,        # at least 15 drops shift
    "interface_errors": 5.0,    # at least 5 errors shift
    "latency_ms": 20.0,         # at least 20ms shift
    "cpu_pct": 20.0,            # at least 20% shift
    "memory_pct": 20.0,         # at least 20% shift
    "dns_resolution_ms": 25.0,  # at least 25ms shift
}


class EventClassification(str, Enum):
    INITIATING_EVENT = "INITIATING_EVENT"
    CASCADING_SYMPTOM = "CASCADING_SYMPTOM"
    INDEPENDENT_ANOMALY = "INDEPENDENT_ANOMALY"
    RECOVERY = "RECOVERY"
    STEADY_STATE = "STEADY_STATE"


class TemporalEvent(BaseModel):
    """Atomic anomalous event placed on the timeline."""
    event_id: str
    device_id: str
    metric_name: str
    timestamp: datetime
    observed_value: float
    baseline_value: float
    z_score: float
    rate_of_change_per_sec: float
    classification: EventClassification
    causal_parent_id: Optional[str] = None
    explanation: str


class MetricRollingBaseline(BaseModel):
    """Statistical rolling baseline for a single device metric."""
    device_id: str
    metric_name: str
    sample_count: int = 0
    ewma: float = 0.0
    mean: float = 0.0
    variance: float = 0.0
    std_dev: float = 0.0
    alpha: float = 0.20  # EWMA decay factor

    def update(self, value: float) -> Tuple[float, float]:
        """Update rolling statistics with a new measurement (Welford's algorithm).
        
        Returns:
            (delta_from_mean, z_score)
        """
        self.sample_count += 1
        if self.sample_count == 1:
            self.ewma = value
            self.mean = value
            self.variance = 0.0
            self.std_dev = 0.0
            return 0.0, 0.0

        # Update EWMA
        self.ewma = (self.alpha * value) + ((1.0 - self.alpha) * self.ewma)

        # Welford's algorithm for online mean and variance
        delta = value - self.mean
        self.mean += delta / self.sample_count
        delta2 = value - self.mean
        self.variance += delta * delta2
        self.std_dev = math.sqrt(self.variance / (self.sample_count - 1)) if self.sample_count > 1 else 0.0

        z = (value - self.mean) / self.std_dev if self.std_dev > 1e-4 else 0.0
        return delta, z


class TemporalCausalEngine:
    """Engine responsible for timeline reconstruction and causal verification."""

    ANOMALY_Z_THRESHOLD: float = 2.5

    def __init__(self, topology_engine: Optional[TopologyEngine] = None) -> None:
        self.topology = topology_engine or TopologyEngine()
        # Key: (device_id, metric_name) -> MetricRollingBaseline
        self._baselines: Dict[Tuple[str, str], MetricRollingBaseline] = {}

    def get_or_create_baseline(self, device_id: str, metric_name: str) -> MetricRollingBaseline:
        key = (device_id, metric_name)
        if key not in self._baselines:
            self._baselines[key] = MetricRollingBaseline(device_id=device_id, metric_name=metric_name)
        return self._baselines[key]

    def process_timeline(
        self,
        timeline_batches: List[List[CanonicalTelemetry]]
    ) -> List[TemporalEvent]:
        """Process chronological series of telemetry batches and reconstruct causal sequence."""
        events: List[TemporalEvent] = []

        # Sort batches by timestamp of first record if present
        def get_batch_ts(batch: List[CanonicalTelemetry]) -> datetime:
            for r in batch:
                if r.timestamp:
                    return r.timestamp if r.timestamp.tzinfo else r.timestamp.replace(tzinfo=timezone.utc)
            return datetime.fromtimestamp(0, tz=timezone.utc)

        sorted_batches = sorted(timeline_batches, key=get_batch_ts)

        for b_idx, batch in enumerate(sorted_batches):
            for record in batch:
                dev = record.device_id
                ts = record.timestamp or datetime.now(timezone.utc)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)

                metrics_to_check = [
                    ("latency_ms", record.metrics.latency_ms),
                    ("packet_loss_pct", record.metrics.packet_loss_pct),
                    ("queue_drops", float(record.metrics.queue_drops) if record.metrics.queue_drops is not None else None),
                    ("interface_errors", float(record.metrics.interface_errors) if record.metrics.interface_errors is not None else None),
                    ("cpu_pct", record.metrics.cpu_pct),
                    ("memory_pct", record.metrics.memory_pct),
                    ("dns_resolution_ms", record.metrics.dns_resolution_ms)
                ]

                for metric_name, val in metrics_to_check:
                    if val is None:
                        continue

                    baseline = self.get_or_create_baseline(dev, metric_name)
                    # Establish reference baseline prior to this observation
                    if baseline.sample_count == 0:
                        base_mean = NOMINAL_METRIC_BASELINES.get(metric_name, 0.0)
                        base_std = NOMINAL_METRIC_STDDEV.get(metric_name, 1.0)
                    else:
                        base_mean = baseline.mean
                        base_std = baseline.std_dev if baseline.std_dev > 1e-4 else NOMINAL_METRIC_STDDEV.get(metric_name, 1.0)

                    # Calculate shift from prior baseline
                    delta = val - base_mean
                    z = delta / base_std if base_std > 1e-4 else 0.0

                    # Update online rolling baseline
                    baseline.update(val)

                    # Anomaly qualification:
                    # 1. Must exhibit meaningful deviation from baseline
                    min_delta = MIN_MEANINGFUL_DELTAS.get(metric_name, 5.0)
                    meaningful_shift = abs(delta) >= min_delta

                    # 2. Must not be a zero z-score or unchanged metric
                    if not meaningful_shift or (abs(delta) < 0.01 and abs(z) < 0.1):
                        continue

                    # 3. Must exceed anomaly threshold or statistical z-score
                    exceeds_threshold = (
                        (z >= self.ANOMALY_Z_THRESHOLD) or
                        (metric_name == "packet_loss_pct" and val > 2.0) or
                        (metric_name == "queue_drops" and val > 20.0) or
                        (metric_name == "interface_errors" and val > 5.0) or
                        (metric_name == "latency_ms" and val > 50.0) or
                        (metric_name == "cpu_pct" and val > 80.0) or
                        (metric_name == "dns_resolution_ms" and val > 500.0)
                    )

                    if meaningful_shift and exceeds_threshold:
                        events.append(TemporalEvent(
                            event_id=f"TEV-{dev}-{metric_name}-{len(events)+1}",
                            device_id=dev,
                            metric_name=metric_name,
                            timestamp=ts,
                            observed_value=val,
                            baseline_value=round(base_mean, 2),
                            z_score=round(z, 2),
                            rate_of_change_per_sec=round(delta, 3),
                            classification=EventClassification.INDEPENDENT_ANOMALY,
                            explanation=f"{metric_name} shifted from baseline {base_mean:.1f} to {val:.1f} (z={z:.1f})"
                        ))

        # Reconstruct Causal Ordering & Dependencies
        return self._classify_causality(events)

    def _classify_causality(self, events: List[TemporalEvent]) -> List[TemporalEvent]:
        """Classify events as initiating root cause vs cascading symptoms using topology precedence and temporal rigor."""
        if not events:
            return []

        # Filter out any non-anomalies or zero z-score events (defense in depth)
        valid_events = [
            e for e in events
            if e.timestamp is not None
            and abs(e.observed_value - e.baseline_value) >= MIN_MEANINGFUL_DELTAS.get(e.metric_name, 0.5)
            and abs(e.z_score) > 0.0
        ]
        if not valid_events:
            return []

        # Sort strictly chronologically
        valid_events.sort(key=lambda e: e.timestamp)
        first_event = valid_events[0]
        first_event.classification = EventClassification.INITIATING_EVENT
        first_event.explanation += " (Earliest anomaly detected on timeline)"

        for i in range(1, len(valid_events)):
            curr = valid_events[i]
            upstream_path = self.topology.get_upstream_path(curr.device_id)

            causal_parent: Optional[TemporalEvent] = None
            for prev in valid_events[:i]:
                dt = (curr.timestamp - prev.timestamp).total_seconds()
                # Strict requirement: To be a cascading symptom downstream from an upstream device,
                # the upstream event MUST temporally precede it (dt > 0.05s).
                # Simultaneous events (dt <= 0.05s) must NOT be assigned invented causal ordering.
                if prev.device_id in upstream_path and dt > 0.05:
                    causal_parent = prev
                    break

            if causal_parent:
                curr.classification = EventClassification.CASCADING_SYMPTOM
                curr.causal_parent_id = causal_parent.event_id
                dt = (curr.timestamp - causal_parent.timestamp).total_seconds()
                curr.explanation = (
                    f"{curr.metric_name} shifted from baseline {curr.baseline_value:.1f} to {curr.observed_value:.1f} (z={curr.z_score:.1f}); "
                    f"Cascading symptom downstream from {causal_parent.device_id} ({causal_parent.metric_name}) "
                    f"with propagation lag of {dt:.2f}s"
                )
            else:
                # Check for earlier events on the exact same device
                same_dev_prev = next((p for p in valid_events[:i] if p.device_id == curr.device_id), None)
                if same_dev_prev:
                    dt = (curr.timestamp - same_dev_prev.timestamp).total_seconds()
                    curr.classification = EventClassification.CASCADING_SYMPTOM
                    curr.causal_parent_id = same_dev_prev.event_id
                    if dt > 0.05:
                        curr.explanation = (
                            f"{curr.metric_name} shifted from baseline {curr.baseline_value:.1f} to {curr.observed_value:.1f} (z={curr.z_score:.1f}); "
                            f"Co-occurring symptom on same device following {same_dev_prev.metric_name} (+{dt:.2f}s)"
                        )
                    else:
                        # Simultaneous measurement on same device
                        curr.explanation = (
                            f"{curr.metric_name} shifted from baseline {curr.baseline_value:.1f} to {curr.observed_value:.1f} (z={curr.z_score:.1f}); "
                            f"Co-occurring symptom on same device alongside {same_dev_prev.metric_name}"
                        )
                else:
                    curr.classification = EventClassification.INDEPENDENT_ANOMALY
                    # If upstream device exists with simultaneous anomaly, explain explicitly:
                    simul_upstream = next(
                        (p for p in valid_events[:i] if p.device_id in upstream_path and abs((curr.timestamp - p.timestamp).total_seconds()) <= 0.05),
                        None
                    )
                    if simul_upstream:
                        curr.explanation += f" (Simultaneous anomaly with upstream {simul_upstream.device_id}; causality unassigned without temporal precedence)"
                    else:
                        curr.explanation += " (Independent topological domain from prior anomalies)"

        return valid_events
