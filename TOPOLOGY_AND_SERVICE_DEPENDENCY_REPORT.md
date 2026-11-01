# Campus Topology & Service Dependency — Engineering Report

## 1. Overview & Campus Network Model
NetCoop AI models the campus network of the **Indian Institute of Technology Bhubaneswar (IIT BBS)**, structured into a hierarchical four-tier topology:
1. **Campus Core Tier**: High-capacity core routing switches (`CORE-SW-01`, `CORE-SW-02`) interconnecting campus zones and upstream ISP gateways.
2. **Distribution / Aggregation Tier**: Regional distribution switches (`DIST-SW-NORTH`, `DIST-SW-SOUTH`, `DIST-SW-EAST`, `DIST-SW-WEST`).
3. **Building Access Tier**: Local building switches (`BLDG-SW-ENG`, `BLDG-SW-ADMIN`, `BLDG-SW-HOSTEL-01`, `BLDG-SW-LIBRARY`).
4. **Edge & Wireless Tier**: Dual-band IEEE 802.11ax Access Points (`AP-HOSTEL-1A`, `AP-LIBRARY-02`, etc.) and client endpoints.
5. **Central Services Tier**: Critical core infrastructure servers (`DNS-SRV-CORE`, `DHCP-SRV-01`, `RADIUS-AUTH-01`).

---

## 2. Graph Engine Implementation (`core/topology.py`)

The `TopologyEngine` provides deterministic graph queries:
- `get_upstream_path(device_id)`: Traverses parent links up to the core gateway.
- `get_downstream_devices(device_id)`: Computes the complete subtree affected by a failure (blast radius).
- `are_in_same_domain(dev_a, dev_b)`: Determines whether two devices share an upstream distribution bottleneck.
- `calculate_blast_radius(failed_device_id)`: Returns estimated affected client count, downstream switches, and dependent services.

---

## 3. Disjoint Root-Cause Discrimination

When faults occur simultaneously across disconnected branches (e.g. `BLDG-SW-ENG` buffer drops and `BLDG-SW-ADMIN` physical layer errors), the topology engine detects that their paths diverge immediately below the core:
$$\text{LCA}(\text{BLDG-SW-ENG}, \text{BLDG-SW-ADMIN}) = \text{CORE-SW-01}$$

Because `CORE-SW-01` exhibits nominal counters, the system correctly deduces that the anomalies are **independent disjoint incidents**, preventing incorrect aggregation under a single false hypothesis.

---

## 4. Verification Evidence

- Pre-loaded campus topology JSON (`data/topology.json`) fully validated.
- Tested across `test_scenarios.py` (all 15 scenarios), `test_end_to_end_scenarios.py` (Scenario 9, Scenario 20), and `test_multi_incident_clustering.py` (7 tests).
