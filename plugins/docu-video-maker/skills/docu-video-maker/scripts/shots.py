"""時刻表の各カットと扉を、1本ずつの短い映像（shots/NNN.mp4）にする。同時に何本も作る。
使い方: python3 shots.py <回のフォルダ> [--only 12,13] [--workers 6]
素材の置き場（回のフォルダ内）: assets/img/<場面ID>.(png|jpg)  assets/vid/<場面ID>.mp4
場面の種類（script.json の scenes[].kind）:
  pd / ai_image : 静止画。横長は深度で立体的に動かす。縦長（肖像画など）はぼかした地の上に額のように置いて寄る
  ai_video      : 動画（無ければ同名の静止画で代用）
  map           : maps.py で地図を描く
  black         : 黒
"""
import json, math, os, sys, pathlib, subprocess
from concurrent.futures import ProcessPoolExecutor
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from common import load_ep, FF, FFPROBE, W, FPS, font, WHITE, RED, decoded, shadowed, BAR
from common import CH as H   # カットは上下の黒帯を除いた帯（1920×816）で作る。帯は assemble.py で足す

XF = 0.25  # 次のカットへ溶ける長さ（各カットの尻にこの分だけ余分に作る）
ENC = ["-c:v", "h264_videotoolbox", "-b:v", "18M", "-pix_fmt", "yuv420p", "-r", str(FPS)]
MOTIONS = ["push", "panR", "pull", "panL", "tilt", "push2"]


def find_asset(ep, scene, kind):
    d = ep / "assets" / kind
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".mp4"):
        p = d / f"{scene}{ext}"
        if p.exists():
            return p
    return None


def pipe_writer(out, w=W, h=H):
    cmd = [FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-", *ENC, str(out)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


def ease(x):
    return 0.5 - 0.5 * math.cos(math.pi * min(1, max(0, x)))


# ---------- 静止画 ----------
_depth_model = None


def _device():
    import torch
    return "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")


def depth_of(img_path, cache):
    """深度マップ（1=近い）。cache に PNG で残す。"""
    if cache.exists():
        return np.asarray(Image.open(cache), dtype=np.float32) / 255.0
    global _depth_model
    try:
        import torch
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    except ImportError:   # 深度推定の部品が無い：立体化をやめ、平らな深度（寄り・パンだけ）にする
        with Image.open(img_path) as im:
            return np.full((im.height, im.width), 0.5, np.float32)
    if _depth_model is None:
        name = "depth-anything/Depth-Anything-V2-Small-hf"   # Apache-2.0
        _depth_model = (AutoImageProcessor.from_pretrained(name), AutoModelForDepthEstimation.from_pretrained(name).to(_device()).eval())
    proc, model = _depth_model
    img = Image.open(img_path).convert("RGB")
    with torch.no_grad():
        d = model(**proc(images=img, return_tensors="pt").to(_device())).predicted_depth
    d = torch.nn.functional.interpolate(d.unsqueeze(1), size=img.size[::-1], mode="bicubic", align_corners=False).squeeze().cpu().numpy()
    d = (d - d.min()) / (d.max() - d.min() + 1e-9)
    cache.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((d * 255).astype(np.uint8)).save(cache)
    return d.astype(np.float32)


def fill_16x9(img, scale=1.18):
    """16:9 の画面を覆う大きさ（余白 scale 倍）に拡大した RGB 配列。"""
    w, h = img.size
    k = max(W * scale / w, H * scale / h)
    return img.resize((int(w * k), int(h * k)), Image.LANCZOS)


def tone(img):
    """画調をそろえる：明るすぎる白（版画の紙など）を抑え、少し暖かくする。"""
    a = np.asarray(img, dtype=np.float32) / 255.0
    a = np.power(a, 1.18) * 0.90
    a[..., 0] *= 1.03; a[..., 2] *= 0.94
    return Image.fromarray((a.clip(0, 1) * 255).astype(np.uint8))


