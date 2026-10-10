"""shots/ の短い映像をつなぎ、字幕・年号・乱れの演出・音を重ねて1本にする。
使い方: python3 assemble.py <回のフォルダ> <版> [--audio audio/mix_<版>.wav]
流れ：溶けてつながるカットのまとまり（塊）ごとに、溶かし＋字幕＋年号を焼き込む（塊は同時に作る）
      → 塊を順につなぎ、扉の前後と赤い語の瞬間に色ずれ・ノイズ・揺れ、全体に周辺減光と粒子 → 音を入れて書き出す
"""
import json, pathlib, subprocess, sys
from concurrent.futures import ProcessPoolExecutor
from common import (load_ep, FF, FFPROBE, W, H, FPS, CH, BAR, subtitle_image, split_subtitles, shows_telop,
                    subtitle_bar_image, year_bar_image, key_telop_layout, can_vertical)
from shots import XF, ENC
import resource
# 1つの塊で数百の素材を同時に開くので、開けるファイル数の上限を上げる（macOS の既定は256）
_soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE, (min(10240, _hard if _hard > 0 else 10240), _hard))


MAXSHOTS = 30   # 1つの塊に入れるカットの上限（多すぎると ffmpeg が極端に遅くなる。境目は溶かさず切り替える）


def chunks_of(seq):
    out, cur = [], []
    for s in seq:
        cur.append(s)
        if not s["dissolve"] or len(cur) >= MAXSHOTS:
            if s["dissolve"]:   # 途中で切るときは、この塊の最後のカットの溶け分を落とす
                s = dict(s, dissolve=False, len=round(s["len"] - XF, 3)); cur[-1] = s
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return out


