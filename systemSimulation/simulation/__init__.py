"""仿真 app 分层模块。"""

from simulation.bootstrap import build_runtime, start_stack
from simulation.gui.runner import create_dashboard
from simulation.headless import run_headless_session

__all__ = ["build_runtime", "start_stack", "run_headless_session", "create_dashboard"]
