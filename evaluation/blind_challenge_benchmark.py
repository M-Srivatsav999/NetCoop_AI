"""Blind Challenge Benchmark Runner for NetCoop AI.

Executes an independent diagnostic evaluation against the 32 hand-crafted blind challenge scenarios
in data/blind_challenge_dataset.json without relying on synthetic generation templates.

Computes:
1. Top-1 and Top-3 Diagnostic Accuracy
2. Per-Class Confusion Matrix, FPR, FNR, Precision, Recall, F1-score
3. Multi-Incident Clustering Precision, Recall, and F1-score
4. Multiclass Brier Score and Expected Calibration Error (ECE)
5. Epistemic Abstention Quality (Precision & Recall for Insufficient Evidence)
6. Latency Distribution (Mean, Median, P95, Max)
"""

from __future__ import annotations

import json
import math
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.confidence_engine import ConfidenceEngine
from core.orchestrator import NetworkIntelligenceOrchestrator
from protocol.models import HypothesisType

DATA_FILE = PROJECT_ROOT / "data" / "blind_challenge_dataset.json"
REPORT_FILE = PROJECT_ROOT / "evaluation" / "blind_challenge_benchmark_report.json"
BLIND_REFERENCE_TIME = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)


class BlindChallengeBenchmarkRunner:
    """Evaluates the multi-agent diagnostic engine against blind challenge scenarios."""

    def __init__(self) -> None:
        self.orchestrator = NetworkIntelligenceOrchestrator()
        self.all_classes = [h.value for h in HypothesisType]

    def run_benchmark(self) -> Dict[str, Any]:
        """Execute evaluation over all 32 blind challenge scenarios."""
        if not DATA_FILE.exists():
            raise FileNotFoundError(f"Blind challenge dataset not found at {DATA_FILE}")

        with open(DATA_FILE, "r", encoding="utf-8") as f:
            cases = json.load(f)

        total_cases = len(cases)
        correct_top1 = 0
        correct_top3 = 0

        # Confusion matrix: confusion_matrix[ground_truth][predicted]
        confusion_matrix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        # Calibration tracking
        brier_sum = 0.0
        multiclass_brier_sum = 0.0
        calibration_bins: Dict[int, List[Tuple[float, int]]] = {i: [] for i in range(10)}
        per_class_calib_tracker: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "brier_sum": 0.0,
            "raw_conf_sum": 0.0,
            "calib_conf_sum": 0.0,
            "count": 0,
            "bins": {i: [] for i in range(10)}
        })
        calibration_provenance: List[Dict[str, Any]] = []

        # Abstention tracking
        expected_abstentions = 0
        actual_abstentions = 0
        correct_abstentions = 0

        # Multi-incident clustering tracking
        expected_multi_incidents = 0
        correctly_clustered_incidents = 0
        total_clusters_found = 0

        latencies_ms: List[float] = []

        for case in cases:
            case_id = case["case_id"]
            ground_truth = case["ground_truth_root_cause"]
            expected_abstention = case.get("expected_abstention", False)
            expected_clusters = case.get("expected_cluster_count", 1)
            secondary_causes = case.get("secondary_root_causes", [])

            if expected_abstention:
                expected_abstentions += 1

            # Execute diagnostic pipeline
            telemetry_json = json.dumps(case["telemetry_payload"])
            start_t = time.perf_counter()
            result = self.orchestrator.process(
                telemetry_json,
                incident_id=case_id,
                reference_time=BLIND_REFERENCE_TIME
            )
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            latencies_ms.append(elapsed_ms)

            report = result.report
            arb = result.arbitration_result
            predicted_root_cause = report.suspected_root_cause
            confidence = report.confidence

            # Build Top-3 list
            candidate_hypotheses = [predicted_root_cause]
            for alt in getattr(arb, "alternative_hypotheses", []):
                h_name = alt.get("hypothesis")
                if h_name and h_name not in candidate_hypotheses:
                    candidate_hypotheses.append(h_name)
            top3 = candidate_hypotheses[:3]

            # Top-1 Check
            is_top1 = (predicted_root_cause == ground_truth)
            if is_top1:
                correct_top1 += 1

            # Top-3 Check
            if ground_truth in top3:
                correct_top3 += 1

            # Update confusion matrix
            confusion_matrix[ground_truth][predicted_root_cause] += 1

            # Abstention checking
            is_actual_abstention = (
                predicted_root_cause == HypothesisType.INSUFFICIENT_EVIDENCE.value or
                report.status == "insufficient_evidence"
            )
            if is_actual_abstention:
                actual_abstentions += 1
                if expected_abstention:
                    correct_abstentions += 1

            # Calibration scoring (for diagnosed cases)
            if not expected_abstention:
                outcome = 1 if is_top1 else 0
                brier_sum += (confidence - outcome) ** 2

                # Multiclass Brier score
                for c in self.all_classes:
                    c_prob = confidence if c == predicted_root_cause else 0.0
                    c_outcome = 1.0 if c == ground_truth else 0.0
                    multiclass_brier_sum += (c_prob - c_outcome) ** 2

                # ECE binning (10 uniform bins [0.0, 0.1), ..., [0.9, 1.0])
                bin_idx = min(9, int(confidence * 10))
                calibration_bins[bin_idx].append((confidence, outcome))

                # Track per-class calibration metrics
                cls_tracker = per_class_calib_tracker[ground_truth]
                cls_tracker["count"] += 1
                cls_tracker["brier_sum"] += (confidence - outcome) ** 2
                cls_tracker["calib_conf_sum"] += confidence
                raw_c = arb.raw_heuristic_confidence if hasattr(arb, "raw_heuristic_confidence") else confidence
                cls_tracker["raw_conf_sum"] += raw_c
                cls_tracker["bins"][bin_idx].append((confidence, outcome))

                # Double-calibration guard verification:
                calib_eng = self.orchestrator.correlation_agent.confidence_engine
                idempotent_test = calib_eng.calibrate_confidence(confidence)
                calibration_provenance.append({
                    "case_id": case_id,
                    "ground_truth": ground_truth,
                    "raw_confidence": raw_c,
                    "calibrated_confidence": confidence,
                    "recalibration_value": idempotent_test,
                    "is_idempotent_guarded": (abs(idempotent_test - confidence) < 0.05),
                    "model_source": "persisted_isotonic_calibrator",
                    "timestamp": report.created_at.isoformat() if hasattr(report, "created_at") else None
                })

            # Multi-incident clustering evaluation
            if expected_clusters > 1:
                expected_multi_incidents += 1
                detected_clusters = len(result.incident_clusters) if hasattr(result, "incident_clusters") else 1
                total_clusters_found += detected_clusters
                if detected_clusters == expected_clusters:
                    correctly_clustered_incidents += 1
            else:
                total_clusters_found += 1

        diagnosed_cases_count = total_cases - expected_abstentions
        top1_accuracy = correct_top1 / total_cases if total_cases > 0 else 0.0
        top3_accuracy = correct_top3 / total_cases if total_cases > 0 else 0.0
        binary_brier = brier_sum / diagnosed_cases_count if diagnosed_cases_count > 0 else 0.0
        multiclass_brier = multiclass_brier_sum / (diagnosed_cases_count * len(self.all_classes)) if diagnosed_cases_count > 0 else 0.0

        # Compute ECE across uniform bins
        ece = 0.0
        bin_details = []
        for b_idx in range(10):
            samples = calibration_bins[b_idx]
            b_count = len(samples)
            if b_count > 0:
                avg_conf = sum(c for c, _ in samples) / b_count
                avg_acc = sum(o for _, o in samples) / b_count
                bin_err = abs(avg_acc - avg_conf)
                ece += (b_count / diagnosed_cases_count) * bin_err
                bin_details.append({
                    "bin_index": b_idx,
                    "range": f"[{b_idx*0.1:.1f}, {(b_idx+1)*0.1:.1f})",
                    "sample_count": b_count,
                    "average_confidence": round(avg_conf, 4),
                    "empirical_accuracy": round(avg_acc, 4),
                    "calibration_gap": round(bin_err, 4),
                    "bias_direction": "OVERCONFIDENT" if avg_conf > avg_acc else ("UNDERCONFIDENT" if avg_conf < avg_acc else "PERFECT")
                })
            else:
                bin_details.append({
                    "bin_index": b_idx,
                    "range": f"[{b_idx*0.1:.1f}, {(b_idx+1)*0.1:.1f})",
                    "sample_count": 0,
                    "average_confidence": 0.0,
                    "empirical_accuracy": 0.0,
                    "calibration_gap": 0.0,
                    "bias_direction": "EMPTY"
                })

        # Compute Per-Class Confusion, Precision, Recall, F1, FPR, FNR
        unique_classes = sorted(list(set(list(confusion_matrix.keys()) + [h.value for h in HypothesisType])))
        per_class_metrics: Dict[str, Dict[str, float]] = {}

        for c in unique_classes:
            tp = confusion_matrix[c][c]
            fn = sum(confusion_matrix[c][other] for other in unique_classes if other != c)
            fp = sum(confusion_matrix[other][c] for other in unique_classes if other != c)
            tn = sum(
                confusion_matrix[r][pred]
                for r in unique_classes if r != c
                for pred in unique_classes if pred != c
            )

            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
            fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
            fnr = fn / (fn + tp) if (fn + tp) > 0 else 0.0

            per_class_metrics[c] = {
                "TP": tp,
                "FP": fp,
                "FN": fn,
                "TN": tn,
                "Precision": round(precision, 4),
                "Recall": round(recall, 4),
                "F1_score": round(f1, 4),
                "FPR": round(fpr, 4),
                "FNR": round(fnr, 4),
            }

        # Multi-Incident Clustering Metrics
        clustering_precision = correctly_clustered_incidents / total_clusters_found if total_clusters_found > 0 else 1.0
        clustering_recall = correctly_clustered_incidents / expected_multi_incidents if expected_multi_incidents > 0 else 1.0
        clustering_f1 = (
            (2 * clustering_precision * clustering_recall) / (clustering_precision + clustering_recall)
            if (clustering_precision + clustering_recall) > 0 else 1.0
        )

        # Epistemic Abstention Quality
        abstention_precision = correct_abstentions / actual_abstentions if actual_abstentions > 0 else 1.0
        abstention_recall = correct_abstentions / expected_abstentions if expected_abstentions > 0 else 1.0
        abstention_f1 = (
            (2 * abstention_precision * abstention_recall) / (abstention_precision + abstention_recall)
            if (abstention_precision + abstention_recall) > 0 else 1.0
        )

        # Latency statistics
        latencies_ms.sort()
        n_lat = len(latencies_ms)
        mean_lat = sum(latencies_ms) / n_lat if n_lat > 0 else 0.0
        p50_lat = latencies_ms[int(n_lat * 0.50)] if n_lat > 0 else 0.0
        p95_lat = latencies_ms[int(n_lat * 0.95)] if n_lat > 0 else 0.0
        max_lat = latencies_ms[-1] if n_lat > 0 else 0.0

        # Construct final report dictionary
        report_data = {
            "evaluation_title": "NetCoop AI Blind Challenge Benchmark Evaluation",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_cases": total_cases,
            "accuracy": {
                "top1_accuracy": round(top1_accuracy, 4),
                "top3_accuracy": round(top3_accuracy, 4),
                "correct_top1_count": correct_top1,
                "correct_top3_count": correct_top3,
            },
            "calibration": {
                "binary_brier_score": round(binary_brier, 4),
                "multiclass_brier_score": round(multiclass_brier, 4),
                "expected_calibration_error_ece": round(ece, 4),
                "reliability_bins": bin_details,
                "double_calibration_guard_provenance": calibration_provenance[:5]
            },
            "clustering": {
                "expected_multi_incidents": expected_multi_incidents,
                "correctly_clustered_incidents": correctly_clustered_incidents,
                "clustering_precision": round(clustering_precision, 4),
                "clustering_recall": round(clustering_recall, 4),
                "clustering_f1_score": round(clustering_f1, 4),
            },
            "abstention_quality": {
                "expected_abstentions": expected_abstentions,
                "actual_abstentions": actual_abstentions,
                "correct_abstentions": correct_abstentions,
                "precision": round(abstention_precision, 4),
                "recall": round(abstention_recall, 4),
                "f1_score": round(abstention_f1, 4),
            },
            "latency_profile_ms": {
                "mean_ms": round(mean_lat, 2),
                "median_p50_ms": round(p50_lat, 2),
                "p95_ms": round(p95_lat, 2),
                "max_ms": round(max_lat, 2),
            },
            "per_class_metrics": per_class_metrics,
            "confusion_matrix": {k: dict(v) for k, v in confusion_matrix.items()},
        }

        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)

        return report_data