def render_still(img_path, out, dur, motion, part, depth_cache, amp=36):
    import cv2
    img = tone(Image.open(img_path).convert("RGB"))
    ar = img.width / img.height
    n = int(round(dur * FPS))
    p = pipe_writer(out)
    if ar < 1.3 and part == 0 and MOTIONS.index(motion) % 2 == 1:
        # 縦長（その2）：横幅いっぱいに広げ、上から下へゆっくりなめる（顔は上の方にあることが多いので上寄り）
        bw = int(W * 1.04); bh = int(bw / ar)
        arr = np.asarray(img.resize((bw, bh), Image.LANCZOS))
        ya, yb = (0.30, 0.42) if motion != "panL" else (0.42, 0.30)
        for i in range(n):
            e = ease(i / max(1, n - 1))
            cy = bh * (ya + (yb - ya) * e)
            cy = min(max(cy, H / 2), bh - H / 2)
            M = np.float32([[1, 0, -(bw - W) / 2], [0, 1, H / 2 - cy]])
            p.stdin.write(cv2.warpAffine(arr, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT).tobytes())
    elif ar < 1.3:
        # 縦長：ぼかした地＋額のように置いた絵。ゆっくり寄る
        bg = fill_16x9(img, 1.1).filter(ImageFilter.GaussianBlur(28))
        bg = Image.eval(bg, lambda v: int(v * 0.38))
        bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
        fh = int(H * 0.88); fw = int(fh * ar)
        fg = img.resize((fw, fh), Image.LANCZOS)
        # 額の位置：part ごと（part 0 は動きの種類ごと）に中央・左寄り・右寄りを変える
        fx0 = (W - fw) // 2 + [0, -int(W * 0.2), int(W * 0.2)][(MOTIONS.index(motion) if part == 0 else part) % 3]
        fy0 = (H - fh) // 2 + 20
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rectangle([fx0 + 10, fy0 - 6, fx0 + fw + 10, fy0 + fh - 6], fill=(0, 0, 0, 200))
        shadow = shadow.filter(ImageFilter.GaussianBlur(18))
        base = bg.convert("RGBA"); base.alpha_composite(shadow)
        base.paste(fg, (fx0, fy0))
        base = np.asarray(base.convert("RGB"))
        cxf = fx0 + fw / 2   # 寄る中心＝額の中心
        # part ごとに構図を変える：全体で寄る → 顔のあたりへ大きく寄る → 引く …
        z0, z1, fy = [(1.0, 1.08, 0.5), (1.55, 1.68, 0.30), (1.10, 1.0, 0.5), (1.35, 1.45, 0.62)][part % 4]
        for i in range(n):
            e = ease(i / max(1, n - 1)); z = z0 + (z1 - z0) * e
            cy = H * fy
            M = np.float32([[z, 0, cxf * (1 - z)], [0, z, H / 2 - cy * z]])   # 横は額の中心を軸に寄る（額の位置を保つ）
            p.stdin.write(cv2.warpAffine(base, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT).tobytes())
    else:
        # 横長：深度で立体的に動かす。part>0 は寄った別の構図
        big = fill_16x9(img, [1.18, 1.6, 1.6, 1.45][part % 4])
        arr = np.asarray(big)
        d = depth_of(img_path, depth_cache)
        d = cv2.resize(d, (big.width, big.height))
        d = cv2.GaussianBlur(d, (0, 0), 3)
        bh, bw = arr.shape[:2]
        # 画面に出す窓の中心（part ごとに場所を変える）
        ox, oy = [(0, 0), (-0.3, -0.12), (0.3, 0.05), (0, -0.25)][part % 4]
        cx0 = bw / 2 + (bw - W) * ox
        cy0 = bh / 2 + (bh - H) * oy
        gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
        for i in range(n):
            e = ease(i / max(1, n - 1))
            z, tx, ty, par = {"push": (1.0 + 0.08 * e, 0, 0, (e - 0.5)), "push2": (1.0 + 0.06 * e, 0, 0, -(e - 0.5)),
                              "pull": (1.08 - 0.08 * e, 0, 0, (e - 0.5)), "panR": (1.03, (e - 0.5) * 120, 0, (e - 0.5)),
                              "panL": (1.03, -(e - 0.5) * 120, 0, -(e - 0.5)), "tilt": (1.04, 0, -(e - 0.5) * 70, 0.0)}[motion]
            sx = cx0 + tx + (gx - W / 2) / z
            sy = cy0 + ty + (gy - H / 2) / z
            dd = cv2.remap(d, sx, sy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            sx2 = (sx - par * 2 * amp * (dd - 0.5)).astype(np.float32)
            p.stdin.write(cv2.remap(arr, sx2, sy.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT).tobytes())
    p.stdin.close(); p.wait()


def render_video(vid, out, dur, motion):
    src_d = float(subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(vid)],
                                 capture_output=True, text=True).stdout)
    usable = max(1.0, src_d - 0.15)
    k = max(1.0, dur / usable)   # 足りなければゆっくりにする
    z1 = 1.06 if motion in ("push", "push2") else 1.0
    vf = (f"setpts={k:.4f}*PTS,fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"scale=w='{W}*(1+{z1-1:.3f}*t/{dur:.3f})':h=-2:eval=frame,crop={W}:{H},setsar=1")
    wh = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(vid)],
                        capture_output=True, text=True).stdout.split()[0].split(",")
    if int(wh[0]) / int(wh[1]) < 1.3:
        # 縦長の動画：ぼかして暗くした地の上に、高さいっぱいで全体を置く
        vf = (f"setpts={k:.4f}*PTS,fps={FPS},split[a][b];"
              f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=28:2,eq=brightness=-0.22[bg];"
              f"[b]scale=-2:{int(H * 0.94)}[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,"
              f"scale=w='{W}*(1+0.04*t/{dur:.3f})':h=-2:eval=frame,crop={W}:{H},setsar=1")
    subprocess.run([FF, "-v", "error", "-y", "-i", str(vid), "-t", f"{dur:.3f}", "-filter_complex" if "split" in vf else "-vf", vf, "-an", *ENC, str(out)], check=True)


