#!/usr/bin/env python3
"""見る道具：書き出した動画を、作った担当も審査役も同じやり方で目で確かめるための一覧を作る。

  cuts   全カットの頭・中・終わりを並べる（作品全体の形・切り替えの乱れ・同じ絵の連続・切れ端）
  fast   動きの速い所を探し、その前後の全コマを並べる（振り向き・飛び・投げ・速い寄り）
  strip  指定した区間の全コマを並べる（見せ場・切り替えの瞬間）
  crop   指定した秒の一部を原寸で切り出す（顔・手・文字の縁・ギザギザ・色の段差）
  read   画面の文字が読み切れる長さ出ているかを調べる（SRT か JSON）

使い方:
  python3 look.py cuts  <動画> [--cuts <json>] [--scene 0.15] [--out <フォルダ>]
  python3 look.py fast  <動画> [--top 3] [--cuts <json>] [--out <フォルダ>]
  python3 look.py strip <動画> <開始秒> <終了秒> [--out <フォルダ>]
  python3 look.py crop  <動画> <秒[,秒...]> <x,y,w,h> [--zoom 2] [--out <フォルダ>]
  python3 look.py read  <字幕.srt|文字.json> [--cps 5] [--cps-voice 10] [--min 1.0] [--min-voice 0.5]

--cuts には区間の一覧（[[開始,終了],...] か [{"start","end"},...]）か、"shots"（と "cards"）を持つ時刻表を渡せる。
渡さなければ絵の変わり目を自動で探す（溶けて切り替わる所は拾いにくいので、時刻表があれば渡す）。
read の JSON は [{"text","start","end","voice"}, ...]。声と一緒に出る文字（字幕）は voice を true にする。
SRT は字幕なので全部 voice あつかい（声の無い文字なら --no-voice）。
出力は既定で <動画のフォルダ>/look/。作った画像は全部目で見る。要るもの: ffmpeg・ffprobe・Pillow。
"""
import argparse, bisect, io, json, os, re, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None


def tool(name):
    p = os.environ.get(name.upper()) or shutil.which(name)
    for d in ("/opt/homebrew/bin", "/usr/local/bin"):
        if not p and os.path.exists(f"{d}/{name}"):
            p = f"{d}/{name}"
    if not p:
        sys.exit(f"{name} が見つかりません（Mac は brew install ffmpeg）")
    return p


def need_pil():
    if Image is None:
        sys.exit("Pillow がありません（python3 -m pip install pillow）")


def probe(video):
    """(幅, 高さ, コマ数/秒, 長さ秒)"""
    r = subprocess.run([tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(video)],
                       capture_output=True, text=True)
    if r.returncode or not r.stdout.strip():
        sys.exit(f"動画を読めません: {video}")
    d = json.loads(r.stdout); s = d["streams"][0]
    n, m = s["r_frame_rate"].split("/")
    return int(s["width"]), int(s["height"]), float(n) / float(m or 1), float(d["format"]["duration"])


def tile_size(w, h, long=320):
    """一覧の 1 コマの大きさ（長い辺を long に、偶数に丸める）"""
    if w >= h:
        return long, max(2, round(long * h / w / 2) * 2)
    return max(2, round(long * w / h / 2) * 2), long


def tc(t):
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m)}:{s:05.2f}"


def font(size=14):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:   # 古い Pillow
        return ImageFont.load_default()


def label(im, text, color=(255, 255, 255), size=14):
    d = ImageDraw.Draw(im); f = font(size)
    x0, y0, x1, y1 = d.textbbox((4, 3), text, font=f)
    d.rectangle((x0 - 3, y0 - 2, x1 + 3, y1 + 2), fill=(0, 0, 0))
    d.text((4, 3), text, fill=color, font=f)


