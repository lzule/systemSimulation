"""阶段4算法基线专项测试。

覆盖 ATP 状态机、光栅扫描、控制程序、Alpha-Beta 预测器、线性卡尔曼滤波、
速率 P/PI 跟踪器、结果汇总工具等新增模块。

运行方式：
    conda run -n simulation python -m unittest tests.test_phase4_algorithm_baselines -v
"""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace

# 确保 systemSimulation 根目录在 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import dataclass

from config import ATPStateMachineConfig
from entities.raspi.atp_state_machine import AtpState, AtpStateMachine
from entities.raspi.atp_control_program import AtpControlProgram
from entities.raspi.predictors.alpha_beta import AlphaBetaFilter
from entities.raspi.predictors.linear_kf import LinearKF
from entities.raspi.trackers.rate_p_tracker import RatePTracker
from entities.raspi.trackers.rate_pi_tracker import RatePITracker
from tools.run_benchmark import is_obs_mode_allowed
from tools.summarize_results import compute_summary
from runtime.types import Detection


# ============================================================
# 辅助工厂
# ============================================================

def _make_small_sm_cfg() -> ATPStateMachineConfig:
    """创建小阈值状态机配置，方便测试快速触发状态转移。"""
    return ATPStateMachineConfig(
        n_detect_enter=2,
        n_acquire_confirm=3,
        n_lost_enter=2,
        n_fine_enter=3,
        coarse_error_threshold_px=50.0,
        search_yaw_range_deg=30.0,
        search_pitch_range_deg=15.0,
        search_step_deg=5.0,
        search_dwell_frames=2,
        search_rate_dps=30.0,
        reacquire_timeout_s=1.0,
        reacquire_search_step_deg=10.0,
        reacquire_search_rate_dps=45.0,
    )


# ============================================================
# 1. TestAtpStateMachine
# ============================================================

