"""新しい回のフォルダとひな形を作る。
使い方: python3 new_episode.py <作業フォルダ> <slug>
→ <作業フォルダ>/<slug>/ に script.json（ひな形）・subs.json・assets/img・assets/vid を作る。既にあれば上書きしない。
"""
import json, pathlib, shutil, sys

HERE = pathlib.Path(__file__).resolve().parent
root, slug = pathlib.Path(sys.argv[1]).expanduser(), sys.argv[2]
ep = root / slug
if (ep / "script.json").exists():
    sys.exit(f"既にあります（上書きしません）: {ep / 'script.json'}")
for d in ("assets/img", "assets/vid", "exports", "planning"):
    (ep / d).mkdir(parents=True, exist_ok=True)
t = json.loads((HERE.parent / "assets/script.template.json").read_text())
t["slug"] = slug
(ep / "script.json").write_text(json.dumps(t, ensure_ascii=False, indent=1))
(ep / "subs.json").write_text("{}")
print(ep)
