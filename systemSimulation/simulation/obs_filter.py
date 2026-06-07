"""观测过滤器：按 obs_mode 对 world_obs 进行字段白名单过滤和噪声注入。

三种模式：
  - debug:     透传全部 obs（当前行为，向后兼容）
  - research:  白名单过滤，只保留 timestamp / gimbal.mode / camera.f_current_mm / frame
  - realistic: frame.image + 有噪声的 gimbal 测量值 + 无 target（模拟真实传感器受限场景）
"""
from __future__ import annotations

import copy
from dataclasses import replace
from typing import Optional

import numpy as np


class ObsFilter:
    """观测整形层：根据 obs_mode 过滤 world_obs 中控制器可见的字段。

    ObsFilter 是纯观测整形层，不反向依赖实体对象。
    """

    # research 模式 gimbal 白名单
    _RESEARCH_GIMBAL_KEYS = {"mode"}

    # research 模式 camera 白名单
    _RESEARCH_CAMERA_KEYS = {"f_current_mm"}

    # realistic 模式 gimbal 白名单
    _REALISTIC_GIMBAL_KEYS = {"mode", "yaw_deg_internal", "pitch_deg", "yaw_rate_dps", "pitch_rate_dps"}

    # realistic 模式 camera 白名单
    _REALISTIC_CAMERA_KEYS = {"f_current_mm"}

    def __init__(
        self,
        mode: str = "debug",
        encoder_noise_std_deg: float = 0.0,
        gyro_noise_std_dps: float = 0.0,
    ) -> None:
        if mode not in ("debug", "research", "realistic"):
            raise ValueError(f"未知的 obs_mode: {mode!r}，可选: debug / research / realistic")
        self.mode = mode
        self.encoder_noise_std_deg = encoder_noise_std_deg
        self.gyro_noise_std_dps = gyro_noise_std_dps

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def filter_obs(
        self,
        world_obs: dict,
        gimbal_measured: Optional[dict] = None,
    ) -> dict:
        """根据当前模式过滤 world_obs，返回过滤后的观测字典。

        Args:
            world_obs: runtime.step() 中构建的完整观测字典。
            gimbal_measured: 预留给 realistic 模式的测量值（轮B任务实现
                get_measured_state() 后传入）。当前为 None 时，realistic 模式
                使用 world_obs 中的原始 gimbal 值叠加噪声。

        Returns:
            过滤后的观测字典（深拷贝，不修改原始 world_obs）。
        """
        if self.mode == "debug":
            # 浅拷贝顶层字典，避免控制程序修改顶层键影响 runtime 内部；
            # frame 单独隔离复制，防止控制程序修改 frame.image 污染相机内部数据。
            result = dict(world_obs)
            result["frame"] = self._copy_frame(world_obs.get("frame"))
            return result

        if self.mode == "research":
            return self._filter_research(world_obs)

        if self.mode == "realistic":
            return self._filter_realistic(world_obs, gimbal_measured)

        # 不应到达此处（__init__ 已校验 mode）
        return world_obs

    # ------------------------------------------------------------------
    # research 模式
    # ------------------------------------------------------------------

    def _filter_research(self, world_obs: dict) -> dict:
        """research 模式：只保留白名单字段，无噪声。"""
        filtered: dict = {}

        # timestamp
        filtered["timestamp"] = world_obs["timestamp"]

        # gimbal：只保留 mode
        raw_gimbal = world_obs.get("gimbal", {})
        filtered["gimbal"] = {k: v for k, v in raw_gimbal.items() if k in self._RESEARCH_GIMBAL_KEYS}

        # camera：只保留 f_current_mm
        raw_camera = world_obs.get("camera", {})
        filtered["camera"] = {k: v for k, v in raw_camera.items() if k in self._RESEARCH_CAMERA_KEYS}

        # frame：完整保留（image + intrinsics）
        filtered["frame"] = self._copy_frame(world_obs.get("frame", {}))

        # research 模式无 target
        filtered["target"] = {}

        return filtered

    # ------------------------------------------------------------------
    # realistic 模式
    # ------------------------------------------------------------------

    def _filter_realistic(self, world_obs: dict, gimbal_measured: Optional[dict]) -> dict:
        """realistic 模式：frame + 有噪声 gimbal 测量值，无 target。"""
        filtered: dict = {}

        # timestamp
        filtered["timestamp"] = world_obs["timestamp"]

        # gimbal：白名单字段 + 噪声
        raw_gimbal = gimbal_measured if gimbal_measured is not None else world_obs.get("gimbal", {})
        filtered["gimbal"] = self._build_realistic_gimbal(raw_gimbal)

        # camera：只保留 f_current_mm
        raw_camera = world_obs.get("camera", {})
        filtered["camera"] = {k: v for k, v in raw_camera.items() if k in self._REALISTIC_CAMERA_KEYS}

        # frame：完整保留（image + intrinsics）
        filtered["frame"] = self._copy_frame(world_obs.get("frame", {}))

        # realistic 模式无 target
        filtered["target"] = {}

        return filtered

    def _build_realistic_gimbal(self, raw_gimbal: dict) -> dict:
        """构建 realistic 模式的 gimbal 观测，叠加传感器噪声。"""
        result: dict = {}

        # mode（无噪声）
        if "mode" in raw_gimbal:
            result["mode"] = raw_gimbal["mode"]

        # 角度测量：叠加编码器噪声
        result["yaw_deg_internal"] = self._add_noise(
            raw_gimbal.get("yaw_deg_internal", raw_gimbal.get("yaw_deg", 0.0)),
            self.encoder_noise_std_deg,
        )
        result["pitch_deg"] = self._add_noise(
            raw_gimbal.get("pitch_deg", 0.0),
            self.encoder_noise_std_deg,
        )

        # 角速度测量：叠加陀螺仪噪声
        result["yaw_rate_dps"] = self._add_noise(
            raw_gimbal.get("yaw_rate_dps", 0.0),
            self.gyro_noise_std_dps,
        )
        result["pitch_rate_dps"] = self._add_noise(
            raw_gimbal.get("pitch_rate_dps", 0.0),
            self.gyro_noise_std_dps,
        )

        return result

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _add_noise(value: float, std: float) -> float:
        """对 value 叠加 N(0, std) 噪声；std <= 0 时直接返回原值。"""
        if std <= 0.0:
            return value
        return float(value + np.random.normal(0.0, std))

    @staticmethod
    def _copy_frame(frame) -> object:
        """拷贝 frame 对象。

        world_obs["frame"] 是 FramePacket dataclass（含 .image / .intrinsics），
        控制器通过属性读取。research / realistic 模式下必须剥离 optional_gt，
        避免通过 frame 泄漏真值投影；若传入的是 dict 则做深拷贝并删除
        optional_gt。
        """
        if frame is None:
            return None
        if isinstance(frame, dict):
            result: dict = {}
            for k, v in frame.items():
                if k == "optional_gt":
                    continue
                if isinstance(v, np.ndarray):
                    result[k] = v.copy()
                elif isinstance(v, dict):
                    result[k] = copy.deepcopy(v)
                else:
                    result[k] = v
            return result
        if hasattr(frame, "image") and hasattr(frame, "intrinsics") and hasattr(frame, "optional_gt"):
            image = frame.image.copy() if isinstance(frame.image, np.ndarray) else frame.image
            intrinsics = copy.deepcopy(frame.intrinsics)
            return replace(frame, image=image, intrinsics=intrinsics, optional_gt=None)
        # 其它对象：保守深拷贝，避免控制程序修改污染原始数据
        return copy.deepcopy(frame)
