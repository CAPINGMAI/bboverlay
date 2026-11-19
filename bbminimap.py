"""bboverlay / bbminimap —— 高德卫星小地图底图 + 经纬度投影

坐标注意：高德是 GCJ-02（火星坐标），黑匣子 GPS 是 WGS-84，
所有点都必须先 wgs2gcj 再投影，否则会偏几百米。
"""
import math
import os
import subprocess

import numpy as np
import pandas as pd
from PIL import Image

Z = 18
MARGIN = 1.35

# ⚠️ 默认用高德卫星瓦片（仅供个人学习/本地预览）。批量抓取、再分发或商用不符合
#    高德地图的服务条款；如需公开发布请改用天地图（官方 key）或自备正射影像底图。
#    可以用环境变量 BBOVERLAY_TILE_URL 换成自己的瓦片地址（%d 依次为 x, y, z）。
URL = os.environ.get(
    "BBOVERLAY_TILE_URL",
    "https://webst01.is.autonavi.com/appmaptile?style=6&x=%d&y=%d&z=%d")


def wgs2gcj(lat, lon):
    a = 6378245.0
    ee = 0.00669342162296594323

    def tf_lat(x, y):
        r = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
        r += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        r += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
        r += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
        return r

    def tf_lon(x, y):
        r = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        r += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        r += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
        r += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
        return r

    dlat = tf_lat(lon - 105.0, lat - 35.0)
    dlon = tf_lon(lon - 105.0, lat - 35.0)
    rl = lat / 180.0 * math.pi
    m = math.sin(rl)
    m = 1 - ee * m * m
    sm = math.sqrt(m)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (m * sm) * math.pi)
    dlon = (dlon * 180.0) / (a / sm * math.cos(rl) * math.pi)
    return lat + dlat, lon + dlon


def lonlat_to_px(lat, lon, z=Z):
    n = 2 ** z * 256
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.log(math.tan(math.radians(lat)) + 1.0 / math.cos(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def _tile(cache, x, y, log=print):
    os.makedirs(cache, exist_ok=True)
    fn = os.path.join(cache, "z%d_%d_%d.png" % (Z, x, y))
    if not os.path.exists(fn) or os.path.getsize(fn) < 500:
        subprocess.run(["curl", "-s", "-A", "Mozilla/5.0", "--max-time", "25",
                        "-o", fn, URL % (x, y, Z)])
    return fn


def build(gps_csv, t0, t_start, t_end, size=360, cache=None, log=print):
    """按 GPS 轨迹范围拼一张 size×size 卫星底图

    返回 (底图 Image, meta, (黑色匣子时间轴, lat, lon))
    """
    if cache is None:
        cache = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "tiles")
    # gps.csv 的表头少两列（blackbox_decode 在行尾多写了 home 经纬度），补名字再读
    with open(gps_csv, "r", encoding="utf-8-sig", errors="replace") as f:
        hdr = [c.strip() for c in f.readline().split(",")]
        first = f.readline()
    ncol = len(first.split(",")) if first.strip() else len(hdr)
    names = hdr + ["_x%d" % i for i in range(max(0, ncol - len(hdr)))]
    df = pd.read_csv(gps_csv, skipinitialspace=True, header=0, names=names)
    cols = list(names)
    tcol = next(c for c in cols if c.startswith("time"))
    # t0 是主日志第一帧的时间（秒），gps.csv 用绝对 micros，换算到主日志时间轴
    tt = df[tcol].values.astype(float) / 1e6 - t0
    lat = df["GPS_coord[0]"].values.astype(float)
    lon = df["GPS_coord[1]"].values.astype(float)

    m = (tt >= t_start - 2) & (tt <= t_end + 2)
    if m.sum() < 5:
        m = np.isfinite(lat) & np.isfinite(lon) & (lat > 0) & (np.abs(lon) > 1)
    if m.sum() < 5:
        raise RuntimeError("GPS 数据太少，做不了小地图")
    gl = np.array([wgs2gcj(a, b) for a, b in zip(lat[m], lon[m])])
    xs = np.array([lonlat_to_px(a, b)[0] for a, b in gl])
    ys = np.array([lonlat_to_px(a, b)[1] for a, b in gl])
    cx, cy = (xs.min() + xs.max()) / 2.0, (ys.min() + ys.max()) / 2.0
    span = max((xs.max() - xs.min()) * MARGIN, (ys.max() - ys.min()) * MARGIN, 120.0)
    left, top = cx - span / 2.0, cy - span / 2.0
    x0, x1 = int(math.floor(left / 256)), int(math.floor((left + span) / 256))
    y0, y1 = int(math.floor(top / 256)), int(math.floor((top + span) / 256))
    canvas = Image.new("RGB", ((x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256), (30, 40, 30))
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            try:
                canvas.paste(Image.open(_tile(cache, x, y, log)).convert("RGB"),
                             ((x - x0) * 256, (y - y0) * 256))
            except Exception as e:                      # 没网/瓦片坏
                log("    瓦片缺失 %d,%d（%s）" % (x, y, e))
    cx0, cy0 = int(round(left - x0 * 256)), int(round(top - y0 * 256))
    span_i = int(math.ceil(span))
    crop = canvas.crop((cx0, cy0, cx0 + span_i, cy0 + span_i)).resize((size, size), Image.LANCZOS)
    meta = dict(left=x0 * 256 + cx0, top=y0 * 256 + cy0, span=span,
                scale=size / float(span_i), z=Z)
    return crop, meta, (tt, lat, lon)


def to_screen(lat, lon, meta):
    g = wgs2gcj(lat, lon)
    x, y = lonlat_to_px(g[0], g[1], meta.get("z", Z))
    s = meta.get("scale", 1.0)
    return (x - meta["left"]) * s, (y - meta["top"]) * s


def meter_per_px(lat, meta):
    return (40075016.0 / (2 ** (meta.get("z", Z) + 8))) * math.cos(math.radians(lat)) / meta.get("scale", 1.0)