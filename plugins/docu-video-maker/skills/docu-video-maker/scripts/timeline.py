"""台本（script.json）と読み上げの実測から、回の時刻表（timeline.json）を作る。
使い方: python3 timeline.py <回のフォルダ> [--dry]   --dry は読み上げ前に 1字0.2秒の仮の長さで組む
構成：ダイジェスト → 題字 → 章ごとに（章の扉 → 行）→ まとめの扉 → 行 → 締め
扉は script.json の "cards": {"title": true, "chapters": true, "end": true} で個別に外せる（短い PV は chapters を外すなど）
"""
import json, re, subprocess, sys
from common import load_ep, FF

GAP = {"digest": 0.30, "ch": 0.45, "summary": 0.55}
CARD, TITLE, END = 2.2, 5.0, 5.0
LONG = 3.6      # これより長い映像区間は分ける（視聴維持のため3〜4秒で絵を変える）


def speech_bounds(path):
    out = subprocess.run([FF, "-hide_banner", "-i", str(path), "-af", "silencedetect=n=-45dB:d=0.08", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out).groups()
    dur = int(h) * 3600 + int(m) * 60 + float(s)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    head = ends[0] if starts and starts[0] < 0.02 and ends else 0.0
    tail = starts[-1] if starts and (len(starts) > len(ends) or ends[-1] >= dur - 0.02) else dur
    return max(0.0, head - 0.03), min(dur, tail + 0.06)


def build(ep_dir, dry=False):
    ep, S = load_ep(ep_dir)
    use = dict({"title": True, "chapters": True, "end": True}, **S.get("cards", {}))
    t, lines, cards, cur = 0.4, [], [], None
    for ln in S["lines"]:
        sec = ln["sec"]
        kind = "digest" if sec == "digest" else ("summary" if sec == "summary" else "ch")
        if kind == "ch" and S.get("pace") == "fast":   # 短い PV は行間を詰める
            kind = "digest"
        if sec != cur:
            if cur == "digest" and use["title"]:
                t += 0.4
                cards.append({"type": "title", "start": round(t, 3), "end": round(t + TITLE, 3)})
                t += TITLE + 0.15
            if use["chapters"] and (ln.get("chapter") or sec == "summary"):
                cards.append({"type": "chapter", "label": ln.get("chapter") or "まとめ", "start": round(t, 3), "end": round(t + CARD, 3)})
                t += CARD + 0.15
            cur = sec
        if dry:
            a, b = 0.0, max(0.8, len(ln["text"]) * 0.2)
        else:
            a, b = speech_bounds(ep / "audio/lines" / f"{ln['id']}.mp3")
        L = dict(ln, start=round(t, 3), end=round(t + b - a, 3), src_in=round(a, 3), src_out=round(b, 3))
        lines.append(L)
        t += (b - a) + GAP[kind]
    t += 0.6
    if use["end"]:
        cards.append({"type": "end", "start": round(t, 3), "end": round(t + END, 3)})
    D = round(t + (END if use["end"] else 0.8), 3)

    # 映像の区間：同じ場面が続く行はまとめる。区間の終わりは次の区間か次の扉の始まり
    card_starts = sorted(c["start"] for c in cards)
    segs = []
    for i, L in enumerate(lines):
        s0 = L["start"] - (0.15 if L["sec"] != "digest" else 0.0)
        if segs and segs[-1]["scene"] == L["scene"] and segs[-1]["sec"] == L["sec"]:
            segs[-1]["lines"].append(L["id"]); continue
        segs.append({"scene": L["scene"], "sec": L["sec"], "start": round(max(0, s0), 3), "lines": [L["id"]]})
    for i, sg in enumerate(segs):
        nxt = [segs[i + 1]["start"]] if i + 1 < len(segs) else []
        nxt += [c for c in card_starts if c > sg["start"] + 0.05]
        sg["end"] = round(min(nxt) if nxt else D, 3)
    # 長い区間は分ける（2つ目以降は同じ絵の別の構図＝part を振る）
    shots = []
    for sg in segs:
        dur = sg["end"] - sg["start"]
        n = max(1, round(dur / LONG)) if dur > LONG * 1.25 else 1
        for k in range(n):
            a = sg["start"] + dur * k / n
            b = sg["start"] + dur * (k + 1) / n
            shots.append(dict(sg, start=round(a, 3), end=round(b, 3), part=k, parts=n))
    TL = {"duration": D, "lines": lines, "cards": cards, "shots": shots, "dry": dry}
    (ep / "timeline.json").write_text(json.dumps(TL, ensure_ascii=False, indent=1))
    print(f"全長 {D/60:.1f}分（{D:.1f}秒）・行 {len(lines)}・カット {len(shots)}・扉 {len(cards)}")
    return TL


if __name__ == "__main__":
    build(sys.argv[1], "--dry" in sys.argv)
