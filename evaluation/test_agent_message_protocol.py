"""Unit and integration test suite for Agent Message Protocol (AMP/2.0).

Validates:
- All 9 protocol message types
- Monotonic sequence numbering and out-of-order rejection
- Message deduplication and anti-replay
- Schema version validation and negotiation
- Clock skew and TTL staleness enforcement
- Append-only cryptographic ledger and tamper detection
- Pub/Sub delivery to targeted and broadcast subscribers
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from protocol.agent_message_protocol import (
    AgentMessageBus,
    AgentProtocolMessage,
    MessageAckStatus,
    ProtocolMessageType,
    ProtocolValidationError,
)


def test_protocol_all_message_types_supported():
    """Verify that all canonical protocol message types can be instantiated and validated."""
    bus = AgentMessageBus()
    incident = "INC-1001"
    sender = "TelemetryAgent"

    types = list(ProtocolMessageType)
    assert len(types) >= 10
    assert ProtocolMessageType.AGENT_DISAGREEMENT in types

    for seq, m_type in enumerate(types, start=1):
        msg = AgentProtocolMessage(
            incident_id=incident,
            correlation_id="CORR-1",
            message_type=m_type,
            sender=sender,
            recipient="Orchestrator",
            sequence_number=seq,
            payload={"action": m_type.value},
            confidence=0.85 if m_type in (ProtocolMessageType.HYPOTHESIS, ProtocolMessageType.ARBITRATION) else None
        )
        ack = bus.publish(msg)
        assert ack.status == MessageAckStatus.ACK, f"Failed for {m_type}: {ack.reason}"

    assert len(bus.get_audit_trail(incident_id=incident)) == len(types)
    valid, err = bus.verify_ledger_integrity()
    assert valid is True
    assert err is None


def test_protocol_sequence_monotonicity_and_out_of_order_rejection():
    """Verify that gaps or out-of-order sequences are strictly rejected with NACK."""
    bus = AgentMessageBus()
    incident = "INC-1002"
    sender = "InfrastructureAgent"

    # Message seq 1 -> Succeeded
    msg1 = AgentProtocolMessage(
        incident_id=incident,
        correlation_id="CORR-2",
        message_type=ProtocolMessageType.OBSERVATION,
        sender=sender,
        recipient="ALL",
        sequence_number=1,
        payload={"metric": "crc_errors", "value": 42}
    )
    ack1 = bus.publish(msg1)
    assert ack1.status == MessageAckStatus.ACK

    # Message seq 3 (gap, expected 2) -> Rejected
    msg3 = AgentProtocolMessage(
        incident_id=incident,
        correlation_id="CORR-2",
        message_type=ProtocolMessageType.OBSERVATION,
        sender=sender,
        recipient="ALL",
        sequence_number=3,
        payload={"metric": "crc_errors", "value": 45}
    )
    ack3 = bus.publish(msg3)
    assert ack3.status == MessageAckStatus.NACK
    assert "Out-of-order sequence number" in ack3.reason
    assert "expected 2, received 3" in ack3.reason

    # Now deliver expected seq 2 -> Succeeded
    msg2 = AgentProtocolMessage(
        incident_id=incident,
        correlation_id="CORR-2",
        message_type=ProtocolMessageType.OBSERVATION,
        sender=sender,
        recipient="ALL",
        sequence_number=2,
        payload={"metric": "crc_errors", "value": 43}
    )
    ack2 = bus.publish(msg2)
    assert ack2.status == MessageAckStatus.ACK

    # Re-delivering seq 2 -> Rejected (duplicate sequence)
    ack2_repeat = bus.publish(msg2)
    assert ack2_repeat.status == MessageAckStatus.NACK
    assert "replay detected" in ack2_repeat.reason


def test_protocol_replay_and_duplicate_message_id_rejection():
    """Verify that repeating a previously processed message_id is flagged as replay."""
    bus = AgentMessageBus()
    incident = "INC-1003"

    msg = AgentProtocolMessage(
        message_id="MSG-STATIC-ID-001",
        incident_id=incident,
        correlation_id="CORR-3",
        message_type=ProtocolMessageType.HYPOTHESIS,
        sender="WirelessAgent",
        recipient="ArbiterAgent",
        sequence_number=1,
        payload={"cause": "WEAK_WIFI"}
    )
    ack1 = bus.publish(msg)
    assert ack1.status == MessageAckStatus.ACK

    # Attempt to replay same message_id
    msg_replay = AgentProtocolMessage(
        message_id="MSG-STATIC-ID-001",
        incident_id=incident,
        correlation_id="CORR-3",
        message_type=ProtocolMessageType.HYPOTHESIS,
        sender="WirelessAgent",
        recipient="ArbiterAgent",
        sequence_number=2,
        payload={"cause": "WEAK_WIFI"}
    )
    ack_replay = bus.publish(msg_replay)
    assert ack_replay.status == MessageAckStatus.NACK
    assert "replay detected" in ack_replay.reason


def test_protocol_version_negotiation():
    """Verify supported schema versions (AMP/1.0, AMP/2.0) and rejection of unsupported versions."""
    bus = AgentMessageBus()

    # AMP/2.0
    msg_v2 = AgentProtocolMessage(
        schema_version="AMP/2.0",
        incident_id="INC-1004",
        correlation_id="CORR-4",
        message_type=ProtocolMessageType.EVIDENCE,
        sender="TelemetryAgent",
        sequence_number=1,
    )
    assert bus.publish(msg_v2).status == MessageAckStatus.ACK

    # AMP/1.0
    msg_v1 = AgentProtocolMessage(
        schema_version="AMP/1.0",
        incident_id="INC-1004",
        correlation_id="CORR-4",
        message_type=ProtocolMessageType.EVIDENCE,
        sender="TelemetryAgent",
        sequence_number=2,
    )
    assert bus.publish(msg_v1).status == MessageAckStatus.ACK

    # Unsupported AMP/99.0
    msg_invalid = AgentProtocolMessage(
        schema_version="AMP/99.0",
        incident_id="INC-1004",
        correlation_id="CORR-4",
        message_type=ProtocolMessageType.EVIDENCE,
        sender="TelemetryAgent",
        sequence_number=3,
    )
    ack_invalid = bus.publish(msg_invalid)
    assert ack_invalid.status == MessageAckStatus.NACK
    assert "Unsupported schema_version" in ack_invalid.reason


def test_protocol_clock_skew_and_ttl_staleness():
    """Verify that messages outside clock skew or beyond TTL are rejected."""
    now = datetime.now(timezone.utc)
    bus = AgentMessageBus(max_ttl_seconds=300.0, allowed_clock_skew_seconds=30.0)

    # 1. Message 120s in the future (skew exceeds 30s)
    future_time = now + timedelta(seconds=120)
    future_msg = AgentProtocolMessage(
        incident_id="INC-1005",
        correlation_id="CORR-5",
        message_type=ProtocolMessageType.OBSERVATION,
        sender="ServiceAgent",
        sequence_number=1,
        created_at=future_time
    )
    future_ack = bus.publish(future_msg, current_time=now)
    assert future_ack.status == MessageAckStatus.NACK
    assert "future-dated" in future_ack.reason

    # 2. Message 600s in the past (age exceeds max_ttl_seconds=300s)
    past_time = now - timedelta(seconds=600)
    stale_msg = AgentProtocolMessage(
        incident_id="INC-1005",
        correlation_id="CORR-5",
        message_type=ProtocolMessageType.OBSERVATION,
        sender="ServiceAgent",
        sequence_number=1,
        created_at=past_time
    )
    stale_ack = bus.publish(stale_msg, current_time=now)
    assert stale_ack.status == MessageAckStatus.NACK
    assert "Message expired" in stale_ack.reason

    # 3. Message with acceptable timestamp (10s in past)
    valid_msg = AgentProtocolMessage(
        incident_id="INC-1005",
        correlation_id="CORR-5",
        message_type=ProtocolMessageType.OBSERVATION,
        sender="ServiceAgent",
        sequence_number=1,
        created_at=now - timedelta(seconds=10)
    )
    valid_ack = bus.publish(valid_msg, current_time=now)
    assert valid_ack.status == MessageAckStatus.ACK


def test_protocol_cryptographic_ledger_and_tamper_detection():
    """Verify that the append-only cryptographic ledger detects any data tampering."""
    bus = AgentMessageBus()
    incident = "INC-1006"

    for i in range(1, 6):
        bus.publish(AgentProtocolMessage(
            incident_id=incident,
            correlation_id="CORR-6",
            message_type=ProtocolMessageType.EVIDENCE,
            sender="InfrastructureAgent",
            sequence_number=i,
            payload={"index": i}
        ))

    # Clean ledger must verify
    valid, err = bus.verify_ledger_integrity()
    assert valid is True
    assert err is None

    # Tamper with an audit entry in the middle
    audit_trail = bus.get_audit_trail()
    assert len(audit_trail) == 5
    audit_trail[2].payload_digest = "TAMPERED_FAKE_HASH_000000000000000000"

    # Verification must fail
    tampered_valid, tampered_err = bus.verify_ledger_integrity()
    assert tampered_valid is False
    assert "Tampered audit entry hash" in str(tampered_err)


def test_protocol_pub_sub_routing():
    """Verify that targeted recipients and broadcast subscribers receive expected messages."""
    bus = AgentMessageBus()
    received_arbiter = []
    received_broadcast = []

    bus.register_subscriber("ArbiterAgent", lambda m: received_arbiter.append(m))
    bus.register_subscriber("ALL", lambda m: received_broadcast.append(m))

    # Targeted message to ArbiterAgent
    msg1 = AgentProtocolMessage(
        incident_id="INC-1007",
        correlation_id="CORR-7",
        message_type=ProtocolMessageType.CHALLENGE,
        sender="PeerReviewManager",
        recipient="ArbiterAgent",
        sequence_number=1,
        payload={"claim": "LINK_CONGESTION_DISPUTED"}
    )
    bus.publish(msg1)

    # Targeted message to InfrastructureAgent
    msg2 = AgentProtocolMessage(
        incident_id="INC-1007",
        correlation_id="CORR-7",
        message_type=ProtocolMessageType.CHALLENGE,
        sender="PeerReviewManager",
        recipient="InfrastructureAgent",
        sequence_number=2,
        payload={"claim": "PORT_ERROR_QUERY"}
    )
    bus.publish(msg2)

    assert len(received_arbiter) == 1
    assert received_arbiter[0].message_id == msg1.message_id
    # Both messages delivered to broadcast
    assert len(received_broadcast) == 2


def test_protocol_canonical_json_determinism():
    """Verify that canonical JSON computation produces identical digests regardless of field ordering."""
    fixed_time = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
    msg1 = AgentProtocolMessage(
        message_id="MSG-DET-1",
        incident_id="INC-1008",
        correlation_id="CORR-8",
        message_type=ProtocolMessageType.FINAL_DECISION,
        sender="ArbiterAgent",
        sequence_number=1,
        created_at=fixed_time,
        payload={"a": 1, "b": [3, 2, 1]},
        evidence_ids=["EV-2", "EV-1"],
        limitations=["caveat-B", "caveat-A"]
    )
    hash1 = msg1.compute_hash()

    msg2 = AgentProtocolMessage(
        message_id="MSG-DET-1",
        incident_id="INC-1008",
        correlation_id="CORR-8",
        message_type=ProtocolMessageType.FINAL_DECISION,
        sender="ArbiterAgent",
        sequence_number=1,
        created_at=fixed_time,
        payload={"b": [3, 2, 1], "a": 1},
        evidence_ids=["EV-1", "EV-2"],
        limitations=["caveat-A", "caveat-B"]
    )
    hash2 = msg2.compute_hash()

    assert hash1 == hash2
    assert len(hash1) == 64


def test_protocol_unauthorized_sender_rejected():
    """Verify that an unauthorized sender is rejected with NACK."""
    bus = AgentMessageBus()
    msg = AgentProtocolMessage(
        incident_id="INC-UNAUTH-01",
        correlation_id="CORR-U",
        message_type=ProtocolMessageType.OBSERVATION,
        sender="MaliciousImposterAgent",
        sequence_number=1,
        payload={"fake": True}
    )
    ack = bus.publish(msg)
    assert ack.status == MessageAckStatus.NACK
    assert "Unauthorized message sender" in ack.reason


def test_protocol_invalid_evidence_ids_rejected():
    """Verify that empty or whitespace evidence IDs are rejected."""
    bus = AgentMessageBus()
    msg = AgentProtocolMessage(
        incident_id="INC-EVID-01",
        correlation_id="CORR-E",
        message_type=ProtocolMessageType.EVIDENCE,
        sender="TelemetryAgent",
        sequence_number=1,
        evidence_ids=["EV-VALID-1", "   "],
        payload={"valid": True}
    )
    ack = bus.publish(msg)
    assert ack.status == MessageAckStatus.NACK
    assert "Invalid evidence reference" in ack.reason


def test_protocol_create_and_publish_monotonic_sequence():
    """Verify create_and_publish helper monotonically advances sequence numbers."""
    bus = AgentMessageBus()
    inc_id = "INC-SEQ-TEST"
    
    msg1, ack1 = bus.create_and_publish(
        sender="TelemetryAgent",
        recipient="ArbiterAgent",
        message_type=ProtocolMessageType.OBSERVATION,
        incident_id=inc_id,
        correlation_id="CORR-SEQ",
        payload={"step": 1}
    )
    assert ack1.status == MessageAckStatus.ACK
    assert msg1.sequence_number == 1

    msg2, ack2 = bus.create_and_publish(
        sender="TelemetryAgent",
        recipient="ArbiterAgent",
        message_type=ProtocolMessageType.HYPOTHESIS,
        incident_id=inc_id,
        correlation_id="CORR-SEQ",
        payload={"step": 2}
    )
    assert ack2.status == MessageAckStatus.ACK
    assert msg2.sequence_number == 2


def test_protocol_orchestrator_peer_review_responses_emitted():
    """Verify that peer-review challenge-responses are converted to canonical AMP/2.0 RESPONSE messages."""
    from core.orchestrator import NetworkIntelligenceOrchestrator

    orchestrator = NetworkIntelligenceOrchestrator()
    # Scenario triggering challenge-response (Rule 1: dropped packets with switch errors)
    raw_payload = [
        {
            "device_id": "IITBBS-SW-CORE",
            "device_type": "SWITCH",
            "tier": "CORE",
            "metrics": {
                "packet_loss_pct": 15.0,
                "interface_errors": 500,
                "crc_errors": 120,
                "buffer_pool_exhaustion": True
            }
        }
    ]
    result = orchestrator.process(raw_payload)
    response_msgs = [
        m for m in result.agent_messages
        if isinstance(m, AgentProtocolMessage) and m.message_type == ProtocolMessageType.RESPONSE
    ]
    assert len(response_msgs) >= 1
    resp = response_msgs[0]
    assert resp.sender == "TelemetryAgent"
    assert resp.recipient == "InfrastructureAgent"
    assert "verdict" in resp.payload
    assert resp.payload["verdict"] == "CONCEDED"
    assert resp.evidence_ids is not None


def test_protocol_strict_protocol_mode_raises_on_validation_failure():
    """Verify that strict_protocol_mode raises ProtocolValidationError if any protocol message fails validation."""
    from core.orchestrator import NetworkIntelligenceOrchestrator

    orchestrator = NetworkIntelligenceOrchestrator(strict_protocol_mode=True)
    # Configure the message bus to reject TelemetryAgent (unauthorized sender test)
    orchestrator.message_bus.authorized_senders = {"Orchestrator", "InfrastructureAgent"}

    sample_payload = [{"device_id": "TEST-SW-01", "metrics": {"packet_drop_rate": 5.0}}]
    with pytest.raises(ProtocolValidationError) as exc_info:
        orchestrator.process(sample_payload)
    assert "Protocol validation failed" in str(exc_info.value)
    assert "Unauthorized message sender 'TelemetryAgent'" in str(exc_info.value)


def test_protocol_non_strict_mode_records_nack_in_limitations():
    """Verify that non-strict mode records protocol NACKs in trace and appends to report limitations."""
    from core.orchestrator import NetworkIntelligenceOrchestrator

    orchestrator = NetworkIntelligenceOrchestrator(strict_protocol_mode=False)
    # Restrict senders so TelemetryAgent gets a NACK
    orchestrator.message_bus.authorized_senders = {"Orchestrator", "InfrastructureAgent"}

    sample_payload = [{"device_id": "TEST-SW-02", "metrics": {"packet_drop_rate": 5.0}}]
    result = orchestrator.process(sample_payload)
    
    nack_traces = [t for t in result.execution_trace if t["step"] == "PROTOCOL_NACK"]
    assert len(nack_traces) >= 1
    assert any("Protocol NACK for message" in lim for lim in result.report.limitations)

