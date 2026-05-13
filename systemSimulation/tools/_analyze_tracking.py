"""Tracking performance analysis"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import math
import numpy as np
from simulation.bootstrap import build_runtime

runtime = build_runtime()
dp = runtime.raspi_client.get_delay_profile()
total_delay_ms = (max(dp['image_read_delay_s'], dp['state_read_delay_s']) + dp['image_process_delay_s'] + dp['command_tx_delay_s']) * 1000
print(f"dt_s={runtime.dt_s}, total_delay={total_delay_ms:.1f}ms")

print("\n--- Tracking Analysis (20s sinusoidal) ---")
pixel_errors = []
angle_errors = []
for i in range(4000):
    snap = runtime.step(1)
    t = snap.timestamp
    target_bearing = math.degrees(math.atan2(snap.target['y_m'], snap.target['x_m']))
    yaw = snap.gimbal['yaw_deg_internal']
    angle_err = ((target_bearing - yaw + 180) % 360) - 180

    if i % 400 == 0:
        u_px = snap.camera['u_px']
        in_fov = snap.camera['in_fov']
        backlog = snap.raspi['pipeline_backlog_len']
        print(f't={t:5.1f}s bearing={target_bearing:7.2f} yaw={yaw:7.2f} err={angle_err:6.2f} u={u_px:8.2f} fov={int(in_fov)} bl={backlog}')

    if snap.camera['in_fov']:
        cx = snap.camera.get('u_px', float('nan'))
        if cx == cx:
            pixel_errors.append(abs(cx - 320))
    angle_errors.append(abs(angle_err))

pe = np.array(pixel_errors)
ae = np.array(angle_errors)
max_target_rate = 15 * 2 * math.pi * 0.2 * 180/math.pi
print(f"\n--- Summary ---")
print(f"Pixel err: mean={pe.mean():.1f} max={pe.max():.1f} rms={np.sqrt((pe**2).mean()):.1f}")
print(f"Angle err: mean={ae.mean():.2f} max={ae.max():.2f} rms={np.sqrt((ae**2).mean()):.2f} deg")
print(f"Target max angular rate: {max_target_rate:.1f} deg/s")
print(f"Gimbal rate limit: 60 deg/s")
print(f"Tracker Kp: 0.08 dps/px")
print(f"Frame rate: 200 Hz (dt=5ms)")

