#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""bboverlay / 元素位置 —— 一边拖画面里的元素、一边填精确数值

只显示主界面「画面」里勾选了的元素：没勾的不出现在这里。
两块 GPS 坐标遮盖黑块各自独立，可一键对齐。
"""
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

CARD = "#ffffff"
BG = "#eef1f5"
INK = "#111827"
SUB = "#6b7280"
ACCENT = "#1f4fd8"

CW, CH = 800, 450          # 画布像素（画布里的“画面”按 1920×1080 或 1080×1920 装）
CS = CW / 1920.0           # 画布像素 / 画面像素
FRAME_W, FRAME_H = 1920.0, 1080.0   # 当前版式的画面尺寸（竖屏时 1080×1920）

# 每个元素可单独改的颜色：key -> (名称, 颜色表, 是否允许“跟框线”)
COLOR_SPECS = (
    ("frame_i", "摇杆框线", "FRAME"),
    ("ball_i", "摇杆圆点", "BALL"),
    ("trail_i", "摇杆轨迹", "FRAME"),
    ("map_trail_i", "地图轨迹", "FRAME"),
    ("map_arrow_i", "地图箭头", "FRAME"),
    ("tele_i", "面板文字", "TEXT", True),
    ("bar_i", "柱状图", "TEXT", True),
    ("text_i", "水印文字", "TEXT", True),
)

LS_BASE = (620.0, 812.0)
RS_BASE = (1300.0, 812.0)
R_STICK = 150.0
ATT_BASE = (960.0, 800.0)
MAP_BASE = (26.0, 20.0)
MAP0 = 360.0

F_BODY = ("Microsoft YaHei UI", 10)
F_BOLD = ("Microsoft YaHei UI", 10, "bold")
F_HINT = ("Microsoft YaHei UI", 9)

# key -> (名称, 颜色, 层素材 key, 基准点, 半宽)
ELEMS = {
    "ls": ("左摇杆", "#38bdf8", "lstick", LS_BASE, 165.0),
    "rs": ("右摇杆", "#22d3ee", "rstick", RS_BASE, 165.0),
    "att": ("姿态（飞机）", "#4ade80", "att", ATT_BASE, 210.0),
    "map": ("小地图", "#fbbf24", "map", MAP_BASE, MAP0 / 2.0),
    "tele": ("数值面板", "#f472b6", "tele", (60.0, 380.0), 170.0),
    "bars": ("柱状图", "#fb923c", "bars", (60.0, 760.0), 90.0),
    "text": ("文字水印", "#c084fc", "text", (960.0, 60.0), 260.0),
}
MASKS = (("mask", "GPS 坐标遮盖 1", "#f87171"), ("mask2", "GPS 坐标遮盖 2", "#c084fc"))

# 透明度的默认值：面板/柱状图/文字切图层时烘的是 0.9，其余是 1.0
Akind = {"tele_alpha": "panel", "bar_alpha": "panel", "text_alpha": "panel"}


def _lay(key):
    """元素键 → 图层素材名（左右摇杆分别是 lstick / rstick）"""
    return {"ls": "lstick", "rs": "rstick", "att": "att", "map": "map",
            "tele": "tele", "bars": "bars", "text": "text", "extra": "extra"}.get(key, key)


class LayoutEditor(tk.Toplevel):
    def __init__(self, master, assets, layout, on_save=None, map_on=True, att_on=True,
                 mask_on=False, mask2_on=False, scale=1.0, stick_mode=2.0,
                 extra_on=False, canvas=None):
        super().__init__(master)
        self.title("元素位置")
        self.configure(bg=BG)
        self.transient(master)
        self.grab_set()
        self.on_save = on_save
        self.S = scale
        self.L = dict(layout)
        # 画布随版式走：横屏 1920×1080（800×450），竖屏 1080×1920（427×760）
        global CW, CH, CS, FRAME_W, FRAME_H
        FRAME_W, FRAME_H = (float(canvas[0]), float(canvas[1])) if canvas else (1920.0, 1080.0)
        if FRAME_W > FRAME_H:            # 横屏 1920×1080 → 800×450
            _k = min(800.0 / FRAME_W, 470.0 / FRAME_H)
        else:                             # 竖屏 1080×1920 → 675×1200（再高窗口就出屏）
            _k = min(1100.0 / FRAME_W, 1200.0 / FRAME_H)
        CW = int(round(FRAME_W * _k))
        CH = int(round(FRAME_H * _k))
        CS = CW / FRAME_W
        self.portrait = FRAME_H > FRAME_W
        # 每个元素「自然位置」（dx=0 时的画面坐标）：
        #   - 竖屏版式由 bbrender.portrait_layout 重新排过，基准点也跟着换
        #   - 小地图位置本身就是绝对值（map_dx 就是左上角），基准取 0
        self.bases = {k: v[3] for k, v in ELEMS.items()}
        self.bases["map"] = (0.0, 0.0)
        if self.portrait:
            # 竖屏下面板/柱状图/文字是另一套绝对坐标（bbrender.portrait_layout 预设）；
            # 摇杆/姿态的基准点不变——它们的 dx 本来就是相对 620/1300/960 算的
            self.bases.update(tele=(620.0, 300.0), bars=(40.0, 1560.0),
                              text=(540.0, 120.0))
        # 竖屏：图层烘在「预设位置」（270/810/540…），而 dx 是相对 620/1300/960 的。
        # 这里记下预设偏移，画图层时把用户拖的那部分单独叠上去，避免位移算两遍。
        self.pd = {k: (0.0, 0.0) for k in ELEMS}
        if self.portrait:
            try:
                import bbrender as BR
                P = BR.portrait_layout(dict(BR.LAYOUT))
                for k in ("ls", "rs", "att"):
                    self.pd[k] = (float(P[k + "_dx"]) - float(BR.LAYOUT[k + "_dx"]),
                                  float(P[k + "_dy"]) - float(BR.LAYOUT[k + "_dy"]))
            except Exception:
                pass
        # 旧版按「比例换算」用的烘焙值；v3.6.2 起 _with_alpha 改成绝对值换算，不再依赖它
        self._alpha_base = {
            "stick": float(self.L.get("stick_alpha", 1.0) or 1.0),
            "map": float(self.L.get("map_alpha", 1.0) or 1.0),
            "extra": float(self.L.get("tele_alpha", 1.0) or 1.0),
            "tele": float(self.L.get("tele_alpha", 1.0) or 1.0),
            "bars": float(self.L.get("bar_alpha", 1.0) or 1.0),
            "text": float(self.L.get("text_alpha", 1.0) or 1.0),
            "mask": float(self.L.get("mask_alpha", 1.0) or 1.0),
            "mask2": float(self.L.get("mask2_alpha", 1.0) or 1.0),
        }
        self.on = {"att": bool(att_on), "map": bool(map_on),
                   "mask": bool(mask_on), "mask2": bool(mask2_on),
                   "extra": bool(extra_on)}
        self.sel = None
        self.drag = None
        self.resize = False
        self._photo = None
        self._updating = False
        self.vars = {}
        self.mode = 2 if float(self.L.get("stick_mode", stick_mode) or 2) >= 1.5 else 1

        def load(key):
            return Image.open(assets[key]).convert("RGBA").resize((CW, CH), Image.LANCZOS)

        # 背景帧：视频帧是横的 16:9，竖屏版式时先按 9:16 居中裁一刀，
        # 这样画布里的背景和成片的竖屏构图一致（不然整张横图会被压扁）
        _f = Image.open(assets["frame"]).convert("RGB")
        if self.portrait and _f.size[0] > _f.size[1]:
            _tw, _th = (FRAME_W, FRAME_H)
            _r = max(_tw / _f.size[0], _th / _f.size[1])
            _f2 = _f.resize((int(round(_f.size[0] * _r)), int(round(_f.size[1] * _r))),
                            Image.LANCZOS)
            _x = (_f2.size[0] - _tw) // 2
            _y = (_f2.size[1] - _th) // 2
            _f = _f2.crop((_x, _y, _x + int(_tw), _y + int(_th)))
        self.bg = _f.resize((CW, CH), Image.LANCZOS)
        # 图层的键统一用「素材名」（lstick/rstick/att/map/tele/bars/text），
        # 和 _group_layers 的映射对得上；元素键走 _lay(key) 转一下
        self.layers = {}
        for k, v in ELEMS.items():
            if not self.on.get(k, True):
                continue
            try:
                self.layers[v[2]] = load(v[2])
            except Exception:
                pass
        # 只要有对应图层就显示/可拖
        for _k in ("tele", "bars", "text", "extra"):
            if _k in self.layers:
                self.on[_k] = True

        # 透明度键初始化成图层里烘出来的真实值：面板/柱状图是 0.9，摇杆实际能到 ~0.47
        # （圆盘底色是半透明的）。这样滑条一打开就是所见即所得，不会「滑条 100% 画面只有 90%」。
        for _k in ("ls", "rs", "att", "map", "tele", "bars", "text"):
            if _k not in self.layers and _lay(_k) not in self.layers:
                continue
            _ak = self._alpha_key(_k)
            if _ak is None or _k in ("mask", "mask2"):
                continue
            try:
                _baked = self._baked_alpha(_k)
                _cur = float(self.L.get(_ak, 1.0))
                # 已经是明显调过的值（<0.5）就保留用户设置；否则按图层真实值初始化
                self.L[_ak] = round(_cur if _cur < 0.5 else _baked, 3)
            except Exception:
                pass

        self._build()
        self._sync_vars()
        self._sync_colors()
        self.redraw()
        # 窗口按内容定尺寸并居中到屏幕：不设的话右侧数值区会被内容请求撑到屏幕外，
        # 截图/录屏里就只剩左边一截（画布被裁、底色发黑）
        try:
            self.update_idletasks()
            w = min(self.winfo_reqwidth() + self.S * 8, self.winfo_screenwidth() - 20)
            h = min(self.winfo_reqheight() + self.S * 8, self.winfo_screenheight() - 40)
            x = max(10, (self.winfo_screenwidth() - w) // 2)
            y = max(10, (self.winfo_screenheight() - h) // 2 - 20)
            self.geometry("%dx%d+%d+%d" % (w, h, x, y))
        except Exception:
            pass

    # ------------------------------------------------------------ 界面
    def _visible_keys(self):
        keys = ["ls", "rs"]
        if self.on["att"]:
            keys.append("att")
        if self.on["map"]:
            keys.append("map")
        for k in ("tele", "bars", "text", "extra"):
            if self.on.get(k) and k in self.layers:
                keys.append(k)
        return keys

    def _build(self):
        top = ttk.Frame(self, padding=(self.S * 12, self.S * 8))
        top.pack(fill="x")
        names = [ELEMS[k][0] for k in self._visible_keys()]
        names += [lab for key, lab, _c in MASKS if self.on.get(key)]
        ttk.Label(top, text="显示：" + "、".join(names) + "　（没勾的元素请回主界面「画面」里勾选）",
                  background="#eef1f5", foreground=SUB, font=F_HINT).pack(side="left")
        ttk.Label(top, text="摇杆手别：%s" % ("美国手 MODE2" if self.mode == 2 else "日本手 MODE1"),
                  background="#eef1f5", foreground=SUB, font=F_HINT).pack(side="right")

        # 底部按钮栏先钉在底部，保证永远可见
        bar = ttk.Frame(self, padding=(self.S * 12, self.S * 8))
        bar.pack(side="bottom", fill="x")

        body = ttk.Frame(self, padding=(self.S * 12, 0))
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body, style="Card.TFrame", padding=self.S * 8)
        left.pack(side="left", anchor="n")
        self.canvas = tk.Canvas(left, width=CW, height=CH, highlightthickness=1,
                                highlightbackground="#9aa3af", cursor="hand2")
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self._down)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._up)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.bind("<Left>", lambda e: self._nudge(-1, 0, e))
        self.bind("<Right>", lambda e: self._nudge(1, 0, e))
        self.bind("<Up>", lambda e: self._nudge(0, -1, e))
        self.bind("<Down>", lambda e: self._nudge(0, 1, e))
        ttk.Label(left, text="拖元素改位置，滚轮改大小，方向键微调（按住 Shift 更细），黑块拖右下角改宽高",
                  background=CARD, foreground=SUB, font=F_HINT).pack(anchor="w", pady=(self.S * 6, 0))

        # 右侧数值区可滚动，窗口不高时也不会把下面的设置藏掉
        right_outer = ttk.Frame(body, style="Card.TFrame", padding=self.S * 6)
        right_outer.pack(side="left", fill="both", expand=True, padx=(self.S * 10, 0))
        self._rcv = tk.Canvas(right_outer, highlightthickness=0, bg=CARD, width=self.S * 320)
        _rsb = ttk.Scrollbar(right_outer, orient="vertical", command=self._rcv.yview)
        self._rcv.configure(yscrollcommand=_rsb.set)
        _rsb.pack(side="right", fill="y")
        self._rcv.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(self._rcv, style="Card.TFrame", padding=self.S * 4)
        self._rwin = self._rcv.create_window((0, 0), window=right, anchor="nw")
        right.bind("<Configure>",
                   lambda e: self._rcv.configure(scrollregion=self._rcv.bbox("all")))
        self._rcv.bind("<Configure>",
                       lambda e: self._rcv.itemconfigure(self._rwin, width=e.width))
        self._rcv.bind("<MouseWheel>",
                       lambda e: self._rcv.yview_scroll(int(-e.delta / 120), "units"))
        ttk.Label(right, text="也可以直接填数字（改完立刻生效）",
                  style="Card.TLabel", font=F_HINT).pack(anchor="w", pady=(0, self.S * 4))
        grid = ttk.Frame(right, style="Card.TFrame")
        grid.pack(fill="x")
        row = 0

        def add_section(title, items):
            nonlocal row
            ttk.Label(grid, text=title, style="Card.TLabel", font=F_BOLD, foreground=ACCENT).grid(
                row=row, column=0, columnspan=3, sticky="w", pady=(self.S * 6, self.S * 2))
            row += 1
            for label, key, kind in items:
                ttk.Label(grid, text=label, style="Card.TLabel", font=F_HINT).grid(
                    row=row, column=0, sticky="w", padx=(self.S * 10, 0))
                v = tk.StringVar()
                ttk.Entry(grid, textvariable=v, width=7, justify="center",
                          font=F_HINT).grid(row=row, column=1, sticky="w",
                                            padx=self.S * 6, pady=1)
                ttk.Label(grid, text="%" if kind == "pct" else "像素",
                          style="Hint.TLabel").grid(row=row, column=2, sticky="w")
                v.trace_add("write", lambda *a, k=key, kk=kind: self._typed(k, kk))
                self.vars[key] = (v, kind)
                row += 1

        for key in self._visible_keys():
            if key == "tele":
                add_section("数值面板", [("左右偏移", "tele_dx", "px"), ("上下偏移", "tele_dy", "px"),
                                     ("缩放", "tele_s", "pct"), ("字号", "tele_size", "px")])
            elif key == "bars":
                add_section("柱状图", [("左右偏移", "bar_dx", "px"), ("上下偏移", "bar_dy", "px"),
                                    ("缩放", "bar_s", "pct")])
            elif key == "text":
                add_section("文字水印", [("左右偏移", "text_dx", "px"), ("上下偏移", "text_dy", "px"),
                                     ("缩放", "text_s", "pct"), ("字号", "text_size", "px")])
            elif key == "ls":
                add_section("左摇杆", [("左右偏移", "ls_dx", "px"), ("上下偏移", "ls_dy", "px"),
                                   ("缩放", "ls_s", "pct")])
            elif key == "rs":
                add_section("右摇杆", [("左右偏移", "rs_dx", "px"), ("上下偏移", "rs_dy", "px"),
                                   ("缩放", "rs_s", "pct")])
            elif key == "att":
                add_section("姿态（飞机）", [("左右偏移", "att_dx", "px"), ("上下偏移", "att_dy", "px"),
                                      ("缩放", "att_s", "pct")])
            elif key == "map":
                add_section("小地图", [("左右位置", "map_dx", "px"), ("上下位置", "map_dy", "px"),
                                   ("缩放", "map_s", "pct")])
        for key, lab, _c in MASKS:
            if self.on.get(key):
                add_section(lab, [("左侧", key + "_x", "px"), ("顶部", key + "_y", "px"),
                                  ("宽度", key + "_w", "px"), ("高度", key + "_h", "px")])

        # ---- 每个元素单独改颜色（不再只靠「高级效果」里一个总颜色）----
        ttk.Label(right, text="颜色（每个元素单独改）", style="Card.TLabel",
                  font=F_BOLD, foreground=ACCENT).pack(anchor="w", pady=(self.S * 10, self.S * 2))
        cbox = ttk.Frame(right, style="Card.TFrame")
        cbox.pack(fill="x")
        self.color_vars = {}
        for spec in COLOR_SPECS:
            key, label, pal = spec[0], spec[1], spec[2]
            allow_follow = len(spec) > 3
            rowf = ttk.Frame(cbox, style="Card.TFrame")
            rowf.pack(fill="x", pady=(0, self.S * 1))
            ttk.Label(rowf, text=label, style="Card.TLabel", font=F_HINT,
                      width=9).pack(side="left")
            names, cols = self._color_choices(pal, allow_follow)
            var = tk.StringVar()
            ttk.Combobox(rowf, textvariable=var, values=names, width=9,
                         state="readonly").pack(side="left", padx=(self.S * 4, 0))
            sw = tk.Label(rowf, text="    ", bg="#ffffff", relief="solid", bd=1)
            sw.pack(side="left", padx=(self.S * 5, 0))
            var.trace_add("write", lambda *a, k=key: self._pick_color(k))
            self.color_vars[key] = (var, sw, names, cols)
        ttk.Label(right, text="颜色是烘进图层的，改完保存后点「预览一帧」才看得到\n"
                              "（拖拽画布里显示的还是旧颜色）",
                  style="Card.TLabel", foreground=SUB, font=F_HINT).pack(anchor="w")

        ttk.Label(right, text="一键对齐", style="Card.TLabel",
                  font=F_BOLD, foreground=ACCENT).pack(anchor="w", pady=(self.S * 8, self.S * 3))
        al = ttk.Frame(right, style="Card.TFrame")
        al.pack(fill="x")
        for txt, fn in (("两杆同一水平线", lambda: self.align("y")),
                        ("两杆同一竖线", lambda: self.align("x")),
                        ("两杆左右对称", self.symmetry),
                        ("右杆等大", self.equal_size)):
            ttk.Button(al, text=txt, command=fn).pack(side="left", padx=(0, self.S * 4))
        if self.on.get("mask") and self.on.get("mask2"):
            al2 = ttk.Frame(right, style="Card.TFrame")
            al2.pack(fill="x", pady=(self.S * 4, 0))
            for txt, fn in (("黑块左边对齐", lambda: self.mask_align("x")),
                            ("黑块顶边对齐", lambda: self.mask_align("y")),
                            ("黑块同尺寸", self.mask_same_size)):
                ttk.Button(al2, text=txt, command=fn).pack(side="left", padx=(0, self.S * 4))
        ttk.Button(right, text="全部恢复默认", command=self._reset).pack(anchor="w",
                                                                pady=(self.S * 8, 0))

        self.l_info = ttk.Label(bar, text="", background="#eef1f5", foreground=SUB, font=F_HINT)
        self.l_info.pack(side="left")
        # 选中元素后可以直接输入精确坐标（画面像素 1920×1080）
        ttk.Label(bar, text="  X").pack(side="left")
        self.v_x = tk.StringVar()
        ttk.Entry(bar, textvariable=self.v_x, width=6).pack(side="left")
        ttk.Label(bar, text="Y").pack(side="left", padx=(self.S * 6, 0))
        self.v_y = tk.StringVar()
        ttk.Entry(bar, textvariable=self.v_y, width=6).pack(side="left")
        ttk.Button(bar, text="应用位置", command=self._apply_xy).pack(side="left",
                                                                  padx=(self.S * 6, 0))
        # 透明度：实时调节选中元素的透明度
        ttk.Label(bar, text="  透明").pack(side="left")
        self.v_alpha = tk.IntVar(value=100)
        self.sc_alpha = tk.Scale(bar, variable=self.v_alpha, from_=0, to=100,
                                 orient="horizontal", length=self.S * 130,
                                 showvalue=1, command=self._apply_alpha)
        self.sc_alpha.pack(side="left", padx=(self.S * 4, 0))
        ttk.Button(bar, text="保存并应用", command=self._save).pack(side="right")
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right", padx=(0, self.S * 8))

    # ------------------------------------------------------------ 数值 ⇄ 版式
    def _typed(self, key, kind):
        if self._updating:
            return
        try:
            val = float(self.vars[key][0].get())
        except ValueError:
            return
        self.L[key] = val / 100.0 if kind == "pct" else val
        self.redraw()

    def _sync_vars(self):
        self._updating = True
        try:
            for key, (var, kind) in self.vars.items():
                v = float(self.L.get(key, 1.0 if kind == "pct" else 0.0))
                txt = "%g" % round(v * 100, 1) if kind == "pct" else "%g" % round(v, 0)
                if var.get() != txt:
                    var.set(txt)
        finally:
            self._updating = False

    # ------------------------------------------------------------ 坐标
    def _base(self, key):
        """元素基准位置（extra = 旧版整体层，v3.2 起已拆成 tele/bars/text，兜底成左上角）"""
        if key in self.bases:
            return self.bases[key]
        return {"extra": (0.0, 0.0)}.get(key, LS_BASE)

    def _params(self, key):
        dx = self.L.get(key + "_dx", 0.0)
        dy = self.L.get(key + "_dy", 0.0)
        s = self.L.get(key + "_s", 1.0)
        base = self._base(key)
        return base[0] + dx, base[1] + dy, max(0.2, min(3.0, s))

    def _affine(self, key):
        cx, cy, s = self._params(key)
        bx, by = self._base(key)
        # 圆盘类元素（摇杆/小地图）不做 x 镜像：镜像会把图形和虚线框错开，
        # 看起来就是「框在这里、图在那边」
        mirror = key in ("att", "tele", "bars", "text")
        dx, dy = cx - bx, cy - by
        # 竖屏摇杆/姿态的图层烘在预设位置，图层里只要叠「用户额外拖的」那一段
        if self.portrait and key in ("ls", "rs", "att"):
            px, py = self.pd.get(key, (0.0, 0.0))
            dx, dy = dx - px, dy - py
            bx, by = bx + px, by + py
        c = (-(CS * bx * (1 - s) + CS * dx)) / s
        f = (-(CS * by * (1 - s) + CS * dy)) / s
        if mirror:
            return (1.0 / s, 0, c, 0, 1.0 / s, f)
        c = (CS * (bx * (1 - s) + dx)) / s
        return (1.0 / s, 0, c, 0, 1.0 / s, f)

    def _map_affine(self, s):
        """小地图图层烘在 MAP_BASE（26,20），编辑器里按 map_dx/map_dy（绝对值）定位"""
        s = max(0.2, min(3.0, float(s or 1.0)))
        ax, ay = MAP_BASE
        dx = float(self.L.get("map_dx", ax))
        dy = float(self.L.get("map_dy", ay))
        c = (-(CS * dx) + CS * ax * s) / s
        f = (-(CS * dy) + CS * ay * s) / s
        return (1.0 / s, 0, c, 0, 1.0 / s, f)

    def _box(self, key):
        if key in ("mask", "mask2"):
            return (CS * self.L.get(key + "_x", 0.0), CS * self.L.get(key + "_y", 110.0),
                    CS * (self.L.get(key + "_x", 0.0) + self.L.get(key + "_w", 1920.0)),
                    CS * (self.L.get(key + "_y", 110.0) + self.L.get(key + "_h", 90.0)))
        cx, cy, s = self._params(key)
        if key == "map":
            return CS * cx, CS * cy, CS * (cx + MAP0 * s), CS * (cy + MAP0 * s)
        bb = self._layer_bbox(_lay(key))
        if bb is not None and s > 0:
            # 有图层就用它的真实范围（摇杆圆盘的直径、面板的宽高各不相同）
            bx, by = self.bases[key]
            px, py = self.pd.get(key, (0.0, 0.0)) if (self.portrait and key in ("ls", "rs", "att")) else (0.0, 0.0)
            x0, y0, x1, y1 = bb
            return (CS * (cx + (x0 - bx - px) * s),
                    CS * (cy + (y0 - by - py) * s),
                    CS * (cx + (x1 - bx - px) * s),
                    CS * (cy + (y1 - by - py) * s))
        half = ELEMS[key][4] * s
        return CS * (cx - half), CS * (cy - half), CS * (cx + half), CS * (cy + half)

    def _hit(self, x, y):
        cand = []
        if self.on.get("mask2"):
            cand.append("mask2")
        if self.on.get("mask"):
            cand.append("mask")
        for _k in ("text", "bars", "tele", "extra"):
            if self.on.get(_k):
                cand.append(_k)
        cand += [k for k in ("map", "att", "rs", "ls") if self.on.get(k, True)]
        for key in cand:
            try:
                b = self._box(key)
            except Exception:
                # 某个元素没素材/没基准（例如面板图层缺了）：跳过它，别让一次点击整个失败，
                # 否则「看起来就是拖不动」
                continue
            if b[0] <= x <= b[2] and b[1] <= y <= b[3]:
                return key
        return None

    # ------------------------------------------------------------ 事件
    def _down(self, e):
        self.sel = self._hit(e.x, e.y)
        self._sync_xy()
        self.resize = False
        if self.sel in ("mask", "mask2"):
            b = self._box(self.sel)
            if abs(e.x - b[2]) < 18 * self.S and abs(e.y - b[3]) < 18 * self.S:
                self.resize = True
        self.drag = (e.x, e.y, dict(self.L))
        self.redraw()

    def _move(self, e):
        if not self.drag or not self.sel:
            return
        x0, y0, L0 = self.drag
        ddx, ddy = (e.x - x0) / CS, (e.y - y0) / CS
        if self.sel in ("mask", "mask2"):
            if self.resize:
                self.L[self.sel + "_w"] = max(40.0, round(L0.get(self.sel + "_w", 1920.0) + ddx))
                self.L[self.sel + "_h"] = max(20.0, round(L0.get(self.sel + "_h", 90.0) + ddy))
            else:
                self.L[self.sel + "_x"] = round(L0.get(self.sel + "_x", 0.0) + ddx)
                self.L[self.sel + "_y"] = round(L0.get(self.sel + "_y", 110.0) + ddy)
        else:
            self.L[self.sel + "_dx"] = round(L0.get(self.sel + "_dx", 0.0) + ddx)
            self.L[self.sel + "_dy"] = round(L0.get(self.sel + "_dy", 0.0) + ddy)
        self._sync_vars()
        self.redraw()

    def _up(self, e):
        self.drag = None

    def _wheel(self, e):
        key = self._hit(e.x, e.y) or self.sel
        if not key:
            return
        step = 1.05 if e.delta > 0 else 1 / 1.05
        if key in ("mask", "mask2"):
            self.L[key + "_w"] = max(40.0, round(self.L.get(key + "_w", 1920.0) * step))
            self.L[key + "_h"] = max(20.0, round(self.L.get(key + "_h", 90.0) * step))
        else:
            k = key + "_s"
            self.L[k] = max(0.2, min(3.0, round(float(self.L.get(k, 1.0)) * step, 3)))
        self.sel = key
        self._sync_vars()
        self.redraw()

    def _nudge(self, dx, dy, e):
        if not self.sel:
            return
        k = 1 if (e.state & 0x0001) else 5
        if self.sel in ("mask", "mask2"):
            self.L[self.sel + "_x"] = self.L.get(self.sel + "_x", 0.0) + dx * k
            self.L[self.sel + "_y"] = self.L.get(self.sel + "_y", 110.0) + dy * k
        else:
            self.L[self.sel + "_dx"] = self.L.get(self.sel + "_dx", 0.0) + dx * k
            self.L[self.sel + "_dy"] = self.L.get(self.sel + "_dy", 0.0) + dy * k
        self._sync_vars()
        self.redraw()

    # ------------------------------------------------------------ 对齐
    def align(self, axis):
        if axis == "y":
            self.L["rs_dy"] = round(self.L.get("ls_dy", 0.0))
        else:
            self.L["rs_dx"] = round(self.bases["ls"][0] + self.L.get("ls_dx", 0.0)
                                    - self.bases["rs"][0])
        self._sync_vars()
        self.redraw()

    def symmetry(self):
        lsx = self.bases["ls"][0] + self.L.get("ls_dx", 0.0)
        d = FRAME_W / 2.0 - lsx
        self.L["rs_dx"] = round(FRAME_W / 2.0 + d - self.bases["rs"][0])
        self._sync_vars()
        self.redraw()

    def equal_size(self):
        self.L["rs_s"] = self.L.get("ls_s", 1.0)
        self._sync_vars()
        self.redraw()

    def mask_align(self, axis):
        if axis == "x":
            self.L["mask2_x"] = round(self.L.get("mask_x", 0.0))
        else:
            self.L["mask2_y"] = round(self.L.get("mask_y", 0.0))
        self._sync_vars()
        self.redraw()

    def mask_same_size(self):
        self.L["mask2_w"] = self.L.get("mask_w", 1920.0)
        self.L["mask2_h"] = self.L.get("mask_h", 46.0)
        self._sync_vars()
        self.redraw()

    def _reset(self):
        if self.portrait:
            # 竖屏：恢复成 bbrender 的竖屏预设
            try:
                import bbrender as BR
                d = BR.portrait_layout(dict(BR.LAYOUT))
            except Exception:
                d = dict(ls_dx=270.0 - LS_BASE[0], ls_dy=1410.0 - LS_BASE[1], ls_s=0.62,
                         rs_dx=810.0 - RS_BASE[0], rs_dy=1410.0 - RS_BASE[1], rs_s=0.62,
                         att_dx=540.0 - ATT_BASE[0], att_dy=980.0 - ATT_BASE[1], att_s=0.58,
                         map_dx=18.0, map_dy=18.0, map_s=0.8,
                         tele_x=620.0, tele_y=300.0, tele_size=26.0,
                         bar_x=40.0, bar_y=1560.0, text_x=540.0, text_y=120.0)
            self.L.update({k: d[k] for k in ("ls_dx", "ls_dy", "ls_s", "rs_dx", "rs_dy",
                                             "rs_s", "att_dx", "att_dy", "att_s",
                                             "map_dx", "map_dy", "map_s")})
        else:
            self.L.update(ls_dx=0, ls_dy=0, ls_s=1.0, rs_dx=0, rs_dy=0, rs_s=1.0,
                          att_dx=0, att_dy=0, att_s=1.0,
                          map_dx=26.0, map_dy=20.0, map_s=1.0,
                          mask_x=0.0, mask_y=0.0, mask_w=1920.0, mask_h=46.0,
                          mask2_x=0.0, mask2_y=250.0, mask2_w=1920.0, mask2_h=60.0)
        self._sync_vars()
        self.redraw()

    def _save(self):
        L = dict(self.L)
        for k in ("ls", "rs", "att", "map", "extra"):
            L[k + "_dx"] = round(L.get(k + "_dx", 0.0))
            L[k + "_dy"] = round(L.get(k + "_dy", 0.0))
            L[k + "_s"] = round(max(0.2, min(3.0, float(L.get(k + "_s", 1.0)))), 3)
        for pre in ("mask_", "mask2_"):
            L[pre + "x"] = round(L.get(pre + "x", 0.0))
            L[pre + "y"] = round(L.get(pre + "y", 110.0))
            L[pre + "w"] = max(40.0, round(L.get(pre + "w", 1920.0)))
            L[pre + "h"] = max(20.0, round(L.get(pre + "h", 90.0)))
        L["stick_mode"] = float(self.mode)
        if self.on_save:
            self.on_save(L)
        self.destroy()

    # ------------------------------------------------------------ 渲染
    def redraw(self):
        im = self.bg.copy()
        for key, _lab, _c in MASKS:
            if self.on.get(key):
                b = self._box(key)
                mal = float(self.L.get(key + "_alpha", 1.0))
                mal = max(0.0, min(1.0, mal))
                ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
                ImageDraw.Draw(ov).rectangle([b[0], b[1], b[2], b[3]],
                                             fill=(0, 0, 0, int(255 * mal)))
                im = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")
        if self.on.get("extra") and self.layers.get("extra") is not None:
            lay = self.layers["extra"].transform((CW, CH), Image.AFFINE, self._affine("extra"),
                                                 resample=Image.BICUBIC)
            lay = self._with_alpha(lay, "extra")
            im.paste(lay, (0, 0), lay.split()[3])
        for key in ("tele", "bars", "text"):
            if not self.on.get(key):
                continue
            lay = self.layers.get(_lay(key))
            if lay is None:
                continue
            lay = lay.transform((CW, CH), Image.AFFINE, self._affine(key), resample=Image.BICUBIC)
            lay = self._with_alpha(lay, key)
            im.paste(lay, (0, 0), lay.split()[3])
        for key in ("map", "ls", "rs", "att"):
            if key in ("map", "att") and not self.on.get(key):
                continue
            aff = (self._map_affine(self.L.get("map_s", 1.0)) if key == "map"
                   else self._affine(key))
            lay = self.layers[_lay(key)].transform((CW, CH), Image.AFFINE, aff,
                                                  resample=Image.BICUBIC)
            lay = self._with_alpha(lay, key)
            im.paste(lay, (0, 0), lay.split()[3])
        self._photo = ImageTk.PhotoImage(im)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
        for key in self._visible_keys():
            label, col = ELEMS[key][0], ELEMS[key][1]
            self._mark(key, label, col)
        for key, lab, col in MASKS:
            if self.on.get(key):
                self._mark(key, lab, col)
        L = self.L
        txt = "左杆 X%+d Y%+d %d%%　右杆 X%+d Y%+d %d%%" % (
            L.get("ls_dx", 0), L.get("ls_dy", 0), round(L.get("ls_s", 1) * 100),
            L.get("rs_dx", 0), L.get("rs_dy", 0), round(L.get("rs_s", 1) * 100))
        if self.on.get("att"):
            txt += "　姿态 X%+d Y%+d %d%%" % (L.get("att_dx", 0), L.get("att_dy", 0),
                                           round(L.get("att_s", 1) * 100))
        if self.on.get("extra"):
            txt += "　面板 X%+d Y%+d" % (L.get("extra_dx", 0), L.get("extra_dy", 0))
        self.l_info.configure(text=txt)

    # ------------------------------------------------------------ 颜色
    @staticmethod
    def _color_choices(pal, allow_follow=False):
        """返回 (选项名, 选项色)：选项色 = (rgb, 编号) 或 None（=跟框线）"""
        names, cols = [], []
        if allow_follow:
            names.append("跟框线")
            cols.append(None)
        try:
            import bbrender as BR
            if pal == "BALL":
                nm, cs = list(BR.BALL_COLOR_NAMES), list(BR.BALL_COLORS)
            else:
                nm = list(BR.FRAME_COLOR_NAMES)
                cs = list(BR.FRAME_COLORS)
        except Exception:
            nm = ["浅灰", "纯白", "深黑", "天蓝", "荧光绿", "亮黄", "朱红", "淡紫"]
            cs = [(245, 245, 245), (255, 255, 255), (25, 25, 25), (0, 210, 255),
                  (0, 255, 130), (255, 200, 10), (255, 70, 70), (185, 120, 255)]
        for i, (n, c) in enumerate(zip(nm, cs)):
            names.append(n)
            cols.append((tuple(c), i))
        return names, cols

    def _follow_rgb(self):
        """「跟框线」时框线是什么颜色"""
        names, cols = self._color_choices("FRAME", False)
        try:
            fi = int(round(float(self.L.get("frame_i", 0.0)))) % len(cols)
            return cols[fi][0]
        except Exception:
            return (245, 245, 245)

    def _sync_colors(self):
        """把 L 里的颜色编号填进下拉框 + 色块"""
        self._col_updating = True
        try:
            for key, (var, sw, names, cols) in self.color_vars.items():
                v = self.L.get(key, -1.0 if cols and cols[0] is None else 0.0)
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    v = 0.0
                idx = None
                if v < 0 and cols and cols[0] is None:
                    idx = 0
                else:
                    want = int(round(v)) % max(1, len(cols) - (1 if cols and cols[0] is None else 0))
                    for j, c in enumerate(cols):
                        if c is not None and c[1] == want:
                            idx = j
                            break
                    if idx is None:
                        idx = 0
                var.set(names[idx])
                rgb = cols[idx][0] if cols[idx] else self._follow_rgb()
                sw.configure(bg="#%02x%02x%02x" % tuple(rgb))
        finally:
            self._col_updating = False

    def _pick_color(self, key):
        if getattr(self, "_col_updating", False):
            return
        item = self.color_vars.get(key)
        if not item:
            return
        var, sw, names, cols = item
        try:
            idx = names.index(var.get())
        except ValueError:
            return
        c = cols[idx]
        self.L[key] = -1.0 if c is None else float(c[1])
        rgb = c[0] if c is not None else self._follow_rgb()
        sw.configure(bg="#%02x%02x%02x" % tuple(rgb))
        if key == "frame_i":
            self._sync_colors()

    def _sync_xy(self):
        """把当前选中元素的坐标填进输入框"""
        try:
            if self.sel in ("mask", "mask2"):
                self.v_x.set("%d" % round(self.L.get(self.sel + "_x", 0.0)))
                self.v_y.set("%d" % round(self.L.get(self.sel + "_y", 0.0)))
            elif self.sel in ELEMS:
                cx, cy, _s = self._params(self.sel)
                self.v_x.set("%d" % round(cx))
                self.v_y.set("%d" % round(cy))
            else:
                self.v_x.set("")
                self.v_y.set("")
            # 透明度滑条同步成「图层里真实的不透明度」——和首次打开时显示 90% 保持一致，
            # 否则滑条停在 100% 而画面只有 90%，一拖动就突然变亮，看着像「不生效」
            akey = self._alpha_key(self.sel)
            if akey and self.sel not in ("mask", "mask2"):
                self._updating = True
                try:
                    self.v_alpha.set(int(round(self._eff_alpha(self.sel) * 100)))
                finally:
                    self._updating = False
            elif akey:
                self._updating = True
                try:
                    self.v_alpha.set(int(round(float(self.L.get(akey, 1.0)) * 100)))
                finally:
                    self._updating = False
        except Exception:
            pass

    # ------------------------------------------------------------ 透明度
    def _alpha_group(self, key):
        """哪些元素共用同一个透明度键：左右摇杆共用 stick_alpha，其余各管各的"""
        return ("ls", "rs") if key in ("ls", "rs") else (key,)

    def _group_layers(self, key):
        return [self.layers[_lay(k)] for k in self._alpha_group(key)
                if _lay(k) in self.layers]

    def _layer_bbox(self, name):
        """图层里非空像素的范围（未缩放，画布坐标系）"""
        lay = self.layers.get(name)
        if lay is None:
            return None
        bb = lay.getbbox()
        if bb is None:
            return None
        if FRAME_W > 0 and lay.size[0] != FRAME_W:
            k = FRAME_W / float(lay.size[0])
            bb = tuple(v * k for v in bb)
        return bb

    def _baked_alpha(self, key):
        """图层里最实那块像素的不透明度（纯烘焙值，不含用户改动）"""
        baked = 0.0
        for lay in self._group_layers(key):
            try:
                baked = max(baked, max(1, lay.getchannel("A").getextrema()[1]) / 255.0)
            except Exception:
                pass
        if baked <= 0:
            ak = self._alpha_key(key)
            try:
                baked = float(self.L.get(ak, 1.0)) if ak else 1.0
            except (TypeError, ValueError):
                baked = 1.0
        return baked

    def _eff_alpha(self, key):
        """元素现在实际的不透明度：L 里的键就是绝对值（打开时按图层烘焙值初始化）"""
        ak = self._alpha_key(key)
        if ak is None:
            return 1.0
        try:
            v = float(self.L.get(ak, 1.0))
        except (TypeError, ValueError):
            v = 1.0
        return max(0.0, min(1.0, v))

    def _alpha_key(self, sel):
        return {"ls": "stick_alpha", "rs": "stick_alpha", "map": "map_alpha",
                "mask": "mask_alpha", "mask2": "mask2_alpha",
                "extra": "tele_alpha", "tele": "tele_alpha",
                "bars": "bar_alpha", "text": "text_alpha"}.get(sel)

    def _apply_alpha(self, _v=None):
        """滑条一动就改对应透明度并立即重绘（实时预览）"""
        if getattr(self, "_updating", False):
            return
        key = self._alpha_key(self.sel)
        if not key:
            return
        try:
            val = max(0, min(100, int(self.v_alpha.get()))) / 100.0
        except Exception:
            return
        self.L[key] = val
        # 摇杆左右共用 stick_alpha
        if key == "stick_alpha":
            self.L["stick_alpha"] = val
        self.redraw()

    def _apply_xy(self):
        """把输入框里的坐标应用到选中元素"""
        if self.sel not in ELEMS and self.sel not in ("mask", "mask2"):
            return
        try:
            x = float(self.v_x.get())
            y = float(self.v_y.get())
        except Exception:
            return
        if self.sel in ("mask", "mask2"):
            self.L[self.sel + "_x"] = x
            self.L[self.sel + "_y"] = y
        else:
            base = self.bases[self.sel]
            if self.sel == "extra":
                self.L["extra_dx"] = x - base[0]
                self.L["extra_dy"] = y - base[1]
            else:
                self.L[self.sel + "_dx"] = x - base[0]
                self.L[self.sel + "_dy"] = y - base[1]
        self.redraw()

    def _with_alpha(self, lay, key):
        """把图层透明度换成滑条设置的值。

        面板/柱状图/文字在切图层时就烘进了 0.9 的透明度，摇杆有时烘的也是 1.0 以下；
        如果按「滑条值 / 图层里烘的值」算比例，滑条拉到 100% 也只能到 0.9、拉到 30%
        实际显示≈0.27，看起来就是「改了没反应」。这里一律按 **绝对值** 换算：
        元素当前的不透明度（含烘进去的那部分）= 滑条值。
        """
        ak = {"map": "map_alpha", "ls": "stick_alpha", "rs": "stick_alpha",
              "extra": "tele_alpha", "tele": "tele_alpha", "bars": "bar_alpha",
              "text": "text_alpha"}.get(key)
        if not ak:
            return lay
        want = max(0.0, min(1.0, float(self.L.get(ak, 1.0))))
        a = lay.getchannel("A")
        peak = max(a.getextrema()[1], 1)          # 图层里最实的那块像素
        if abs(want - 1.0) < 0.001 and peak >= 254:
            return lay
        # v/want*peak：图层里 alpha=peak 的像素落到 want，0 还是 0，中间的按比例
        a = a.point(lambda v: int(round(v * want * 255.0 / peak)) if v else 0)
        lay = lay.copy()
        lay.putalpha(a)
        return lay

    def _mark(self, key, label, col):
        b = self._box(key)
        w = 2 if self.sel == key else 1
        self.canvas.create_rectangle(*b, outline=col, width=w,
                                     dash=() if self.sel == key else (5, 3))
        # 框上标：名字 + 尺寸（画面像素）+ 透明度
        wpx = int(round((b[2] - b[0]) / CS))
        hpx = int(round((b[3] - b[1]) / CS))
        alpha_key = {"ls": "stick_alpha", "rs": "stick_alpha", "map": "map_alpha",
                     "mask": "mask_alpha", "mask2": "mask2_alpha",
                     "extra": "tele_alpha", "tele": "tele_alpha",
                     "bars": "bar_alpha", "text": "text_alpha"}.get(key)
        txt = "%s  %d×%d" % (label, wpx, hpx)
        if alpha_key:
            al = self.L.get(alpha_key)
            if al is not None:
                txt += "  透明%d%%" % int(round(float(al) * 100))
        self.canvas.create_text(b[0] + 3, b[1] - 8, anchor="w", text=txt, fill=col,
                                font=("Microsoft YaHei UI", 8, "bold"))