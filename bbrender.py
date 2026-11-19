"""bboverlay / bbrender —— 绿幕 HUD 帧渲染（摇杆 + 可选 3D 姿态 + 可选小地图）

单独跑一帧可以看版式：
    python bbrender.py 4.01.csv 4.01.gps.csv 174 1 out_preview.png
"""
import math
import os
import sys

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

import bbatt
import bbextra
import bbminimap as MM

VERSION = "3.6.3"
W, H = 1920, 1080
CW, CH = 1920, 1080      # 当前渲染画布（竖屏时 1080x1920）
FPS = 60
GREEN = (0, 177, 64)          # 0x00B140 绿幕色
WHITE = (245, 245, 245)
ACC = (255, 214, 10)
DISC = (10, 40, 25)
SHADOW = (8, 22, 16)
GUIDE = (95, 135, 110)
TICK = (65, 105, 82)

R_STICK = 150
L_CENTER = (620, 812)         # 左杆：油门 / 方向
R_CENTER = (1300, 812)        # 右杆：俯仰 / 横滚
MODEL = (960, 800)            # 姿态模型
HUD_ANCHOR = (960.0, 812.0)   # 摇杆+姿态这一组缩放时的不动点
MAPPOS, MAPSIZE = (26, 20), 360
MAPSIZE0 = 360

# 版式：
#   摇杆 hud_*：两根摇杆这一组（anchor 960,812）的位移/缩放
#   姿态 att_*：中间 3D 飞机（anchor 960,800）的位移/缩放，和摇杆完全独立
#   小地图 map_*、GPS 坐标遮盖黑块 mask_*
LAYOUT = dict(ls_dx=0.0, ls_dy=0.0, ls_s=1.0,      # 左摇杆
              rs_dx=0.0, rs_dy=0.0, rs_s=1.0,      # 右摇杆
              att_dx=0.0, att_dy=0.0, att_s=1.0,   # 3D 姿态
              map_dx=float(MAPPOS[0]), map_dy=float(MAPPOS[1]), map_s=1.0,
              mask_on=0.0, mask_x=0.0, mask_y=0.0, mask_w=1920.0, mask_h=46.0,
              mask2_on=0.0, mask2_x=0.0, mask2_y=250.0, mask2_w=1920.0, mask2_h=60.0,
              stick_mode=2.0,
              inv_thr=0.0, inv_rol=0.0, inv_pit=0.0, inv_yaw=0.0,
              stick_style=0.0, stick_alpha=1.0, frame_i=0.0, ball_i=0.0,
              show_us=0.0,
              map_alpha=1.0, map_shape=0.0,
              mask_shape=0.0, mask_alpha=1.0,
              mask2_shape=0.0, mask2_alpha=1.0,
              trail_len=6.0, trail_i=4.0, trail_w=1.0,
              tele_on=0.0, tele_x=60.0, tele_y=380.0, tele_size=30.0, tele_alpha=0.9,
              tele_i=0.0,
              bar_on=0.0, bar_x=60.0, bar_y=760.0, bar_h=200.0, bar_alpha=0.9,
              text_on=0.0, text_x=960.0, text_y=60.0, text_size=44.0, text_i=1.0,
              text_alpha=0.9, text_anchor=0.0,
              map_trail_i=5.0, map_trail_w=1.0, map_scale_on=0.0, map_vec_on=0.0,
              map_wp_on=0.0, event_on=0.0,
              vign=0.0, corner=0.0, aspect=0.0, fill_mode=0.0,
              extra_dx=0.0, extra_dy=0.0, portrait=0.0, horizon=0.0, att_mode=0.0,
              att_yaw=0.0, map_up=0.0, map_arrow=0.0, map_arrow_i=3.0, map_cam=1.0,
              map_zoom=1.0, att_inv_pit=1.0, att_inv_rol=0.0,
              tele_dx=0.0, tele_dy=0.0, tele_s=1.0,
              bar_dx=0.0, bar_dy=0.0, bar_s=1.0, bar_i=0.0,
              text_dx=0.0, text_dy=0.0, text_s=1.0,
              vbat_k=1.0, vbat_b=0.0,
              amp_k=1.0, amp_b=0.0,
              alt_k=1.0, alt_b=0.0,
              spd_k=1.0, spd_b=0.0)   # 2=美国手 1=日本手

LAYOUT_KEYS = ["ls_dx", "ls_dy", "ls_s", "rs_dx", "rs_dy", "rs_s",
               "att_dx", "att_dy", "att_s",
               "map_dx", "map_dy", "map_s",
               "mask_on", "mask_x", "mask_y", "mask_w", "mask_h",
               "mask2_on", "mask2_x", "mask2_y", "mask2_w", "mask2_h",
               "stick_mode", "inv_thr", "inv_rol", "inv_pit", "inv_yaw",
               "stick_style", "stick_alpha", "frame_i", "ball_i", "show_us",
               "map_alpha", "map_shape",
               "mask_shape", "mask_alpha", "mask2_shape", "mask2_alpha",
               "trail_len", "trail_i", "trail_w",
               "tele_on", "tele_x", "tele_y", "tele_size", "tele_alpha", "tele_i",
               "bar_on", "bar_x", "bar_y", "bar_h", "bar_alpha",
               "text_on", "text_x", "text_y", "text_size", "text_i", "text_alpha",
               "text_anchor",
               "map_trail_i", "map_trail_w", "map_scale_on", "map_vec_on",
               "map_wp_on", "event_on",
               "vign", "corner", "aspect", "fill_mode",
               "extra_dx", "extra_dy", "portrait", "horizon", "att_mode", "att_yaw",
               "map_up", "map_arrow", "map_arrow_i", "map_cam", "map_zoom",
               "att_inv_pit", "att_inv_rol",
               "tele_dx", "tele_dy", "tele_s",
               "bar_dx", "bar_dy", "bar_s", "bar_i",
               "text_dx", "text_dy", "text_s",
               "vbat_k", "vbat_b", "amp_k", "amp_b", "alt_k", "alt_b",
               "spd_k", "spd_b"]

# 形状：0=矩形 1=圆角矩形 2=椭圆/圆
SHAPES = ["矩形", "圆角矩形", "椭圆"]



# 竖屏（9:16）原生排版：画布 1080x1920，元素重排
PORTRAIT_W, PORTRAIT_H = 1080, 1920


def portrait_layout(d):
    """在 1080x1920 画布上排一套竖屏版式（摇杆在下、地图在左上、姿态中间偏上）

    只替换「用户没动过」的项（值还等于横屏默认值），这样在元素位置里拖过的
    位置/缩放到竖屏下依然生效，不会被预设覆盖掉。
    """
    L = dict(d or {})
    preset = dict(ls_dx=270.0 - L_CENTER[0], ls_dy=1410.0 - L_CENTER[1], ls_s=0.62,
                  rs_dx=810.0 - R_CENTER[0], rs_dy=1410.0 - R_CENTER[1], rs_s=0.62,
                  att_dx=540.0 - ATT_ANCHOR[0], att_dy=980.0 - ATT_ANCHOR[1], att_s=0.58,
                  map_dx=18.0, map_dy=18.0, map_s=0.8,
                  tele_x=620.0, tele_y=300.0, tele_size=26.0,
                  bar_x=40.0, bar_y=1560.0,
                  text_x=540.0, text_y=120.0, text_size=34.0, text_anchor=1.0)
    for k, v in preset.items():
        try:
            untouched = (k not in L) or (float(L[k]) == float(LAYOUT.get(k, 0.0)))
        except (TypeError, ValueError):
            untouched = k not in L
        if untouched:
            L[k] = v
    # 黑块默认盖住顶部一条（竖屏下经纬度多半被裁掉，留着兜底）
    if L.get("mask_w", 0) > 1080:
        L["mask_w"] = 1080.0
    return L


def layer_layout(base=None, portrait=False):
    """切图层专用版式：元素都摆在「基准位置」（dx=0、s=1），

    「元素位置」编辑器拿这张图当底，按你拖的 dx/dy/s 再摆一次；
    如果这里把位置也烘进去，拖动就会变成两倍位移（竖屏预设最容易踩）。
    绝对定位的元素照旧：小地图烘在 MAP_BASE，面板/柱状图/文字烘在各自的
    基准坐标（横屏 60,380 / 60,760 / 960,60；竖屏用 portrait_layout 预设）。
    """
    L = norm_layout(base)
    for k in ("ls", "rs", "att"):
        L[k + "_dx"] = 0.0
        L[k + "_dy"] = 0.0
        L[k + "_s"] = 1.0
    L["map_dx"], L["map_dy"], L["map_s"] = float(MAPPOS[0]), float(MAPPOS[1]), 1.0
    for k in ("tele", "bar", "text"):
        L[k + "_dx"] = 0.0
        L[k + "_dy"] = 0.0
        L[k + "_s"] = 1.0
    if portrait:
        P = portrait_layout(dict(L))
        # 竖屏预设把摇杆/姿态挪到 270/810/540，这些位置就是图层里的基准位置
        # （编辑器知道这个偏移，拖动时只叠「用户自己拖的那部分」）
        P0 = portrait_layout(dict(LAYOUT))
        for k in ("ls", "rs", "att"):
            P[k + "_dx"] = P0[k + "_dx"]
            P[k + "_dy"] = P0[k + "_dy"]
            P[k + "_s"] = 1.0
        P["map_dx"], P["map_dy"], P["map_s"] = float(MAPPOS[0]), float(MAPPOS[1]), 1.0
        for k in ("tele", "bar", "text"):
            P[k + "_dx"] = 0.0
            P[k + "_dy"] = 0.0
            P[k + "_s"] = 1.0
        return P
    return L


