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

    f_brand = ImageFont.truetype(FONT_SERIF, 40)
    f_brand_en = ImageFont.truetype(FONT_REG, 22)
    f_mark = ImageFont.truetype(FONT_SERIF, 40)
    f_headline = ImageFont.truetype(FONT_SERIF, 88)
    f_seal = ImageFont.truetype(FONT_SERIF, 44)
    f_sub = ImageFont.truetype(FONT_REG, 30)
    f_chip = ImageFont.truetype(FONT_REG, 26)

    # 品牌区：朱砂方印「谱」+ 宋体产品名
    draw.rounded_rectangle([72, 60, 140, 128], radius=10, fill=ACCENT)
    draw.text((106, 94), "谱", font=f_mark, fill="#FFF6EE", anchor="mm")
    draw.text((164, 66), "有谱掌柜", font=f_brand, fill=INK)
    draw.text((164, 112), "YouPu Clerk · PAYATHON 2026", font=f_brand_en, fill=MUTED)

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
