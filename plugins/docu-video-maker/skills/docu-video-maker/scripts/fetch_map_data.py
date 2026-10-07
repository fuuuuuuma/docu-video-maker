"""地図のカットに使う Natural Earth（パブリックドメイン）の陸地と川を取ってくる。1回だけでよい。
使い方: python3 fetch_map_data.py
置き場: ~/.cache/docu-video-maker/naturalearth/（環境変数 DVM_HOME で変えられる）
"""
import os, pathlib, urllib.request

D = pathlib.Path(os.environ.get("DVM_HOME", pathlib.Path.home() / ".cache/docu-video-maker")) / "naturalearth"
D.mkdir(parents=True, exist_ok=True)
SRC = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
for name, local in (("ne_50m_land.geojson", "ne_50m_land.geojson"), ("ne_50m_rivers_lake_centerlines.geojson", "ne_50m_rivers.geojson")):
    out = D / local
    if out.exists():
        print("あり:", out); continue
    print("取得:", name)
    urllib.request.urlretrieve(SRC + name, out)
    print("保存:", out, f"{out.stat().st_size / 1e6:.1f}MB")
