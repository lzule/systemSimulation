"""算法基线与 Benchmark 工具测试。

运行方式：
    conda run -n simulation python -m unittest tests.test_phase4_algorithm_baselines -v
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.run_benchmark import is_obs_mode_allowed, ALGORITHM_REGISTRY
from tools.summarize_results import compute_summary


# ============================================================
# TestSummarizeResults
# ============================================================

class TestSummarizeResults(unittest.TestCase):
    """结果汇总工具分组测试。"""

    def test_compute_summary_groups_by_obs_mode(self):
        """compute_summary 的 groups 中 obs_mode 作为分组维度。"""
        results = [
            {
                "algorithm_name": "rate_p",
                "condition_id": "scenario_a",
                "observation_mode": "research",
                "seed": 0,
                "metrics": {
                    "capture_success_rate": 1.0,
                    "rms_pixel_error": 10.5,
                },
            },
            {
                "algorithm_name": "rate_p",
                "condition_id": "scenario_a",
                "observation_mode": "research",
                "seed": 1,
                "metrics": {
                    "capture_success_rate": 0.8,
                    "rms_pixel_error": 12.3,
                },
            },
            {
                "algorithm_name": "rate_p",
                "condition_id": "scenario_a",
                "observation_mode": "near_real",
                "seed": 0,
                "metrics": {
                    "capture_success_rate": 0.9,
                    "rms_pixel_error": 15.0,
                },
            },
            {
                "algorithm_name": "rate_pi",
                "condition_id": "scenario_b",
                "observation_mode": "research",
                "seed": 0,
                "metrics": {
                    "capture_success_rate": 1.0,
                    "rms_pixel_error": 8.0,
                },
            },
        ]
        summary = compute_summary(results)

        groups = summary["groups"]
        self.assertGreater(len(groups), 0)

        obs_modes = set()
        for g in groups:
            self.assertIn("obs_mode", g)
            obs_modes.add(g["obs_mode"])

        self.assertIn("research", obs_modes)
        self.assertIn("near_real", obs_modes)

    def test_compute_summary_counts_experiments(self):
        """compute_summary 正确统计实验数量。"""
        results = [
            {
                "algorithm_name": "rate_p",
                "condition_id": "s1",
                "observation_mode": "research",
                "seed": 0,
                "metrics": {"rms_pixel_error": 10.0},
            },
            {
                "algorithm_name": "rate_p",
                "condition_id": "s1",
                "observation_mode": "research",
                "seed": 1,
                "metrics": {"rms_pixel_error": 12.0},
            },
        ]
        summary = compute_summary(results)
        self.assertEqual(summary["total_experiments"], 2)
        self.assertEqual(summary["successful_experiments"], 2)
        self.assertEqual(summary["failed_experiments"], 0)

    def test_compute_summary_skips_failures(self):
        """compute_summary 跳过含 failure_reason 的实验。"""
        results = [
            {
                "algorithm_name": "rate_p",
                "condition_id": "s1",
                "observation_mode": "research",
                "seed": 0,
                "failure_reason": "timeout",
                "metrics": {},
            },
        ]
        summary = compute_summary(results)
        self.assertEqual(summary["total_experiments"], 1)
        self.assertEqual(summary["failed_experiments"], 1)
        self.assertEqual(summary["successful_experiments"], 0)
        self.assertEqual(len(summary["groups"]), 0)

    def test_compute_summary_by_algorithm(self):
        """by_algorithm 汇总按算法+模式分组。"""
        results = [
            {
                "algorithm_name": "rate_p",
                "condition_id": "s1",
                "observation_mode": "research",
                "seed": 0,
                "metrics": {"rms_pixel_error": 10.0},
            },
            {
                "algorithm_name": "rate_pi",
                "condition_id": "s1",
                "observation_mode": "research",
                "seed": 0,
                "metrics": {"rms_pixel_error": 8.0},
            },
            {
                "algorithm_name": "rate_p",
                "condition_id": "s2",
                "observation_mode": "realistic",
                "seed": 0,
                "metrics": {"rms_pixel_error": 20.0},
            },
        ]
        summary = compute_summary(results)
        by_alg = summary["by_algorithm"]
        pairs = {(a["algorithm_name"], a.get("obs_mode")) for a in by_alg}
        self.assertIn(("rate_p", "research"), pairs)
        self.assertIn(("rate_p", "realistic"), pairs)
        self.assertIn(("rate_pi", "research"), pairs)


class TestBenchmarkBasic(unittest.TestCase):
    """Benchmark 基础设施测试。"""

    def test_algorithm_registry_has_baseline(self):
        """算法注册表包含 baseline_rate_p。"""
        self.assertIn("baseline_rate_p", ALGORITHM_REGISTRY)

    def test_baseline_rate_p_factory(self):
        """baseline_rate_p 工厂函数能创建实例。"""
        cp = ALGORITHM_REGISTRY["baseline_rate_p"]()
        self.assertIsNotNone(cp)
        self.assertTrue(hasattr(cp, "on_tick"))

    def test_is_obs_mode_allowed_baseline(self):
        """baseline_rate_p 允许所有观测模式。"""
        for mode in ("debug", "research", "realistic"):
            self.assertTrue(is_obs_mode_allowed("baseline_rate_p", mode))


if __name__ == "__main__":
    unittest.main()
