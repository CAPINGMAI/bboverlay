#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""bboverlay A 版 —— 黑匣子 + 眼镜视频，一键出「摇杆 / 姿态 / 卫星小地图」叠加片

用法（最短一行）：
    python bboverlay.py 我的.BBL 眼镜视频.MOV --vstart 174 --dur 30

会自动做：
    1. 解码 BBL（blackbox_decode.exe，结果缓存到 work/）
    2. 用「视频运动量 × 陀螺模长」互相关自动测视频与日志的时间差
    3. 逐帧渲染绿幕 HUD（摇杆 + 3D 姿态 + 高德卫星小地图轨迹）
    4. ffmpeg 编码 → 色度键抠绿 + 顶部渐变压暗 → 成品 mp4
    （同时保留一份纯绿幕 overlay.mp4，方便自己拿去剪映里用）

输出默认目录：E:\\大肥鱼Harness\\02_飞行器项目\\摇杆演示\\
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bbsync
import bbrender
import bbcompose

def _find_tool(name, *defaults):
    """先找程序目录下的 tools/，再找本机固定路径，最后找 PATH"""
    cands = [os.path.join(HERE, "tools", name)] + list(defaults)
    w = shutil.which(name)
    if w:
        cands.append(w)
    for c in cands:
        if c and os.path.exists(c):
            return c
    return defaults[0] if defaults else name


FFMPEG = _find_tool("ffmpeg.exe", r"E:\天问Block\tools\ffmpeg.exe")
DECODER = _find_tool("blackbox_decode.exe",
                     r"C:\Program Files\PIDtoolbox\application\blackbox_decode.exe")
ASSETS = os.path.join(HERE, "assets")
WORK = os.path.join(HERE, "work")
CACHE = os.path.join(HERE, "cache")
DEFAULT_OUT = r"E:\大肥鱼Harness\02_飞行器项目\摇杆演示"
GRAD = os.path.join(ASSETS, "grad.png")
GREEN_HEX = "0x00B140"


# ---------------------------------------------------------------- 基础工具
def log(msg=""):
    print(msg, flush=True)


def run(cmd, **kw):
    p = subprocess.run(cmd, **kw)
    if p.returncode != 0:
        raise RuntimeError("命令失败(%d)：%s" % (p.returncode, " ".join(map(str, cmd))))
    return p


def video_info(path):
    """返回 (时长秒, 宽, 高, 帧率)"""
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", path], capture_output=True)
    s = p.stderr.decode("utf-8", "replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", s)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None
    m = re.search(r"Video:.*?(\d{3,4})x(\d{3,4})", s)
    wh = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    m = re.search(r"([\d.]+)\s*fps", s)
    fps = float(m.group(1)) if m else None
    return dur, wh[0], wh[1], fps


# ---------------------------------------------------------------- 1. 解码
def decode_bbl(bbl):
    """解码 BBL，返回 [(段号, csv路径, gps csv路径)]，已经解过就直接用缓存"""
    import hashlib
    bbl = os.path.abspath(bbl)
    base = os.path.splitext(os.path.basename(bbl))[0]
    # 不同目录下同名 BBL 不能混用缓存，按完整路径加短哈希分开存
    work = os.path.join(WORK, "%s_%s" % (base, hashlib.md5(bbl.encode("utf-8")).hexdigest()[:8]))
    os.makedirs(work, exist_ok=True)

    def found():
        out = []
        for c in sorted(glob.glob(os.path.join(work, base + ".*.csv"))):
            if c.endswith(".gps.csv"):
                continue
            n = re.search(r"\.(\d+)\.csv$", c)
            if not n:
                continue
            gps = c[:-4] + ".gps.csv"
            out.append((int(n.group(1)), c, gps if os.path.exists(gps) else None))
        return out

    cur = found()
    need = (not cur) or max(os.path.getmtime(c) for _, c, _ in cur) < os.path.getmtime(bbl)
    if need:
        # blackbox_decode 把 CSV 写在「输入文件旁边」，所以先把 BBL 放到 work 目录
        # （同盘用硬链接，不占空间；跨盘才复制）
        local = os.path.join(work, os.path.basename(bbl))
        if not os.path.exists(local) or os.path.getmtime(local) != os.path.getmtime(bbl):
            if os.path.exists(local):
                os.remove(local)
            try:
                os.link(bbl, local)
            except OSError:
                shutil.copy2(bbl, local)
        log("解码黑匣子（%s）..." % os.path.basename(bbl))
        t0 = time.time()
        run([DECODER, local], cwd=work)
        cur = found()
        log("  解码完成，%d 段，用时 %.0f s" % (len(cur), time.time() - t0))
    else:
        log("用已解码的缓存（%d 段）" % len(cur))
    if not cur:
        raise RuntimeError("解码后没有找到 CSV，检查一下 BBL 是否完整")
    for i, c, g in cur:
        log("  第 %d 段：%s%s" % (i, os.path.basename(c), "" if g else "（无 GPS CSV）"))
    return cur


def gyro_of(csv):
    """只为测时间差，读 time + gyroUnfilt"""
    import pandas as pd
    cols = bbrender._cols(csv)
    want = [c for c in cols if c.startswith("time") or c.startswith("gyroUnfilt")]
    df = pd.read_csv(csv, skipinitialspace=True, usecols=want, low_memory=False)
    t = df[[c for c in cols if c.startswith("time")][0]].values.astype(float)
    t = (t - t[0]) / 1e6
    g = np.vstack([df["gyroUnfilt[%d]" % i].values.astype(float) for i in range(3)])
    return t, g


# ---------------------------------------------------------------- 2. 测时间差
def measure_lag(video, segs, max_lag, vstart=0.0, dur=30.0):
    """对多段日志逐段做互相关，再挑“对得上、而且时长够用”的那一段"""
    log("测视频与黑匣子的时间差（每段都比一次，几十秒）...")
    t0 = time.time()
    items = []
    durs = {}
    for i, csv, _gps in segs:
        t, g = gyro_of(csv)
        items.append(("第%d段" % i, t, g))
        durs[i] = float(t[-1]) if len(t) else 0.0
    idx, lag, ncc, rows = bbsync.measure(video, items, max_lag=max_lag, log=log)

    # 逐段打印，并算出“这一段能不能盖住你要的那一小段”
    pick = None
    best_ok = None
    for n, r in enumerate(rows):
        segno = segs[n][0]
        span = durs.get(segno, 0.0)
        bb_start = vstart - r["lag"]
        fit = (bb_start >= -0.5) and (bb_start + dur <= span + 0.5)
        log("  %-6s 时长 %5.0f s  lag %+7.2f s  相关 %.3f  次峰 %.3f  %s"
            % (r["name"], span, r["lag"], r["ncc"], r["second"],
               "可用" if fit else "这段盖不住所选时间"))
        if fit and (best_ok is None or r["ncc"] > rows[best_ok]["ncc"]):
            best_ok = n
    if best_ok is not None:
        pick = best_ok
    else:
        pick = idx
        log("  ！没有哪一段能完整盖住 %.0f~%.0f s，先用相关最高的一段" % (vstart, vstart + dur))
    r = rows[pick]
    log("  → 用%s，lag = %+.2f s（视频时间 = 黑匣子时间 %+.2f）用时 %.0f s"
        % (r["name"], r["lag"], r["lag"], time.time() - t0))
    return segs[pick], r["lag"], r["ncc"]


