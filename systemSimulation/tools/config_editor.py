"""PyQt5 配置编辑器 — 实体导航式，现代卡片 UI。"""

from __future__ import annotations

import dataclasses
import math
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Callable, get_args, get_origin

try:
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QFont
    from PyQt5.QtWidgets import (
        QApplication,
        QComboBox,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSplitter,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:
    raise SystemExit("未检测到 PyQt5，请安装：pip install PyQt5") from exc


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
import config as config_module  # noqa: E402

CONFIG_PATH = os.path.join(ROOT_DIR, "config.py")

# ── 配色 ──────────────────────────────────────────────

PALETTE = {
    "bg": "#F7F8FC",
    "sidebar_bg": "#FFFFFF",
    "sidebar_border": "#E5E7EB",
    "card_bg": "#FFFFFF",
    "card_border": "#E5E7EB",
    "card_header": "#F9FAFB",
    "text": "#1F2937",
    "text_secondary": "#6B7280",
    "text_muted": "#9CA3AF",
    "accent": "#3B82F6",
    "accent_light": "#EFF6FF",
    "success": "#10B981",
    "warn": "#F59E0B",
    "input_bg": "#F9FAFB",
    "input_border": "#D1D5DB",
    "input_focus": "#3B82F6",
    "derived_bg": "#F0FDF4",
    "derived_border": "#BBF7D0",
}

ENTITY_COLORS = {
    "target": "#EF4444",
    "gimbal": "#F59E0B",
    "camera": "#3B82F6",
    "raspi": "#8B5CF6",
    "scene": "#10B981",
}

ENTITY_ICONS = {
    "target": "T",
    "gimbal": "G",
    "camera": "C",
    "raspi": "R",
    "scene": "S",
}

ENTITY_DESCS = {
    "target": "目标运动参数",
    "gimbal": "云台控制与约束",
    "camera": "相机成像参数",
    "raspi": "树莓派延时链路",
    "scene": "仿真步长与可视化",
}


# ── 数据结构 ──────────────────────────────────────────

@dataclass(frozen=True)
class FieldMeta:
    desc: str
    suggestion: str = "按业务目标调整。"
    impact: str = "会影响相关行为。"


ENTITY_GROUPS = [
    {"key": "target", "label": "目标", "configs": ["target_cfg"]},
    {"key": "gimbal", "label": "云台", "configs": ["gimbal_cfg", "axis_limit_cfg", "loop_cfg", "control_preset_cfg", "yaw_display_cfg"]},
    {"key": "camera", "label": "相机", "configs": ["camera_cfg"]},
    {"key": "raspi", "label": "树莓派", "configs": ["raspi_cfg", "raspi_delay_cfg"]},
    {"key": "scene", "label": "场景", "configs": ["scene_cfg"]},
]

GROUP_TITLES = {
    "target_cfg": "目标运动",
    "gimbal_cfg": "云台基础参数",
    "axis_limit_cfg": "两轴约束",
    "loop_cfg": "控制频率",
    "control_preset_cfg": "控制预设",
    "yaw_display_cfg": "航向显示",
    "camera_cfg": "相机参数",
    "raspi_cfg": "树莓派配置",
    "raspi_delay_cfg": "延时链路",
    "scene_cfg": "场景与仿真",
}

FIELD_META: dict[tuple[str, str], FieldMeta] = {
    # ── target_cfg 目标运动 ──
    ("target_cfg", "motion_type"): FieldMeta(
        "目标运动模式",
        "sinusoidal = 正弦往复（验证跟踪带宽）; linear = 匀速直线; constant_accel = 匀加速; random = 随机游走; waypoint = 逐航点飞行",
        "决定目标轨迹的数学模型，直接影响跟踪难度和控制器负载",
    ),
    ("target_cfg", "initial_x_m"): FieldMeta(
        "目标初始 X 坐标（米）",
        "通常设为远处，如 100m，使目标在相机视场内",
        "改变目标初始空间位置，影响首帧跟踪误差",
    ),
    ("target_cfg", "initial_y_m"): FieldMeta(
        "目标初始 Y 坐标（米）",
        "设为 0 表示正前方，正值偏上，负值偏下",
        "与 initial_x_m 共同确定目标初始方位角",
    ),
    ("target_cfg", "velocity_x_mps"): FieldMeta(
        "X 方向初始速度（米/秒）",
        "linear/constant_accel 模式下生效，0 表示静止",
        "控制目标径向远离/接近速度",
    ),
    ("target_cfg", "velocity_y_mps"): FieldMeta(
        "Y 方向初始速度（米/秒）",
        "linear 模式典型值 1-3 m/s，过高会超出跟踪带宽",
        "控制目标切向运动速度，直接影响跟踪角速率需求",
    ),
    ("target_cfg", "accel_x_mps2"): FieldMeta(
        "X 方向加速度（米/秒²）",
        "constant_accel 模式下生效",
        "持续加速会让目标最终远离视场",
    ),
    ("target_cfg", "accel_y_mps2"): FieldMeta(
        "Y 方向加速度（米/秒²）",
        "constant_accel 模式典型值 0.1-0.5 m/s²",
        "越大目标切向加速越快，控制器越难跟上",
    ),
    ("target_cfg", "sin_amplitude_m"): FieldMeta(
        "正弦运动振幅（米）",
        "10-30m 适合验证，过大可能超出云台限位",
        "振幅越大，目标偏离中心越远，对云台角度范围要求越高",
    ),
    ("target_cfg", "sin_frequency_hz"): FieldMeta(
        "正弦运动频率（Hz）",
        "0.1-0.5Hz 适合常规验证；>1Hz 需要高带宽控制器",
        "频率越高目标运动越快，超出控制器带宽时跟踪误差急剧增大",
    ),
    ("target_cfg", "random_max_accel_mps2"): FieldMeta(
        "随机游走最大加速度（米/秒²）",
        "0.5-2.0 范围内选取，越大运动越剧烈",
        "控制随机轨迹的剧烈程度",
    ),
    ("target_cfg", "random_damping"): FieldMeta(
        "随机游走阻尼系数",
        "0.95-0.99，越接近 1 惯性越大",
        "越接近 1 运动越平滑持久，越小运动衰减越快",
    ),
    ("target_cfg", "random_seed"): FieldMeta(
        "随机种子",
        "固定种子可复现同一轨迹，便于对比实验",
        "相同种子产生完全相同的随机运动轨迹",
    ),
    ("target_cfg", "waypoints"): FieldMeta(
        "航点列表 [(x, y, speed), ...]",
        "speed > 0 表示以该速度飞向下一航点，speed = 0 表示悬停",
        "定义目标的完整飞行路线，目标按顺序逐点飞越",
    ),
    ("target_cfg", "waypoint_arrival_radius_m"): FieldMeta(
        "到达航点判定半径（米）",
        "0.5-2.0m，越小切换越精确但可能迟迟不触发",
        "目标进入此半径内即视为到达当前航点，切换到下一航点",
    ),

    # ── gimbal_cfg 云台基础参数 ──
    ("gimbal_cfg", "angle_min_deg"): FieldMeta(
        "云台角度最小值（度）",
        "按实际云台机械限位填写，典型 -90°",
        "超出此范围的角度会被裁剪到限位",
    ),
    ("gimbal_cfg", "angle_max_deg"): FieldMeta(
        "云台角度最大值（度）",
        "按实际云台机械限位填写，典型 +90°",
        "超出此范围的角度会被裁剪到限位",
    ),
    ("gimbal_cfg", "max_velocity_dps"): FieldMeta(
        "云台最大角速度（度/秒）",
        "按云台规格书峰值角速度填写",
        "限制云台转向速率，超出此值的命令会被饱和",
    ),
    ("gimbal_cfg", "response_tau_s"): FieldMeta(
        "云台响应时间常数 τ（秒）",
        "一阶滞后模型参数，真实硬件约 0.02-0.05s",
        "τ 越大云台响应越迟钝，引入额外相位延迟",
    ),
    ("gimbal_cfg", "initial_angle_deg"): FieldMeta(
        "云台初始角度（度）",
        "0° 表示正前方",
        "仿真开始时云台的朝向角度",
    ),

    # ── axis_limit_cfg 两轴约束 ──
    ("axis_limit_cfg", "pitch_min_deg"): FieldMeta(
        "俯仰轴最小角度（度）",
        "按真实硬件限位填写，典型 -135°",
        "俯仰角不会低于此值",
    ),
    ("axis_limit_cfg", "pitch_max_deg"): FieldMeta(
        "俯仰轴最大角度（度）",
        "按真实硬件限位填写，典型 +90°",
        "俯仰角不会高于此值",
    ),
    ("axis_limit_cfg", "max_rate_dps"): FieldMeta(
        "两轴最大角速率（度/秒）",
        "按规格书峰值速率设置",
        "Yaw/Pitch 角速率指令的上限",
    ),

    # ── loop_cfg 控制频率 ──
    ("loop_cfg", "angle_loop_hz"): FieldMeta(
        "角度外环频率（Hz）",
        "通常 50Hz，需 ≤ rate_loop_hz 的 1/2",
        "外环每个周期计算一次角度误差，输出目标角速率给内环",
    ),
    ("loop_cfg", "rate_loop_hz"): FieldMeta(
        "角速度内环频率（Hz）",
        "通常 200Hz，保持 ≥ 4× angle_loop_hz",
        "内环每个周期计算一次角速率误差，输出电机指令",
    ),

    # ── control_preset_cfg PID 控制预设 ──
    ("control_preset_cfg", "angle_kp_yaw"): FieldMeta(
        "角度外环 Yaw 比例增益",
        "从小值开始调，出现振荡则降低，跟踪慢则升高",
        "将角度误差转换为目标角速率，过大导致振荡",
    ),
    ("control_preset_cfg", "angle_kp_pitch"): FieldMeta(
        "角度外环 Pitch 比例增益",
        "通常与 angle_kp_yaw 相同，如有非对称负载可不同",
        "将俯仰角度误差转换为目标角速率",
    ),
    ("control_preset_cfg", "rate_kp_yaw"): FieldMeta(
        "角速度内环 Yaw 比例增益",
        "主要控制参数，1.0-3.0 范围调整",
        "将角速率误差转换为电机指令的瞬时响应分量",
    ),
    ("control_preset_cfg", "rate_ki_yaw"): FieldMeta(
        "角速度内环 Yaw 积分增益",
        "消除稳态误差，典型值 2.0-8.0，过大会导致积分饱和",
        "累积角速率误差消除静差，过大导致超调和振荡",
    ),
    ("control_preset_cfg", "rate_kp_pitch"): FieldMeta(
        "角速度内环 Pitch 比例增益",
        "通常与 rate_kp_yaw 相同",
        "俯仰轴角速率的比例响应分量",
    ),
    ("control_preset_cfg", "rate_ki_pitch"): FieldMeta(
        "角速度内环 Pitch 积分增益",
        "通常与 rate_ki_yaw 相同",
        "俯仰轴角速率的积分消除静差分量",
    ),
    ("control_preset_cfg", "rate_integral_limit"): FieldMeta(
        "角速率积分限幅值",
        "设为 actuator_cmd_limit 的 50%-100%",
        "防止积分项过大导致执行器饱和和积分发散",
    ),
    ("control_preset_cfg", "actuator_cmd_limit_dps"): FieldMeta(
        "执行器指令上限（度/秒）",
        "与 max_rate_dps 保持一致或略大",
        "PID 输出指令的绝对值上限，超出会被饱和裁剪",
    ),

    # ── yaw_display_cfg 航向显示 ──
    ("yaw_display_cfg", "default_mode"): FieldMeta(
        "航向角显示模式",
        "0_360 = [0°, 360°)；pm180 = [-180°, 180°)",
        "影响所有可视化图表中 Yaw 轴的数值范围",
    ),

    # ── camera_cfg 相机参数 ──
    ("camera_cfg", "resolution_w"): FieldMeta(
        "传感器水平分辨率（像素）",
        "按实际相机输出分辨率填写",
        "影响像元尺寸、FOV 计算和像素误差分辨率",
    ),
    ("camera_cfg", "resolution_h"): FieldMeta(
        "传感器垂直分辨率（像素）",
        "按实际相机输出分辨率填写",
        "影响像元尺寸和垂直 FOV",
    ),
    ("camera_cfg", "sensor_w_mm"): FieldMeta(
        "传感器宽度（毫米）",
        "按传感器规格书的感光面尺寸填写",
        "与焦距共同决定 FOV 和像素尺度",
    ),
    ("camera_cfg", "sensor_h_mm"): FieldMeta(
        "传感器高度（毫米）",
        "按传感器规格书的感光面尺寸填写",
        "影响垂直 FOV 计算",
    ),
    ("camera_cfg", "focal_length_mm"): FieldMeta(
        "当前焦距（毫米）",
        "增大焦距 → 视场角变小 → 像素误差放大（望远效果）",
        "直接影响 FOV、焦距像素值、每度像素数等所有光学参数",
    ),
    ("camera_cfg", "focal_min_mm"): FieldMeta(
        "最小焦距（毫米）",
        "变焦镜头的最短焦距，定焦镜头与 focal_length_mm 相同",
        "用于焦距搜索范围的下界",
    ),
    ("camera_cfg", "focal_max_mm"): FieldMeta(
        "最大焦距（毫米）",
        "变焦镜头的最长焦距，定焦镜头与 focal_length_mm 相同",
        "用于焦距搜索范围的上界",
    ),

    # ── raspi_cfg 树莓派配置 ──
    ("raspi_cfg", "boot_delay_s"): FieldMeta(
        "树莓派启动延时（秒）",
        "模拟真实硬件从上电到就绪的时间，通常 0.5-2.0s",
        "树莓派实体在此时间内不响应任何指令",
    ),
    ("raspi_cfg", "enabled"): FieldMeta(
        "是否启用树莓派数字孪生",
        "关闭后仿真跳过树莓派延时链路",
        "关闭时观测和命令传输无延时，适合纯 PID 调试",
    ),

    # ── raspi_delay_cfg 延时链路 ──
    ("raspi_delay_cfg", "image_read_delay_s"): FieldMeta(
        "图像读取延时（秒）",
        "传感器曝光+传输时间，通常 5-15ms",
        "观测数据经过此延时后才进入处理管线",
    ),
    ("raspi_delay_cfg", "image_process_delay_s"): FieldMeta(
        "图像处理延时（秒）",
        "目标检测+跟踪算法耗时，真实硬件约 15-30ms",
        "影响观测时间戳的延迟，直接降低跟踪实时性",
    ),
    ("raspi_delay_cfg", "state_read_delay_s"): FieldMeta(
        "状态读取延时（秒）",
        "读取云台当前角度的通信延时",
        "控制器基于延时的状态做决策，引入额外滞后",
    ),
    ("raspi_delay_cfg", "command_tx_delay_s"): FieldMeta(
        "命令发送延时（秒）",
        "控制指令从发送到执行的传输延时",
        "指令到达云台前的最后一段延迟",
    ),
    ("raspi_delay_cfg", "jitter_std_s"): FieldMeta(
        "延时抖动标准差（秒）",
        "模拟真实系统的随机延时波动，0 表示无抖动",
        "抖动使跟踪性能出现随机波动，增加分析难度",
    ),

    # ── scene_cfg 场景与仿真 ──
    ("scene_cfg", "dt_s"): FieldMeta(
        "仿真步长（秒）",
        "0.002-0.01s，越小精度越高但计算越慢",
        "每个仿真 tick 的时间间隔，影响数值积分精度",
    ),
    ("scene_cfg", "duration_s"): FieldMeta(
        "仿真总时长（秒）",
        "按需设置，调参时可用 10-20s 快速验证",
        "仿真运行的总物理时间",
    ),
    ("scene_cfg", "anim_fps"): FieldMeta(
        "实时动画帧率（FPS）",
        "20-60fps，帧率越高动画越流畅",
        "控制 matplotlib 实时动画的刷新频率",
    ),
    ("scene_cfg", "gif_fps"): FieldMeta(
        "GIF 输出帧率（FPS）",
        "10-20fps，过高导致文件体积大",
        "保存为 GIF 时的播放帧率",
    ),
    ("scene_cfg", "trail_length_s"): FieldMeta(
        "轨迹拖尾时长（秒）",
        "2-8s，越长轨迹越完整但画面越密集",
        "动画中保留的历史轨迹长度",
    ),
    ("scene_cfg", "plot_window_s"): FieldMeta(
        "时序图时间窗口（秒）",
        "5-15s，窗口越大一次看到更多历史数据",
        "实时图表的滚动时间范围",
    ),
    ("scene_cfg", "world_view_range_m"): FieldMeta(
        "世界视图范围（米）",
        "按目标运动范围设置，如 150m",
        "2D 世界俯视图的显示半径",
    ),
    ("scene_cfg", "pixel_noise_std"): FieldMeta(
        "像素观测噪声标准差（像素）",
        "0 表示无噪声，0.5-2.0 模拟真实传感器噪声",
        "在观测中叠加高斯噪声，测试控制器抗扰能力",
    ),
}

DERIVED_FIELDS: list[tuple[str, str, str, Callable[[], Any], str]] = [
    ("camera_cfg", "pixel_size_um", "um", lambda: config_module.camera_cfg.pixel_size_mm * 1000.0, "像元尺寸"),
    ("camera_cfg", "focal_length_px", "px", lambda: config_module.camera_cfg.focal_length_px, "焦距像素值"),
    ("camera_cfg", "fov_h_deg", "deg", lambda: config_module.camera_cfg.fov_h_deg, "水平视场角"),
    ("camera_cfg", "px_per_deg", "px/deg", lambda: config_module.camera_cfg.px_per_deg, "每度像素数"),
]

UNIT_HINTS = {
    "_s": "秒", "_hz": "Hz", "_deg": "度", "_dps": "度/秒",
    "_m": "米", "_mps": "米/秒", "_mps2": "米/秒²",
    "_mm": "毫米", "_px": "像素",
}


# ── 工具函数 ──────────────────────────────────────────

def _field_unit(field_name: str) -> str:
    for suffix, unit in UNIT_HINTS.items():
        if field_name.endswith(suffix):
            return unit
    return "-"

def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)

