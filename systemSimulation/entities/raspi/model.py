from __future__ import annotations

from entities.raspi.delay_pipeline import DelayPipeline


class RaspiDelayModel:
    def __init__(self):
        self.pipeline = DelayPipeline()

    def reset(self) -> None:
        self.pipeline = DelayPipeline()

