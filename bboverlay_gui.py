#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""黑匣子叠加工具 —— B 版图形界面（A 版的壳，不改核心流程）

双击「启动黑匣子叠加工具.vbs」打开；背后还是调 bboverlay.py，所以命令行照样能用。
"""
import ctypes
import json
import os

import numpy as np
import queue
import shutil
import re
import subprocess
import time
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
APP = os.path.join(HERE, "bboverlay.py")
PYDIR = os.path.dirname(os.path.abspath(sys.executable))
PYEXE = os.path.join(PYDIR, "python.exe")
if not os.path.exists(PYEXE):
    PYEXE = sys.executable
def bbrender_styles():
    try:
        import bbrender
        return bbrender.STICK_STYLES
    except Exception:
        return ["经典圆盘", "圆角方框", "极简圆", "极简方框"]


def bbrender_color_names():
    try:
        import bbrender
        return bbrender.FRAME_COLOR_NAMES
    except Exception:
        return ["浅灰", "纯白", "深黑", "天蓝", "荧光绿", "亮黄", "朱红", "淡紫"]


def bbrender_ball_names():
    try:
        import bbrender
        return bbrender.BALL_COLOR_NAMES
    except Exception:
        return ["红点", "白点", "黑点", "青点", "黄点", "绿点", "紫点", "蓝点"]


APP_VERSION = "3.6.3"

NL = chr(10)


def _write_crash(exc_type, exc_value, tb):
    """把崩溃信息写到 crash.log，pythonw 下也能查"""
    import traceback
    from datetime import datetime
    try:
        path = os.path.join(HERE, "crash.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(NL + "===== %s  v%s =====" % (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), APP_VERSION) + NL)
            f.write("".join(traceback.format_exception(exc_type, exc_value, tb)))
            f.write(NL)
        try:
            messagebox.showerror(
                "程序出错了",
                "已把错误写进 crash.log（在程序文件夹里）：" + NL + path + NL + NL +
                "把那个文件发给我就能定位问题。")
        except Exception:
            pass
    except Exception:
        pass


def _find_ffmpeg():
    for c in (os.path.join(HERE, "tools", "ffmpeg.exe"),
              r"E:\天问Block\tools\ffmpeg.exe", shutil.which("ffmpeg")):
        if c and os.path.exists(c):
            return c
    return "ffmpeg"


FFMPEG = _find_ffmpeg()
OUT_DEFAULT = r"E:\大肥鱼Harness\02_飞行器项目\摇杆演示"
if not os.path.exists(r"E:\大肥鱼Harness"):
    # 换电脑用：没有 E 盘这个目录就默认输出到程序目录下的「输出」
    OUT_DEFAULT = os.path.join(HERE, "输出")
CFG = os.path.join(HERE, "gui_config.json")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

CRF_CHOICES = [("高清（文件大）", 20), ("标准（推荐）", 24), ("小文件", 27)]
BASE_ONLINE = "在线卫星图（高德）"
BASE_PHOTO = "自定义航拍图"

LAYOUT0 = dict(ls_dx=0.0, ls_dy=0.0, ls_s=1.0,
               rs_dx=0.0, rs_dy=0.0, rs_s=1.0,
               att_dx=0.0, att_dy=0.0, att_s=1.0,
               map_dx=26.0, map_dy=20.0, map_s=1.0,
               mask_on=0.0, mask_x=0.0, mask_y=0.0, mask_w=1920.0, mask_h=46.0,
               mask2_on=0.0, mask2_x=0.0, mask2_y=250.0, mask2_w=1920.0, mask2_h=60.0,
               extra_dx=0.0, extra_dy=0.0,
               stick_mode=2.0,
               # 每个元素自己的颜色（元素位置编辑器里改），-1 表示跟框线颜色
               frame_i=0.0, ball_i=0.0, trail_i=4.0,
               map_trail_i=5.0, map_arrow_i=3.0,
               tele_i=-1.0, bar_i=-1.0, text_i=-1.0,
               # 面板/柱状图/文字 的绝对位置、字号、偏移与缩放（编辑器里改）
               tele_x=60.0, tele_y=380.0, tele_size=30.0,
               bar_x=60.0, bar_y=760.0, bar_h=200.0,
               text_x=960.0, text_y=60.0, text_size=44.0, text_anchor=1.0,
               tele_dx=0.0, tele_dy=0.0, tele_s=1.0,
               bar_dx=0.0, bar_dy=0.0, bar_s=1.0,
               text_dx=0.0, text_dy=0.0, text_s=1.0,
               tele_alpha=0.9, bar_alpha=0.9, text_alpha=0.9,
               stick_alpha=1.0, map_alpha=1.0,
               mask_alpha=1.0, mask2_alpha=1.0)

BG = "#eef1f5"
CARD = "#ffffff"
INK = "#111827"
SUB = "#6b7280"
LINE = "#d7dce3"
ACCENT = "#1f4fd8"


# ---------------------------------------------------------------- DPI
def dpi_scale():
    """开启 DPI 感知，返回系统缩放（1.0=100%，1.5=150%）。不开会糊成一团。"""
    if os.name != "nt":
        return 1.0
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)      # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return max(1.0, dpi / 96.0)
    except Exception:
        return 1.0


S = dpi_scale()


def px(v):
    return int(round(v * S))


F_TITLE = ("Microsoft YaHei UI", 17, "bold")
F_BODY = ("Microsoft YaHei UI", 10)
F_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT = "Microsoft YaHei UI"
F_HINT = ("Microsoft YaHei UI", 9)
F_MONO = ("Consolas", 9)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("黑匣子叠加工具 · B 版  v" + APP_VERSION)
        self.geometry("%dx%d" % (px(1060), px(1000)))
        self.minsize(px(940), px(720))
        self.configure(bg=BG)
        try:
            self.tk.call("tk", "scaling", S * 96.0 / 72.0)     # 字体按真实 DPI 渲染
        except Exception:
            pass
        self.proc = None
        self.final = None
        self.q = queue.Queue()
        self.cfg = self._load_cfg()
        self.photo_cal = dict(center="", mpp="", rotate="")
        self.layout = dict(LAYOUT0)
        self.layout_p = None        # 竖屏版式（第一次进竖屏时按 bbrender 预设生成，之后独立保存）
        self.extra = dict(tele=True, tele_x=60.0, tele_y=380.0, tele_size=30.0,
                          bars=True, bar_x=60.0, bar_y=760.0,
                          trail_len=6.0, trail_i=4, trail_w=1.0,
                          map_ruler=False, map_vec=False, map_wp=False,
                          event=False, vignette=0.0, corner=False,
                          size="16:9", fill=0, portrait=False, hud_pos="bottom",
                          text="", text_x=960.0, text_y=60.0,
                          text_size=44.0, text_anchor=1, obj="")

        self._style()
        self._build()
        self._load_values()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(120, self._pump)

    # ------------------------------------------------------------ 外观
    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure(".", font=F_BODY, background=BG, foreground=INK)
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=CARD, relief="flat")
        s.configure("TLabel", background=BG, foreground=INK)
        s.configure("Card.TLabel", background=CARD, foreground=INK)
        s.configure("Hint.TLabel", background=CARD, foreground=SUB, font=F_HINT)
        s.configure("HintBg.TLabel", background=BG, foreground=SUB, font=F_HINT)
        s.configure("Step.TLabel", background=CARD, foreground=ACCENT, font=F_BOLD)
        s.configure("TButton", padding=(px(10), px(5)), font=F_BODY,
                    background="#f6f8fb", foreground=INK, borderwidth=1)
        s.map("TButton", background=[("active", "#e6ecf6")])
        s.configure("Go.TButton", padding=(px(20), px(9)), font=F_BOLD,
                    background=ACCENT, foreground="#ffffff", borderwidth=0)
        s.map("Go.TButton", background=[("active", "#1740b0"), ("disabled", "#9fb0d8")],
              foreground=[("disabled", "#eef1f5")])
        s.configure("TCheckbutton", background=CARD, foreground=INK, font=F_BODY)
        s.map("TCheckbutton", background=[("active", CARD)])
        s.configure("TEntry", padding=px(4), fieldbackground="#ffffff")
        s.configure("TCombobox", padding=px(3))
        s.configure("TProgressbar", background=ACCENT, troughcolor="#dfe5ee",
                    borderwidth=0, thickness=px(6))

    def _card(self, parent, step, title, sub=None):
        outer = ttk.Frame(parent, style="Card.TFrame", padding=px(16))
        ttk.Label(outer, text="%s　%s" % (step, title), style="Step.TLabel").pack(anchor="w")
        if sub:
            ttk.Label(outer, text=sub, style="Hint.TLabel").pack(anchor="w", pady=(px(2), px(10)))
        else:
            ttk.Frame(outer, style="Card.TFrame", height=px(8)).pack()
        return outer

    # ------------------------------------------------------------ 布局
    def _build(self):
        head = ttk.Frame(self, padding=(px(20), px(16), px(20), px(6)))
        head.pack(fill="x")
        ttk.Label(head, text="黑匣子叠加工具", style="TLabel", font=F_TITLE).pack(side="left")
        ttk.Label(head, text="日志 + 眼镜视频 → 摇杆 / 姿态 / 卫星地图叠加片",
                  style="HintBg.TLabel").pack(side="left", padx=px(12), pady=px(8))

        # 常驻进度条 + 动画（无论日志是否打开都看得到）
        prog = ttk.Frame(self, padding=(px(18), px(2), px(18), 0))
        prog.pack(side="bottom", fill="x")
        self.l_spin = ttk.Label(prog, text="", style="HintBg.TLabel", width=px(3))
        self.l_spin.pack(side="left")
        self.pb = ttk.Progressbar(prog, mode="determinate", maximum=100)
        self.pb.pack(side="left", fill="x", expand=True, padx=(px(6), px(10)))
        self.l_prog = ttk.Label(prog, text="就绪", style="HintBg.TLabel")
        self.l_prog.pack(side="right")

        # 按钮
        bar = ttk.Frame(self, padding=(px(18), px(4), px(18), px(6)))
        bar.pack(side="bottom", fill="x")
        self.b_go = ttk.Button(bar, text="开始生成", style="Go.TButton", command=self.start)
        self.b_go.pack(side="left")
        self.b_prev = ttk.Button(bar, text="预览一帧", command=self.preview)
        self.b_prev.pack(side="left", padx=px(10))
        self.b_elem = ttk.Button(bar, text="元素位置", command=self.edit_layout_drag)
        self.b_elem.pack(side="left", padx=(px(10), 0))
        self.b_play = ttk.Button(bar, text="播放成片", command=self.play, state="disabled")
        self.b_play.pack(side="left")
        self.b_log = ttk.Button(bar, text="显示日志", command=self.toggle_log)
        self.b_log.pack(side="right")

        self.l_status = ttk.Label(self, text="就绪", style="HintBg.TLabel", padding=(px(20), px(6)))
        self.l_status.pack(side="bottom", fill="x")

        body = ttk.Frame(self, padding=(px(20), px(4), px(20), 0))
        body.pack(fill="x")
        body.columnconfigure(0, weight=3, uniform="col")
        body.columnconfigure(1, weight=2, uniform="col")

        # 左列：文件
        c1 = self._card(body, "①", "选文件", "黑匣子用 Betaflight 导出的 .bbl / .bfl；视频用眼镜卡里的 .MOV / .mp4")
        c1.grid(row=0, column=0, sticky="ew", padx=(0, px(10)), pady=(0, px(10)))
        g = ttk.Frame(c1, style="Card.TFrame")
        g.pack(fill="x")
        g.columnconfigure(1, weight=1)
        ttk.Label(g, text="黑匣子日志", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.v_bbl = tk.StringVar()
        self.e_bbl = ttk.Entry(g, textvariable=self.v_bbl)
        self.e_bbl.grid(row=0, column=1, sticky="ew", padx=px(8))
        ttk.Button(g, text="选择日志文件", command=self.pick_bbl).grid(row=0, column=2)
        ttk.Label(g, text="眼镜视频", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(px(8), 0))
        self.v_video = tk.StringVar()
        self.e_video = ttk.Entry(g, textvariable=self.v_video)
        self.e_video.grid(row=1, column=1, sticky="ew", padx=px(8), pady=(px(8), 0))
        ttk.Button(g, text="选择视频文件", command=self.pick_video).grid(row=1, column=2, pady=(px(8), 0))
        self.l_video = ttk.Label(g, text="（选好视频后这里显示时长和分辨率）", style="Hint.TLabel")
        self.l_video.grid(row=2, column=1, sticky="w", padx=px(8), pady=(px(4), 0))

        # 左列：时间段
        c2 = self._card(body, "②", "做哪一段", "时间按视频播放器里看到的秒数填")
        c2.grid(row=1, column=0, sticky="ew", padx=(0, px(10)), pady=(0, px(10)))
        g2 = ttk.Frame(c2, style="Card.TFrame")
        g2.pack(fill="x")
        ttk.Label(g2, text="起点", style="Card.TLabel").pack(side="left")
        self.v_start = tk.StringVar(value="0")
        ttk.Entry(g2, width=7, justify="center", textvariable=self.v_start).pack(side="left", padx=px(6))
        ttk.Label(g2, text="秒", style="Card.TLabel").pack(side="left")
        ttk.Label(g2, text="时长", style="Card.TLabel").pack(side="left", padx=(px(18), 0))
        self.v_dur = tk.StringVar(value="30")
        ttk.Entry(g2, width=7, justify="center", textvariable=self.v_dur).pack(side="left", padx=px(6))
        ttk.Label(g2, text="秒", style="Card.TLabel").pack(side="left")
        g2b = ttk.Frame(c2, style="Card.TFrame")
        g2b.pack(fill="x", pady=(px(8), 0))
        ttk.Label(g2b, text="日志段", style="Card.TLabel").pack(side="left")
        self.v_seg = tk.StringVar(value="0")
        ttk.Entry(g2b, width=5, justify="center", textvariable=self.v_seg).pack(side="left",
                                                                             padx=px(6))
        ttk.Label(g2b, text="（0 = 自动挑对得上的那段；日志只有一段就填 1）",
                  style="Hint.TLabel").pack(side="left")
        ttk.Label(c2, text="30 秒 1080p 成片大约 40~50 MB", style="Hint.TLabel").pack(anchor="w", pady=(px(6), 0))

        # 右列：画面
        c3 = self._card(body, "③", "画面", "勾掉不需要的元素，出片更快")
        c3.grid(row=0, column=1, sticky="ew", pady=(0, px(10)))
        g3 = ttk.Frame(c3, style="Card.TFrame")
        g3.pack(fill="x")
        self.v_map = tk.BooleanVar(value=True)
        self.v_att = tk.BooleanVar(value=True)
        tk.Checkbutton(g3, text="卫星小地图", variable=self.v_map, bg=CARD,
                       activebackground=CARD, font=F_BODY, anchor="w").pack(side="left")
        tk.Checkbutton(g3, text="3D 姿态", variable=self.v_att, bg=CARD, activebackground=CARD,
                       font=F_BODY, anchor="w").pack(side="left", padx=(px(16), 0))
        self.v_mask = tk.BooleanVar(value=False)
        self.v_mask2 = tk.BooleanVar(value=False)
        g3m = ttk.Frame(c3, style="Card.TFrame")
        g3m.pack(fill="x", pady=(px(8), 0))
        tk.Checkbutton(g3m, text="GPS 坐标遮盖 1（黑块）", variable=self.v_mask, bg=CARD,
                       activebackground=CARD, font=F_BODY, anchor="w").pack(side="left")
        tk.Checkbutton(g3m, text="GPS 坐标遮盖 2（黑块）", variable=self.v_mask2, bg=CARD,
                       activebackground=CARD, font=F_BODY, anchor="w").pack(side="left",
                                                                          padx=(px(14), 0))
        self.v_grad = tk.BooleanVar(value=False)
        g3g = ttk.Frame(c3, style="Card.TFrame")
        g3g.pack(fill="x", pady=(px(6), 0))
        tk.Checkbutton(g3g, text="顶部渐变压暗", variable=self.v_grad, bg=CARD,
                       activebackground=CARD, font=F_BODY, anchor="w").pack(side="left")
        ttk.Label(g3g, text="（勾了会把画面顶上压暗一条，默认不加）",
                  style="Hint.TLabel").pack(side="left", padx=(px(8), 0))
        ttk.Label(c3, text="两块黑块的位置和大小在「元素位置」里调", style="Hint.TLabel").pack(
            anchor="w", pady=(px(2), 0))
        gm = ttk.Frame(c3, style="Card.TFrame")
        gm.pack(fill="x", pady=(px(10), 0))
        ttk.Label(gm, text="摇杆手别", style="Card.TLabel").pack(side="left")
        self.v_mode = tk.StringVar(value="美国手（MODE2）")
        ttk.Combobox(gm, textvariable=self.v_mode, state="readonly", width=px(16),
                     values=["美国手（MODE2）", "日本手（MODE1）"]).pack(side="left", padx=(px(8), 0))
        # 摇杆样式：样式 / 透明度 / 颜色 / us 数值
        gs = ttk.Frame(c3, style="Card.TFrame")
        gs.pack(fill="x", pady=(px(8), 0))
        ttk.Label(gs, text="摇杆样式", style="Card.TLabel").pack(side="left")
        self.v_style = tk.StringVar(value="经典圆盘")
        ttk.Combobox(gs, textvariable=self.v_style, width=px(9), state="readonly",
                     values=bbrender_styles()).pack(side="left", padx=(px(6), px(10)))
        ttk.Label(gs, text="透明", style="Card.TLabel").pack(side="left")
        self.v_alpha = tk.DoubleVar(value=1.0)
        ttk.Scale(gs, variable=self.v_alpha, from_=0.15, to=1.0, orient="horizontal", length=px(84)).pack(side="left", padx=(px(4), px(10)))

        gc = ttk.Frame(c3, style="Card.TFrame")
        gc.pack(fill="x", pady=(px(4), 0))
        ttk.Label(gc, text="颜色", style="Card.TLabel").pack(side="left")
        self.v_fcol = tk.StringVar(value="浅灰")
        ttk.Combobox(gc, textvariable=self.v_fcol, width=px(6), state="readonly",
                     values=bbrender_color_names()).pack(side="left", padx=(px(6), px(8)))
        self.v_bcol = tk.StringVar(value="红点")
        ttk.Combobox(gc, textvariable=self.v_bcol, width=px(6), state="readonly",
                     values=bbrender_ball_names()).pack(side="left", padx=(0, px(10)))
        self.v_us = tk.BooleanVar(value=False)
        tk.Checkbutton(gc, text="显示 us 数值", variable=self.v_us, bg=CARD,
                       activebackground=CARD, font=F_BODY).pack(side="left")

        gr = ttk.Frame(c3, style="Card.TFrame")
        gr.pack(fill="x", pady=(px(6), 0))
        ttk.Label(gr, text="通道反向", style="Card.TLabel").pack(side="left")
        self.v_inv = {}
        for key, label in (("thr", "油门"), ("rol", "横滚"), ("pit", "俯仰"), ("yaw", "方向")):
            var = tk.BooleanVar(value=False)
            tk.Checkbutton(gr, text=label, variable=var, bg=CARD, activebackground=CARD,
                           font=F_BODY).pack(side="left", padx=(px(6), 0))
            self.v_inv[key] = var
        ttk.Label(c3, text="（感觉某个通道反了就勾它，改完重新「预览一帧」核对）",
                  style="Hint.TLabel").pack(anchor="w", pady=(px(2), 0))
        gm = ttk.Frame(c3, style="Card.TFrame")
        gm.pack(fill="x", pady=(px(6), 0))
        ttk.Label(gm, text="小地图", style="Card.TLabel").pack(side="left")
        self.v_mapshape = tk.StringVar(value="矩形")
        ttk.Combobox(gm, textvariable=self.v_mapshape, width=px(7), state="readonly",
                     values=["矩形", "圆角矩形", "椭圆"]).pack(side="left", padx=(px(4), px(6)))
        ttk.Label(gm, text="透明", style="Card.TLabel").pack(side="left")
        self.v_mapalpha = tk.DoubleVar(value=1.0)
        ttk.Scale(gm, variable=self.v_mapalpha, from_=0.2, to=1.0, orient="horizontal", length=px(70)).pack(side="left")

        gc2 = ttk.Frame(c3, style="Card.TFrame")
        gc2.pack(fill="x", pady=(px(4), 0))
        ttk.Label(gc2, text="小地图视角", style="Card.TLabel").pack(side="left")
        self.v_mapcam = tk.StringVar(value=str(self.extra.get("map_cam", "位置居中（跟随）")))
        ttk.Combobox(gc2, textvariable=self.v_mapcam, width=px(12), state="readonly",
                     values=["起点居中", "轨迹居中", "位置居中（跟随）"]).pack(side="left", padx=(px(6), 0))
        self.v_mapzoom = tk.BooleanVar(value=bool(self.extra.get("map_zoom", True)))
        tk.Checkbutton(gc2, text="自动缩放", variable=self.v_mapzoom, bg=CARD,
                       activebackground=CARD, font=F_BODY).pack(side="left", padx=(px(8), 0))

        gu = ttk.Frame(c3, style="Card.TFrame")
        gu.pack(fill="x", pady=(px(4), 0))
        ttk.Label(gu, text="小地图朝向", style="Card.TLabel").pack(side="left")
        self.v_mapup = tk.StringVar(value=str(self.extra.get("map_up", "正北朝上")))
        ttk.Combobox(gu, textvariable=self.v_mapup, width=px(8), state="readonly",
                     values=["正北朝上", "航向朝上"]).pack(side="left", padx=(px(6), px(10)))
        self.v_maparrow = tk.BooleanVar(value=bool(self.extra.get("map_arrow", True)))
        tk.Checkbutton(gu, text="飞行方向箭头", variable=self.v_maparrow, bg=CARD,
                       activebackground=CARD, font=F_BODY).pack(side="left")

        gk = ttk.Frame(c3, style="Card.TFrame")
        gk.pack(fill="x", pady=(px(4), 0))
        ttk.Label(gk, text="黑块", style="Card.TLabel").pack(side="left")
        self.v_kshape = tk.StringVar(value="矩形")
        ttk.Combobox(gk, textvariable=self.v_kshape, width=px(7), state="readonly",
                     values=["矩形", "圆角矩形", "椭圆"]).pack(side="left", padx=(px(4), px(6)))
        ttk.Label(gk, text="透明", style="Card.TLabel").pack(side="left")
        self.v_kalpha = tk.DoubleVar(value=1.0)
        ttk.Scale(gk, variable=self.v_kalpha, from_=0.3, to=1.0, orient="horizontal", length=px(70)).pack(side="left")

        ga = ttk.Frame(c3, style="Card.TFrame")
        ga.pack(fill="x", pady=(px(6), 0))
        ttk.Label(ga, text="姿态来源", style="Card.TLabel").pack(side="left")
        self.v_attmode = tk.StringVar(value=str(self.extra.get("att_mode", "积分（稳）")))
        ttk.Combobox(ga, textvariable=self.v_attmode, width=px(9), state="readonly",
                     values=["积分（稳）", "重力（试）"]).pack(side="left", padx=(px(6), px(10)))
        ttk.Label(ga, text="机头偏置", style="Card.TLabel").pack(side="left")
        self.v_attyaw = tk.StringVar(value="%d°" % int(self.extra.get("att_yaw", 0)))
        ttk.Combobox(ga, textvariable=self.v_attyaw, width=px(6), state="readonly",
                     values=["0°", "90°", "180°", "270°"]).pack(side="left", padx=(px(6), 0))


        gb = ttk.Frame(c3, style="Card.TFrame")
        gb.pack(fill="x", pady=(px(4), 0))
        ttk.Label(gb, text="俯仰显示", style="Card.TLabel").pack(side="left")
        self.v_attinvpit = tk.BooleanVar(value=bool(self.extra.get("att_inv_pit", True)))
        self.v_attinvrol = tk.BooleanVar(value=bool(self.extra.get("att_inv_rol", False)))
        self.v_stickdir = tk.StringVar(value=str(self.extra.get("stick_dir", "拉杆=抬头（标准）")))
        ttk.Combobox(gb, textvariable=self.v_stickdir, width=px(9), state="readonly",
                     values=["拉杆=抬头（标准）", "跟随机头"]).pack(side="left", padx=(px(6), px(8)))
        ttk.Button(gb, text="摇杆自动校准", command=self.auto_calib_sticks).pack(side="left")
        gd = ttk.Frame(c3, style="Card.TFrame")
        gd.pack(fill="x", pady=(px(4), 0))
        ttk.Label(gd, text="模型反向", style="Card.TLabel").pack(side="left")
        tk.Checkbutton(gd, text="俯仰", variable=self.v_attinvpit, bg=CARD,
                       activebackground=CARD, font=F_BODY).pack(side="left", padx=(px(8), 0))
        tk.Checkbutton(gd, text="滚转", variable=self.v_attinvrol, bg=CARD,
                       activebackground=CARD, font=F_BODY).pack(side="left", padx=(px(6), 0))

        ge = ttk.Frame(c3, style="Card.TFrame")
        ge.pack(fill="x", pady=(px(6), 0))
        ttk.Button(ge, text="高级效果（面板/柱状图/文字/画幅/暗角/模型）",
                   command=self.extra_dialog).pack(side="left")

        ttk.Label(c3, text="底图", style="Card.TLabel").pack(anchor="w", pady=(px(10), px(2)))
        self.v_base = tk.StringVar(value=BASE_ONLINE)
        ttk.Combobox(c3, textvariable=self.v_base, state="readonly", width=px(20),
                     values=[BASE_ONLINE, BASE_PHOTO],
                     font=F_BODY).pack(anchor="w")
        self.v_base.trace_add("write", lambda *a: self._toggle_base())

        self.f_photo = ttk.Frame(c3, style="Card.TFrame")
        gp = ttk.Frame(self.f_photo, style="Card.TFrame")
        gp.pack(fill="x", pady=(px(8), 0))
        gp.columnconfigure(0, weight=1)
        self.v_photo = tk.StringVar()
        ttk.Entry(gp, textvariable=self.v_photo).grid(row=0, column=0, sticky="ew")
        ttk.Button(gp, text="选择图片", command=self.pick_photo).grid(row=0, column=1, padx=(px(6), 0))
        ttk.Button(gp, text="标定参数", command=self.calibrate).grid(row=0, column=2, padx=(px(6), 0))
        self.l_cal = ttk.Label(self.f_photo, text="标定：中心/米每像素/旋转（EXIF 能读就自动）",
                               style="Hint.TLabel")
        self.l_cal.pack(anchor="w", pady=(px(4), 0))

        # 右列：输出
        c4 = self._card(body, "④", "输出")
        c4.grid(row=1, column=1, sticky="ew", pady=(0, px(10)))
        g4 = ttk.Frame(c4, style="Card.TFrame")
        g4.pack(fill="x")
        g4.columnconfigure(1, weight=1)
        ttk.Label(g4, text="画质", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.v_crf = tk.StringVar(value=CRF_CHOICES[1][0])
        ttk.Combobox(g4, textvariable=self.v_crf, width=px(14), state="readonly",
                     values=[c[0] for c in CRF_CHOICES]).grid(row=0, column=1, sticky="w", padx=px(8))
        ttk.Label(c4, text="输出目录", style="Card.TLabel").pack(anchor="w", pady=(px(10), px(4)))
        go = ttk.Frame(c4, style="Card.TFrame")
        go.pack(fill="x")
        go.columnconfigure(0, weight=1)
        self.v_out = tk.StringVar(value=OUT_DEFAULT)
        ttk.Entry(go, textvariable=self.v_out).grid(row=0, column=0, columnspan=3, sticky="ew")
        ttk.Button(go, text="选择目录", command=self.pick_out).grid(row=1, column=0,
                                                                sticky="w", pady=(px(6), 0))
        ttk.Button(go, text="打开文件夹", command=self.open_out).grid(row=1, column=1,
                                                                 sticky="w", padx=(px(6), 0),
                                                                 pady=(px(6), 0))
        ttk.Button(go, text="一键卸载程序", command=self.uninstall_app).grid(
            row=1, column=2, sticky="w", padx=(px(6), 0), pady=(px(6), 0))


        # 时间差
        c5 = ttk.Frame(body, style="Card.TFrame", padding=px(10))
        c5.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, px(10)))
        self.v_auto = tk.BooleanVar(value=True)
        tk.Checkbutton(c5, text="自动测时间差（推荐）", variable=self.v_auto, command=self._toggle_lag,
                       bg=CARD, activebackground=CARD, font=F_BODY).pack(side="left")
        ttk.Label(c5, text="手动 lag", style="Card.TLabel").pack(side="left", padx=(px(20), px(6)))
        self.v_lag = tk.StringVar(value="-0.97")
        self.e_lag = ttk.Entry(c5, textvariable=self.v_lag, width=8, justify="center")
        self.e_lag.pack(side="left")
        ttk.Label(c5, text="秒（自动测失败时才手填）", style="Hint.TLabel").pack(side="left", padx=px(8))

        self.logf = ttk.Frame(self)          # 占位：日志已改到独立窗口
        logf = self.logf
        # 默认收起；展开时只占固定高度，绝不把下面的按钮挤出去
        self._log_open = False

        wrap = ttk.Frame(logf)
        wrap.pack(fill="both", expand=True)
        self.txt = tk.Text(wrap, height=8, bg="#0f172a", fg="#cbd5e1", insertbackground="#fff",
                           font=F_MONO, relief="flat", wrap="none", padx=px(10), pady=px(8),
                           selectbackground="#1e3a8a")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.log("就绪。选好黑匣子和视频，点「开始生成」。")

    # ------------------------------------------------------------ 底图切换
    def _toggle_base(self):
        if self.v_base.get() == BASE_PHOTO:
            self.f_photo.pack(fill="x", anchor="w")
        else:
            self.f_photo.pack_forget()

    def pick_photo(self):
        p = filedialog.askopenfilename(
            title="选自己航拍的正射图 / 正俯视照片",
            filetypes=[("图片", "*.jpg *.jpeg *.png *.tif *.tiff *.JPG *.JPEG"), ("所有文件", "*.*")])
        if not p:
            return
        self.v_photo.set(p)
        try:
            import bbphotomap
            info = bbphotomap.read_info(p, log=lambda *a: None)
            bits = []
            if info.get("lat") is not None:
                bits.append("中心 %.6f,%.6f" % (info["lat"], info["lon"]))
                self.photo_cal["center"] = "%.7f,%.7f" % (info["lat"], info["lon"])
            if info.get("mpp"):
                bits.append("%.4f 米/像素" % info["mpp"])
                self.photo_cal["mpp"] = "%.5f" % info["mpp"]
            if info.get("yaw") is not None:
                bits.append("旋转 %.0f°" % info["yaw"])
                self.photo_cal["rotate"] = "%.1f" % info["yaw"]
            if info.get("mpp") is None:
                bits.append("EXIF 里没有高度/焦距 → 请点「标定参数」手填米/像素")
            self.l_cal.configure(text="　".join(bits) or "读不到 EXIF，请点「标定参数」手填")
            self.log("底图：%s  %s" % (os.path.basename(p), "　".join(bits)))
        except Exception as e:
            self.l_cal.configure(text="读 EXIF 失败：%s" % e)

    def calibrate(self):
        d = tk.Toplevel(self)
        d.title("底图标定")
        d.configure(bg=CARD)
        d.transient(self)
        d.grab_set()
        f = ttk.Frame(d, style="Card.TFrame", padding=px(18))
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="照片中心经纬度、分辨率、旋转（填一个点也行，留空就按轨迹自动）",
                  style="Hint.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, px(10)))
        fields = [("中心 lat,lon", "center"), ("米/像素", "mpp"), ("旋转角 °", "rotate")]
        vs = {}
        for i, (label, key) in enumerate(fields, start=1):
            ttk.Label(f, text=label, style="Card.TLabel").grid(row=i, column=0, sticky="w", pady=px(4))
            v = tk.StringVar(value=self.photo_cal.get(key, ""))
            ttk.Entry(f, textvariable=v, width=px(26)).grid(row=i, column=1, sticky="w",
                                                            padx=px(10), pady=px(4))
            vs[key] = v

        def from_exif():
            p = self.v_photo.get()
            if not p:
                return
            try:
                import bbphotomap
                info = bbphotomap.read_info(p, log=lambda *a: None)
                if info.get("lat") is not None:
                    vs["center"].set("%.7f,%.7f" % (info["lat"], info["lon"]))
                if info.get("mpp"):
                    vs["mpp"].set("%.5f" % info["mpp"])
                if info.get("yaw") is not None:
                    vs["rotate"].set("%.1f" % info["yaw"])
            except Exception as e:
                messagebox.showerror("读不到", str(e), parent=d)

        def ok():
            for k, v in vs.items():
                self.photo_cal[k] = v.get().strip()
            d.destroy()
            c = self.photo_cal
            self.l_cal.configure(text="标定：中心 %s　米/像素 %s　旋转 %s°"
                                 % (c.get("center") or "轨迹中心", c.get("mpp") or "自动",
                                    c.get("rotate") or "0"))

        bf = ttk.Frame(f, style="Card.TFrame")
        bf.grid(row=len(fields) + 1, column=0, columnspan=2, sticky="e", pady=(px(14), 0))
        ttk.Button(bf, text="从图片 EXIF 读取", command=from_exif).pack(side="left", padx=(0, px(8)))
        ttk.Button(bf, text="确定", style="Go.TButton", command=ok).pack(side="left")

    # ------------------------------------------------------------ 元素位置
    def edit_layout_drag(self):
        if self.proc:
            messagebox.showinfo("正在跑", "上一个任务还没结束")
            return
        if not self._check():
            return
        import re as _re
        stem = os.path.splitext(os.path.basename(self.v_video.get()))[0]
        tag = "%s_%gs-%gs" % (stem, self._start(), self._start() + self._dur())
        if self._is_portrait():
            tag += "_竖屏"            # 横/竖屏图层画布不一样，缓存目录必须分开
        d = os.path.join(HERE, "cache", "layers_" + _re.sub(r"[^\w.-]", "_", tag))
        self.log("正在切出可拖拽的图层（一次约 30 秒）")
        self._run(self._args(layers=d), "切图层")

    def _is_portrait(self):
        """当前是否竖屏原生排版（HUD 画布是 1080x1920）"""
        return bool(self.extra.get("portrait")) and str(self.extra.get("size", "16:9")) == "9:16"

    def eff_layout(self):
        """当前实际生效的版式：横屏用 layout，竖屏用 layout_p（预设 + 用户拖动）"""
        if not self._is_portrait():
            return self.layout
        if not isinstance(self.layout_p, dict):
            try:
                import bbrender
                self.layout_p = bbrender.portrait_layout(dict(self.layout))
            except Exception:
                self.layout_p = dict(self.layout)
        return self.layout_p

    def _set_layout(self, lay):
        if self._is_portrait():
            self.layout_p = lay
        else:
            self.layout = lay

    def _color_layout(self):
        """把界面上各处的颜色合进版式，供「元素位置」显示/修改"""
        L = dict(self.eff_layout())
        try:
            fnames = bbrender_color_names()
            bnames = bbrender_ball_names()
            L["frame_i"] = float(fnames.index(self.v_fcol.get())
                                 if self.v_fcol.get() in fnames else 0)
            L["ball_i"] = float(bnames.index(self.v_bcol.get())
                                if self.v_bcol.get() in bnames else 0)
            L["trail_i"] = float(self.extra.get("trail_i", 4))
        except Exception:
            pass
        return L

    def _apply_color_layout(self, lay):
        """编辑器改了颜色 → 写回主界面下拉框 / 高级效果，保持两处一致"""
        try:
            fnames = bbrender_color_names()
            bnames = bbrender_ball_names()
            if "frame_i" in lay:
                self.v_fcol.set(fnames[int(round(float(lay["frame_i"]))) % len(fnames)])
            if "ball_i" in lay:
                self.v_bcol.set(bnames[int(round(float(lay["ball_i"]))) % len(bnames)])
            if "trail_i" in lay:
                self.extra["trail_i"] = int(round(float(lay["trail_i"])))
            for k in ("tele_i", "bar_i", "text_i"):
                if k in lay:
                    self.eff_layout()[k] = float(lay[k])
        except Exception:
            pass

    def _open_drag_editor(self, data):
        try:
            from bboverlay_layout_editor import LayoutEditor
        except Exception as e:
            messagebox.showerror("打不开编辑器", str(e))
            return

        def on_save(lay):
            self._set_layout(lay)
            self._apply_color_layout(lay)
            for _k in ("tele_x", "tele_y", "tele_size", "bar_x", "bar_y",
                       "text_x", "text_y", "text_size", "text_anchor"):
                if _k in lay:
                    self.extra[_k] = lay[_k]
            self.save_cfg()
            self.log("元素位置已保存：左杆 (%d,%d) %d%%　右杆 (%d,%d) %d%%　姿态 (%d,%d) %d%%"
                     % (lay.get("ls_dx", 0), lay.get("ls_dy", 0), round(lay.get("ls_s", 1) * 100),
                        lay.get("rs_dx", 0), lay.get("rs_dy", 0), round(lay.get("rs_s", 1) * 100),
                        lay.get("att_dx", 0), lay.get("att_dy", 0),
                        round(lay.get("att_s", 1.0) * 100)))
            self.status("元素位置已保存，点「预览一帧」看效果")

        size = tuple(data.get("size") or (1920, 1080))
        LayoutEditor(self, data, self._color_layout(), on_save=on_save,
                     map_on=self.v_map.get(), att_on=self.v_att.get(),
                     mask_on=self.v_mask.get(), mask2_on=self.v_mask2.get(),
                     scale=S, stick_mode=float(self._mode()),
                     canvas=size,
                     extra_on=bool(self.extra.get("tele") or self.extra.get("bars")
                                   or (self.extra.get("text") or "").strip()))

    # ------------------------------------------------------------ 版式（数值）
    def _mode(self):
        return 2 if "美国" in self.v_mode.get() else 1

# ---------------------------------------------------------------- 高级效果
# ------------------------------------------------------------ 自动校准
    def toggle_log(self):
        """日志单独开一个窗口，主界面按钮区不受影响"""
        win = getattr(self, "_logwin", None)
        if win is not None and win.winfo_exists():
            win.destroy()
            self._logwin = None
            self.b_log.configure(text="显示日志")
            return
        win = tk.Toplevel(self)
        win.title("运行日志")
        win.configure(bg=BG)
        win.geometry("%dx%d" % (px(760), px(420)))
        self._logwin = win
        box = ttk.Frame(win, padding=px(8))
        box.pack(fill="both", expand=True)
        txt = tk.Text(box, height=16, bg="#0f172a", fg="#cbd5e1", insertbackground="#fff",
                      relief="flat", wrap="none", padx=px(10), pady=px(8))
        sb = ttk.Scrollbar(box, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        txt.configure(state="normal")
        txt.insert("end", "".join(getattr(self, "_loghist", [])))
        txt.configure(state="disabled")
        txt.see("end")
        self._logwin_txt = txt
        self.b_log.configure(text="隐藏日志")

    def auto_calib_sticks(self):
        """用「摇杆指令 vs 陀螺」的相关性自动判断通道方向（负相关就反向）"""
        bbl = self.v_bbl.get()
        if not (bbl and os.path.exists(bbl)):
            messagebox.showwarning("先选日志", "先在①里选好黑匣子日志，再点自动校准。")
            return
        w = os.path.join(HERE, "work")
        cand = []
        try:
            cand = sorted([f for f in os.listdir(w)
                           if f.endswith(".csv") and not f.endswith(".gps.csv")])
        except Exception:
            cand = []
        if not cand:
            messagebox.showinfo("还没解码",
                                "先点一次「预览一帧」（会自动解码），再点自动校准。")
            return
        self.log("自动校准：分析摇杆指令与陀螺的相关性 …")
        try:
            import bbrender
            t, rc, gyro, acc, t0, ext = bbrender.read_csv(
                os.path.join(w, cand[0]), need_att=True, log=lambda *a: None)
            for name, key, i in (("横滚", "rol", 0), ("俯仰", "pit", 1), ("方向", "yaw", 2)):
                try:
                    c = float(np.corrcoef(rc[i], gyro[i])[0, 1])
                except Exception:
                    c = 1.0
                inv = c < -0.05
                self.v_inv[key].set(inv)
                self.log("  %s：相关性 %+.2f → %s" % (name, c, "已反向" if inv else "正常"))
            self._safe_save()
            self.log("自动校准完成，结果已写进「通道反向」，可以「预览一帧」核对一下")
        except Exception as e:
            self.log("自动校准失败：%s" % e)

    def extra_dialog(self):
        e = self.extra
        dlg = tk.Toplevel(self)
        dlg.title("高级效果")
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.resizable(False, False)
        S_ = px

        body = ttk.Frame(dlg, padding=S_(16))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1, uniform="c")
        body.columnconfigure(1, weight=1, uniform="c")

        def card(r, c, title):
            f = ttk.Frame(body, style="Card.TFrame", padding=S_(12))
            f.grid(row=r, column=c, sticky="nsew", padx=S_(6), pady=S_(6))
            ttk.Label(f, text=title, style="Card.TLabel",
                      font=(FONT, int(12), "bold")).pack(anchor="w")
            return f

        vars_ = {}

        def chk(parent, key, text):
            v = tk.BooleanVar(value=bool(e.get(key)))
            tk.Checkbutton(parent, text=text, variable=v, bg=CARD, activebackground=CARD,
                           font=F_BODY).pack(anchor="w")
            vars_[key] = v
            return v

        def row(parent, label, key, width=7):
            fr = ttk.Frame(parent, style="Card.TFrame")
            fr.pack(anchor="w", pady=(S_(2), 0))
            ttk.Label(fr, text=label, style="Card.TLabel").pack(side="left")
            v = tk.StringVar(value=str(e.get(key, "")))
            ttk.Entry(fr, textvariable=v, width=width, justify="center").pack(side="left", padx=S_(6))
            vars_[key] = v
            return v

        c1 = card(0, 0, "数值面板")
        chk(c1, "tele", "显示 油门/电压/电流/速度/高度/卫星")
        row(c1, "位置 X", "tele_x")
        row(c1, "位置 Y", "tele_y")
        row(c1, "字号", "tele_size")

        c2 = card(0, 1, "条形图")
        chk(c2, "bars", "显示 油门 / 电压 竖条")
        row(c2, "位置 X", "bar_x")
        row(c2, "位置 Y", "bar_y")

        c3 = card(1, 0, "自定义文字")
        fr = ttk.Frame(c3, style="Card.TFrame")
        fr.pack(anchor="w")
        ttk.Label(fr, text="内容", style="Card.TLabel").pack(side="left")
        v_text = tk.StringVar(value=str(e.get("text") or ""))
        ttk.Entry(fr, textvariable=v_text, width=S_(22)).pack(side="left", padx=S_(6))
        vars_["text"] = v_text
        row(c3, "位置 X", "text_x")
        row(c3, "位置 Y", "text_y")
        row(c3, "字号", "text_size")
        fr = ttk.Frame(c3, style="Card.TFrame")
        fr.pack(anchor="w", pady=(S_(2), 0))
        ttk.Label(fr, text="锚点", style="Card.TLabel").pack(side="left")
        anchors = ["左上", "中上", "右上", "左中", "居中", "右中", "左下", "中下", "右下"]
        v_anchor = tk.StringVar(value=anchors[int(e.get("text_anchor", 1)) % 9])
        ttk.Combobox(fr, textvariable=v_anchor, values=anchors, width=S_(6),
                     state="readonly").pack(side="left", padx=S_(6))
        vars_["text_anchor"] = v_anchor

        c4 = card(1, 1, "摇杆轨迹")
        row(c4, "长度（帧）", "trail_len")
        row(c4, "粗细倍数", "trail_w")
        fr = ttk.Frame(c4, style="Card.TFrame")
        fr.pack(anchor="w", pady=(S_(2), 0))
        ttk.Label(fr, text="颜色", style="Card.TLabel").pack(side="left")
        v_tc = tk.StringVar(value=bbrender_color_names()[int(e.get("trail_i", 4)) % 8])
        ttk.Combobox(fr, textvariable=v_tc, values=bbrender_color_names(), width=S_(6),
                     state="readonly").pack(side="left", padx=S_(6))
        vars_["trail_i"] = v_tc

        ccal = card(3, 0, "数据校准（对齐眼镜 OSD：新值 = 原值×倍率 + 偏移）")
        cal_vars = {}
        grid = ttk.Frame(ccal, style="Card.TFrame")
        grid.pack(anchor="w")
        for i, (key, lab) in enumerate((("vbat", "电压 V"), ("amp", "电流 A"),
                                        ("alt", "高度 m"), ("spd", "速度 km/h"))):
            ttk.Label(grid, text=lab, style="Card.TLabel").grid(
                row=i, column=0, sticky="w", pady=S_(2))
            vk = tk.StringVar(value="%.3f" % float(e.get(key + "_k", 1.0)))
            vb = tk.StringVar(value="%.2f" % float(e.get(key + "_b", 0.0)))
            ttk.Entry(grid, textvariable=vk, width=S_(6), justify="center").grid(
                row=i, column=1, padx=S_(4))
            ttk.Entry(grid, textvariable=vb, width=S_(6), justify="center").grid(
                row=i, column=2, padx=S_(4))
            cal_vars[key] = (vk, vb)
        ttk.Label(ccal, text="倍率（左） / 偏移（右）", style="Card.TLabel").pack(anchor="w")
        vars_["__cal__"] = cal_vars

        c5 = card(2, 0, "小地图附加")
        chk(c5, "map_ruler", "比例尺")
        chk(c5, "map_vec", "速度矢量")
        chk(c5, "map_wp", "航点小圆点")
        chk(c5, "event", "解锁 / 上锁 标记")

        c6 = card(2, 1, "画面观感")
        fr = ttk.Frame(c6, style="Card.TFrame")
        fr.pack(anchor="w")
        ttk.Label(fr, text="暗角", style="Card.TLabel").pack(side="left")
        v_vg = tk.DoubleVar(value=float(e.get("vignette", 0.0)))
        tk.Scale(fr, variable=v_vg, from_=0.0, to=1.0, resolution=0.1, orient="horizontal",
                 length=S_(80), bg=CARD, highlightthickness=0, font=F_HINT).pack(side="left")
        vars_["vignette"] = v_vg
        chk(c6, "corner", "四角圆角")
        fr = ttk.Frame(c6, style="Card.TFrame")
        fr.pack(anchor="w", pady=(S_(2), 0))
        ttk.Label(fr, text="画幅", style="Card.TLabel").pack(side="left")
        v_size = tk.StringVar(value=e.get("size", "16:9"))
        ttk.Combobox(fr, textvariable=v_size, values=["16:9", "1:1", "4:5", "9:16"], width=S_(6),
                     state="readonly").pack(side="left", padx=S_(6))
        vars_["size"] = v_size
        v_fill = tk.StringVar(value="补黑边" if int(e.get("fill", 0)) == 0 else "裁切填满")
        ttk.Combobox(fr, textvariable=v_fill, values=["补黑边", "裁切填满"], width=S_(8),
                     state="readonly").pack(side="left")
        vars_["fill"] = v_fill
        v_pt = tk.BooleanVar(value=bool(e.get("portrait")))
        tk.Checkbutton(c6, text="竖屏排版（HUD 按竖屏重新布局，字号更大）",
                       variable=v_pt, bg=CARD, activebackground=CARD,
                       font=F_BODY).pack(anchor="w", pady=(S_(2), 0))
        vars_["portrait"] = v_pt
        fr = ttk.Frame(c6, style="Card.TFrame")
        fr.pack(anchor="w")
        ttk.Label(fr, text="HUD 位置", style="Card.TLabel").pack(side="left")
        posmap = {"底部": "bottom", "居中": "center", "顶部": "top"}
        rev = {v: k for k, v in posmap.items()}
        v_pos = tk.StringVar(value=rev.get(str(e.get("hud_pos", "bottom")), "底部"))
        ttk.Combobox(fr, textvariable=v_pos, values=["底部", "居中", "顶部"], width=S_(6),
                     state="readonly").pack(side="left", padx=S_(6))
        vars_["hud_pos"] = v_pos

        c7 = card(3, 0, "3D 模型（可选）")
        ttk.Label(c7, text="留空＝内置方块飞机；选 .obj 用自己的模型",
                  style="Hint.TLabel").pack(anchor="w")
        fr = ttk.Frame(c7, style="Card.TFrame")
        fr.pack(anchor="w", pady=(S_(4), 0))
        v_obj = tk.StringVar(value=str(e.get("obj") or ""))
        ttk.Entry(fr, textvariable=v_obj, width=S_(24)).pack(side="left")
        vars_["obj"] = v_obj

        def pick_obj():
            p = filedialog.askopenfilename(title="选择 OBJ 模型",
                                           filetypes=[("OBJ 模型", "*.obj"), ("所有文件", "*.*")])
            if p:
                v_obj.set(p)
        ttk.Button(fr, text="选择模型", command=pick_obj).pack(side="left", padx=S_(6))

        bar = ttk.Frame(dlg, padding=(S_(16), 0, S_(16), S_(14)))
        bar.pack(fill="x")

        def on_ok():
            def fnum(key, default=0.0):
                try:
                    return float(vars_[key].get())
                except Exception:
                    return default
            e["tele"] = bool(vars_["tele"].get())
            e["tele_x"], e["tele_y"] = fnum("tele_x", 60), fnum("tele_y", 380)
            e["tele_size"] = fnum("tele_size", 30)
            e["bars"] = bool(vars_["bars"].get())
            e["bar_x"], e["bar_y"] = fnum("bar_x", 60), fnum("bar_y", 760)
            e["text"] = v_text.get()
            e["text_x"], e["text_y"] = fnum("text_x", 960), fnum("text_y", 60)
            e["text_size"] = fnum("text_size", 44)
            try:
                e["text_anchor"] = anchors.index(v_anchor.get())
            except ValueError:
                e["text_anchor"] = 1
            e["trail_len"] = fnum("trail_len", 6)
            e["trail_w"] = max(0.3, fnum("trail_w", 1.0))
            try:
                e["trail_i"] = bbrender_color_names().index(v_tc.get())
            except ValueError:
                e["trail_i"] = 4
            e["map_up"] = self.v_mapup.get()
            e["map_arrow"] = bool(self.v_maparrow.get())
            e["map_cam"] = self.v_mapcam.get()
            e["map_zoom"] = bool(self.v_mapzoom.get())
            e["att_inv_pit"] = bool(self.v_attinvpit.get())
            e["att_inv_rol"] = bool(self.v_attinvrol.get())
            e["map_ruler"] = bool(vars_["map_ruler"].get())
            e["map_vec"] = bool(vars_["map_vec"].get())
            e["map_wp"] = bool(vars_["map_wp"].get())
            e["event"] = bool(vars_["event"].get())
            e["vignette"] = round(float(v_vg.get()), 2)
            e["corner"] = bool(vars_["corner"].get())
            e["size"] = v_size.get()
            e["fill"] = 0 if v_fill.get() == "补黑边" else 1
            e["portrait"] = bool(vars_["portrait"].get())
            e["hud_pos"] = {"底部": "bottom", "居中": "center", "顶部": "top"}.get(
                vars_["hud_pos"].get(), "bottom")
            e["obj"] = v_obj.get().strip()
            for _k, (_vk, _vb) in (vars_.get("__cal__") or {}).items():
                try:
                    e[_k + "_k"] = float(_vk.get())
                except Exception:
                    e[_k + "_k"] = 1.0
                try:
                    e[_k + "_b"] = float(_vb.get())
                except Exception:
                    e[_k + "_b"] = 0.0
            # 面板/柱状图/文字的坐标和字号：写进当前生效的版式（横屏 layout / 竖屏 layout_p）
            try:
                Lc = self.eff_layout()
                for _k in ("tele_x", "tele_y", "tele_size", "bar_x", "bar_y",
                           "text_x", "text_y", "text_size", "text_anchor"):
                    if _k in e:
                        Lc[_k] = float(e[_k])
            except Exception:
                pass
            self._safe_save()
            self.log("高级效果：面板 %s ｜ 柱状图 %s ｜ 文字 %s ｜ 画幅 %s ｜ 暗角 %.1f ｜ 圆角 %s ｜ 模型 %s"
                     % ("开" if e["tele"] else "关", "开" if e["bars"] else "关",
                        e["text"] or "无", e["size"], e["vignette"],
                        "开" if e["corner"] else "关", e["obj"] or "内置"))
            dlg.destroy()

        ttk.Button(bar, text="确定", style="Go.TButton", command=on_ok).pack(side="right")
        ttk.Button(bar, text="取消", command=dlg.destroy).pack(side="right", padx=S_(8))

        dlg.update_idletasks()
        try:
            x = self.winfo_rootx() + (self.winfo_width() - dlg.winfo_width()) // 2
            y = self.winfo_rooty() + (self.winfo_height() - dlg.winfo_height()) // 3
            dlg.geometry("+%d+%d" % (max(0, x), max(0, y)))
        except Exception:
            pass
        dlg.grab_set()

    # ------------------------------------------------------------ 配置
    def _load_cfg(self):
        try:
            with open(CFG, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _load_values(self):
        c = self.cfg
        self.v_bbl.set(c.get("bbl", ""))
        self.v_video.set(c.get("video", ""))
        self.v_start.set(str(c.get("start", 0)))
        self.v_seg.set(str(c.get("seg", 0)))
        self.v_dur.set(str(c.get("dur", 30)))
        label = c.get("crf_label", CRF_CHOICES[1][0])
        self.v_crf.set(label if label in [x[0] for x in CRF_CHOICES] else CRF_CHOICES[1][0])
        self.v_map.set(bool(c.get("map", True)))
        self.v_att.set(bool(c.get("att", True)))
        self.v_auto.set(bool(c.get("auto", True)))
        self.v_lag.set(str(c.get("lag", -0.97)))
        self.v_out.set(c.get("out", OUT_DEFAULT))
        base = c.get("base", BASE_ONLINE)
        self.v_base.set(base if base in (BASE_ONLINE, BASE_PHOTO) else BASE_ONLINE)
        self.v_photo.set(c.get("photo", ""))
        self.photo_cal = dict(c.get("photo_cal") or {"center": "", "mpp": "", "rotate": ""})
        lay = dict(LAYOUT0)
        lay.update({k: float(v) for k, v in (c.get("layout") or {}).items() if k in lay})
        self.layout = lay
        # 竖屏版式单独存一份；没有就等第一次进竖屏时按预设现生
        lp = c.get("layout_p")
        if isinstance(lp, dict) and lp:
            p = dict(lay)
            for k, v in lp.items():
                try:
                    p[k] = float(v)
                except (TypeError, ValueError):
                    continue
            self.layout_p = p
        else:
            self.layout_p = None
        self.v_mask.set(bool(c.get("mask", lay.get("mask_on", 0) >= 0.5)))
        self.v_mask2.set(bool(c.get("mask2", lay.get("mask2_on", 0) >= 0.5)))
        self.v_mode.set("美国手（MODE2）" if lay.get("stick_mode", 2) >= 1.5
                        else "日本手（MODE1）")
        self.v_grad.set(bool(c.get("grad", False)))
        for key, var in self.v_inv.items():
            var.set(bool((c.get("inv") or {}).get(key, False)))
        st = c.get("stick") or {}
        self.v_style.set(st.get("style", "经典圆盘"))
        try:
            self.v_alpha.set(float(st.get("alpha", 1.0)))
        except Exception:
            self.v_alpha.set(1.0)
        self.v_fcol.set(st.get("fcol", "浅灰"))
        self.v_bcol.set(st.get("bcol", "红点"))
        self.v_us.set(bool(st.get("us", False)))
        try:
            self.v_mapup.set(str(self.extra.get("map_up", "正北朝上")))
            self.v_maparrow.set(bool(self.extra.get("map_arrow", True)))
            self.v_mapcam.set(str(self.extra.get("map_cam", "位置居中（跟随）")))
            self.v_mapzoom.set(bool(self.extra.get("map_zoom", True)))
            self.v_attinvpit.set(bool(self.extra.get("att_inv_pit", True)))
            self.v_attinvrol.set(bool(self.extra.get("att_inv_rol", False)))
        except Exception:
            pass
        try:
            self.v_attmode.set(str(self.extra.get("att_mode", "积分（稳）")))
            self.v_attyaw.set("%d°" % int(self.extra.get("att_yaw", 0)))
            self.v_stickdir.set(str(self.extra.get("stick_dir", "拉杆=抬头（标准）")))
        except Exception:
            pass
        ex = c.get("extra") or {}
        if isinstance(ex, dict):
            self.extra.update({k: v for k, v in ex.items() if k in self.extra})
            # 老配置：面板坐标只存在 extra 里，补进版式（否则会被版式默认值盖掉）
            _raw_layout = c.get("layout") or {}
            for _k in ("tele_x", "tele_y", "tele_size", "bar_x", "bar_y",
                       "text_x", "text_y", "text_size", "text_anchor"):
                if _k not in _raw_layout and _k in self.extra:
                    try:
                        self.layout[_k] = float(self.extra[_k])
                    except (TypeError, ValueError):
                        pass
            if not isinstance(self.extra.get("text"), str):
                self.extra["text"] = ""
        shp = ["矩形", "圆角矩形", "椭圆"]
        if st.get("mapshape") in shp:
            self.v_mapshape.set(st.get("mapshape"))
        if st.get("kshape") in shp:
            self.v_kshape.set(st.get("kshape"))
        try:
            self.v_mapalpha.set(float(st.get("mapalpha", 1.0)))
            self.v_kalpha.set(float(st.get("kalpha", 1.0)))
        except Exception:
            pass
        if self.photo_cal.get("mpp") or self.photo_cal.get("center"):
            self.l_cal.configure(text="标定：中心 %s　米/像素 %s　旋转 %s°"
                                 % (self.photo_cal.get("center") or "轨迹中心",
                                    self.photo_cal.get("mpp") or "自动",
                                    self.photo_cal.get("rotate") or "0"))
        self._toggle_lag()
        self._toggle_base()
        if self.v_video.get():
            self.probe_video(self.v_video.get())

    def _safe_save(self):
        try:
            fn = getattr(self, "save_cfg", None)
            if callable(fn):
                fn()
        except Exception:
            pass

    def save_cfg(self):
        try:
            with open(CFG, "w", encoding="utf-8") as f:
                json.dump(dict(bbl=self.v_bbl.get(), video=self.v_video.get(),
                               start=self._start(), dur=self._dur(), seg=self._seg(),
                               crf_label=self.v_crf.get(),
                               map=self.v_map.get(), att=self.v_att.get(),
                               auto=self.v_auto.get(), lag=self.v_lag.get(),
                               out=self.v_out.get(), base=self.v_base.get(),
                               photo=self.v_photo.get(), photo_cal=self.photo_cal,
                               layout=dict(self.layout, stick_mode=float(self._mode())),
                               layout_p=(dict(self.layout_p, stick_mode=float(self._mode()))
                                         if isinstance(self.layout_p, dict) else None),
                               mask=self.v_mask.get(), mask2=self.v_mask2.get(),
                               grad=self.v_grad.get(),
                               inv={k: v.get() for k, v in self.v_inv.items()},
                               extra=self.extra,
                               stick=dict(style=self.v_style.get(),
                                          alpha=round(float(self.v_alpha.get()), 2),
                                          fcol=self.v_fcol.get(), bcol=self.v_bcol.get(),
                                          us=self.v_us.get(),
                                          mapshape=self.v_mapshape.get(),
                                          mapalpha=round(float(self.v_mapalpha.get()), 2),
                                          kshape=self.v_kshape.get(),
                                          kalpha=round(float(self.v_kalpha.get()), 2))),
                          f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def _start(self):
        try:
            return float(self.v_start.get())
        except ValueError:
            return 0.0

    def _seg(self):
        try:
            return max(0, int(float(self.v_seg.get())))
        except ValueError:
            return 0

    def _dur(self):
        try:
            return max(1.0, float(self.v_dur.get()))
        except ValueError:
            return 30.0

    def crf(self):
        for label, val in CRF_CHOICES:
            if label == self.v_crf.get():
                return val
        return 24

    def _toggle_lag(self):
        self.e_lag.configure(state="disabled" if self.v_auto.get() else "normal")

    # ------------------------------------------------------------ 选文件
    def pick_bbl(self):
        p = filedialog.askopenfilename(
            title="选黑匣子日志",
            filetypes=[("黑匣子", "*.bbl *.bfl *.BBL *.BFL"), ("所有文件", "*.*")])
        if p:
            self.v_bbl.set(p)
            self.log("黑匣子：%s" % p)

    def pick_video(self):
        p = filedialog.askopenfilename(
            title="选眼镜视频",
            filetypes=[("视频", "*.MOV *.mov *.mp4 *.MP4 *.mkv *.avi"), ("所有文件", "*.*")])
        if p:
            self.v_video.set(p)
            self.log("视频：%s" % p)
            self.probe_video(p)

    def pick_out(self):
        p = filedialog.askdirectory(title="选输出目录", initialdir=self.v_out.get() or OUT_DEFAULT)
        if p:
            self.v_out.set(p)

    def probe_video(self, path):
        def work():
            try:
                p = subprocess.run([FFMPEG, "-hide_banner", "-i", path], capture_output=True,
                                   creationflags=NO_WINDOW)
                s = p.stderr.decode("utf-8", "replace")
                m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", s)
                d = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None
                m2 = re.search(r"Video:.*?(\d{3,4})x(\d{3,4})", s)
                wh = "%sx%s" % (m2.group(1), m2.group(2)) if m2 else ""
                if d:
                    self.q.put(("video", "时长 %d 分 %.0f 秒　%s" % (int(d // 60), d % 60, wh)))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ 日志
    def log(self, s):
        line = s.rstrip() + chr(10)
        hist = self.__dict__.get('_loghist')
        if hist is None:
            self._loghist = hist = []
        hist.append(line)
        if len(hist) > 800:
            del hist[:200]
        try:
            self.txt.configure(state='normal')
            self.txt.insert('end', line)
            self.txt.see('end')
            self.txt.configure(state='disabled')
        except Exception:
            pass
        win = self.__dict__.get('_logwin')
        if win is not None:
            try:
                if win.winfo_exists():
                    t = self.__dict__.get('_logwin_txt')
                    if t is not None:
                        t.configure(state='normal')
                        t.insert('end', line)
                        t.see('end')
                        t.configure(state='disabled')
            except Exception:
                pass

    def status(self, s):
        self.l_status.configure(text=s)

    def _pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.log(val)
                    self._progress_from(val)
                elif kind == "video":
                    self.l_video.configure(text=val)
                elif kind == "done":
                    self._finish(val)
                elif kind == "status":
                    self.status(val)
        except queue.Empty:
            pass
        self._tick()          # 转圈动画 + 计时
        self.after(120, self._pump)

    def _tick(self):
        """运行中：转圈动画 + 已用秒数，一眼能看出程序在跑"""
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        running = getattr(self, "proc", None) is not None and self.proc.poll() is None
        if running:
            i = getattr(self, "_spin_i", 0) + 1
            self._spin_i = i
            t0 = getattr(self, "_t_run", None)
            secs = int(time.time() - t0) if t0 else 0
            try:
                self.l_spin.configure(text=frames[i % len(frames)])
                self.l_prog.configure(text="运行中 %ds  进度 %d%%" % (secs, int(self.pb["value"])))
            except Exception:
                pass
        else:
            try:
                if getattr(self, "_spin_i", 0):
                    self._spin_i = 0
                    self.l_spin.configure(text="")
            except Exception:
                pass

    def _progress_from(self, line):
        m = re.search(r"渲染 (\d+)/(\d+)", line)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            self.pb["value"] = 25 + 50.0 * a / max(1, b)
            return
        for kw, val in (("解码", 5), ("时间差", 12), ("算姿态", 22), ("卫星底图", 22),
                        ("航拍图", 22), ("编码", 78), ("合成", 88)):
            if kw in line:
                self.pb["value"] = max(self.pb["value"], val)

    # ------------------------------------------------------------ 跑命令
    def _args(self, preview=False, layers=None):
        a = [PYEXE, APP, self.v_bbl.get(), self.v_video.get(),
             "--vstart", "%.3f" % self._start(),
             "--dur", "%.3f" % self._dur(),
             "--crf", str(self.crf()),
             "--out", self.v_out.get()]
        if preview:
            a.append("--preview")
        elif layers:
            # 切图层时两层都要，元素显不显示在编辑器里决定
            a += ["--layers", layers]
        else:
            if not self.v_map.get():
                a.append("--no-map")
            if not self.v_att.get():
                a.append("--no-att")
        if not self.v_auto.get():
            try:
                a += ["--lag", "%.2f" % float(self.v_lag.get())]
            except ValueError:
                pass
        if self.v_base.get() == BASE_PHOTO and self.v_photo.get():
            a += ["--map-image", self.v_photo.get()]
            c = self.photo_cal.get("center", "").strip()
            if c:
                a += ["--map-center", c]
            if self.photo_cal.get("mpp", "").strip():
                a += ["--map-mpp", self.photo_cal["mpp"].strip()]
            if self.photo_cal.get("rotate", "").strip():
                a += ["--map-rotate", self.photo_cal["rotate"].strip()]
        if self._seg() > 0:
            a += ["--seg", str(self._seg())]
        L = self.eff_layout()          # 竖屏时用竖屏版式
        a += ["--stick-mode", str(self._mode()),
              "--lstick-x", "%g" % L.get("ls_dx", 0), "--lstick-y", "%g" % L.get("ls_dy", 0),
              "--lstick-scale", "%g" % L.get("ls_s", 1),
              "--rstick-x", "%g" % L.get("rs_dx", 0), "--rstick-y", "%g" % L.get("rs_dy", 0),
              "--rstick-scale", "%g" % L.get("rs_s", 1),
              "--att-x", "%g" % L.get("att_dx", 0.0), "--att-y", "%g" % L.get("att_dy", 0.0),
              "--att-scale", "%g" % L.get("att_s", 1.0),
              "--map-x", "%g" % L.get("map_dx", 26), "--map-y", "%g" % L.get("map_dy", 20),
              "--map-scale", "%g" % L.get("map_s", 1)]
        # 用 --mask=... 的等号写法：坐标可能是负数（拖到画面外），
        # 写成 --mask -50,... 会被 argparse 当成选项而报 expected one argument
        if self.v_mask.get():
            a.append("--mask=%g,%g,%g,%g" % (L.get("mask_x", 0), L.get("mask_y", 0),
                                             L.get("mask_w", 1920), L.get("mask_h", 46)))
        if self.v_mask2.get():
            a.append("--mask2=%g,%g,%g,%g" % (L.get("mask2_x", 0), L.get("mask2_y", 250),
                                              L.get("mask2_w", 1920), L.get("mask2_h", 60)))
        if self.v_grad.get():
            a.append("--grad")
        for key, flag in (("thr", "--inv-thr"), ("rol", "--inv-rol"),
                          ("pit", "--inv-pit"), ("yaw", "--inv-yaw")):
            if self.inv_flags().get(key):
                a.append(flag)
        # 摇杆样式
        styles = bbrender_styles()
        st = styles.index(self.v_style.get()) if self.v_style.get() in styles else 0
        a += ["--stick-style", str(st)]
        a += ["--stick-alpha", "%.2f" % round(float(self.v_alpha.get()), 2)]
        fnames = bbrender_color_names()
        bnames = bbrender_ball_names()
        fi = fnames.index(self.v_fcol.get()) if self.v_fcol.get() in fnames else 0
        bi = bnames.index(self.v_bcol.get()) if self.v_bcol.get() in bnames else 0
        a += ["--frame-color", str(fi), "--ball-color", str(bi)]
        # 每个元素单独的颜色（元素位置编辑器里可改；-1 = 跟框线颜色）
        def _ci(key, dflt=fi):
            try:
                v = int(round(float(L.get(key, -1.0))))
            except Exception:
                v = -1
            return str(v if v >= 0 else dflt)
        a += ["--tele-color", _ci("tele_i"), "--bar-color", _ci("bar_i"),
              "--text-color", _ci("text_i"),
              "--map-trail-color", _ci("map_trail_i", 5),
              "--map-arrow-color", _ci("map_arrow_i", 3)]
        if self.v_us.get():
            a.append("--show-us")
        e = self.extra
        a += ["--extra-dx", "%.0f" % float(L.get("extra_dx", 0.0)),
              "--extra-dy", "%.0f" % float(L.get("extra_dy", 0.0))]
        a += ["--trail-len", "%.0f" % e.get("trail_len", 6),
              "--trail-color", str(int(e.get("trail_i", 4))),
              "--trail-w", "%.2f" % e.get("trail_w", 1.0)]
        def _pv(key, default):
            """面板/柱状图/文字的坐标：版式里改过的优先（元素位置里拖的就是它）"""
            try:
                return float(L.get(key, default))
            except (TypeError, ValueError):
                return float(default)
        if e.get("tele"):
            a += ["--tele", "--tele-x", "%.0f" % _pv("tele_x", e.get("tele_x", 60)),
                  "--tele-y", "%.0f" % _pv("tele_y", e.get("tele_y", 380)),
                  "--tele-size", "%.0f" % _pv("tele_size", e.get("tele_size", 30)),
                  "--tele-alpha", "%.2f" % round(float(L.get("tele_alpha", 0.9)), 2)]
        if e.get("bars"):
            a += ["--bars", "--bar-x", "%.0f" % _pv("bar_x", e.get("bar_x", 60)),
                  "--bar-y", "%.0f" % _pv("bar_y", e.get("bar_y", 760)),
                  "--bar-alpha", "%.2f" % round(float(L.get("bar_alpha", 0.9)), 2)]
        if (e.get("text") or "").strip():
            a += ["--text", e["text"], "--text-x", "%.0f" % _pv("text_x", e.get("text_x", 960)),
                  "--text-y", "%.0f" % _pv("text_y", e.get("text_y", 60)),
                  "--text-size", "%.0f" % _pv("text_size", e.get("text_size", 44)),
                  "--text-anchor", str(int(_pv("text_anchor", e.get("text_anchor", 1)))),
                  "--text-alpha", "%.2f" % round(float(L.get("text_alpha", 0.9)), 2)]
        if e.get("map_ruler"):
            a.append("--map-ruler")
        if e.get("map_vec"):
            a.append("--map-vec")
        if e.get("map_wp"):
            a.append("--map-wp")
        a += ["--map-up", "1" if self.v_mapup.get() == "航向朝上" else "0"]
        for _k in ("vbat", "amp", "alt", "spd"):
            a += ["--%s-k" % _k, "%.4f" % float(self.extra.get(_k + "_k", 1.0)),
                  "--%s-b" % _k, "%.3f" % float(self.extra.get(_k + "_b", 0.0))]
        a += ["--inv-att-pit", "1" if self.v_attinvpit.get() else "0",
              "--inv-att-rol", "1" if self.v_attinvrol.get() else "0"]
        a += ["--map-zoom", "1" if self.v_mapzoom.get() else "0"]
        _cam = self.v_mapcam.get()
        a += ["--map-cam", "3" if "位置" in _cam else ("2" if "轨迹" in _cam else "1")]
        if self.v_maparrow.get():
            a.append("--map-arrow")
        if e.get("event"):
            a.append("--event")
        if float(e.get("vignette", 0)) > 0.05:
            a += ["--vignette", "%.2f" % e["vignette"]]
        if e.get("corner"):
            a.append("--corner")
        # 姿态来源 / 机头偏置 / 摇杆方向
        try:
            am = 0 if "积分" in self.v_attmode.get() else 1
            ay = int(str(self.v_attyaw.get()).replace("°", "") or 0)
            e["att_mode"] = self.v_attmode.get()
            e["att_yaw"] = ay
            e["stick_dir"] = self.v_stickdir.get()
        except Exception:
            am, ay = 0, 0
        a += ["--att-mode", str(am), "--att-yaw", str(ay)]
        if "反向" in self.v_stickdir.get() and not self.v_inv["pit"].get():
            a.append("--inv-pit")
        a += ["--size", e.get("size", "16:9"), "--fill", str(int(e.get("fill", 0)))]
        if e.get("portrait"):
            a += ["--portrait", "--hud-pos", e.get("hud_pos", "bottom"),
                  "--portrait-mode", e.get("portrait_mode", "native")]
        if (e.get("obj") or "").strip():
            a += ["--obj", e["obj"]]
        shp = ["矩形", "圆角矩形", "椭圆"]
        a += ["--map-shape", str(shp.index(self.v_mapshape.get()) if self.v_mapshape.get() in shp else 0),
              "--map-alpha", "%.2f" % round(float(self.v_mapalpha.get()), 2)]
        a += ["--mask-shape", str(shp.index(self.v_kshape.get()) if self.v_kshape.get() in shp else 0),
              "--mask-alpha", "%.2f" % round(float(self.v_kalpha.get()), 2)]
        return a

    def inv_flags(self):
        try:
            return {k: bool(v.get()) for k, v in self.v_inv.items()}
        except Exception:
            return {}

    def _check(self):
        if not self.v_bbl.get() or not os.path.exists(self.v_bbl.get()):
            messagebox.showwarning("还差一步", "先选黑匣子日志（.bbl）")
            return False
        if not self.v_video.get() or not os.path.exists(self.v_video.get()):
            messagebox.showwarning("还差一步", "先选眼镜视频（.MOV / .mp4）")
            return False
        if self.v_base.get() == BASE_PHOTO and not (self.v_photo.get()
                                                    and os.path.exists(self.v_photo.get())):
            messagebox.showwarning("还差一步", "选了「自定义航拍图」但没选图片")
            return False
        return True

    def _run(self, args, tag):
        if self.proc:
            messagebox.showinfo("正在跑", "上一个任务还没结束")
            return
        self.save_cfg()
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")
        self.log("摇杆样式：%s ｜ 透明度 %.2f ｜ 框线 %s ｜ 点 %s ｜ us %s"
                 % (self.v_style.get(), float(self.v_alpha.get()),
                    self.v_fcol.get(), self.v_bcol.get(), "开" if self.v_us.get() else "关"))
        self.log("小地图：%s 透明度 %.2f ｜ 黑块：%s 透明度 %.2f"
                 % (self.v_mapshape.get(), float(self.v_mapalpha.get()),
                    self.v_kshape.get(), float(self.v_kalpha.get())))
        inv = [k for k, v in self.inv_flags().items() if v]
        self.log("通道反向：%s" % ("、".join(inv) if inv else "无"))
        self.log("这次的元素：卫星小地图 %s ｜ 3D 姿态 %s ｜ 黑块1 %s ｜ 黑块2 %s ｜ 顶部压暗 %s"
                 % ("开" if self.v_map.get() else "关", "开" if self.v_att.get() else "关",
                    "开" if self.v_mask.get() else "关", "开" if self.v_mask2.get() else "关",
                    "开" if self.v_grad.get() else "关"))
        self.log("命令：%s" % " ".join(args[2:]))
        self.pb["value"] = 0
        self._t_run = time.time()
        try:
            self.l_prog.configure(text="启动中…")
        except Exception:
            pass
        self.status("正在%s" % tag)
        for b in (self.b_go, self.b_prev):
            b.configure(state="disabled")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        try:
            self.proc = subprocess.Popen(args, cwd=HERE, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                         errors="replace", env=env, creationflags=NO_WINDOW)
        except Exception as e:
            self.proc = None
            for b in (self.b_go, self.b_prev):
                b.configure(state="normal")
            messagebox.showerror("起不来", str(e))
            return
        threading.Thread(target=self._reader, args=(self.proc, tag), daemon=True).start()

    def _reader(self, proc, tag):
        last = None
        for line in proc.stdout:
            self.q.put(("log", line.rstrip()))
            if line.strip().startswith("{"):
                last = line.strip()
        code = proc.wait()
        self.q.put(("done", (tag, code, last)))

    def _finish(self, val):
        tag, code, last = val
        self.proc = None
        for b in (self.b_go, self.b_prev):
            b.configure(state="normal")
        data = None
        if last:
            try:
                data = json.loads(last)
            except Exception:
                data = None
        if tag == "切图层":
            ok = bool(code == 0 and data and data.get("lstick") and data.get("rstick")
                      and data.get("att") and data.get("frame"))
            if ok:
                self.status("图层准备好了，打开元素位置")
                self._open_drag_editor(data)
            else:
                self.status("切图层失败（退出码 %s），看日志" % code)
                messagebox.showerror("切图层失败", "看日志最后几行。通常是日志和视频没对上，或时间超出日志范围。")
            return
        if tag == "预览":
            if code == 0 and data and data.get("preview"):
                self.status("预览图已生成：%s" % os.path.basename(data["preview"]))
                os.startfile(data["preview"])
            else:
                self.status("预览失败（退出码 %s），看日志" % code)
            return
        if code == 0 and data and data.get("final"):
            self.final = data["final"]
            self.pb["value"] = 100
            self.status("完成：%s" % os.path.basename(self.final))
            self.b_play.configure(state="normal")
            messagebox.showinfo("搞定", "成片已生成：\n%s\n\n绿幕 overlay 在同一目录。"
                                % os.path.basename(self.final))
        else:
            self.status("出错了（退出码 %s），看日志最后几行" % code)
            messagebox.showerror("出错了", "看下面日志的最后几行，通常是日志/视频对不上或时间超范围。")

    # ------------------------------------------------------------ 按钮
    def preview(self):
        if self._check():
            self._run(self._args(preview=True), "预览")

    def start(self):
        if self._check():
            self._run(self._args(), "生成")

    def open_out(self):
        out = self.v_out.get() or OUT_DEFAULT
        try:
            os.makedirs(out, exist_ok=True)
        except Exception as e:
            messagebox.showerror("打不开", "输出目录建不了：%s" % e)
            return
        try:
            # 有刚生成的成片就把它在资源管理器里选中，方便直接看
            if self.final and os.path.exists(self.final):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(self.final)])
            else:
                os.startfile(out)
        except Exception as e:
            messagebox.showerror("打不开", str(e))

    def play(self):
        if self.final and os.path.exists(self.final):
            os.startfile(self.final)

    def on_close(self):
        if self.proc:
            if not messagebox.askyesno("还在跑", "任务没结束，确定关掉吗？"):
                return
            try:
                self.proc.kill()
            except Exception:
                pass
        self.save_cfg()
        self.destroy()


    def uninstall_app(self):
        """打开一键卸载程序（会先把本界面关掉，方便删文件）"""
        vbs = os.path.join(HERE, "一键卸载程序.vbs")
        ps1 = os.path.join(HERE, "一键卸载.ps1")
        if not (os.path.exists(vbs) and os.path.exists(ps1)):
            messagebox.showwarning("找不到卸载程序",
                                   "这个文件夹里没有「一键卸载程序.vbs / 一键卸载.ps1」。\n"
                                   "直接用压缩包里的卸载程序，或手动删除本文件夹即可。")
            return
        if not messagebox.askyesno(
                "一键卸载",
                "会打开卸载窗口，让你勾选要删的东西（缓存、成片、pip 依赖、Python、整个程序文件夹）。\n"
                "卸载程序只删本程序自己目录里的文件，不会碰别的地方。\n\n"
                "现在关掉本界面并打开卸载程序？"):
            return
        try:
            os.startfile(vbs)
        except Exception as e:
            messagebox.showerror("打不开卸载程序", str(e))
            return
        self.destroy()

if __name__ == "__main__":
    import sys as _sys
    _sys.excepthook = _write_crash
    try:
        app = App()
        app.log("黑匣子叠加工具 v%s 启动｜Python %s" % (APP_VERSION, _sys.version.split()[0]))
        app.mainloop()
    except Exception:
        import traceback
        _write_crash(*_sys.exc_info())
        raise