"""bboverlay / bbatt —— Mahony 四元数姿态解算（用 gyroUnfilt + accSmooth）

imuQuaternion 列在 BF 4.x 里是垃圾值、gyroADC 在预测帧会爆，唯一可靠的是 gyroUnfilt，
所以必须自己积分。Kp≈2.0，用 accSmooth/2048 做重力校正。
"""
import numpy as np


def quat_filter(t, g, a, kp=2.0):
    dt = float(np.median(np.diff(t)))
    d2r = np.pi / 180.0
    n = len(t)
    w, x, y, z = 1.0, 0.0, 0.0, 0.0
    out = np.zeros((n, 4))
    nrm = np.sqrt((a ** 2).sum(0))
    for i in range(n):
        ax, ay, az = a[0, i], a[1, i], a[2, i]
        nz = nrm[i]
        gx, gy, gz = g[0, i] * d2r, g[1, i] * d2r, g[2, i] * d2r
        if 0.75 < nz < 1.25:                      # 只在不处于大过载时用加速度计校正
            A = np.array([ax, ay, az]) / nz
            V = np.array([2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)])
            e = np.cross(A, V)
            gx += kp * e[0]
            gy += kp * e[1]
            gz += kp * e[2]
        qd = 0.5 * np.array([-(x * gx + y * gy + z * gz),
                             w * gx + y * gz - z * gy,
                             w * gy + z * gx - x * gz,
                             w * gz + x * gy - y * gx])
        w += qd[0] * dt
        x += qd[1] * dt
        y += qd[2] * dt
        z += qd[3] * dt
        s = np.sqrt(w * w + x * x + y * y + z * z)
        w /= s
        x /= s
        y /= s
        z /= s
        out[i] = (w, x, y, z)
    return out


def quat_to_R(q):
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])