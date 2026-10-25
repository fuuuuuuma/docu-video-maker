"""書き出す前に、ブラウザでその場で再生して見る（プレビュー）。動画ファイルは作らない。
使い方: python3 preview.py <回> [--serve [ポート]]
読むもの: script.json・timeline.json・subs.json・shotlist.json・audio/lines・audio/bgm_*.mp3・assets/
出すもの: <回>/preview.html（と、地図のカットだけ preview/maps/ に短い映像）
  絵の動き・溶け・テロップ・年号・扉・効果音・BGM の下げ方を、書き出しと同じ時刻表で再生する。
  テロップと年号は書き出しと同じ画像（cache/）を使う。深度による立体化と画面の粒子は簡易版（書き出しで確かめる）。
  ブラウザは file:// では音を読めないので、--serve で回のフォルダを http で開く（既定のポート 8765）。
"""
import json, pathlib, re, shutil, sys
from concurrent.futures import ProcessPoolExecutor
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import load_ep, HOME, BAR, year_bar_image
import shots, assemble, audio


def _map_job(args):
    import maps
    meta, out, dur = args
    if not pathlib.Path(out).exists():
        maps.render_map(meta, pathlib.Path(out), dur)
    return out


def build(ep_dir):
    ep, S = load_ep(ep_dir)
    TL = json.loads((ep / "timeline.json").read_text())
    if TL.get("dry"):
        print("注意: timeline.json は仮の長さ（--dry）です。読み上げ後に timeline.py を流し直すと音と合います")
    seq = shots.plan(ep_dir)
    (ep / "shots_plan.json").write_text(json.dumps(seq, ensure_ascii=False, indent=0))
    lines, years = assemble.prepare_overlays(ep, S, TL)
    rel = lambda p: str(pathlib.Path(p).relative_to(ep))

    items, maps_todo = [], []
    for s in seq:
        it = s["item"]
        e = {"idx": s["idx"], "start": round(s["start"], 3), "len": s["len"], "dissolve": s["dissolve"]}
        if s["kind"] == "card":
            e.update(kind="card", type=it["type"], label=it.get("label", ""))
            items.append(e); continue
        a = it.get("asset") or it["scene"]
        meta = S["scenes"].get(a[4:] if a.startswith("map:") else a, {})
        motion = shots.MOTIONS[s["idx"] % len(shots.MOTIONS)]
        e.update(motion=motion, part=it.get("part", 0))
        done = ep / "shots" / f"{s['idx']:04d}.mp4"
        if a.startswith("map:") or (not it.get("asset") and meta.get("kind") == "map"):
            if done.exists():
                e.update(kind="video", src=rel(done), rate=1.0, still=True)
            else:
                out = ep / "preview" / "maps" / f"{s['idx']:04d}.mp4"
                maps_todo.append((meta, str(out), s["len"]))
                e.update(kind="video", src=rel(out), rate=1.0, still=True)
            items.append(e); continue
        if meta.get("kind") == "black" and not it.get("asset"):
            e.update(kind="black"); items.append(e); continue
        vid = shots.find_asset(ep, a, "vid")
        if vid and (it.get("asset") or (meta.get("kind") == "ai_video" and it.get("part", 0) == 0)):
            e.update(kind="video", src=rel(vid), still=False)
            items.append(e); continue
        img = shots.find_asset(ep, a, "img")
        if img is None:
            e.update(kind="missing", label=f"{a}　{meta.get('desc', '')}"[:80])
        else:
            with Image.open(img) as im:
                e.update(kind="image", src=rel(img), ar=round(im.width / im.height, 3))
        items.append(e)

    if maps_todo:
        (ep / "preview" / "maps").mkdir(parents=True, exist_ok=True)
        with ProcessPoolExecutor(min(6, len(maps_todo))) as ex:
            list(ex.map(_map_job, maps_todo))

    # テロップ・年号（書き出しと同じ画像と時刻）
    subs, caps = [], []
    for L in lines:
        for si, (sa, sb) in enumerate(L.get("subs_t", [])):
            x, y = L["subs_xy"][si]
            subs.append({"src": f"cache/sub/{L['id']}_{si}.png", "x": x, "y": y, "a": round(sa, 3), "b": round(sb, 3)})
        if L.get("show_telop"):
            x, y = L["cap_xy"]
            caps.append({"src": f"cache/cap/{L['id']}.png", "x": x, "y": y, "a": round(L["start"] + 0.05, 3),
                         "b": round(L["hide"], 3), "anim": L["cap_anim"]})
    yrs = []
    for (ya, yb, yv) in years:
        if yv:
            x, y = year_bar_image(yv)[1]
            yrs.append({"src": f"cache/year/{yv}.png", "x": x, "y": y, "a": round(ya, 3), "b": round(yb, 3)})

    # 音：読み上げは1文ずつ、BGM は声の間だけ下げる、効果音は書き出しと同じ位置
    voice = [{"src": f"audio/lines/{L['id']}.mp3", "start": L["start"], "in": L["src_in"], "out": L["src_out"]}
             for L in TL["lines"] if (ep / "audio/lines" / f"{L['id']}.mp3").exists()]
    b = S.get("bgm", {"provider": "elevenlabs"})
    bgm = None
    if b.get("provider") != "none":
        if b.get("file"):
            src = pathlib.Path(b["file"]).expanduser()
            if src.exists():
                dst = ep / "preview" / ("bgm" + src.suffix)
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.exists():
                    shutil.copy(src, dst)
                bgm = rel(dst)
        else:
            found = sorted((ep / "audio").glob("bgm_*.mp3"), key=lambda p: p.stat().st_mtime)
            found = [f for f in found if not re.search(r"_p\d+$", f.stem)]   # 区切りごとの部品（_p0…）は除く
            bgm = rel(found[-1]) if found else None
    sfx = []
    (ep / "preview" / "sfx").mkdir(parents=True, exist_ok=True)
    for n, t, g in audio.sfx_cues(S, TL):
        src = HOME / "sfx" / f"{n}.mp3"
        if not src.exists():
            continue
        dst = ep / "preview" / "sfx" / f"{n}.mp3"
        if not dst.exists():
            shutil.copy(src, dst)
        sfx.append({"src": rel(dst), "t": round(t, 3), "db": g - 6})
    hits = sorted({round(c["start"], 3) for c in TL["cards"]} | {round(c["end"], 3) for c in TL["cards"]} | {
        round(L["start"] + (L["end"] - L["start"]) * max(0, L["text"].find(L["red"])) / max(1, len(L["text"])), 3)
        for L in lines if L.get("red") and L.get("show_telop") and L["text"].find(L["red"]) >= 0})

    data = {"duration": TL["duration"], "items": items, "subs": subs, "caps": caps, "years": yrs, "voice": voice,
            "bgm": bgm, "sfx": sfx, "hits": hits, "xf": shots.XF, "bar": BAR,
            "hush": [[round(L["start"] - L["hush"], 3), round(L["start"], 3)] for L in TL["lines"] if L.get("hush")],
            "title": {"series": S.get("series", ""), "main": S.get("title_main", ""), "sub": S.get("title_sub", ""),
                      "bg": rel(shots.find_asset(ep, S.get("title_bg", "T_title"), "img")) if shots.find_asset(ep, S.get("title_bg", "T_title"), "img") else None},
            "chapters": [{"label": c.get("label") or ("題字" if c["type"] == "title" else "締め"), "start": c["start"]} for c in TL["cards"]]}
    html = (pathlib.Path(__file__).resolve().parent.parent / "assets" / "preview.html").read_text()
    out = ep / "preview.html"
    out.write_text(html.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False)))
    print(f"プレビュー: {out}（カット {sum(1 for i in items if i['kind'] != 'card')}・扉 {sum(1 for i in items if i['kind'] == 'card')}"
          f"・読み上げ {len(voice)}/{len(TL['lines'])}・BGM {'あり' if bgm else 'なし'}・効果音 {len(sfx)}）")
    miss = [i["label"] for i in items if i["kind"] == "missing"]
    if miss:
        print(f"素材が無いカット {len(miss)}（仮の文字で出す）: {miss[:3]}")
    return out


