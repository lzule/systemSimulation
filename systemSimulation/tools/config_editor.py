"""PyQt5 配置编辑器 — 以实体为单位导航，参数卡片内联展开。"""

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
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
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
    ("target_cfg", "motion_type"): FieldMeta("目标运动类型。", "sinusoidal 适合验证跟踪；waypoint 适合自定义轨迹。"),
    ("target_cfg", "sin_amplitude_m"): FieldMeta("正弦运动振幅。", "越大目标偏离越远，跟踪越难。"),
    ("target_cfg", "sin_frequency_hz"): FieldMeta("正弦运动频率。", "越高运动越快，对控制带宽要求越高。"),
    ("target_cfg", "waypoints"): FieldMeta("航点列表，格式 [(x, y, speed), ...]。", "speed=0 表示悬停。"),
    ("target_cfg", "waypoint_arrival_radius_m"): FieldMeta("到达航点的判定半径。", "越小精度越高但切换越慢。"),
    ("axis_limit_cfg", "pitch_min_deg"): FieldMeta("俯仰最小角度。", "按真实硬件限位填写。"),
    ("axis_limit_cfg", "pitch_max_deg"): FieldMeta("俯仰最大角度。", "按真实硬件限位填写。"),
    ("axis_limit_cfg", "max_rate_dps"): FieldMeta("两轴角速度上限。", "按规格书峰值速率设置。"),
    ("loop_cfg", "angle_loop_hz"): FieldMeta("角度外环频率。", "通常 50Hz。"),
    ("loop_cfg", "rate_loop_hz"): FieldMeta("角速度内环频率。", "通常 200Hz，保持高于外环。"),
    ("control_preset_cfg", "angle_kp_yaw"): FieldMeta("角度外环 Yaw 比例增益。", "越大跟踪越快但可能振荡。"),
    ("control_preset_cfg", "rate_kp_yaw"): FieldMeta("角速度内环 Yaw 比例增益。"),
    ("control_preset_cfg", "rate_ki_yaw"): FieldMeta("角速度内环 Yaw 积分增益。", "消除稳态误差。"),
    ("raspi_delay_cfg", "image_read_delay_s"): FieldMeta("读取观测延时。"),
    ("raspi_delay_cfg", "image_process_delay_s"): FieldMeta("图像处理/算法延时。", "真实硬件约 20ms。"),
    ("raspi_delay_cfg", "command_tx_delay_s"): FieldMeta("命令发送延时。"),
    ("raspi_delay_cfg", "jitter_std_s"): FieldMeta("延时抖动标准差。"),
    ("scene_cfg", "dt_s"): FieldMeta("仿真步长。", "越小精度越高但计算越慢。"),
    ("scene_cfg", "duration_s"): FieldMeta("仿真总时长。"),
    ("camera_cfg", "focal_length_mm"): FieldMeta("当前焦距。", "增大焦距 → 视场角变小 → 同一角度偏移对应更大像素误差。"),
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


# ── 参数行组件 ──────────────────────────────────────────

class ParamRow(QWidget):
    """单参数行：名称 + 值编辑器 + 单位 + 一句话说明，点击展开详情。"""

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
        self._expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(0)

        # 主行
        main_row = QHBoxLayout()
        main_row.setSpacing(8)

        name_label = QLabel(field_name)
        name_label.setFixedWidth(180)
        name_label.setStyleSheet("font-weight: 600; font-size: 11pt;")
        main_row.addWidget(name_label)

        if is_derived:
            val_label = QLabel(_format_value(current_value))
            val_label.setStyleSheet("color: #666; font-size: 11pt;")
            main_row.addWidget(val_label)
        elif literal_options:
            self.editor = QComboBox()
            for opt in literal_options:
                self.editor.addItem(opt)
            idx = literal_options.index(current_value) if current_value in literal_options else 0
            self.editor.setCurrentIndex(idx)
            self.editor.currentTextChanged.connect(lambda _: on_changed())
            self.editor.setFixedWidth(160)
            main_row.addWidget(self.editor)
        else:
            self.editor = QLineEdit(_format_value(current_value))
            self.editor.setFixedWidth(160)
            self.editor.setStyleSheet("font-size: 11pt;")
            self.editor.textChanged.connect(lambda _: on_changed())
            main_row.addWidget(self.editor)

        unit_label = QLabel(unit)
        unit_label.setFixedWidth(60)
        unit_label.setStyleSheet("color: #888; font-size: 10pt;")
        main_row.addWidget(unit_label)

        desc_label = QLabel(fmeta.desc.split("。")[0] if fmeta.desc else "")
        desc_label.setStyleSheet("color: #666; font-size: 9pt;")
        desc_label.setWordWrap(True)
        main_row.addWidget(desc_label, 1)

        layout.addLayout(main_row)

        # 展开详情
        self.detail_widget = QWidget()
        detail_layout = QVBoxLayout(self.detail_widget)
        detail_layout.setContentsMargins(188, 2, 4, 2)
        detail_layout.setSpacing(1)

        for text in [f"取值建议: {fmeta.suggestion}", f"影响范围: {fmeta.impact}"]:
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #888; font-size: 9pt;")
            lbl.setWordWrap(True)
            detail_layout.addWidget(lbl)
        self.detail_widget.hide()
        layout.addWidget(self.detail_widget)

        # 点击展开/折叠
        self.setCursor(Qt.PointingHandCursor)
        self._detail_visible = False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._detail_visible = not self._detail_visible
            self.detail_widget.setVisible(self._detail_visible)
        super().mousePressEvent(event)

    def get_edit_value(self) -> str:
        if self.is_derived:
            return _format_value(self.current_value)
        if isinstance(self.editor, QComboBox):
            return self.editor.currentText()
        return self.editor.text().strip()

    def parse_edit_value(self) -> Any:
        raw = self.get_edit_value()
        return _parse_value(raw, self.current_value, self.literal_options)


