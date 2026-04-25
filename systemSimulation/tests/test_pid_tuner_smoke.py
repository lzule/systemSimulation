import os
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.pid_tuner import Candidate, run_all


class TestPidTunerSmoke(unittest.TestCase):
    def test_pid_tuner_generates_plot_and_metrics(self):
        out = ROOT / "output" / f"pid_tuner_smoke_{uuid.uuid4().hex}.png"
        metrics = run_all(
            output_path=str(out),
            duration_s=4.0,
            stable_from_s=1.0,
            candidates=[Candidate("smoke", 0.675, 0.60, 0.01)],
            render_plot=True,
        )

        self.assertTrue(out.exists())
        self.assertEqual(len(metrics), 1)
        m = metrics[0][1]
        self.assertIn("track_ratio", m)
        self.assertGreaterEqual(m["track_ratio"], 0.0)
        self.assertGreater(m["yaw_span_deg"], 0.01)
        try:
            out.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    unittest.main()
