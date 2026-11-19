"""bboverlay / bbphotomap —— 用自己航拍的正射图（或一张正俯视照片）当小地图底图

和在线卫星图最大的区别：**自己拍的图是真 WGS-84 坐标，不做火星坐标纠偏**。

标定三件事（能从 EXIF 读的自动读，读不到就用参数补）：
    中心经纬度  —— 照片中心对应哪儿（默认取轨迹中心）
    米 / 像素   —— 正俯视照片可由「高度 × 36 ÷ 等效焦距 ÷ 像宽」算出
    旋转角      —— 图上方朝哪个方向（0 = 朝北；DJI 读 GimbalYawDegree）
"""
import math
import os
import re

import numpy as np
import pandas as pd
from PIL import Image

EXIF_GPS = 34853
LAT_REF, LAT, LON_REF, LON = 1, 2, 3, 4
ALT_REF, ALT = 5, 6


def _dms(v):
    try:
        d, m, s = v
        return float(d) + float(m) / 60.0 + float(s) / 3600.0
    except Exception:
        return None


def _num(v):
    """EXIF 里的数可能是 (num,den) 有理数，也可能已经是小数"""
    try:
        if isinstance(v, (tuple, list)) and len(v) == 2:
            return float(v[0]) / float(v[1])
        return float(v)
    except Exception:
        return None


def read_info(path, log=print):
    """尽力从 EXIF / DJI XMP 里读出 经纬度 / 高度 / 等效焦距 / 机头朝向"""
    info = dict(width=None, height=None, lat=None, lon=None, alt_m=None,
                f35=None, yaw=None, mpp=None)
    try:
        im = Image.open(path)
        info["width"], info["height"] = im.size
        ex = im.getexif() or {}
        try:
            gps = ex.get_ifd(EXIF_GPS) or {}
        except Exception:
            gps = {}
        if LAT in gps and LON in gps:
            lat, lon = _dms(gps.get(LAT)), _dms(gps.get(LON))
            if lat is not None and lon is not None:
                if gps.get(LAT_REF) in ("S", b"S"):
                    lat = -lat
                if gps.get(LON_REF) in ("W", b"W"):
                    lon = -lon
                info["lat"], info["lon"] = lat, lon
        if ALT in gps:
            a = _num(gps[ALT])
            if a is not None:
                ref = gps.get(ALT_REF, 0)
                ref = ref[0] if isinstance(ref, (bytes, bytearray)) else ref
                info["alt_m"] = -a if ref == 1 else a
        f35 = ex.get(41989)                        # FocalLengthIn35mmFilm
        if not f35:
            try:
                f35 = ex.get_ifd(34665).get(41989)  # 有的机器放在 Exif 子 IFD 里
            except Exception:
                f35 = None
        if f35:
            info["f35"] = float(f35)
    except Exception as e:
        log("    读照片信息失败：%s" % e)

    # DJI 的相对高度 / 机头朝向写在 XMP 里
    try:
        with open(path, "rb") as f:
            head = f.read(300000)
        m = re.search(rb'drone-dji:RelativeAltitude="([+-]?[0-9.]+)"', head)
        if m:
            info["alt_m"] = abs(float(m.group(1)))
        y = re.search(rb'drone-dji:(?:GimbalYawDegree|FlightYawDegree)="([+-]?[0-9.]+)"', head)
        if y:
            info["yaw"] = float(y.group(1))
    except Exception:
        pass

    if info["alt_m"] and info["f35"] and info["width"]:
        # 正俯视：地面宽度 = 高度 × 36 / 等效焦距
        info["mpp"] = (info["alt_m"] * 36.0 / info["f35"]) / float(info["width"])
    return info


def _gps_series(gps_csv, t0):
    # gps.csv 表头比数据少两列（解码器在行尾多写了 home 经纬度），补名字再读
    with open(gps_csv, "r", encoding="utf-8-sig", errors="replace") as f:
        hdr = [c.strip() for c in f.readline().split(",")]
        first = f.readline()
    ncol = len(first.split(",")) if first.strip() else len(hdr)
    names = hdr + ["_x%d" % i for i in range(max(0, ncol - len(hdr)))]
    df = pd.read_csv(gps_csv, skipinitialspace=True, header=0, names=names)
    tcol = next(c for c in names if c.startswith("time"))
    tt = df[tcol].values.astype(float) / 1e6 - t0
    lat = df["GPS_coord[0]"].values.astype(float)
    lon = df["GPS_coord[1]"].values.astype(float)
    return tt, lat, lon


