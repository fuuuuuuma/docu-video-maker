"""制作に使える道具を確かめ、どの作り方ができるかを表示する。鍵やメールアドレスは画面に出さない。
使い方: python3 check_env.py [--json]
"""
import importlib.util, json, os, pathlib, shutil, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
r = {}


def has_mod(m):
    return importlib.util.find_spec(m) is not None


def runs(c):
    try:
        return subprocess.run([c, "-version"], capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


r["ffmpeg"] = any(runs(c) for c in (shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg") if c)
r["yt_dlp"] = bool(shutil.which("yt-dlp")) or has_mod("yt_dlp")
r["python_core"] = all(has_mod(m) for m in ("numpy", "PIL", "cv2"))
r["depth"] = has_mod("torch") and has_mod("transformers")   # 無ければ立体化なしで動く
r["macos_say"] = bool(shutil.which("say"))
r["elevenlabs_key"] = bool(os.environ.get("ELEVENLABS_API_KEY")) or pathlib.Path("~/.config/elevenlabs/api_key").expanduser().exists()
hf = os.environ.get("HIGGSFIELD_CLI") or shutil.which("higgsfield") or "/opt/homebrew/opt/higgsfield/bin/higgsfield"
r["higgsfield_cli"] = pathlib.Path(hf).exists()
r["higgsfield_credits"] = None
if r["higgsfield_cli"]:
    try:
        out = subprocess.run([hf, "account", "status"], capture_output=True, text=True, timeout=30).stdout
        # 1行目は「メール — プラン, 残高」。メールは出さない
        r["higgsfield_credits"] = out.split("—")[-1].strip() if "credits" in out else "未ログイン（higgsfield auth login）"
    except Exception as e:
        r["higgsfield_credits"] = f"確認できず: {e.__class__.__name__}"
try:
    sys.path.insert(0, str(HERE))
    import common   # 書体の検出
    r["fonts"] = {"mincho": common.MINCHO_B[0], "gothic": common.GOTHIC[0]}
except SystemExit as e:
    r["fonts"] = f"見つからない: {e}"
except ImportError:
    r["fonts"] = "python の部品（numpy / Pillow）が無いので未確認"
r["map_data"] = (pathlib.Path(os.environ.get("DVM_HOME", pathlib.Path.home() / ".cache/docu-video-maker")) / "naturalearth/ne_50m_land.geojson").exists()

voice = "ElevenLabs" if r["elevenlabs_key"] else ("macOS の読み上げ（say）" if r["macos_say"] else "無し（声の手段が必要）")
images = "名画（パブリックドメイン）＋ Higgsfield の AI 画像・動画" if r["higgsfield_cli"] else "名画（パブリックドメイン）と地図だけ"
music = "ElevenLabs で作曲" if r["elevenlabs_key"] else "手持ちの曲か、BGM なし"
n_sfx = len(list((pathlib.Path(os.environ.get("DVM_HOME", pathlib.Path.home() / ".cache/docu-video-maker")) / "sfx").glob("*.mp3")))
sfx = (f"取り込み・作成済み {n_sfx} 種" if n_sfx else
       ("ElevenLabs で 14 種を作る" if r["elevenlabs_key"] else "無し（効果音ラボ・Mixkit から取って audio.py sfx --from で取り込める）"))
r["mode"] = {"voice": voice, "images": images, "music": music, "sfx": sfx}
fixes = []
if not r["ffmpeg"]: fixes.append("ffmpeg を入れる: brew install ffmpeg")
if not r["python_core"]: fixes.append(f"python の部品を入れる: python3 -m pip install -r {HERE / 'requirements.txt'}")
if not r["yt_dlp"]: fixes.append("参考動画の分析に yt-dlp を入れる: brew install yt-dlp")
if not r["map_data"]: fixes.append(f"地図を使うなら: python3 {HERE / 'fetch_map_data.py'}")
if isinstance(r["fonts"], str) and "見つからない" in r["fonts"]: fixes.append("日本語の書体（Noto Sans JP / Noto Serif JP）を入れる")
if not r["depth"]: fixes.append("（任意）絵を立体的に動かすなら: python3 -m pip install torch transformers")
r["fixes"] = fixes

if "--json" in sys.argv:
    print(json.dumps(r, ensure_ascii=False, indent=1))
else:
    ok = lambda b: "✓" if b else "×"
    print(f"ffmpeg {ok(r['ffmpeg'])} / yt-dlp {ok(r['yt_dlp'])} / python の部品 {ok(r['python_core'])} / 立体化 {ok(r['depth'])} / 地図データ {ok(r['map_data'])}")
    print(f"ElevenLabs の鍵 {ok(r['elevenlabs_key'])} / Higgsfield の CLI {ok(r['higgsfield_cli'])} {r['higgsfield_credits'] or ''}")
    print("書体:", r["fonts"])
    print("いまの環境での作り方 → 声:", voice, "／ 絵:", images, "／ BGM:", music, "／ 効果音:", sfx)
    for f in fixes:
        print(" -", f)