# ---------------------------------------------------------------- 3+4. 渲染合成
def encode_green(frames, out_mp4, fps, n=None, size="16:9", fill_mode=0):
    """把 RGBA 帧压成绿幕底，给剪映抠图用"""
    log("编码绿幕 overlay ...")
    w, h = SIZES.get(size, (1920, 1080))
    fc = "[1:v]format=rgba[ov];[0:v][ov]overlay=0:0:format=auto[g0];"
    fc += _size_filters("g0", "v", size, fill_mode).replace("[v];", "[v]")
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "color=c=%s:s=1920x1080:r=%d" % (GREEN_HEX, fps),
           "-framerate", str(fps), "-i", os.path.join(frames, "f%05d.png"),
           "-filter_complex", fc,
           "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
           "-pix_fmt", "yuv420p"]
    if n:
        cmd += ["-frames:v", str(int(n))]
    cmd.append(out_mp4)
    run(cmd)


# ---------------------------------------------------------------- 缓存
def _key(parts):
    import hashlib
    return hashlib.md5(json.dumps(parts, ensure_ascii=False, sort_keys=True,
                                  default=str).encode("utf-8")).hexdigest()[:12]


def _cache_dir(kind, parts):
    d = os.path.join(CACHE, "%s_%s" % (kind, _key(parts)))
    os.makedirs(d, exist_ok=True)
    return d


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path, obj):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def ensure_layers(csv, gps, bb_start, dur, args, lag, segno, where="auto", log=log,
                  portrait=False):
    """切出 lstick/rstick/att/map 四张透明图层 + 视频帧；有缓存就直接用"""
    want_att = not args.no_att
    want_map = not args.no_map
    parts = [os.path.abspath(csv), round(bb_start, 2), round(dur, 2),
             float(args.stick_mode), bool(args.inv_thr), bool(args.inv_rol),
             bool(args.inv_pit), bool(args.inv_yaw),
             int(args.stick_style), round(float(args.stick_alpha), 3),
             int(args.frame_color), int(args.ball_color), bool(args.show_us),
             round(float(args.map_alpha), 3), int(args.map_shape),
             int(args.map_cam), int(args.map_zoom), int(args.map_up), int(args.map_arrow),
             int(args.map_trail_color), int(args.map_arrow_color),
             int(args.trail_color), round(float(args.trail_len), 2),
             bool(args.tele), bool(args.bars), args.text,
             float(args.tele_x), float(args.tele_y), float(args.bar_x), float(args.bar_y),
             float(args.text_x), float(args.text_y), float(args.text_size),
             int(args.text_anchor), int(args.text_color), int(args.bar_color),
             int(args.tele_color), round(float(args.text_alpha), 3),
             round(float(args.tele_alpha), 3), round(float(args.bar_alpha), 3),
             bool(portrait),
             want_att, want_map,
             args.map_image, args.map_center, args.map_mpp, args.map_rotate]
    d = _cache_dir("layers", parts) if where in (None, "auto") else where
    meta_path = os.path.join(d, "meta.json")
    meta = _read_json(meta_path)
    need = ["lstick_layer.png", "rstick_layer.png", "att_layer.png",
            "map_layer.png", "frame.jpg"]
    if meta and not args.refresh and all(os.path.exists(os.path.join(d, n)) for n in need):
        log("      用缓存的图层（不用再切）")
        return meta
    os.makedirs(d, exist_ok=True)
    log("      切图层中（第一次要几十秒，之后会缓存）...")
    lay = dict(stick_mode=float(args.stick_mode),
               inv_thr=1.0 if args.inv_thr else 0.0, inv_rol=1.0 if args.inv_rol else 0.0,
               inv_pit=1.0 if args.inv_pit else 0.0, inv_yaw=1.0 if args.inv_yaw else 0.0,
               stick_style=float(args.stick_style), stick_alpha=float(args.stick_alpha),
               frame_i=float(args.frame_color), ball_i=float(args.ball_color),
               show_us=1.0 if args.show_us else 0.0,
               map_alpha=float(args.map_alpha), map_shape=float(args.map_shape),
               tele_on=1.0 if args.tele else 0.0, tele_x=float(args.tele_x),
               tele_y=float(args.tele_y), tele_size=float(args.tele_size),
               tele_i=float(args.frame_color if args.tele_color < 0 else args.tele_color),
               tele_alpha=float(args.tele_alpha),
               bar_on=1.0 if args.bars else 0.0, bar_x=float(args.bar_x),
               bar_y=float(args.bar_y),
               bar_i=float(args.frame_color if args.bar_color < 0 else args.bar_color),
               bar_alpha=float(args.bar_alpha),
               trail_i=float(args.trail_color), trail_len=float(args.trail_len),
               map_trail_i=float(args.map_trail_color),
               map_arrow_i=float(args.map_arrow_color),
               map_up=float(args.map_up), map_arrow=1.0 if args.map_arrow else 0.0,
               map_cam=float(args.map_cam), map_zoom=float(args.map_zoom),
               text_on=1.0 if args.text else 0.0, text_x=float(args.text_x),
               text_y=float(args.text_y), text_size=float(args.text_size),
               text_i=float(args.frame_color if args.text_color < 0 else args.text_color),
               text_alpha=float(args.text_alpha),
               text_anchor=float(args.text_anchor))
    info = bbrender.render_layers(csv, gps, bb_start, dur, d, want_att=want_att,
                                 want_map=want_map, log=log,
                                 map_image=args.map_image, map_center=args.map_center,
                                 map_mpp=args.map_mpp, map_rotate=args.map_rotate,
                                 layout=lay, text=args.text, portrait=portrait)
    # 铺上通道反向后的结果已经在图层里（render_layers 用的是默认版式，反向要重画）
    vt = args.vstart + info["k"] / float(bbrender.FPS)
    frame_jpg = os.path.join(d, "frame.jpg")
    grab_frame(args.video, vt, frame_jpg)
    meta = dict(lstick=info["lstick"], rstick=info["rstick"], att=info["att"],
                map=info["map"], extra=info.get("extra"), tele=info.get("tele"),
                bars=info.get("bars"), text=info.get("text"), frame=frame_jpg,
                stick_mode=info["stick_mode"], size=list(info.get("size") or (1920, 1080)),
                k=info["k"], n=info["n"], bb_start=bb_start, dur=dur, lag=lag, seg=segno)
    _write_json(meta_path, meta)
    return meta