# ── 主窗口 ──────────────────────────────────────────

class ConfigEditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("配置编辑器")
        self.resize(1100, 720)
        self.setMinimumSize(900, 600)

        self._instances = {name: inst for name, inst in _instance_defs()}
        self._param_rows: dict[tuple[str, str], ParamRow] = {}

        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        splitter = QSplitter(Qt.Horizontal)

        # 左侧实体列表
        self.entity_list = QListWidget()
        self.entity_list.setFixedWidth(120)
        self.entity_list.setStyleSheet("""
            QListWidget { font-size: 12pt; border: 1px solid #d0d0d0; border-radius: 4px; }
            QListWidget::item { padding: 10px 8px; }
            QListWidget::item:selected { background: #dbeafe; color: #1a1a1a; }
        """)
        for eg in ENTITY_GROUPS:
            item = QListWidgetItem(eg["label"])
            item.setData(Qt.UserRole, eg["key"])
            self.entity_list.addItem(item)
        self.entity_list.currentRowChanged.connect(self._on_entity_selected)
        splitter.addWidget(self.entity_list)

        # 右侧参数面板
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        self.param_panel = QWidget()
        self.param_layout = QVBoxLayout(self.param_panel)
        self.param_layout.setContentsMargins(8, 8, 8, 8)
        self.param_layout.setSpacing(12)
        self.param_layout.addStretch()
        scroll.setWidget(self.param_panel)
        splitter.addWidget(scroll)
        splitter.setSizes([120, 960])

        root.addWidget(splitter, 1)

        # 按钮栏
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        for text, slot in [("保存并关闭", self._save), ("恢复默认", self._reset), ("取消", self.close)]:
            btn = QPushButton(text)
            btn.setMinimumWidth(110)
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)
        root.addLayout(btn_row)

        # 默认选中第一个
        self.entity_list.setCurrentRow(0)

    def _on_entity_selected(self, row: int):
        if row < 0 or row >= len(ENTITY_GROUPS):
            return
        eg = ENTITY_GROUPS[row]
        self._show_entity(eg)

    def _show_entity(self, entity: dict):
        # 清空面板
        while self.param_layout.count() > 1:
            item = self.param_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._param_rows.clear()

        for cfg_key in entity["configs"]:
            instance = self._instances.get(cfg_key)
            if instance is None:
                continue
            gmeta = GROUP_TITLES.get(cfg_key, cfg_key)

            group_box = QGroupBox(gmeta)
            group_box.setStyleSheet("""
                QGroupBox { font-size: 12pt; font-weight: 600; border: 1px solid #d0d0d0;
                            border-radius: 4px; margin-top: 12px; padding-top: 8px; }
                QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            """)
            group_layout = QVBoxLayout(group_box)
            group_layout.setSpacing(2)

            for field in dataclasses.fields(instance):
                value = getattr(instance, field.name)
                fmeta = FIELD_META.get((cfg_key, field.name), FieldMeta("参数。"))
                row = ParamRow(
                    cfg_key, field.name, value, _field_unit(field.name),
                    fmeta, _literal_options(field.type), False,
                    on_changed=self._refresh_derived,
                )
                group_layout.addWidget(row)
                self._param_rows[(cfg_key, field.name)] = row

            # 派生字段
            derived = [(gk, n, u, fn, d) for gk, n, u, fn, d in DERIVED_FIELDS if gk == cfg_key]
            if derived:
                sep = QFrame()
                sep.setFrameShape(QFrame.HLine)
                sep.setStyleSheet("color: #ccc;")
                group_layout.addWidget(sep)
                derived_label = QLabel("派生参数（只读）")
                derived_label.setStyleSheet("color: #888; font-size: 9pt; font-weight: 600;")
                group_layout.addWidget(derived_label)
                for _, name, unit, getter, desc in derived:
                    row = ParamRow(
                        cfg_key, name, getter(), unit,
                        FieldMeta(desc), None, True,
                        on_changed=lambda: None,
                    )
                    group_layout.addWidget(row)

            self.param_layout.insertWidget(self.param_layout.count() - 1, group_box)

    def _refresh_derived(self):
        for (_, name), row in self._param_rows.items():
            if row.is_derived:
                for gk, n, _, getter, _ in DERIVED_FIELDS:
                    if row.group_key == gk and row.field_name == n:
                        row.current_value = getter()
                        # 更新显示
                        for child in row.findChildren(QLabel):
                            if child.text() and child.styleSheet().startswith("color: #666"):
                                child.setText(_format_value(row.current_value))

    def _collect_updates(self) -> tuple[dict[tuple[str, str], Any], list[str]]:
        updates = {}
        errors = []
        for key, row in self._param_rows.items():
            if row.is_derived:
                continue
            try:
                parsed = row.parse_edit_value()
                updates[key] = parsed
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

        lines = [f"- {k[0]}.{k[1]}: {_format_value(self._param_rows[k].current_value)} → {_format_value(v)}"
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
    app.setFont(QFont("Microsoft YaHei UI", 11))
    window = ConfigEditorWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
