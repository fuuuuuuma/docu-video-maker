"""組み立ての共通部品：場所・書体・色・ffmpeg の呼び方・文字の画像化。"""
import json, os, pathlib, shutil, subprocess, random
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

PIPE = pathlib.Path(__file__).resolve().parent
def _tool(name):
    """実際に起動できる ffmpeg / ffprobe を選ぶ（PATH に別の CPU 用の古いものが残っていることがある）。"""
    cands = [shutil.which(name), f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}", f"/usr/bin/{name}"]
    for c in cands:
        if c and pathlib.Path(c).exists():
            try:
                subprocess.run([c, "-version"], capture_output=True, timeout=10, check=True)
                return c
            except Exception:
                continue
    raise SystemExit(f"{name} が見つかりません（brew install ffmpeg）")


FF = _tool("ffmpeg")
FFPROBE = _tool("ffprobe")
W, H, FPS = 1920, 1080, 30
# 共有の置き場（地図のデータ・効果音）。回をまたいで使い回す。既定は ~/.cache/docu-video-maker
HOME = pathlib.Path(os.environ.get("DVM_HOME", pathlib.Path.home() / ".cache/docu-video-maker"))


def _first(*cands):
    """書体の候補から、存在する最初のものを返す（(パス, index)）。環境変数で上書きできる。"""
    for c in cands:
        p, i = c if isinstance(c, tuple) else (c, 0)
        if p and pathlib.Path(p).expanduser().exists():
            return str(pathlib.Path(p).expanduser()), i
    raise SystemExit("日本語の書体が見つかりません。check_env.py の案内に従って Noto Sans/Serif JP を入れるか、"
                     "DVM_FONT_MINCHO / DVM_FONT_GOTHIC に書体ファイルのパスを入れてください")


# 明朝（見出し・題字）とゴシック（通常テロップ）。macOS はヒラギノ、無ければ Noto
MINCHO_B = _first(os.environ.get("DVM_FONT_MINCHO"), ("/System/Library/Fonts/ヒラギノ明朝 ProN.ttc", 1),
                  "~/Library/Fonts/NotoSerifJP-Bold.otf", "~/Library/Fonts/NotoSerifJP-Black.otf",
                  "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc")
MINCHO_R = _first(os.environ.get("DVM_FONT_MINCHO_LIGHT"), ("/System/Library/Fonts/ヒラギノ明朝 ProN.ttc", 0),
                  "~/Library/Fonts/NotoSerifJP-Regular.otf", MINCHO_B)
WHITE = (247, 245, 238)
RED = (225, 34, 26)
GOLD = (255, 205, 120)


def font(size, weight=6):
    p, i = MINCHO_B if weight >= 6 else MINCHO_R
    return ImageFont.truetype(p, size, index=i)


def load_ep(ep_dir):
    ep = pathlib.Path(ep_dir).resolve()
    return ep, json.loads((ep / "script.json").read_text())


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def duration(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    return float(out)


def shadowed(size_wh, draw_fn, blur=7, shadow_alpha=230, offset=(2, 3)):
    """draw_fn(draw, dx, dy, fill_override) で描いた文字に、ぼかした影を付けた RGBA 画像を返す。"""
    w, h = size_wh
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(sh), offset[0], offset[1], (0, 0, 0, shadow_alpha))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    fg = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(fg), 0, 0, None)
    return Image.alpha_composite(sh, fg)


def text_runs(d, x, y, runs, fnt, fill_override=None):
    """runs=[(文字, 色)] を横に並べて描く。"""
    for s, col in runs:
        d.text((x, y), s, font=fnt, fill=fill_override or col)
        x += d.textlength(s, font=fnt)


