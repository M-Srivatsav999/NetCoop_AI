"""Curated Challenge Dataset Generator for NetCoop AI.

Generates data/challenge_dataset.json with 50 realistic, hand-crafted, non-templated
network incident scenarios testing subtle edge cases:
- Asymmetric link latency & buffer congestion
- Physical hardware failure & CRC frame corruptions
- Core DNS/DHCP services degradation
- Wi-Fi RF path loss and signal attenuation
- Control plane resource exhaustion
- Normal campus baseline operation
- Insufficient evidence & critical staleness abstention
- Multi-incident concurrent independent fault domains
"""

import json
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = PROJECT_ROOT / "data" / "challenge_dataset.json"

CHALLENGE_CASES = []

def add_case(
    case_id: str,
    title: str,
    ground_truth: str,
    affected_devices: list,
    telemetry: list,
    expected_abstention: bool = False,
    expected_cluster_count: int = 1,
    secondary_causes: list = None,
    notes: str = ""
):
    CHALLENGE_CASES.append({
        "case_id": case_id,
        "title": title,
        "ground_truth_root_cause": ground_truth,
        "secondary_root_causes": secondary_causes or [],
        "affected_devices": affected_devices,
        "expected_abstention": expected_abstention,
        "expected_cluster_count": expected_cluster_count,
        "notes": notes,
        "telemetry_payload": telemetry
    })

BASE_TIME = "2026-11-01T10:00:00Z"

# -------------------------------------------------------------
# 1. Asymmetric Link Latency & Buffer Congestion (Cases 1-8)
# -------------------------------------------------------------
add_case(
    "CHALLENGE-001",
    "Uplink Buffer Saturated on Mahanadi Hall Switch",
    "LINK_CONGESTION",
    ["IITBBS-SW-MHR"],
    [{
        "device_id": "IITBBS-SW-MHR",
        "timestamp": BASE_TIME,
        "status": "WARNING",
        "metrics": {"latency_ms": 185.0, "jitter_ms": 28.0, "packet_loss_pct": 4.5, "queue_drops": 140, "interface_errors": 0}
    }],
    notes="High latency + queue drops with zero interface errors proves link congestion"
)

add_case(
    "CHALLENGE-002",
    "Microburst Video Traffic Overwhelming Brahmaputra Distribution Uplink",
    "LINK_CONGESTION",
    ["IITBBS-SW-BHR"],
    [{
        "device_id": "IITBBS-SW-BHR",
        "timestamp": BASE_TIME,
        "status": "WARNING",
        "metrics": {"latency_ms": 210.0, "jitter_ms": 35.0, "packet_loss_pct": 6.0, "queue_drops": 220, "interface_errors": 0}
    }],
    notes="Transient microburst causing buffer drops"
)

add_case(
    "CHALLENGE-003",
    "Hostel Subnet Uplink Saturated with Heavy Backup Flow",
    "LINK_CONGESTION",
    ["IITBBS-SW-SHR"],
    [{
        "device_id": "IITBBS-SW-SHR",
        "timestamp": BASE_TIME,
        "status": "WARNING",
        "metrics": {"latency_ms": 165.0, "packet_loss_pct": 3.8, "queue_drops": 95, "link_utilization_pct": 94.0}
    }],
    notes="Link utilization 94% with queue drops"
)

add_case(
    "CHALLENGE-004",
    "Academic Complex Switch Upstream Aggregation Congestion",
    "LINK_CONGESTION",
    ["IITBBS-SW-SMS"],
    [{
        "device_id": "IITBBS-SW-SMS",
        "timestamp": BASE_TIME,
        "status": "WARNING",
        "metrics": {"latency_ms": 178.0, "jitter_ms": 22.0, "packet_loss_pct": 5.2, "queue_drops": 110, "throughput_mbps": 12.0}
    }],
    notes="Throughput degradation accompanied by buffer drops"
)