def _literal_options(field_type: Any) -> list[str] | None:
    if get_origin(field_type) is None:
        return None
    args = get_args(field_type)
    if args and all(isinstance(v, str) for v in args):
        return list(args)
    return None

def _instance_defs() -> list[tuple[str, Any]]:
    instances = []
    for name, value in vars(config_module).items():
        if name.endswith("_cfg") and dataclasses.is_dataclass(value):
            instances.append((name, value))
    instances.sort(key=lambda x: x[0])
    return instances

def _parse_value(raw: str, current: Any, options: list[str] | None) -> Any:
    raw = raw.strip()
    if options is not None:
        if raw not in options:
            raise ValueError(f"必须在 {options} 中选择")
        return raw
    if isinstance(current, bool):
        low = raw.lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
        raise ValueError("布尔值: true/false")
    if isinstance(current, int) and not isinstance(current, bool):
        return int(raw)
    if isinstance(current, float):
        return float(raw)
    return raw

def _value_repr(value: Any) -> str:
    if isinstance(value, str):
        return f'"{value}"'
    return repr(value)


# ── 实体导航按钮 ──────────────────────────────────────

class EntityButton(QWidget):
    clicked = None  # will use mousePressEvent

    def __init__(self, entity_key: str, label: str, parent=None):
        super().__init__(parent)
        self.entity_key = entity_key
        self._selected = False
        self.setFixedHeight(64)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        color = ENTITY_COLORS.get(entity_key, "#888")
        icon_char = ENTITY_ICONS.get(entity_key, "?")

        icon_label = QLabel(icon_char)
        icon_label.setFixedSize(36, 36)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet(f"""
            background: {color}18; color: {color};
            border-radius: 8px; font-size: 15pt; font-weight: 700;
        """)
        layout.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        name = QLabel(label)
        name.setStyleSheet(f"font-size: 11pt; font-weight: 600; color: {PALETTE['text']}; border: none;")
        text_col.addWidget(name)
        desc = QLabel(ENTITY_DESCS.get(entity_key, ""))
        desc.setStyleSheet(f"font-size: 8pt; color: {PALETTE['text_muted']}; border: none;")
        text_col.addWidget(desc)
        layout.addLayout(text_col, 1)

        self._color = color

    def set_selected(self, selected: bool):
        self._selected = selected
        if selected:
            self.setStyleSheet(f"""
                QWidget {{ background: {PALETTE['accent_light']}; border: none; border-left: 3px solid {PALETTE['accent']}; }}
            """)
        else:
            self.setStyleSheet("QWidget { background: transparent; border: none; border-left: 3px solid transparent; }")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.parent():
            main_window = self.window()
            if isinstance(main_window, ConfigEditorWindow):
                main_window.select_entity(self.entity_key)
        super().mousePressEvent(event)


