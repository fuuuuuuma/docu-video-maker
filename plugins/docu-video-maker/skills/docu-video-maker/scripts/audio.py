"""音まわり：読み上げ（1文ずつ）・効果音の共通ライブラリ・区切りに合わせた BGM・ミックス。
使い方:
  python3 audio.py tts <回>            → <回>/audio/lines/<行ID>.mp3（既にあれば作らない）
  python3 audio.py sfx                 → ~/.cache/docu-video-maker/sfx/*.mp3（回をまたいで共通・1回だけ）
  python3 audio.py bgm <回> <版>        → <回>/audio/bgm_<版>.mp3（章の区切りに合わせて作曲）
  python3 audio.py mix <回> <版>        → <回>/audio/mix_<版>.wav（-14 LUFS）
script.json の設定:
  "voice": {"provider": "elevenlabs", "id": "<voice_id>", "model": "eleven_v3", "seed": 1789}
           {"provider": "say", "name": "Kyoko", "rate": 190}      ← macOS の読み上げ（無料）
  "bgm":   {"provider": "elevenlabs"} / {"file": "曲のパス"} / {"provider": "none"}
効果音は ElevenLabs の鍵があるときだけ作る。無ければミックスで飛ばす。
"""
import json, os, pathlib, subprocess, sys, tempfile
import numpy as np
from common import HOME, FF, load_ep, shows_telop

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import el   # 同封の ElevenLabs 呼び出し（鍵は環境変数 ELEVENLABS_API_KEY か ~/.config/elevenlabs/api_key）

DEFAULT_VOICE = {"provider": "elevenlabs", "model": "eleven_v3", "seed": 1789}
SR = 48000
LIB = HOME / "sfx"
SFX = {  # 名前: (秒, 説明)
    "impact": (3, "Huge cinematic trailer impact hit, deep boom with long reverb tail, dark and powerful"),
    "impact_soft": (3, "Soft deep cinematic low boom, gentle, distant, documentary"),
    "whoosh": (1, "Fast cinematic whoosh swoosh transition, airy, no music"),
    "riser": (4, "Dark tension riser building up, rising pitch and noise, cinematic trailer, ends abruptly"),
    "glitch": (1, "Short digital glitch burst, electronic stutter and static crackle"),
    "bell_toll": (5, "Single deep church bell toll, slow decay, solemn"),
    "paper_flip": (1, "Quick old paper page flip"),
    "tick": (2, "Mechanical clock ticking, a few clean ticks, close"),
    "heartbeat": (3, "Slow deep heartbeat, low thump, tense cinematic"),
    "quill": (3, "Quill pen scratching on parchment paper, close up, quiet room"),
    "carriage": (5, "Horse-drawn carriage on a dirt road at night, hooves and wooden wheels"),
    "crowd": (6, "Angry crowd of hundreds of people shouting in a city street, 18th century riot"),
    "door_slam": (2, "Heavy wooden prison door slamming shut, iron lock, echo"),
    "wind": (6, "Cold wind howling through an old stone tower, desolate"),
}


def has_key():
    return bool(os.environ.get("ELEVENLABS_API_KEY")) or pathlib.Path("~/.config/elevenlabs/api_key").expanduser().exists()


def tts_one(text, v, out):
    if v.get("provider") == "say":   # macOS の読み上げ（無料）。品質は ElevenLabs より落ちる
        with tempfile.TemporaryDirectory() as td:
            aiff = pathlib.Path(td) / "a.aiff"
            subprocess.run(["say", "-v", v.get("name", "Kyoko"), "-r", str(v.get("rate", 190)), "-o", str(aiff), text], check=True)
            subprocess.run([FF, "-v", "error", "-y", "-i", str(aiff), "-ar", "44100", "-b:a", "128k", str(out)], check=True)
        return
    if not v.get("id"):
        raise SystemExit("script.json の voice.id（ElevenLabs の voice_id）が空です。python3 el.py voices で選んでください")
    body = {"text": text, "model_id": v.get("model", "eleven_v3"), "language_code": v.get("lang", "ja")}
    if v.get("seed") is not None:
        body["seed"] = v["seed"]
    raw, _ = el.call("POST", f"/v1/text-to-speech/{v['id']}", body, {"output_format": "mp3_44100_128"})
    out.write_bytes(raw)