class TestAtpStateMachine(unittest.TestCase):
    """ATP 状态机状态转换测试。"""

    def test_initial_state_is_search(self):
        """初始状态应为 SEARCH。"""
        sm = AtpStateMachine(_make_small_sm_cfg())
        self.assertEqual(sm.state, AtpState.SEARCH)

    def test_search_to_acquire(self):
        """连续 n_detect_enter 帧检出后转入 ACQUIRE。"""
        cfg = _make_small_sm_cfg()  # n_detect_enter=2
        sm = AtpStateMachine(cfg)
        # 第 1 帧：不够
        sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        self.assertEqual(sm.state, AtpState.SEARCH)
        # 第 2 帧：达到阈值
        sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        self.assertEqual(sm.state, AtpState.ACQUIRE)

    def test_search_detect_counter_resets_on_miss(self):
        """中间丢失一帧会重置连续检出计数。"""
        cfg = _make_small_sm_cfg()  # n_detect_enter=2
        sm = AtpStateMachine(cfg)
        sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        sm.update(detection_found=False, pixel_error=None, dt=0.01)
        sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        # 仍然 SEARCH（计数器被重置过）
        self.assertEqual(sm.state, AtpState.SEARCH)

    def test_acquire_to_track_coarse(self):
        """ACQUIRE 状态下连续 n_acquire_confirm 帧确认后转入 TRACK_COARSE。"""
        cfg = _make_small_sm_cfg()  # n_acquire_confirm=3
        sm = AtpStateMachine(cfg)
        # 先进入 ACQUIRE（n_detect_enter=2）
        for _ in range(2):
            sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        self.assertEqual(sm.state, AtpState.ACQUIRE)
        # 继续连续检出 n_acquire_confirm=3 帧
        for _ in range(3):
            sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        self.assertEqual(sm.state, AtpState.TRACK_COARSE)

    def test_track_coarse_to_track_fine(self):
        """TRACK_COARSE 下连续 n_fine_enter 帧低误差后转入 TRACK_FINE。"""
        cfg = _make_small_sm_cfg()  # n_fine_enter=3, coarse_error_threshold_px=50.0
        sm = AtpStateMachine(cfg)
        # 快速推进到 TRACK_COARSE
        for _ in range(2):   # SEARCH → ACQUIRE
            sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        for _ in range(3):   # ACQUIRE → TRACK_COARSE
            sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        self.assertEqual(sm.state, AtpState.TRACK_COARSE)
        # 连续低误差帧
        for _ in range(3):
            sm.update(detection_found=True, pixel_error=5.0, dt=0.01)
        self.assertEqual(sm.state, AtpState.TRACK_FINE)

    def test_track_coarse_low_error_counter_resets_on_high_error(self):
        """TRACK_COARSE 下中间出现高误差会重置低误差计数。"""
        # 使用较大的 n_fine_enter 避免进入 TRACK_COARSE 后残留计数干扰
        cfg = ATPStateMachineConfig(
            n_detect_enter=2,
            n_acquire_confirm=3,
            n_lost_enter=2,
            n_fine_enter=5,
            coarse_error_threshold_px=50.0,
            search_yaw_range_deg=30.0,
            search_pitch_range_deg=15.0,
            search_step_deg=5.0,
            search_dwell_frames=2,
            search_rate_dps=30.0,
            reacquire_timeout_s=1.0,
            reacquire_search_step_deg=10.0,
            reacquire_search_rate_dps=45.0,
        )
        sm = AtpStateMachine(cfg)
        # 推进到 TRACK_COARSE（进入时 low_error 被重置为 0）
        for _ in range(2):
            sm.update(detection_found=True, pixel_error=80.0, dt=0.01)  # 高误差不累积 low_error
        for _ in range(3):
            sm.update(detection_found=True, pixel_error=80.0, dt=0.01)  # 高误差不累积 low_error
        self.assertEqual(sm.state, AtpState.TRACK_COARSE)
        # 3 帧低误差
        sm.update(detection_found=True, pixel_error=5.0, dt=0.01)
        sm.update(detection_found=True, pixel_error=5.0, dt=0.01)
        sm.update(detection_found=True, pixel_error=5.0, dt=0.01)
        # 1 帧高误差（> threshold=50），重置低误差计数
        sm.update(detection_found=True, pixel_error=80.0, dt=0.01)
        # 再 3 帧低误差仍不够（计数器被重置过，需要 5 帧）
        sm.update(detection_found=True, pixel_error=5.0, dt=0.01)
        sm.update(detection_found=True, pixel_error=5.0, dt=0.01)
        sm.update(detection_found=True, pixel_error=5.0, dt=0.01)
        self.assertEqual(sm.state, AtpState.TRACK_COARSE)
        # 再加 1 帧低误差（共 4 帧，仍不够 5）
        sm.update(detection_found=True, pixel_error=5.0, dt=0.01)
        self.assertEqual(sm.state, AtpState.TRACK_COARSE)
        # 第 5 帧低误差才够
        sm.update(detection_found=True, pixel_error=5.0, dt=0.01)
        self.assertEqual(sm.state, AtpState.TRACK_FINE)

    def test_track_fine_to_lost_then_reacquire(self):
        """TRACK_FINE 下连续 n_lost_enter 帧丢失 → LOST → 立即级联到 REACQUIRE。"""
        cfg = _make_small_sm_cfg()  # n_lost_enter=2
        sm = AtpStateMachine(cfg)
        # 推进到 TRACK_FINE
        for _ in range(2):   # SEARCH → ACQUIRE
            sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        for _ in range(3):   # ACQUIRE → TRACK_COARSE
            sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        for _ in range(3):   # TRACK_COARSE → TRACK_FINE
            sm.update(detection_found=True, pixel_error=5.0, dt=0.01)
        self.assertEqual(sm.state, AtpState.TRACK_FINE)
        # 连续丢失
        sm.update(detection_found=False, pixel_error=None, dt=0.01)
        self.assertEqual(sm.state, AtpState.TRACK_FINE)
        sm.update(detection_found=False, pixel_error=None, dt=0.01)
        # LOST 是瞬态，应在同一 tick 内级联到 REACQUIRE
        self.assertEqual(sm.state, AtpState.REACQUIRE)

    def test_reacquire_timeout_to_search(self):
        """REACQUIRE 超时后转入 SEARCH。"""
        cfg = _make_small_sm_cfg()  # reacquire_timeout_s=1.0
        sm = AtpStateMachine(cfg)
        # 推进到 REACQUIRE
        for _ in range(2):
            sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        for _ in range(3):
            sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        for _ in range(3):
            sm.update(detection_found=True, pixel_error=5.0, dt=0.01)
        for _ in range(2):
            sm.update(detection_found=False, pixel_error=None, dt=0.01)
        self.assertEqual(sm.state, AtpState.REACQUIRE)
        # REACQUIRE 级联时已有少量 elapsed（来自 LOST→REACQUIRE 级联的 dt）。
        # 模拟超时：先送 dt=0.4（仍未超时）
        sm.update(detection_found=False, pixel_error=None, dt=0.4)
        self.assertEqual(sm.state, AtpState.REACQUIRE)
        # 再送 dt=0.6，累计超过 timeout=1.0
        sm.update(detection_found=False, pixel_error=None, dt=0.6)
        self.assertEqual(sm.state, AtpState.SEARCH)

    def test_reacquire_to_acquire_on_detect(self):
        """REACQUIRE 状态下连续 n_detect_enter 帧检出 → ACQUIRE。"""
        cfg = _make_small_sm_cfg()  # n_detect_enter=2
        sm = AtpStateMachine(cfg)
        # 推进到 REACQUIRE
        for _ in range(2):
            sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        for _ in range(3):
            sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        for _ in range(3):
            sm.update(detection_found=True, pixel_error=5.0, dt=0.01)
        for _ in range(2):
            sm.update(detection_found=False, pixel_error=None, dt=0.01)
        self.assertEqual(sm.state, AtpState.REACQUIRE)
        # 重新检出
        sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        self.assertEqual(sm.state, AtpState.ACQUIRE)

    def test_reset(self):
        """reset() 能恢复到 SEARCH。"""
        cfg = _make_small_sm_cfg()
        sm = AtpStateMachine(cfg)
        # 推进到 TRACK_COARSE
        for _ in range(2):
            sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        for _ in range(3):
            sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        self.assertEqual(sm.state, AtpState.TRACK_COARSE)
        # reset
        sm.reset()
        self.assertEqual(sm.state, AtpState.SEARCH)

    def test_acquire_to_lost_on_miss(self):
        """ACQUIRE 状态下连续 n_lost_enter 帧丢失 → LOST → REACQUIRE。"""
        cfg = _make_small_sm_cfg()  # n_lost_enter=2
        sm = AtpStateMachine(cfg)
        # 进入 ACQUIRE
        for _ in range(2):
            sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        self.assertEqual(sm.state, AtpState.ACQUIRE)
        # 连续丢失
        sm.update(detection_found=False, pixel_error=None, dt=0.01)
        sm.update(detection_found=False, pixel_error=None, dt=0.01)
        # LOST → REACQUIRE（瞬态级联）
        self.assertEqual(sm.state, AtpState.REACQUIRE)

    def test_track_coarse_to_lost_on_miss(self):
        """TRACK_COARSE 下连续 n_lost_enter 帧丢失 → LOST → REACQUIRE。"""
        cfg = _make_small_sm_cfg()  # n_lost_enter=2
        sm = AtpStateMachine(cfg)
        # 推进到 TRACK_COARSE
        for _ in range(2):
            sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        for _ in range(3):
            sm.update(detection_found=True, pixel_error=10.0, dt=0.01)
        self.assertEqual(sm.state, AtpState.TRACK_COARSE)
        # 连续丢失
        sm.update(detection_found=False, pixel_error=None, dt=0.01)
        sm.update(detection_found=False, pixel_error=None, dt=0.01)
        self.assertEqual(sm.state, AtpState.REACQUIRE)


