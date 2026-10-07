"""参考の YouTube チャンネル・動画を分析して、作風の手がかりを1つのフォルダにまとめる。
使い方:
  python3 analyze_reference.py <URL> [<URL> ...] --out <作業フォルダ>/reference [--video]
  URL はチャンネル（@handle や /channel/...）でも動画でもよい。
  --video を付けると、動画は 480p 以下を一時的に取得して、カットの切り替え間隔と10秒ごとのコマ一覧を作る（分析専用。映像は使い回さない）。
出力: reference/summary.md（人が読む）・reference/data.json・thumbs/*.jpg・sheets/*.jpg
"""
import json, pathlib, re, shutil, statistics, subprocess, sys, urllib.request
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import FF

YTDLP = shutil.which("yt-dlp") or "yt-dlp"


def ytj(url, *extra):
    r = subprocess.run([YTDLP, "--no-update", "-J", *extra, url], capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise RuntimeError(r.stderr[-400:])
    return json.loads(r.stdout)


def is_channel(url):
    return bool(re.search(r"youtube\.com/(@|channel/|c/|user/)", url)) and "watch?" not in url


def fetch(url, path):
    try:
        urllib.request.urlretrieve(url, path); return True
    except Exception:
        return False


def channel(url, out):
    base = re.sub(r"/(videos|shorts|streams|featured)/?$", "", url.rstrip("/"))
    meta = ytj(base, "--flat-playlist", "--playlist-items", "0")
    vids = ytj(base + "/videos", "--flat-playlist", "--playlist-end", "40")
    rows = [{"title": e.get("title"), "id": e.get("id"), "duration": e.get("duration"), "views": e.get("view_count")}
            for e in vids.get("entries", [])]
    av = next((t["url"] for t in meta.get("thumbnails", []) if t.get("id") == "avatar_uncropped"), None)
    if av:
        fetch(av, out / "thumbs" / "channel_avatar.jpg")
    for e in sorted([r for r in rows if r["views"]], key=lambda r: -r["views"])[:6]:   # よく見られている動画のサムネ
        fetch(f"https://i.ytimg.com/vi/{e['id']}/hqdefault.jpg", out / "thumbs" / f"{e['id']}.jpg")
    durs = [r["duration"] for r in rows if r["duration"]]
    return {"kind": "channel", "url": base, "name": meta.get("channel"), "description": meta.get("description", ""),
            "followers": meta.get("channel_follower_count"), "videos": rows,
            "median_duration_min": round(statistics.median(durs) / 60, 1) if durs else None}


def video(url, out, analyze):
    m = ytj(url)
    vid = m["id"]
    fetch(f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg", out / "thumbs" / f"{vid}.jpg") or \
        fetch(f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", out / "thumbs" / f"{vid}.jpg")
    d = {"kind": "video", "url": url, "id": vid, "title": m.get("title"), "channel": m.get("channel"),
         "duration_min": round((m.get("duration") or 0) / 60, 1), "views": m.get("view_count"),
         "chapters": [(round(c["start_time"]), c["title"]) for c in (m.get("chapters") or [])],
         "description": m.get("description", "")[:3000], "tags": m.get("tags", [])[:30]}
    if analyze:
        tmp = out / "_tmp"; tmp.mkdir(exist_ok=True)
        f = tmp / f"{vid}.mp4"
        # YouTube は既定の取得経路を 403 で拒むことがある。経路を替えて順に試す。結合には起動できる ffmpeg を渡す
        err = ""
        for client in (None, "mweb", "web_safari"):
            extra = ["--extractor-args", f"youtube:player_client={client}"] if client else []
            r = subprocess.run([YTDLP, "--no-update", *extra, "--ffmpeg-location", FF, "-f", "bv*[height<=480]+ba/b[height<=480]/worst",
                                "--merge-output-format", "mp4", "-o", str(f), url], capture_output=True, text=True, timeout=1800)
            if f.exists():
                break
            err = (r.stderr or "").strip().splitlines()[-1:] or ["不明"]
        if not f.exists():
            d["video_error"] = f"動画本体を取得できず、カット間隔とコマ一覧は無い: {err[0][:200]}"
        if f.exists():
            # カットの切り替え（画面の変化量が大きい瞬間）
            r = subprocess.run([FF, "-hide_banner", "-i", str(f), "-vf", "select='gt(scene,0.32)',showinfo", "-an", "-f", "null", "-"],
                               capture_output=True, text=True).stderr
            ts = [float(x) for x in re.findall(r"pts_time:([\d.]+)", r)]
            gaps = [b - a for a, b in zip([0.0] + ts, ts)]
            d["cuts"] = len(ts)
            d["median_shot_sec"] = round(statistics.median(gaps), 2) if gaps else None
            # 10秒ごとのコマを 5×6 の一覧に（最初の5分）
            (out / "sheets").mkdir(exist_ok=True)
            subprocess.run([FF, "-v", "error", "-y", "-t", "300", "-i", str(f), "-vf", "fps=1/10,scale=384:-2,tile=5x6",
                            "-frames:v", "1", str(out / "sheets" / f"{vid}.jpg")])
            f.unlink()
        shutil.rmtree(tmp, ignore_errors=True)
    return d


def main():
    urls = [a for a in sys.argv[1:] if a.startswith("http")]
    out = pathlib.Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else pathlib.Path("reference")
    (out / "thumbs").mkdir(parents=True, exist_ok=True)
    res = []
    for u in urls:
        try:
            res.append(channel(u, out) if is_channel(u) else video(u, out, "--video" in sys.argv))
        except Exception as e:
            res.append({"url": u, "error": str(e)[:300]})
    (out / "data.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    md = ["# 参考の分析", ""]
    for r in res:
        if r.get("error"):
            md += [f"## 取得できず: {r['url']}", r["error"], ""]; continue
        if r["kind"] == "channel":
            md += [f"## チャンネル: {r['name']}", f"- 登録者: {r.get('followers')}／動画の長さの中央値: {r.get('median_duration_min')}分",
                   "- 説明欄:", "", "```", r["description"][:1200], "```", "", "| 再生数 | 長さ(分) | タイトル |", "|---:|---:|---|"]
            for v in sorted(r["videos"], key=lambda v: -(v["views"] or 0))[:20]:
                md.append(f"| {v['views'] or ''} | {round((v['duration'] or 0) / 60, 1)} | {v['title']} |")
        else:
            md += [f"## 動画: {r['title']}", f"- チャンネル: {r['channel']}／長さ {r['duration_min']}分／再生数 {r['views']}"]
            if r.get("video_error"):
                md.append(f"- ⚠ {r['video_error']}（作風はサムネと説明欄からの推定になる。そう作り手に伝える）")
            if r.get("median_shot_sec"):
                md.append(f"- カットの切り替え: {r['cuts']}回・中央値 {r['median_shot_sec']}秒")
            if r["chapters"]:
                md.append("- チャプター: " + " / ".join(f"{t//60}:{t%60:02d} {c}" for t, c in r["chapters"]))
            md += ["- 説明欄（冒頭）:", "", "```", r["description"][:800], "```"]
        md.append("")
    md.append("サムネイルは thumbs/、コマの一覧は sheets/ にある。画像は必ず目で見て、構図・文字の置き方・色を読み取ること。")
    (out / "summary.md").write_text("\n".join(md))
    print(out / "summary.md")


if __name__ == "__main__":
    main()
