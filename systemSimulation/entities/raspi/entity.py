from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from config import RaspiConfig, RaspiDelayConfig, raspi_cfg, raspi_delay_cfg
from entities.raspi.control_program import NoopControlProgram
from entities.raspi.model import RaspiDelayModel
from runtime.types import POWER_BOOTING, POWER_OFF, POWER_READY, Command, CommandResult


@dataclass
class RaspiState:
    timestamp: float
    power_state: str
    effective_obs_timestamp: float
    pipeline_backlog_len: int
    last_process_latency_s: float
    last_command_apply_timestamp: float
    delay_metrics: Dict[str, float]
    control_program_name: str


class RaspiEntity:
    def __init__(self, cfg: RaspiConfig | None = None, delay_cfg: RaspiDelayConfig | None = None):
        # 深拷贝配置，确保每个 RaspiEntity 拥有独立副本
        self.cfg = copy.deepcopy(cfg or raspi_cfg)
        # 深拷贝，避免 set_delay_profile() 通过 setattr 污染全局单例配置
        self.delay_cfg = copy.deepcopy(delay_cfg or raspi_delay_cfg)

        self.power_state = POWER_OFF
        self.boot_remaining_s = 0.0

        self.delay_model = RaspiDelayModel(
            buffer_policy=self.delay_cfg.buffer_policy,
            queue_capacity=self.delay_cfg.queue_capacity,
        )
        self.control_program = NoopControlProgram()

        self.effective_obs_timestamp = float("nan")
        self._control_rate_hz = 0.0
        self._last_control_tick = float("-inf")
        self.last_process_latency_s = 0.0
        self.last_command_apply_timestamp = float("nan")
        self._last_state = RaspiState(
            timestamp=0.0,
            power_state=POWER_OFF,
            effective_obs_timestamp=float("nan"),
            pipeline_backlog_len=0,
            last_process_latency_s=0.0,
            last_command_apply_timestamp=float("nan"),
            delay_metrics={},
            control_program_name=type(self.control_program).__name__,
        )

    def load_control_program(self, program) -> CommandResult:
        self.control_program = program if program is not None else NoopControlProgram()
        return CommandResult(True, "OK", "program loaded")

    def power_on(self, timestamp: float) -> CommandResult:
        if self.power_state in (POWER_BOOTING, POWER_READY):
            return CommandResult(True, "ALREADY_ON", "raspi already on", timestamp)
        self.power_state = POWER_BOOTING
        self.boot_remaining_s = float(self.cfg.boot_delay_s)
        return CommandResult(True, "OK", "raspi booting", timestamp)

    def power_off(self, timestamp: float) -> CommandResult:
        self.power_state = POWER_OFF
        self.boot_remaining_s = 0.0
        self.delay_model.reset()
        return CommandResult(True, "OK", "raspi off", timestamp)

    def set_delay_profile(self, profile: Dict[str, float]) -> CommandResult:
        for k, v in profile.items():
            if hasattr(self.delay_cfg, k):
                current = getattr(self.delay_cfg, k)
                if isinstance(current, str):
                    setattr(self.delay_cfg, k, str(v))
                elif isinstance(current, int) and not isinstance(current, bool):
                    if k == "queue_capacity":
                        setattr(self.delay_cfg, k, max(1, int(v)))
                    else:
                        setattr(self.delay_cfg, k, int(v))
                else:
                    if k == "control_rate_hz":
                        setattr(self.delay_cfg, k, max(0.0, float(v)))
                    else:
                        setattr(self.delay_cfg, k, float(v))
        # 更新延迟模型参数，保留当前处理中的观测
        self.delay_model.reconfigure(
            buffer_policy=self.delay_cfg.buffer_policy,
            queue_capacity=self.delay_cfg.queue_capacity,
        )
        self._last_control_tick = float("-inf")
        return CommandResult(True, "OK", "delay profile updated")

    def get_delay_profile(self) -> Dict[str, float]:
        return {
            "image_read_delay_s": float(self.delay_cfg.image_read_delay_s),
            "image_process_delay_s": float(self.delay_cfg.image_process_delay_s),
            "state_read_delay_s": float(self.delay_cfg.state_read_delay_s),
            "command_tx_delay_s": float(self.delay_cfg.command_tx_delay_s),
            "jitter_std_s": float(self.delay_cfg.jitter_std_s),
            "buffer_policy": self.delay_cfg.buffer_policy,
            "queue_capacity": int(self.delay_cfg.queue_capacity),
            "control_rate_hz": float(self.delay_cfg.control_rate_hz),
        }

    def _jitter(self) -> float:
        std = float(self.delay_cfg.jitter_std_s)
        if std <= 0.0:
            return 0.0
        return abs(random.gauss(0.0, std))

    def update(
        self,
        timestamp: float,
        world_obs: Dict,
        submit_cmd: Callable[[Command, float], None],
        runtime_dt: float,
    ) -> RaspiState:
        if self.power_state == POWER_BOOTING:
            self.boot_remaining_s -= runtime_dt
            if self.boot_remaining_s <= 0.0:
                self.power_state = POWER_READY

        if self.power_state == POWER_READY:
            obs_delay = max(float(self.delay_cfg.image_read_delay_s), float(self.delay_cfg.state_read_delay_s)) + self._jitter()

            # 多速率控制：只在控制 tick 时接受新观测
            if self.delay_cfg.control_rate_hz > 0.0:
                control_interval = 1.0 / self.delay_cfg.control_rate_hz
                if timestamp - self._last_control_tick >= control_interval - 1e-9:
                    self._last_control_tick = timestamp
                    self.delay_model.try_start(timestamp, world_obs, obs_delay)
            else:
                self.delay_model.try_start(timestamp, world_obs, obs_delay)

            for obs_ts, cmds in self.delay_model.tick(
                timestamp,
                float(self.delay_cfg.image_process_delay_s),
                float(self.delay_cfg.command_tx_delay_s),
                self.control_program,
                self._jitter,
            ):
                self.effective_obs_timestamp = obs_ts
                self.last_process_latency_s = max(0.0, timestamp - obs_ts)
                for cmd in cmds:
                    apply_at = timestamp + runtime_dt
                    submit_cmd(cmd, apply_at)
                    self.last_command_apply_timestamp = apply_at

        self._last_state = RaspiState(
            timestamp=timestamp,
            power_state=self.power_state,
            effective_obs_timestamp=self.effective_obs_timestamp,
            pipeline_backlog_len=(1 if self.delay_model.is_busy() else 0) + self.delay_model.queue_len,
            last_process_latency_s=self.last_process_latency_s,
            last_command_apply_timestamp=self.last_command_apply_timestamp,
            delay_metrics={
                "image_read_delay_s": float(self.delay_cfg.image_read_delay_s),
                "image_process_delay_s": float(self.delay_cfg.image_process_delay_s),
                "state_read_delay_s": float(self.delay_cfg.state_read_delay_s),
                "command_tx_delay_s": float(self.delay_cfg.command_tx_delay_s),
                "jitter_std_s": float(self.delay_cfg.jitter_std_s),
                "buffer_policy": self.delay_cfg.buffer_policy,
                "queue_capacity": int(self.delay_cfg.queue_capacity),
                "control_rate_hz": float(self.delay_cfg.control_rate_hz),
            },
            control_program_name=type(self.control_program).__name__,
        )
        return self._last_state

    def get_state(self) -> Dict[str, float | str | int]:
        s = self._last_state
        result = {
            "timestamp": s.timestamp,
            "power_state": s.power_state,
            "effective_obs_timestamp": s.effective_obs_timestamp,
            "pipeline_backlog_len": s.pipeline_backlog_len,
            "last_process_latency_s": s.last_process_latency_s,
            "last_command_apply_timestamp": s.last_command_apply_timestamp,
            "delay_metrics": dict(s.delay_metrics),
            "control_program_name": s.control_program_name,
        }
        return result
