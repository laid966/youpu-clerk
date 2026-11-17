"""生成分享封面图 clerk/web/og-cover.png（1200×630，OG 标准尺寸）。

## 为什么要有它
作品详情页链接被分享到微信/钉钉/小红书/赛事社区时，卡片预览显示的就是这张图——
它是 20% 影响力分的第一眼。风格与战报卡一致：白底、大数字式主张、单一强调色。

## 复现（用带 Pillow 的 Python 跑，不在项目 venv 依赖里）
    python clerk/make_og_cover.py
字体用 Windows 自带的微软雅黑（msyh*.ttc）；换机器跑如果报字体缺失，
把 FONT_* 路径指到任意中文字体即可——产物是位图，跑一次提交一次就够。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "web" / "og-cover.png"

W, H = 1200, 630
BG = "#F4EFE4"        # 宣纸
INK = "#221D18"       # 墨
MUTED = "#6E6459"
ACCENT = "#C2401D"    # 朱砂
BORDER = "#C9BCA4"

FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
FONT_REG = "C:/Windows/Fonts/msyh.ttc"
FONT_SERIF = "C:/Windows/Fonts/simsun.ttc"  # 宋体：木刻印刷感


def main() -> None:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)

    f_brand = ImageFont.truetype(FONT_SERIF, 46)
    f_brand_en = ImageFont.truetype(FONT_REG, 20)
    f_mark = ImageFont.truetype(FONT_SERIF, 38)
    f_headline = ImageFont.truetype(FONT_SERIF, 88)
    f_seal = ImageFont.truetype(FONT_SERIF, 44)
    f_sub = ImageFont.truetype(FONT_REG, 30)
    f_chip = ImageFont.truetype(FONT_REG, 26)

    # 标志：极简算盘（梁+档+双珠），与 clerk/web/logo.svg 同源几何
    lx, ly, ls = 72.0, 56.0, 76.0 / 64.0

    def px(v: float) -> float:
        return lx + v * ls

    def py(v: float) -> float:
        return ly + v * ls

    GRAY_BEAD = "#8D857A"  # 墨色 35% 不透明落在宣纸上的等效色
    draw.line([px(12), py(10), px(52), py(10)], fill=INK, width=7)
    draw.line([px(32), py(10), px(32), py(58)], fill=INK, width=6)
    for cx, cy, r in ((12, 10, 3.5), (52, 10, 3.5), (32, 10, 3), (32, 58, 3)):  # 圆头线帽
        draw.ellipse([px(cx) - r, py(cy) - r, px(cx) + r, py(cy) + r], fill=INK)
    draw.ellipse([px(16), py(14), px(48), py(34)], fill=ACCENT)    # 靠梁的朱砂珠
    draw.ellipse([px(21), py(41), px(43), py(55)], fill=GRAY_BEAD)  # 归位的灰珠

    # 字标：有谱（黑体粗·朱砂）+ 掌柜（宋体·墨）——字体对比即性格
    f_word = ImageFont.truetype(FONT_BOLD, 46)
    draw.text((172, 92), "有谱", font=f_word, fill=ACCENT, anchor="lm")
    width = draw.textlength("有谱", font=f_word)
    draw.text((172 + width + 10, 92), "掌柜", font=f_brand, fill=INK, anchor="lm")
    draw.text((174, 130), "YOUPU CLERK · PAYATHON 2026", font=f_brand_en, fill=MUTED, anchor="la")

    # 右上核印（圆章，微旋转）
    draw.ellipse([W - 208, 52, W - 96, 164], outline=ACCENT, width=5)
    draw.text((W - 152, 108), "核", font=f_seal, fill=ACCENT, anchor="mm")

    # 主标题（宋体大字，第二行朱砂）
    draw.text((72, 250), "话是 AI 说的，", font=f_headline, fill=INK)
    draw.text((72, 352), "钱是程序算的。", font=f_headline, fill=ACCENT)

    # 副标题
    draw.text((72, 470), "二手卖家的可信 AI 店员 —— 每次让步都有据可查，中英双语接待", font=f_sub, fill=MUTED)

    # 底部三枚承诺 chip（墨线白底，木刻感）
    chips = ["授权之内议价", "逐条规则依据", "台账不可改写"]
    x = 72
    for text in chips:
        width = draw.textlength(text, font=f_chip)
        draw.rounded_rectangle([x, 528, x + width + 44, 582], radius=6, outline=INK, width=2, fill="#FFFCF5")
        draw.text((x + 22, 555), text, font=f_chip, fill=INK, anchor="lm")
        x += width + 44 + 20

    # 底部强调条
    draw.rectangle([0, H - 8, W, H], fill=ACCENT)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT, "PNG")
    print(f"已生成 {OUT}（{OUT.stat().st_size} 字节）")


if __name__ == "__main__":
    main()