SIZES = {"16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350), "9:16": (1080, 1920)}


def _size_filters(tag_in, tag_out, size_key, fill_mode):
    """输出画幅：0=补黑边(完整画面) 1=裁切(填满)"""
    w, h = SIZES.get(size_key, (1920, 1080))
    if (w, h) == (1920, 1080):
        return "[%s]null[%s];" % (tag_in, tag_out)
    if int(fill_mode) == 1:
        return ("[%s]scale=%d:%d:force_original_aspect_ratio=increase,"
                "crop=%d:%d[%s];" % (tag_in, w, h, w, h, tag_out))
    return ("[%s]scale=%d:%d:force_original_aspect_ratio=decrease,"
            "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black[%s];" % (tag_in, w, h, w, h, tag_out))




def _corner_overlay(size_key):
    """生成四角圆角遮罩 PNG（黑角），返回路径"""
    from PIL import Image as _I, ImageDraw as _D
    w, h = SIZES.get(size_key, (1920, 1080))
    p = os.path.join(CACHE, "corners_%dx%d.png" % (w, h))
    if not os.path.exists(p):
        os.makedirs(CACHE, exist_ok=True)
        im = _I.new("RGBA", (w, h), (0, 0, 0, 0))
        d = _D.Draw(im)
        r = int(min(w, h) * 0.055)
        d.polygon([(0, 0), (r, 0), (0, r)], fill=(0, 0, 0, 255))
        d.polygon([(w - 1, 0), (w - 1 - r, 0), (w - 1, r)], fill=(0, 0, 0, 255))
        d.polygon([(0, h - 1), (r, h - 1), (0, h - 1 - r)], fill=(0, 0, 0, 255))
        d.polygon([(w - 1, h - 1), (w - 1 - r, h - 1), (w - 1, h - 1 - r)], fill=(0, 0, 0, 255))
        im.save(p)
    return p


def composite(video, frames, out_mp4, vstart, dur, fps, crf, with_audio=True,
              grad=False, n=None, size="16:9", fill_mode=0, vign=0.0, corner=0.0,
              portrait=False, hud_pos="bottom", native_portrait=False):
    """把 RGBA 的 HUD 帧叠到视频上（真透明）。

    portrait=True 且 size=9:16 时：视频铺满竖屏，HUD 等比缩小后压在下/上/中间，
    这样摇杆不会被裁掉。
    """
    log("合成成品%s ..." % ("（含顶部渐变）" if grad else ""))
    w, h = SIZES.get(size, (1920, 1080))
    is_portrait = (bool(portrait) or bool(native_portrait)) and size == "9:16"
    fc = "[0:v]fps=%d,setsar=1" % fps
    if is_portrait:
        fc += ",scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d[bg];" % (w, h, w, h)
        if grad:
            fc += "[2:v]scale=%d:%d[gd];[bg][gd]overlay=0:0[bg2];" % (w, h)
            bg = "bg2"
        else:
            bg = "bg"
        if native_portrait:
            fc += "[1:v]format=rgba[hs];[%s][hs]overlay=0:0[o1];" % bg
        else:
            hud_h = int(round(w * 1080.0 / 1920.0))
            pos = (hud_pos or "bottom").lower()
            y = 40 if pos == "top" else ((h - hud_h) // 2 if pos == "center" else h - hud_h - 40)
            fc += "[1:v]format=rgba,scale=%d:%d[hs];[%s][hs]overlay=(W-w)/2:%d[o1];" % (
                w, hud_h, bg, y)
        last = "o1"
    else:
        fc += ",scale=1920:1080[v0];[1:v]format=rgba[ov];"
        if grad:
            fc += "[v0][2:v]overlay=0:0[t];[t][ov]overlay=0:0[o1];"
        else:
            fc += "[v0][ov]overlay=0:0[o1];"
        last = "o1"
    if float(vign) > 0.05:
        fc += "[%s]vignette=angle=PI/%.1f[vg];" % (last, max(3.0, 10.0 / max(0.1, float(vign))))
        last = "vg"
    if not is_portrait:
        fc += _size_filters(last, "sz", size, fill_mode)
        last = "sz"
    idx = 2 if grad else 1
    corner_png = None
    if float(corner) > 0.5:
        corner_png = _corner_overlay(size)
        fc += "[%d:v]format=rgba[cn];[%s][cn]overlay=0:0[v]" % (idx + 1, last)
    else:
        fc += "[%s]null[v]" % last

    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
           "-ss", "%.3f" % vstart, "-t", "%.3f" % dur, "-i", video,
           "-framerate", str(fps), "-i", os.path.join(frames, "f%05d.png")]
    if grad:
        cmd += ["-i", GRAD]
    if corner_png:
        cmd += ["-i", corner_png]
    cmd += ["-filter_complex", fc, "-map", "[v]"]
    if with_audio:
        cmd += ["-map", "0:a?", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-t", "%.3f" % dur]
    if n:
        cmd += ["-frames:v", str(int(n))]
    cmd.append(out_mp4)
    run(cmd)


def composite_still(video, hud_png, out_jpg, vtime, fps=None, grad=False,
                    size="16:9", fill_mode=0, portrait=False, hud_pos="bottom",
                    native_portrait=False):
    """把单帧 RGBA HUD 叠到视频对应时刻上，出 JPG（预览用）"""
    f = fps or bbrender.FPS
    w, h = SIZES.get(size, (1920, 1080))
    is_portrait = (bool(portrait) or bool(native_portrait)) and size == "9:16"
    if is_portrait and native_portrait:
        fc = ("[0:v]fps=%d,scale=%d:%d:force_original_aspect_ratio=increase,"
              "crop=%d:%d[bg];" % (f, w, h, w, h))
        if grad:
            fc += "[2:v]scale=%d:%d[gd];[bg][gd]overlay=0:0[b2];" % (w, h)
            bg = "b2"
        else:
            bg = "bg"
        fc += "[1:v]format=rgba[hs];[%s][hs]overlay=0:0[v]" % bg
    elif is_portrait:
        fc = ("[0:v]fps=%d,scale=%d:%d:force_original_aspect_ratio=increase,"
              "crop=%d:%d[bg];" % (f, w, h, w, h))
        if grad:
            fc += "[2:v]scale=%d:%d[gd];[bg][gd]overlay=0:0[b2];" % (w, h)
            bg = "b2"
        else:
            bg = "bg"
        hud_h = int(round(w * 1080.0 / 1920.0))
        pos = (hud_pos or "bottom").lower()
        y = 40 if pos == "top" else ((h - hud_h) // 2 if pos == "center" else h - hud_h - 40)
        fc += "[1:v]format=rgba,scale=%d:%d[hs];[%s][hs]overlay=(W-w)/2:%d[v]" % (w, hud_h, bg, y)
    else:
        fc = "[0:v]fps=%d,scale=1920:1080,setsar=1[v0];[1:v]format=rgba[ov];" % f
        if grad:
            fc += "[v0][2:v]overlay=0:0[t];[t][ov]overlay=0:0[o1];"
            base = "o1"
        else:
            fc += "[v0][ov]overlay=0:0[o1];"
            base = "o1"
        if size != "16:9":
            fc += _size_filters(base, "v", size, fill_mode)
        else:
            fc += "[%s]null[v]" % base
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
           "-ss", "%.3f" % vtime, "-i", video, "-i", hud_png, "-frames:v", "1"]
    if grad:
        cmd += ["-i", GRAD]
    cmd += ["-filter_complex", fc, "-map", "[v]", "-q:v", "2", out_jpg]
    run(cmd)


def grab_frame(video, vtime, out_jpg):
    """从视频里抓一帧当背景板（拖拽版式编辑器用）"""
    run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
         "-ss", "%.3f" % vtime, "-i", video, "-frames:v", "1",
         "-vf", "scale=1920:1080,setsar=1", "-q:v", "2", out_jpg])