def cmd_tts(ep_dir):
    ep, S = load_ep(ep_dir)
    v = dict(DEFAULT_VOICE, **S.get("voice", {}))
    out = ep / "audio/lines"; out.mkdir(parents=True, exist_ok=True)
    todo = [L for L in S["lines"] if not (out / f"{L['id']}.mp3").exists()]
    # ElevenLabs の同時に作れる本数は契約で決まる（Creator は2本）。say は手元なので4本
    workers = int(os.environ.get("DVM_TTS_WORKERS", 2 if v.get("provider") != "say" else 4))
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(workers) as ex:   # 読み違える語は tts に読みを書く
        list(ex.map(lambda L: tts_one(L.get("tts", L["text"]), v, out / f"{L['id']}.mp3"), todo))
    n = len(todo)
    print("読み上げ", n, "行を作成（全", len(S["lines"]), "行）")


def cmd_sfx():
    if not has_key():
        print("ElevenLabs の鍵が無いので効果音は作りません（ミックスでは飛ばします）"); return
    LIB.mkdir(parents=True, exist_ok=True)
    for n, (sec, text) in SFX.items():
        f = LIB / f"{n}.mp3"
        if not f.exists():
            raw, _ = el.call("POST", "/v1/sound-generation", {"text": text, "model_id": "eleven_text_to_sound_v2", "duration_seconds": sec},
                             {"output_format": "mp3_44100_128"})
            f.write_bytes(raw)
    print("効果音", len(SFX), "種")


def cmd_bgm(ep_dir, ver):
    ep, S = load_ep(ep_dir)
    b = S.get("bgm", {"provider": "elevenlabs"})
    if b.get("file") or b.get("provider") == "none":
        print("BGM は", b.get("file") or "なし", "（作曲しない）"); return
    TL = json.loads((ep / "timeline.json").read_text())
    D = TL["duration"]
    cards = TL["cards"]
    title = [c for c in cards if c["type"] == "title"]
    chap = [c for c in cards if c["type"] == "chapter"]
    end = [c for c in cards if c["type"] == "end"]
    cuts = sorted(set([0.0] + [c["start"] for c in title + chap + end] + [D]))
    G = ["68 BPM", "cinematic orchestral film score", "historical documentary", "melancholic and dignified", "instrumental"]
    styles = {"digest": ["dark tense underscore", "low string ostinato", "sparse deep drum hits", "builds to a hit"],
              "title": ["solemn orchestral swell", "wordless choir chord", "low brass"],
              "ch": ["calm documentary underscore", "solo cello and piano motif", "soft pulse", "space for narration"],
              "dark": ["darker and tense", "low strings", "distant timpani", "space for narration"],
              "summary": ["reflective and hopeful", "warm strings and piano", "gentle swell"],
              "end": ["final solemn resolution", "clean ending"]}
    # 区切りごとの曲調：扉の種類から決める（ダイジェスト→題字→章（明暗を交互）→まとめ→締め）
    kinds = {round(c["start"], 3): c for c in cards}
    names, k = [], 0
    for x in cuts[:-1]:
        c = kinds.get(round(x, 3))
        if c is None:
            names.append("digest" if x == 0.0 and title else "ch")
        elif c["type"] == "title":
            names.append("title")
        elif c["type"] == "end":
            names.append("end")
        elif c.get("label") == "まとめ":
            names.append("summary")
        else:
            names.append("dark" if k % 2 else "ch"); k += 1
    G = S.get("bgm", {}).get("styles", G)
    chunks = []
    for i in range(len(cuts) - 1):
        ms = int(round((cuts[i + 1] - cuts[i]) * 1000))
        if ms < 3000:
            chunks[-1]["duration_ms"] += ms; continue
        # 1区間は最長120秒までなので分ける
        while ms > 0:
            take = min(ms, 120000)
            chunks.append({"text": f"[{names[i]}]", "duration_ms": max(3000, take), "positive_styles": G + styles[names[i]],
                           "negative_styles": ["vocals with lyrics", "pop", "electronic dance", "drums too loud"], "context_adherence": "high"})
            ms -= take
    # 1曲は10分まで：区切りの位置で何曲かに分けて作り、つなぐ（つなぎ目は章の扉＝効果音が鳴る所）
    groups, cur, acc = [], [], 0
    for c in chunks:
        if acc + c["duration_ms"] > 540000 and cur:
            groups.append(cur); cur, acc = [], 0
        cur.append(c); acc += c["duration_ms"]
    groups.append(cur)
    parts = []
    for gi, g in enumerate(groups):
        raw, _ = el.call("POST", "/v1/music", {"composition_plan": {"chunks": g}, "model_id": "music_v2_5"}, {"output_format": "mp3_44100_192"})
        pf = ep / "audio" / f"bgm_{ver}_p{gi}.mp3"; pf.write_bytes(raw); parts.append(pf)
    out = ep / "audio" / f"bgm_{ver}.mp3"
    if len(parts) == 1:
        parts[0].rename(out)
    else:
        lst = ep / "audio" / f"bgm_{ver}_list.txt"
        lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
        subprocess.run([FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "libmp3lame", "-b:a", "192k", str(out)], check=True)
        lst.unlink()
    print("BGM", out.name, round(sum(c["duration_ms"] for c in chunks) / 1000, 1), "秒・", len(parts), "曲")


