from __future__ import annotations

from pathlib import Path


def main() -> int:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        print("Pillow (PIL) is required. Install with: pip install pillow")
        return 1

    sizes = [16, 24, 32, 48, 64, 128, 256]
    bg = (15, 23, 42, 255)  # dark navy
    accent = (249, 115, 22, 255)  # orange
    white = (255, 255, 255, 255)

    images = []
    for s in sizes:
        img = Image.new("RGBA", (s, s), bg)
        draw = ImageDraw.Draw(img)

        pad = max(1, s // 12)
        draw.rounded_rectangle((pad, pad, s - pad, s - pad), radius=max(2, s // 6), outline=accent, width=max(1, s // 18))

        # Minimal saw-blade hint: small orange circle with teeth
        cx = s * 0.28
        cy = s * 0.32
        r = s * 0.16
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=accent, width=max(1, s // 24))

        # "OC" letters
        try:
            font = ImageFont.truetype("arial.ttf", max(10, int(s * 0.42)))
        except Exception:
            font = ImageFont.load_default()

        text = "OC"
        tw, th = draw.textbbox((0, 0), text, font=font)[2:4]
        tx = (s - tw) * 0.52
        ty = (s - th) * 0.55
        draw.text((tx, ty), text, font=font, fill=white)

        # Orange accent bar
        bar_h = max(2, s // 10)
        draw.rounded_rectangle((pad, s - pad - bar_h, s - pad, s - pad), radius=bar_h // 2, fill=accent)

        images.append(img)

    out = Path("icon.ico")
    images[0].save(out, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"Created {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

