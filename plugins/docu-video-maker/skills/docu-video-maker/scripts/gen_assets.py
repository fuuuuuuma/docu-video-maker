"""Higgsfield 公式コマンドで、回の新しい絵・動画をまとめて作る（プランのクレジットを使う）。
使い方: python3 gen_assets.py <回> [--workers 6] [--dry]
読むもの: <回>/new_assets.json
  [{"id":"n_cradle_close","type":"image","prompt":"…","ref":["assets/img/v_empty_cradle.png"]},
   {"id":"nv_cradle_close","type":"video","prompt":"…","start":"assets/img/n_cradle_close.png"}]
  画像は assets/img/<id>.png、動画は assets/vid/<id>.mp4 に保存。既にあれば作らない。
  画調は script.json の "image_style"（無ければ18世紀ヨーロッパの歴史画）。
  現代の場面は項目に "era": "modern" を付ける（時代の画調を付けず、現代の服装を明示する。付けないとかつら姿になる）。
  動画の start が同じ一覧の画像なら、その画像ができてから作る。
記録: <回>/gen_log.jsonl（受付番号・費用・結果の URL）
"""
import json, os, pathlib, shutil, subprocess, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

# Higgsfield 公式の CLI。Homebrew の `hf` は Hugging Face の別物なので使わない
H = os.environ.get("HIGGSFIELD_CLI") or shutil.which("higgsfield") or "/opt/homebrew/opt/higgsfield/bin/higgsfield"
DEFAULT_STYLE = ("Cinematic historical oil painting in the manner of late 18th-century French academic history painting, dramatic chiaroscuro, "
         "dark moody palette of deep navy blue, charcoal and candle-gold with blood-red accents, visible painterly brushstrokes, "
         "subtle film grain, widescreen 16:9. No text, no letters, no captions, no watermark.")


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-400:] or r.stdout[-400:])
    return json.loads(r.stdout)


MODERN = (" Present-day scene: everyone wears modern clothing (suits, shirts, lab coats, glasses), modern haircuts, no wigs, "
          "no period costume. Painted as a dark cinematic oil painting with visible brushstrokes, deep navy and charcoal tones "
          "with cold blue light and small warm accents, film grain, widescreen 16:9. No text, no letters, no watermark.")


def make(ep, a, dry, style):
    out = ep / "assets" / ("img" if a["type"] == "image" else "vid") / f"{a['id']}.{'png' if a['type'] == 'image' else 'mp4'}"
    if out.exists():
        return a["id"], "exists", 0
    if a.get("era") == "modern":
        prompt = a["prompt"] + MODERN
    else:
        prompt = a["prompt"] if "oil painting" in a["prompt"] else a["prompt"] + " " + style
    if a["type"] == "image":
        cmd = [H, "generate", "create", "gpt_image_2_5", "--prompt", prompt, "--quality", "medium", "--resolution", "2k", "--aspect_ratio", "16:9"]
        for r in a.get("ref", []):
            cmd += ["--image-references", str(ep / r) if not r.count("-") == 4 else r]
        cost_model = ["gpt_image_2_5", "--quality", "medium", "--resolution", "2k"]
    else:
        start = ep / a["start"]
        for _ in range(120):   # 元の画像が並行で作られている途中なら待つ
            if start.exists():
                break
            time.sleep(10)
        cmd = [H, "generate", "create", "kling3_0", "--prompt", a["prompt"] + " Keep the painting style and composition, subtle natural motion, no text.",
               "--mode", "pro", "--duration", str(a.get("duration", 5)), "--sound", "off", "--start-image", str(start)]
        cost_model = ["kling3_0", "--mode", "pro", "--duration", str(a.get("duration", 5))]
    if dry:
        return a["id"], "dry", 0
    last = None
    for attempt in range(4):
        try:
            res = run(cmd + ["--wait", "--wait-timeout", "30m", "--json"])
            job = res[0] if isinstance(res, list) else res
            if job.get("status") != "completed":
                raise RuntimeError(f"status={job.get('status')}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(urllib.request.urlopen(job["result_url"], timeout=300).read())
            with open(ep / "gen_log.jsonl", "a") as f:
                f.write(json.dumps({"id": a["id"], "job": job.get("id"), "type": a["type"], "url": job["result_url"],
                                    "cost": 1.0 if a["type"] == "image" else 7.5 * a.get("duration", 5) / 5}, ensure_ascii=False) + "\n")
            return a["id"], "ok", 1
        except Exception as e:
            last = str(e)
            time.sleep(20 * (attempt + 1))
    return a["id"], "fail: " + (last or "")[:200], 0


def main():
    ep = pathlib.Path(sys.argv[1]).resolve()
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 6
    dry = "--dry" in sys.argv
    items = json.loads((ep / "new_assets.json").read_text())
    S = json.loads((ep / "script.json").read_text()) if (ep / "script.json").exists() else {}
    style = S.get("image_style", DEFAULT_STYLE)
    if not dry and not pathlib.Path(H).exists():
        raise SystemExit("Higgsfield の CLI が見つかりません。check_env.py の案内に従うか、HIGGSFIELD_CLI にパスを入れてください")
    imgs = [a for a in items if a["type"] == "image"]
    vids = [a for a in items if a["type"] == "video"]
    est = len([a for a in imgs if not (ep / "assets/img" / f"{a['id']}.png").exists()]) * 1.0 + \
        sum(7.5 * a.get("duration", 5) / 5 for a in vids if not (ep / "assets/vid" / f"{a['id']}.mp4").exists())
    print(f"作る数：画像 {len(imgs)}・動画 {len(vids)}（未作成ぶんの見込み {est:.0f} クレジット）")
    if dry:
        return
    fails = []
    with ThreadPoolExecutor(workers) as ex:
        for i, (aid, st, _) in enumerate(ex.map(lambda a: make(ep, a, dry, style), imgs + vids)):
            if not st in ("ok", "exists"):
                fails.append((aid, st))
            if i % 10 == 0:
                print(i, aid, st, flush=True)
    print("失敗", len(fails), fails[:10])


if __name__ == "__main__":
    main()