# ============================================================
# 2. TestRasterScan
# ============================================================

class TestRasterScan(unittest.TestCase):
    """光栅扫描 get_next_search_rate 测试。"""

    def test_returns_tuple(self):
        """返回值结构为 (yaw_rate, pitch_rate)。"""
        sm = AtpStateMachine(_make_small_sm_cfg())
        result = sm.get_next_search_rate()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        yaw_rate, pitch_rate = result
        self.assertIsInstance(yaw_rate, float)
        self.assertIsInstance(pitch_rate, float)

    def test_pitch_rate_not_always_zero(self):
        """搜索足够多步后 pitch_rate 应出现非零值。"""
        sm = AtpStateMachine(_make_small_sm_cfg())
        pitch_rates = []
        for _ in range(200):
            _, pitch_rate = sm.get_next_search_rate()
            pitch_rates.append(pitch_rate)
        self.assertTrue(
            any(pr != 0.0 for pr in pitch_rates),
            "pitch_rate 在 200 步内始终为 0，预期应出现非零 pitch 步进",
        )

    def test_yaw_direction_reverses(self):
        """连续调用足够多次后 yaw 方向应该反转。"""
        sm = AtpStateMachine(_make_small_sm_cfg())
        yaw_rates = []
        for _ in range(200):
            yaw_rate, _ = sm.get_next_search_rate()
            yaw_rates.append(yaw_rate)
        # 检查 yaw_rate 的正负号发生了变化
        positive = any(r > 0 for r in yaw_rates if r != 0.0)
        negative = any(r < 0 for r in yaw_rates if r != 0.0)
        self.assertTrue(
            positive and negative,
            "yaw_rate 在 200 步内未出现方向反转（应同时有正值和负值）",
        )