add_case(
    "CHALLENGE-005",
    "Research Wing Edge Saturated During Dataset Sync",
    "LINK_CONGESTION",
    ["IITBBS-SW-SES"],
    [{
        "device_id": "IITBBS-SW-SES",
        "timestamp": BASE_TIME,
        "status": "WARNING",
        "metrics": {"latency_ms": 195.0, "packet_loss_pct": 4.1, "queue_drops": 160, "interface_errors": 0}
    }],
    notes="Bulk dataset synchronization saturation"
)

add_case(
    "CHALLENGE-006",
    "Central Library Switch Congested Under Peak Study Hours",
    "LINK_CONGESTION",
    ["IITBBS-SW-LBC"],
    [{
        "device_id": "IITBBS-SW-LBC",
        "timestamp": BASE_TIME,
        "status": "WARNING",
        "metrics": {"latency_ms": 160.0, "jitter_ms": 19.0, "packet_loss_pct": 3.5, "queue_drops": 85, "link_utilization_pct": 91.5}
    }],
    notes="High library user concurrency saturation"
)

add_case(
    "CHALLENGE-007",
    "Admin Building Switch Buffer Overrun",
    "LINK_CONGESTION",
    ["IITBBS-SW-ADMIN"],
    [{
        "device_id": "IITBBS-SW-ADMIN",
        "timestamp": BASE_TIME,
        "status": "WARNING",
        "metrics": {"latency_ms": 172.0, "packet_loss_pct": 4.8, "queue_drops": 130, "interface_errors": 0}
    }],
    notes="Administrative block switch buffer drops"
)

add_case(
    "CHALLENGE-008",
    "Core Distribution Link Congestion Spilling to Edge",
    "LINK_CONGESTION",
    ["DIST-SW-01"],
    [{
        "device_id": "DIST-SW-01",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"latency_ms": 240.0, "jitter_ms": 42.0, "packet_loss_pct": 8.0, "queue_drops": 350, "link_utilization_pct": 98.0}
    }],
    notes="Distribution layer link 98% saturated"
)

# -------------------------------------------------------------
# 2. Hardware Failure & Physical Layer Cable Faults (Cases 9-16)
# -------------------------------------------------------------
add_case(
    "CHALLENGE-009",
    "FCS / CRC Frame Corruption on Subarnarekha Hostel Switch",
    "HARDWARE_FAILURE",
    ["IITBBS-SW-SHR"],
    [{
        "device_id": "IITBBS-SW-SHR",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"latency_ms": 22.0, "packet_loss_pct": 14.0, "interface_errors": 85, "crc_errors": 70, "queue_drops": 0}
    }],
    notes="High CRC errors and packet loss with normal latency confirms physical layer defect"
)

add_case(
    "CHALLENGE-010",
    "Damaged Fiber Patch Cable on Core Interconnect",
    "HARDWARE_FAILURE",
    ["CORE-SW-01"],
    [{
        "device_id": "CORE-SW-01",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"latency_ms": 18.0, "packet_loss_pct": 18.5, "interface_errors": 140, "crc_errors": 115}
    }],
    notes="Physical fiber cable degradation causing frame drops"
)

add_case(
    "CHALLENGE-011",
    "Transceiver SFP Fault on Rishikulya Switch",
    "HARDWARE_FAILURE",
    ["IITBBS-SW-RHR"],
    [{
        "device_id": "IITBBS-SW-RHR",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"latency_ms": 25.0, "packet_loss_pct": 12.0, "interface_errors": 95, "crc_errors": 80}
    }],
    notes="SFP optic transceiver emitting corrupted Ethernet frames"
)

add_case(
    "CHALLENGE-012",
    "Bad Switch Port ASIC Port 12 Flapping",
    "HARDWARE_FAILURE",
    ["IITBBS-SW-MHR"],
    [{
        "device_id": "IITBBS-SW-MHR",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"latency_ms": 30.0, "packet_loss_pct": 16.0, "interface_errors": 110, "crc_errors": 90}
    }],
    notes="Internal PHY hardware fault"
)

