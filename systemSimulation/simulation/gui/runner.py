"""GUI 运行封装。"""

from __future__ import annotations

import sys

from simulation.gui.window import DashboardWindow
from simulation.qt_compat import QtGui, QtWidgets, pg
from simulation.types import AppConfig


def create_dashboard(cfg: AppConfig) -> DashboardWindow:
    """创建主仪表盘窗口实例。"""
    return DashboardWindow(cfg)


def run_gui(cfg: AppConfig) -> None:
    """GUI 模式主循环。"""
    if QtWidgets is None:
        raise RuntimeError("缺少 GUI 依赖，请确认 simulation 环境已安装 PyQt5。")
    if pg is None:
        raise RuntimeError("缺少 pyqtgraph 依赖，请确认 simulation 环境已安装 pyqtgraph。")

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("DigitalTwinDashboard")
    app.setFont(QtGui.QFont("Microsoft YaHei UI", 10))
    window = create_dashboard(cfg)
    window.show()
    app.exec_()
