from __future__ import annotations

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


class RaspiEntity:
    def __init__(self, cfg: RaspiConfig | None = None, delay_cfg: RaspiDelayConfig | None = None):
        self.cfg = cfg or raspi_cfg
        self.delay_cfg = delay_cfg or raspi_delay_cfg

        self.power_state = POWER_OFF
        self.boot_remaining_s = 0.0

        self.delay_model = RaspiDelayModel()
        self.control_program = NoopControlProgram()

        self.effective_obs_timestamp = float("nan")
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
                setattr(self.delay_cfg, k, float(v))
        return CommandResult(True, "OK", "delay profile updated")

    def get_delay_profile(self) -> Dict[str, float]:
        return {
            "image_read_delay_s": float(self.delay_cfg.image_read_delay_s),
            "image_process_delay_s": float(self.delay_cfg.image_process_delay_s),
            "state_read_delay_s": float(self.delay_cfg.state_read_delay_s),
            "command_tx_delay_s": float(self.delay_cfg.command_tx_delay_s),
            "jitter_std_s": float(self.delay_cfg.jitter_std_s),
        }

    def _jitter(self) -> float:
        std = float(self.delay_cfg.jitter_std_s)
        if std <= 0.0:
            return 0.0
        return max(0.0, random.gauss(0.0, std))

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
            self.delay_model.pipeline.push_obs(timestamp + obs_delay, world_obs)

            ready_obs = self.delay_model.pipeline.pop_ready_obs(timestamp)
            for obs in ready_obs:
                process_available = timestamp + float(self.delay_cfg.image_process_delay_s) + self._jitter()
                self.delay_model.pipeline.push_proc(process_available, {"obs": obs, "ready_at": process_available})

            ready_proc = self.delay_model.pipeline.pop_ready_proc(timestamp)
            for proc_item in ready_proc:
                obs = proc_item["obs"]
                obs_ts = float(obs["timestamp"])
                self.effective_obs_timestamp = obs_ts
                self.last_process_latency_s = max(0.0, timestamp - obs_ts)

                cmds = self.control_program.on_tick(obs)
                for cmd in cmds:
                    cmd_available = timestamp + float(self.delay_cfg.command_tx_delay_s) + self._jitter()
                    self.delay_model.pipeline.push_cmd(cmd_available, cmd)

            ready_cmds = self.delay_model.pipeline.pop_ready_cmd(timestamp)
            for cmd in ready_cmds:
                apply_at = timestamp + runtime_dt
                submit_cmd(cmd, apply_at)
                self.last_command_apply_timestamp = apply_at

        self._last_state = RaspiState(
            timestamp=timestamp,
            power_state=self.power_state,
            effective_obs_timestamp=self.effective_obs_timestamp,
            pipeline_backlog_len=self.delay_model.pipeline.backlog_len(),
            last_process_latency_s=self.last_process_latency_s,
            last_command_apply_timestamp=self.last_command_apply_timestamp,
            delay_metrics={
                "image_read_delay_s": float(self.delay_cfg.image_read_delay_s),
                "image_process_delay_s": float(self.delay_cfg.image_process_delay_s),
                "state_read_delay_s": float(self.delay_cfg.state_read_delay_s),
                "command_tx_delay_s": float(self.delay_cfg.command_tx_delay_s),
                "jitter_std_s": float(self.delay_cfg.jitter_std_s),
            },
        )
        return self._last_state

    def get_state(self) -> Dict[str, float | str | int]:
        s = self._last_state
        return {
            "timestamp": s.timestamp,
            "power_state": s.power_state,
            "effective_obs_timestamp": s.effective_obs_timestamp,
            "pipeline_backlog_len": s.pipeline_backlog_len,
            "last_process_latency_s": s.last_process_latency_s,
            "last_command_apply_timestamp": s.last_command_apply_timestamp,
            "delay_metrics": dict(s.delay_metrics),
        }