add_case(
    "CHALLENGE-013",
    "Mechanical Cable Strain on Lecture Hall Complex",
    "HARDWARE_FAILURE",
    ["IITBBS-SW-LHC"],
    [{
        "device_id": "IITBBS-SW-LHC",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"latency_ms": 20.0, "packet_loss_pct": 15.0, "interface_errors": 75, "crc_errors": 60}
    }],
    notes="Cable crimp damage causing interface errors"
)

add_case(
    "CHALLENGE-014",
    "Electromagnetic Interference (EMI) Inducing Packet Corruptions",
    "HARDWARE_FAILURE",
    ["IITBBS-SW-POWER"],
    [{
        "device_id": "IITBBS-SW-POWER",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"latency_ms": 28.0, "packet_loss_pct": 22.0, "interface_errors": 160, "crc_errors": 140}
    }],
    notes="Substation EMI causing CRC check failures"
)

add_case(
    "CHALLENGE-015",
    "Water Ingress on Outdoor Fiber Enclosure",
    "HARDWARE_FAILURE",
    ["DIST-SW-OUTDOOR"],
    [{
        "device_id": "DIST-SW-OUTDOOR",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"latency_ms": 32.0, "packet_loss_pct": 25.0, "interface_errors": 210, "crc_errors": 180}
    }],
    notes="Fiber splice tray condensation"
)

add_case(
    "CHALLENGE-016",
    "Switch Backplane Bus Degradation",
    "HARDWARE_FAILURE",
    ["IITBBS-SW-SES"],
    [{
        "device_id": "IITBBS-SW-SES",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"latency_ms": 24.0, "packet_loss_pct": 13.0, "interface_errors": 88, "crc_errors": 65}
    }],
    notes="Backplane fabric error counters rising"
)

# -------------------------------------------------------------
# 3. Core DNS & DHCP Services Failures (Cases 17-24)
# -------------------------------------------------------------
add_case(
    "CHALLENGE-017",
    "DNS Primary Daemon Unresponsive (Resolution Timeout)",
    "DNS_DHCP_FAILURE",
    ["SRV-DNS-01"],
    [{
        "device_id": "SRV-DNS-01",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"latency_ms": 15.0, "packet_loss_pct": 0.0, "dns_resolution_ms": 1250.0, "interface_errors": 0}
    }],
    notes="Zero packet loss + 1250ms DNS resolution isolates application service fault"
)

add_case(
    "CHALLENGE-018",
    "DHCP Address Pool Exhaustion on Hostel Scope",
    "DNS_DHCP_FAILURE",
    ["SRV-DHCP-01"],
    [{
        "device_id": "SRV-DHCP-01",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"latency_ms": 14.0, "packet_loss_pct": 0.0, "dhcp_lease_success": False, "dns_resolution_ms": 18.0}
    }],
    notes="dhcp_lease_success is False on nominal link"
)

add_case(
    "CHALLENGE-019",
    "DNS SERVFAIL on Campus Authoritative Nameserver",
    "DNS_DHCP_FAILURE",
    ["SRV-DNS-02"],
    [{
        "device_id": "SRV-DNS-02",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"latency_ms": 16.0, "packet_loss_pct": 0.0, "dns_resolution_ms": 890.0}
    }],
    notes="DNS SERVFAIL response causes resolution delay > 500ms"
)

add_case(
    "CHALLENGE-020",
    "DHCP Relay Agent Failure on Distribution Switch",
    "DNS_DHCP_FAILURE",
    ["DIST-SW-RELAY"],
    [{
        "device_id": "DIST-SW-RELAY",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"latency_ms": 18.0, "dhcp_lease_success": False, "packet_loss_pct": 0.0}
    }],
    notes="DHCP relay forward drop prevents student lease acquisition"
)

add_case(
    "CHALLENGE-021",
    "Recursive DNS Resolver Rate-Limiting Campus Clients",
    "DNS_DHCP_FAILURE",
    ["SRV-DNS-RECURSIVE"],
    [{
        "device_id": "SRV-DNS-RECURSIVE",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"latency_ms": 15.0, "dns_resolution_ms": 950.0}
    }],
    notes="Rate-limit backoff pushes DNS latency to near 1 second"
)

