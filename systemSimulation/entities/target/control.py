from __future__ import annotations


class PassiveTargetController:
    """目标实体默认无控制输入，仅做占位以统一实体目录结构。"""

    def step(self, _obs: dict | None = None) -> None:
        return None

