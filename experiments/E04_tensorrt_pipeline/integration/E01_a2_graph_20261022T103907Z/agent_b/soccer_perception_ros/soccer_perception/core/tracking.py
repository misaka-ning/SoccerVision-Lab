"""球的 3D 状态跟踪器。"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from soccer_perception.types import TrackState


class BallTracker(ABC):
    """所有跟踪器实现需要满足的最小接口。"""

    @abstractmethod
    def reset(self) -> None:
        """清空已有状态,等待下一次测量重新初始化。"""

        raise NotImplementedError

    @abstractmethod
    def update(self, measurement: np.ndarray | None, timestamp: float) -> TrackState:
        """用当前帧测量更新状态;measurement 为 None 时可选择预测或丢失。"""

        raise NotImplementedError


class AlphaBetaBallTracker(BallTracker):
    """轻量 Alpha-Beta tracker,用位置残差同时修正位置和速度。"""

    def __init__(
        self,
        alpha: float = 0.55,
        beta: float = 0.18,
        max_coast_frames: int = 8,
        max_coast_time_s: float = 0.35,
        velocity_decay: float = 0.72,
    ):
        # alpha 越大位置越贴近测量,beta 越大速度修正越激进。
        self.alpha = alpha
        self.beta = beta
        # 漏检允许维持预测的最大帧数/时间,超过后取消锁定。
        self.max_coast_frames = max_coast_frames
        self.max_coast_time_s = max_coast_time_s
        self.velocity_decay = velocity_decay
        self.state = TrackState(
            p=np.zeros(3, dtype=np.float64),
            v=np.zeros(3, dtype=np.float64),
            last_t=0.0,
            initialized=False,
        )
        self._last_measurement_t: float | None = None

    def reset(self) -> None:
        """重置为未初始化状态。"""

        self.state = TrackState(
            p=np.zeros(3, dtype=np.float64),
            v=np.zeros(3, dtype=np.float64),
            last_t=0.0,
            initialized=False,
        )
        self._last_measurement_t = None

    def update(self, measurement: np.ndarray | None, timestamp: float) -> TrackState:
        """执行一次预测-校正;返回状态副本,避免外部修改内部数组。"""

        t = float(timestamp)
        if not self.state.initialized:
            if measurement is not None:
                # 第一帧有效 3D 测量直接初始化位置,速度从 0 开始估计。
                self.state.p = measurement.astype(np.float64)
                self.state.v[:] = 0.0
                self.state.last_t = t
                self.state.initialized = True
                self.state.frames_since_measurement = 0
                self.state.coasting = False
                self._last_measurement_t = t
            return self.state.copy()

        dt = max(1e-3, t - self.state.last_t)
        pred = self.state.p + self.state.v * dt
        if measurement is None:
            # 短时漏检时沿速度预测,并逐帧衰减速度,避免目标持续漂移。
            self.state.frames_since_measurement += 1
            if (
                self.state.frames_since_measurement > self.max_coast_frames
                or self._last_measurement_t is None
                or t - self._last_measurement_t > self.max_coast_time_s
            ):
                # 漏检超过门限后丢弃当前轨迹。
                self.state.v[:] = 0.0
                self.state.initialized = False
                self.state.coasting = False
                self.state.last_t = t
                return self.state.copy()
            self.state.p = pred
            self.state.v *= self.velocity_decay
            self.state.last_t = t
            self.state.coasting = True
            return self.state.copy()

        # 有测量值时用 residual 修正预测位置,并把 residual/dt 注入速度。
        residual = measurement.astype(np.float64) - pred
        self.state.p = pred + self.alpha * residual
        self.state.v = self.state.v + self.beta * residual / dt
        self.state.last_t = t
        self.state.frames_since_measurement = 0
        self.state.coasting = False
        self._last_measurement_t = t
        return self.state.copy()
