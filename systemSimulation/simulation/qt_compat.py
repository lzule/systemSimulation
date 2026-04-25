"""Qt / pyqtgraph 兼容导入。"""

from __future__ import annotations

try:
    from PyQt5 import QtCore, QtGui, QtWidgets
except Exception:  # noqa: BLE001
    QtCore = None
    QtGui = None
    QtWidgets = None

try:
    import pyqtgraph as pg
except Exception:  # noqa: BLE001
    pg = None

__all__ = ["QtCore", "QtGui", "QtWidgets", "pg"]
