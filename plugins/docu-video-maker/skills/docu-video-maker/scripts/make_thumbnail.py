"""サムネイル（1280×720）を作る。絵を1枚画面いっぱいに敷き、左に太い明朝の問いを階段に組み、1語だけ赤くする型。
使い方: python3 make_thumbnail.py <設計.json> <出力.png>
設計.json の例（image=敷く絵・crop=原画の切り抜き[左,上,右,下]・place=絵を置く横の中心0〜1、文字は反対側・
lines=[下端の y, [[文字, 大きさ, "w"白 か "r"赤], ...]]）:
{"image": "assets/img/pd_family.jpg", "crop": [0, 560, 2000, 2300], "place": 0.66,
 "lines": [[150, [["王妃の", 120, "w"]]],
           [380, [["4人", 250, "r"], ["の子は", 130, "w"]]],
           [560, [["どうなった", 150, "w"], ["のか", 110, "w"]]]]}
小さく（320×180）縮めた確認用も <出力>_small.png に出す。必ず両方を目で見る。
"""
import json, os, pathlib, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import MINCHO_B

W, H = 1280, 720
COL = {"w": (250, 248, 242), "r": (226, 20, 24)}
SERIF = os.environ.get("DVM_FONT_THUMB") or next((p for p in (str(pathlib.Path.home() / "Library/Fonts/NotoSerifJP-Black.otf"),) if pathlib.Path(p).exists()), MINCHO_B[0])
IDX = 0 if SERIF != MINCHO_B[0] else MINCHO_B[1]


def F(s):
    return ImageFont.truetype(SERIF, s, index=IDX)


def bleed(img, box, cx):
    part = img.crop(box) if box else img
    k = H / part.height
    fg = part.resize((int(part.width * k), H), Image.LANCZOS)
    bg = img.resize((W, int(img.height * W / img.width)), Image.LANCZOS)
    bg = bg.crop((0, max(0, (bg.height - H) // 2), W, max(0, (bg.height - H) // 2) + H)).resize((W, H)).filter(ImageFilter.GaussianBlur(24))
    bg = ImageEnhance.Brightness(bg).enhance(0.35)
    if fg.width >= W:
        x0 = int(min(max(0, fg.width * cx - W / 2), fg.width - W))
        return fg.crop((x0, 0, x0 + W, H))
    x0 = min(max(int(W * cx - fg.width / 2), 0), W - fg.width)
    m = np.ones((H, fg.width), np.float32); ramp = np.linspace(0, 1, 80, dtype=np.float32)
    if x0 > 0: m[:, :80] *= ramp[None, :]
    if x0 + fg.width < W: m[:, -80:] *= ramp[::-1][None, :]
    bg.paste(fg, (x0, 0), Image.fromarray((m * 255).astype(np.uint8)))
    return bg


def darken(im, left=True):
    a = np.asarray(im.convert("RGB"), dtype=np.float32)
    x = np.arange(W, dtype=np.float32) / W
    x = x if left else 1 - x
    k = 1 - 0.8 * np.clip(1 - x / 0.58, 0, 1) ** 1.4
    v = 1 - 0.35 * np.clip((np.arange(H, dtype=np.float32) / H - 0.7) / 0.3, 0, 1)
    return Image.fromarray((a * k[None, :, None] * v[:, None, None]).clip(0, 255).astype(np.uint8)).convert("RGBA")


def draw_words(im, lines, x0):
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    for key in ("w", "r"):
        m = Image.new("L", (W, H), 0); d = ImageDraw.Draw(m)
        for y, segs in lines:
            x = x0
            for t, s, c in segs:
                if c == key:
                    d.text((x, y), t, font=F(s), fill=255, anchor="ls")
                x += probe.textlength(t, font=F(s)) + 6
        if not m.getbbox():
            continue
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0)); glow.putalpha(m.filter(ImageFilter.MaxFilter(15)).filter(ImageFilter.GaussianBlur(14)))
        im.alpha_composite(glow)
        edge = Image.new("RGBA", (W, H), (0, 0, 0, 255)); edge.putalpha(m.filter(ImageFilter.MaxFilter(7)))
        im.alpha_composite(edge)
        face = Image.new("RGBA", (W, H), COL[key] + (255,)); face.putalpha(m)
        im.alpha_composite(face)
    return im


def main():
    spec_p = pathlib.Path(sys.argv[1]); out = pathlib.Path(sys.argv[2])
    sp = json.loads(spec_p.read_text())
    ip = pathlib.Path(sp["image"]); ip = ip if ip.is_absolute() else spec_p.parent / ip
    img = Image.open(ip).convert("RGB")
    place = sp.get("place", 0.66)
    im = darken(bleed(img, sp.get("crop"), place), left=place >= 0.5)
    im = draw_words(im, sp["lines"], 40 if place >= 0.5 else int(W * 0.42))
    im = im.convert("RGB"); im.save(out)
    im.resize((320, 180), Image.LANCZOS).save(out.with_name(out.stem + "_small.png"))
    print(out)


if __name__ == "__main__":
    main()
