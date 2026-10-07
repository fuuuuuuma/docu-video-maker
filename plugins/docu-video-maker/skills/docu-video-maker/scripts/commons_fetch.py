"""ウィキメディア・コモンズから、パブリックドメインまたは CC0 の絵だけを探して取ってくる。出典は sources.json に残す。
使い方:
  python3 commons_fetch.py search "<語>" [--limit 20]            # 候補を一覧（取らない）。語は英語・原語のほうが当たる
  python3 commons_fetch.py get <回のフォルダ> <ID> "File:xxx.jpg" ["説明"]   # 1点取る → assets/img/<ID>.jpg と sources.json
ID は px_ で始める（例 px_louis16_portrait）。CC BY 系や不明なライセンスは取らない。
"""
import json, pathlib, re, sys, urllib.parse, urllib.request

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "docu-video-maker/1.0 (https://github.com/fuuuuuuma/docu-video-maker)"}
OK = re.compile(r"^(public domain|pd\b|pd-|cc0|cc-zero)", re.I)


def q(params):
    url = API + "?" + urllib.parse.urlencode(dict(params, format="json"))
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read())


def info(pages):
    out = []
    for p in pages.values():
        ii = (p.get("imageinfo") or [{}])[0]
        md = ii.get("extmetadata", {})
        lic = md.get("LicenseShortName", {}).get("value", "")
        strip = lambda s: re.sub(r"<[^>]+>", "", s or "").strip()
        out.append({"title": p.get("title"), "license": lic, "ok": bool(OK.match(lic.strip())),
                    "artist": strip(md.get("Artist", {}).get("value"))[:80], "date": re.sub(r"date QS.*$", "", strip(md.get("DateTimeOriginal", {}).get("value")))[:40],
                    "size": [ii.get("width"), ii.get("height")], "url": ii.get("descriptionurl"), "file": ii.get("thumburl") or ii.get("url")})
    return out


def search(term, limit=20):
    r = q({"action": "query", "generator": "search", "gsrsearch": term, "gsrnamespace": 6, "gsrlimit": limit,
           "prop": "imageinfo", "iiprop": "url|extmetadata|size", "iiurlwidth": 2400})
    rows = info(r.get("query", {}).get("pages", {}))
    for x in rows:
        mark = "○" if x["ok"] else "×"
        print(f"{mark} {x['size'][0]}x{x['size'][1]}  {x['license'][:14]:14}  {x['title']}  — {x['artist']} {x['date']}")
    print("○ だけ使える（PD / CC0）。短辺 900px 未満は画面で粗く見えるので避ける。")


def get(ep, aid, title, desc=""):
    ep = pathlib.Path(ep)
    r = q({"action": "query", "titles": title, "prop": "imageinfo", "iiprop": "url|extmetadata|size", "iiurlwidth": 2400})
    x = info(r["query"]["pages"])[0]
    if not x["ok"]:
        sys.exit(f"取りません（ライセンスが PD / CC0 ではない）: {x['license']}")
    out = ep / "assets/img" / f"{aid}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(urllib.request.urlopen(urllib.request.Request(x["file"], headers=UA), timeout=120).read())
    sp = ep / "sources.json"
    src = json.loads(sp.read_text()) if sp.exists() else []
    src = [s for s in src if s["id"] != aid] + [{"id": aid, "desc": desc, "title": x["title"], "artist": x["artist"],
                                                  "date": x["date"], "license": x["license"], "url": x["url"]}]
    sp.write_text(json.dumps(src, ensure_ascii=False, indent=1))
    print("保存:", out, x["license"], x["size"])


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "search":
        search(a[1], int(a[a.index("--limit") + 1]) if "--limit" in a else 20)
    elif a and a[0] == "get":
        get(a[1], a[2], a[3], a[4] if len(a) > 4 else "")
    else:
        print(__doc__)