add_case(
    "CHALLENGE-022",
    "DHCP NAK Storm From Corrupt Lease Database",
    "DNS_DHCP_FAILURE",
    ["SRV-DHCP-02"],
    [{
        "device_id": "SRV-DHCP-02",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"latency_ms": 12.0, "dhcp_lease_success": False}
    }],
    notes="Database lock triggers immediate DHCP lease denial"
)

add_case(
    "CHALLENGE-023",
    "DNS Forwarder Blackholing Internal Campus Domains",
    "DNS_DHCP_FAILURE",
    ["SRV-DNS-FWD"],
    [{
        "device_id": "SRV-DNS-FWD",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"latency_ms": 14.0, "dns_resolution_ms": 1500.0}
    }],
    notes="Forwarder timeout on intranet lookups"
)

add_case(
    "CHALLENGE-024",
    "Rogue DHCP Server Conflict on Student Dormitory",
    "DNS_DHCP_FAILURE",
    ["IITBBS-SW-MHR-ACCESS"],
    [{
        "device_id": "IITBBS-SW-MHR-ACCESS",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"latency_ms": 16.0, "dhcp_lease_success": False, "packet_loss_pct": 0.0}
    }],
    notes="Rogue DHCP server blocking legitimate lease confirmations"
)

# -------------------------------------------------------------
# 4. Weak Wi-Fi RF Path Loss & Interferences (Cases 25-32)
# -------------------------------------------------------------
add_case(
    "CHALLENGE-025",
    "Mahanadi Wing A Weak Wi-Fi Signal Coverage Hole",
    "WEAK_WIFI",
    ["AP-MHR-W1"],
    [{
        "device_id": "AP-MHR-W1",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"signal_strength_dbm": -82.0, "packet_loss_pct": 12.0, "latency_ms": 45.0}
    }],
    notes="Signal -82 dBm is below the -75 dBm roaming floor"
)

add_case(
    "CHALLENGE-026",
    "Auditorium Co-Channel Interference with Severe RF Attenuation",
    "WEAK_WIFI",
    ["AP-AUD-01"],
    [{
        "device_id": "AP-AUD-01",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"signal_strength_dbm": -86.0, "packet_loss_pct": 18.0, "latency_ms": 55.0}
    }],
    notes="Extreme path loss through acoustic baffles"
)

add_case(
    "CHALLENGE-027",
    "Central Canteen Access Point Antenna Misorientation",
    "WEAK_WIFI",
    ["AP-CANTEEN-01"],
    [{
        "device_id": "AP-CANTEEN-01",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"signal_strength_dbm": -79.0, "packet_loss_pct": 8.5}
    }],
    notes="Physical antenna polarization mismatch"
)

add_case(
    "CHALLENGE-028",
    "Library Quiet Zone RF Shielding",
    "WEAK_WIFI",
    ["AP-LBC-02"],
    [{
        "device_id": "AP-LBC-02",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"signal_strength_dbm": -84.0, "packet_loss_pct": 14.0}
    }],
    notes="Metallic architectural mesh attenuating 5GHz signals"
)

add_case(
    "CHALLENGE-029",
    "Guest House Outdoor Terrace Long-Range Link",
    "WEAK_WIFI",
    ["AP-GH-01"],
    [{
        "device_id": "AP-GH-01",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"signal_strength_dbm": -88.0, "packet_loss_pct": 21.0}
    }],
    notes="Free space path loss on terrace clients"
)

add_case(
    "CHALLENGE-030",
    "Subarnarekha Wing B Concrete Pillar Shadowing",
    "WEAK_WIFI",
    ["AP-SHR-W2"],
    [{
        "device_id": "AP-SHR-W2",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"signal_strength_dbm": -81.0, "packet_loss_pct": 9.0}
    }],
    notes="Reinforced concrete obstruction"
)