def selftest():
    """自检：给「新电脑配置程序」用，逐项报 OK / 缺失"""
    import platform
    ok = True
    log("Python %s  (%s)" % (platform.python_version(), sys.executable))
    for name, imp in (("pillow", "from PIL import Image"), ("numpy", "import numpy"),
                      ("pandas", "import pandas"), ("tkinter", "import tkinter")):
        try:
            exec(imp, {})
            log("  [OK]   %s" % name)
        except Exception as e:
            ok = False
            log("  [缺失] %s —— %s" % (name, e))
    for label, path in (("ffmpeg", FFMPEG), ("黑匣子解码器", DECODER)):
        if path and os.path.exists(path):
            log("  [OK]   %s：%s" % (label, path))
        else:
            ok = False
            log("  [缺失] %s：找不到（%s）" % (label, path))
    if os.path.exists(GRAD):
        log("  [OK]   渐变压暗图 assets/grad.png")
    else:
        log("  [缺失] assets/grad.png")
        ok = False
    # 版式算法自检（竖屏预设 / 图层基准 / 预设不覆盖用户拖动）
    try:
        import bbrender as BR
        chk = []
        P = BR.portrait_layout(dict(BR.LAYOUT))
        chk.append(("竖屏预设摇杆在 270/810",
                    abs(BR.L_CENTER[0] + P["ls_dx"] - 270) < 0.5
                    and abs(BR.R_CENTER[0] + P["rs_dx"] - 810) < 0.5))
        chk.append(("竖屏预设地图在 18,18", abs(P["map_dx"] - 18) < 0.5))
        U = dict(BR.LAYOUT, ls_dx=123.0, map_dx=88.0)
        P2 = BR.portrait_layout(U)
        chk.append(("拖过的位置不被竖屏预设覆盖",
                    abs(P2["ls_dx"] - 123.0) < 0.5 and abs(P2["map_dx"] - 88.0) < 0.5))
        L0 = BR.layer_layout(dict(ls_dx=-300.0, map_dx=500.0), portrait=False)
        chk.append(("切图层用基准位置（dx=0）",
                    abs(L0["ls_dx"]) < 1e-6 and abs(L0["map_dx"] - BR.MAPPOS[0]) < 1e-6))
        L1 = BR.layer_layout(None, portrait=True)
        chk.append(("竖屏图层按预设位置烘（摇杆 270）",
                    abs(BR.L_CENTER[0] + L1["ls_dx"] - 270) < 0.5))
        for name, good in chk:
            log(("  [OK]   " if good else "  [失败] ") + name)
            ok = ok and good
    except Exception as e:
        ok = False
        log("  [失败] 版式算法自检：%s" % e)
    log("")
    log("自检结果：%s" % ("全部通过，可以用了" if ok else "有缺失项，见上面"))
    print(json.dumps({"selftest": ok}, ensure_ascii=False))
    return 0 if ok else 1


def _join_arg_values(argv):
    """--mask -50,110,700,60 这种“值以负号开头”的写法会被 argparse 当成选项，
    这里预先并成 --mask=-50,... 的形式"""
    need = {"--mask", "--mask2", "--map-center"}
    out, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a in need and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            out.append(a + "=" + argv[i + 1])
            i += 2
            continue
        out.append(a)
        i += 1
    return out