def shape_mask(size, shape, rr=0.16):
    """生成形状遮罩（L 模式，白=显示）"""
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    if int(shape) == 1:
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=max(2, int(min(w, h) * rr)), fill=255)
    elif int(shape) == 2:
        d.ellipse([0, 0, w - 1, h - 1], fill=255)
    else:
        d.rectangle([0, 0, w - 1, h - 1], fill=255)
    return m

# 摇杆样式：0=经典圆盘 1=圆角方框(示例) 2=极简细线圆 3=极简细线方框
STICK_STYLES = ["经典圆盘", "圆角方框", "极简圆", "极简方框"]
# 框线颜色 / 圆点颜色（GUI 里按名字选）
FRAME_COLORS = [(245, 245, 245), (255, 255, 255), (25, 25, 25), (0, 210, 255),
                (0, 255, 130), (255, 200, 10), (255, 70, 70), (185, 120, 255)]
FRAME_COLOR_NAMES = ["浅灰", "纯白", "深黑", "天蓝", "荧光绿", "亮黄", "朱红", "淡紫"]
BALL_COLORS = [(255, 60, 60), (255, 255, 255), (25, 25, 25), (0, 220, 255),
               (255, 200, 10), (0, 255, 130), (185, 120, 255), (120, 200, 255)]
BALL_COLOR_NAMES = ["红点", "白点", "黑点", "青点", "黄点", "绿点", "紫点", "蓝点"]

# 老配置里的 hud_*（整组）迁移到左右两根独立参数
ALIAS = dict(ls_dx="hud_dx", ls_dy="hud_dy", ls_s="hud_s",
             rs_dx="hud_dx", rs_dy="hud_dy", rs_s="hud_s")


def norm_layout(d):
    """把外部传进来的版式补全成完整的 LAYOUT（兼容老键名）"""
    out = dict(LAYOUT)
    src = dict(d or {})
    if "hud_dx" in src or "hud_s" in src:
        for k, hk in ALIAS.items():
            if hk in src and k not in src:
                src[k] = src[hk]
    for k in LAYOUT:
        if k in src and src[k] is not None:
            try:
                out[k] = float(src[k])
            except (TypeError, ValueError):
                pass
    return out
ATT_ANCHOR = (960.0, 800.0)


def layout_kw(**kw):
    """返回一份版式参数（没传的用当前默认）"""
    d = dict(LAYOUT)
    for k, v in kw.items():
        if v is not None:
            d[k] = float(v)
    return d


INIT = {"alpha": True, "vbat": None, "amp": None, "baro": None, "rssi": None,
        "spd": None, "galt": None, "sats": None, "course": None, "text": ""}
META_MPP = [0.0]        # 小地图米/像素，比例尺用
TEXT_TRAIL_COL = [(0, 255, 130), (255, 200, 10)]   # 条形图：油门 / 电压


# ------------------------------------------------------------------ 读数据
def _cols(path):
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        return [c.strip() for c in f.readline().split(",")]


def read_csv(path, need_att=True, log=print):
    """只读需要的列，返回 (t秒, rc[4]×N, gyro, acc, t0秒)"""
    cols = _cols(path)
    want, names = [], []
    for i in range(4):
        n = "rcCommand[%d]" % i
        if n not in cols:
            raise RuntimeError("黑匣子里没有 %s 这一列（不是 Betaflight 标准日志？）" % n)
        want.append(n)
        names.append("rc%d" % i)
    tcol = next(c for c in cols if c.startswith("time"))
    want.append(tcol)
    names.append("t")
    ext_cols = {}
    for key, col in (("vbat", "vbatLatest (V)"), ("amp", "amperageLatest (A)"),
                     ("baro", "baroAlt"), ("rssi", "rssi"),
                     ("thr", "rcCommand[3]")):
        if col in cols:
            ext_cols[key] = col
            if col not in want:
                want.append(col)
    if need_att:
        for i in range(3):
            want.append("gyroUnfilt[%d]" % i)
            names.append("g%d" % i)
        for i in range(3):
            if "accSmooth[%d]" % i in cols:
                want.append("accSmooth[%d]" % i)
                names.append("a%d" % i)
    df = pd.read_csv(path, skipinitialspace=True, usecols=want, low_memory=False)
    t_raw = df[tcol].values.astype(float)
    t0 = t_raw[0] / 1e6
    t = t_raw / 1e6 - t0
    rc = np.vstack([df["rcCommand[%d]" % i].values.astype(float) for i in range(4)])
    gyro = acc = None
    if need_att and "gyroUnfilt[0]" in df.columns:
        gyro = np.vstack([df["gyroUnfilt[%d]" % i].values.astype(float) for i in range(3)])
        acc = np.vstack([df["accSmooth[%d]" % i].values.astype(float) for i in range(3)]) / 2048.0 \
            if "accSmooth[0]" in df.columns else None
    ext = {}
    for key, col in ext_cols.items():
        try:
            ext[key] = df[col].values.astype(float)
        except Exception:
            pass
    log("    样本 %d 帧，时长 %.1f s" % (len(t), t[-1]))
    return t, rc, gyro, acc, t0, ext


# ------------------------------------------------------------------ 姿态
def _tilt_only(R):
    u = R[:, 2]
    u = u / (np.linalg.norm(u) + 1e-9)
    ax = np.cross(np.array([0.0, 0.0, 1.0]), u)
    sn = np.linalg.norm(ax)
    cs = float(u[2])
    if sn < 1e-6:
        return np.eye(3) if cs > 0 else np.diag([1.0, -1.0, -1.0])
    ax = ax / sn
    K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    th = np.arctan2(sn, cs)
    return np.eye(3) + np.sin(th) * K + (1 - np.cos(th)) * (K @ K)



def _rot_from_up(up_body):
    """把「机体坐标系里的世界向上方向」转成旋转矩阵：R @ up_body = (0,0,1)"""
    u = np.array(up_body, float)
    n = np.linalg.norm(u)
    if n < 1e-6:
        return np.eye(3)
    u = u / n
    e = np.array([0.0, 0.0, 1.0])
    v = np.cross(u, e)
    c = float(np.dot(u, e))
    s_ = np.linalg.norm(v)
    if s_ < 1e-6:
        return np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * ((1 - c) / (s_ * s_))


def _read_gps(gps_csv):
    """按列位置读 GPS csv（部分日志列数比表头多，用表头会错位）。
    返回 dict: t(秒), sats, lat, lon, alt, speed, course, vn, ve
    """
    import pandas as _pd
    df = _pd.read_csv(gps_csv, skipinitialspace=True, header=None, skiprows=1,
                      names=list(range(16)), engine="python")
    def col(i, scale=1.0):
        if i >= df.shape[1]:
            return np.zeros(len(df))
        return df[i].values.astype(float) * scale
    return dict(t=col(0) / 1e6, sats=col(1), lat=col(2), lon=col(3), alt=col(4),
                speed=col(5), course=col(6), vn=col(7), ve=col(8))


def rotations_tilt(t, gyro, acc, tt, log=print, yaw_off=0.0):
    """加速度计定滚转/俯仰（重力方向），陀螺积分定偏航 —— 比纯积分稳，不会慢慢漂歪

    机体坐标系里 acc 约等于「上方」方向（无人机正放时 acc_z≈+1g）。
    """
    if acc is None:
        return rotations(t, gyro, acc, tt, log=log)
    # 重力方向：低通 + 归一化
    g = acc.copy().astype(float)
    k = 0.02
    for i in range(1, g.shape[1]):
        g[:, i] = g[:, i - 1] * (1 - k) + g[:, i] * k
    nrm = np.linalg.norm(g, axis=0)
    nrm[nrm < 1e-6] = 1.0
    g = g / nrm
    # 偏航：陀螺 z 轴积分
    yaw = np.concatenate([[0.0], np.cumsum(gyro[2][1:] * np.diff(t))])
    # 偏航在高机动时会漂，用 GPS 航向（如果外面传了 course 就用外部的，这里只做基础）
    R = np.empty((g.shape[1], 3, 3))
    for i in range(g.shape[1]):
        gy_, gx_, gz_ = float(g[1, i]), float(g[0, i]), float(g[2, i])
        roll = math.asin(max(-1.0, min(1.0, -gy_)))          # 绕 X 滚转
        pitch = math.atan2(gx_, gz_ if abs(gz_) > 1e-6 else 1e-6)   # 绕 Y 俯仰
        cr, sr = math.cos(roll), math.sin(roll)
        cp, sp = math.cos(pitch), math.sin(pitch)
        Rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
        Ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
        R0 = Ry @ Rx
        if abs(yaw_off) > 0.01:      # 补偿：板子相对机身的偏转角
            a = math.radians(-yaw_off)
            Rz = np.array([[math.cos(a), -math.sin(a), 0.0],
                           [math.sin(a), math.cos(a), 0.0],
                           [0.0, 0.0, 1.0]])
            R0 = R0 @ Rz
        R[i] = R0          # 显示用：偏航固定（始终从机体后方看），只体现滚转/俯仰
    idx = np.clip(np.searchsorted(t, tt), 0, len(t) - 1)
    return R[idx]


