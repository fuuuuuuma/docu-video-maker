#!/usr/bin/env python3
"""ElevenLabs API の小さな道具（標準ライブラリだけ）。

鍵は ~/.config/elevenlabs/api_key（600）か環境変数 ELEVENLABS_API_KEY から読む。鍵は画面に出さない。

  python3 el.py me                                   # 契約と残りクレジット
  python3 el.py voices [--search 語]                 # 声の一覧（voice_id）
  python3 el.py tts   --text "…" --voice VOICE_ID --out a.mp3 [--model eleven_v3] [--lang ja]
  python3 el.py music --prompt "…" --seconds 30 --out m.mp3 [--instrumental] [--model music_v2_5]
  python3 el.py sfx   --text "…" --out s.mp3 [--seconds 2] [--influence 0.5] [--loop]

--format で出力形式を変えられる（既定 mp3_44100_128。wav_44100 など。高音質の形式は上位プランのみ）。
"""
import argparse, json, os, pathlib, sys, urllib.error, urllib.parse, urllib.request

BASE = "https://api.elevenlabs.io"


def key():
    k = os.environ.get("ELEVENLABS_API_KEY")
    if k:
        return k.strip()
    p = pathlib.Path("~/.config/elevenlabs/api_key").expanduser()
    if not p.exists():
        sys.exit("鍵がありません: ~/.config/elevenlabs/api_key に保存してください")
    return p.read_text().strip()


def call(method, path, body=None, query=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(query) if query else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"xi-api-key": key(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.read(), r.headers
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode(errors='replace')[:800]}")


def save(raw, out):
    out = pathlib.Path(out)
    if out.exists():
        sys.exit(f"上書きしません（既にあります）: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    print(f"保存: {out} ({len(raw)/1024:.0f} KB)")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("me")
    v = sub.add_parser("voices"); v.add_argument("--search")
    t = sub.add_parser("tts")
    t.add_argument("--text", required=True); t.add_argument("--voice", required=True)
    t.add_argument("--model", default="eleven_v3"); t.add_argument("--lang")
    t.add_argument("--stability", type=float); t.add_argument("--speed", type=float)
    t.add_argument("--similarity", type=float); t.add_argument("--style", type=float)
    t.add_argument("--seed", type=int)
    m = sub.add_parser("music")
    m.add_argument("--prompt", required=True); m.add_argument("--seconds", type=float, default=30)
    m.add_argument("--model", default="music_v2_5"); m.add_argument("--instrumental", action="store_true")
    s = sub.add_parser("sfx")
    s.add_argument("--text", required=True); s.add_argument("--seconds", type=float)
    s.add_argument("--influence", type=float); s.add_argument("--loop", action="store_true")
    for p in (t, m, s):
        p.add_argument("--out", required=True); p.add_argument("--format", default="mp3_44100_128")
    a = ap.parse_args()

    if a.cmd == "me":
        raw, _ = call("GET", "/v1/user/subscription")
        d = json.loads(raw)
        used, lim = d.get("character_count"), d.get("character_limit")
        print(f"プラン: {d.get('tier')}  使用: {used} / {lim}  残り: {(lim or 0) - (used or 0)}")
        print(f"次の補充: {d.get('next_character_count_reset_unix')}  状態: {d.get('status')}")
    elif a.cmd == "voices":
        q = {"page_size": 100}
        if a.search:
            q["search"] = a.search
        raw, _ = call("GET", "/v2/voices", query=q)
        for x in json.loads(raw).get("voices", []):
            lab = x.get("labels") or {}
            print(f"{x['voice_id']}  {x['name']}  [{x.get('category')}] "
                  f"{lab.get('gender','')} {lab.get('age','')} {lab.get('accent','')} {lab.get('description','')}".rstrip())
    elif a.cmd == "tts":
        body = {"text": a.text, "model_id": a.model}
        if a.lang:
            body["language_code"] = a.lang
        vs = {k: val for k, val in (("stability", a.stability), ("speed", a.speed),
                                     ("similarity_boost", a.similarity), ("style", a.style)) if val is not None}
        if vs:
            body["voice_settings"] = vs
        if a.seed is not None:
            body["seed"] = a.seed
        raw, h = call("POST", f"/v1/text-to-speech/{a.voice}", body, {"output_format": a.format})
        save(raw, a.out)
        if h.get("character-cost"):
            print(f"消費: {h.get('character-cost')} クレジット")
    elif a.cmd == "music":
        body = {"prompt": a.prompt, "music_length_ms": int(a.seconds * 1000), "model_id": a.model,
                "force_instrumental": a.instrumental}
        raw, _ = call("POST", "/v1/music", body, {"output_format": a.format})
        save(raw, a.out)
    elif a.cmd == "sfx":
        body = {"text": a.text, "model_id": "eleven_text_to_sound_v2"}
        if a.seconds is not None:
            body["duration_seconds"] = a.seconds
        if a.influence is not None:
            body["prompt_influence"] = a.influence
        if a.loop:
            body["loop"] = True
        raw, _ = call("POST", "/v1/sound-generation", body, {"output_format": a.format})
        save(raw, a.out)


if __name__ == "__main__":
    main()