def caption_image(text, red=None, size=52, tracking=0.08):
    """上部中央の字幕（明朝・影・一部の語だけ赤）。文字の外形ぎりぎりの RGBA と、置く左上座標を返す。"""
    fnt = font(size)
    chars = list(text)
    red_idx = set()
    if red and red in text:
        a = text.index(red); red_idx = set(range(a, a + len(red)))
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    sp = size * tracking
    widths = [probe.textlength(c, font=fnt) for c in chars]
    tw = sum(widths) + sp * (len(chars) - 1)
    pad = 30
    cw, ch = int(tw + pad * 2), int(size * 1.6 + pad * 2)

    def draw(d, dx, dy, ov):
        x = pad + dx
        for i, c in enumerate(chars):
            d.text((x, pad + dy), c, font=fnt, fill=ov or (RED if i in red_idx else WHITE),
                   stroke_width=0 if ov else 3, stroke_fill=(20, 16, 14))
            x += widths[i] + sp
    im = shadowed((cw, ch), draw)
    return im, (int((W - cw) / 2), 96 - pad)


def year_image(year):
    """左上の年号（数字は大きく「年」「代」は小さく、上に赤い線）。"""
    big, small = font(64), font(30)
    cw, chh = 420, 170
    m = __import__("re").match(r"^(\d+)(年代)?$", year)
    num, rest = (m.group(1), m.group(2) or "年") if m else (year, "")

    def draw(d, dx, dy, ov):
        d.text((30 + dx, 40 + dy), num, font=big, fill=ov or WHITE)
        nx = 30 + d.textlength(num, font=big) + 6
        d.text((nx + dx, 72 + dy), rest, font=small, fill=ov or WHITE)
        if ov is None:
            d.line([(32, 28), (84, 28)], fill=RED, width=4)
    im = shadowed((cw, chh), draw)
    return im, (56, 40)


POOL = "亜哀愛悪握圧安案暗以衣位囲医依委威為異移偉意違維遺域育逸引印因員院陰飲隠韻右宇羽雨運雲永泳英映栄営影鋭衛易益液越円延沿炎宴援園煙遠塩演王央応往押欧桜奥横屋億憶音恩温穏下化火加可仮何花価果河科夏家荷華貨過暇禍歌課我画芽賀雅介回灰会快戒改怪悔海界皆械絵開階塊解壊懐外害街慨蓋該概各角拡革格核郭覚較隔閣確獲学岳楽額括活渇割滑株干刊甘汗缶完肝官冠巻看陥乾勘患貫寒喚堪換敢棺款間閑勧寛幹感漢慣管関歓監緩憾還館環簡観艦鑑丸含岸岩眼頑顔願王政民権血刃剣城塔獄鎖炎"


def decoded(text, t, t0, step=0.06, hold=0.09, seed=0):
    """文字化けから正しい字に確定していく途中の文字列（NoBorder 風）。"""
    out, f = "", int(t * FPS)
    for i, c in enumerate(text):
        a = t0 + i * step
        if t < a:
            break
        if c in " 　、。" or t >= a + hold:
            out += c
        else:
            r = random.Random(f * 31 + i + seed)
            out += POOL[r.randrange(len(POOL))]
    return out