def rotations(t, gyro, acc, tt, log=print):
    """在 [tt 起点-8s, 终点+1s] 内跑 Mahony，再插值到帧时间"""
    lo, hi = tt[0] - 8.0, tt[-1] + 1.0
    m = (t >= lo) & (t <= hi)
    if m.sum() < 10 or acc is None:
        return np.repeat(np.eye(3)[None], len(tt), axis=0)
    q = bbatt.quat_filter(t[m], gyro[:, m], acc[:, m], kp=8.0)
    R = np.array([bbatt.quat_to_R(x) for x in q])
    R = np.array([_tilt_only(x) for x in R[::2]])
    tr = t[m][::2]
    idx = np.clip(np.searchsorted(tr, tt), 0, len(tr) - 1)
    return R[idx]


# ------------------------------------------------------------------ 3D 模型
def _box(cx, cy, cz, sx, sy, sz):
    v = []
    for ix in (-1, 1):
        for iy in (-1, 1):
            for iz in (-1, 1):
                v.append((cx + ix * sx / 2, cy + iy * sy / 2, cz + iz * sz / 2))
    f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return np.array(v, float), f


def _model():
    verts, faces, fcol = [], [], []

    def add(v, f, color):
        base = len(verts)
        verts.extend(list(v))
        for q in f:
            faces.append(tuple(base + i for i in q))
            fcol.append(color)

    add(*_box(0, 0, 0, 0.30, 0.24, 0.10), (55, 58, 66))          # 机身
    add(*_box(0.02, 0, 0.075, 0.16, 0.16, 0.06), (35, 38, 44))   # 机盖
    ARM = 0.62
    for k, (ax, ay) in enumerate([(1, 1), (1, -1), (-1, -1), (-1, 1)]):
        d = np.array([ax, ay], float)
        d /= np.linalg.norm(d)
        mx, my = d[0] * ARM, d[1] * ARM
        ang = math.atan2(d[1], d[0])
        px, py = -math.sin(ang), math.cos(ang)
        w = 0.055
        ex, ey = d[0] * ARM, d[1] * ARM
        vv = []
        for zz in (-0.005, 0.017):
            vv += [(-px * w, -py * w, zz), (px * w, py * w, zz),
                   (ex + px * w, ey + py * w, zz), (ex - px * w, ey - py * w, zz)]
        ff = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
        add(np.array(vv, float), ff, (44, 46, 52))
        add(*_box(mx, my, 0.012, 0.10, 0.10, 0.06), (232, 138, 32))   # 电机
        NP = 14
        vv = []
        for zz in (0.045, 0.055):
            for i in range(NP):
                a = 2 * math.pi * i / NP
                vv.append((mx + 0.265 * math.cos(a), my + 0.265 * math.sin(a), zz))
        ff = [tuple(range(NP))[::-1], tuple(range(NP, 2 * NP))]
        for i in range(NP):
            j = (i + 1) % NP
            ff.append((i, j, NP + j, NP + i))
        add(np.array(vv, float), ff, (238, 240, 243))                  # 桨盘
        if k == 0:
            add(*_box(mx * 1.12, my * 1.12, 0.02, 0.06, 0.06, 0.04), (240, 70, 60))
    return np.array(verts, float), faces, np.array(fcol, float)


def load_obj(path, scale=1.0):
    """读最简单的 OBJ（只要 v / f），归一化到机身大小，用灰白配色"""
    vs, fs = [], []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("v "):
                a = line.split()
                if len(a) >= 4:
                    vs.append([float(a[1]), float(a[2]), float(a[3])])
            elif line.startswith("f "):
                idx = []
                for tok in line.split()[1:]:
                    try:
                        idx.append(int(tok.split("/")[0]))
                    except Exception:
                        pass
                if len(idx) >= 3:
                    fs.append(idx)
    if not vs or not fs:
        raise RuntimeError("这个 OBJ 里没读到顶点/面：%s" % path)
    V = np.array(vs, float)
    V = V - V.mean(axis=0)
    mx = np.abs(V).max() or 1.0
    V = V / mx * 1.15 * float(scale)
    F, C = [], []
    for idx in fs:
        poly = [i - 1 if i > 0 else len(V) + i for i in idx]
        for j in range(1, len(poly) - 1):
            F.append((poly[0], poly[j], poly[j + 1]))
    C = np.tile(np.array([205.0, 210.0, 215.0]), (len(F), 1))
    return V, np.array(F, int), C


V_M, F_M, C_M = _model()
EYE = np.array([-2.9, 0.0, 1.25])
_TGT = np.array([0.0, 0.0, 0.0])
FWD = _TGT - EYE
FWD /= np.linalg.norm(FWD)
RIGHT = np.cross(FWD, np.array([0, 0, 1.0]))
RIGHT /= np.linalg.norm(RIGHT)
UPV = np.cross(RIGHT, FWD)
LIGHT = np.array([-0.4, -0.6, 0.7])
LIGHT /= np.linalg.norm(LIGHT)
FOC = 620


def _project(P3, cx, cy, foc):
    rel = P3 - EYE
    xc, yc, zc = rel @ RIGHT, rel @ UPV, rel @ FWD
    zc = np.maximum(zc, 0.05)
    return np.stack([cx + foc * xc / zc, cy - foc * yc / zc], axis=1), zc