# ============================================================
# 3. TestAtpControlProgram
# ============================================================

class TestAtpControlProgram(unittest.TestCase):
    """ATP 控制程序命令记录测试。"""

    def test_on_tick_returns_commands(self):
        """on_tick 返回命令列表。"""
        prog = AtpControlProgram(tracker=None, predictor=None)
        obs = {"timestamp": 0.1, "frame": None}
        cmds = prog.on_tick(obs)
        self.assertIsInstance(cmds, list)

    def test_attributes_exist(self):
        """last_yaw_rate_cmd_dps, last_pitch_rate_cmd_dps, last_detection_found 属性存在。"""
        prog = AtpControlProgram(tracker=None, predictor=None)
        self.assertTrue(hasattr(prog, "last_yaw_rate_cmd_dps"))
        self.assertTrue(hasattr(prog, "last_pitch_rate_cmd_dps"))
        self.assertTrue(hasattr(prog, "last_detection_found"))

    def test_search_state_sends_nonzero_rate(self):
        """SEARCH 状态下应发送非零 yaw 速率（光栅扫描）。"""
        prog = AtpControlProgram(tracker=None, predictor=None, config=_make_small_sm_cfg())
        obs = {"timestamp": 0.1, "frame": None}
        prog.on_tick(obs)
        self.assertNotEqual(prog.last_yaw_rate_cmd_dps, 0.0)

    def test_multiple_ticks_advance_timestamp(self):
        """多次 tick 时间戳递增，不报错。"""
        prog = AtpControlProgram(tracker=None, predictor=None, config=_make_small_sm_cfg())
        for i in range(5):
            obs = {"timestamp": 0.01 * (i + 1), "frame": None}
            cmds = prog.on_tick(obs)
            self.assertIsInstance(cmds, list)


# ============================================================
# 4. TestAlphaBetaFilter
# ============================================================

