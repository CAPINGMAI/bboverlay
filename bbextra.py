"""bboverlay / bbextra —— 附加效果：数值面板、条形图、自定义文字、事件标记、暗角/圆角

所有绘制都在 HUD 图层上完成（RGBA），所以透明度是真实的。
"""
import math

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080

# 文字颜色（和摇杆的调色板一致）
TEXT_COLORS = [(245, 245, 245), (255, 255, 255), (25, 25, 25), (0, 210, 255),
               (0, 255, 130), (255, 200, 10), (255, 70, 70), (185, 120, 255)]

_FONT_CACHE = {}


def font(size, bold=True):
    key = (int(size), bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    names = ["msyhbd.ttc", "msyh.ttc", "arialbd.ttf", "arial.ttf"] if bold else \
            ["msyh.ttc", "arial.ttf"]
    f = None
    for n in names:
        try:
            f = ImageFont.truetype(n, int(size))
            break
        except Exception:
            continue
    if f is None:
        try:
            f = ImageFont.load_default()
        except Exception:
            f = None
    _FONT_CACHE[key] = f
    return f


def _fmt(v, unit="", nd=1):
    if v is None:
        return "--"
    try:
        if math.isnan(float(v)):
            return "--"
    except Exception:
        return "--"
    if nd == 0:
        return "%d%s" % (int(round(float(v))), unit)
    return ("%." + str(nd) + "f%s") % (float(v), unit)


def draw_telemetry(img, x, y, rows, alpha=0.85, size=30, color_i=0, bg=True):
    """参数面板：rows = [(标签, 数值), ...]，返回 (宽, 高)"""
    f = font(size)
    fl = font(int(size * 0.62))
    col = TEXT_COLORS[int(color_i) % len(TEXT_COLORS)]
    pad = int(size * 0.55)
    lh = int(size * 1.35)
    # 标签列 / 数值列 各自最宽
    lab_w, val_w = 0, 0
    for lab, val in rows:
        try:
            lab_w = max(lab_w, int(fl.getbbox(lab)[2]))
            val_w = max(val_w, int(f.getbbox(val)[2]))
        except Exception:
            lab_w = max(lab_w, len(lab) * int(size * 0.5))
            val_w = max(val_w, len(val) * int(size * 0.5))
    box_w = pad * 3 + lab_w + val_w
    box_h = lh * len(rows) + int(size * 0.5)
    ov = Image.new("RGBA", (max(1, box_w), max(1, box_h)), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    if bg:
        od.rounded_rectangle([0, 0, box_w - 1, box_h - 1], radius=int(size * 0.5),
                             fill=(10, 12, 16, int(140 * alpha)))
    ty = int(size * 0.25)
    for lab, val in rows:
        od.text((pad, ty + int(size * 0.12)), lab, font=fl, fill=col + (int(240 * alpha),))
        od.text((pad * 2 + lab_w, ty), val, font=f, fill=(255, 255, 255, int(250 * alpha)))
        ty += lh
    img.paste(ov, (int(x), int(y)), ov)
    return box_w, box_h


def draw_bars(img, x, y, h, items, alpha=0.9, width=26, gap=16, color_i=0):
    """竖向条形图：items = [(值0..1, 颜色RGB 或 索引, 小标签)]"""
    ov = Image.new("RGBA", (int(width * 3 + gap * 4), int(h + 34)), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    cx = gap
    for i, (v, col, lab) in enumerate(items):
        if isinstance(col, tuple):
            c = col
        else:
            c = TEXT_COLORS[(int(col) + int(color_i)) % len(TEXT_COLORS)]
        v = max(0.0, min(1.0, float(v)))
        od.rounded_rectangle([cx, 0, cx + width, h], radius=width // 3,
                             fill=(255, 255, 255, int(40 * alpha)))
        fh = int(h * v)
        if fh > 4:
            od.rounded_rectangle([cx, h - fh, cx + width, h], radius=width // 3,
                                 fill=c + (int(235 * alpha),))
        od.text((cx + width // 2, h + 2), lab, font=font(20), anchor="mt",
                fill=(240, 240, 240, int(240 * alpha)))
        cx += width + gap
    img.paste(ov, (int(x), int(y)), ov)
    return ov.size


def draw_text(img, x, y, text, size=40, color_i=0, alpha=0.9, anchor="lt", shadow=True):
    f = font(size)
    col = TEXT_COLORS[int(color_i) % len(TEXT_COLORS)]
    try:
        w = int(f.getbbox(text)[2])
        h = int(f.getbbox(text)[3])
    except Exception:
        w, h = len(text) * int(size * 0.7), size
    pad = int(size * 0.5)
    ov = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    if shadow:
        od.text((pad + 2, pad + 2), text, font=f, fill=(0, 0, 0, int(150 * alpha)))
    od.text((pad, pad), text, font=f, fill=col + (int(255 * alpha),))
    px = int(x) - (ov.size[0] // 2 if anchor in ("mt", "mb") else 0)
    py = int(y) - (ov.size[1] if anchor in ("lb", "mb") else 0)
    if anchor == "mm":
        px, py = int(x) - ov.size[0] // 2, int(y) - ov.size[1] // 2
    img.paste(ov, (px, py), ov)
    return ov.size


def draw_event_badge(img, x, y, text, color=(255, 200, 10), alpha=0.95, size=24):
    f = font(size, bold=True)
    try:
        w = int(f.getbbox(text)[2]) + int(size * 0.9)
    except Exception:
        w = len(text) * size
    h = int(size * 1.7)
    ov = Image.new("RGBA", (max(1, w), h), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2,
                         fill=(10, 10, 12, int(160 * alpha)),
                         outline=color + (int(230 * alpha),), width=2)
    od.text((w // 2, h // 2), text, font=f, anchor="mm",
            fill=color + (int(255 * alpha),))
    img.paste(ov, (int(x), int(y)), ov)
    return w, h