def serve(root, port=8765):
    """回のフォルダを http で配る。動画と音を途中から再生できるよう、Range（部分の読み出し）に答える。"""
    import http.server, functools, os

    class H(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send_head(self):
            # 名前の付け替え（DNS rebinding）で外のサイトから読まれないよう、宛先が手元の名前の要求だけに答える
            if self.headers.get("Host", "") not in (f"localhost:{port}", f"127.0.0.1:{port}"):
                self.send_error(403); return None
            rng = self.headers.get("Range")
            path = self.translate_path(self.path)
            if not rng or not os.path.isfile(path):
                return super().send_head()
            size = os.path.getsize(path)
            a, _, b = rng.replace("bytes=", "").partition("-")
            start = int(a) if a else max(0, size - int(b))
            end = int(b) if a and b else size - 1
            if start >= size:
                self.send_error(416); return None
            f = open(path, "rb"); f.seek(start)
            self.send_response(206)
            self.send_header("Content-Type", self.guess_type(path))
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self._left = end - start + 1
            return f

        def copyfile(self, src, dst):
            left = getattr(self, "_left", None)
            if left is None:
                return super().copyfile(src, dst)
            while left > 0:
                buf = src.read(min(1 << 20, left))
                if not buf:
                    break
                try:
                    dst.write(buf)
                except (BrokenPipeError, ConnectionResetError):
                    break
                left -= len(buf)

    h = functools.partial(H, directory=str(root))
    print(f"開く: http://localhost:{port}/preview.html （止めるときは Ctrl+C）", flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), h).serve_forever()


if __name__ == "__main__":
    ep_dir = sys.argv[1]
    build(ep_dir)
    if "--serve" in sys.argv:
        k = sys.argv.index("--serve")
        port = int(sys.argv[k + 1]) if len(sys.argv) > k + 1 and sys.argv[k + 1].isdigit() else 8765
        serve(pathlib.Path(ep_dir).resolve(), port)
