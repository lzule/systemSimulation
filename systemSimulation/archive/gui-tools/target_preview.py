"""
tools/target_preview.py — 目标运动实时预览
==========================================
【功能】
    独立预览目标在 3D 世界坐标中的运动轨迹。
    实时显示目标位置、速度向量、方位角/俯仰角随时间变化，
    结束后可保存 GIF。

【运行方式】
    python tools/target_preview.py
    python tools/target_preview.py --save-gif

【界面布局】
    ┌────────────────────┬─────────────────────┐
    │  2D 轨迹图(XY)     │  方位角时间曲线      │
    │  · 实时位置点       ├─────────────────────┤
    │  · 历史轨迹线       │  俯仰角时间曲线      │
    │  · 原点（云台）     ├─────────────────────┤
    │  · 速度向量箭头     │  3D距离时间曲线      │
    └────────────────────┴─────────────────────┘
"""

import sys
import os
import io
import math
import argparse
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from collections import deque

_no_display = '--no-display' in sys.argv
if _no_display:
    matplotlib.use('Agg')
else:
    try:
        matplotlib.use('TkAgg')
    except Exception:
        matplotlib.use('Agg')
        _no_display = True

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import target_cfg, scene_cfg, camera_cfg
from entities.target.model import TargetKinematics3D

os.makedirs(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'output'), exist_ok=True)
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'output')

# ── 学术配色 ──────────────────────────────────────────
plt.rcParams.update({
    'font.family':       'DejaVu Sans',
    'font.size':         10,
    'axes.titlesize':    11,
    'axes.titleweight':  'bold',
    'axes.facecolor':    'white',
    'axes.edgecolor':    '#333333',
    'figure.facecolor':  'white',
    'grid.color':        '#CCCCCC',
    'grid.linestyle':    '--',
    'grid.alpha':        0.6,
    'axes.spines.top':   False,
    'axes.spines.right': False,
    'lines.linewidth':   1.8,
})