def load(path, a=None, b=None):
    cmd = [FF, "-v", "error", "-i", str(path)]
    if a is not None:
        cmd += ["-ss", f"{a:.3f}", "-to", f"{b:.3f}"]
    cmd += ["-f", "f32le", "-ac", "2", "-ar", str(SR), "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32).reshape(-1, 2).copy()


def sfx_cues(S, TL):
    """効果音を鳴らす位置 [(名前, 秒, dB)]。扉に当てる分＋赤い語＋ script.json の \"sfx\"（書き出しとプレビューで共用）。"""
    cues = []
    for c in TL["cards"]:
        if c["type"] == "title":
            cues += [("riser", c["start"] - 3.6, -8), ("impact", c["start"], -2), ("bell_toll", c["start"] + 0.3, -8)]
        elif c["type"] == "chapter":
            cues += [("whoosh", c["start"] - 0.3, -6), ("impact_soft", c["start"], -4), ("paper_flip", c["end"] - 0.15, -12)]
        elif c["type"] == "end":
            cues += [("impact_soft", c["start"], -4), ("bell_toll", c["start"] + 0.4, -8)]
    byid = {L["id"]: L for L in TL["lines"]}
    latest = {x["id"]: x for x in S["lines"]}   # 見出し・赤・演出テロップは script.json の最新を使う
    for L in TL["lines"]:
        for key in ("caption", "red", "fx", "sfx"):
            if key in latest.get(L["id"], {}):
                L[key] = latest[L["id"]][key]
    for L in TL["lines"]:
        if L.get("red") and shows_telop(L, S):
            cues.append(("impact_soft", L["start"] + 0.05, -8))
        for s in L.get("sfx", []):
            cues.append((s["name"], L["start"] + s.get("t", 0.0), s.get("gain", -8)))
    return cues


def cmd_mix(ep_dir, ver):
    ep, S = load_ep(ep_dir)
    TL = json.loads((ep / "timeline.json").read_text())
    N = int((TL["duration"] + 0.5) * SR)
    db = lambda g: 10 ** (g / 20)

    def place(buf, x, t, gain=1.0):
        i = int(round(t * SR))
        if i < 0:
            x, i = x[-i:], 0
        j = min(len(buf), i + len(x)); buf[i:j] += x[:j - i] * gain
    voice = np.zeros((N, 2), np.float32)
    for L in TL["lines"]:
        x = load(ep / "audio/lines" / f"{L['id']}.mp3", L["src_in"], L["src_out"])
        f = int(0.012 * SR); x[:f] *= np.linspace(0, 1, f)[:, None]; x[-f:] *= np.linspace(1, 0, f)[:, None]
        place(voice, x, L["start"])
    rv = np.zeros_like(voice)
    for dl, g in ((0.031, 0.09), (0.047, 0.07), (0.071, 0.05), (0.113, 0.035)):
        k = int(dl * SR); rv[k:] += voice[:-k] * g
    voice += rv
    bgm = np.zeros((N, 2), np.float32)
    b = S.get("bgm", {"provider": "elevenlabs"})
    bf = pathlib.Path(b["file"]).expanduser() if b.get("file") else ep / "audio" / f"bgm_{ver}.mp3"
    if not bf.exists() and not b.get("file"):
        found = sorted((ep / "audio").glob("bgm_*.mp3"))
        bf = found[-1] if found else None
    if bf and b.get("provider") != "none":
        x = load(bf)[:N]; fo = min(len(x), int(2.5 * SR)); x[-fo:] *= np.linspace(1, 0, fo)[:, None]
        place(bgm, x, 0.0)
    env = np.zeros(N, np.float32)
    for L in TL["lines"]:
        env[int(L["start"] * SR): int(L["end"] * SR)] = 1
    env = np.maximum(env, np.roll(env, -int(0.1 * SR)))
    sm = np.zeros(N, np.float32); v = 0.0
    a1, r1 = 1 - np.exp(-1 / (0.12 * SR)), 1 - np.exp(-1 / (0.45 * SR))
    for i in range(0, N, 48):
        tg = env[i]; v += (tg - v) * (1 - (1 - (a1 if tg > v else r1)) ** 48); sm[i:i + 48] = v
    bgm *= (db(-11) ** sm)[:, None]
    # 効果音：扉に当てる＋ script.json の "sfx":[{"name","t"}]（行IDからの相対も可）
    sfx = np.zeros((N, 2), np.float32)
    cues = sfx_cues(S, TL)
    cache = {}
    for n, t, g in cues:
        if not (LIB / f"{n}.mp3").exists():   # 効果音を作っていない環境では飛ばす
            continue
        if n not in cache:
            cache[n] = load(LIB / f"{n}.mp3")
        place(sfx, cache[n], t, db(g - 6))
    mix = voice + bgm * db(-9) + sfx * db(-4)
    raw = ep / "audio" / f"mix_{ver}_raw.wav"
    subprocess.run([FF, "-v", "error", "-y", "-f", "f32le", "-ac", "2", "-ar", str(SR), "-i", "-", "-c:a", "pcm_s24le", str(raw)],
                   input=mix.astype(np.float32).tobytes(), check=True)
    r = subprocess.run([FF, "-hide_banner", "-i", str(raw), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    m = json.loads(r[r.rindex("{"):r.rindex("}") + 1])
    af = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
          f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,aresample={SR}")
    out = ep / "audio" / f"mix_{ver}.wav"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(raw), "-af", af, "-c:a", "pcm_s24le", str(out)], check=True)
    raw.unlink()
    print("mix", out.name, f"{N/SR:.1f}秒")


if __name__ == "__main__":
    c = sys.argv[1]
    {"tts": lambda: cmd_tts(sys.argv[2]), "sfx": cmd_sfx, "bgm": lambda: cmd_bgm(sys.argv[2], sys.argv[3]),
     "mix": lambda: cmd_mix(sys.argv[2], sys.argv[3])}[c]()
