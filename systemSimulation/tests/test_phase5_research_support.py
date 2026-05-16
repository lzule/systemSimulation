"""阶段5研究支撑与结果固化专项测试。

覆盖：
1. 回归对比工具对 0 值指标的保留
2. 回归对比工具对 ATP 指标的纳入
3. 对比可视化工具基本出图能力
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.compare_results import compare_groups, load_grouped_results
from tools.plot_comparison import plot_phase_boxplot, plot_ranking_bar


class TestCompareResultsPhase5(unittest.TestCase):
    """阶段5回归对比工具测试。"""

    @patch("tools.compare_results.scan_results")
    def test_load_grouped_results_preserves_zero_metrics(self, mock_scan_results):
        """0 值指标不应在聚合时被误当成缺失值丢掉。"""
        mock_scan_results.return_value = [
            {
                "algorithm_name": "alg_a",
                "condition_id": "B1",
                "observation_mode": "research",
                "seed": 42,
                "failure_reason": None,
                "metrics": {
                    "rms_pixel_error": 10.0,
                    "lock_loss_count": 0,
                    "lock_loss_rate": 0.0,
                },
                "atp_metrics": {
                    "reacquire_success_rate": 0.0,
                    "time_to_acquire_s": 0.0,
                    "time_to_fine_track_s": 0.0,
                },
            }
        ]

        grouped = load_grouped_results("dummy_dir", algorithms=["alg_a"], scenarios=["B1"])
        metrics = grouped[("alg_a", "B1")]["metrics"]

        self.assertEqual(metrics["lock_loss_count"], 0)
        self.assertEqual(metrics["lock_loss_rate"], 0.0)
        self.assertEqual(metrics["reacquire_success_rate"], 0.0)
        self.assertEqual(metrics["time_to_acquire_s"], 0.0)
        self.assertEqual(metrics["time_to_fine_track_s"], 0.0)

    def test_compare_groups_includes_reacquire_and_timing_metrics(self):
        """对比输出应包含阶段5新增关注的 ATP 指标。"""
        baseline = {
            ("alg_a", "B1"): {
                "metrics": {
                    "rms_pixel_error": 10.0,
                    "reacquire_success_rate": 1.0,
                    "time_to_acquire_s": 1.0,
                    "time_to_fine_track_s": 2.0,
                },
                "n": 1,
                "seeds": [42],
            }
        }
        new = {
            ("alg_a", "B1"): {
                "metrics": {
                    "rms_pixel_error": 12.0,
                    "reacquire_success_rate": 0.5,
                    "time_to_acquire_s": 1.5,
                    "time_to_fine_track_s": 2.5,
                },
                "n": 1,
                "seeds": [42],
            }
        }

        result = compare_groups(baseline, new)
        metric_names = {m["metric"] for m in result["comparisons"][0]["metrics"]}

        self.assertIn("reacquire_success_rate", metric_names)
        self.assertIn("time_to_acquire_s", metric_names)
        self.assertIn("time_to_fine_track_s", metric_names)


class TestPlotComparisonPhase5(unittest.TestCase):
    """阶段5对比可视化工具测试。"""

    def test_plot_ranking_bar_generates_png(self):
        """排名图应能成功生成文件。"""
        groups = [
            {
                "algorithm_name": "atp_search_track_baseline",
                "condition_id": "B1",
                "stats": {
                    "rms_pixel_error": {"mean": 8.0},
                    "tracking_efficiency": {"mean": 1.0},
                },
            },
            {
                "algorithm_name": "linear_kf_tracker",
                "condition_id": "B1",
                "stats": {
                    "rms_pixel_error": {"mean": 20.0},
                    "tracking_efficiency": {"mean": 0.5},
                },
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "ranking.png")
            plot_ranking_bar(groups, out_path)
            self.assertTrue(os.path.isfile(out_path))
            self.assertGreater(os.path.getsize(out_path), 0)

    def test_plot_phase_boxplot_generates_png(self):
        """分时段箱线图应能成功生成文件。"""
        data = {
            "atp_search_track_baseline": [
                {"atp_state": "SEARCH", "pixel_error_total": 100.0},
                {"atp_state": "TRACK_COARSE", "pixel_error_total": 40.0},
                {"atp_state": "TRACK_FINE", "pixel_error_total": 8.0},
            ],
            "linear_kf_tracker": [
                {"atp_state": "SEARCH", "pixel_error_total": 110.0},
                {"atp_state": "TRACK_COARSE", "pixel_error_total": 70.0},
                {"atp_state": "TRACK_COARSE", "pixel_error_total": 80.0},
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "phase_box.png")
            plot_phase_boxplot(data, "B1", "atp_search_track_baseline", out_path)
            self.assertTrue(os.path.isfile(out_path))
            self.assertGreater(os.path.getsize(out_path), 0)


if __name__ == "__main__":
    unittest.main()