class TestAlphaBetaFilter(unittest.TestCase):
    """Alpha-Beta 预测器测试。"""

    def test_predict_returns_none_before_init(self):
        """未初始化时 predict() 返回 None。"""
        ab = AlphaBetaFilter()
        self.assertIsNone(ab.predict(n_steps=1))

    def test_predict_returns_tuple_after_init(self):
        """初始化后 predict() 返回 tuple[float, float]。"""
        ab = AlphaBetaFilter()
        det = Detection(found=True, cx=100.0, cy=200.0)
        obs = {"timestamp": 1.0}
        ab.update(obs, det)
        result = ab.predict(n_steps=1)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], float)
        self.assertIsInstance(result[1], float)

    def test_predict_updates_position(self):
        """多次 update 后 predict 位置应该变化。"""
        ab = AlphaBetaFilter(alpha=0.8, beta=0.3)
        # 第一帧初始化
        obs1 = {"timestamp": 1.0}
        det1 = Detection(found=True, cx=100.0, cy=200.0)
        ab.update(obs1, det1)
        pred1 = ab.predict(n_steps=1)

        # 第二帧有速度
        obs2 = {"timestamp": 2.0}
        det2 = Detection(found=True, cx=110.0, cy=220.0)
        ab.update(obs2, det2)
        pred2 = ab.predict(n_steps=1)

        # 两次 predict 应该不同（第二帧有速度外推）
        self.assertNotEqual(pred1, pred2)

    def test_no_detection_does_not_crash(self):
        """无检测时 update 不崩溃。"""
        ab = AlphaBetaFilter()
        obs = {"timestamp": 1.0}
        ab.update(obs, None)
        self.assertIsNone(ab.predict(n_steps=1))

    def test_not_found_detection_treated_as_missing(self):
        """found=False 的 detection 等同于无检测。"""
        ab = AlphaBetaFilter()
        det = Detection(found=False)
        obs = {"timestamp": 1.0}
        ab.update(obs, det)
        self.assertIsNone(ab.predict(n_steps=1))


# ============================================================
# 5. TestLinearKF
# ============================================================

class TestLinearKF(unittest.TestCase):
    """线性卡尔曼滤波测试。"""

    def test_predict_returns_none_before_init(self):
        """未初始化时 predict() 返回 None。"""
        kf = LinearKF()
        self.assertIsNone(kf.predict(n_steps=1))

    def test_predict_returns_tuple_after_init(self):
        """初始化后 predict() 返回 tuple。"""
        kf = LinearKF()
        det = Detection(found=True, cx=150.0, cy=250.0)
        obs = {"timestamp": 1.0}
        kf.update(obs, det)
        result = kf.predict(n_steps=1)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_predict_returns_floats(self):
        """predict() 返回 tuple 中的元素为 float。"""
        kf = LinearKF()
        det = Detection(found=True, cx=150.0, cy=250.0)
        obs1 = {"timestamp": 1.0}
        kf.update(obs1, det)
        pred = kf.predict(n_steps=3)
        self.assertIsInstance(pred[0], float)
        self.assertIsInstance(pred[1], float)

    def test_multiple_updates_shift_prediction(self):
        """多次 update 后预测位置应发生变化。"""
        kf = LinearKF()
        obs1 = {"timestamp": 1.0}
        det1 = Detection(found=True, cx=100.0, cy=100.0)
        kf.update(obs1, det1)
        pred1 = kf.predict(n_steps=5)

        obs2 = {"timestamp": 2.0}
        det2 = Detection(found=True, cx=120.0, cy=130.0)
        kf.update(obs2, det2)
        pred2 = kf.predict(n_steps=5)

        # 预测位置应该不同（速度估计已更新）
        self.assertNotAlmostEqual(pred1[0], pred2[0], places=1)

    def test_no_detection_does_not_crash(self):
        """无检测时 update 不崩溃。"""
        kf = LinearKF()
        obs = {"timestamp": 1.0}
        kf.update(obs, None)
        self.assertIsNone(kf.predict(n_steps=1))