# ---------- テロップ v2（見やすさ優先・ドキュメンタリーの上品な体裁） ----------
GOTHIC = _first(os.environ.get("DVM_FONT_GOTHIC"), "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
                "~/Library/Fonts/NotoSansJP-Bold.otf", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
GOTHIC_B = _first("/System/Library/Fonts/ヒラギノ角ゴシック W7.ttc", "~/Library/Fonts/NotoSansJP-Black.otf", GOTHIC)
GOLD2 = (228, 194, 124)
CRIMSON = (232, 62, 50)
INK = (16, 13, 12)


def gothic(size, bold=False):
    p, i = GOTHIC_B if bold else GOTHIC
    return ImageFont.truetype(p, size, index=i)


def subtitle_image(text, size=48):
    """画面下の語り字幕：角ゴシック・白・太い暗色の縁・やわらかい影。中央揃え。"""
    fnt = gothic(size)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    tw = probe.textlength(text, font=fnt)
    pad = 36
    cw, ch = int(tw + pad * 2), int(size * 1.5 + pad * 2)

    def draw(d, dx, dy, ov):
        d.text((pad + dx, pad + dy), text, font=fnt, fill=ov or (250, 248, 244),
               stroke_width=0 if ov else 5, stroke_fill=INK)
    im = shadowed((cw, ch), draw, blur=9, shadow_alpha=200, offset=(0, 4))
    return im, (int((W - cw) / 2), 1080 - 76 - ch + pad)


def key_telop_image(text, red=None, size=80):
    """左上の見出しテロップ：金の細線＋明朝の大きな文字。左から薄れる暗い帯を敷く。"""
    fnt = font(size)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    chars = list(text); sp = size * 0.04
    widths = [probe.textlength(c, font=fnt) for c in chars]
    tw = sum(widths) + sp * (len(chars) - 1)
    red_idx = set()
    if red and red in text:
        a = text.index(red); red_idx = set(range(a, a + len(red)))
    cw, ch = int(tw + 260), int(size * 1.9 + 40)
    # 帯：左は濃く、文字の右端の先で消える
    band = np.zeros((ch, cw, 4), np.uint8)
    xs = np.arange(cw, dtype=np.float32)
    alpha = np.clip(1.0 - (xs - (tw + 40)) / 220.0, 0, 1) * 0.78
    ys = np.arange(ch, dtype=np.float32)
    vy = np.clip(1 - np.abs(ys - ch / 2) / (ch / 2), 0, 1) ** 0.7
    band[..., 3] = (alpha[None, :] * vy[:, None] * 255).astype(np.uint8)
    im = Image.fromarray(band, "RGBA")
    x0, y0 = 70, 24

    def draw(d, dx, dy, ov):
        x = x0 + dx
        for i, c in enumerate(chars):
            d.text((x, y0 + 18 + dy), c, font=fnt, fill=ov or (CRIMSON if i in red_idx else (248, 244, 236)))
            x += widths[i] + sp
    txt = shadowed((cw, ch), draw, blur=6, shadow_alpha=170, offset=(0, 3))
    im.alpha_composite(txt)
    ImageDraw.Draw(im).line([(x0, y0 + 4), (x0 + 72, y0 + 4)], fill=GOLD2 + (255,), width=3)
    return im, (0, 150)


def year_image_v2(year):
    """左上の年号：金の明朝・数字は大きく、年／年代は小さく。"""
    import re
    m = re.match(r"^(\d+)(年代)?$", year)
    num, rest = (m.group(1), m.group(2) or "年") if m else (year, "")
    big, small = font(54), font(26)
    cw, chh = 420, 130

    def draw(d, dx, dy, ov):
        d.text((70 + dx, 34 + dy), num, font=big, fill=ov or GOLD2)
        nx = 70 + d.textlength(num, font=big) + 6
        d.text((nx + dx, 60 + dy), rest, font=small, fill=ov or GOLD2)
    im = shadowed((cw, chh), draw, blur=6, shadow_alpha=200)
    return im, (0, 26)


def split_subtitles(text, maxlen=24):
    """読み上げ文を、句読点で区切って画面に出す長さ（maxlen 字以内）のまとまりにする。"""
    import re
    parts = [p for p in re.split(r"(?<=[、。！？])", text) if p.strip()]
    out, cur = [], ""
    for p in parts:
        p = p.strip()
        if len(cur) + len(p) <= maxlen:
            cur += p
        else:
            if cur:
                out.append(cur)
            while len(p) > maxlen:
                out.append(p[:maxlen]); p = p[maxlen:]
            cur = p
    if cur:
        out.append(cur)
    return [o.rstrip("。、") for o in out]


def shows_telop(L, S):
    """演出テロップ（左上の見出し）を出す行か。script.json に fx が1つでもあれば fx=true の行だけ、無ければ見出しのある行すべて。"""
    if not L.get("caption"):
        return False
    if any("fx" in x for x in S["lines"]):
        return bool(L.get("fx"))
    return True


def subtitle_image_v3(text, size=44):
    """通常テロップ（要約・句読点なし・最大2行）：画面下中央、白い角ゴシックに暗い縁とやわらかい影。参考は「その後の日本史」の下字幕。"""
    fnt = gothic(size)
    rows = text.split("\n")[:2]
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    ws = [probe.textlength(r, font=fnt) for r in rows]
    pad, lh = 34, int(size * 1.42)
    cw, ch = int(max(ws) + pad * 2), int(lh * len(rows) + pad * 2)

    def draw(d, dx, dy, ov):
        for i, r in enumerate(rows):
            d.text(((cw - ws[i]) / 2 + dx, pad + i * lh + dy), r, font=fnt, fill=ov or (252, 250, 246),
                   stroke_width=0 if ov else 4, stroke_fill=INK)
    im = shadowed((cw, ch), draw, blur=8, shadow_alpha=190, offset=(0, 3))
    return im, (int((W - cw) / 2), 1080 - 64 - ch + pad)


# ---------- 上下クロップ（シネスコ帯）版 ----------
CH = 816                 # 絵を出す帯の高さ（1920×816 ≒ 2.35:1）
BAR = (H - CH) // 2      # 上下の黒帯の高さ（132）


def subtitle_bar_image(text, size=44):
    """通常テロップ（1行・句読点なし）：下の黒帯の中央。"""
    fnt = gothic(size)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    tw = probe.textlength(text, font=fnt)
    pad = 20
    cw, ch = int(tw + pad * 2), int(size * 1.4 + pad * 2)

    def draw(d, dx, dy, ov):
        d.text((pad + dx, pad + dy), text, font=fnt, fill=ov or (246, 243, 236))
    im = shadowed((cw, ch), draw, blur=4, shadow_alpha=160, offset=(0, 2))
    return im, (int((W - cw) / 2), H - BAR // 2 - int(size * 0.62) - pad)


def year_bar_image(year):
    """年号：上の黒帯の左。金の明朝・数字は大きく、年／年代は小さく。"""
    import re
    m = re.match(r"^(\d+)(年代)?$", year)
    num, rest = (m.group(1), m.group(2) or "年") if m else (year, "")
    big, small = font(46), font(22)
    cw, chh = 400, 110

    def draw(d, dx, dy, ov):
        d.text((70 + dx, 26 + dy), num, font=big, fill=ov or GOLD2)
        nx = 70 + d.textlength(num, font=big) + 6
        d.text((nx + dx, 48 + dy), rest, font=small, fill=ov or GOLD2)
    im = shadowed((cw, chh), draw, blur=4, shadow_alpha=160)
    return im, (0, BAR // 2 - 26 - 30)


def _red_idx(text, red):
    if red and red in text:
        a = text.index(red); return set(range(a, a + len(red)))
    return set()


def can_vertical(text):
    """縦書きにしてよい文言か（数字・長音・かっこ・英字は縦にすると崩れるので外す）。"""
    import re
    return len(text) <= 10 and not re.search(r"[0-9A-Za-z０-９ー「」（）()]", text)


def key_telop_layout(text, red=None, layout="left"):
    """演出テロップを置き方ごとに描く。返り値 (RGBA, 左上座標, 出方)。出方は slideL/slideR/fade/drop。
    left: 帯の左上（金の線＋明朝）／ right: 帯の右下（右揃え）／ center: 中央に大きく、上下に金の線／ vertical: 右寄りに縦書き"""
    red_idx = _red_idx(text, red)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    if layout in ("left", "right"):
        im, _ = key_telop_image(text, red, 76)
        if layout == "left":
            return im, (0, BAR + 34), "slideL"
        fnt = font(76); sp = 76 * 0.04
        widths = [probe.textlength(c, font=fnt) for c in text]
        tw = sum(widths) + sp * (len(text) - 1)
        # 帯：右が濃く、文字の左端の先で消える（left の帯の左右反転。文字は含めない）
        a = np.asarray(im).copy(); a[..., :3] = 0
        cw0, ch0 = im.size
        xs = np.arange(cw0, dtype=np.float32)[::-1]
        alpha = np.clip(1.0 - (xs - (tw + 40)) / 220.0, 0, 1) * 0.78
        vy = np.clip(1 - np.abs(np.arange(ch0, dtype=np.float32) - ch0 / 2) / (ch0 / 2), 0, 1) ** 0.7
        a[..., 3] = (alpha[None, :] * vy[:, None] * 255).astype(np.uint8)
        band = Image.fromarray(a, "RGBA")
        x0 = band.width - 70 - tw

        def draw(d, dx, dy, ov):
            x = x0 + dx
            for i, c in enumerate(text):
                d.text((x, 24 + 18 + dy), c, font=fnt, fill=ov or (CRIMSON if i in red_idx else (248, 244, 236)))
                x += widths[i] + sp
        band.alpha_composite(shadowed(band.size, draw, blur=6, shadow_alpha=170, offset=(0, 3)))
        ImageDraw.Draw(band).line([(band.width - 70 - 72, 28), (band.width - 70, 28)], fill=GOLD2 + (255,), width=3)
        return band, (W - band.width, BAR + CH - band.height - 40), "slideR"
    if layout == "center":
        size = 104 if len(text) <= 10 else 84
        fnt = font(size); sp = size * 0.10
        widths = [probe.textlength(c, font=fnt) for c in text]
        tw = sum(widths) + sp * (len(text) - 1)
        cw, ch = int(tw + 360), int(size * 2.6)
        # 文字の後ろだけをやわらかく暗くする（楕円のぼかし）
        sh = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(sh).ellipse([60, ch * 0.18, cw - 60, ch * 0.82], fill=150)
        sh = sh.filter(ImageFilter.GaussianBlur(40))
        im = Image.new("RGBA", (cw, ch), (0, 0, 0, 0)); im.putalpha(sh)
        x0, y0 = (cw - tw) / 2, (ch - size * 1.25) / 2

        def draw(d, dx, dy, ov):
            x = x0 + dx
            for i, c in enumerate(text):
                d.text((x, y0 + dy), c, font=fnt, fill=ov or (CRIMSON if i in red_idx else (250, 246, 238)))
                x += widths[i] + sp
        im.alpha_composite(shadowed((cw, ch), draw, blur=8, shadow_alpha=200, offset=(0, 3)))
        d = ImageDraw.Draw(im); L = min(tw * 0.5, 260)
        d.line([((cw - L) / 2, y0 - 22), ((cw + L) / 2, y0 - 22)], fill=GOLD2 + (255,), width=2)
        d.line([((cw - L) / 2, y0 + size * 1.25 + 26), ((cw + L) / 2, y0 + size * 1.25 + 26)], fill=GOLD2 + (255,), width=2)
        return im, (int((W - cw) / 2), int(BAR + CH / 2 - ch / 2)), "fade"
    # vertical：縦書き。右寄りに置き、左に金の縦線
    size = int(min(78, (CH - 190) / (1.12 * len(text)))); fnt = font(size); step = int(size * 1.12)   # 帯の高さに収まる大きさ
    cw, ch = int(size * 3.2), int(step * len(text) + 120)
    sh = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(sh).rounded_rectangle([20, 10, cw - 20, ch - 10], radius=60, fill=160)
    sh = sh.filter(ImageFilter.GaussianBlur(34))
    im = Image.new("RGBA", (cw, ch), (0, 0, 0, 0)); im.putalpha(sh)
    cx = cw / 2

    def draw(d, dx, dy, ov):
        for i, c in enumerate(text):
            if c in " 　":
                continue
            wc = d.textlength(c, font=fnt)
            d.text((cx - wc / 2 + dx, 60 + i * step + dy), c, font=fnt, fill=ov or (CRIMSON if i in red_idx else (250, 246, 238)))
    im.alpha_composite(shadowed((cw, ch), draw, blur=7, shadow_alpha=190, offset=(0, 3)))
    ImageDraw.Draw(im).line([(cx - size * 0.85, 64), (cx - size * 0.85, 64 + min(150, step * len(text) * 0.5))], fill=GOLD2 + (255,), width=3)
    y = BAR + max(24, int((CH - ch) / 2) - 40)
    return im, (W - cw - 150, y), "drop"
