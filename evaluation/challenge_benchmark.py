"""Independent Diagnostic Challenge Benchmark Harness for NetCoop AI.

Evaluates NetCoop AI against the 50 hand-crafted, non-templated challenge scenarios
in data/challenge_dataset.json, computing:
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

DATA_FILE = PROJECT_ROOT / "data" / "challenge_dataset.json"
REPORT_FILE = PROJECT_ROOT / "evaluation" / "challenge_benchmark_report.json"
CHALLENGE_REFERENCE_TIME = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)


class ChallengeBenchmarkRunner:
    """Evaluates the multi-agent diagnostic engine against curated challenge scenarios."""

    def __init__(self) -> None:
        self.orchestrator = NetworkIntelligenceOrchestrator()
        self.all_classes = [h.value for h in HypothesisType]

    def run_benchmark(self) -> Dict[str, Any]:
        """Execute evaluation over all 50 challenge scenarios."""
        if not DATA_FILE.exists():
            raise FileNotFoundError(f"Challenge dataset not found at {DATA_FILE}")

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
                reference_time=CHALLENGE_REFERENCE_TIME
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
            is_actual_abstention = (predicted_root_cause == HypothesisType.INSUFFICIENT_EVIDENCE.value or report.status == "insufficient_evidence")
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

                # Per-class calibration tracking
                c_item = per_class_calib_tracker[ground_truth]
                c_item["brier_sum"] += (confidence - outcome) ** 2
                c_item["raw_conf_sum"] += getattr(arb, "raw_confidence", confidence)
                c_item["calib_conf_sum"] += confidence
                c_item["count"] += 1
                c_item["bins"][bin_idx].append((confidence, outcome))

                # Raw vs calibrated check and double calibration verification
                raw_c = getattr(arb, "raw_confidence", confidence)
                double_cal_test = ConfidenceEngine.calibrate_confidence(confidence, is_already_calibrated=True)
                calibration_provenance.append({
                    "case_id": case_id,
                    "ground_truth": ground_truth,
                    "predicted": predicted_root_cause,
                    "raw_confidence": round(raw_c, 3),
                    "calibrated_confidence": round(confidence, 3),
                    "double_calibration_guarded": (double_cal_test == confidence),
                    "delta": round(confidence - raw_c, 3)
                })

            # Multi-incident clustering evaluation
            if expected_clusters > 1:
                expected_multi_incidents += 1
                found_incidents = getattr(report, "incidents", []) or getattr(arb, "co_occurring_incidents", [])
                total_clusters_found += len(found_incidents)

                all_expected_causes = {ground_truth} | set(secondary_causes)
                found_causes = {inc.root_cause for inc in found_incidents}
                # Check if all independent fault causes were identified in the partition
                if all_expected_causes.issubset(found_causes) and len(found_incidents) >= expected_clusters:
                    correctly_clustered_incidents += 1

        # Calculate Per-Class Metrics (Precision, Recall, F1, FPR, FNR)
        per_class_metrics: Dict[str, Dict[str, float]] = {}
        f1_scores: List[float] = []

        all_gt_classes = sorted(list({c["ground_truth_root_cause"] for c in cases}))
        for c in all_gt_classes:
            tp = confusion_matrix[c][c]
            fp = sum(confusion_matrix[other][c] for other in all_gt_classes if other != c)
            fn = sum(confusion_matrix[c][other] for other in all_gt_classes if other != c)
            tn = total_cases - (tp + fp + fn)

            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
            fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
            fnr = fn / (fn + tp) if (fn + tp) > 0 else 0.0

            per_class_metrics[c] = {
                "precision": round(prec, 4),
                "recall": round(rec, 4),
                "f1_score": round(f1, 4),
                "false_positive_rate": round(fpr, 4),
                "false_negative_rate": round(fnr, 4),
                "support": sum(confusion_matrix[c].values())
            }
            f1_scores.append(f1)

        macro_f1 = sum(f1_scores) / len(f1_scores) if f1_scores else 0.0
        accuracy_top1 = (correct_top1 / total_cases) * 100.0
        accuracy_top3 = (correct_top3 / total_cases) * 100.0

        diagnosed_cases = total_cases - expected_abstentions
        top_brier = brier_sum / diagnosed_cases if diagnosed_cases > 0 else 0.0
        mc_brier = multiclass_brier_sum / diagnosed_cases if diagnosed_cases > 0 else 0.0

        # Expected Calibration Error (ECE) and Detailed Reliability Bins
        ece = 0.0
        reliability_bins_list = []
        for b_idx in range(10):
            items = calibration_bins[b_idx]
            low = b_idx * 0.1
            high = (b_idx + 1) * 0.1
            if items:
                avg_conf = sum(x[0] for x in items) / len(items)
                avg_acc = sum(x[1] for x in items) / len(items)
                cal_err = abs(avg_acc - avg_conf)
                ece += (len(items) / diagnosed_cases) * cal_err
                bias = "UNDERCONFIDENT" if avg_acc > avg_conf else ("OVERCONFIDENT" if avg_conf > avg_acc else "PERFECT")
                reliability_bins_list.append({
                    "bin_index": b_idx,
                    "bin_range": f"[{low:.1f}, {high:.1f})",
                    "sample_count": len(items),
                    "mean_confidence": round(avg_conf, 4),
                    "observed_accuracy": round(avg_acc, 4),
                    "calibration_error": round(cal_err, 4),
                    "bias_direction": bias
                })
            else:
                reliability_bins_list.append({
                    "bin_index": b_idx,
                    "bin_range": f"[{low:.1f}, {high:.1f})",
                    "sample_count": 0,
                    "mean_confidence": 0.0,
                    "observed_accuracy": 0.0,
                    "calibration_error": 0.0,
                    "bias_direction": "EMPTY"
                })

        # Per-class calibration analysis
        per_class_calib_dict = {}
        for c_name, c_data in per_class_calib_tracker.items():
            if c_data["count"] > 0:
                c_brier = c_data["brier_sum"] / c_data["count"]
                c_raw_mean = c_data["raw_conf_sum"] / c_data["count"]
                c_cal_mean = c_data["calib_conf_sum"] / c_data["count"]
                c_ece = 0.0
                for b_i, b_items in c_data["bins"].items():
                    if b_items:
                        b_conf = sum(x[0] for x in b_items) / len(b_items)
                        b_acc = sum(x[1] for x in b_items) / len(b_items)
                        c_ece += (len(b_items) / c_data["count"]) * abs(b_acc - b_conf)
                per_class_calib_dict[c_name] = {
                    "sample_count": c_data["count"],
                    "class_brier_score": round(c_brier, 4),
                    "mean_raw_confidence": round(c_raw_mean, 4),
                    "mean_calibrated_confidence": round(c_cal_mean, 4),
                    "class_ece": round(c_ece, 4)
                }

        # Abstention metrics
        abstention_prec = correct_abstentions / actual_abstentions if actual_abstentions > 0 else 1.0
        abstention_rec = correct_abstentions / expected_abstentions if expected_abstentions > 0 else 1.0
        abstention_f1 = (2 * abstention_prec * abstention_rec) / (abstention_prec + abstention_rec) if (abstention_prec + abstention_rec) > 0 else 0.0

        # Multi-incident clustering metrics
        cluster_prec = correctly_clustered_incidents / (total_clusters_found / 2) if total_clusters_found > 0 else 1.0
        cluster_rec = correctly_clustered_incidents / expected_multi_incidents if expected_multi_incidents > 0 else 1.0
        cluster_f1 = (2 * cluster_prec * cluster_rec) / (cluster_prec + cluster_rec) if (cluster_prec + cluster_rec) > 0 else 0.0

        # Latency statistics
        sorted_lat = sorted(latencies_ms)
        p95_idx = int(math.ceil(0.95 * len(sorted_lat))) - 1

        report_summary = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "challenge_cases_evaluated": total_cases,
            "top1_accuracy_pct": round(accuracy_top1, 2),
            "top3_accuracy_pct": round(accuracy_top3, 2),
            "macro_f1_score": round(macro_f1, 4),
            "top_label_brier_score": round(top_brier, 4),
            "multiclass_brier_score": round(mc_brier, 4),
            "expected_calibration_error": round(ece, 4),
            "abstention_metrics": {
                "precision": round(abstention_prec, 4),
                "recall": round(abstention_rec, 4),
                "f1_score": round(abstention_f1, 4),
                "expected": expected_abstentions,
                "actual": actual_abstentions
            },
            "multi_incident_clustering": {
                "precision": round(cluster_prec, 4),
                "recall": round(cluster_rec, 4),
                "f1_score": round(cluster_f1, 4),
                "expected_multi_incidents": expected_multi_incidents,
                "correctly_partitioned": correctly_clustered_incidents
            },
            "per_class_metrics": per_class_metrics,
            "reliability_bins": reliability_bins_list,
            "per_class_calibration": per_class_calib_dict,
            "calibration_provenance_samples": calibration_provenance[:10],
            "latency": {
                "mean_ms": round(sum(latencies_ms) / len(latencies_ms), 2),
                "median_ms": round(sorted_lat[len(sorted_lat) // 2], 2),
                "p95_ms": round(sorted_lat[p95_idx], 2),
                "max_ms": round(sorted_lat[-1], 2)
            }
        }

        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(report_summary, f, indent=2)

        # Print formatted summary table
        print("\n" + "=" * 80)
        print("          NetCoop AI — Independent Curated Challenge Benchmark Report")
        print("=" * 80)
        print(f"Total Scenarios Evaluated: {total_cases}")
        print(f"Top-1 Diagnostic Accuracy: {report_summary['top1_accuracy_pct']}%")
        print(f"Top-3 Diagnostic Accuracy: {report_summary['top3_accuracy_pct']}%")
        print(f"Macro-F1 Score:            {report_summary['macro_f1_score']}")
        print(f"Top-Label Brier Score:     {report_summary['top_label_brier_score']}")
        print(f"Multiclass Brier Score:    {report_summary['multiclass_brier_score']}")
        print(f"Expected Calibration Error:{report_summary['expected_calibration_error']}")
        print(f"Abstention Quality:        Prec: {abstention_prec*100:.1f}% | Rec: {abstention_rec*100:.1f}% | F1: {abstention_f1:.3f}")
        print(f"Clustering F1 Score:       {report_summary['multi_incident_clustering']['f1_score']}")
        print(f"Inference Latency:         Mean: {report_summary['latency']['mean_ms']}ms | P95: {report_summary['latency']['p95_ms']}ms")
        print("-" * 80)
        print(f"{'Root Cause Class':<24} | {'Prec':<7} | {'Recall':<7} | {'F1':<7} | {'FPR':<7} | {'FNR':<7} | {'Supp'}")
        print("-" * 80)
        for c_name, m in per_class_metrics.items():
            print(f"{c_name:<24} | {m['precision']:<7.3f} | {m['recall']:<7.3f} | {m['f1_score']:<7.3f} | {m['false_positive_rate']:<7.3f} | {m['false_negative_rate']:<7.3f} | {m['support']}")
        print("-" * 80)
        print("Reliability Diagram Bins (ECE Breakdown):")
        print(f"{'Bin Range':<14} | {'Count':<6} | {'Mean Conf':<10} | {'Observed Acc':<12} | {'Calib Error':<12} | Bias Direction")
        print("-" * 80)
        for b in reliability_bins_list:
            if b["sample_count"] > 0:
                print(f"{b['bin_range']:<14} | {b['sample_count']:<6} | {b['mean_confidence']:<10.4f} | {b['observed_accuracy']:<12.4f} | {b['calibration_error']:<12.4f} | {b['bias_direction']}")
        print("=" * 80)
        print(f"Detailed challenge report exported to: evaluation/challenge_benchmark_report.json\n")

        return report_summary


if __name__ == "__main__":
    runner = ChallengeBenchmarkRunner()
    runner.run_benchmark()