def print_summary(report: Dict[str, Any]) -> None:
    """Print clean terminal report table."""
    acc = report["accuracy"]
    cal = report["calibration"]
    abst = report["abstention_quality"]
    lat = report["latency_profile_ms"]

    print("\n" + "=" * 70)
    print("   NETCOOP AI — BLIND CHALLENGE BENCHMARK RESULTS (32 CASes)")
    print("=" * 70)
    print(f" Top-1 Diagnostic Accuracy : {acc['top1_accuracy'] * 100:.2f}% ({acc['correct_top1_count']}/{report['total_cases']})")
    print(f" Top-3 Diagnostic Accuracy : {acc['top3_accuracy'] * 100:.2f}% ({acc['correct_top3_count']}/{report['total_cases']})")
    print(f" Multiclass Brier Score    : {cal['multiclass_brier_score']:.4f}")
    print(f" Expected Calib Error (ECE): {cal['expected_calibration_error_ece']:.4f}")
    print(f" Abstention F1-Score       : {abst['f1_score']:.4f} (Recall: {abst['recall']*100:.1f}%)")
    print(f" Latency Mean / P95        : {lat['mean_ms']} ms / {lat['p95_ms']} ms")
    print("-" * 70)
    print(f"{'Fault Class':<26} | {'Prec':<7} | {'Recall':<7} | {'F1':<7} | {'FPR':<7}")
    print("-" * 70)
    for cls_name, m in report["per_class_metrics"].items():
        if m["TP"] + m["FN"] > 0:
            print(f"{cls_name:<26} | {m['Precision']:<7.3f} | {m['Recall']:<7.3f} | {m['F1_score']:<7.3f} | {m['FPR']:<7.3f}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    runner = BlindChallengeBenchmarkRunner()
    results = runner.run_benchmark()
    print_summary(results)
