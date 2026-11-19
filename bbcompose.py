"""bboverlay / bbcompose —— 用已经切好的图层，在本地快速拼出一张预览图

作用：预览一帧 和 元素位置 共用同一批图层（lstick / rstick / att / map + 视频帧），
拖动版式后再出图也不需要重新解码、算姿态、下瓦片，一两秒就能出。
"""
import os

from PIL import Image, ImageChops, ImageDraw

W, H = 1920, 1080

LS_BASE = (620.0, 812.0)
RS_BASE = (1300.0, 812.0)
ATT_BASE = (960.0, 800.0)
MAP_BASE = (26.0, 20.0)
MAP0 = 360.0

# 图层 key -> (基准点, 半宽)
BASES = {"ls": LS_BASE, "rs": RS_BASE, "att": ATT_BASE, "map": MAP_BASE}


def _shape_mask(size, shape, rr=0.16):
    """0=矩形 1=圆角矩形 2=椭圆"""
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


def _element_affine(base, dx, dy, s, cs=1.0):
    bx, by = base
    c = (-(cs * bx * (1 - s) + cs * dx)) / s
    f = (-(cs * by * (1 - s) + cs * dy)) / s
    return (1.0 / s, 0, c, 0, 1.0 / s, f)


def _map_affine(dx, dy, s, cs=1.0):
    ax, ay = MAP_BASE
    c = (-(cs * dx) + cs * ax * s) / s
    f = (-(cs * dy) + cs * ay * s) / s
    return (1.0 / s, 0, c, 0, 1.0 / s, f)


def compose(layers, frame_path, layout, att_on=True, map_on=True,
            mask_on=False, mask2_on=False, out_path=None, size=None, extra_on=True):
    """把各图层按版式叠到视频帧上，返回 PIL 图像（并可保存）

    layers: {"ls": png, "rs": png, "att": png, "map": png}
    size: (宽, 高)，默认 1920×1080
    """
    L = dict(layout or {})
    frame = Image.open(frame_path).convert("RGB")
    if size and tuple(size) != frame.size:
        frame = frame.resize(tuple(size), Image.LANCZOS)
    im = frame.copy()
    cs = im.size[0] / float(W)

    # 黑块先画（在 HUD 下面，和成片一致）
    d = ImageDraw.Draw(im)
    for pre, on in (("mask_", mask_on), ("mask2_", mask2_on)):
        if not on:
            continue
        x0 = L.get(pre + "x", 0.0) * cs
        y0 = L.get(pre + "y", 110.0) * cs
        mw = L.get(pre + "w", 1920.0) * cs
        mh = L.get(pre + "h", 90.0) * cs
        sh = int(round(L.get(pre + "shape", 0.0)))
        al = max(0.0, min(1.0, float(L.get(pre + "alpha", 1.0))))
        if al >= 0.999:
            if sh == 1:
                d.rounded_rectangle([x0, y0, x0 + mw, y0 + mh],
                                    radius=max(2, int(min(mw, mh) * 0.18)), fill=(0, 0, 0))
            elif sh == 2:
                d.ellipse([x0, y0, x0 + mw, y0 + mh], fill=(0, 0, 0))
            else:
                d.rectangle([x0, y0, x0 + mw, y0 + mh], fill=(0, 0, 0))
        else:
            box = (int(round(mw)), int(round(mh)))
            lay = Image.new("RGBA", box, (0, 0, 0, int(round(255 * al))))
            m = _shape_mask(box, sh)
            lay.putalpha(Image.composite(lay.getchannel("A"),
                                         Image.new("L", box, 0), m))
            im.paste(lay, (int(round(x0)), int(round(y0))), lay)

    for key in ("map", "ls", "rs", "att", "extra", "tele", "bars", "text"):
        if key == "map" and not map_on:
            continue
        if key == "att" and not att_on:
            continue
        if key == "extra" and not extra_on:
            continue
        path = (layers or {}).get(key)
        if not path or not os.path.exists(path):
            continue
        lay = Image.open(path).convert("RGBA").resize(im.size, Image.LANCZOS)
        if key == "map":
            a = _map_affine(L.get("map_dx", 26.0), L.get("map_dy", 20.0),
                            max(0.3, min(3.0, L.get("map_s", 1.0))), cs)
        elif key in ("tele", "bars", "text"):
            dx = L.get(key + "_dx", 0.0)
            dy = L.get(key + "_dy", 0.0)
            a = (1.0, 0, -dx * cs, 0, 1.0, -dy * cs)
        else:
            a = _element_affine(BASES[key], L.get(key + "_dx", 0.0),
                                L.get(key + "_dy", 0.0),
                                max(0.2, min(3.0, L.get(key + "_s", 1.0))), cs)
        moved = lay.transform(im.size, Image.AFFINE, a, resample=Image.BICUBIC)
        if key == "map":
            msh = int(round(L.get("map_shape", 0.0)))
            mal = max(0.0, min(1.0, float(L.get("map_alpha", 1.0))))
            if msh != 0 or mal < 0.999:
                ms = int(round(MAP0 * max(0.2, min(3.0, L.get("map_s", 1.0))) * cs))
                bx = int(round(L.get("map_dx", 26.0) * cs))
                by = int(round(L.get("map_dy", 20.0) * cs))
                box = (max(1, ms), max(1, ms))
                m = _shape_mask(box, msh)
                if mal < 0.999:
                    m = m.point(lambda v: max(0, min(255, int(round(v * mal)))))
                full = Image.new("L", im.size, 0)
                full.paste(m, (bx, by))
                alpha = ImageChops.multiply(moved.split()[3], full)
                moved.putalpha(alpha)
        im.paste(moved, (0, 0), moved.split()[3])

    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        im.save(out_path, quality=93)
    return im