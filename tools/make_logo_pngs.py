"""把 clerk/web/logo.svg 的几何渲染成可直接使用的 PNG 套件（提交材料/发帖/头像用）。

## why
SVG 是源，但赛事表单、社区发帖、头像上传往往只收 PNG。
本脚本与 logo.svg / make_og_cover.py 共用同一套 64 网格几何——三处永不漂移。

产物（assets/）：
  logo-512.png / logo-192.png / logo-64.png   透明底图形标
  logo-512-paper.png                          宣纸底（需要不透明场合）
  logo-lockup-1200.png                        图形标+字标横版（文档/详情页头图）

用法：.venv\\Scripts\\python.exe tools/make_logo_pngs.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

INK = "#221D18"
SEAL = "#C2401D"
PAPER = "#F4EFE4"
GRAY_BEAD = "#8D857A"  # 墨 35% 落于宣纸的等效色（透明底时用墨+.35 .alpha）

FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
FONT_SERIF = "C:/Windows/Fonts/simsun.ttc"
FONT_REG = "C:/Windows/Fonts/msyh.ttc"

OUT = Path("assets")


def draw_mark(draw: ImageDraw.ImageDraw, box: tuple[float, float, float], alpha_bead: int = 255) -> None:
    """在 box=(x0,y0,size) 内按 64 网格画算盘标。"""
    x0, y0, size = box
    s = size / 64.0

    def px(v: float) -> float:
        return x0 + v * s

    def py(v: float) -> float:
        return y0 + v * s

    gray = (34, 29, 24, alpha_bead)
    # 横梁 + 圆头
    draw.line([px(12), py(10), px(52), py(10)], fill=INK, width=max(2, round(6 * s)))
    for cx in (12, 52):
        r = 3 * s
        draw.ellipse([px(cx) - r, py(10) - r, px(cx) + r, py(10) + r], fill=INK)
    # 档 + 圆头
    draw.line([px(32), py(10), px(32), py(58)], fill=INK, width=max(2, round(5 * s)))
    for cy in (10, 58):
        r = 2.5 * s
        draw.ellipse([px(32) - r, py(cy) - r, px(32) + r, py(cy) + r], fill=INK)
    # 朱砂珠（靠梁）与灰珠（归位）
    draw.ellipse([px(16), py(14), px(48), py(34)], fill=SEAL)
    draw.ellipse([px(21), py(41), px(43), py(55)], fill=gray)


def make_mark(size: int, background: str | None) -> Image.Image:
    mode = "RGBA"
    bg = (0, 0, 0, 0) if background is None else (*Image.new("RGB", (1, 1), background).getpixel((0, 0)), 255)
    image = Image.new(mode, (size, size), bg)
    draw_mark(ImageDraw.Draw(image), (0, 0, size))
    return image


def make_lockup(width: int = 1200) -> Image.Image:
    height = 300
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw_mark(draw, (40, 34, 232))
    f_youpu = ImageFont.truetype(FONT_BOLD, 120)
    f_zhanggui = ImageFont.truetype(FONT_SERIF, 120)
    f_en = ImageFont.truetype(FONT_REG, 40)
    x = 320
    draw.text((x, 150), "有谱", font=f_youpu, fill=SEAL, anchor="lm")
    w1 = draw.textlength("有谱", font=f_youpu)
    draw.text((x + w1 + 16, 150), "掌柜", font=f_zhanggui, fill=INK, anchor="lm")
    draw.text((x + 2, 232), "YOUPU CLERK · 可信 AI 店员", font=f_en, fill="#6E6459", anchor="lm")
    return image


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for size in (512, 192, 64):
        make_mark(size, None).save(OUT / f"logo-{size}.png", "PNG")
    make_mark(512, PAPER).save(OUT / "logo-512-paper.png", "PNG")
    make_lockup().save(OUT / "logo-lockup-1200.png", "PNG")
    for path in sorted(OUT.glob("logo-*.png")):
        print(f"{path}  {path.stat().st_size} 字节")


if __name__ == "__main__":
    main()