add_case(
    "CHALLENGE-031",
    "Sports Complex Gymnasium Multipath Distortion",
    "WEAK_WIFI",
    ["AP-GYM-01"],
    [{
        "device_id": "AP-GYM-01",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"signal_strength_dbm": -83.0, "packet_loss_pct": 11.5}
    }],
    notes="Metal girder reflections causing destructive interference"
)

add_case(
    "CHALLENGE-032",
    "Faculty Housing Walkway Boundary Degradation",
    "WEAK_WIFI",
    ["AP-FAC-01"],
    [{
        "device_id": "AP-FAC-01",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"signal_strength_dbm": -85.0, "packet_loss_pct": 15.0}
    }],
    notes="Peripheral cell edge degradation"
)

# -------------------------------------------------------------
# 5. Control Plane Resource Exhaustion (Cases 33-38)
# -------------------------------------------------------------
add_case(
    "CHALLENGE-033",
    "BGP Process Loop Saturating Core Switch CPU",
    "RESOURCE_EXHAUSTION",
    ["IITBBS-CORE-SW1"],
    [{
        "device_id": "IITBBS-CORE-SW1",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"cpu_pct": 96.0, "memory_pct": 82.0, "latency_ms": 35.0, "queue_drops": 0}
    }],
    notes="Control plane 96% CPU spike without interface buffer congestion"
)

add_case(
    "CHALLENGE-034",
    "Memory Leak on Academic Gateway Switch",
    "RESOURCE_EXHAUSTION",
    ["IITBBS-SW-SMS"],
    [{
        "device_id": "IITBBS-SW-SMS",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"cpu_pct": 78.0, "memory_pct": 95.5, "latency_ms": 28.0}
    }],
    notes="Memory exhausted at 95.5% triggers resource exhaustion hypothesis"
)

add_case(
    "CHALLENGE-035",
    "SNMP Query Storm Saturating Switch CPU",
    "RESOURCE_EXHAUSTION",
    ["IITBBS-SW-MHR"],
    [{
        "device_id": "IITBBS-SW-MHR",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"cpu_pct": 98.0, "memory_pct": 88.0}
    }],
    notes="SNMP agent poll loop hogging CPU cycles"
)

add_case(
    "CHALLENGE-036",
    "TCAM Overflow on Multicast Distribution Node",
    "RESOURCE_EXHAUSTION",
    ["DIST-SW-TCAM"],
    [{
        "device_id": "DIST-SW-TCAM",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"cpu_pct": 92.0, "memory_pct": 94.0}
    }],
    notes="Table exhaustion causing software punt"
)

add_case(
    "CHALLENGE-037",
    "Syslog Daemon Buffer OOM Condition",
    "RESOURCE_EXHAUSTION",
    ["IITBBS-SW-SES"],
    [{
        "device_id": "IITBBS-SW-SES",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"cpu_pct": 89.0, "memory_pct": 97.0}
    }],
    notes="System RAM at 97%"
)

add_case(
    "CHALLENGE-038",
    "Crypto Process Spike During SSH Key Rotation",
    "RESOURCE_EXHAUSTION",
    ["IITBBS-SW-LBC"],
    [{
        "device_id": "IITBBS-SW-LBC",
        "timestamp": BASE_TIME,
        "status": "CRITICAL",
        "metrics": {"cpu_pct": 95.0, "memory_pct": 75.0}
    }],
    notes="Heavy cryptographic calculations pinning CPU"
)

# -------------------------------------------------------------
# 6. Normal Campus Baseline Operations (Cases 39-44)
# -------------------------------------------------------------
add_case(
    "CHALLENGE-039",
    "Nominal Baseline Telemetry on Core Switch",
    "NORMAL_OPERATION",
    ["IITBBS-CORE-SW1"],
    [{
        "device_id": "IITBBS-CORE-SW1",
        "timestamp": BASE_TIME,
        "status": "HEALTHY",
        "metrics": {"latency_ms": 12.0, "jitter_ms": 1.2, "packet_loss_pct": 0.0, "queue_drops": 0, "interface_errors": 0, "cpu_pct": 32.0, "memory_pct": 45.0}
    }],
    notes="All transport, interface, and hardware metrics strictly nominal"
)

