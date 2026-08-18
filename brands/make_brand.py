"""Generate the brand assets (icon/logo, light+dark, 1x/2x) for home-assistant/brands.

Run:  python brands/make_brand.py
Concept: a lightning bolt (consumption) under a ceiling bar (the capacity limit / peak).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "capacity_tariff"
OUT.mkdir(exist_ok=True)

AMBER = (246, 162, 27, 255)
NAVY = (31, 58, 95, 255)
LIGHT = (232, 238, 245, 255)
S = 4  # supersampling factor

# Geometry in a 256 x 256 grid
CEILING = (40, 34, 216, 60)  # x0, y0, x1, y1
BOLT = [(158, 72), (70, 166), (124, 166), (94, 240), (188, 132), (132, 132), (172, 72)]


def draw_icon(size: int, bar_color: tuple[int, int, int, int]) -> Image.Image:
    px = 256 * S
    im = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = (v * S for v in CEILING)
    d.rounded_rectangle((x0, y0, x1, y1), radius=(y1 - y0) // 2, fill=bar_color)
    d.polygon([(x * S, y * S) for x, y in BOLT], fill=AMBER)
    return im.resize((size, size), Image.LANCZOS)


def draw_logo(height: int, bar_color, text_color) -> Image.Image:
    icon_px = int(height * 0.82)
    icon = draw_icon(icon_px, bar_color)
    font = ImageFont.truetype("C:/Windows/Fonts/bahnschrift.ttf", int(height * 0.36))
    text = "Capaciteitstarief"
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = tmp.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    gap = int(height * 0.12)
    width = icon_px + gap + tw + int(height * 0.06)
    im = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    im.paste(icon, (0, (height - icon_px) // 2), icon)
    d = ImageDraw.Draw(im)
    d.text(
        (icon_px + gap - bbox[0], (height - th) // 2 - bbox[1]),
        text,
        font=font,
        fill=text_color,
    )
    return im


def main() -> None:
    for name, bar in (("icon", NAVY), ("dark_icon", LIGHT)):
        draw_icon(256, bar).save(OUT / f"{name}.png")
        draw_icon(512, bar).save(OUT / f"{name}@2x.png")
    for name, bar, text in (("logo", NAVY, NAVY), ("dark_logo", LIGHT, LIGHT)):
        draw_logo(128, bar, text).save(OUT / f"{name}.png")
        draw_logo(256, bar, text).save(OUT / f"{name}@2x.png")
    # preview sheet for a quick visual check
    logo = Image.open(OUT / "logo@2x.png")
    w = 40 + 256 + 40 + logo.width + 40 + 96 + 40
    sheet = Image.new("RGBA", (w, 600), (255, 255, 255, 255))
    sheet.paste(Image.new("RGBA", (w, 300), (28, 28, 30, 255)), (0, 300))
    for row, (icon_name, logo_name) in enumerate((("icon", "logo"), ("dark_icon", "dark_logo"))):
        y = 300 * row + 22
        icon = Image.open(OUT / f"{icon_name}.png")
        lg = Image.open(OUT / f"{logo_name}@2x.png")
        sheet.paste(icon, (40, y), icon)
        sheet.paste(lg, (40 + 256 + 40, y), lg)
        for i, size in enumerate((96, 48, 24)):
            small = icon.resize((size, size), Image.LANCZOS)
            sheet.paste(small, (w - 40 - 96, y + i * 110), small)
    sheet.save(Path(__file__).parent / "preview.png")
    print("written to", OUT)


if __name__ == "__main__":
    main()
