# Docu Video Maker

参考にしたい YouTube チャンネルや動画の URL を渡すと、その作風を読み取って、ドキュメンタリー風の解説動画や PV を MP4 まで作るスキルです。Claude Code と Codex の両方で使えます。After Effects は使いません。

- 参考を分析して、コンセプト・題材・構成の**叩き台**を先に出します
- 長さ・題材・使える有料サービス・声を**短い質問**で確かめてから作ります
- 名画（パブリックドメイン）・AI 画像と動画・地図に、ナレーション・BGM・効果音・テロップを重ねて、1080p の MP4 に書き出します
- サムネイル・タイトル・概要欄・クレジットの一式も作ります（YouTube への投稿はご自身で）

## インストール

**Claude Code**

```bash
claude plugin marketplace add fuuuuuuma/docu-video-maker
claude plugin install docu-video-maker@docu-video-maker
```

**Codex**

```bash
codex plugin marketplace add fuuuuuuma/docu-video-maker
codex plugin add docu-video-maker@docu-video-maker
```

入れたあと、新しいセッションで使えます。

## 使い方

URL と、作りたいものを一言で伝えます。

```text
このチャンネルみたいな解説動画を作りたい。題材は世界史で。
https://www.youtube.com/@xxxx
```

```text
この動画の感じで、3分くらいの PV を作って。
https://youtu.be/xxxx
```

最初に道具の確認と参考の分析が走り、叩き台と4問前後の質問が返ってきます。答えると、台本 → 承認 → 素材 → 音 → 組み立て → 検査 → 審査（作っていない担当が7観点で採点し、直してもう一度）→ 公開用の一式、の順に進みます。お金がかかる生成（Higgsfield のクレジットなど）は、見込みを示して上限を確かめてから行います。

## 必要なもの

| もの | 必須か | 用途 |
|---|---|---|
| macOS（Apple Silicon 推奨） | 推奨 | 書体（ヒラギノ）と読み上げ。ほかの OS では Noto Sans/Serif JP を入れる |
| Python 3.10 以降と `numpy` `pillow` `opencv-python` | 必須 | 組み立て（`pip install -r .../scripts/requirements.txt`） |
| `ffmpeg` | 必須 | 映像と音の処理（`brew install ffmpeg`） |
| `yt-dlp` | 推奨 | 参考動画の分析（`brew install yt-dlp`） |
| ElevenLabs の API キー | 任意 | 声・BGM・効果音。無ければ macOS の読み上げで作る（品質は落ちる） |
| Higgsfield の CLI とクレジット | 任意 | AI 画像・動画。無ければ名画と地図だけで作る |
| `torch` `transformers` | 任意 | 絵を奥行きをつけて動かす。無ければ寄り・パンだけ |

ElevenLabs のキーは、環境変数 `ELEVENLABS_API_KEY` か `~/.config/elevenlabs/api_key` に置いてください。キーをチャットに貼る必要はありません。

## 費用の目安（2026年10月時点）

20分の回で、Higgsfield は約500クレジット（AI 画像約200枚・AI 動画約40本）、ElevenLabs は読み上げ約1.5万文字と BGM 数曲です。3分の PV なら、その1割前後です。

## 素材と権利

- 名画・版画は、ウィキメディア・コモンズの**パブリックドメインと CC0 の作品だけ**を取ります。出典は自動で記録し、固定コメント用のクレジットを作ります
- 参考動画の映像・音・サムネは分析にだけ使い、作る動画には流用しません
- AI のイメージ図と合成音声を使うので、YouTube の「改変または合成されたコンテンツ」の開示を「はい」にしてください
- 生成した画像・音声・書体・BGM の利用条件は、それぞれのサービスの規約に従ってください

## ライセンス

MIT License
