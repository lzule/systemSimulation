import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.step_response import CommandRecord, GimbalSim


class TestStepResponseMetrics(unittest.TestCase):
    def test_positive_step_rise_time_uses_first_threshold_crossings(self):
        rec = CommandRecord(idx=1, t_inject=0.0, mode="RATE", axis="yaw", value=10.0)
        rec.seg_t = [0.0, 0.05, 0.10, 0.15, 0.20]
        rec.seg_actual = [0.0, 1.0, 3.0, 9.0, 10.0]
        rec.steady_value = 10.0

        GimbalSim._compute_metrics(rec)

        self.assertAlmostEqual(rec.rise_ms, 100.0, places=6)

    def test_negative_step_rise_time_supports_descending_response(self):
        rec = CommandRecord(idx=2, t_inject=0.0, mode="ANGLE", axis="pitch", value=-10.0)
        rec.seg_t = [0.0, 0.05, 0.10, 0.15, 0.20]
        rec.seg_actual = [0.0, -1.0, -3.0, -9.0, -10.0]
        rec.steady_value = -10.0

        GimbalSim._compute_metrics(rec)

        self.assertAlmostEqual(rec.rise_ms, 100.0, places=6)


if __name__ == "__main__":
    unittest.main()