# ── 参数行 ──────────────────────────────────────────────

class ParamRow(QWidget):
    def __init__(self, group_key: str, field_name: str, current_value: Any,
                 unit: str, fmeta: FieldMeta, literal_options: list[str] | None,
                 is_derived: bool, on_changed: Callable[[], None]):
        super().__init__()
        self.group_key = group_key
        self.field_name = field_name
        self.current_value = current_value
        self.literal_options = literal_options
        self.is_derived = is_derived
        self._on_changed = on_changed
        self._detail_visible = False
        self._val_label = None

        bg = PALETTE["derived_bg"] if is_derived else "transparent"
        border = PALETTE["derived_border"] if is_derived else "transparent"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(0)

        self.setStyleSheet(f"ParamRow {{ background: {bg}; border-radius: 4px; }}")

        main_row = QHBoxLayout()
        main_row.setSpacing(12)

        # 字段名
        name_label = QLabel(field_name)
        name_label.setFixedWidth(200)
        name_label.setStyleSheet(f"""
            font-size: 10pt; font-weight: 600; color: {PALETTE['text']};
            font-family: 'Consolas', 'Courier New', monospace;
        """)
        main_row.addWidget(name_label)

        # 值编辑器
        if is_derived:
            self.editor = None
            val_label = QLabel(_format_value(current_value))
            val_label.setStyleSheet(f"""
                font-size: 10pt; color: {PALETTE['success']}; font-weight: 600;
                background: {PALETTE['derived_bg']}; border: 1px solid {PALETTE['derived_border']};
                border-radius: 4px; padding: 4px 8px;
            """)
            val_label.setFixedWidth(160)
            main_row.addWidget(val_label)
            self._val_label = val_label
        elif literal_options:
            self.editor = QComboBox()
            for opt in literal_options:
                self.editor.addItem(opt)
            idx = literal_options.index(current_value) if current_value in literal_options else 0
            self.editor.setCurrentIndex(idx)
            self.editor.currentTextChanged.connect(lambda _: on_changed())
            self.editor.setFixedWidth(160)
            self.editor.setStyleSheet(f"""
                QComboBox {{
                    font-size: 10pt; padding: 4px 8px; border: 1px solid {PALETTE['input_border']};
                    border-radius: 4px; background: {PALETTE['input_bg']}; color: {PALETTE['text']};
                }}
                QComboBox:focus {{ border: 1px solid {PALETTE['input_focus']}; }}
            """)
            main_row.addWidget(self.editor)
        else:
            self.editor = QLineEdit(_format_value(current_value))
            self.editor.setFixedWidth(160)
            self.editor.textChanged.connect(lambda _: on_changed())
            self.editor.setStyleSheet(f"""
                QLineEdit {{
                    font-size: 10pt; padding: 4px 8px; border: 1px solid {PALETTE['input_border']};
                    border-radius: 4px; background: {PALETTE['input_bg']}; color: {PALETTE['text']};
                }}
                QLineEdit:focus {{ border: 1px solid {PALETTE['input_focus']}; }}
            """)
            main_row.addWidget(self.editor)

        # 单位
        unit_label = QLabel(unit)
        unit_label.setFixedWidth(50)
        unit_label.setStyleSheet(f"font-size: 9pt; color: {PALETTE['text_muted']};")
        main_row.addWidget(unit_label)

        # 一句话说明
        desc_text = fmeta.desc
        desc_label = QLabel(desc_text)
        desc_label.setStyleSheet(f"font-size: 9pt; color: {PALETTE['text_secondary']};")
        desc_label.setWordWrap(True)
        main_row.addWidget(desc_label, 1)

        # 展开箭头
        if not is_derived:
            self._arrow = QLabel("▸")
            self._arrow.setFixedWidth(16)
            self._arrow.setStyleSheet(f"font-size: 10pt; color: {PALETTE['text_muted']};")
            main_row.addWidget(self._arrow)

        layout.addLayout(main_row)

        # 展开详情区
        if not is_derived:
            self.detail_widget = QWidget()
            detail_layout = QVBoxLayout(self.detail_widget)
            detail_layout.setContentsMargins(212, 2, 12, 2)
            detail_layout.setSpacing(2)
            for text in [f"💡 取值建议: {fmeta.suggestion}", f"⚠ 影响范围: {fmeta.impact}"]:
                lbl = QLabel(text)
                lbl.setStyleSheet(f"font-size: 9pt; color: {PALETTE['text_muted']};")
                lbl.setWordWrap(True)
                detail_layout.addWidget(lbl)
            self.detail_widget.hide()
            layout.addWidget(self.detail_widget)

            self.setCursor(Qt.PointingHandCursor)

        # 悬停效果
        self._hover = False

    def enterEvent(self, event):
        if not self.is_derived:
            self._hover = True
            self.setStyleSheet(f"ParamRow {{ background: {PALETTE['card_header']}; border-radius: 4px; }}")
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self.is_derived:
            self._hover = False
            self.setStyleSheet(f"ParamRow {{ background: transparent; border-radius: 4px; }}")
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.is_derived:
            self._detail_visible = not self._detail_visible
            self.detail_widget.setVisible(self._detail_visible)
            self._arrow.setText("▾" if self._detail_visible else "▸")
        super().mousePressEvent(event)

    def get_edit_value(self) -> str:
        if self.is_derived:
            return _format_value(self.current_value)
        if isinstance(self.editor, QComboBox):
            return self.editor.currentText()
        return self.editor.text().strip()

    def parse_edit_value(self) -> Any:
        return _parse_value(self.get_edit_value(), self.current_value, self.literal_options)

    def update_derived_display(self, value: Any):
        self.current_value = value
        if self._val_label:
            self._val_label.setText(_format_value(value))