# ============================================================
# 6. TestRatePTracker / TestRatePITracker
# ============================================================

class TestRatePTracker(unittest.TestCase):
    """速率 P 跟踪器基本功能测试。"""

    def test_compute_commands_returns_list(self):
        """compute_commands 返回 list。"""
        tracker = RatePTracker()
        obs = {"timestamp": 0.1, "frame": None}
        cmds = tracker.compute_commands(obs, AtpState.TRACK_COARSE, None)
        self.assertIsInstance(cmds, list)

    def test_frame_none_returns_empty_or_mode_command(self):
        """frame=None 时返回空列表或仅含模式切换命令。"""
        tracker = RatePTracker()
        obs = {"timestamp": 0.1, "frame": None}
        cmds = tracker.compute_commands(obs, AtpState.TRACK_COARSE, None)
        # frame=None 时不会有检测，只可能有模式切换命令
        for cmd in cmds:
            self.assertNotEqual(cmd.action, "set_rate_target")

    def test_instance_attributes(self):
        """实例具有 last_pixel_error_x 等属性。"""
        tracker = RatePTracker()
        self.assertTrue(hasattr(tracker, "last_pixel_error_x"))
        self.assertTrue(hasattr(tracker, "last_pixel_error_y"))
        self.assertTrue(hasattr(tracker, "last_detection_found"))


class TestRatePITracker(unittest.TestCase):
    """速率 PI 跟踪器基本功能测试。"""

    def test_compute_commands_returns_list(self):
        """compute_commands 返回 list。"""
        tracker = RatePITracker()
        obs = {"timestamp": 0.1, "frame": None}
        cmds = tracker.compute_commands(obs, AtpState.TRACK_COARSE, None)
        self.assertIsInstance(cmds, list)

    def test_frame_none_returns_empty_or_mode_command(self):
        """frame=None 时不含 set_rate_target 命令。"""
        tracker = RatePITracker()
        obs = {"timestamp": 0.1, "frame": None}
        cmds = tracker.compute_commands(obs, AtpState.TRACK_COARSE, None)
        for cmd in cmds:
            self.assertNotEqual(cmd.action, "set_rate_target")

    def test_instance_attributes(self):
        """实例具有 last_pixel_error_x 等属性。"""
        tracker = RatePITracker()
        self.assertTrue(hasattr(tracker, "last_pixel_error_x"))
        self.assertTrue(hasattr(tracker, "last_pixel_error_y"))
        self.assertTrue(hasattr(tracker, "last_detection_found"))


# ============================================================
# 7. TestSummarizeResults
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

        # groups 应包含 obs_mode 维度
        groups = summary["groups"]
        self.assertGreater(len(groups), 0)

        # 每个 group 应有 obs_mode 字段
        obs_modes = set()
        for g in groups:
            self.assertIn("obs_mode", g)
            obs_modes.add(g["obs_mode"])

        # 应该同时出现 research 和 near_real 两种模式
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
        # groups 应为空（唯一的实验是失败的）
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


class TestBenchmarkObsModeCompatibility(unittest.TestCase):
    """基准工具中的算法/观测模式兼容性校验测试。"""

    def test_angle_mode_realistic_rejects_research(self):
        """angle_mode_realistic 不能在 research 模式下运行。"""
        self.assertFalse(is_obs_mode_allowed("angle_mode_realistic", "research"))

    def test_angle_mode_realistic_allows_realistic(self):
        """angle_mode_realistic 可以在 realistic 模式下运行。"""
        self.assertTrue(is_obs_mode_allowed("angle_mode_realistic", "realistic"))

    def test_rate_pi_allows_research(self):
        """速率模式算法继续允许 research。"""
        self.assertTrue(is_obs_mode_allowed("rate_pi", "research"))


if __name__ == "__main__":
    unittest.main()
