"""映像に実際に映る名画のクレジットを、固定コメント用の文にする。
使い方: python3 make_credits.py <回>
出力: <回>/exports/credits_comment.txt（題材（年）／作者（ライセンス）の1行ずつ）・<回>/exports/credits_full.txt（URL 付きの控え）
映る素材は shotlist.json（無ければ script.json の scenes）と、AI 動画の元画像から数える。
"""
import json, pathlib, re, sys

ep = pathlib.Path(sys.argv[1]).resolve()
S = json.loads((ep / "script.json").read_text())
src = {s["id"]: s for s in json.loads((ep / "sources.json").read_text())} if (ep / "sources.json").exists() else {}
sl = json.loads((ep / "shotlist.json").read_text()) if (ep / "shotlist.json").exists() else {}
na = {a["id"]: a for a in json.loads((ep / "new_assets.json").read_text())} if (ep / "new_assets.json").exists() else {}
used = list(dict.fromkeys(list(sl.values()) + [L["scene"] for L in S["lines"]] + [S.get("title_bg", "")]))
for v in list(used):
    if v in na and na[v]["type"] == "video":
        used.append(pathlib.Path(na[v]["start"]).stem)
lines, full = [], []
for aid in dict.fromkeys(used):
    s = src.get(aid)
    if not s:
        continue
    lic = "パブリックドメイン" if s["license"].lower().startswith(("public", "pd")) else s["license"]
    who = re.sub(r"[.,]\s*(graveur|lithographe|dessinateur|peintre|photographe|editeur).*$", "", s.get("artist") or "", flags=re.I).strip()
    if not who or re.search(r"unknown|anonym|unidentified", who, re.I):
        who = "作者不詳"
    name = s.get("desc") or s["title"]
    date = s.get("date") or ""
    line = f"・{name}{'' if (not date or date in name) else '（' + date + '）'}／{who}（{lic}）"
    lines.append(line); full.append(f"{line} {s['url']}")
head = "映像に使った肖像画・版画・絵画の一覧です（ウィキメディア・コモンズで公開されているパブリックドメインまたは CC0 の作品）\n"
(ep / "exports").mkdir(exist_ok=True)
(ep / "exports/credits_comment.txt").write_text(head + "\n".join(lines) + "\n")
(ep / "exports/credits_full.txt").write_text("\n".join(full) + "\n")
n = len(head) + sum(len(x) + 1 for x in lines)
print(f"{len(lines)}点・{n}字（固定コメントは10,000字まで{'・超えている' if n > 10000 else ''}）")