# ── 主窗口 ──────────────────────────────────────────────

class ConfigEditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("配置编辑器")
        self.resize(1200, 760)
        self.setMinimumSize(960, 600)
        self.setStyleSheet(f"QMainWindow {{ background: {PALETTE['bg']}; }}")

        self._instances = {name: inst for name, inst in _instance_defs()}
        self._param_rows: dict[tuple[str, str], ParamRow] = {}
        self._entity_buttons: dict[str, EntityButton] = {}

        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 左侧边栏 ──
        sidebar = QWidget()
        sidebar.setFixedWidth(180)
        sidebar.setStyleSheet(f"""
            QWidget {{ background: {PALETTE['sidebar_bg']}; border-right: 1px solid {PALETTE['sidebar_border']}; }}
        """)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 16, 0, 16)
        sidebar_layout.setSpacing(4)

        title = QLabel("实体配置")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"""
            font-size: 13pt; font-weight: 700; color: {PALETTE['text']};
            padding: 8px; border: none;
        """)
        sidebar_layout.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {PALETTE['sidebar_border']}; border: none;")
        sidebar_layout.addWidget(sep)

        for eg in ENTITY_GROUPS:
            btn = EntityButton(eg["key"], eg["label"], sidebar)
            sidebar_layout.addWidget(btn)
            self._entity_buttons[eg["key"]] = btn

        sidebar_layout.addStretch()
        root.addWidget(sidebar)

        # ── 右侧内容区 ──
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 16)
        content_layout.setSpacing(12)

        # 顶部标题
        self._entity_title = QLabel("目标")
        self._entity_title.setStyleSheet(f"font-size: 16pt; font-weight: 700; color: {PALETTE['text']}; border: none;")
        content_layout.addWidget(self._entity_title)

        # 滚动区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: {PALETTE['bg']}; }}
            QScrollBar:vertical {{
                background: transparent; width: 6px; border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {PALETTE['sidebar_border']}; border-radius: 3px; min-height: 30px;
            }}
        """)
        self.param_panel = QWidget()
        self.param_panel.setStyleSheet(f"background: {PALETTE['bg']};")
        self.param_layout = QVBoxLayout(self.param_panel)
        self.param_layout.setContentsMargins(0, 0, 8, 0)
        self.param_layout.setSpacing(16)
        self.param_layout.addStretch()
        scroll.setWidget(self.param_panel)
        content_layout.addWidget(scroll, 1)

        # 底部按钮栏
        btn_bar = QWidget()
        btn_bar.setStyleSheet(f"background: {PALETTE['bg']}; border: none;")
        btn_layout = QHBoxLayout(btn_bar)
        btn_layout.setContentsMargins(0, 8, 0, 0)
        btn_layout.addStretch()

        for text, slot, primary in [
            ("保存并关闭", self._save, True),
            ("恢复默认", self._reset, False),
            ("取消", self.close, False),
        ]:
            btn = QPushButton(text)
            btn.setMinimumWidth(110)
            btn.setCursor(Qt.PointingHandCursor)
            if primary:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {PALETTE['accent']}; color: white;
                        border: none; border-radius: 6px; padding: 8px 20px;
                        font-size: 10pt; font-weight: 600;
                    }}
                    QPushButton:hover {{ background: #2563EB; }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: white; color: {PALETTE['text']};
                        border: 1px solid {PALETTE['input_border']}; border-radius: 6px;
                        padding: 8px 20px; font-size: 10pt;
                    }}
                    QPushButton:hover {{ background: {PALETTE['card_header']}; }}
                """)
            btn.clicked.connect(slot)
            btn_layout.addWidget(btn)

        content_layout.addWidget(btn_bar)
        root.addWidget(content, 1)

        # 默认选中
        self.select_entity("target")

    def select_entity(self, entity_key: str):
        for key, btn in self._entity_buttons.items():
            btn.set_selected(key == entity_key)

        eg = next((e for e in ENTITY_GROUPS if e["key"] == entity_key), None)
        if eg is None:
            return

        color = ENTITY_COLORS.get(entity_key, PALETTE["accent"])
        self._entity_title.setText(eg["label"])
        self._entity_title.setStyleSheet(f"""
            font-size: 16pt; font-weight: 700; color: {PALETTE['text']}; border: none;
            border-bottom: 2px solid {color}; padding-bottom: 6px;
        """)
        self._show_entity(eg)

    def _show_entity(self, entity: dict):
        while self.param_layout.count() > 1:
            item = self.param_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._param_rows.clear()

        for cfg_key in entity["configs"]:
            instance = self._instances.get(cfg_key)
            if instance is None:
                continue
            title = GROUP_TITLES.get(cfg_key, cfg_key)

            # 卡片
            card = QWidget()
            card.setStyleSheet(f"""
                QWidget {{ background: {PALETTE['card_bg']}; border: 1px solid {PALETTE['card_border']};
                            border-radius: 8px; }}
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(0, 0, 0, 8)
            card_layout.setSpacing(0)

            # 卡片标题
            header = QLabel(f"  {title}")
            header.setStyleSheet(f"""
                background: {PALETTE['card_header']}; color: {PALETTE['text']};
                font-size: 11pt; font-weight: 600; padding: 10px 12px;
                border-bottom: 1px solid {PALETTE['card_border']};
                border-top-left-radius: 8px; border-top-right-radius: 8px;
            """)
            card_layout.addWidget(header)

            # 参数行
            for field in dataclasses.fields(instance):
                value = getattr(instance, field.name)
                fmeta = FIELD_META.get((cfg_key, field.name), FieldMeta(field.name))
                row = ParamRow(
                    cfg_key, field.name, value, _field_unit(field.name),
                    fmeta, _literal_options(field.type), False,
                    on_changed=self._refresh_derived,
                )
                card_layout.addWidget(row)
                self._param_rows[(cfg_key, field.name)] = row

            # 派生字段
            derived = [(gk, n, u, fn, d) for gk, n, u, fn, d in DERIVED_FIELDS if gk == cfg_key]
            if derived:
                sep = QFrame()
                sep.setFrameShape(QFrame.HLine)
                sep.setStyleSheet(f"color: {PALETTE['derived_border']}; margin: 4px 12px;")
                card_layout.addWidget(sep)
                derived_header = QLabel("  派生参数（只读）")
                derived_header.setStyleSheet(f"""
                    font-size: 9pt; font-weight: 600; color: {PALETTE['success']};
                    padding: 4px 12px; background: transparent; border: none;
                """)
                card_layout.addWidget(derived_header)
                for _, name, unit, getter, desc in derived:
                    row = ParamRow(
                        cfg_key, name, getter(), unit,
                        FieldMeta(desc), None, True,
                        on_changed=lambda: None,
                    )
                    card_layout.addWidget(row)

            self.param_layout.insertWidget(self.param_layout.count() - 1, card)

            # target_cfg: 按 motion_type 动态过滤参数行
            if cfg_key == "target_cfg":
                motion_row = self._param_rows.get(("target_cfg", "motion_type"))
                if motion_row and isinstance(motion_row.editor, QComboBox):
                    motion_row.editor.currentTextChanged.connect(self._apply_motion_filter)
                    self._apply_motion_filter(motion_row.editor.currentText())

    def _apply_motion_filter(self, motion_type: str):
        mode_params = getattr(config_module, "MOTION_MODE_PARAMS", {})
        visible_fields = set(mode_params.get(motion_type, []))
        for (_, fname), row in self._param_rows.items():
            if row.group_key != "target_cfg":
                continue
            if fname in ("motion_type", "initial_x_m", "initial_y_m"):
                continue
            row.setVisible(fname in visible_fields)

    def _refresh_derived(self):
        for (_, name), row in self._param_rows.items():
            if row.is_derived:
                for gk, n, _, getter, _ in DERIVED_FIELDS:
                    if row.group_key == gk and row.field_name == n:
                        row.update_derived_display(getter())

    def _collect_updates(self) -> tuple[dict[tuple[str, str], Any], list[str]]:
        updates, errors = {}, []
        for key, row in self._param_rows.items():
            if row.is_derived:
                continue
            try:
                updates[key] = row.parse_edit_value()
            except Exception as exc:
                errors.append(f"{row.group_key}.{row.field_name}: {exc}")
        return updates, errors

    def _write_back(self, updates: dict[tuple[str, str], Any]) -> None:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        for (_, field_name), value in updates.items():
            replacement = _value_repr(value)
            pattern = r"(?m)^([ \t]*" + re.escape(field_name) + r"\s*:\s*[^=\n]+=\s*)([^\n#]+)(\s*(?:#.*)?$)"
            content, n = re.subn(
                pattern,
                lambda m: f"{m.group(1)}{replacement}{m.group(3)}",
                content, count=1,
            )
            if n == 0:
                raise RuntimeError(f"回写失败：未找到字段 {field_name}")
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(content)

    def _save(self):
        updates, errors = self._collect_updates()
        if errors:
            QMessageBox.critical(self, "参数校验失败", "\n".join(errors[:10]))
            return
        changed = {k: v for k, v in updates.items()
                   if k in self._param_rows and v != self._param_rows[k].current_value}
        if not changed:
            QMessageBox.information(self, "无需保存", "参数未发生变化。")
            return
        try:
            self._write_back(changed)
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        lines = [f"  {k[1]}: {_format_value(self._param_rows[k].current_value)} → {_format_value(v)}"
                 for k, v in list(changed.items())[:15]]
        QMessageBox.information(self, "保存成功", "已写入 config.py\n\n" + "\n".join(lines))
        self.close()

    def _reset(self):
        if QMessageBox.question(self, "确认", "恢复所有参数为默认值？") != QMessageBox.Yes:
            return
        defaults = {name: type(inst)() for name, inst in self._instances.items()}
        for key, row in self._param_rows.items():
            if row.is_derived:
                continue
            default_obj = defaults.get(row.group_key)
            if default_obj:
                default_val = getattr(default_obj, row.field_name)
                if isinstance(row.editor, QComboBox):
                    idx = row.editor.findText(default_val)
                    if idx >= 0:
                        row.editor.setCurrentIndex(idx)
                else:
                    row.editor.setText(_format_value(default_val))
        self._refresh_derived()


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    window = ConfigEditorWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