def _draw_horizon(d, R, cx, cy, rad, alpha=210):
    """人工地平线：圆圈里上半天空色、下半地面色，随 roll/pitch 转，一眼看出正倒飞"""
    from PIL import Image as _I, ImageDraw as _D
    size = int(rad * 2 + 8)
    im = _I.new("RGBA", (size, size), (0, 0, 0, 0))
    dd = _D.Draw(im)
    # 天空 + 地面（左右两个半圆之外的方形，最后用圆遮罩裁掉）
    dd.rectangle([0, 0, size, size // 2], fill=(36, 108, 200, alpha))
    dd.rectangle([0, size // 2, size, size], fill=(120, 82, 40, alpha))
    dd.line([0, size // 2, size, size // 2], fill=(255, 255, 255, 255), width=3)
    # 地平线细刻度
    for j in (-2, -1, 1, 2):
        y = size // 2 + j * int(rad * 0.22)
        w = int(rad * 0.30) if j % 2 == 0 else int(rad * 0.16)
        dd.line([size // 2 - w, y, size // 2 + w, y], fill=(255, 255, 255, 190), width=2)
    # 按 pitch 平移、按 roll 旋转
    up = R @ np.array([0.0, 0.0, 1.0])
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, -up[0])))) if abs(up[0]) <= 1 else 0.0
    fwd = R @ np.array([1.0, 0.0, 0.0])
    roll = math.degrees(math.atan2(fwd[1], fwd[2] + 1e-9))
    shift = int(max(-rad * 0.9, min(rad * 0.9, pitch / 30.0 * rad)))
    im = im.rotate(-roll, resample=_I.BILINEAR, center=(size // 2, size // 2))
    im = im.transform((size, size), _I.AFFINE, (1, 0, 0, 0, 1, -shift))
    mask = _I.new("L", (size, size), 0)
    _D.Draw(mask).ellipse([2, 2, size - 3, size - 3], fill=255)
    im.putalpha(_I.composite(im.getchannel("A"), _I.new("L", (size, size), 0), mask))
    d.bitmap((int(cx - size // 2), int(cy - size // 2)), im) if hasattr(d, "bitmap") else None
    return im


def _paste_horizon(img, R, cx, cy, rad):
    im = _draw_horizon(None, R, cx, cy, rad)
    img.paste(im, (int(cx - im.size[0] // 2), int(cy - im.size[1] // 2)), im)


def _draw_model(d, R, cx, cy, foc):
    P3 = V_M @ R.T
    P2, zc = _project(P3, cx, cy, foc)
    order = np.argsort(-np.array([zc[list(f)].mean() for f in F_M]))
    for fi in order:
        f = F_M[fi]
        p = P3[list(f)]
        nrml = np.cross(p[1] - p[0], p[2] - p[0])
        ln = np.linalg.norm(nrml)
        if ln < 1e-9:
            continue
        nrml /= ln
        shade = 0.35 + 0.65 * abs(float(nrml @ LIGHT))
        # 机体坐标里 +Z 是机顶：顶面亮、底面暗（倒飞时看到的就是深色底）
        c = C_M[fi] * (shade * 1.18 if nrml[2] > 0.15 else shade * 0.55)
        d.polygon([tuple(P2[i]) for i in f],
                  fill=(int(min(255, c[0])), int(min(255, c[1])), int(min(255, c[2]))),
                  outline=(15, 18, 20))


def _draw_arrow(d, R, alen, color, edge, cx, cy, foc, s=1.0, axis=(0.0, 0.0, 1.0)):
    """axis = 机身坐标系里的方向（默认 +Z；出图时用 X 轴＝机头方向）"""
    a = np.array(axis, float)
    a = a / (np.linalg.norm(a) or 1.0)
    P = np.array([[0.0, 0.0, 0.0], a * alen], float) @ R.T
    P2, _ = _project(P, cx, cy, foc)
    x0, y0 = P2[0]
    x1, y1 = P2[1]
    dx, dy = x1 - x0, y1 - y0
    ln = math.hypot(dx, dy) or 1.0
    ux, uy = dx / ln, dy / ln
    px, py = -uy, ux
    head = max(16.0 * s, min(46.0 * s, ln * 0.42))
    shaft = max(6.0 * s, min(18.0 * s, ln * 0.13))
    bx, by = x1 - ux * head, y1 - uy * head
    d.line([x0, y0, bx, by], fill=edge, width=int(shaft + 6 * s))
    d.line([x0, y0, bx, by], fill=color, width=int(shaft))
    d.polygon([(x1, y1), (bx + px * head * 0.78, by + py * head * 0.78),
               (bx - px * head * 0.78, by - py * head * 0.78)], fill=color, outline=edge)


# ------------------------------------------------------------------ 单帧
def _place(c, L, key):
    """把默认坐标按某个元素（ls/rs/att）的缩放/位移换算到实际位置"""
    return (c[0] + L.get(key + "_dx", 0.0), c[1] + L.get(key + "_dy", 0.0))


def _us_text(pwm):
    return "%d us" % int(round(pwm))


def _stick_widget(r, x, y, trail, style, fcol, bcol, alpha, show_us, up_txt, dn_txt,
                  tcol=None, tw=1.0):
    """画一根摇杆（含样式/颜色/透明度），返回 (RGBA 小图, 粘贴左上角偏移)

    整根摇杆先画成不透明的小图，再按 alpha 统一降透明度，
    这样叠在视频上才是真正半透明（不是和绿幕混色）。
    """
    s = r / 150.0
    pad = int(r * 0.85) + int(40 * s)
    size = int(2 * r + 2 * pad)
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = cy = size // 2
    px, py = cx + x * r, cy + y * r
    lw = max(1, int(3 * s))
    tcol_c = (tcol or (130, 205, 150))
    tw = max(0.3, float(tw or 1.0))

    if style == 0:                                  # 经典圆盘：深绿盘 + 十字 + 同心圆 + 绿轨迹
        d.ellipse([cx - r - 7 * s, cy - r - 7 * s, cx + r + 7 * s, cy + r + 7 * s],
                  fill=SHADOW + (255,))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=DISC + (255,),
                  outline=fcol + (255,), width=max(1, int(5 * s)))
        d.line([cx - r, cy, cx + r, cy], fill=GUIDE + (255,), width=max(1, int(2 * s)))
        d.line([cx, cy - r, cx, cy + r], fill=GUIDE + (255,), width=max(1, int(2 * s)))
        for j in range(1, 4):
            rr = r * j / 4
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=TICK + (255,), width=1)
        for i, (tx, ty) in enumerate(trail):
            sz = (5 + i) * s * tw
            d.ellipse([cx + tx - sz, cy + ty - sz, cx + tx + sz, cy + ty + sz],
                      fill=tcol_c + (255,))
        d.ellipse([px - 30 * s, py - 30 * s, px + 30 * s, py + 30 * s],
                  fill=bcol + (255,), outline=(255, 255, 255, 255), width=max(1, int(4 * s)))
        d.ellipse([px - 11 * s, py - 11 * s, px + 11 * s, py + 11 * s], fill=(20, 20, 20, 255))

    elif style == 1:                                # 圆角方框（示例图那种）
        box = [cx - r, cy - r, cx + r, cy + r]
        d.rounded_rectangle(box, radius=int(r * 0.24), fill=(36, 38, 42, 150),
                            outline=fcol + (255,), width=lw)
        # 四宫格细线
        d.line([cx, cy - r + 4 * s, cx, cy + r - 4 * s], fill=(255, 255, 255, 70),
               width=max(1, int(2 * s)))
        d.line([cx - r + 4 * s, cy, cx + r - 4 * s, cy], fill=(255, 255, 255, 70),
               width=max(1, int(2 * s)))
        # 轨迹：一点点白色小尾巴
        for i, (tx, ty) in enumerate(trail):
            sz = (2.5 + i) * s * tw
            d.ellipse([cx + tx - sz, cy + ty - sz, cx + tx + sz, cy + ty + sz],
                      fill=tcol_c + (140,))
        d.ellipse([px - 17 * s, py - 17 * s, px + 17 * s, py + 17 * s], fill=bcol + (255,))
        d.ellipse([px - 5.5 * s, py - 5.5 * s, px + 5.5 * s, py + 5.5 * s],
                  fill=(255, 255, 255, 245))

    elif style == 2:                                # 极简细线圆
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=fcol + (230,), width=lw)
        d.line([cx - r, cy, cx + r, cy], fill=fcol + (90,), width=max(1, int(2 * s)))
        d.line([cx, cy - r, cx, cy + r], fill=fcol + (90,), width=max(1, int(2 * s)))
        for i, (tx, ty) in enumerate(trail):
            sz = (2 + i) * s * tw
            d.ellipse([cx + tx - sz, cy + ty - sz, cx + tx + sz, cy + ty + sz],
                      fill=tcol_c + (110,))
        d.ellipse([px - 18 * s, py - 18 * s, px + 18 * s, py + 18 * s], fill=bcol + (255,))

    else:                                           # 极简细线方框
        d.rounded_rectangle([cx - r, cy - r, cx + r, cy + r], radius=int(r * 0.08),
                            outline=fcol + (230,), width=lw)
        d.line([cx - r, cy, cx + r, cy], fill=fcol + (80,), width=1)
        d.line([cx, cy - r, cx, cy + r], fill=fcol + (80,), width=1)
        for i, (tx, ty) in enumerate(trail):
            sz = (2 + i) * s * tw
            d.ellipse([cx + tx - sz, cy + ty - sz, cx + tx + sz, cy + ty + sz],
                      fill=tcol_c + (110,))
        d.ellipse([px - 17 * s, py - 17 * s, px + 17 * s, py + 17 * s], fill=bcol + (255,))

    # us 数值（示例图里那种 1505 us）
    if show_us:
        try:
            f = ImageFont.truetype("arialbd.ttf", int(40 * s))
        except Exception:
            try:
                f = ImageFont.truetype("arial.ttf", int(40 * s))
            except Exception:
                f = ImageFont.load_default()
        if up_txt:
            d.text((cx, cy - r - int(12 * s)), up_txt, font=f, anchor="mb",
                   fill=(255, 255, 255, 240))
        if dn_txt:
            d.text((cx, cy + r + int(12 * s)), dn_txt, font=f, anchor="mt",
                   fill=(255, 255, 255, 240))

    if alpha < 0.999:
        a = im.getchannel("A").point(lambda v: max(0, min(255, int(round(v * alpha)))))
        im.putalpha(a)
    return im, (int(round(cx)), int(round(cy)))


def render_one(k, img=None, only="all", save=True):
    """画第 k 帧。

    img=None 时新建绿幕画布（批处理路径）；也可以传一张透明画布，
    only="hud"/"map" 只画其中一层，用来给拖拽版式编辑器切图层。
    """
    I = INIT
    L = I["L"]
    if img is None:
        if I.get("alpha"):
            img = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
        else:
            img = Image.new("RGB", (CW, CH), GREEN)
    d = ImageDraw.Draw(img)

    # --- GPS 坐标遮盖（黑块）：先盖视频，HUD 再画在上面 ---
    #     （切图层时编辑器自己画矩形，这里不画）
    if only == "all":
        for pre in ("mask_", "mask2_"):
            on = L.get(pre + "on", 0.0)
            if on >= 0.5:
                x0 = L.get(pre + "x", 0.0)
                y0 = L.get(pre + "y", 110.0)
                w = L.get(pre + "w", 1920.0)
                h = L.get(pre + "h", 90.0)
                sh = int(round(L.get(pre + "shape", 0.0)))
                al = max(0.0, min(1.0, float(L.get(pre + "alpha", 1.0))))
                x1, y1 = x0 + w, y0 + h
                if al >= 0.999:
                    if sh == 1:
                        d.rounded_rectangle([x0, y0, x1, y1], radius=max(2, int(min(w, h) * 0.18)),
                                            fill=(0, 0, 0))
                    elif sh == 2:
                        d.ellipse([x0, y0, x1, y1], fill=(0, 0, 0))
                    else:
                        d.rectangle([x0, y0, x1, y1], fill=(0, 0, 0))
                else:
                    lay = Image.new("RGBA", (int(w), int(h)), (0, 0, 0, int(round(255 * al))))
                    msk = shape_mask((w, h), sh)
                    a = lay.getchannel("A").point(lambda v: v)
                    lay.putalpha(Image.composite(a, Image.new("L", (int(w), int(h)), 0), msk))
                    img.paste(lay, (int(round(x0)), int(round(y0))), lay)

    # --- 小地图（位置/大小/形状/透明度可调）---
    if only in ("all", "map") and I["map"] is not None:
        msize = I["map"].size[0]
        mk = msize / float(MAPSIZE0)          # 轨迹坐标从 360 空间换算
        mxpos = (int(round(L["map_dx"])), int(round(L["map_dy"])))
        panel = I["map"].copy()
        px, py = np.array(I["mx"], float) * mk, np.array(I["my"], float) * mk
        # 相机模式：1=起点居中 2=整条轨迹居中 3=位置居中（跟随飞机），都放大 2 倍
        cam = int(round(float(L.get("map_cam", 1.0))))
        auto_zoom = float(L.get("map_zoom", 1.0)) >= 0.5
        if cam >= 1:
            if cam == 2:
                Z = 1.0                      # 轨迹居中：整条轨迹装进小地图（自动适配）
            elif cam == 1:
                # 起点居中：中心取「起点与当前位置的中点」，按最远点自动缩放，
                # 这样起点和飞机都始终在画面内（不会飞出小地图）
                _cc = (float(px[0] + px[k]) / 2.0, float(py[0] + py[k]) / 2.0)
                if auto_zoom:
                    _dist = max(float(np.hypot(px[:k + 1] - _cc[0], py[:k + 1] - _cc[1]).max()),
                                float(np.hypot(px[0] - _cc[0], py[0] - _cc[1])))
                    Z = msize / max(msize * 0.40, 2.0 * _dist) if _dist > 1 else 2.4
                    Z = max(1.0, min(2.6, Z))
                else:
                    Z = 2.0
            else:
                Z = 2.0                      # 位置居中（跟随）：固定 2 倍
            w = max(60, int(msize / Z))
            if cam == 3:
                ccx, ccy = float(px[k]), float(py[k])
            elif cam == 2:
                ccx, ccy = float(px.mean()), float(py.mean())
            else:
                ccx, ccy = _cc
            x0 = int(min(max(0, ccx - w / 2.0), msize - w))
            y0 = int(min(max(0, ccy - w / 2.0), msize - w))
            sc = msize / float(w)
            panel = panel.crop((x0, y0, x0 + w, y0 + w)).resize((msize, msize), Image.BICUBIC)
            px = (px - x0) * sc
            py = (py - y0) * sc
            mk = mk * sc
        pd_ = ImageDraw.Draw(panel)
        if k > 0:
            step = max(1, k // 400)
            seq = [(px[i], py[i]) for i in range(0, k + 1, step)]
            if seq[-1] != (px[k], py[k]):
                seq.append((px[k], py[k]))
            if len(seq) > 1:
                tcol = FRAME_COLORS[int(round(L.get("map_trail_i", 5.0))) % len(FRAME_COLORS)]
                tws = max(0.3, min(3.0, float(L.get("map_trail_w", 1.0))))
                lw = max(2, int(9 * mk))
                pd_.line(seq, fill=(15, 15, 15), width=max(2, int(lw * tws)), joint="curve")
                pd_.line(seq, fill=tcol, width=max(1, int(lw * 0.55 * tws)), joint="curve")
                if L.get("map_wp_on", 0.0) >= 0.5 and len(seq) > 6:
                    step = max(6, len(seq) // 14)
                    for j, (qx, qy) in enumerate(seq):
                        if j % step:
                            continue
                        rw = 4.5 * mk
                        pd_.ellipse([qx - rw, qy - rw, qx + rw, qy + rw],
                                    fill=(255, 255, 255), outline=(20, 20, 20))
        # ---- 运动方向：指向下一个航点（GPS 航点多按 0.3 s 前瞻）----
        course = 0.0
        try:
            # 用「最近 1.5 秒实际走过的方向」当运动方向（和轨迹线严格一致）
            j1 = max(0, k - 90)
            j2 = min(len(px) - 1, k + 10)
            ddx, ddy = float(px[k] - px[j1]), float(py[k] - py[j1])
            if math.hypot(ddx, ddy) > 0.8:
                course = math.degrees(math.atan2(ddx, -ddy)) % 360.0
            else:
                ddx2, ddy2 = float(px[j2] - px[k]), float(py[j2] - py[k])
                if math.hypot(ddx2, ddy2) > 0.8:
                    course = math.degrees(math.atan2(ddx2, -ddy2)) % 360.0
                elif I.get("head") is not None and k < len(I["head"]):
                    course = float(I["head"][k])
        except Exception:
            course = 0.0
        up_mode = L.get("map_up", 0.0) >= 0.5
        sx, sy = px[k], py[k]
        r1, r2 = 12 * mk, 5 * mk
        # 标记（飞机点 / 航向箭头 / N）画在单独的透明层上，跟着地图一起转，不会错位
        # 先算好“旋转后飞机点在哪”，再在旋转后的图上直接画点和箭头，保证箭头朝上/对齐
        import numpy as _np
        if up_mode:
            try:
                panel = panel.rotate(-course, resample=Image.BICUBIC, expand=False)
            except Exception:
                pass
            probe = Image.new("L", panel.size, 0)
            ImageDraw.Draw(probe).ellipse([sx - 3, sy - 3, sx + 3, sy + 3], fill=255)
            try:
                probe = probe.rotate(-course, resample=Image.NEAREST, expand=False)
                arr = _np.array(probe)
                ys, xs = _np.nonzero(arr)
                if len(xs):
                    sx, sy = float(xs.mean()), float(ys.mean())
            except Exception:
                pass
        pd_ = ImageDraw.Draw(panel)
        r1, r2 = 12 * mk, 5 * mk
        pd_.ellipse([sx - r1, sy - r1, sx + r1, sy + r1], fill=(255, 255, 255),
                    outline=(20, 20, 20), width=max(1, int(3 * mk)))
        pd_.ellipse([sx - r2, sy - r2, sx + r2, sy + r2], fill=(225, 40, 40))
        if L.get("map_arrow", 0.0) >= 0.5:
            acol = FRAME_COLORS[int(round(L.get("map_arrow_i", 1.0))) % len(FRAME_COLORS)]
            ang = 0.0 if up_mode else math.radians(course)
            alen = max(14.0, 34 * mk)
            ax, ay = math.sin(ang), -math.cos(ang)
            ex_, ey_ = sx + ax * alen, sy + ay * alen
            hw = max(3.0, 7 * mk)
            pd_.line([sx, sy, ex_, ey_], fill=acol, width=max(2, int(5 * mk)))
            pd_.polygon([(ex_ + ax * hw, ey_ + ay * hw),
                         (ex_ - ay * hw, ey_ + ax * hw),
                         (ex_ + ay * hw, ey_ - ax * hw)],
                        fill=acol, outline=(15, 15, 15))
        try:
            ms = int(msize)
            nnx, nny = ms // 2, ms * 0.16
            if up_mode:
                nnx = ms // 2 - math.sin(math.radians(course)) * ms * 0.34
                nny = ms // 2 - math.cos(math.radians(course)) * ms * 0.34
            pd_.text((nnx, nny), "N", anchor="mm", fill=(255, 255, 255),
                     stroke_width=2, stroke_fill=(20, 20, 20))
        except Exception:
            pass
        s = msize
        pd_.polygon([(s - 26 * mk, 26 * mk), (s - 16 * mk, 48 * mk), (s - 36 * mk, 48 * mk)],
                    fill=(255, 255, 255), outline=(20, 20, 20))
        # 比例尺
        if L.get("map_scale_on", 0.0) >= 0.5:
            mpp = float(8.0 if META_MPP[0] <= 0 else META_MPP[0])
            want_m = 50.0 if mpp * s < 0.6 else 20.0
            bar_px = max(20.0, want_m / max(1e-6, mpp) / max(1e-6, mk))
            bx, by = s * 0.06, s - 22 * mk
            pd_.line([(bx, by), (bx + bar_px, by)], fill=(255, 255, 255), width=max(2, int(4 * mk)))
            for ex in (bx, bx + bar_px):
                pd_.line([(ex, by - 7 * mk), (ex, by + 7 * mk)], fill=(255, 255, 255),
                         width=max(2, int(4 * mk)))
            pd_.text((bx + bar_px / 2, by - 14 * mk), "%d m" % int(want_m), anchor="mb",
                     fill=(255, 255, 255))
        # 速度矢量
        if L.get("map_vec_on", 0.0) >= 0.5 and I.get("spd") is not None and I.get("course") is not None:
            sp = float(I["spd"][k])
            crs = float(I["course"][k])
            ln = min(s * 0.26, (6 + sp * 12) * mk)
            if ln > 6:
                # 航向朝上模式下，速度矢量也要跟着旋转（指向正上方）
                a = 0.0 if L.get("map_up", 0.0) >= 0.5 else math.radians(crs)
                ex, ey = sx + ln * math.sin(a), sy - ln * math.cos(a)
                pd_.line([(sx, sy), (ex, ey)], fill=(0, 240, 255), width=max(2, int(5 * mk)))
                pd_.polygon([(ex, ey),
                             (ex - 9 * mk * math.sin(a - 0.5), ey + 9 * mk * math.cos(a - 0.5)),
                             (ex - 9 * mk * math.sin(a + 0.5), ey + 9 * mk * math.cos(a + 0.5))],
                            fill=(0, 240, 255))
        # 事件标记（解锁/上锁）
        if L.get("event_on", 0.0) >= 0.5 and I.get("mx") is not None and len(I["mx"]) > 2:
            for j, col in ((0, (0, 255, 130)), (len(I["mx"]) - 1, (255, 70, 70))):
                ex, ey = px[j], py[j]
                pd_.ellipse([ex - 9 * mk, ey - 9 * mk, ex + 9 * mk, ey + 9 * mk],
                            outline=col, width=max(2, int(4 * mk)))
        # 形状 + 透明度
        msh = int(round(L.get("map_shape", 0.0)))
        mal = max(0.0, min(1.0, float(L.get("map_alpha", 1.0))))
        lay = panel.convert("RGBA")
        mm = shape_mask(lay.size, msh)
        if mal < 0.999:
            mm = mm.point(lambda v: max(0, min(255, int(round(v * mal)))))
        lay.putalpha(mm)
        try:
            META_MPP[0] = float(meta.get("span", 0)) * float(MM.meter_per_px(glat[0], meta)) / max(1e-6, float(meta.get("span", 1)))
        except Exception:
            META_MPP[0] = 0.0
        img.paste(lay, mxpos, lay)
        # 外框（按形状画）
        bx0, by0 = mxpos
        bx1, by1 = bx0 + s - 1, by0 + s - 1
        dot = (20, 20, 20)
        if msh == 1:
            r = max(4, int(s * 0.16))
            d.rounded_rectangle([bx0 - 3, by0 - 3, bx1 + 3, by1 + 3], radius=r + 3,
                                outline=dot, width=3)
            d.rounded_rectangle([bx0, by0, bx1, by1], radius=r, outline=(245, 245, 245), width=3)
        elif msh == 2:
            d.ellipse([bx0 - 3, by0 - 3, bx1 + 3, by1 + 3], outline=dot, width=3)
            d.ellipse([bx0, by0, bx1, by1], outline=(245, 245, 245), width=3)
        else:
            d.rectangle([bx0 - 3, by0 - 3, bx1 + 3, by1 + 3], outline=dot, width=3)
            d.rectangle([bx0, by0, bx1, by1], outline=(245, 245, 245), width=3)

    # --- 3D 姿态（位置/大小自己一套，和摇杆互不影响）---
    if only in ("all", "hud", "att") and I["Rf"] is not None:
        a_s = max(0.2, min(3.0, L.get("att_s", 1.0)))
        mcx = ATT_ANCHOR[0] + L.get("att_dx", 0.0)
        mcy = ATT_ANCHOR[1] + L.get("att_dy", 0.0)
        foc = FOC * a_s
        d.ellipse([mcx - 120 * a_s, mcy + 108 * a_s, mcx + 120 * a_s, mcy + 152 * a_s],
                  fill=(6, 32, 20))
        R = I["Rf"][k]
        # 人工地平线（可选）：放在飞机后面
        if L.get("horizon", 0.0) >= 0.5:
            try:
                _paste_horizon(img, R, mcx, mcy, 135 * a_s)
                d = ImageDraw.Draw(img)
            except Exception:
                pass
        # 正飞 / 倒飞 徽标
        up_w = R @ np.array([0.0, 0.0, 1.0])
        inverted = up_w[2] < 0.0
        bbextra.draw_event_badge(img, mcx - 150 * a_s, mcy - 175 * a_s,
                                 "INVERTED" if inverted else "UPRIGHT",
                                 (255, 70, 70) if inverted else (60, 220, 130),
                                 alpha=0.9, size=int(18 * max(0.6, a_s)))
        _draw_model(d, R, mcx, mcy, foc)
        # 红箭头指机头（机身 +X），白箭头指机尾；都顺着机身轴，不再垂直机身
        _draw_arrow(d, R, 1.15, (232, 44, 44), (255, 255, 255), mcx, mcy, foc, a_s,
                    axis=(1.0, 0.0, 0.0))
        _draw_arrow(d, R, 0.85, (245, 245, 245), (20, 20, 20), mcx, mcy, foc, a_s,
                    axis=(-1.0, 0.0, 0.0))

    # --- 摇杆（左右各自位置/大小；美国手 / 日本手）---
    cmd = I["cmd"]
    want_l = only in ("all", "hud", "sticks", "lstick")
    want_r = only in ("all", "hud", "sticks", "rstick")
    if want_l or want_r:
        x_yaw = np.clip(cmd[2] / 500.0, -1, 1)
        y_thr = np.clip(1 - 2 * (cmd[3] - 1000) / 1000.0, -1, 1)
        x_rol = np.clip(cmd[0] / 500.0, -1, 1)
        # 俯仰：黑匣子 rcCommand[1] 正 = 拉杆（抬头）→ 屏幕上点向下，符合真实杆位
        y_pit = np.clip(-cmd[1] / 500.0, -1, 1)
        # 通道反向（黑匣子里记录的是“指令值”，遥控器/飞控里做过反向时方向会与直觉相反）
        if L.get("inv_thr", 0.0) >= 0.5:
            y_thr = -y_thr
        if L.get("inv_rol", 0.0) >= 0.5:
            x_rol = -x_rol
        if L.get("inv_pit", 0.0) >= 0.5:
            y_pit = -y_pit
        if L.get("inv_yaw", 0.0) >= 0.5:
            x_yaw = -x_yaw
        mode2 = L.get("stick_mode", 2.0) >= 1.5
        style = int(round(L.get("stick_style", 0.0)))
        alpha = max(0.05, min(1.0, float(L.get("stick_alpha", 1.0))))
        fcol = FRAME_COLORS[int(round(L.get("frame_i", 0.0))) % len(FRAME_COLORS)]
        bcol = BALL_COLORS[int(round(L.get("ball_i", 0.0))) % len(BALL_COLORS)]
        show_us = L.get("show_us", 0.0) >= 0.5
        if mode2:      # 美国手：左=方向+油门，右=横滚+俯仰
            sticks = [(L_CENTER, "ls", x_yaw, y_thr, want_l,
                       _us_text(cmd[3, k]), _us_text(1500 + cmd[2, k])),
                      (R_CENTER, "rs", x_rol, y_pit, want_r,
                       _us_text(1500 + cmd[1, k]), _us_text(1500 + cmd[0, k]))]
        else:          # 日本手：左=方向+俯仰，右=横滚+油门
            sticks = [(L_CENTER, "ls", x_yaw, y_pit, want_l,
                       _us_text(1500 + cmd[1, k]), _us_text(1500 + cmd[2, k])),
                      (R_CENTER, "rs", x_rol, y_thr, want_r,
                       _us_text(cmd[3, k]), _us_text(1500 + cmd[0, k]))]
        for (bx, by), key, xs, ys, on, up_txt, dn_txt in sticks:
            if not on:
                continue
            sx = max(0.2, min(3.0, L.get(key + "_s", 1.0)))
            cx = bx + L.get(key + "_dx", 0.0)
            cy = by + L.get(key + "_dy", 0.0)
            r = R_STICK * sx
            k0 = max(0, k - max(0, int(round(float(L.get("trail_len", 6.0))))))
            tcol = FRAME_COLORS[int(round(L.get("trail_i", 4.0))) % len(FRAME_COLORS)]
            tw = max(0.3, min(3.0, float(L.get("trail_w", 1.0))))
            trail = [(float(xs[i]) * r, float(ys[i]) * r) for i in range(k0, k + 1)]
            wid, off = _stick_widget(r, float(xs[k]), float(ys[k]), trail, style, fcol, bcol,
                                     alpha, show_us, up_txt, dn_txt, tcol, tw)
            img.paste(wid, (int(round(cx)) - off[0], int(round(cy)) - off[1]), wid)


    # --- 数值面板 / 条形图 / 自定义文字 / 事件徽标 ---
    if only in ("all", "hud", "extra", "tele", "bars", "text"):
        Lx = L
        def _val(key, nd=1, unit=""):
            arr = I.get(key)
            if arr is None or k >= len(arr):
                return bbextra._fmt(None)
            return bbextra._fmt(arr[k], unit, nd)

        if Lx.get("tele_on", 0.0) >= 0.5 and only in ("all", "hud", "tele"):
            def _altv():
                """高度优先气压计；气压计在整段里几乎不动时改用 GPS 高度；都不动就返回 None"""
                bar = I.get("baro")
                gal = I.get("galt")
                if bar is not None:
                    span = float(np.max(bar) - np.min(bar)) / 100.0
                    if span >= 1.5:
                        return float(bar[k] - I.get("baro0", 0.0)) / 100.0
                if gal is not None:
                    if float(np.max(gal) - np.min(gal)) >= 1.5:
                        return float(gal[k] - I.get("galt0", 0.0))
                return None

            rows = [
                ("油门", _val("thr", 0, "") + "%" if False else
                 ("%d%%" % int(round((float(I["cmd"][3, k]) - 1000) / 10.0)))),
                ("电压", bbextra._fmt(
                    (float(I["vbat"][k]) * float(I.get("vbat_auto_k", 1.0))
                     * float(Lx.get("vbat_k", 1.0))
                     + float(Lx.get("vbat_b", 0.0))) if I.get("vbat") is not None else None, " V", 2)),
                ("电流", bbextra._fmt(
                    (float(I["amp"][k]) * float(Lx.get("amp_k", 1.0))
                     + float(Lx.get("amp_b", 0.0))) if I.get("amp") is not None else None, " A", 1)),
            ]
            bbextra.draw_telemetry(img,
                                   Lx.get("tele_x", 60.0) + Lx.get("extra_dx", 0.0) + Lx.get("tele_dx", 0.0),
                                   Lx.get("tele_y", 380.0) + Lx.get("extra_dy", 0.0) + Lx.get("tele_dy", 0.0),
                                   rows,
                                   alpha=float(Lx.get("tele_alpha", 0.9)),
                                   size=float(Lx.get("tele_size", 30.0)) * max(0.4, float(Lx.get("tele_s", 1.0))),
                                   color_i=int(round(Lx.get("tele_i", 0.0))))

        if Lx.get("bar_on", 0.0) >= 0.5 and only in ("all", "hud", "bars"):
            thr = max(0.0, min(1.0, (float(I["cmd"][3, k]) - 1000) / 1000.0))
            vb = I.get("vbat")
            vv = 0.0
            if vb is not None and k < len(vb):
                _v = (float(vb[k]) * float(I.get("vbat_auto_k", 1.0))
                      * float(Lx.get("vbat_k", 1.0)) + float(Lx.get("vbat_b", 0.0)))
                vv = max(0.0, min(1.0, (_v - 9.0) / (16.8 - 9.0)))
            items = [(thr, TEXT_TRAIL_COL[0], "THR"), (vv, TEXT_TRAIL_COL[1], "BAT")]
            _bs = max(0.3, float(Lx.get("bar_s", 1.0)))
            bbextra.draw_bars(img,
                              Lx.get("bar_x", 60.0) + Lx.get("extra_dx", 0.0) + Lx.get("bar_dx", 0.0),
                              Lx.get("bar_y", 760.0) + Lx.get("extra_dy", 0.0) + Lx.get("bar_dy", 0.0),
                              float(Lx.get("bar_h", 200.0)) * _bs, items,
                              alpha=float(Lx.get("bar_alpha", 0.9)),
                              color_i=int(round(Lx.get("bar_i", 0.0))))

        if Lx.get("text_on", 0.0) >= 0.5 and I.get("text") and only in ("all", "hud", "text"):
            anchors = ["lt", "mt", "rt", "lm", "mm", "rm", "lb", "mb", "rb"]
            at = anchors[int(round(Lx.get("text_anchor", 0.0))) % len(anchors)]
            bbextra.draw_text(img,
                              Lx.get("text_x", 960.0) + Lx.get("extra_dx", 0.0) + Lx.get("text_dx", 0.0),
                              Lx.get("text_y", 60.0) + Lx.get("extra_dy", 0.0) + Lx.get("text_dy", 0.0),
                              I["text"],
                              size=float(Lx.get("text_size", 44.0)) * max(0.4, float(Lx.get("text_s", 1.0))),
                              color_i=int(round(Lx.get("text_i", 1.0))),
                              alpha=float(Lx.get("text_alpha", 0.9)), anchor=at)

        if Lx.get("event_on", 0.0) >= 0.5 and I.get("cmd") is not None:
            # 解锁/上锁：rcCommand[3] 从 1000 起跳的那一帧算解锁
            thr_arr = I["cmd"][3]
            arm = int(np.argmax(thr_arr > 1050)) if (thr_arr > 1050).any() else -1
            if arm == k:
                bbextra.draw_event_badge(img, 200, 150, "ARM", (0, 255, 130))
            if arm >= 0 and k == len(thr_arr) - 1:
                bbextra.draw_event_badge(img, 200, 150, "DISARM", (255, 70, 70))

    if save:
        img.save(os.path.join(INIT["out"], "f%05d.png" % k), compress_level=1)
    return k


def render_layers(csv_path, gps_csv, start_bb, dur, out_dir, fps=FPS,
                  want_att=True, want_map=True, log=print, map_image=None,
                  map_center=None, map_mpp=None, map_rotate=None, layout=None,
                  text="", portrait=False):
    """给「拖拽版式」用：把 HUD 层和小地图层分别存成透明 PNG（默认版式、原始位置）"""
    os.makedirs(out_dir, exist_ok=True)
    # 元素摆在基准位置（dx=0/s=1），拖动由编辑器自己叠，避免位移算两遍
    L0 = layer_layout(layout, portrait=portrait)
    npz, map_png, n = prepare(csv_path, gps_csv, start_bb, dur, out_dir, fps=fps,
                              want_att=want_att, want_map=want_map, log=log,
                              map_image=map_image, map_center=map_center,
                              map_mpp=map_mpp, map_rotate=map_rotate, layout=L0,
                              alpha=True, text=text, portrait=portrait, preset=False)
    _init_worker(npz, map_png, out_dir)
    k = min(n - 1, int(n // 2))
    def layer(kind):
        # 竖屏时画布是 1080x1920，切图层必须跟着 _init_worker 设的 CW/CH，
        # 否则 y>1080 的元素（竖屏摇杆在 y≈1410）会被裁掉，元素位置里也放不下
        im = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
        render_one(k, img=im, only=kind, save=False)
        pth = os.path.join(out_dir, "%s_layer.png" % kind)
        im.save(pth)
        return pth

    out = dict(lstick=layer("lstick"), rstick=layer("rstick"),
               att=layer("att"), map=layer("map"), extra=layer("extra"),
               tele=layer("tele"), bars=layer("bars"), text=layer("text"),
               k=k, n=n, size=(CW, CH),
               stick_mode=float(LAYOUT["stick_mode"]))
    return out


# ------------------------------------------------------------------ 准备 + 并行
def _init_worker(npz, map_png, out):
    z = np.load(npz)
    INIT["cmd"] = z["cmd"]
    INIT["Rf"] = z["Rf"] if "Rf" in z.files else None
    INIT["mx"] = z["mx"] if "mx" in z.files else None
    INIT["my"] = z["my"] if "my" in z.files else None
    if "layout" in z.files:
        a = z["layout"]
        d = dict(LAYOUT)
        for i, key in enumerate(LAYOUT_KEYS):
            if i < len(a):
                d[key] = float(a[i])
        INIT["L"] = d
    else:
        INIT["L"] = dict(LAYOUT)
    INIT["map"] = None
    if map_png:
        im = Image.open(map_png).convert("RGB")
        ms = max(80, min(1000, int(round(MAPSIZE0 * INIT["L"]["map_s"]))))
        INIT["map"] = im.resize((ms, ms), Image.LANCZOS) if ms != im.size[0] else im
    INIT["alpha"] = bool(z["alpha"][0] >= 0.5) if "alpha" in z.files else False
    global CW, CH
    if "size" in z.files:
        CW, CH = int(z["size"][0]), int(z["size"][1])
    else:
        CW, CH = W, H
    for key in ("vbat", "vbat_auto_k", "amp", "baro", "baro0", "rssi", "spd", "galt", "galt0",
                "sats", "course", "head"):
        INIT[key] = z[key] if key in z.files else None
    INIT["text"] = bytes(z["text"].tobytes()).decode("utf-8", "ignore") if "text" in z.files else ""
    if "obj" in z.files:
        try:
            pth = bytes(z["obj"].tobytes()).decode("utf-8", "ignore")
            V, F, C = load_obj(pth)
            globals()["V_M"], globals()["F_M"], globals()["C_M"] = V, F, C
        except Exception as e:
            log_e = "（OBJ 加载失败：%s）" % e
            INIT["text"] = INIT.get("text", "")
    INIT["out"] = out


def prepare(csv_path, gps_csv, start_bb, dur, out_frames, fps=FPS,
            want_att=True, want_map=True, log=print, map_image=None,
            map_center=None, map_mpp=None, map_rotate=None, layout=None,
            alpha=True, text="", obj="", portrait=False, preset=True):
    """算好每帧要用的数组，写成 npz；返回 (npz路径, 底图png, 帧数)

    preset=True：竖屏时套用 portrait_layout 预设（正式出片走这条）；
    preset=False：版式已经排好（切图层用 layer_layout 摆基准位置），不要再套预设。
    """
    os.makedirs(out_frames, exist_ok=True)
    log("  读黑匣子 %s" % os.path.basename(csv_path))
    t, rc, gyro, acc, t0, ext = read_csv(csv_path, need_att=want_att, log=log)
    n = int(round(dur * fps))
    tt = start_bb + np.arange(n) / float(fps)
    if tt[-1] > t[-1]:
        raise RuntimeError("时间超出日志范围：要 %.1f~%.1f s，日志只有 0~%.1f s"
                           % (tt[0], tt[-1], t[-1]))
    cmd = np.vstack([np.interp(tt, t, rc[i]) for i in range(4)])
    L = norm_layout(layout)
    if portrait and preset:
        L = portrait_layout(L)
    data = dict(cmd=cmd.astype(np.float32),
                layout=np.array([L[k] for k in LAYOUT_KEYS], dtype=np.float32),
                alpha=np.array([1.0 if alpha else 0.0], np.float32))
    # 电压 / 电流 / 气压 / 信号（没有的列用 nan）
    for key in ("vbat", "amp", "baro", "rssi"):
        if key in ext and len(ext[key]):
            data[key] = np.interp(tt, t, ext[key]).astype(np.float32)
    data["size"] = np.array([PORTRAIT_W if portrait else W,
                             PORTRAIT_H if portrait else H], np.float32)
    if obj:
        data["obj"] = np.frombuffer(obj.encode("utf-8"), dtype=np.uint8)
    # 文字水印内容
    if text:
        data["text"] = np.frombuffer(text.encode("utf-8"), dtype=np.uint8)
    # ---- 航向（给「小地图航向朝上」用）：GPS 航向 → 轨迹方向 → 沿用上一次 ----
    head = None
    if gps_csv and os.path.exists(gps_csv):
        try:
            _gps = _read_gps(gps_csv)
            gt = _gps["t"]
            crs = np.interp(tt, gt, _gps["course"])
            spd = np.abs(np.interp(tt, gt, _gps["speed"]))
            if float(np.nanmedian(spd)) > 60:
                spd = spd / 100.0
            head = crs % 360.0
            # 速度太小时 GPS 航向不可信，标成无效（后面用轨迹方向补）
            head = np.where(spd > 0.3, head, np.nan)
        except Exception:
            head = None
    if head is None:
        head = np.full(len(tt), np.nan)
    # 无效处用轨迹方向补（窗口 40 帧 ≈ 0.7 s，避免悬停抖动）
    if want_map and "mx" in data and "my" in data:
        mx, my = data["mx"], data["my"]
        w = 120
        for i in range(len(head)):
            if not np.isnan(head[i]):
                continue
            j = max(0, i - w)
            ddx, ddy = float(mx[i] - mx[j]), float(my[i] - my[j])
            if math.hypot(ddx, ddy) > 1.5:
                head[i] = math.degrees(math.atan2(ddx, -ddy)) % 360.0
    # 兜底：仍无效就退回原始 GPS 航向（哪怕低速，也比 0 好）
    if gps_csv and os.path.exists(gps_csv):
        try:
            import pandas as _pd
            _g = _pd.read_csv(gps_csv, skipinitialspace=True, low_memory=False)
            _gt = _g.iloc[:, 0].values.astype(float) / 1e6
            if "GPS_ground_course" in _g.columns:
                _raw = np.interp(tt, _gt, _g["GPS_ground_course"].values.astype(float)) % 360.0
                head = np.where(np.isnan(head), _raw, head)
        except Exception:
            pass
    # 还是无效就沿用上一次有效值（前进填充）
    last = 0.0
    for i in range(len(head)):
        if np.isnan(head[i]):
            head[i] = last
        else:
            last = head[i]
    # 轻度平滑，避免箭头抖
    if len(head) > 5:
        k = np.ones(5) / 5.0
        head = np.convolve(np.concatenate([head[:2][::-1], head, head[-2:]]), k, mode="same")[2:-2]
    data["head"] = head.astype(np.float32)
    # 电压自动校准：整段 98 分位低于 16.2V 时，按满电 16.8V 自动补比例（老固件 vbat 偏低）
    try:
        if data.get("vbat") is not None and len(data["vbat"]):
            _p98 = float(np.nanpercentile(data["vbat"], 99.5))
            data["vbat_auto_k"] = np.float32(
                1.0 if _p98 >= 16.2 or _p98 <= 8 else min(1.6, 16.6 / _p98))
    except Exception:
        pass
    # 高度基线（起飞点）：气压计和 GPS 高度都减去第一个值
    for _k, _k0 in (("baro", "baro0"), ("galt", "galt0")):
        if data.get(_k) is not None and len(data[_k]):
            _raw = ext.get(_k)
            if _raw is not None and len(_raw):
                data[_k0] = np.float32(float(_raw[0]))      # 整段日志起点（解锁/起飞）
            else:
                data[_k0] = np.float32(float(data[_k][0]))

    # GPS 速度 / 高度 / 卫星数（有 gps csv 才存）
    if gps_csv and os.path.exists(gps_csv):
        try:
            _gps2 = _read_gps(gps_csv)
            gt = _gps2["t"]
            # 速度：用 GPS_speed（自动判别 cm/s 还是 m/s）
            _raw = np.abs(np.interp(tt, gt, _gps2["speed"]))
            _med = float(np.nanmedian(_raw))
            # 老固件记 cm/s（几百~几千），新固件记 m/s（0~40）
            sp = _raw / 100.0 if _med > 60 else _raw
            data["spd"] = np.clip(sp, 0, 120).astype(np.float32)
            data["course"] = np.interp(tt, gt, _gps2["course"]).astype(np.float32)
            sat = np.interp(tt, gt, _gps2["sats"])
            sat = np.where((sat > 0) & (sat <= 40), sat, np.nan)
            data["sats"] = sat.astype(np.float32)
        except Exception:
            pass

    if want_att:
        log("  算姿态（Mahony）...")
        # 姿态反向（黑匣子陀螺符号和模型轴向可能相反）：按开关翻一下，不改原始数据
        gyro_a = np.array(gyro, dtype=float, copy=True)
        if float(L.get("att_inv_rol", 0.0)) >= 0.5:
            gyro_a[0] *= -1.0
        if float(L.get("att_inv_pit", 0.0)) >= 0.5:
            gyro_a[1] *= -1.0
        gyro = gyro_a
        if float(L.get("att_mode", 1.0)) >= 0.5:      # 1=重力(默认) 0=陀螺积分
            data["Rf"] = rotations_tilt(t, gyro, acc, tt, log=log,
                                        yaw_off=float(L.get("att_yaw", 0.0))).astype(np.float32)
        else:
            data["Rf"] = rotations(t, gyro, acc, tt, log=log).astype(np.float32)

    map_png = None
    if want_map and gps_csv and os.path.exists(gps_csv):
        try:
            if map_image:
                import bbphotomap
                log("  用自己的航拍图当底图 ...")
                ctr = None
                if isinstance(map_center, str) and "," in map_center:
                    a, b = map_center.split(",")[:2]
                    ctr = (float(a), float(b))          # 传的是 lat,lon
                elif isinstance(map_center, (tuple, list)) and len(map_center) == 2:
                    ctr = (float(map_center[0]), float(map_center[1]))
                base, meta, (gt, glat, glon) = bbphotomap.build(
                    map_image, gps_csv, t0, start_bb, start_bb + dur,
                    log=log, center=ctr, mpp=map_mpp, rotate=map_rotate)
                screen = bbphotomap.to_screen
            else:
                log("  拼卫星底图 ...")
                base, meta, (gt, glat, glon) = MM.build(gps_csv, t0, start_bb,
                                                        start_bb + dur, log=log)
                screen = MM.to_screen
                log("    地图范围 %.0f m" % (meta["span"] * MM.meter_per_px(glat[0], meta)))
            map_png = os.path.join(os.path.dirname(out_frames), "minimap_base.png")
            base.save(map_png)
            pts = np.array([screen(a, b, meta) for a, b in zip(glat, glon)], float)
            order = np.argsort(gt)
            gt, pts = gt[order], pts[order]
            data["mx"] = np.interp(tt, gt, pts[:, 0]).astype(np.float32)
            data["my"] = np.interp(tt, gt, pts[:, 1]).astype(np.float32)
        except Exception as e:                     # 没网 / 没 GPS / 照片标定不对
            log("    小地图跳过：%s" % e)
            map_png = None

    npz = os.path.join(out_frames, "frame_data.npz")
    np.savez(npz, **data)
    return npz, map_png, n


def render(csv_path, gps_csv, start_bb, dur, out_frames, fps=FPS, jobs=None,
           want_att=True, want_map=True, log=print, map_image=None,
           map_center=None, map_mpp=None, map_rotate=None, layout=None, text="", obj="",
           portrait=False):
    npz, map_png, n = prepare(csv_path, gps_csv, start_bb, dur, out_frames, fps=fps,
                              want_att=want_att, want_map=want_map, log=log,
                              map_image=map_image, map_center=map_center,
                              map_mpp=map_mpp, map_rotate=map_rotate, layout=layout,
                              alpha=True, text=text, obj=obj, portrait=portrait)
    if jobs is None:
        jobs = max(1, min(12, (os.cpu_count() or 4) - 2))
    log("  渲染 %d 帧（%d 进程）..." % (n, jobs))
    if jobs == 1:
        _init_worker(npz, map_png, out_frames)
        for k in range(n):
            render_one(k)
            if k % 300 == 0:
                log("    %d/%d" % (k, n))
    else:
        import multiprocessing as mp
        ctx = mp.get_context("spawn")
        with ctx.Pool(jobs, initializer=_init_worker, initargs=(npz, map_png, out_frames)) as pool:
            done = 0
            for _ in pool.imap_unordered(render_one, range(n), chunksize=8):
                done += 1
                if done % 600 == 0:
                    log("    %d/%d" % (done, n))
    return n


if __name__ == "__main__":
    # 单帧预览：csv gps_csv start_bb 帧号 输出png
    csv, gps, start, idx, png = sys.argv[1], sys.argv[2], float(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
    out = os.path.join(os.path.dirname(os.path.abspath(png)), "_preview_frames")
    npz, map_png, n = prepare(csv, gps, start, max(1.0, (idx + 2) / FPS), out)
    _init_worker(npz, map_png, out)
    render_one(idx)
    Image.open(os.path.join(out, "f%05d.png" % idx)).save(png)
    print("saved", png)