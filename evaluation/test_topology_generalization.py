"""Pytest Regression Suite for Network Topology Generalization.

Validates that NetCoop AI maintains high diagnostic fidelity across 4 unseen topologies:
1. Spine-Leaf (Clos data center fabric)
2. Metro Ring (Cyclic packet optical)
3. Multi-Domain WAN (Inter-campus distributed domains)
4. Star-Mesh Hybrid (Meshed core with access spokes)
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from evaluation.topology_benchmark import run_topology_benchmark

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_FILE = PROJECT_ROOT / "evaluation" / "topology_benchmark_report.json"


@pytest.fixture(scope="module")
def topology_report():
    """Run or load topology benchmark report."""
    if REPORT_FILE.exists():
        with open(REPORT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return run_topology_benchmark(verbose=False)


def test_topology_benchmark_volume_and_architectures(topology_report):
    """Assert benchmark covers 32 scenarios across 4 novel graph families."""
    assert topology_report["total_scenarios_evaluated"] == 32
    assert topology_report["total_topologies_evaluated"] == 4
    families = set(topology_report["topology_families"])
    assert families == {"Spine-Leaf", "Metro Ring", "Multi-Domain WAN", "Star-Mesh Hybrid"}


def test_topology_benchmark_accuracy_and_f1(topology_report):
    """Assert top-1 accuracy is >= 95% and macro F1 is >= 0.80."""
    assert topology_report["overall_top1_accuracy"] >= 95.0
    assert topology_report["macro_f1_score"] >= 0.80
    assert topology_report["root_device_localization_accuracy"] >= 95.0


def test_topology_benchmark_brier_and_calibration(topology_report):
    """Assert multiclass Brier score is <= 0.10."""
    assert topology_report["multiclass_brier_score"] <= 0.10


def test_topology_benchmark_family_breakdowns(topology_report):
    """Assert all 4 network topology families achieve >= 90% top-1 accuracy."""
    breakdown = topology_report["family_breakdown"]
    for fam_name in ["Spine-Leaf", "Metro Ring", "Multi-Domain WAN", "Star-Mesh Hybrid"]:
        fam = breakdown[fam_name]
        assert fam["total"] == 8
        assert fam["top1_accuracy"] >= 90.0
        assert fam["abstentions_emitted"] >= 1  # Graceful abstention on sparse cases