def grab(video, t, vf=None):
    """t 秒の 1 コマ（無ければ None）"""
    cmd = [tool("ffmpeg"), "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(video), "-frames:v", "1"]
    if vf:
        cmd += ["-vf", vf]
    r = subprocess.run(cmd + ["-f", "image2pipe", "-c:v", "png", "-"], capture_output=True)
    return Image.open(io.BytesIO(r.stdout)).convert("RGB") if r.stdout else None


def grab_many(video, times, vf=None):
    with ThreadPoolExecutor(min(8, os.cpu_count() or 4)) as ex:
        return list(ex.map(lambda t: grab(video, t, vf), times))


def outdir(video, out):
    d = Path(out) if out else Path(video).resolve().parent / "look"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clean(d, prefix):
    for f in d.glob(f"{prefix}*.jpg"):
        f.unlink()


def scene_scores(video):
    """各コマの「前のコマとの違い」（0〜1）を [(秒, 値)] で返す"""
    r = subprocess.run([tool("ffmpeg"), "-v", "error", "-i", str(video), "-an", "-vf",
                        "scale=320:-2,select='gte(scene,0)',metadata=print:file=-", "-f", "null", "-"],
                       capture_output=True, text=True)
    out, t = [], None
    for line in r.stdout.splitlines():
        m = re.search(r"pts_time:(-?[\d.]+)", line)
        if m:
            t = float(m.group(1)); continue
        m = re.search(r"lavfi\.scene_score=([\d.]+)", line)
        if m and t is not None:
            out.append((t, float(m.group(1))))
    return out


def load_segments(path):
    """区間の一覧か時刻表（"shots"・"cards"）から [(開始, 終了)]"""
    d = json.loads(Path(path).read_text())
    if isinstance(d, dict):
        rows = d.get("shots", []) + d.get("cards", [])
    else:
        rows = d
    segs = []
    for x in rows:
        if isinstance(x, dict):
            a, b = x.get("start", x.get("t0")), x.get("end", x.get("t1"))
        else:
            a, b = x[0], x[1]
        if a is not None and b is not None and float(b) > float(a):
            segs.append((float(a), float(b)))
    return sorted(segs)


def detect_segments(scores, dur, thr=0.15):
    cuts = []
    for t, s in scores:
        if s >= thr and t > 0.02 and (not cuts or t - cuts[-1] > 0.02):
            cuts.append(t)
    b = [0.0] + cuts + [dur]
    return [(x, y) for x, y in zip(b, b[1:]) if y > x]


def cuts(video, segments=None, out=None, scene=0.15, per_row=2, rows=8):
    """全カットの頭・中・終わりを 1 行に並べた一覧を作り、ファイルの一覧を返す"""
    need_pil()
    w, h, fps, dur = probe(video)
    segs = segments if segments is not None else detect_segments(scene_scores(video), dur, scene)
    tw, th = tile_size(w, h)
    d = outdir(video, out); clean(d, "cuts_")
    gap, per_sheet, files = 12, per_row * rows, []
    for k in range(0, len(segs), per_sheet):
        chunk = segs[k:k + per_sheet]
        times = []
        for s, e in chunk:
            m = min(0.12, (e - s) * 0.2)
            times += [s + m, (s + e) / 2, max(s, e - m - 1 / fps)]
        ims = grab_many(video, times, f"scale={tw}:{th}")
        n_rows = (len(chunk) + per_row - 1) // per_row
        sheet = Image.new("RGB", (per_row * 3 * tw + (per_row - 1) * gap, n_rows * (th + 4)), (40, 40, 40))
        for j, (s, e) in enumerate(chunk):
            x0, y0 = (j % per_row) * (3 * tw + gap), (j // per_row) * (th + 4)
            for c in range(3):
                im = ims[3 * j + c] or Image.new("RGB", (tw, th), (90, 0, 0))
                if c == 0:
                    short = e - s < 0.3
                    label(im, f"#{k + j + 1} {tc(s)}-{tc(e)} {e - s:.2f}s" + (" SHORT" if short else ""),
                          (255, 80, 80) if short else (255, 255, 255))
                sheet.paste(im, (x0 + c * tw, y0))
        f = d / f"cuts_{k // per_sheet + 1:02d}.jpg"; sheet.save(f, quality=85); files.append(f)
    short = [(i + 1, s) for i, (s, e) in enumerate(segs) if e - s < 0.3]
    print(f"カット {len(segs)} 個（{'時刻表から' if segments is not None else '絵の変わり目を自動で探した'}）")
    if short:
        print("0.3 秒未満のカット（切れ端・一瞬の閃光でないか見る）: " + ", ".join(f"#{n} {tc(s)}" for n, s in short[:20]))
    print(f"■ 各カットの頭・中・終わり（1 行に {per_row} カット・{len(files)} 枚）")
    for f in files:
        print(" ", f)
    return files


def strip(video, a, b, out=None, name=None, cols=8, limit=240):
    """a〜b 秒の全コマを並べた 1 枚を作り、そのパスを返す"""
    need_pil()
    w, h, fps, dur = probe(video)
    a, b = max(0.0, a), min(dur, b)
    tw, th = tile_size(w, h, 240)
    r = subprocess.run([tool("ffmpeg"), "-v", "error", "-ss", f"{a:.3f}", "-i", str(video), "-t", f"{b - a:.3f}",
                        "-vf", f"scale={tw}:{th}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    size = tw * th * 3; n = min(limit, len(r.stdout) // size)
    if not n:
        print("コマを取り出せませんでした", tc(a), tc(b)); return None
    sheet = Image.new("RGB", (cols * tw, ((n + cols - 1) // cols) * th))
    for i in range(n):
        im = Image.frombytes("RGB", (tw, th), r.stdout[i * size:(i + 1) * size])
        label(im, f"{a + i / fps:.2f}", (255, 230, 80), 12)
        sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
    d = outdir(video, out)
    f = d / (name or f"strip_{a:07.2f}-{b:07.2f}.jpg"); sheet.save(f, quality=85)
    return f


def fast(video, top=3, segments=None, scene=0.15, out=None):
    """切り替えを除いて動きの一番速い所を top 個探し、それぞれ前後 0.5 秒の全コマを並べる"""
    need_pil()
    w, h, fps, dur = probe(video)
    sc = scene_scores(video)
    if segments is not None:
        edges, win = sorted({x for s in segments for x in s}), 0.5
    else:
        edges, win = [t for t, s in sc if s >= scene], 2.5 / fps

    def near(t):
        i = bisect.bisect_left(edges, t - win)
        return i < len(edges) and edges[i] <= t + win

    vals = [0.0 if near(t) else s for t, s in sc]
    k = max(1, int(round(fps * 0.25)))
    cs = [0.0]
    for v in vals:
        cs.append(cs[-1] + v)
    sm = [(cs[min(len(vals), i + k)] - cs[max(0, i - k)]) / (min(len(vals), i + k) - max(0, i - k)) for i in range(len(vals))]
    order = sorted(range(len(sm)), key=lambda i: -sm[i])
    picks = []
    for i in order:
        if sm[i] < 0.015 or len(picks) >= top:
            break
        if all(abs(sc[i][0] - p) >= 2.0 for p in picks):
            picks.append(sc[i][0])
    d = outdir(video, out); clean(d, "fast_")
    if not picks:
        print("目立って速い動きは見つかりませんでした"); return []
    files = [strip(video, t - 0.5, t + 0.5, d, f"fast_{n + 1}_{t:07.2f}.jpg") for n, t in enumerate(sorted(picks))]
    print(f"■ 動きの速い所の全コマ（{len(files)} か所）")
    for f in files:
        print(" ", f)
    return files


def crop(video, times, box, zoom=1, out=None):
    """各秒の x,y,w,h を原寸で切り出す（zoom で拡大）"""
    need_pil()
    x, y, cw, ch = box
    d = outdir(video, out); files = []
    for t in times:
        im = grab(video, t, f"crop={cw}:{ch}:{x}:{y}")
        if im is None:
            print("取り出せませんでした", tc(t)); continue
        if zoom > 1:
            im = im.resize((cw * zoom, ch * zoom), Image.NEAREST)
        f = d / f"crop_{t:07.2f}_{x}_{y}_{cw}x{ch}.png"; im.save(f); files.append(f)
    for f in files:
        print(" ", f)
    return files


def parse_srt(text, voice=True):
    items = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "").strip()):
        m = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", block)
        if not m:
            continue
        g = m.groups()
        s = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 10 ** len(g[3])
        e = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 10 ** len(g[7])
        items.append({"text": block[m.end():].strip(), "start": s, "end": e, "voice": voice})
    return items


def load_texts(path, voice=True):
    p = Path(path)
    if p.suffix.lower() == ".srt":
        return parse_srt(p.read_text(encoding="utf-8-sig"), voice)
    d = json.loads(p.read_text())
    rows = d.get("texts", d.get("items", [])) if isinstance(d, dict) else d
    return [{"text": x["text"], "start": float(x.get("start", x.get("t0"))), "end": float(x.get("end", x.get("t1"))),
             "voice": bool(x.get("voice", False)), "kind": x.get("kind", "")} for x in rows]


def chars(s):
    return len(re.sub(r"\s", "", s))


def read_check(items, cps=5.0, cps_voice=10.0, mn=1.0, mn_voice=0.5):
    """読み切れないかもしれない文字の一覧。声と一緒に出る文字は耳でも分かるので速くてよい"""
    bad = []
    for it in items:
        v = it.get("voice", False)
        need = max(mn_voice if v else mn, chars(it["text"]) / (cps_voice if v else cps))
        shown = it["end"] - it["start"]
        if shown + 0.05 < need:
            bad.append(dict(it, shown=round(shown, 2), need=round(need, 2)))
    return bad


def print_read(bad, total):
    print(f"■ 読み切れないかもしれない文字（{total} 個のうち {len(bad)} 個・短すぎる順）")
    bad = sorted(bad, key=lambda b: b["shown"] / b["need"])
    for b in bad[:40]:
        kind = f"[{b['kind']}] " if b.get("kind") else ""
        print(f" - {tc(b['start'])} {kind}「{b['text'][:30]}」 {b['shown']}秒（読むのに約{b['need']}秒）")
    if len(bad) > 40:
        print(f"   ほか {len(bad) - 40} 個")
    if not bad:
        print(" - なし")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("cuts"); s.add_argument("video"); s.add_argument("--cuts"); s.add_argument("--scene", type=float, default=0.15); s.add_argument("--out")
    s = sp.add_parser("fast"); s.add_argument("video"); s.add_argument("--top", type=int, default=3); s.add_argument("--cuts"); s.add_argument("--scene", type=float, default=0.15); s.add_argument("--out")
    s = sp.add_parser("strip"); s.add_argument("video"); s.add_argument("a", type=float); s.add_argument("b", type=float); s.add_argument("--out")
    s = sp.add_parser("crop"); s.add_argument("video"); s.add_argument("times"); s.add_argument("box"); s.add_argument("--zoom", type=int, default=1); s.add_argument("--out")
    s = sp.add_parser("read"); s.add_argument("file"); s.add_argument("--no-voice", action="store_true")
    s.add_argument("--cps", type=float, default=5.0); s.add_argument("--cps-voice", type=float, default=10.0)
    s.add_argument("--min", type=float, default=1.0); s.add_argument("--min-voice", type=float, default=0.5)
    a = ap.parse_args(argv)
    if a.cmd == "cuts":
        cuts(a.video, load_segments(a.cuts) if a.cuts else None, a.out, a.scene)
    elif a.cmd == "fast":
        fast(a.video, a.top, load_segments(a.cuts) if a.cuts else None, a.scene, a.out)
    elif a.cmd == "strip":
        if a.b - a.a > 10:
            sys.exit("10 秒までにしてください（全コマを並べるので長いと見きれない）")
        f = strip(a.video, a.a, a.b, a.out)
        if f:
            print(" ", f)
    elif a.cmd == "crop":
        box = [int(v) for v in a.box.split(",")]
        if len(box) != 4:
            sys.exit("x,y,w,h の 4 つの数で指定してください")
        crop(a.video, [float(t) for t in a.times.split(",")], box, a.zoom, a.out)
    elif a.cmd == "read":
        items = load_texts(a.file, voice=not a.no_voice)
        print_read(read_check(items, a.cps, a.cps_voice, a.min, a.min_voice), len(items))


if __name__ == "__main__":
    main()
