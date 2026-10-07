"""カット表（shotlist.json）を作るための材料を出す。shots.py を一度流して shots_plan.json ができてから使う。
使い方: python3 make_cuts.py <回>
出力: <回>/cuts.json（各カットの番号・秒・読まれる文・いまの場面）・<回>/inventory.json（手持ち素材の一覧と説明）
"""
import json, pathlib, sys

ep = pathlib.Path(sys.argv[1]).resolve()
S = json.loads((ep / "script.json").read_text())
TL = json.loads((ep / "timeline.json").read_text())
plan = json.loads((ep / "shots_plan.json").read_text())
text = {L["id"]: L["text"] for L in S["lines"]}
cuts = []
for p in plan:
    if p["kind"] != "shot":
        continue
    it = p["item"]; sc = S["scenes"].get(it["scene"], {})
    cuts.append({"idx": p["idx"], "sec": it["sec"], "start": round(p["start"], 2), "dur": round(p["len"], 2),
                 "lines": [{"id": i, "text": text.get(i, "")} for i in it["lines"]], "part": it.get("part", 0), "parts": it.get("parts", 1),
                 "current_scene": it["scene"], "scene_kind": sc.get("kind"), "scene_desc": sc.get("desc", "")})
(ep / "cuts.json").write_text(json.dumps(cuts, ensure_ascii=False, indent=1))
src = {s["id"]: s for s in json.loads((ep / "sources.json").read_text())} if (ep / "sources.json").exists() else {}
inv = []
for d, kind in (("img", "image"), ("vid", "video")):
    for f in sorted((ep / "assets" / d).glob("*")):
        if f.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".mp4"):
            continue
        aid = f.stem
        desc = S["scenes"].get(aid, {}).get("desc") or src.get(aid, {}).get("desc") or ""
        inv.append({"id": aid, "type": kind, "desc": desc, "file": str(f.relative_to(ep))})
(ep / "inventory.json").write_text(json.dumps(inv, ensure_ascii=False, indent=1))
print(f"カット {len(cuts)}・手持ち素材 {len(inv)}")
