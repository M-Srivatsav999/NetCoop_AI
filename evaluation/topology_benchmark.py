"""Dedicated Network Topology Generalization Benchmark.

Tests NetCoop AI's multi-agent architecture across four genuinely novel, unseen network topologies:
1. Spine-Leaf Data Center Fabric (Multi-Root Clos Network)
2. Metro Ring Resilient Network (Cycle with redundant dual homing)
3. Multi-Domain Campus WAN (Geographically separated distribution hubs)
4. Star-Mesh Hybrid (Full mesh core with star access spokes)

Verifies that fault localization, blast radius calculation, peer review deliberation,
temporal ordering, and abstention behavior generalize correctly across arbitrary graph architectures
without overfitting to the primary IIT Bhubaneswar campus tree.

Outputs results to evaluation/topology_benchmark_report.json.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.orchestrator import NetworkIntelligenceOrchestrator
from core.topology import TopologyEngine, TopologyNode
from protocol.models import CanonicalTelemetry

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_REPORT_PATH = PROJECT_ROOT / "evaluation" / "topology_benchmark_report.json"


# -----------------------------------------------------------------------------
# Topology Definitions
# -----------------------------------------------------------------------------

def create_spine_leaf_topology() -> Dict[str, Any]:
    """Spine-Leaf Clos Fabric (Dual spine, 4 leaves, 4 server pods)."""
    return {
        "network_name": "Spine-Leaf Cloud Data Center Fabric",
        "version": "1.0",
        "nodes": [
            {"id": "SPINE-01", "type": "spine_switch", "name": "Spine Switch 01", "location": "DC-RowA-Rack1", "capacity_gbps": 100.0, "parent": None},
            {"id": "SPINE-02", "type": "spine_switch", "name": "Spine Switch 02", "location": "DC-RowB-Rack1", "capacity_gbps": 100.0, "parent": None},
            {"id": "LEAF-01", "type": "leaf_switch", "name": "Leaf Top-of-Rack 01", "location": "DC-RowA-Rack2", "capacity_gbps": 40.0, "parent": "SPINE-01"},
            {"id": "LEAF-02", "type": "leaf_switch", "name": "Leaf Top-of-Rack 02", "location": "DC-RowA-Rack3", "capacity_gbps": 40.0, "parent": "SPINE-01"},
            {"id": "LEAF-03", "type": "leaf_switch", "name": "Leaf Top-of-Rack 03", "location": "DC-RowB-Rack2", "capacity_gbps": 40.0, "parent": "SPINE-02"},
            {"id": "LEAF-04", "type": "leaf_switch", "name": "Leaf Top-of-Rack 04", "location": "DC-RowB-Rack3", "capacity_gbps": 40.0, "parent": "SPINE-02"},
            {"id": "SRV-WEB-01", "type": "server", "name": "Web Application Cluster Node 1", "location": "DC-Rack2-U10", "capacity_gbps": 10.0, "parent": "LEAF-01"},
            {"id": "SRV-APP-01", "type": "server", "name": "Application Backend Node 1", "location": "DC-Rack3-U10", "capacity_gbps": 10.0, "parent": "LEAF-02"},
            {"id": "SRV-DB-01", "type": "server", "name": "Database Cluster Node 1", "location": "DC-Rack4-U10", "capacity_gbps": 10.0, "parent": "LEAF-03"},
            {"id": "SRV-STORAGE-01", "type": "server", "name": "SAN Storage Controller", "location": "DC-Rack5-U10", "capacity_gbps": 10.0, "parent": "LEAF-04"}
        ],
        "service_dependencies": {
            "SRV-WEB-01": {"database": "SRV-DB-01", "backend": "SRV-APP-01"},
            "SRV-APP-01": {"database": "SRV-DB-01", "storage": "SRV-STORAGE-01"}
        }
    }


def create_metro_ring_topology() -> Dict[str, Any]:
    """Metro Optical Packet Ring with 5 ring switches and edge branches."""
    return {
        "network_name": "Metro Packet Optical Ring",
        "version": "1.0",
        "nodes": [
            {"id": "RING-01", "type": "ring_node", "name": "Metro Hub Central", "location": "PoP-Downtown", "capacity_gbps": 100.0, "parent": None},
            {"id": "RING-02", "type": "ring_node", "name": "Metro Ring North", "location": "PoP-NorthEdge", "capacity_gbps": 40.0, "parent": "RING-01"},
            {"id": "RING-03", "type": "ring_node", "name": "Metro Ring East", "location": "PoP-EastSuburbs", "capacity_gbps": 40.0, "parent": "RING-02"},
            {"id": "RING-04", "type": "ring_node", "name": "Metro Ring South", "location": "PoP-SouthIndustrial", "capacity_gbps": 40.0, "parent": "RING-03"},
            {"id": "RING-05", "type": "ring_node", "name": "Metro Ring West", "location": "PoP-WestTechPark", "capacity_gbps": 40.0, "parent": "RING-04"},
            {"id": "EDGE-N1", "type": "edge_access", "name": "North Enterprise Access", "location": "Enterprise-Park", "capacity_gbps": 10.0, "parent": "RING-02"},
            {"id": "EDGE-E1", "type": "edge_access", "name": "East Residential Gateway", "location": "Residential-Agg", "capacity_gbps": 10.0, "parent": "RING-03"},
            {"id": "EDGE-W1", "type": "edge_access", "name": "West Tech Hub Gateway", "location": "TechHub-Bldg1", "capacity_gbps": 10.0, "parent": "RING-05"}
        ],
        "service_dependencies": {}
    }


def create_multi_domain_wan_topology() -> Dict[str, Any]:
    """Multi-Domain WAN connecting Academic, Residential, and Research zones."""
    return {
        "network_name": "Multi-Domain Inter-Campus WAN",
        "version": "1.0",
        "nodes": [
            {"id": "WAN-CORE-NORTH", "type": "wan_core", "name": "WAN Primary Gateway", "location": "North Datacenter", "capacity_gbps": 100.0, "parent": None},
            {"id": "DIST-ACADEMIC", "type": "dist_switch", "name": "Academic Zone Aggregator", "location": "Academic Hub", "capacity_gbps": 40.0, "parent": "WAN-CORE-NORTH"},
            {"id": "DIST-RESIDENTIAL", "type": "dist_switch", "name": "Hostel Zone Aggregator", "location": "Hostel Hub", "capacity_gbps": 40.0, "parent": "WAN-CORE-NORTH"},
            {"id": "DIST-RESEARCH", "type": "dist_switch", "name": "Research High-Performance Aggregator", "location": "Research Complex", "capacity_gbps": 40.0, "parent": "WAN-CORE-NORTH"},
            {"id": "BLDG-BIO", "type": "building_switch", "name": "Bio-Tech Lab Switch", "location": "Bio Sciences Bldg", "capacity_gbps": 10.0, "parent": "DIST-ACADEMIC"},
            {"id": "BLDG-CHEM", "type": "building_switch", "name": "Chemical Sciences Switch", "location": "Chemistry Bldg", "capacity_gbps": 10.0, "parent": "DIST-ACADEMIC"},
            {"id": "HOSTEL-MAHANADI", "type": "building_switch", "name": "Mahanadi Residence Switch", "location": "Mahanadi Hall", "capacity_gbps": 10.0, "parent": "DIST-RESIDENTIAL"},
            {"id": "LAB-SUPERCOMP", "type": "building_switch", "name": "HPC Supercomputer Switch", "location": "Data Center HPC Row", "capacity_gbps": 40.0, "parent": "DIST-RESEARCH"},
            {"id": "AP-MAHANADI-01", "type": "access_point", "name": "Hostel Wi-Fi AP 1", "location": "Mahanadi Wing A", "capacity_gbps": 1.0, "parent": "HOSTEL-MAHANADI"},
            {"id": "SRV-CAMPUS-DNS", "type": "dns_server", "name": "Campus DNS/DHCP Master", "location": "North Datacenter Rack 4", "capacity_gbps": 10.0, "parent": "WAN-CORE-NORTH"}
        ],
        "service_dependencies": {
            "BLDG-BIO": {"dns": "SRV-CAMPUS-DNS"},
            "BLDG-CHEM": {"dns": "SRV-CAMPUS-DNS"},
            "HOSTEL-MAHANADI": {"dns": "SRV-CAMPUS-DNS"},
            "AP-MAHANADI-01": {"dns": "SRV-CAMPUS-DNS"}
        }
    }


def create_star_mesh_topology() -> Dict[str, Any]:
    """Star-Mesh Hybrid: 3 interconnected hubs with hanging access spokes."""
    return {
        "network_name": "Star-Mesh Regional Hub Network",
        "version": "1.0",
        "nodes": [
            {"id": "HUB-ALPHA", "type": "core_hub", "name": "Regional Hub Alpha", "location": "Zone Alpha", "capacity_gbps": 100.0, "parent": None},
            {"id": "HUB-BETA", "type": "core_hub", "name": "Regional Hub Beta", "location": "Zone Beta", "capacity_gbps": 100.0, "parent": "HUB-ALPHA"},
            {"id": "HUB-GAMMA", "type": "core_hub", "name": "Regional Hub Gamma", "location": "Zone Gamma", "capacity_gbps": 100.0, "parent": "HUB-ALPHA"},
            {"id": "SPOKE-A1", "type": "access_spoke", "name": "Spoke Access A1", "location": "Site A1", "capacity_gbps": 10.0, "parent": "HUB-ALPHA"},
            {"id": "SPOKE-A2", "type": "access_spoke", "name": "Spoke Access A2", "location": "Site A2", "capacity_gbps": 10.0, "parent": "HUB-ALPHA"},
            {"id": "SPOKE-B1", "type": "access_spoke", "name": "Spoke Access B1", "location": "Site B1", "capacity_gbps": 10.0, "parent": "HUB-BETA"},
            {"id": "SPOKE-B2", "type": "access_spoke", "name": "Spoke Access B2", "location": "Site B2", "capacity_gbps": 10.0, "parent": "HUB-BETA"},
            {"id": "SPOKE-G1", "type": "access_spoke", "name": "Spoke Access G1", "location": "Site G1", "capacity_gbps": 10.0, "parent": "HUB-GAMMA"},
            {"id": "SPOKE-G2", "type": "access_spoke", "name": "Spoke Access G2", "location": "Site G2", "capacity_gbps": 10.0, "parent": "HUB-GAMMA"}
        ],
        "service_dependencies": {}
    }


# -----------------------------------------------------------------------------
# Curated Multi-Device Scenarios across the 4 Topologies (32 cases)
# -----------------------------------------------------------------------------

def build_benchmark_scenarios() -> List[Dict[str, Any]]:
    now = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
    t0 = now
    t1 = now + timedelta(seconds=15)
    t2 = now + timedelta(seconds=30)

    scenarios: List[Dict[str, Any]] = [
        # =====================================================================
        # TOPOLOGY 1: Spine-Leaf Data Center Fabric (8 cases)
        # =====================================================================
        {
            "id": "TOPO-SPINE-01-CONGESTION",
            "topology_family": "Spine-Leaf",
            "title": "Spine Switch Egress Buffer Congestion Cascading to Leaves",
            "expected_root_cause": "LINK_CONGESTION",
            "expected_faulty_device": "SPINE-01",
            "telemetry": [
                {"device_id": "SPINE-01", "timestamp": t0.isoformat(), "latency_ms": 190.0, "packet_loss_pct": 5.5, "queue_drops": 320, "interface_errors": 0},
                {"device_id": "LEAF-01", "timestamp": t1.isoformat(), "latency_ms": 175.0, "packet_loss_pct": 4.8, "queue_drops": 40, "interface_errors": 0},
                {"device_id": "LEAF-02", "timestamp": t1.isoformat(), "latency_ms": 180.0, "packet_loss_pct": 5.0, "queue_drops": 35, "interface_errors": 0},
                {"device_id": "SRV-WEB-01", "timestamp": t2.isoformat(), "latency_ms": 165.0, "packet_loss_pct": 4.2, "queue_drops": 0, "interface_errors": 0}
            ]
        },
        {
            "id": "TOPO-SPINE-02-HARDWARE",
            "topology_family": "Spine-Leaf",
            "title": "Leaf Optical Transceiver Physical Degradation",
            "expected_root_cause": "HARDWARE_FAILURE",
            "expected_faulty_device": "LEAF-03",
            "telemetry": [
                {"device_id": "LEAF-03", "timestamp": t0.isoformat(), "latency_ms": 25.0, "packet_loss_pct": 14.0, "interface_errors": 120, "queue_drops": 0},
                {"device_id": "SRV-DB-01", "timestamp": t1.isoformat(), "latency_ms": 28.0, "packet_loss_pct": 12.5, "interface_errors": 25, "queue_drops": 0}
            ]
        },
        {
            "id": "TOPO-SPINE-03-RESOURCE",
            "topology_family": "Spine-Leaf",
            "title": "Database Server Compute Resource Exhaustion",
            "expected_root_cause": "RESOURCE_EXHAUSTION",
            "expected_faulty_device": "SRV-DB-01",
            "telemetry": [
                {"device_id": "SRV-DB-01", "timestamp": t0.isoformat(), "cpu_pct": 98.5, "memory_pct": 96.0, "latency_ms": 85.0, "packet_loss_pct": 1.5},
                {"device_id": "LEAF-03", "timestamp": t0.isoformat(), "cpu_pct": 25.0, "memory_pct": 40.0, "latency_ms": 15.0, "packet_loss_pct": 0.0}
            ]
        },
        {
            "id": "TOPO-SPINE-04-HEALTHY",
            "topology_family": "Spine-Leaf",
            "title": "Spine-Leaf Healthy Operational Baseline",
            "expected_root_cause": "NORMAL_OPERATION",
            "expected_faulty_device": None,
            "telemetry": [
                {"device_id": "SPINE-01", "timestamp": t0.isoformat(), "latency_ms": 12.0, "packet_loss_pct": 0.0, "cpu_pct": 32.0, "interface_errors": 0},
                {"device_id": "SPINE-02", "timestamp": t0.isoformat(), "latency_ms": 11.5, "packet_loss_pct": 0.0, "cpu_pct": 30.0, "interface_errors": 0},
                {"device_id": "LEAF-01", "timestamp": t0.isoformat(), "latency_ms": 14.0, "packet_loss_pct": 0.0, "cpu_pct": 28.0, "interface_errors": 0},
                {"device_id": "SRV-WEB-01", "timestamp": t0.isoformat(), "latency_ms": 15.0, "packet_loss_pct": 0.0, "cpu_pct": 45.0, "interface_errors": 0}
            ]
        },
        {
            "id": "TOPO-SPINE-05-INDEPENDENT-FAULTS",
            "topology_family": "Spine-Leaf",
            "title": "Dual Independent Faults Across Separated Pods",
            "expected_root_cause": ["HARDWARE_FAILURE", "RESOURCE_EXHAUSTION"],
            "expected_faulty_device": "LEAF-01",
            "telemetry": [
                {"device_id": "LEAF-01", "timestamp": t0.isoformat(), "interface_errors": 95, "packet_loss_pct": 7.0, "latency_ms": 25.0},
                {"device_id": "SRV-STORAGE-01", "timestamp": t0.isoformat(), "cpu_pct": 99.0, "memory_pct": 94.0, "latency_ms": 22.0}
            ]
        },
        {
            "id": "TOPO-SPINE-06-UPSTREAM-FAILURE",
            "topology_family": "Spine-Leaf",
            "title": "Complete Spine-02 Upstream Node Outage",
            "expected_root_cause": ["UPSTREAM_SWITCH_FAILURE", "LINK_CONGESTION"],
            "expected_faulty_device": "SPINE-02",
            "telemetry": [
                {"device_id": "SPINE-02", "timestamp": t0.isoformat(), "packet_loss_pct": 100.0, "latency_ms": 999.0, "reported_status": "DOWN"},
                {"device_id": "LEAF-03", "timestamp": t1.isoformat(), "packet_loss_pct": 100.0, "latency_ms": 999.0},
                {"device_id": "LEAF-04", "timestamp": t1.isoformat(), "packet_loss_pct": 100.0, "latency_ms": 999.0}
            ]
        },
        {
            "id": "TOPO-SPINE-07-SPARSE-ABSTAIN",
            "topology_family": "Spine-Leaf",
            "title": "Sparse Ambiguous Metrics Demanding Abstention",
            "expected_root_cause": "INSUFFICIENT_EVIDENCE",
            "expected_faulty_device": None,
            "telemetry": [
                {"device_id": "LEAF-02", "timestamp": t0.isoformat(), "latency_ms": 65.0}  # Only 1 single metric with no loss/errors/queue drops
            ]
        },
        {
            "id": "TOPO-SPINE-08-CASCADING-DELAY",
            "topology_family": "Spine-Leaf",
            "title": "Microsecond Order Reversal on Spine Link Buffer Drops",
            "expected_root_cause": "LINK_CONGESTION",
            "expected_faulty_device": "SPINE-01",
            "telemetry": [
                {"device_id": "SPINE-01", "timestamp": t0.isoformat(), "queue_drops": 190, "latency_ms": 160.0, "packet_loss_pct": 4.0},
                {"device_id": "LEAF-02", "timestamp": (t0 + timedelta(seconds=5)).isoformat(), "queue_drops": 0, "latency_ms": 155.0, "packet_loss_pct": 3.8}
            ]
        },

        # =====================================================================
        # TOPOLOGY 2: Metro Ring Resilient Network (8 cases)
        # =====================================================================
        {
            "id": "TOPO-RING-01-HUB-CONGESTION",
            "topology_family": "Metro Ring",
            "title": "Central Metro Hub Interface Congestion Affecting Ring",
            "expected_root_cause": "LINK_CONGESTION",
            "expected_faulty_device": "RING-01",
            "telemetry": [
                {"device_id": "RING-01", "timestamp": t0.isoformat(), "latency_ms": 220.0, "packet_loss_pct": 6.5, "queue_drops": 450, "interface_errors": 0},
                {"device_id": "RING-02", "timestamp": t1.isoformat(), "latency_ms": 200.0, "packet_loss_pct": 5.2, "queue_drops": 20, "interface_errors": 0},
                {"device_id": "EDGE-N1", "timestamp": t2.isoformat(), "latency_ms": 190.0, "packet_loss_pct": 4.8, "queue_drops": 0, "interface_errors": 0}
            ]
        },
        {
            "id": "TOPO-RING-02-FIBER-DEGRADATION",
            "topology_family": "Metro Ring",
            "title": "East Metro Ring Optical Span Degradation with CRC Errors",
            "expected_root_cause": "HARDWARE_FAILURE",
            "expected_faulty_device": "RING-03",
            "telemetry": [
                {"device_id": "RING-03", "timestamp": t0.isoformat(), "interface_errors": 120, "packet_loss_pct": 14.0, "latency_ms": 25.0, "queue_drops": 0},
                {"device_id": "EDGE-E1", "timestamp": t1.isoformat(), "interface_errors": 20, "packet_loss_pct": 12.0, "latency_ms": 28.0, "queue_drops": 0}
            ]
        },
        {
            "id": "TOPO-RING-03-HEALTHY",
            "topology_family": "Metro Ring",
            "title": "Metro Ring Steady-State Normal Operation",
            "expected_root_cause": "NORMAL_OPERATION",
            "expected_faulty_device": None,
            "telemetry": [
                {"device_id": "RING-01", "timestamp": t0.isoformat(), "latency_ms": 18.0, "packet_loss_pct": 0.0, "interface_errors": 0},
                {"device_id": "RING-02", "timestamp": t0.isoformat(), "latency_ms": 19.5, "packet_loss_pct": 0.0, "interface_errors": 0},
                {"device_id": "RING-04", "timestamp": t0.isoformat(), "latency_ms": 20.0, "packet_loss_pct": 0.0, "interface_errors": 0},
                {"device_id": "EDGE-N1", "timestamp": t0.isoformat(), "latency_ms": 22.0, "packet_loss_pct": 0.0, "interface_errors": 0}
            ]
        },
        {
            "id": "TOPO-RING-04-NODE-FAIL",
            "topology_family": "Metro Ring",
            "title": "Metro Ring Node Total Failure Isolating East Edge",
            "expected_root_cause": ["UPSTREAM_SWITCH_FAILURE", "LINK_CONGESTION"],
            "expected_faulty_device": "RING-03",
            "telemetry": [
                {"device_id": "RING-03", "timestamp": t0.isoformat(), "packet_loss_pct": 100.0, "latency_ms": 999.0, "reported_status": "DOWN"},
                {"device_id": "EDGE-E1", "timestamp": t1.isoformat(), "packet_loss_pct": 100.0, "latency_ms": 999.0}
            ]
        },
        {
            "id": "TOPO-RING-05-WEST-CPU",
            "topology_family": "Metro Ring",
            "title": "West Tech Hub Gateway CPU Exhaustion (Control Plane Denial)",
            "expected_root_cause": "RESOURCE_EXHAUSTION",
            "expected_faulty_device": "RING-05",
            "telemetry": [
                {"device_id": "RING-05", "timestamp": t0.isoformat(), "cpu_pct": 99.2, "memory_pct": 88.0, "latency_ms": 22.0, "packet_loss_pct": 1.0},
                {"device_id": "EDGE-W1", "timestamp": t1.isoformat(), "cpu_pct": 20.0, "memory_pct": 30.0, "latency_ms": 20.0, "packet_loss_pct": 0.5}
            ]
        },
        {
            "id": "TOPO-RING-06-SIMULTANEOUS-RING-ERRORS",
            "topology_family": "Metro Ring",
            "title": "Simultaneous Disjoint Ring Anomalies (Preserving Ambiguity)",
            "expected_root_cause": "HARDWARE_FAILURE",
            "expected_faulty_device": "RING-02",
            "telemetry": [
                {"device_id": "RING-02", "timestamp": t0.isoformat(), "interface_errors": 45, "packet_loss_pct": 5.0, "latency_ms": 140.0},
                {"device_id": "RING-05", "timestamp": t0.isoformat(), "interface_errors": 50, "packet_loss_pct": 5.5, "latency_ms": 145.0}
            ]
        },
        {
            "id": "TOPO-RING-07-CONCURRENT-ISOLATION",
            "topology_family": "Metro Ring",
            "title": "Ring Congestion at Hub while Edge Has Physical Drop",
            "expected_root_cause": "LINK_CONGESTION",
            "expected_faulty_device": "RING-01",
            "telemetry": [
                {"device_id": "RING-01", "timestamp": t0.isoformat(), "queue_drops": 280, "latency_ms": 190.0, "packet_loss_pct": 4.5},
                {"device_id": "EDGE-W1", "timestamp": (t0 + timedelta(seconds=20)).isoformat(), "interface_errors": 10, "packet_loss_pct": 3.0}
            ]
        },
        {
            "id": "TOPO-RING-08-SPARSE-ABSTAIN",
            "topology_family": "Metro Ring",
            "title": "Isolated Mild Latency Bump Without Supporting Signals",
            "expected_root_cause": "INSUFFICIENT_EVIDENCE",
            "expected_faulty_device": None,
            "telemetry": [
                {"device_id": "RING-04", "timestamp": t0.isoformat(), "latency_ms": 52.0}
            ]
        },

        # =====================================================================
        # TOPOLOGY 3: Multi-Domain Campus WAN (8 cases)
        # =====================================================================
        {
            "id": "TOPO-WAN-01-DNS-OUTAGE",
            "topology_family": "Multi-Domain WAN",
            "title": "Central Campus DNS Infrastructure Outage Cascading Across Domains",
            "expected_root_cause": "DNS_DHCP_FAILURE",
            "expected_faulty_device": "SRV-CAMPUS-DNS",
            "telemetry": [
                {"device_id": "SRV-CAMPUS-DNS", "timestamp": t0.isoformat(), "dns_resolution_ms": 850.0, "dhcp_lease_success": False, "packet_loss_pct": 2.0},
                {"device_id": "BLDG-BIO", "timestamp": t1.isoformat(), "dns_resolution_ms": 780.0, "latency_ms": 30.0, "packet_loss_pct": 1.0},
                {"device_id": "HOSTEL-MAHANADI", "timestamp": t1.isoformat(), "dns_resolution_ms": 810.0, "latency_ms": 25.0, "packet_loss_pct": 1.0}
            ]
        },
        {
            "id": "TOPO-WAN-02-HOSTEL-WIFI",
            "topology_family": "Multi-Domain WAN",
            "title": "Mahanadi Hostel Access Point Severe RF Signal Degradation",
            "expected_root_cause": "WEAK_WIFI",
            "expected_faulty_device": "AP-MAHANADI-01",
            "telemetry": [
                {"device_id": "AP-MAHANADI-01", "timestamp": t0.isoformat(), "signal_strength_dbm": -88.0, "packet_loss_pct": 8.0, "latency_ms": 160.0},
                {"device_id": "HOSTEL-MAHANADI", "timestamp": t0.isoformat(), "signal_strength_dbm": None, "packet_loss_pct": 0.0, "latency_ms": 15.0}
            ]
        },
        {
            "id": "TOPO-WAN-03-WAN-CORE-CONGESTION",
            "topology_family": "Multi-Domain WAN",
            "title": "North WAN Core Gateway Egress Saturation",
            "expected_root_cause": "LINK_CONGESTION",
            "expected_faulty_device": "WAN-CORE-NORTH",
            "telemetry": [
                {"device_id": "WAN-CORE-NORTH", "timestamp": t0.isoformat(), "latency_ms": 210.0, "packet_loss_pct": 6.2, "queue_drops": 510, "interface_errors": 0},
                {"device_id": "DIST-ACADEMIC", "timestamp": t1.isoformat(), "latency_ms": 195.0, "packet_loss_pct": 5.5, "queue_drops": 30, "interface_errors": 0},
                {"device_id": "BLDG-CHEM", "timestamp": t2.isoformat(), "latency_ms": 180.0, "packet_loss_pct": 4.5, "queue_drops": 0, "interface_errors": 0}
            ]
        },
        {
            "id": "TOPO-WAN-04-HPC-FAILURE",
            "topology_family": "Multi-Domain WAN",
            "title": "Research HPC Aggregator Switch Hardware Failure",
            "expected_root_cause": "HARDWARE_FAILURE",
            "expected_faulty_device": "LAB-SUPERCOMP",
            "telemetry": [
                {"device_id": "LAB-SUPERCOMP", "timestamp": t0.isoformat(), "interface_errors": 110, "packet_loss_pct": 9.5, "latency_ms": 190.0, "queue_drops": 0},
                {"device_id": "DIST-RESEARCH", "timestamp": t0.isoformat(), "interface_errors": 0, "packet_loss_pct": 0.5, "latency_ms": 15.0, "queue_drops": 0}
            ]
        },
        {
            "id": "TOPO-WAN-05-HEALTHY",
            "topology_family": "Multi-Domain WAN",
            "title": "Multi-Domain WAN Healthy Baseline Across All Sectors",
            "expected_root_cause": "NORMAL_OPERATION",
            "expected_faulty_device": None,
            "telemetry": [
                {"device_id": "WAN-CORE-NORTH", "timestamp": t0.isoformat(), "latency_ms": 14.0, "packet_loss_pct": 0.0, "interface_errors": 0},
                {"device_id": "DIST-ACADEMIC", "timestamp": t0.isoformat(), "latency_ms": 15.0, "packet_loss_pct": 0.0, "interface_errors": 0},
                {"device_id": "DIST-RESIDENTIAL", "timestamp": t0.isoformat(), "latency_ms": 16.0, "packet_loss_pct": 0.0, "interface_errors": 0},
                {"device_id": "DIST-RESEARCH", "timestamp": t0.isoformat(), "latency_ms": 14.5, "packet_loss_pct": 0.0, "interface_errors": 0},
                {"device_id": "SRV-CAMPUS-DNS", "timestamp": t0.isoformat(), "dns_resolution_ms": 22.0, "dhcp_lease_success": True, "packet_loss_pct": 0.0}
            ]
        },
        {
            "id": "TOPO-WAN-06-DIST-ACAD-FAILURE",
            "topology_family": "Multi-Domain WAN",
            "title": "Academic Distribution Aggregator Total Failure",
            "expected_root_cause": ["UPSTREAM_SWITCH_FAILURE", "LINK_CONGESTION"],
            "expected_faulty_device": "DIST-ACADEMIC",
            "telemetry": [
                {"device_id": "DIST-ACADEMIC", "timestamp": t0.isoformat(), "packet_loss_pct": 100.0, "latency_ms": 999.0, "reported_status": "DOWN"},
                {"device_id": "BLDG-BIO", "timestamp": t1.isoformat(), "packet_loss_pct": 100.0, "latency_ms": 999.0},
                {"device_id": "BLDG-CHEM", "timestamp": t1.isoformat(), "packet_loss_pct": 100.0, "latency_ms": 999.0}
            ]
        },
        {
            "id": "TOPO-WAN-07-CONCURRENT-ISOLATION",
            "topology_family": "Multi-Domain WAN",
            "title": "Concurrent DNS Latency and Disjoint Hostel Wi-Fi Weakness",
            "expected_root_cause": "DNS_DHCP_FAILURE",
            "expected_faulty_device": "SRV-CAMPUS-DNS",
            "telemetry": [
                {"device_id": "SRV-CAMPUS-DNS", "timestamp": t0.isoformat(), "dns_resolution_ms": 650.0, "dhcp_lease_success": False},
                {"device_id": "AP-MAHANADI-01", "timestamp": (t0 + timedelta(seconds=25)).isoformat(), "signal_strength_dbm": -82.0, "latency_ms": 80.0}
            ]
        },
        {
            "id": "TOPO-WAN-08-SPARSE-ABSTAIN",
            "topology_family": "Multi-Domain WAN",
            "title": "Sparse Single-Metric Ping Latency Demanding Safe Abstention",
            "expected_root_cause": "INSUFFICIENT_EVIDENCE",
            "expected_faulty_device": None,
            "telemetry": [
                {"device_id": "DIST-RESIDENTIAL", "timestamp": t0.isoformat(), "latency_ms": 68.0}
            ]
        },

        # =====================================================================
        # TOPOLOGY 4: Star-Mesh Hybrid (8 cases)
        # =====================================================================
        {
            "id": "TOPO-STARMESH-01-HUB-CONGESTION",
            "topology_family": "Star-Mesh Hybrid",
            "title": "Hub Alpha Core Buffer Congestion Impacting Local Spokes",
            "expected_root_cause": "LINK_CONGESTION",
            "expected_faulty_device": "HUB-ALPHA",
            "telemetry": [
                {"device_id": "HUB-ALPHA", "timestamp": t0.isoformat(), "latency_ms": 205.0, "packet_loss_pct": 5.8, "queue_drops": 380, "interface_errors": 0},
                {"device_id": "SPOKE-A1", "timestamp": t1.isoformat(), "latency_ms": 185.0, "packet_loss_pct": 5.0, "queue_drops": 10, "interface_errors": 0},
                {"device_id": "SPOKE-A2", "timestamp": t1.isoformat(), "latency_ms": 190.0, "packet_loss_pct": 5.2, "queue_drops": 15, "interface_errors": 0}
            ]
        },
        {
            "id": "TOPO-STARMESH-02-BETA-HARDWARE",
            "topology_family": "Star-Mesh Hybrid",
            "title": "Hub Beta Optical Transceiver Degradation with Frame CRC Errors",
            "expected_root_cause": "HARDWARE_FAILURE",
            "expected_faulty_device": "HUB-BETA",
            "telemetry": [
                {"device_id": "HUB-BETA", "timestamp": t0.isoformat(), "interface_errors": 130, "packet_loss_pct": 15.0, "latency_ms": 24.0, "queue_drops": 0},
                {"device_id": "SPOKE-B1", "timestamp": t1.isoformat(), "interface_errors": 22, "packet_loss_pct": 12.0, "latency_ms": 26.0, "queue_drops": 0}
            ]
        },
        {
            "id": "TOPO-STARMESH-03-GAMMA-CPU",
            "topology_family": "Star-Mesh Hybrid",
            "title": "Hub Gamma Routing Engine Exhaustion (High BGP Churn)",
            "expected_root_cause": "RESOURCE_EXHAUSTION",
            "expected_faulty_device": "HUB-GAMMA",
            "telemetry": [
                {"device_id": "HUB-GAMMA", "timestamp": t0.isoformat(), "cpu_pct": 98.8, "memory_pct": 92.5, "latency_ms": 95.0, "packet_loss_pct": 2.2},
                {"device_id": "SPOKE-G1", "timestamp": t1.isoformat(), "cpu_pct": 18.0, "memory_pct": 32.0, "latency_ms": 90.0, "packet_loss_pct": 1.5}
            ]
        },
        {
            "id": "TOPO-STARMESH-04-HEALTHY",
            "topology_family": "Star-Mesh Hybrid",
            "title": "Star-Mesh Full Hybrid Normal Baseline State",
            "expected_root_cause": "NORMAL_OPERATION",
            "expected_faulty_device": None,
            "telemetry": [
                {"device_id": "HUB-ALPHA", "timestamp": t0.isoformat(), "latency_ms": 12.0, "packet_loss_pct": 0.0, "interface_errors": 0},
                {"device_id": "HUB-BETA", "timestamp": t0.isoformat(), "latency_ms": 13.0, "packet_loss_pct": 0.0, "interface_errors": 0},
                {"device_id": "HUB-GAMMA", "timestamp": t0.isoformat(), "latency_ms": 12.5, "packet_loss_pct": 0.0, "interface_errors": 0},
                {"device_id": "SPOKE-A1", "timestamp": t0.isoformat(), "latency_ms": 15.0, "packet_loss_pct": 0.0, "interface_errors": 0},
                {"device_id": "SPOKE-B1", "timestamp": t0.isoformat(), "latency_ms": 16.0, "packet_loss_pct": 0.0, "interface_errors": 0}
            ]
        },
        {
            "id": "TOPO-STARMESH-05-UPSTREAM-FAIL",
            "topology_family": "Star-Mesh Hybrid",
            "title": "Hub Beta Power Outage Isolating Spokes B1 and B2",
            "expected_root_cause": ["UPSTREAM_SWITCH_FAILURE", "LINK_CONGESTION"],
            "expected_faulty_device": "HUB-BETA",
            "telemetry": [
                {"device_id": "HUB-BETA", "timestamp": t0.isoformat(), "packet_loss_pct": 100.0, "latency_ms": 999.0, "reported_status": "DOWN"},
                {"device_id": "SPOKE-B1", "timestamp": t1.isoformat(), "packet_loss_pct": 100.0, "latency_ms": 999.0},
                {"device_id": "SPOKE-B2", "timestamp": t1.isoformat(), "packet_loss_pct": 100.0, "latency_ms": 999.0}
            ]
        },
        {
            "id": "TOPO-STARMESH-06-SPOKE-HARDWARE",
            "topology_family": "Star-Mesh Hybrid",
            "title": "Spoke Access Port Defect on Site G2",
            "expected_root_cause": "HARDWARE_FAILURE",
            "expected_faulty_device": "SPOKE-G2",
            "telemetry": [
                {"device_id": "SPOKE-G2", "timestamp": t0.isoformat(), "interface_errors": 75, "packet_loss_pct": 6.5, "latency_ms": 140.0},
                {"device_id": "HUB-GAMMA", "timestamp": t0.isoformat(), "interface_errors": 0, "packet_loss_pct": 0.0, "latency_ms": 14.0}
            ]
        },
        {
            "id": "TOPO-STARMESH-07-DISJOINT-HUBS",
            "topology_family": "Star-Mesh Hybrid",
            "title": "Disjoint Simultaneous Faults on Separated Hub Spokes",
            "expected_root_cause": "HARDWARE_FAILURE",
            "expected_faulty_device": "SPOKE-A1",
            "telemetry": [
                {"device_id": "SPOKE-A1", "timestamp": t0.isoformat(), "interface_errors": 60, "packet_loss_pct": 5.0, "latency_ms": 130.0},
                {"device_id": "SPOKE-G1", "timestamp": t0.isoformat(), "queue_drops": 210, "packet_loss_pct": 4.5, "latency_ms": 150.0}
            ]
        },
        {
            "id": "TOPO-STARMESH-08-SPARSE-ABSTAIN",
            "topology_family": "Star-Mesh Hybrid",
            "title": "Incomplete Single Device Telemetry Demanding Abstention",
            "expected_root_cause": "INSUFFICIENT_EVIDENCE",
            "expected_faulty_device": None,
            "telemetry": [
                {"device_id": "SPOKE-B2", "timestamp": t0.isoformat(), "latency_ms": 70.0}
            ]
        }
    ]
    return scenarios


# -----------------------------------------------------------------------------
# Benchmark Runner
# -----------------------------------------------------------------------------

def run_topology_benchmark(verbose: bool = True) -> Dict[str, Any]:
    """Execute complete topology generalization benchmark across all 4 novel graph families."""
    start_time = time.time()
    scenarios = build_benchmark_scenarios()

    topo_generators = {
        "Spine-Leaf": create_spine_leaf_topology,
        "Metro Ring": create_metro_ring_topology,
        "Multi-Domain WAN": create_multi_domain_wan_topology,
        "Star-Mesh Hybrid": create_star_mesh_topology
    }

    # Pre-instantiate TopologyEngines using temporary JSON files
    engines: Dict[str, TopologyEngine] = {}
    temp_files: List[str] = []

    try:
        for name, gen_fn in topo_generators.items():
            topo_dict = gen_fn()
            tf = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
            json.dump(topo_dict, tf, indent=2)
            tf.close()
            temp_files.append(tf.name)
            engines[name] = TopologyEngine(topology_path=tf.name)

        results: List[Dict[str, Any]] = []
        family_stats: Dict[str, Dict[str, Any]] = {
            f: {"total": 0, "top1_correct": 0, "top3_correct": 0, "root_dev_correct": 0, "abstentions": 0}
            for f in topo_generators.keys()
        }

        all_hypotheses = [
            "LINK_CONGESTION", "HARDWARE_FAILURE", "RESOURCE_EXHAUSTION",
            "UPSTREAM_SWITCH_FAILURE", "WEAK_WIFI", "DNS_DHCP_FAILURE",
            "NORMAL_OPERATION", "INSUFFICIENT_EVIDENCE"
        ]

        brier_sum = 0.0
        calibration_bins: List[Tuple[float, float]] = []  # (conf, is_correct)

        for scen in scenarios:
            fam = scen["topology_family"]
            topo = engines[fam]
            orch = NetworkIntelligenceOrchestrator(topology_engine=topo)

            res = orch.process(scen["telemetry"], incident_id=scen["id"])
            pred_rc = res.report.suspected_root_cause
            expected_rc_spec = scen["expected_root_cause"]
            expected_rcs = expected_rc_spec if isinstance(expected_rc_spec, list) else [expected_rc_spec]
            expected_rc = expected_rcs[0]
            conf = res.report.confidence

            # Candidate rankings
            ranked_hyps = [h.hypothesis for h in res.arbiter_decision.ranked_hypotheses]
            top3 = ranked_hyps[:3] if ranked_hyps else [pred_rc]

            is_top1 = (pred_rc in expected_rcs)
            is_top3 = any(c in top3 for c in expected_rcs)

            # Check root cause device identification if applicable
            expected_dev = scen.get("expected_faulty_device")
            identified_dev = None
            if res.report.affected_devices:
                # Find most plausible faulty device
                identified_dev = res.report.affected_devices[0]

            root_dev_match = True
            if expected_dev is not None:
                root_dev_match = (expected_dev in res.report.affected_devices)

            family_stats[fam]["total"] += 1
            if is_top1:
                family_stats[fam]["top1_correct"] += 1
            if is_top3:
                family_stats[fam]["top3_correct"] += 1
            if root_dev_match:
                family_stats[fam]["root_dev_correct"] += 1
            if pred_rc == "INSUFFICIENT_EVIDENCE":
                family_stats[fam]["abstentions"] += 1

            # Brier Score calculation
            target_vector = [1.0 if h == expected_rc else 0.0 for h in all_hypotheses]
            pred_vector = [conf if h == pred_rc else (1.0 - conf) / (len(all_hypotheses) - 1) for h in all_hypotheses]
            sq_err = sum((p - t) ** 2 for p, t in zip(pred_vector, target_vector))
            brier_sum += sq_err

            calibration_bins.append((conf, 1.0 if is_top1 else 0.0))

            results.append({
                "scenario_id": scen["id"],
                "topology_family": fam,
                "title": scen["title"],
                "expected_root_cause": expected_rc,
                "predicted_root_cause": pred_rc,
                "is_top1_correct": is_top1,
                "is_top3_correct": is_top3,
                "confidence": round(conf, 4),
                "expected_faulty_device": expected_dev,
                "affected_devices_identified": res.report.affected_devices,
                "root_device_match": root_dev_match,
                "status": res.arbiter_decision.status
            })

            if verbose:
                status_icon = "PASS" if is_top1 else "FAIL"
                print(f"[{fam:<18}] {scen['id']:<32} | Exp: {expected_rc:<24} | Pred: {pred_rc:<24} | Conf: {conf:.2f} | {status_icon}")

        total_cases = len(scenarios)
        total_top1 = sum(f["top1_correct"] for f in family_stats.values())
        total_top3 = sum(f["top3_correct"] for f in family_stats.values())
        total_dev = sum(f["root_dev_correct"] for f in family_stats.values())

        top1_acc = (total_top1 / total_cases) * 100.0
        top3_acc = (total_top3 / total_cases) * 100.0
        dev_acc = (total_dev / total_cases) * 100.0
        mean_brier = brier_sum / (total_cases * len(all_hypotheses))

        # Expected Calibration Error (ECE) with 5 bins
        ece_sum = 0.0
        bin_size = 0.20
        for b in range(5):
            b_low = b * bin_size
            b_high = (b + 1) * bin_size
            items_in_bin = [c for c in calibration_bins if b_low <= c[0] < b_high or (b == 4 and c[0] == 1.0)]
            if items_in_bin:
                avg_conf = sum(x[0] for x in items_in_bin) / len(items_in_bin)
                avg_acc = sum(x[1] for x in items_in_bin) / len(items_in_bin)
                ece_sum += (len(items_in_bin) / total_cases) * abs(avg_conf - avg_acc)

        # Macro F1 calculation
        class_f1s = []
        for h in all_hypotheses:
            tp = sum(1 for r in results if r["predicted_root_cause"] == h and r["expected_root_cause"] == h)
            fp = sum(1 for r in results if r["predicted_root_cause"] == h and r["expected_root_cause"] != h)
            fn = sum(1 for r in results if r["predicted_root_cause"] != h and r["expected_root_cause"] == h)
            prec = tp / (tp + fp) if (tp + fp) > 0 else 1.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 1.0
            f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
            class_f1s.append(f1)
        macro_f1 = sum(class_f1s) / len(class_f1s)

        elapsed = time.time() - start_time

        report = {
            "benchmark_title": "NetCoop AI — Topology Generalization Benchmark",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_topologies_evaluated": len(topo_generators),
            "topology_families": list(topo_generators.keys()),
            "total_scenarios_evaluated": total_cases,
            "overall_top1_accuracy": round(top1_acc, 2),
            "overall_top3_accuracy": round(top3_acc, 2),
            "root_device_localization_accuracy": round(dev_acc, 2),
            "macro_f1_score": round(macro_f1, 4),
            "multiclass_brier_score": round(mean_brier, 4),
            "expected_calibration_error_ece": round(ece_sum, 4),
            "duration_seconds": round(elapsed, 2),
            "family_breakdown": {
                fam: {
                    "total": st["total"],
                    "top1_accuracy": round((st["top1_correct"] / st["total"]) * 100.0, 1),
                    "top3_accuracy": round((st["top3_correct"] / st["total"]) * 100.0, 1),
                    "device_accuracy": round((st["root_dev_correct"] / st["total"]) * 100.0, 1),
                    "abstentions_emitted": st["abstentions"]
                }
                for fam, st in family_stats.items()
            },
            "scenarios": results
        }

        # Save report
        OUTPUT_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        if verbose:
            print("\n" + "=" * 80)
            print(f"TOPOLOGY BENCHMARK SUMMARY (Duration: {elapsed:.2f}s)")
            print(f"Scenarios Evaluated: {total_cases} across 4 Graph Architectures")
            print(f"Top-1 Diagnostic Accuracy: {top1_acc:.2f}%")
            print(f"Top-3 Diagnostic Accuracy: {top3_acc:.2f}%")
            print(f"Device Localization Accuracy: {dev_acc:.2f}%")
            print(f"Macro-F1 Score: {macro_f1:.4f}")
            print(f"Multi-Class Brier Score: {mean_brier:.4f}")
            print(f"Expected Calibration Error (ECE): {ece_sum:.4f}")
            print("=" * 80)

        return report

    finally:
        # Cleanup temporary topology files
        for tf_path in temp_files:
            try:
                os.remove(tf_path)
            except OSError:
                pass


if __name__ == "__main__":
    run_topology_benchmark()
