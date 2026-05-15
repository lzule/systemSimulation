"""仿真 app 层公共类型与常量。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from runtime.types import Detection, wrap_pm180

UI_TEXT = {
    "title": "完整实时仿真仪表盘（Raspi 闭环）",
    "start": "开始",
    "pause": "暂停",
    "reset": "重置",
    "save": "保存快照",
    "delay_label": "链路延时(ms)",
    "apply_delay": "应用延时",
    "running": "运行中",
    "paused": "已暂停",
    "reset_done": "已重置",
    "finished": "运行完成",
    "save_done": "已保存快照",
    "apply_delay_done": "已提交延时设置",
    "thread_error": "仿真线程异常",
    "fps": "UI FPS",
    "tab_core": "核心状态",
    "tab_diag": "诊断信息",
}

COLOR = {
    "bg": "#f6f7fb",
    "panel": "#ffffff",
    "border": "#d6dce7",
    "text_main": "#1f2a44",
    "text_sub": "#4b5f7a",
    "ok": "#2e7d32",
    "warn": "#c62828",
    "traj": "#1e5bb8",
    "target": "#c62828",
    "origin": "#2e7d32",
    "gimbal": "#f57c00",
    "fov": "#ffb74d",
    "center": "#008ba3",
    "err": "#1565c0",
    "rate": "#ad1457",
    "angle": "#00897b",
}


@dataclass
class AppConfig:
    duration_s: float
    mode: str
    delay_ms: float
    no_gui: bool
    control_program_path: str = ""      # "module:Class" 格式，空=默认 BaselineTrackerProgram
    target_type: str = ""               # 空=使用 config 默认
    waypoints: str = ""                 # "(x1,y1,z1,s1),(x2,y2,z2,s2)" 或 "(x1,y1,s1)"（z缺省为0），空=使用 config 默认


@dataclass
class FrameSample:
    timestamp: float
    image: np.ndarray
    intrinsics: dict[str, float]
    detection: Detection


# wrap_pm180 已统一到 runtime.types，此处从 runtime.types 导入
