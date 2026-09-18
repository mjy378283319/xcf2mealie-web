"""生成 xcf2mealie-web 的应用图标（Unraid 容器图标 / 网页 favicon 通用）。

设计
----
暖橙渐变圆角方块（呼应下厨房的橙色食欲感）
  + 白色厨师帽（点明「菜谱」）
  + 帽箍内一个向下箭头（点明「导入」）

下面所有几何常量都写在 512 的设计坐标系里，绘制时统一按 SCALE 围绕画布中心
放大，再乘超采样倍数 SS。想整体调整图标大小，只改 SCALE 一个数即可。

用法
----
    python assets/make_icon.py

依赖：Pillow
输出：assets/icon.png（512×512，圆角外透明）
"""
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SS = 4               # 超采样倍数：先按 4 倍画，再缩小，得到平滑边缘
SIZE = 512
S = SIZE * SS
CENTER = SIZE / 2

SCALE = 1.30         # 主体相对设计稿的放大倍数（太小学 48px 时看不清）

BG_TOP = (255, 164, 82)      # 顶部的暖橙
BG_BOTTOM = (236, 68, 26)    # 底部的深橙红
SHADOW_RGBA = (150, 42, 8, 78)
ACCENT = (236, 68, 26, 255)  # 箭头与分隔线颜色（与底色一致，形成镂空感）

CORNER_RADIUS = 114

# --- 厨师帽几何（512 设计坐标系）----------------------------------------- #
# 帽顶三个蓬起 + 帽身填缝。比例很关键：帽箍要「宽而扁」（约占全高 1/4），
# 帽顶要占 3/4，否则整体会看成一个方块上面接一朵云。
LOBES = [((198, 244), 52), ((314, 244), 52), ((256, 206), 64)]

# 帽身用梯形而不是矩形，把帽顶宽度收拢到帽箍宽度；用矩形会在交界处留下凹角。
# 梯形底边一直延伸到帽箍圆角结束处（y0 + 半径），底边宽度正好等于帽箍宽度，
# 这样接缝严丝合缝，不会在帽箍两肩留下月牙形的缝。
BODY_POLY = [(150, 258), (362, 258), (346, 322), (166, 322)]
BAND = (166, 306, 346, 368, 16)                # x0, y0, x1, y1, 圆角半径

# 帽箍上沿的分隔线：横向范围故意画得很宽，靠帽子轮廓裁掉两端
DIVIDER_X = (120, 392)
DIVIDER_Y = (307, 317)

# --- 帽箍里的向下箭头 ----------------------------------------------------- #
ARROW_STEM = (249, 314, 263, 337)              # x0, y0, x1, y1
ARROW_HEAD = [(237, 334), (275, 334), (256, 358)]


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _vertical_gradient(size, top, bottom):
    """先画 1×size 的像素条再放大，比逐像素快得多。"""
    strip = Image.new("RGB", (1, size))
    px = strip.load()
    for y in range(size):
        px[0, y] = _lerp(top, bottom, y / (size - 1))
    return strip.resize((size, size), Image.BILINEAR)


def _t(v):
    """设计坐标 -> 实际像素坐标（先按中心缩放，再乘超采样倍数）。"""
    return (CENTER + (v - CENTER) * SCALE) * SS


def _tr(v):
    """设计坐标下的长度 -> 实际像素长度（只缩放，不平移）。"""
    return v * SCALE * SS


def _t_box(box):
    return [_t(box[0]), _t(box[1]), _t(box[2]), _t(box[3])]


def _t_points(points):
    return [(_t(x), _t(y)) for x, y in points]


def _c(v):
    """设计坐标 -> 512 画布坐标（不带超采样），供导出 SVG 用。"""
    return round(CENTER + (v - CENTER) * SCALE, 2)


def _cr(v):
    """设计坐标下的长度 -> 画布长度，供导出 SVG 用。"""
    return round(v * SCALE, 2)


def _draw_hat(target, color):
    d = ImageDraw.Draw(target)
    for (cx, cy), r in LOBES:
        d.ellipse([_t(cx - r), _t(cy - r), _t(cx + r), _t(cy + r)], fill=color)
    d.polygon(_t_points(BODY_POLY), fill=color)
    x0, y0, x1, y1, rad = BAND
    d.rounded_rectangle(_t_box((x0, y0, x1, y1)), radius=_tr(rad), fill=color)