def data_check(bbl, argv_video=None):
    """检查黑匣子每一段的数据质量，打印出来"""
    import numpy as np
    segs = decode_bbl(bbl)
    log("=== 黑匣子数据体检：%s ===" % os.path.basename(bbl))
    for i, csv, gps in segs:
        try:
            import pandas as pd
            cols = bbrender._cols(csv)
            tcol = next(c for c in cols if c.startswith("time"))
            df = pd.read_csv(csv, skipinitialspace=True, low_memory=False)
            t = df[tcol].values.astype(float) / 1e6
            dt = np.diff(t)
            gaps = int((dt > 0.05).sum())
            samp = len(t)
            rate = samp / max(1e-6, (t[-1] - t[0]))
            log("第%d段：%s" % (i, os.path.basename(csv)))
            log("   时长 %.1f s｜样本 %d｜平均 %.0f Hz｜断点(>50ms) %d 处" % (
                t[-1] - t[0], samp, rate, gaps))
            for name, col in (("rcCommand[0]", "rcCommand[0]"),
                              ("gyroUnfilt[0]", "gyroUnfilt[0]"),
                              ("accSmooth[0]", "accSmooth[0]"),
                              ("vbatLatest (V)", "vbatLatest (V)")):
                if col in df.columns:
                    v = df[col].values.astype(float)
                    nan = int(np.isnan(v).sum())
                    log("   %-16s 范围 %8.1f ~ %8.1f   NaN %d" % (name, np.nanmin(v), np.nanmax(v), nan))
                else:
                    log("   %-16s 缺失（这一列没有记录）" % name)
            if gps and os.path.exists(gps):
                g = pd.read_csv(gps, skipinitialspace=True, low_memory=False)
                have = [c for c in g.columns if "course" in c.lower() or "speed" in c.lower()]
                log("   GPS 文件：%s（%d 行）｜航向/速度列：%s" % (
                    os.path.basename(gps), len(g), ", ".join(have) or "无"))
                if "GPS_speed (m/s)" in g.columns:
                    sp = g["GPS_speed (m/s)"].values.astype(float)
                    log("   GPS 速度：中位 %.0f cm/s｜最大 %.0f cm/s｜零值占比 %.0f%%" % (
                        np.median(sp), np.max(sp), 100.0 * (sp < 1).mean()))
            else:
                log("   ！没有 GPS CSV（这段日志没记录 GPS，小地图/航向用不了）")
        except Exception as e:
            log("第%d段读不了：%s" % (i, e))
    log("=== 体检结束 ===")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="黑匣子 + 眼镜视频 → 摇杆/姿态/卫星地图叠加成片（A 版命令行）")
    ap.add_argument("bbl", nargs="?", help="黑匣子文件 .bbl / .bfl")
    ap.add_argument("video", nargs="?", help="眼镜视频（DJI 的 .MOV / .mp4 都行）")
    ap.add_argument("--vstart", "--start", dest="vstart", type=float, default=0.0,
                    help="从视频第几秒开始（默认 0）")
    ap.add_argument("--dur", type=float, default=30.0, help="做多长（秒，默认 30）")
    ap.add_argument("--lag", type=float, default=None,
                    help="手动指定时间差（视频=黑匣子+lag），不给就自动测")
    ap.add_argument("--seg", type=int, default=None, help="强制用第几段日志（1 起）")
    ap.add_argument("--csv", default=None, help="直接用已解码的主 CSV（跳过解码）")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出目录")
    ap.add_argument("--jobs", type=int, default=None, help="并行进程数（默认 CPU-2）")
    ap.add_argument("--no-map", action="store_true", help="不画卫星小地图")
    ap.add_argument("--no-att", action="store_true", help="不画 3D 姿态模型")
    ap.add_argument("--map-image", default=None,
                    help="用自己航拍的正射图/正俯视照片当小地图底图（跳过在线卫星图）")
    ap.add_argument("--map-center", default=None, help="自定义底图中心经纬度 lat,lon（默认取轨迹中心）")
    ap.add_argument("--map-mpp", type=float, default=None, help="自定义底图分辨率 米/像素（默认从 EXIF 算）")
    ap.add_argument("--map-rotate", type=float, default=None, help="自定义底图旋转角，0=图上方朝北（默认读 EXIF 机头朝向）")
    ap.add_argument("--hud-x", type=float, default=None, help="两根摇杆一起左右移动（兼容老参数）")
    ap.add_argument("--hud-y", type=float, default=None, help="两根摇杆一起上下移动（兼容老参数）")
    ap.add_argument("--hud-scale", type=float, default=None, help="两根摇杆一起缩放（兼容老参数）")
    ap.add_argument("--lstick-x", type=float, default=None, help="左摇杆左右移动（像素，正=右）")
    ap.add_argument("--lstick-y", type=float, default=None, help="左摇杆上下移动（像素，正=下）")
    ap.add_argument("--lstick-scale", type=float, default=None, help="左摇杆缩放（1.0=原大）")
    ap.add_argument("--rstick-x", type=float, default=None, help="右摇杆左右移动（像素，正=右）")
    ap.add_argument("--rstick-y", type=float, default=None, help="右摇杆上下移动（像素，正=下）")
    ap.add_argument("--rstick-scale", type=float, default=None, help="右摇杆缩放（1.0=原大）")
    ap.add_argument("--stick-mode", type=int, default=2, choices=[1, 2],
                    help="1=日本手(MODE1)  2=美国手(MODE2，默认)")
    ap.add_argument("--att-x", type=float, default=0.0, help="3D 姿态左右移动（像素，正=右）")
    ap.add_argument("--att-y", type=float, default=0.0, help="3D 姿态上下移动（像素，正=下）")
    ap.add_argument("--att-scale", type=float, default=1.0, help="3D 姿态缩放（1.0=原大）")
    ap.add_argument("--map-x", type=float, default=26.0, help="小地图左边距（像素，默认 26）")
    ap.add_argument("--map-y", type=float, default=20.0, help="小地图上边距（像素，默认 20）")
    ap.add_argument("--map-scale", type=float, default=1.0, help="小地图缩放（1.0=360 像素）")
    ap.add_argument("--mask", default=None,
                    help="第 1 块 GPS 坐标遮盖：x,y,w,h（像素，例 0,110,1920,90）；不给则不画")
    ap.add_argument("--mask2", default=None,
                    help="第 2 块 GPS 坐标遮盖：x,y,w,h（不给则不画）")
    ap.add_argument("--no-mask", action="store_true", help="两块 GPS 坐标遮盖都不画")
    ap.add_argument("--crf", type=int, default=21, help="成品画质，越小越清晰（默认 21）")
    ap.add_argument("--grad", action="store_true",
                    help="给画面上方加一层渐变压暗（默认不加，加了会把顶部画面压暗）")
    ap.add_argument("--preview", action="store_true", help="只渲染一帧预览图，看版式")
    ap.add_argument("--inv-thr", action="store_true", help="油门通道反向")
    ap.add_argument("--inv-rol", action="store_true", help="横滚通道反向")
    ap.add_argument("--inv-pit", action="store_true", help="俯仰（升降）通道反向")
    ap.add_argument("--inv-yaw", action="store_true", help="方向（偏航）通道反向")
    ap.add_argument("--stick-style", type=int, default=0,
                    help="摇杆样式 0=经典圆盘 1=圆角方框 2=极简圆 3=极简方框")
    ap.add_argument("--stick-alpha", type=float, default=1.0, help="摇杆透明度 0.05~1")
    ap.add_argument("--frame-color", type=int, default=0, help="框线/文字颜色编号")
    ap.add_argument("--ball-color", type=int, default=0, help="摇杆点颜色编号")
    ap.add_argument("--tele-color", type=int, default=-1,
                    help="数值面板文字颜色编号（-1=跟 --frame-color）")
    ap.add_argument("--bar-color", type=int, default=-1,
                    help="柱状图颜色编号（-1=跟 --frame-color）")
    ap.add_argument("--text-color", type=int, default=-1,
                    help="水印文字颜色编号（-1=跟 --frame-color）")
    ap.add_argument("--show-us", action="store_true", help="摇杆旁边显示 us 数值")
    ap.add_argument("--map-alpha", type=float, default=1.0, help="小地图透明度")
    ap.add_argument("--map-shape", type=int, default=0, help="小地图形状 0=矩形 1=圆角 2=椭圆")
    ap.add_argument("--mask-shape", type=int, default=0, help="GPS 遮盖块形状 0=矩形 1=圆角 2=椭圆")
    ap.add_argument("--mask-alpha", type=float, default=1.0, help="GPS 遮盖块透明度（1=全黑不透明）")
    # ---- 附加效果 ----
    ap.add_argument("--trail-len", type=float, default=6, help="摇杆轨迹长度（帧数）")
    ap.add_argument("--trail-color", type=int, default=4, help="轨迹颜色编号")
    ap.add_argument("--trail-w", type=float, default=1.0, help="轨迹粗细倍数")
    ap.add_argument("--tele", action="store_true", help="显示数值面板（油门/电压/电流/速度/高度/卫星）")
    ap.add_argument("--tele-x", type=float, default=60, help="数值面板 X")
    ap.add_argument("--tele-y", type=float, default=380, help="数值面板 Y")
    ap.add_argument("--tele-size", type=float, default=30, help="数值面板字号")
    ap.add_argument("--bars", action="store_true", help="显示油门/电压条形图")
    ap.add_argument("--bar-x", type=float, default=60, help="条形图 X")
    ap.add_argument("--bar-y", type=float, default=760, help="条形图 Y")
    ap.add_argument("--text", default="", help="屏幕上的自定义文字（水印/机主名/日期）")
    ap.add_argument("--text-x", type=float, default=960, help="文字 X")
    ap.add_argument("--text-y", type=float, default=60, help="文字 Y")
    ap.add_argument("--text-size", type=float, default=44, help="文字字号")
    ap.add_argument("--text-alpha", type=float, default=0.9, help="文字透明度")
    ap.add_argument("--tele-alpha", type=float, default=0.9, help="数值面板透明度")
    ap.add_argument("--bar-alpha", type=float, default=0.9, help="柱状图透明度")
    ap.add_argument("--text-anchor", type=int, default=0,
                    help="文字锚点 0=左上 1=中上 2=右上 3=左中 4=居中 5=右中 6=左下 7=中下 8=右下")
    ap.add_argument("--map-trail-color", type=int, default=5, help="小地图轨迹颜色编号")
    ap.add_argument("--map-arrow-color", type=int, default=3, help="小地图方向箭头颜色编号")
    ap.add_argument("--map-trail-w", type=float, default=1.0, help="小地图轨迹粗细")
    ap.add_argument("--map-ruler", action="store_true", help="小地图显示比例尺")
    ap.add_argument("--map-vec", action="store_true", help="小地图显示速度矢量")
    ap.add_argument("--map-up", type=int, default=0, choices=[0, 1],
                    help="小地图朝向 0=正北朝上 1=航向朝上")
    ap.add_argument("--map-cam", type=int, default=1, choices=[1, 2, 3],
                    help="小地图视角 1=起点居中 2=整条轨迹居中 3=位置居中(跟随)")
    ap.add_argument("--inv-att-pit", type=int, default=1, choices=[0, 1],
                    help="3D 模型俯仰反向（默认 1：拉杆=抬头）")
    ap.add_argument("--inv-att-rol", type=int, default=0, choices=[0, 1],
                    help="3D 模型滚转反向")
    for _nm, _hlp in (("vbat", "电压"), ("amp", "电流"), ("alt", "高度"), ("spd", "速度")):
        ap.add_argument("--%s-k" % _nm, type=float, default=1.0, help="%s 倍率" % _hlp)
        ap.add_argument("--%s-b" % _nm, type=float, default=0.0, help="%s 偏移" % _hlp)
    ap.add_argument("--map-zoom", type=int, default=1, choices=[0, 1],
                    help="小地图缩放 0=固定 1=自动（起点居中时快超出就自动缩小）")
    ap.add_argument("--map-arrow", action="store_true", help="小地图显示飞行方向箭头")
    ap.add_argument("--map-wp", action="store_true", help="小地图标出航点")
    ap.add_argument("--event", action="store_true", help="显示解锁/上锁标记")
    ap.add_argument("--att-mode", type=int, default=0, choices=[0, 1],
                    help="3D 姿态来源 1=加速度计+陀螺(稳，推荐) 0=纯陀螺积分")
    ap.add_argument("--att-yaw", type=float, default=0.0,
                    help="机头方向偏置（度）：板子装歪时填 90/180/270")
    for _k, _n in (("tele", "数值面板"), ("bar", "柱状图"), ("text", "文字")):
        ap.add_argument("--%s-dx" % _k, type=float, default=0.0, help=_n + " X 偏移")
        ap.add_argument("--%s-dy" % _k, type=float, default=0.0, help=_n + " Y 偏移")
        ap.add_argument("--%s-scale" % _k, type=float, default=1.0, help=_n + " 缩放")
    ap.add_argument("--horizon", action="store_true", help="3D 姿态画人工地平线（分清正飞/倒飞）")
    ap.add_argument("--extra-dx", type=float, default=0.0, help="面板/柱状图/文字 整体 X 偏移")
    ap.add_argument("--extra-dy", type=float, default=0.0, help="面板/柱状图/文字 整体 Y 偏移")
    ap.add_argument("--obj", default="", help="用自己的 OBJ 模型代替内置方块飞机")
    ap.add_argument("--vignette", type=float, default=0.0, help="暗角强度 0~1")
    ap.add_argument("--corner", action="store_true", help="四角做圆角")
    ap.add_argument("--size", default="16:9", choices=["16:9", "1:1", "4:5", "9:16"],
                    help="输出画幅")
    ap.add_argument("--fill", type=int, default=0, help="画幅填充 0=补黑边 1=裁切填满")
    ap.add_argument("--portrait", action="store_true",
                    help="竖屏排版：视频铺满 9:16，HUD 缩小压在底部（摇杆不会被裁）")
    ap.add_argument("--portrait-mode", default="native", choices=["native", "band"],
                    help="竖屏方式：native=原生竖屏排版（推荐） band=整块 HUD 缩小压底部")
    ap.add_argument("--hud-pos", default="bottom", choices=["bottom", "center", "top"],
                    help="竖屏时 HUD 放哪：bottom/center/top")
    ap.add_argument("--refresh", action="store_true", help="不用缓存，重新切图层")
    ap.add_argument("--layers", nargs="?", const="auto", default=None,
                    help="切出各图层（默认用自动缓存目录；也可以给目录）")
    ap.add_argument("--check", action="store_true",
                    help="体检黑匣子数据（样本数/断点/有没有 GPS 航向、速度）")
    ap.add_argument("--selftest", action="store_true",
                    help="自检：检查 Python 库、ffmpeg、黑匣子解码器、tkinter")
    ap.add_argument("--keep-frames", action="store_true", help="保留中间帧 PNG")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.bbl or (not args.video and not getattr(args, "check", False)):
        log("用法：bboverlay.py 日志.BBL 视频.MOV --vstart 174 --dur 30")
        return 2

    if getattr(args, "check", False) and args.bbl and not args.video:
        data_check(os.path.abspath(args.bbl))
        return 0

    t_all = time.time()
    log("bboverlay v%s（命令行）" % bbrender.VERSION)
    bbl = os.path.abspath(args.bbl)
    video = os.path.abspath(args.video)
    for p in (bbl, video):
        if not os.path.exists(p):
            log("找不到文件：%s" % p)
            return 2
    if not os.path.exists(FFMPEG):
        log("找不到 ffmpeg：%s" % FFMPEG)
        return 2

    vdur, vw, vh, vfps = video_info(video)
    log("视频 %s  %.1f s  %sx%s  %s fps" % (os.path.basename(video), vdur or 0, vw, vh, vfps))
    if args.vstart < 0:
        args.vstart = 0.0
    if vdur and args.vstart >= vdur - 0.5:
        log("起始时间超出视频长度（%.1f s）" % vdur)
        return 2
    dur = args.dur
    if vdur and args.vstart + dur > vdur:
        dur = max(1.0, vdur - args.vstart)
        log("时长超出视频，自动截到 %.1f s" % dur)

    if getattr(args, "check", False):
        if not args.bbl:
            log("用法：bboverlay.py 日志.BBL --check")
            return 2
        data_check(os.path.abspath(args.bbl))
        return 0

    # 1. 段 + 时间差
    if args.csv:
        csv = os.path.abspath(args.csv)
        gps = csv[:-4] + ".gps.csv"
        segs = [(args.seg or 1, csv, gps if os.path.exists(gps) else None)]
    else:
        segs = decode_bbl(bbl)
    if args.seg:
        segs = [s for s in segs if s[0] == args.seg] or segs

    if args.lag is None:
        seg, lag, ncc = measure_lag(video, segs, max_lag=min(60.0, (vdur or 60) + 10),
                                    vstart=args.vstart, dur=dur)
    else:
        seg, lag, ncc = segs[0], args.lag, float("nan")
        log("用指定的 lag %+.2f s" % lag)
    segno, csv, gps = seg

    bb_start = args.vstart - lag
    log("视频 %.1f~%.1f s  ↔  黑匣子第%d段 %.1f~%.1f s"
        % (args.vstart, args.vstart + dur, segno, bb_start, bb_start + dur))
    if bb_start < 0:
        log("提示：起点早于日志开头 %.1f s，前面空的部分会被裁掉或取日志首帧" % (-bb_start))
        cut = -bb_start
        dur -= cut
        bb_start = 0.0
        args.vstart += cut
        if dur <= 1.0:
            log("可用时长太短，换个 vstart 试试")
            return 2

    # 2. 版式 + 图层缓存
    portrait_mode = bool(args.portrait) and args.size == "9:16" and args.portrait_mode == "native"
    layout = dict(stick_style=float(args.stick_style),
                  stick_alpha=float(args.stick_alpha),
                  frame_i=float(args.frame_color), ball_i=float(args.ball_color),
                  show_us=1.0 if args.show_us else 0.0,
                  map_alpha=float(args.map_alpha), map_shape=float(args.map_shape),
                  mask_shape=float(args.mask_shape), mask_alpha=float(args.mask_alpha),
                  mask2_shape=float(args.mask_shape), mask2_alpha=float(args.mask_alpha),
                  trail_len=float(args.trail_len), trail_i=float(args.trail_color),
                  trail_w=float(args.trail_w),
                  tele_on=1.0 if args.tele else 0.0, tele_x=float(args.tele_x),
                  tele_y=float(args.tele_y), tele_size=float(args.tele_size),
                  tele_i=float(args.frame_color if args.tele_color < 0 else args.tele_color),
                  bar_on=1.0 if args.bars else 0.0, bar_x=float(args.bar_x),
                  bar_y=float(args.bar_y),
                  bar_i=float(args.frame_color if args.bar_color < 0 else args.bar_color),
                  text_on=1.0 if args.text else 0.0, text_x=float(args.text_x),
                  text_y=float(args.text_y), text_size=float(args.text_size),
                  text_i=float(args.frame_color if args.text_color < 0 else args.text_color),
                  text_alpha=float(args.text_alpha),
                  tele_alpha=float(args.tele_alpha), bar_alpha=float(args.bar_alpha),
                  text_anchor=float(args.text_anchor),
                  map_trail_i=float(args.map_trail_color), map_trail_w=float(args.map_trail_w),
                  map_arrow_i=float(args.map_arrow_color),
                  map_scale_on=1.0 if args.map_ruler else 0.0,
                  map_vec_on=1.0 if args.map_vec else 0.0,
                  map_wp_on=1.0 if args.map_wp else 0.0,
                  map_up=float(args.map_up), map_cam=float(args.map_cam),
                  map_zoom=float(args.map_zoom),
                  tele_dx=args.tele_dx, tele_dy=args.tele_dy, tele_s=args.tele_scale,
                  bar_dx=args.bar_dx, bar_dy=args.bar_dy, bar_s=args.bar_scale,
                  text_dx=args.text_dx, text_dy=args.text_dy, text_s=args.text_scale,
                  vbat_k=args.vbat_k, vbat_b=args.vbat_b,
                  amp_k=args.amp_k, amp_b=args.amp_b,
                  alt_k=args.alt_k, alt_b=args.alt_b,
                  spd_k=args.spd_k, spd_b=args.spd_b,
                  att_inv_pit=float(args.inv_att_pit), att_inv_rol=float(args.inv_att_rol),
                  map_arrow=1.0 if args.map_arrow else 0.0,
                  event_on=1.0 if args.event else 0.0,
                  extra_dx=float(args.extra_dx), extra_dy=float(args.extra_dy),
                  horizon=1.0 if args.horizon else 0.0,
                  att_mode=float(args.att_mode), att_yaw=float(args.att_yaw),
                  vign=float(args.vignette), corner=1.0 if args.corner else 0.0,
                  aspect=0.0, fill_mode=float(args.fill),
                  att_dx=args.att_x, att_dy=args.att_y, att_s=args.att_scale,
                  map_dx=args.map_x, map_dy=args.map_y, map_s=args.map_scale,
                  stick_mode=float(args.stick_mode),
                  inv_thr=1.0 if args.inv_thr else 0.0, inv_rol=1.0 if args.inv_rol else 0.0,
                  inv_pit=1.0 if args.inv_pit else 0.0, inv_yaw=1.0 if args.inv_yaw else 0.0)
    # 老参数 --hud-*：同时作用到左右两根；--lstick-*/--rstick-* 优先
    for key, val in (("dx", args.hud_x), ("dy", args.hud_y), ("s", args.hud_scale)):
        if val is not None:
            layout["ls_" + key] = val
            layout["rs_" + key] = val
    for key, val in (("dx", args.lstick_x), ("dy", args.lstick_y), ("s", args.lstick_scale)):
        if val is not None:
            layout["ls_" + key] = val
    for key, val in (("dx", args.rstick_x), ("dy", args.rstick_y), ("s", args.rstick_scale)):
        if val is not None:
            layout["rs_" + key] = val
    for suffix, spec in (("", args.mask), ("2", args.mask2)):
        if spec and not args.no_mask:
            try:
                mx, my, mw, mh = [float(v) for v in spec.split(",")[:4]]
                pre = "mask" + suffix
                layout.update({pre + "_on": 1.0, pre + "_x": mx, pre + "_y": my,
                               pre + "_w": mw, pre + "_h": mh})
            except ValueError:
                log("--mask%s 格式不对，应该是 x,y,w,h" % suffix)

    mask_on = bool(args.mask) and not args.no_mask
    mask2_on = bool(args.mask2) and not args.no_mask

    # 「元素位置」：切图层（有缓存就直接用）
    if args.layers is not None:
        meta = ensure_layers(csv, gps, bb_start, dur, args, lag, segno,
                             where=args.layers, log=log, portrait=portrait_mode)
        print(json.dumps(dict(lstick=meta["lstick"], rstick=meta["rstick"],
                              att=meta["att"], map=meta["map"],
                              extra=meta.get("extra"), tele=meta.get("tele"),
                              bars=meta.get("bars"), text=meta.get("text"),
                              frame=meta["frame"], size=meta.get("size") or [1920, 1080],
                              stick_mode=meta.get("stick_mode", args.stick_mode),
                              vstart=args.vstart, dur=dur, bb_start=bb_start, seg=segno),
                         ensure_ascii=False))
        return 0

    os.makedirs(args.out, exist_ok=True)
    stem = os.path.splitext(os.path.basename(video))[0]
    tag = "%s_%gs-%gs" % (stem, args.vstart, args.vstart + dur)
    if portrait_mode:
        tag += "_竖屏"          # 横竖两版别互相覆盖输出文件


    # 「预览一帧」：有附加效果（面板/柱状图/文字/事件）时直接渲染一帧，保证所见即所得
    advanced = bool(args.tele or args.bars or args.text or args.event
                    or args.vignette > 0.05 or args.corner
                    or args.map_up or args.map_arrow
                    or portrait_mode
                    or int(args.map_cam) != 1 or int(args.map_zoom) != 1)
    if args.preview and advanced:
        tag2 = tag
        frames = os.path.join(CACHE, "pv_" + re.sub(r"[^\w.-]", "_", tag2))
        if os.path.exists(frames):
            shutil.rmtree(frames)
        npz, map_png, n = bbrender.prepare(csv, gps, bb_start, dur, frames,
                                          want_att=not args.no_att,
                                          want_map=not args.no_map, log=log,
                                          map_image=args.map_image,
                                          map_center=args.map_center,
                                          map_mpp=args.map_mpp,
                                          map_rotate=args.map_rotate,
                                          layout=layout, alpha=True, text=args.text,
                                          obj=args.obj, portrait=portrait_mode)
        k = min(max(0, n - 1), int(n // 2))
        bbrender._init_worker(npz, map_png, frames)
        bbrender.render_one(k)
        hud = os.path.join(frames, "f%05d.png" % k)
        vt = args.vstart + k / float(bbrender.FPS)
        out_jpg = os.path.join(args.out, "预览_%s.jpg" % tag2)
        composite_still(video, hud, out_jpg, vt, grad=args.grad, size=args.size,
                        fill_mode=args.fill,
                        portrait=bool(args.portrait) and args.portrait_mode == "band",
                        hud_pos=args.hud_pos, native_portrait=portrait_mode)
        log("预览图（已叠加视频，含附加效果）：%s" % out_jpg)
        print(json.dumps(dict(preview=out_jpg, lag=lag, vstart=args.vstart, dur=dur,
                              bb_start=bb_start, seg=segno), ensure_ascii=False))
        if not args.keep_frames:
            shutil.rmtree(frames, ignore_errors=True)
        return 0

    # 普通「预览一帧」：和元素位置共用同一批图层，本地拼图，1~2 秒出
    if args.preview:
        meta = ensure_layers(csv, gps, bb_start, dur, args, lag, segno,
                             where="auto", log=log)
        out_jpg = os.path.join(args.out, "预览_%s.jpg" % tag)
        bbcompose.compose(dict(ls=meta["lstick"], rs=meta["rstick"],
                               att=meta["att"], map=meta["map"]),
                          meta["frame"], layout,
                          att_on=not args.no_att, map_on=not args.no_map,
                          mask_on=mask_on, mask2_on=mask2_on, out_path=out_jpg,
                          extra_on=bool(args.tele or args.bars or args.text))
        if args.grad:
            # 勾了顶部压暗：用 ffmpeg 补一层（可选的少数情况）
            try:
                tmp = out_jpg.replace(".jpg", "_g.jpg")
                run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", out_jpg,
                     "-i", GRAD, "-filter_complex", "[0:v][1:v]overlay=0:0[v]",
                     "-map", "[v]", "-q:v", "2", tmp])
                os.replace(tmp, out_jpg)
            except Exception as e:
                log("    顶部压暗没加上：%s" % e)
        log("预览图（用缓存图层拼的）：%s" % out_jpg)
        print(json.dumps(dict(preview=out_jpg, layers=os.path.dirname(meta["frame"]),
                              lag=lag, vstart=args.vstart, dur=dur,
                              bb_start=bb_start, seg=segno), ensure_ascii=False))
        return 0

    frames = os.path.join(CACHE, "frames_" + re.sub(r"[^\w.-]", "_", tag))
    if os.path.exists(frames):
        shutil.rmtree(frames)

    n = bbrender.render(csv, gps, bb_start, dur, frames, jobs=args.jobs,
                        want_att=not args.no_att, want_map=not args.no_map, log=log,
                        map_image=args.map_image, map_center=args.map_center,
                        map_mpp=args.map_mpp, map_rotate=args.map_rotate,
                        layout=layout, text=args.text, obj=args.obj,
                        portrait=portrait_mode)
    log("  渲染完成 %d 帧" % n)

    green = os.path.join(args.out, "绿幕overlay_%s.mp4" % tag)
    encode_green(frames, green, bbrender.FPS, n, size=args.size, fill_mode=args.fill)
    final = os.path.join(args.out, "成片_%s.mp4" % tag)
    composite(video, frames, final, args.vstart, dur, bbrender.FPS, args.crf,
              grad=args.grad, n=n, size=args.size, fill_mode=args.fill,
              vign=args.vignette, corner=1.0 if args.corner else 0.0,
              portrait=bool(args.portrait) and args.portrait_mode == "band",
              hud_pos=args.hud_pos, native_portrait=portrait_mode)

    ok = os.path.exists(final) and os.path.getsize(final) > 10000
    log("")
    log("成品：%s  (%.1f MB)" % (final, os.path.getsize(final) / 1e6 if ok else 0))
    log("绿幕：%s" % green)
    log("总用时 %.0f s" % (time.time() - t_all))
    if not args.keep_frames:
        shutil.rmtree(frames, ignore_errors=True)
    print(json.dumps(dict(final=final, green=green, lag=lag, vstart=args.vstart,
                          dur=dur, bb_start=bb_start, seg=segno), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(_join_arg_values(sys.argv[1:])))