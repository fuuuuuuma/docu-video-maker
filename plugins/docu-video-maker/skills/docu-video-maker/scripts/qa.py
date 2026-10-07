"""書き出した回を機械で検査し、目で見るためのコマ一覧を作る。
使い方: python3 qa.py <回のフォルダ> <版> [--every 6]
検査: 音の有無・音量（-14 LUFS 前後）・絵の帯の中の黒い区間・テロップの句読点・カット表の使い回し。
出力: <回>/qa/sheet_NN.jpg（N 秒ごとのコマを 4×8 に並べたもの）。**全部の一覧を目で見る**こと。
"""
import json, pathlib, re, shutil, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import FF, FFPROBE

PUNCT = "、。，．！？!?"


def main():
    ep = pathlib.Path(sys.argv[1]).resolve(); ver = sys.argv[2]
    every = int(sys.argv[sys.argv.index("--every") + 1]) if "--every" in sys.argv else 6
    S = json.loads((ep / "script.json").read_text())
    out = ep / "exports" / f"{S.get('slug', 'ep')}_{ver}.mp4"
    probs, notes = [], []
    if not out.exists():
        sys.exit(f"書き出しがありません: {out}")
    kinds = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True).stdout.split()
    if "audio" not in kinds:
        probs.append("音が入っていない")
    dur = float(subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                               capture_output=True, text=True).stdout)
    notes.append(f"長さ {dur / 60:.1f}分（{dur:.1f}秒）")
    r = subprocess.run([FF, "-nostats", "-i", str(out), "-af", "ebur128=framelog=quiet", "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.search(r"I:\s+(-?[\d.]+) LUFS", r)
    if m:
        lufs = float(m.group(1)); notes.append(f"音量 {lufs} LUFS")
        if abs(lufs + 14) > 1.0:
            probs.append(f"音量が -14 LUFS から外れている（{lufs}）")
    r = subprocess.run([FF, "-nostats", "-i", str(out), "-vf", "crop=1920:816:0:132,blackdetect=d=0.5:pix_th=0.06", "-an", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    blacks = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", r)
    if blacks:
        notes.append("黒い区間（意図した暗転か確かめる）: " + ", ".join(f"{float(a):.1f}-{float(b):.1f}秒" for a, b in blacks))
    subs = json.loads((ep / "subs.json").read_text()) if (ep / "subs.json").exists() else {}
    bad = [k for k, v in subs.items() if any(c in v for c in PUNCT)]
    if bad:
        probs.append(f"通常テロップに句読点: {bad[:8]}")
    miss = [L["id"] for L in S["lines"] if S.get("subtitles", True) and subs and L["id"] not in subs]
    if miss:
        probs.append(f"通常テロップが無い行: {miss[:8]}")
    capbad = [L["id"] for L in S["lines"] if L.get("caption") and any(c in L["caption"] for c in PUNCT)]
    if capbad:
        probs.append(f"演出テロップに句読点: {capbad[:8]}")
    for k in ("title_main", "title_sub"):
        if any(c in S.get(k, "") for c in PUNCT):
            probs.append(f"{k} に句読点: {S[k]}")
    sl = ep / "shotlist.json"
    if sl.exists():
        a = {int(k): v for k, v in json.loads(sl.read_text()).items()}
        from collections import Counter
        over = [v for v, c in Counter(a.values()).items() if c > 2]
        ks = sorted(a); adj = [k for p, k in zip(ks, ks[1:]) if a[p] == a[k]]
        if over: probs.append(f"3回以上使っている素材: {over[:8]}")
        if adj: probs.append(f"隣り合うカットで同じ素材: {adj[:8]}")
    qa = ep / "qa"; qa.mkdir(exist_ok=True)
    for f in qa.glob("sheet_*.jpg"):
        f.unlink()
    subprocess.run([FF, "-v", "error", "-i", str(out), "-vf", f"fps=1/{every},scale=480:-2,tile=4x8", "-q:v", "4",
                    str(qa / "sheet_%02d.jpg")], check=True)
    sheets = sorted(qa.glob("sheet_*.jpg"))
    print("\n".join(["■ 記録"] + [" - " + n for n in notes]))
    print("\n".join(["■ 直すこと"] + ([" - " + p for p in probs] or [" - なし"])))
    print(f"■ 目で見る一覧（{every}秒ごと・{len(sheets)}枚・左上から右へ時間順）")
    for s in sheets:
        print(" ", s)


if __name__ == "__main__":
    main()
