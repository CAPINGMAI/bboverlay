"""bboverlay / bbsync —— 自动测视频与黑匣子的时间差

原理：黑匣子的陀螺模长曲线和视频画面的运动量（相邻帧差）是同一段动作的两种记录，
把两条曲线在时间轴上做归一化互相关，相关峰的位置就是时间差。

约定：lag 满足  视频时间 = 黑匣子时间 + lag
      也就是  黑匣子时间 = 视频时间 - lag
"""
import os
import shutil
import subprocess

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def _find_ffmpeg():
    for c in (os.environ.get("FFMPEG", ""), os.path.join(HERE, "tools", "ffmpeg.exe"),
              shutil.which("ffmpeg")):
        if c and os.path.exists(c):
            return c
    return "ffmpeg"


FFMPEG = _find_ffmpeg()


# ---------------------------------------------------------------- 视频运动量
def video_energy(video, ffmpeg=FFMPEG, fps=30, w=160, h=90, ss=None, dur=None):
    """逐帧平均帧差（0~255 灰度的平均绝对差），返回 (energy, fps)"""
    cmd = [ffmpeg, "-v", "error"]
    if ss not in (None, 0):
        cmd += ["-ss", "%.3f" % ss]
    if dur:
        cmd += ["-t", "%.3f" % dur]
    cmd += ["-i", video,
            "-vf", "fps=%d,scale=%d:%d,format=gray" % (fps, w, h),
            "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    buf = p.stdout
    fsz = w * h
    n = len(buf) // fsz
    if n == 0:
        raise RuntimeError("读不到视频帧：%s\n%s" % (video, p.stderr.decode("utf-8", "replace")[:500]))
    fr = np.frombuffer(buf[:n * fsz], dtype=np.uint8).reshape(n, fsz)
    e = np.zeros(n, np.float32)
    prev = fr[0].astype(np.int16)
    for i in range(1, n):
        cur = fr[i].astype(np.int16)
        e[i] = np.abs(cur - prev).mean()
        prev = cur
    return e, fps


# ---------------------------------------------------------------- 黑匣子运动量
def bb_envelope(t, gyro, fps=30):
    """把陀螺模长重采样到视频帧率，返回 (times, mag)"""
    g = np.sqrt((gyro ** 2).sum(0))
    tv = np.arange(t[0], t[-1], 1.0 / fps)
    return tv, np.interp(tv, t, g)


# ---------------------------------------------------------------- 互相关
def _detrend_norm(x, fps, smooth=0.1, hp=2.0):
    k = max(1, int(round(smooth * fps)))
    if k > 1:
        x = np.convolve(x, np.ones(k) / k, mode="same")
    k2 = max(3, int(round(hp * fps)))
    base = np.convolve(x, np.ones(k2) / k2, mode="same")
    y = x - base
    return (y - y.mean()) / (y.std() + 1e-9)


def ncc_curve(a, b):
    """归一化互相关（重叠段各自归一）。

    a: 视频运动量; b: 黑匣子运动量。
    返回 (lags秒, ncc)，lag = 视频时间 - 黑匣子时间
    """
    a = np.asarray(a, np.float64)
    b = np.asarray(b, np.float64)
    Na, Nb = len(a), len(b)
    n = Na + Nb - 1
    fa = np.fft.rfft(a, n)
    fb = np.fft.rfft(b, n)
    corr = np.fft.irfft(fa * np.conj(fb), n)
    ones_a = np.fft.rfft(np.ones(Na), n)
    ones_b = np.fft.rfft(np.ones(Nb), n)
    sa = np.fft.irfft(np.fft.rfft(a * a, n) * np.conj(ones_b), n)
    sb = np.fft.irfft(ones_a * np.conj(np.fft.rfft(b * b, n)), n)
    ncc = corr / np.sqrt(np.maximum(sa * sb, 1e-12))
    k = np.arange(n).astype(float)       # corr[m] = Σ a[j+m]·b[j] → a 下标 - b 下标 = m
    k[k > (n - 1) / 2.0] -= n            # 折回负值
    # 每个 lag 下的有效重叠帧数
    ovl = np.minimum(Nb - 1, Na - 1 - k) - np.maximum(0.0, -k) + 1
    ovl = np.clip(ovl, 0, None)
    return k, ncc, ovl


def measure(video, csv_gyro_list, fps=30, video_fps=30, max_lag=30.0,
            min_overlap=0.3, log=print):
    """对多段黑匣子逐段测时间差，返回 (best_index, lag_seconds, ncc, 明细表)

    csv_gyro_list: [(名字, t, gyro3xN), ...]
    返回 lag：视频时间 = 黑匣子时间 + lag
    """
    log("  读视频运动量 ...")
    ve, vfps = video_energy(video, fps=video_fps)
    a = _detrend_norm(ve, vfps)
    rows = []
    for name, t, gyro in csv_gyro_list:
        tv, mag = bb_envelope(t, gyro, fps=vfps)
        b = _detrend_norm(np.interp(np.arange(len(ve)) / vfps, tv, mag), vfps)
        k, ncc, ovl = ncc_curve(a, b)
        mask = (np.abs(k) <= max_lag * vfps) & (ovl >= min_overlap * min(len(a), len(b)))
        if not mask.any():
            mask = ovl >= min_overlap * min(len(a), len(b))
        kk, cc = k[mask], ncc[mask]
        i = int(np.argmax(cc))
        # 峰的“唯一性”：离主峰 1.5 秒以外的最高值
        far = np.abs(kk - kk[i]) > 1.5 * vfps
        second = float(cc[far].max()) if far.any() else 0.0
        rows.append(dict(name=name, lag=float(kk[i]) / vfps, ncc=float(cc[i]),
                         second=second))
    best = max(range(len(rows)), key=lambda i: rows[i]["ncc"])
    b = rows[best]
    return best, b["lag"], b["ncc"], rows


def self_test():
    """自检：造一段已知 lag 的数据，看能不能测回来"""
    rng = np.random.default_rng(7)
    fps = 30
    n = 60 * fps
    bb = np.zeros(n)
    for t0 in (10, 22, 35, 41, 52):
        i = t0 * fps
        bb[i:i + 40] = rng.uniform(200, 900)
    bb = np.convolve(bb, np.hanning(9) / np.hanning(9).sum(), mode="same")
    for true_lag in (-1.0, 0.27, 2.4, -3.5):
        shift = int(round(true_lag * fps))
        vid = np.zeros(n + abs(shift) + 20)
        if shift >= 0:                              # 视频里动作比黑匣子晚 shift 帧
            vid[shift:shift + n] = bb
        else:                                       # 视频里动作比黑匣子早
            vid[0:n + shift] = bb[-shift:]
        a = _detrend_norm(vid, fps)
        b = _detrend_norm(bb, fps)
        k, ncc, ovl = ncc_curve(a, b)
        m = ovl >= 0.3 * min(len(a), len(b))
        lag = k[m][int(np.argmax(ncc[m]))] / fps
        print("  真实 lag %+.2fs -> 测得 %+.2fs  ncc %.3f" % (true_lag, lag, ncc[m].max()))


if __name__ == "__main__":
    self_test()