add_case(
    "CHALLENGE-040",
    "Quiet Nighttime Operations on Mahanadi Hall Switch",
    "NORMAL_OPERATION",
    ["IITBBS-SW-MHR"],
    [{
        "device_id": "IITBBS-SW-MHR",
        "timestamp": BASE_TIME,
        "status": "HEALTHY",
        "metrics": {"latency_ms": 15.0, "packet_loss_pct": 0.0, "queue_drops": 0, "interface_errors": 0}
    }],
    notes="Nominal operation verified"
)

add_case(
    "CHALLENGE-041",
    "Healthy High-Speed Link on School of Electrical Sciences",
    "NORMAL_OPERATION",
    ["IITBBS-SW-SES"],
    [{
        "device_id": "IITBBS-SW-SES",
        "timestamp": BASE_TIME,
        "status": "HEALTHY",
        "metrics": {"latency_ms": 9.5, "packet_loss_pct": 0.0, "throughput_mbps": 850.0, "queue_drops": 0}
    }],
    notes="Full throughput with zero drops"
)

add_case(
    "CHALLENGE-042",
    "Nominal DNS Server Operations",
    "NORMAL_OPERATION",
    ["SRV-DNS-01"],
    [{
        "device_id": "SRV-DNS-01",
        "timestamp": BASE_TIME,
        "status": "HEALTHY",
        "metrics": {"dns_resolution_ms": 8.0, "packet_loss_pct": 0.0, "latency_ms": 4.0}
    }],
    notes="Sub-10ms DNS resolution is perfectly healthy"
)

add_case(
    "CHALLENGE-043",
    "Nominal DHCP Server Lease Issuance",
    "NORMAL_OPERATION",
    ["SRV-DHCP-01"],
    [{
        "device_id": "SRV-DHCP-01",
        "timestamp": BASE_TIME,
        "status": "HEALTHY",
        "metrics": {"dhcp_lease_success": True, "latency_ms": 5.0, "packet_loss_pct": 0.0}
    }],
    notes="DHCP operational and responding"
)

add_case(
    "CHALLENGE-044",
    "Optimal Wi-Fi Access Point RF Metrics",
    "NORMAL_OPERATION",
    ["AP-MHR-W1"],
    [{
        "device_id": "AP-MHR-W1",
        "timestamp": BASE_TIME,
        "status": "HEALTHY",
        "metrics": {"signal_strength_dbm": -52.0, "packet_loss_pct": 0.0, "latency_ms": 14.0}
    }],
    notes="Signal -52 dBm is optimal RF strength"
)

# -------------------------------------------------------------
# 7. Insufficient Evidence & Critical Staleness Abstention (Cases 45-47)
# -------------------------------------------------------------
add_case(
    "CHALLENGE-045",
    "Severely Stale Telemetry (6 Hours Old) Requiring Abstention",
    "INSUFFICIENT_EVIDENCE",
    [],
    [{
        "device_id": "IITBBS-SW-MHR",
        "timestamp": "2026-11-01T04:00:00Z",  # 6 hours prior to 10:00 UTC
        "status": "HEALTHY",
        "metrics": {"latency_ms": 15.0, "packet_loss_pct": 0.0}
    }],
    expected_abstention=True,
    notes="Staleness > 7200s with nominal telemetry triggers honest epistemic abstention"
)

add_case(
    "CHALLENGE-046",
    "Completely Empty Telemetry Payload Requiring Abstention",
    "INSUFFICIENT_EVIDENCE",
    [],
    [],
    expected_abstention=True,
    notes="Zero telemetry records must cleanly trigger INSUFFICIENT_EVIDENCE"
)

add_case(
    "CHALLENGE-047",
    "Borderline Telemetry Without Decisive Anomaly Signals",
    "INSUFFICIENT_EVIDENCE",
    [],
    [{
        "device_id": "IITBBS-SW-UNKNOWN",
        "timestamp": BASE_TIME,
        "status": "UNKNOWN",
        "metrics": {"latency_ms": 36.0}  # Barely over baseline, everything else missing
    }],
    expected_abstention=True,
    notes="Extremely sparse single-metric reading below confidence threshold"
)