def render_placeholder(out, dur, sc, meta):
    im = Image.new("RGB", (W, H), (22, 24, 30)); d = ImageDraw.Draw(im)
    d.rectangle([60, 60, W - 60, H - 60], outline=(70, 74, 86), width=3)
    d.text((120, 380), f"［生成前］{meta.get('kind', '')}  {sc}", font=font(44, 3), fill=(150, 150, 160))
    desc = meta.get("desc", "")
    for k in range(0, min(len(desc), 120), 30):
        d.text((120, 470 + k // 30 * 70), desc[k:k + 30], font=font(52), fill=(205, 200, 190))
    im.save(out.with_suffix(".png"))
    subprocess.run([FF, "-v", "error", "-y", "-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", str(out.with_suffix(".png")),
                    "-vf", "format=yuv420p", *ENC, str(out)], check=True)
    out.with_suffix(".png").unlink()


def render_black(out, dur):
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={dur:.3f}", *ENC, str(out)], check=True)


# ---------- 扉（題字・章・締め） ----------
def render_card(card, out, S, ep, dur):
    n = int(round(dur * FPS))
    p = pipe_writer(out)
    bg_path = find_asset(ep, S.get("title_bg", "T_title"), "img")
    bg = None
    if bg_path:
        bg = fill_16x9(Image.open(bg_path).convert("RGB"), 1.08)
        bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
    noise = np.random.default_rng(1).integers(0, 255, (H // 8, W // 8), dtype=np.uint8)
    fog = Image.fromarray(noise).resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(40))
    fog = np.asarray(fog, dtype=np.float32) / 255.0
    for i in range(n):
        t = i / FPS
        if card["type"] == "title" and bg is not None:
            z = 1.0 + 0.05 * t / dur
            frame = bg.resize((int(W * z), int(H * z)), Image.BILINEAR)
            frame = frame.crop(((frame.width - W) // 2, (frame.height - H) // 2, (frame.width - W) // 2 + W, (frame.height - H) // 2 + H))
            frame = Image.eval(frame, lambda v: int(v * 0.55)).convert("RGBA")
        else:
            shift = int(t * 30) % W
            f = np.roll(fog, shift, axis=1)
            base = (np.stack([f * 18 + 6, f * 20 + 7, f * 26 + 11], -1)).astype(np.uint8)
            frame = Image.fromarray(base).convert("RGBA")
        lay = []
        if card["type"] == "title":
            lay = [(S.get("series", ""), font(40, 3), (230, 222, 205), 330 - BAR, 0.4, None),
                   (S["title_main"], font(150), WHITE, 470 - BAR, 0.0, "decode"),
                   (S.get("title_sub", ""), font(58), WHITE, 650 - BAR, 0.9, None)]
        elif card["type"] == "chapter":
            parts = card["label"].split("　")
            if len(parts) > 1:
                lay.append((parts[0], font(40), RED, 420 - BAR, 0.0, None))
            lay.append((parts[-1], font(140), WHITE, 520 - BAR, 0.12, "decode"))
        else:
            lay = [(S.get("series", ""), font(40, 3), (210, 205, 195), 600 - BAR, 0.4, None),
                   (S["title_main"], font(110), WHITE, 470 - BAR, 0.1, None)]
        for text, fnt, col, y, delay, mode in lay:
            if not text or t < delay:
                continue
            s = decoded(text, t, delay, 0.06, 0.10) if mode == "decode" else text
            a = min(1.0, (t - delay) / 0.35)
            if t > dur - 0.35:
                a *= max(0.0, (dur - t) / 0.35)
            probe = ImageDraw.Draw(frame)
            tw = probe.textlength(text, font=fnt)
            if tw > W - 220:   # 画面からはみ出す長さなら縮める
                fnt = ImageFont.truetype(fnt.path, int(fnt.size * (W - 220) / tw), index=fnt.index)
                tw = probe.textlength(text, font=fnt)

            def draw(d, dx, dy, ov, s=s, fnt=fnt, col=col, tw=tw, y=y):
                d.text(((W - tw) / 2 + dx, y + dy), s, font=fnt, fill=ov or col)
            layer = shadowed((W, H), draw, blur=10)
            if a < 1:
                layer.putalpha(Image.eval(layer.getchannel("A"), lambda v, a=a: int(v * a)))
            frame.alpha_composite(layer)
        if card["type"] == "chapter" and t > 0.3:
            k = ease((t - 0.3) / 0.5)
            ImageDraw.Draw(frame).line([(960 - 220 * k, 690 - BAR), (960 + 220 * k, 690 - BAR)], fill=RED, width=3)
        p.stdin.write(np.asarray(frame.convert("RGB")).tobytes())
    p.stdin.close(); p.wait()


# ---------- 振り分け ----------
def job(args):
    kind, ep_dir, item, idx, dur = args
    ep, S = load_ep(ep_dir)
    out = ep / "shots" / f"{idx:04d}.mp4"
    if out.exists():
        return str(out)
    out.parent.mkdir(exist_ok=True)
    if kind == "card":
        render_card(item, out, S, ep, dur)
        return str(out)
    sc = item["scene"]
    meta = S["scenes"].get(sc, {})
    motion = MOTIONS[idx % len(MOTIONS)]
    # カット表（shotlist.json）でこのカットに別の絵・動画が当てられていれば、それを使う（同じ絵の撮り直しを避ける）
    if item.get("asset"):
        a = item["asset"]
        if a.startswith("map:"):
            import maps
            maps.render_map(S["scenes"][a[4:]], out, dur)
            return str(out)
        vid = find_asset(ep, a, "vid")
        if vid:
            render_video(vid, out, dur, motion)
        else:
            img = find_asset(ep, a, "img")
            if img is None:
                raise FileNotFoundError(f"素材が無い: {a}（カット {idx}）")
            render_still(img, out, dur, motion, 0, ep / "cache/depth" / f"{a}.png")
        return str(out)
    k = meta.get("kind", "ai_image")
    if k == "black":
        render_black(out, dur)
    elif k == "map":
        import maps
        maps.render_map(meta, out, dur)
    else:
        vid = find_asset(ep, sc, "vid") if k == "ai_video" else None
        if vid and item.get("part", 0) == 0:
            render_video(vid, out, dur, motion)
        else:
            img = find_asset(ep, sc, "img")
            if img is None:
                if os.environ.get("PLACEHOLDER"):   # 仮組み：生成前の場面は説明を書いた仮の絵にする
                    render_placeholder(out, dur, sc, meta)
                    return str(out)
                raise FileNotFoundError(f"素材が無い: {sc}")
            render_still(img, out, dur, motion, item.get("part", 0), ep / "cache/depth" / f"{sc}.png")
    return str(out)


def plan(ep_dir):
    """組み立ての順番（扉とカットを時刻順に並べ、各要素の番号・次へ溶けるか）を返す。"""
    ep, S = load_ep(ep_dir)
    TL = json.loads((ep / "timeline.json").read_text())
    items = [("card", c) for c in TL["cards"]] + [("shot", s) for s in TL["shots"]]
    items.sort(key=lambda x: x[1]["start"])
    sl = ep / "shotlist.json"
    if sl.exists():   # カットごとの絵の割り当て（番号 → 素材ID）
        assign = {int(k): v for k, v in json.loads(sl.read_text()).items()}
        for i, (kind, it) in enumerate(items):
            if kind == "shot" and i in assign:
                it["asset"] = assign[i]
    seq = []
    for i, (kind, it) in enumerate(items):
        nxt = items[i + 1] if i + 1 < len(items) else None
        # 同じ節のカット同士は溶かしてつなぐ。扉の前後は切り替え（乱れ）でつなぐ
        dissolve = kind == "shot" and nxt is not None and nxt[0] == "shot" and nxt[1]["sec"] == it["sec"]
        end = nxt[1]["start"] if nxt else TL["duration"]
        seq.append({"idx": i, "kind": kind, "item": it, "dissolve": dissolve, "start": it["start"],
                    "len": round(end - it["start"] + (XF if dissolve else 0), 3)})
    return seq


def main():
    ep_dir = sys.argv[1]
    only = None
    if "--only" in sys.argv:
        only = {int(x) for x in sys.argv[sys.argv.index("--only") + 1].split(",")}
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 6
    seq = plan(ep_dir)
    (pathlib.Path(ep_dir) / "shots").mkdir(exist_ok=True)
    (pathlib.Path(ep_dir) / "shots_plan.json").write_text(json.dumps(seq, ensure_ascii=False, indent=0))
    jobs = [(s["kind"], ep_dir, s["item"], s["idx"], s["len"]) for s in seq if only is None or s["idx"] in only]
    # 深度推定は最初に1プロセスでまとめて作る（GPU を取り合わない）
    ep, S = load_ep(ep_dir)
    for kind, _, it, idx, _ in jobs:
        if kind == "shot":
            name = it.get("asset") or it["scene"]
            if name.startswith("map:") or (it.get("asset") and find_asset(ep, name, "vid")):
                continue
            meta = S["scenes"].get(it["scene"], {}) if not it.get("asset") else {"kind": "pd"}
            img = find_asset(ep, name, "img")
            if img and meta.get("kind") not in ("map", "black"):
                with Image.open(img) as im:
                    if im.width / im.height >= 1.3:
                        depth_of(img, ep / "cache/depth" / f"{name}.png")
    with ProcessPoolExecutor(workers) as ex:
        for r in ex.map(job, jobs):
            pass
    print(f"{len(jobs)} 本を作成")


if __name__ == "__main__":
    main()