def build():
    # 1) 渐变底
    img = _vertical_gradient(S, BG_TOP, BG_BOTTOM).convert("RGBA")

    # 2) 顶部一层很淡的高光，避免大色块显得死板。
    #    刻意不用 Image.radial_gradient：它放大后会出现明显的横向色带。
    sheen = Image.new("L", (1, S))
    px = sheen.load()
    for y in range(S):
        t = y / (S * 0.45)
        px[0, y] = 0 if t >= 1 else int(26 * (1 - t) ** 1.6)
    img = Image.composite(
        Image.new("RGBA", (S, S), (255, 255, 255, 255)),
        img,
        sheen.resize((S, S), Image.BILINEAR),
    )

    # 3) 帽子投影：画实心 -> 高斯模糊 -> 下移，营造轻微悬浮感
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    _draw_hat(shadow, SHADOW_RGBA)
    shadow = shadow.filter(ImageFilter.GaussianBlur(_tr(11)))
    shadow_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shadow_layer.paste(shadow, (0, int(_tr(7))), shadow)
    img.alpha_composite(shadow_layer)

    # 4) 白帽
    hat = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    _draw_hat(hat, (255, 255, 255, 255))
    img.alpha_composite(hat)

    # 4b) 帽箍与帽顶之间的分隔线。拿帽子的 alpha 当蒙版裁一下，
    #     线条两端就会自然贴合外轮廓，不会戳出帽子外面。
    divider = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(divider).rectangle(
        _t_box((DIVIDER_X[0], DIVIDER_Y[0], DIVIDER_X[1], DIVIDER_Y[1])), fill=ACCENT
    )
    divider.putalpha(ImageChops.multiply(divider.split()[3], hat.split()[3]))
    img.alpha_composite(divider)

    # 5) 帽箍内的橙色向下箭头
    arrow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(arrow)
    d.rectangle(_t_box(ARROW_STEM), fill=ACCENT)
    d.polygon(_t_points(ARROW_HEAD), fill=ACCENT)
    img.alpha_composite(arrow)

    # 6) 圆角裁切
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, S - 1, S - 1], radius=CORNER_RADIUS * SS, fill=255
    )
    img.putalpha(mask)

    # 7) 降采样输出
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def _svg_hat_shapes():
    """帽子各部件，PNG 与 SVG 共用同一套几何常量。"""
    parts = []
    for (cx, cy), r in LOBES:
        parts.append(
            f'    <circle cx="{_c(cx)}" cy="{_c(cy)}" r="{_cr(r)}"/>'
        )
    pts = " ".join(f"{_c(x)},{_c(y)}" for x, y in BODY_POLY)
    parts.append(f'    <polygon points="{pts}"/>')
    x0, y0, x1, y1, rad = BAND
    parts.append(
        f'    <rect x="{_c(x0)}" y="{_c(y0)}" width="{_cr(x1 - x0)}" '
        f'height="{_cr(y1 - y0)}" rx="{_cr(rad)}"/>'
    )
    return "\n".join(parts)


def render_svg():
    """导出等价的矢量版本，方便以后改色/改尺寸。"""
    hex_top = "#%02X%02X%02X" % BG_TOP
    hex_bottom = "#%02X%02X%02X" % BG_BOTTOM
    hex_accent = "#%02X%02X%02X" % ACCENT[:3]
    dx0, dx1 = DIVIDER_X
    dy0, dy1 = DIVIDER_Y
    arrow_pts = " ".join(f"{_c(x)},{_c(y)}" for x, y in ARROW_HEAD)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <!-- xcf2mealie-web 应用图标：暖橙底 + 白厨师帽 + 导入箭头 -->
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{hex_top}"/>
      <stop offset="1" stop-color="{hex_bottom}"/>
    </linearGradient>
    <linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#fff" stop-opacity="0.10"/>
      <stop offset="0.45" stop-color="#fff" stop-opacity="0"/>
    </linearGradient>
    <clipPath id="round">
      <rect x="0" y="0" width="512" height="512" rx="{CORNER_RADIUS}" ry="{CORNER_RADIUS}"/>
    </clipPath>
    <clipPath id="hat">
      <g>
{_svg_hat_shapes()}
      </g>
    </clipPath>
    <filter id="soft" x="-30%" y="-30%" width="160%" height="160%">
      <feDropShadow dx="0" dy="{_cr(7)}" stdDeviation="{_cr(5)}"
                    flood-color="#962A08" flood-opacity="0.30"/>
    </filter>
  </defs>

  <g clip-path="url(#round)">
    <rect width="512" height="512" fill="url(#bg)"/>
    <rect width="512" height="512" fill="url(#sheen)"/>

    <g fill="#FFFFFF" filter="url(#soft)">
{_svg_hat_shapes()}
    </g>

    <rect x="{_c(dx0)}" y="{_c(dy0)}" width="{_cr(dx1 - dx0)}"
          height="{_cr(dy1 - dy0)}" fill="{hex_accent}" clip-path="url(#hat)"/>

    <rect x="{_c(ARROW_STEM[0])}" y="{_c(ARROW_STEM[1])}"
          width="{_cr(ARROW_STEM[2] - ARROW_STEM[0])}"
          height="{_cr(ARROW_STEM[3] - ARROW_STEM[1])}" fill="{hex_accent}"/>
    <polygon points="{arrow_pts}" fill="{hex_accent}"/>
  </g>
</svg>
"""


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))

    out = os.path.join(here, "icon.png")
    icon = build()
    icon.save(out, "PNG", optimize=True)
    print("wrote", out, icon.size, os.path.getsize(out), "bytes")

    out = os.path.join(here, "icon.svg")
    with open(out, "w", encoding="utf-8") as f:
        f.write(render_svg())
    print("wrote", out, os.path.getsize(out), "bytes")
