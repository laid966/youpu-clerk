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
BG = "#FAFAF9"
INK = "#1C1917"
MUTED = "#78716C"
ACCENT = "#1677FF"
BORDER = "#E7E5E4"

FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
FONT_REG = "C:/Windows/Fonts/msyh.ttc"


def main() -> None:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)

    f_brand = ImageFont.truetype(FONT_BOLD, 34)
    f_brand_en = ImageFont.truetype(FONT_REG, 22)
    f_mark = ImageFont.truetype(FONT_BOLD, 40)
    f_headline = ImageFont.truetype(FONT_BOLD, 76)
    f_sub = ImageFont.truetype(FONT_REG, 30)
    f_chip = ImageFont.truetype(FONT_REG, 26)

    # 品牌区：蓝色圆角方块「谱」+ 产品名
    draw.rounded_rectangle([72, 64, 136, 128], radius=18, fill=ACCENT)
    draw.text((104, 96), "谱", font=f_mark, fill="white", anchor="mm")
    draw.text((160, 70), "有谱掌柜", font=f_brand, fill=INK)
    draw.text((160, 112), "YouPu Clerk · PAYATHON 2026", font=f_brand_en, fill=MUTED)

    # 主标题（两行，产品灵魂）
    draw.text((72, 232), "话是 AI 说的，", font=f_headline, fill=INK)
    draw.text((72, 322), "钱是程序算的。", font=f_headline, fill=ACCENT)

    # 副标题
    draw.text((72, 436), "二手卖家的可信 AI 店员 —— 每次让步都有据可查，中英双语接待", font=f_sub, fill=MUTED)

    # 底部三枚承诺 chip
    chips = ["授权之内议价", "逐条规则依据", "台账不可改写"]
    x = 72
    for text in chips:
        width = draw.textlength(text, font=f_chip)
        draw.rounded_rectangle([x, 512, x + width + 44, 566], radius=27, outline=BORDER, width=2, fill="white")
        draw.text((x + 22, 539), text, font=f_chip, fill=INK, anchor="lm")
        x += width + 44 + 20

    # 底部强调条
    draw.rectangle([0, H - 8, W, H], fill=ACCENT)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT, "PNG")
    print(f"已生成 {OUT}（{OUT.stat().st_size} 字节）")


if __name__ == "__main__":
    main()
