"""运行时创建与启动编排。"""

from __future__ import annotations

from typing import Any, Protocol

from runtime.digital_twin_runtime import DigitalTwinRuntime


class ControlProgramFactory(Protocol):
    """控制程序工厂协议，用于延迟实例化。"""
    def __call__(self) -> Any: ...


def apply_delay_profile(runtime: DigitalTwinRuntime, delay_ms: float) -> None:
    """按统一规则设置 Raspi 链路延时。"""
    if delay_ms <= 0.0:
        return
    delay_s = float(delay_ms) / 1000.0
    runtime.raspi_client.set_delay_profile(
        image_read_delay_s=delay_s,
        image_process_delay_s=delay_s,
        state_read_delay_s=delay_s * 0.5,
        command_tx_delay_s=delay_s,
        jitter_std_s=0.0,
    )


def start_stack(
    runtime: DigitalTwinRuntime,
    delay_ms: float = 0.0,
    control_program: Any | None = None,
) -> DigitalTwinRuntime:
    """上电并进入 READY，随后装载 Raspi 控制程序。

    Args:
        runtime: DigitalTwinRuntime 实例。
        delay_ms: Raspi 链路延时（毫秒）。
        control_program: 控制程序实例、工厂函数、或 None。
            - None: 使用默认 BaselineTrackerProgram。
            - 对象: 直接加载（需实现 on_tick(obs) -> list[Command]）。
            - 可调用: 调用后返回控制程序实例。
    """
    runtime.gimbal_client.power_on()
    runtime.camera_client.power_on()
    runtime.raspi_client.power_on()

    for _ in range(3200):
        snap = runtime.step(1)
        if (
            snap.gimbal["power_state"] == "READY"
            and snap.camera["power_state"] == "READY"
            and snap.raspi["power_state"] == "READY"
        ):
            break
    else:
        raise RuntimeError("等待设备 READY 超时，请检查配置。")

    if control_program is None:
        from entities.raspi.tracker_program import BaselineTrackerProgram
        control_program = BaselineTrackerProgram()

    program = control_program() if callable(control_program) and not hasattr(control_program, "on_tick") else control_program
    runtime.raspi_client.load_control_program(program)
    apply_delay_profile(runtime, delay_ms)
    return runtime


def build_runtime(delay_ms: float = 0.0, control_program: Any | None = None) -> DigitalTwinRuntime:
    """创建并初始化 runtime：上电 -> 等待 READY -> 加载控制程序。

    Args:
        delay_ms: Raspi 链路延时（毫秒）。
        control_program: 控制程序实例、工厂函数、或 None。
    """
    runtime = DigitalTwinRuntime()
    return start_stack(runtime, delay_ms=delay_ms, control_program=control_program)


def load_control_program_from_path(dotted_path: str) -> Any:
    """从模块路径加载控制程序，格式: 'module.path:ClassName' 或 'module.path'。

    示例:
        'my_tracker:MyTracker'  -> from my_tracker import MyTracker; return MyTracker()
        'my_package.my_tracker:MyTracker'
    """
    if ":" in dotted_path:
        module_path, class_name = dotted_path.rsplit(":", 1)
    else:
        module_path = dotted_path
        class_name = None

    import importlib
    module = importlib.import_module(module_path)

    if class_name:
        cls = getattr(module, class_name)
        return cls()

    # 尝试自动发现：找模块中第一个实现了 on_tick 的类
    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, type) and hasattr(obj, "on_tick") and name != "ControlProgram":
            return obj()

    raise ValueError(f"在 {module_path} 中找不到实现了 on_tick 的类，请使用 'module:ClassName' 格式指定")