def _track_center(tt, lat, lon, t_start, t_end):
    m = (tt >= t_start - 2) & (tt <= t_end + 2) & np.isfinite(lat) & (lat != 0)
    if m.sum() < 5:
        m = np.isfinite(lat) & (lat != 0)
    if m.sum() < 5:
        raise RuntimeError("GPS 数据太少，做不了底图")
    return float((lat[m].min() + lat[m].max()) / 2), float((lon[m].min() + lon[m].max()) / 2)


def _meters(lat, lon, lat0, lon0):
    e = (np.asarray(lon) - lon0) * 111320.0 * math.cos(math.radians(lat0))
    n = (np.asarray(lat) - lat0) * 110540.0
    return e, n


def _to_uv(e, n, rot):
    """世界(东,北) → 底图自身坐标(向右 u, 向下 v)；rot = 图上方朝向（度，顺时针离北）"""
    a = math.radians(rot)
    u = e * math.cos(a) - n * math.sin(a)
    v = -(e * math.sin(a) + n * math.cos(a))
    return u, v


def build(img_path, gps_csv, t0, t_start, t_end, size=360, center=None,
          mpp=None, rotate=None, log=print):
    """返回 (底图 Image, meta, (轨迹时间轴, lat, lon))"""
    info = read_info(img_path, log=log)
    tt, lat, lon = _gps_series(gps_csv, t0)
    lat0, lon0 = _track_center(tt, lat, lon, t_start, t_end)
    if center:                                  # center 传的是 (lat, lon)
        lat0, lon0 = float(center[0]), float(center[1])
    mpp = mpp or info.get("mpp")
    rotate = info.get("yaw") if rotate is None else rotate
    rotate = 0.0 if rotate is None else float(rotate)
    if not mpp:
        raise RuntimeError("算不出底图「米/像素」：EXIF 里没有高度或焦距，请手动填（--map-mpp）")

    photo = Image.open(img_path).convert("RGBA")
    W, H = photo.size
    plat = info["lat"] if info.get("lat") is not None else lat0
    plon = info["lon"] if info.get("lon") is not None else lon0
    src = "EXIF" if info.get("lat") is not None else "参数/轨迹"

    # 轨迹在底图坐标里的范围 → 决定显示跨度（留 35% 余量）
    e, n = _meters(lat, lon, lat0, lon0)
    u, v = _to_uv(e, n, rotate)
    span_m = max(float(u.max() - u.min()) * 1.35, float(v.max() - v.min()) * 1.35, 60.0)
    span_m = min(span_m, 4000.0)
    mpp_out = span_m / float(size)          # 屏幕上 1 像素代表多少米

    # 照片中心相对轨迹中心的偏移
    ep, np_ = _meters(plat, plon, lat0, lon0)
    up, vp = _to_uv(ep, np_, rotate)
    # 输出像素 (x,y) → 照片像素：纯缩放 + 平移（旋转已含在 u,v 里）
    k = mpp_out / float(mpp)
    c = -size / 2.0 * k - float(up) / mpp + W / 2.0
    f = -size / 2.0 * k - float(vp) / mpp + H / 2.0
    moved = photo.transform((size, size), Image.AFFINE, (k, 0, c, 0, k, f),
                            resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0))
    base = Image.new("RGB", (size, size), (18, 26, 20))
    base.paste(moved, (0, 0), moved)

    cover = (W * mpp) / span_m               # 照片横向覆盖屏宽的多少
    cover_h = (H * mpp) / span_m
    if cover < 1.0 or cover_h < 1.0:
        log("    注意：照片只盖住屏幕 %.0f%%×%.0f%%，四周会露底色（想更满就飞高一点或换大图）"
            % (min(cover, 1) * 100, min(cover_h, 1) * 100))
    log("    底图 %s  %dx%d  %.4f 米/像素  旋转 %.0f°  中心 %.6f,%.6f（来自%s）  视野 %.0f 米"
        % (os.path.basename(img_path), W, H, mpp, rotate, lat0, lon0, src, span_m))
    meta = dict(kind="photo", lat0=lat0, lon0=lon0, mpp=mpp_out, rot=rotate,
                size=size, frame="wgs")
    return base, meta, (tt, lat, lon)


def to_screen(lat, lon, meta):
    """轨迹点 → 屏幕像素（自己拍的图不做火星坐标纠偏）"""
    e, n = _meters(lat, lon, meta["lat0"], meta["lon0"])
    u, v = _to_uv(e, n, meta["rot"])
    s = meta["size"] / 2.0
    return s + u / meta["mpp"], s + v / meta["mpp"]