def build_chunk(args):
    ep_dir, k, chunk, lines, years = args
    ep = pathlib.Path(ep_dir)
    out = ep / "chunks" / f"c{k:03d}.mp4"
    t0 = chunk[0]["start"]
    clen = sum(s["len"] - (XF if s["dissolve"] else 0) for s in chunk)
    inputs, fl = [], []
    for i, s in enumerate(chunk):
        inputs += ["-i", str(ep / "shots" / f"{s['idx']:04d}.mp4")]
    if len(chunk) == 1:
        fl.append(f"[0:v]trim=0:{clen:.3f},setpts=PTS-STARTPTS[v0]")
    else:
        prev, off = "0:v", 0.0
        for i in range(1, len(chunk)):
            off += chunk[i - 1]["len"] - XF
            fl.append(f"[{prev}][{i}:v]xfade=transition=fade:duration={XF}:offset={off:.3f}[x{i}]")
            prev = f"x{i}"
        fl.append(f"[{prev}]trim=0:{clen:.3f},setpts=PTS-STARTPTS[v0]")
    fl.append(f"[v0]pad={W}:{H}:0:{BAR}:black[v]")   # 上下の黒帯（シネスコ）を足す
    cur, n = "v", len(chunk)
    is_card = chunk[0]["kind"] == "card"
    ov = []
    if not is_card:
        for L in lines:
            if not (t0 - 0.01 <= L["start"] < t0 + clen):
                continue
            if L.get("show_telop"):   # 演出テロップ（置き方は行ごとに left/center/right/vertical）
                a = L["start"] - t0 + 0.05
                b = min(L["hide"] - t0, clen) - 0.02
                ov.append((ep / "cache/cap" / f"{L['id']}.png", L["cap_xy"], a, b, 0.35 if L["cap_anim"] == "fade" else 0.3, L["cap_anim"]))
            for si, (sa, sb) in enumerate(L["subs_t"]):   # 通常テロップ（下の黒帯・すっと出る）
                ov.append((ep / "cache/sub" / f"{L['id']}_{si}.png", L["subs_xy"][si], sa - t0, min(sb - t0, clen) - 0.01, 0.1, None))
        for (ya, yb, yv) in years:
            a, b = max(ya, t0) - t0, min(yb, t0 + clen) - t0
            if yv and b - a > 0.05:
                ov.append((ep / "cache/year" / f"{yv}.png", year_bar_image(yv)[1], a, b, 0.0, None))
    ov = [o for o in ov if o[3] - o[2] >= 0.05]   # 出る時間が無いものは入力に加えない（番号がずれないように先に落とす）
    for j, (png, (x, y), a, b, fd, anim) in enumerate(ov):
        # 表示する間だけの長さで読み込み、出る時刻へずらす（全体の長さで回すより大幅に軽い）
        d = b - a
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{d:.3f}", "-i", str(png)]
        idx = n + j
        fade = f",fade=t=in:st=0:d={fd}:alpha=1,fade=t=out:st={max(0, d - fd):.3f}:d={fd}:alpha=1" if fd else ""
        fl.append(f"[{idx}:v]format=rgba{fade},setpts=PTS+{a:.3f}/TB[p{j}]")
        k = f"max(0,1-(t-{a:.3f})/0.35)^2"   # 出始めの0.35秒だけ動く
        xs = {"slideL": f"'{x}-36*{k}'", "slideR": f"'{x}+36*{k}'"}.get(anim, str(x))
        ys = f"'{y}-26*{k}'" if anim == "drop" else str(y)
        fl.append(f"[{cur}][p{j}]overlay=x={xs}:y={ys}:eof_action=pass:repeatlast=0[o{j}]")
        cur = f"o{j}"
    fl.append(f"[{cur}]format=yuv420p[out]")
    r = subprocess.run([FF, "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fl), "-map", "[out]", "-t", f"{clen:.3f}", *ENC, str(out)],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"塊 {k}（素材 {len(inputs)//2} 個）の作成に失敗: {r.stderr[-800:]}")
    return str(out), clen


def prepare_overlays(ep, S, TL):
    """字幕・演出テロップ・年号の画像を cache/ に作り、出す時刻を付けた行と年号の区間を返す（書き出しとプレビューで共用）。"""
    (ep / "cache/cap").mkdir(parents=True, exist_ok=True); (ep / "cache/year").mkdir(parents=True, exist_ok=True)
    # 字幕・年号の画像
    lines = TL["lines"]
    latest = {x["id"]: x for x in S["lines"]}
    for L in lines:
        for key in ("caption", "red", "fx"):
            if key in latest.get(L["id"], {}):
                L[key] = latest[L["id"]][key]
    (ep / "cache/sub").mkdir(parents=True, exist_ok=True)
    subs = json.loads((ep / "subs.json").read_text()) if (ep / "subs.json").exists() else {}
    if subs:
        bad = [k for k, v in subs.items() if any(c in v for c in "、。，．！？!?")]
        if bad:
            raise SystemExit(f"通常テロップに句読点が入っています: {bad[:5]}")
    cycle, ptr = ["left", "center", "right", "vertical"], 0
    for i, L in enumerate(lines):
        nxt = lines[i + 1]["start"] if i + 1 < len(lines) else TL["duration"]
        L["hide"] = min(nxt - 0.05, L["end"] + 0.6)
        L["show_telop"] = shows_telop(L, S)
        if L["show_telop"]:
            # 置き方：script の telop_pos があればそれ、無ければ 左上→中央→右下→縦書き を順に回す（合わない置き方は飛ばす）
            pos = latest.get(L["id"], {}).get("telop_pos")
            while not pos:
                c = cycle[ptr % 4]; ptr += 1
                if (c == "vertical" and not can_vertical(L["caption"])) or (c == "center" and len(L["caption"]) > 14):
                    continue
                pos = c
            im, xy, anim = key_telop_layout(L["caption"], L.get("red"), pos)
            im.save(ep / "cache/cap" / f"{L['id']}.png"); L["cap_xy"], L["cap_anim"] = xy, anim
        if S.get("subtitles", True) is False:   # 通常テロップ（語り字幕）を出さない回
            L["subs_t"], L["subs_xy"] = [], []
            continue
        if subs.get(L["id"]):   # 要約した通常テロップ（subs.json）：下の黒帯に1行。句読点なし
            rows = [r for r in subs[L["id"]].split("\n") if r.strip()]
            joined = "　".join(rows)
            # 1行で収まる長さ（30字まで）ならそのまま1行、長ければ行ごとに順に出す（時間は字数で按分）
            pieces = [joined] if len(joined) <= 30 else rows
            end_all = min(L["end"] + 0.35, nxt - 0.03)
            tot = sum(len(p) for p in pieces)
            t, L["subs_t"], L["subs_xy"] = L["start"], [], []
            for si, p in enumerate(pieces):
                e = end_all if si + 1 == len(pieces) else t + (L["end"] - L["start"]) * len(p) / tot
                im, xy = subtitle_bar_image(p)
                im.save(ep / "cache/sub" / f"{L['id']}_{si}.png")
                L["subs_t"].append((t, e)); L["subs_xy"].append(xy); t = e
            continue
        # 語り字幕：句読点で区切り、字数に比例した時間で出す
        pieces = split_subtitles(L["text"])
        tot = sum(len(p) for p in pieces) or 1
        t, L["subs_t"], L["subs_xy"] = L["start"], [], []
        for k, p in enumerate(pieces):
            dt = (L["end"] - L["start"]) * len(p) / tot
            end = t + dt if k + 1 < len(pieces) else min(L["end"] + 0.25, nxt - 0.02)
            im, xy = subtitle_image(p)
            im.save(ep / "cache/sub" / f"{L['id']}_{k}.png")
            L["subs_t"].append((t, end)); L["subs_xy"].append(xy); t += dt
    years, cur = [], None
    for L in lines:
        y = L.get("year") or ""
        s0 = L["start"] - (0.15 if L["sec"] != "digest" else 0)
        if cur is None or cur[2] != y:
            if cur:
                cur[1] = s0
            cur = [s0, TL["duration"], y]; years.append(cur)
    for (_, _, y) in years:
        if y:
            year_bar_image(y)[0].save(ep / "cache/year" / f"{y}.png")
    return lines, years


def main():
    ep_dir, ver = sys.argv[1], sys.argv[2]
    ep, S = load_ep(ep_dir)
    if "--audio" in sys.argv:
        audio = sys.argv[sys.argv.index("--audio") + 1]
    else:
        cands = [ep / f"audio/mix_{ver}.wav"] + sorted((ep / "audio").glob("mix_*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
        found = [c for c in cands if c.exists()]
        if not found and "--no-audio" not in sys.argv:
            raise SystemExit("音のファイル（audio/mix_*.wav）がありません。audio.py mix を先に流すか --no-audio を付けてください")
        audio = str(found[0].relative_to(ep)) if found else None
        print("音:", audio)
    TL = json.loads((ep / "timeline.json").read_text())
    seq = json.loads((ep / "shots_plan.json").read_text())
    (ep / "chunks").mkdir(exist_ok=True)
    lines, years = prepare_overlays(ep, S, TL)
    chunks = chunks_of(seq)
    jobs = [(str(ep), k, ch, lines, years) for k, ch in enumerate(chunks)]
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(build_chunk, jobs))
    # つなぐ（最初の黒い間を足す）
    lst = ep / "chunks/list.txt"
    pad = seq[0]["start"]
    subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={pad:.3f}", *ENC, str(ep / "chunks/pad.mp4")], check=True)
    lst.write_text("file 'pad.mp4'\n" + "".join(f"file '{pathlib.Path(r[0]).name}'\n" for r in res))
    # 乱れを入れる時刻：塊の境目（扉の前後）と、赤い語の瞬間
    bounds, t = [], pad
    for (_, clen) in res:
        t += clen; bounds.append(t)
    hits = [b for b in bounds[:-1]]
    for L in lines:
        if L.get("red") and L.get("show_telop"):
            k = L["text"].find(L["red"])
            if k >= 0:
                hits.append(L["start"] + (L["end"] - L["start"]) * k / max(1, len(L["text"])))
    g = "+".join(f"between(t,{h-0.10:.3f},{h+0.10:.3f})" for h in sorted(hits)) or "0"
    vf = (f"rgbashift=rh=-12:bh=12:enable='{g}',noise=alls=36:allf=t:enable='{g}',"
          f"crop=w=iw-24:h=ih-24:x='12+if({g},random(1)*24-12,0)':y='12+if({g},random(2)*24-12,0)',scale={W}:{H},"
          f"vignette=PI/5.5,noise=alls=5:allf=t,format=yuv420p")
    out = ep / "exports" / f"{S.get('slug', 'ep')}_{ver}.mp4"
    out.parent.mkdir(exist_ok=True)
    cmd = [FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst)]
    fc = f"[0:v]{vf}[v]"
    if audio:
        cmd += ["-i", str(ep / audio), "-filter_complex", fc, "-map", "[v]", "-map", "1:a", "-c:a", "aac", "-b:a", "256k", "-shortest"]
    else:
        cmd += ["-filter_complex", fc, "-map", "[v]"]
    # 書き出しは YouTube の 1080p 推奨（8〜12Mbps）に合わせて 10Mbps
    cmd += ["-c:v", "h264_videotoolbox", "-b:v", "10M", "-maxrate", "14M", "-bufsize", "20M", "-pix_fmt", "yuv420p", "-r", "30",
            "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    kinds = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True).stdout.split()
    if audio and "audio" not in kinds:
        raise SystemExit(f"書き出しに音が入っていません: {out}")
    print("wrote", out, "streams:", ",".join(kinds))


if __name__ == "__main__":
    main()
