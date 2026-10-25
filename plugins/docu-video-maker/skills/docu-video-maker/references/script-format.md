# 台本と表の形式

回のフォルダに置くファイルと、その項目。ひな形は `new_episode.py` が `assets/script.template.json` から作る。

## script.json

| 項目 | 意味 |
|---|---|
| `slug` | 回の名前（英数字）。書き出しは `exports/<slug>_<版>.mp4` |
| `series` / `title_main` / `title_sub` | チャンネル名・題字・副題（扉に出る。**句読点を入れない**） |
| `title_bg` | 題字の扉の背景にする画像の ID（`assets/img/<ID>.png|jpg`） |
| `voice` | `{"provider": "elevenlabs", "id": "<voice_id>", "model": "eleven_v3", "seed": 1789}` か `{"provider": "say", "name": "Kyoko", "rate": 190}` |
| `bgm` | `{"provider": "elevenlabs"}`・`{"file": "曲のパス"}`・`{"provider": "none"}`。`"styles": [...]` で曲調の語を差し替え |
| `cards` | 扉の有無 `{"title": true, "chapters": true, "end": true}` |
| `pace` | `"fast"` で行間を詰める（短い PV 向け） |
| `image_style` | AI 画像の画調の文（英語）。全カットに足される |
| `subtitles` | `false` で通常テロップを出さない |
| `lines` | 台本の行（下） |
| `scenes` | 場面の ID ごとの種類と説明（下） |

### lines の1行

```json
{"id": "c12", "sec": "ch2", "chapter": "第2章　塔の中の王子", "text": "読み上げる文。", "scene": "pd_temple",
 "caption": "タンプル塔に幽閉", "red": "幽閉", "fx": true, "year": "1792", "tts": "読みの差し替え",
 "sfx": [{"name": "door_slam", "t": 0.4, "gain": -6}], "telop_pos": "center"}
```

- `id`：一意。慣例はダイジェスト `d1…`・本編 `c1…`・まとめ `s1…`
- `sec`：`digest`・`ch1`〜・`summary`。`sec` が変わる最初の行に `chapter`（章の扉の文言。「第2章　名前」のように全角空白で区切る）
- `text`：1文。1行6秒前後に収める（長い文は分ける）。数字は読み上げに合わせて書く
- `scene`：絵の ID（`scenes` のキー）。同じ場面が続く行は同じ ID でよい（カット表で別の絵に分ける）
- `caption`・`red`・`fx`：演出テロップ。`fx: true` の行にだけ出す（約30秒に1回）。`red` は caption の中の赤くする語で、その瞬間に衝撃音と画面の乱れが入る
- `year`：上の帯の年号（変わる所だけ書けば続く）
- `tts`：読み違える固有名詞だけ、読みを書く（例 `"text": "サン・ドニ"` → `"tts": "サンドニ"`）
- `telop_pos`：演出テロップの置き方を固定したいとき（`left`・`center`・`right`・`vertical`）。無ければ順に回す
- `hush`：この行の前に空ける静かな間（秒。1〜1.5 が目安）。声も BGM も止まり、前の絵が残る。山場や転機の前に置く
- `sfx`：効果音。`t` は行の始まりからの秒で、負にすると場面が変わる前から鳴る（音の受け渡し）

### scenes の種類

| `kind` | 中身 |
|---|---|
| `pd` | 名画・版画（`assets/img/<ID>.jpg`）。縦長は額のように置くか、横幅いっぱいでなめる |
| `ai_image` | AI 画像（`assets/img/<ID>.png`） |
| `ai_video` | AI 動画（`assets/vid/<ID>.mp4`、無ければ同名の静止画） |
| `map` | 地図。`"map": {"view_from": [西, 南, 東, 北], "view_to": [...], "points": [{"name","lon","lat","at"}], "routes": [{"from","to","at","dur"}]}`。範囲は経度12度未満なら自動で広がる |
| `black` | 黒 |

## subs.json（通常テロップ）

`{"行ID": "要約した文"}`。句読点（、。！？）は入れない（入っていると組み立てが止まる）。数字は算用数字。30字以内は1行、超えたら `\n` で2つに分けると、前半・後半の順に1行ずつ出る。語りをそのまま写すのではなく、少しだけ要約する。

## shotlist.json（カット表）

`{"カット番号": "素材ID"}`。カット番号は `shots_plan.json` の `idx`（`shots.py` を一度流すとできる。扉の分は飛ぶ）。素材 ID は `assets/img`・`assets/vid` のファイル名、新しく作る素材の ID、地図なら `"map:<scenes のキー>"`。

- 同じ素材は2回まで、隣り合うカットでは使わない
- 続く3カットが同じ種類の画（引き・人物・寄り・象徴）にならないようにする
- AI 動画は約6カットに1本、山場（死・別れ・脱出・再会）を優先

370カットを手で埋めるのは重いので、サブエージェントが使えるなら、`cuts.json`（各カットの番号・秒・読まれる文・いまの場面）と手持ち素材の一覧を渡して作らせ、上の条件を Python で検査してから使う。

## new_assets.json（AI で作る素材）

```json
[{"id": "n_cradle", "type": "image", "prompt": "英語の描写", "ref": ["assets/img/pd_family.jpg"]},
 {"id": "n_lab", "type": "image", "era": "modern", "prompt": "英語の描写"},
 {"id": "nv_cradle", "type": "video", "prompt": "動きだけ（slow push-in, candle flickers）", "start": "assets/img/n_cradle.png"}]
```

画調は `image_style` が自動で足されるので、prompt には書かない。`era: "modern"` は現代の場面（服装を現代に固定）。`ref` は同じ人物の顔や服をそろえたいときに既存の画像を最大2つ。