# -------------------------------------------------------------
# 8. Multi-Incident Concurrent Independent Campus Faults (Cases 48-50)
# -------------------------------------------------------------
add_case(
    "CHALLENGE-048",
    "Concurrent Independent Faults: Mahanadi Congestion + Rishikulya Hardware Failure",
    "LINK_CONGESTION",  # Primary root cause
    ["IITBBS-SW-MHR", "IITBBS-SW-RHR"],
    [
        # Incident 1: Congestion in Mahanadi Hall
        {
            "device_id": "IITBBS-SW-MHR",
            "timestamp": BASE_TIME,
            "status": "WARNING",
            "metrics": {"latency_ms": 190.0, "queue_drops": 140, "packet_loss_pct": 5.0, "interface_errors": 0}
        },
        # Incident 2: Hardware Physical Failure in Rishikulya Hall
        {
            "device_id": "IITBBS-SW-RHR",
            "timestamp": BASE_TIME,
            "status": "CRITICAL",
            "metrics": {"latency_ms": 22.0, "interface_errors": 90, "crc_errors": 75, "packet_loss_pct": 14.0}
        }
    ],
    expected_cluster_count=2,
    secondary_causes=["HARDWARE_FAILURE"],
    notes="Page 5 multi-incident: two independent hostels experiencing distinct fault types simultaneously"
)

add_case(
    "CHALLENGE-049",
    "Concurrent Independent Faults: Library Wi-Fi RF Hole + Central DNS Service Outage",
    "DNS_DHCP_FAILURE",
    ["SRV-DNS-01", "AP-LBC-01"],
    [
        # Incident 1: Core DNS failure
        {
            "device_id": "SRV-DNS-01",
            "timestamp": BASE_TIME,
            "status": "CRITICAL",
            "metrics": {"dns_resolution_ms": 1100.0, "packet_loss_pct": 0.0, "latency_ms": 15.0}
        },
        # Incident 2: RF attenuation in Library
        {
            "device_id": "AP-LBC-01",
            "timestamp": BASE_TIME,
            "status": "CRITICAL",
            "metrics": {"signal_strength_dbm": -84.0, "packet_loss_pct": 12.0}
        }
    ],
    expected_cluster_count=2,
    secondary_causes=["WEAK_WIFI"],
    notes="Concurrent application service failure and wireless RF attenuation in separate facilities"
)

add_case(
    "CHALLENGE-050",
    "Concurrent Independent Faults: Electrical Sciences Congestion + Admin Switch CPU Saturation",
    "LINK_CONGESTION",
    ["IITBBS-SW-SES", "IITBBS-SW-ADMIN"],
    [
        # Incident 1: Link congestion in SES
        {
            "device_id": "IITBBS-SW-SES",
            "timestamp": BASE_TIME,
            "status": "WARNING",
            "metrics": {"latency_ms": 182.0, "queue_drops": 125, "packet_loss_pct": 4.2, "interface_errors": 0}
        },
        # Incident 2: Control plane CPU spike in Admin
        {
            "device_id": "IITBBS-SW-ADMIN",
            "timestamp": BASE_TIME,
            "status": "CRITICAL",
            "metrics": {"cpu_pct": 97.0, "memory_pct": 89.0, "latency_ms": 25.0}
        }
    ],
    expected_cluster_count=2,
    secondary_causes=["RESOURCE_EXHAUSTION"],
    notes="Simultaneous network buffer saturation and control plane processor exhaustion"
)

def build_file():
    assert len(CHALLENGE_CASES) == 50, f"Expected exactly 50 cases, got {len(CHALLENGE_CASES)}"
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(CHALLENGE_CASES, f, indent=2)
    print(f"Successfully generated {len(CHALLENGE_CASES)} challenge cases to {DATA_FILE}")

if __name__ == "__main__":
    build_file()