class TargetPreview:

    def __init__(self, save_gif: bool = False, no_display: bool = False):
        self.save_gif   = save_gif
        self.no_display = no_display
        self.target     = TargetKinematics3D(target_cfg)
        self.scn        = scene_cfg
        self.cam        = camera_cfg

        self.steps_per_frame = max(1, int(
            1.0 / (self.scn.anim_fps * self.scn.dt_s)))

        trail_len = int(self.scn.trail_length_s / self.scn.dt_s)
        win_len   = int(self.scn.plot_window_s / self.scn.dt_s)

        self.buf_x        = deque(maxlen=trail_len)
        self.buf_y        = deque(maxlen=trail_len)
        self.buf_t        = deque(maxlen=win_len)
        self.buf_bearing  = deque(maxlen=win_len)
        self.buf_elevation = deque(maxlen=win_len)
        self.buf_dist     = deque(maxlen=win_len)

        self._t           = 0.0
        self._gif_frames  = []
        self._gif_interval = max(1, self.scn.anim_fps // self.scn.gif_fps)
        self._frame_cnt   = 0

        self._build_figure()

    def _build_figure(self):
        self.fig = plt.figure(figsize=(14, 7))
        self.fig.suptitle(
            f"Target Motion Preview  |  Type: {target_cfg.motion_type}  |  "
            f"Duration: {self.scn.duration_s} s",
            fontsize=12, fontweight='bold')

        gs = gridspec.GridSpec(
            3, 2, figure=self.fig,
            hspace=0.52, wspace=0.32,
            left=0.07, right=0.97,
            top=0.90, bottom=0.08
        )
        self.ax_traj     = self.fig.add_subplot(gs[:, 0])   # 左：轨迹（占全高）
        self.ax_bearing  = self.fig.add_subplot(gs[0, 1])   # 右上：方位角
        self.ax_elevation = self.fig.add_subplot(gs[1, 1])  # 右中：俯仰角
        self.ax_dist     = self.fig.add_subplot(gs[2, 1])   # 右下：距离

        # ── 轨迹图静态元素 ──
        ax = self.ax_traj
        R  = self.scn.world_view_range_m
        ax.set_xlim(-R * 0.1, R)
        ax.set_ylim(-R, R)
        ax.set_aspect('equal')
        ax.set_xlabel('X (m)')
        ax.set_ylabel('Y (m)')
        ax.set_title('Target Trajectory (2D World)')
        ax.grid(True)
        ax.axhline(0, color='#999999', linewidth=0.8)
        ax.axvline(0, color='#999999', linewidth=0.8)
        # 原点（云台/相机）
        ax.plot(0, 0, 's', color='#2E7D32', markersize=12,
                zorder=10, label='Camera/Gimbal')

        # 初始位置标记
        ax.plot(target_cfg.initial_x_m, target_cfg.initial_y_m,
                'x', color='#888888', markersize=10,
                linewidth=2, label='Initial pos', zorder=5)

        # 动态元素
        self.trail_line, = ax.plot([], [], '-', color='#90CAF9',
                                    linewidth=1.5, alpha=0.7, label='Trail')
        self.target_dot, = ax.plot([], [], 'o', color='#1565C0',
                                    markersize=11, zorder=8, label='Target')
        self._vel_arrow  = None   # 速度向量箭头

        ax.legend(loc='upper right', fontsize=8)

        # 当前位置文字
        self.pos_text = ax.text(
            0.02, 0.97, '', transform=ax.transAxes,
            va='top', ha='left', fontsize=9, family='monospace',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='#F8F8F8',
                      edgecolor='#AAAAAA', alpha=0.9))

        # ── 方位角曲线 ──
        ax = self.ax_bearing
        ax.set_xlabel('Time (s)')
        ax.set_ylabel('Azimuth (deg)')
        ax.set_title('Target Azimuth from Camera')
        ax.axhline(0, color='#888888', linewidth=0.8)
        ax.grid(True)
        self.bearing_line, = ax.plot([], [], color='#C62828', linewidth=1.8)

        # FOV 限制标注
        fov_half = self.cam.fov_h_deg / 2
        ax.axhline( fov_half, color='#E65100', linewidth=1.2,
                    linestyle=':', alpha=0.7,
                    label=f'FOV limit ±{fov_half:.1f}°')
        ax.axhline(-fov_half, color='#E65100', linewidth=1.2,
                    linestyle=':', alpha=0.7)
        ax.fill_between([-1, self.scn.duration_s + 1],
                         -fov_half, fov_half,
                         color='#FFF3E0', alpha=0.5)
        ax.legend(fontsize=8, loc='upper right')

        # ── 俯仰角曲线 ──
        ax = self.ax_elevation
        ax.set_xlabel('Time (s)')
        ax.set_ylabel('Elevation (deg)')
        ax.set_title('Target Elevation from Camera')
        ax.axhline(0, color='#888888', linewidth=0.8)
        ax.grid(True)
        self.elevation_line, = ax.plot([], [], color='#6A1B9A', linewidth=1.8)
        # 垂直 FOV 限制标注
        fov_v_half = self.cam.fov_v_deg / 2
        ax.axhline( fov_v_half, color='#E65100', linewidth=1.2,
                    linestyle=':', alpha=0.7,
                    label=f'FOV limit ±{fov_v_half:.1f}°')
        ax.axhline(-fov_v_half, color='#E65100', linewidth=1.2,
                    linestyle=':', alpha=0.7)
        ax.fill_between([-1, self.scn.duration_s + 1],
                         -fov_v_half, fov_v_half,
                         color='#F3E5F5', alpha=0.5)
        ax.legend(fontsize=8, loc='upper right')

        # ── 距离曲线 ──
        ax = self.ax_dist
        ax.set_xlabel('Time (s)')
        ax.set_ylabel('Distance (m)')
        ax.set_title('Target Distance from Camera')
        ax.grid(True)
        self.dist_line, = ax.plot([], [], color='#1565C0', linewidth=1.8)

    def _update(self, t: float, x: float, y: float, z: float,
                vx: float, vy: float, vz: float):
        azimuth   = math.degrees(math.atan2(y, x))
        h_dist    = math.hypot(x, y)
        elevation = math.degrees(math.atan2(z, h_dist))
        dist      = math.sqrt(x*x + y*y + z*z)

        # 轨迹
        self.buf_x.append(x)
        self.buf_y.append(y)
        if len(self.buf_x) > 1:
            self.trail_line.set_data(list(self.buf_x), list(self.buf_y))
        self.target_dot.set_data([x], [y])

        # 速度向量箭头
        if self._vel_arrow is not None:
            try:
                self._vel_arrow.remove()
            except Exception:
                pass
        spd = math.sqrt(vx*vx + vy*vy + vz*vz)
        if spd > 0.1:
            scale = min(self.scn.world_view_range_m * 0.15, spd * 3)
            self._vel_arrow = self.ax_traj.annotate(
                '', xy=(x + vx / spd * scale, y + vy / spd * scale),
                xytext=(x, y),
                arrowprops=dict(arrowstyle='->', color='#E65100',
                                lw=2, mutation_scale=15))

        # 位置文字
        in_fov_h = abs(azimuth) <= self.cam.fov_h_deg / 2
        in_fov_v = abs(elevation) <= self.cam.fov_v_deg / 2
        in_fov   = in_fov_h and in_fov_v
        fov_s    = 'IN FOV' if in_fov else 'OUT OF FOV'
        self.pos_text.set_text(
            f"t = {t:.2f} s\n"
            f"x = {x:.1f}  y = {y:.1f}  z = {z:.1f} m\n"
            f"dist   = {dist:.1f} m\n"
            f"azim   = {azimuth:.1f} deg\n"
            f"elev   = {elevation:.1f} deg\n"
            f"speed  = {spd:.2f} m/s\n"
            f"FOV    : {fov_s}")
        self.pos_text.set_color('#2E7D32' if in_fov else '#C62828')

        # 曲线
        self.buf_t.append(t)
        self.buf_bearing.append(azimuth)
        self.buf_elevation.append(elevation)
        self.buf_dist.append(dist)

        t_arr = np.array(self.buf_t)
        self.bearing_line.set_data(t_arr, np.array(self.buf_bearing))
        self.ax_bearing.set_xlim(t_arr[0], max(t_arr[-1], t_arr[0] + 0.5))
        self.ax_bearing.relim()
        self.ax_bearing.autoscale_view(scalex=False)

        self.elevation_line.set_data(t_arr, np.array(self.buf_elevation))
        self.ax_elevation.set_xlim(t_arr[0], max(t_arr[-1], t_arr[0] + 0.5))
        self.ax_elevation.relim()
        self.ax_elevation.autoscale_view(scalex=False)

        self.dist_line.set_data(t_arr, np.array(self.buf_dist))
        self.ax_dist.set_xlim(t_arr[0], max(t_arr[-1], t_arr[0] + 0.5))
        self.ax_dist.relim()
        self.ax_dist.autoscale_view(scalex=False)

    def _capture_gif_frame(self):
        buf = io.BytesIO()
        self.fig.savefig(buf, format='png', dpi=80,
                         bbox_inches='tight', facecolor='white')
        buf.seek(0)
        from PIL import Image
        self._gif_frames.append(Image.open(buf).copy())
        buf.close()

    def _save_gif(self):
        path = os.path.join(OUTPUT_DIR, 'target_preview.gif')
        if not self._gif_frames:
            return
        print(f"\n[target_preview] Saving GIF ({len(self._gif_frames)} frames)...",
              end='', flush=True)
        self._gif_frames[0].save(
            path, save_all=True,
            append_images=self._gif_frames[1:],
            loop=0,
            duration=int(1000 / self.scn.gif_fps))
        print(f" Done. → {path}")

    def run(self):
        print("=" * 55)
        print("  Target Motion Preview")
        print("=" * 55)
        print(f"  Motion type  : {target_cfg.motion_type}")
        print(f"  Initial pos  : ({target_cfg.initial_x_m}, "
              f"{target_cfg.initial_y_m}, {target_cfg.initial_z_m}) m")
        print(f"  Duration     : {self.scn.duration_s} s")
        print(f"  GIF saving   : {'ON' if self.save_gif else 'OFF'}")
        print("-" * 55)

        n_steps       = int(self.scn.duration_s / self.scn.dt_s)
        prev_x, prev_y, prev_z = target_cfg.initial_x_m, target_cfg.initial_y_m, target_cfg.initial_z_m

        for step_i in range(n_steps):
            self._t += self.scn.dt_s
            x, y, z = self.target.step(self.scn.dt_s)
            vx = (x - prev_x) / self.scn.dt_s
            vy = (y - prev_y) / self.scn.dt_s
            vz = (z - prev_z) / self.scn.dt_s
            prev_x, prev_y, prev_z = x, y, z

            # 每隔 steps_per_frame 渲染一次
            if step_i % self.steps_per_frame == 0:
                self._update(self._t, x, y, z, vx, vy, vz)
                self._frame_cnt += 1

                if self.save_gif and \
                   (self._frame_cnt % self._gif_interval == 0):
                    self._capture_gif_frame()

                if not self.no_display:
                    plt.pause(0.001)

                if self._frame_cnt % 30 == 0:
                    pct = step_i / n_steps * 100
                    print(f"\r  Progress: {pct:.1f}%  ", end='', flush=True)

        print("\r  Progress: 100.0%  Done.          ")

        if self.save_gif:
            self._save_gif()
        elif not self.no_display:
            ans = input("\n  Save GIF? [y/N]: ").strip().lower()
            if ans == 'y':
                self._save_gif()

        if not self.no_display:
            print("  Close the window to exit.")
            plt.show()
        print("=" * 55)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Target Motion Preview')
    parser.add_argument('--save-gif',   action='store_true')
    parser.add_argument('--no-display', action='store_true')
    args = parser.parse_args()

    preview = TargetPreview(
        save_gif=args.save_gif or args.no_display,
        no_display=_no_display or args.no_display)
    preview.run()