"""地図のカット：Natural Earth（パブリックドメイン）の陸地と川を描き、地名のピンと移動の線をアニメーションする。
script.json の場面に次のように書く（経度・緯度）:
 "kind":"map", "map": {
   "view_from":[経度西, 緯度南, 経度東, 緯度北], "view_to":[...],          # 画面に入れる範囲（始め→終わり）
   "points":[{"name":"パリ","lon":2.35,"lat":48.86,"at":0.3}],            # at=出る時刻（秒）
   "routes":[{"from":"パリ","to":"ウィーン","at":0.8,"dur":2.0}] }         # 赤い線が伸びる
"""
import json, math, pathlib
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from common import HOME, W, FPS, font, WHITE, RED, shadowed
from common import CH as H   # 地図も上下の黒帯を除いた帯（1920×816）で描く
from shots import pipe_writer, ease

_D = HOME / "naturalearth"
if not (_D / "ne_50m_land.geojson").exists():
    raise SystemExit("地図のデータがありません。先に python3 fetch_map_data.py を流してください")
LAND = json.loads((_D / "ne_50m_land.geojson").read_text())
RIVERS = json.loads((_D / "ne_50m_rivers.geojson").read_text())
SEA, LANDC, COAST, RIVER = (11, 14, 20), (46, 43, 38), (216, 210, 196), (92, 118, 150)
SS = 2   # 下地は2倍の解像度で描いて切り出す


def _rings(geom):
    if geom["type"] == "Polygon":
        return geom["coordinates"]
    if geom["type"] == "MultiPolygon":
        return [r for poly in geom["coordinates"] for r in poly]
    return []


def _lines(geom):
    if geom["type"] == "LineString":
        return [geom["coordinates"]]
    if geom["type"] == "MultiLineString":
        return geom["coordinates"]
    return []


def render_map(meta, out, dur):
    m = meta["map"]

    def widen(v, minw=12.0):
        """狭すぎる範囲は、海岸線や国の形が見える広さ（経度 minw 度）まで広げる。"""
        w = v[2] - v[0]
        if w >= minw:
            return v
        cx, cy, k = (v[0] + v[2]) / 2, (v[1] + v[3]) / 2, minw / max(w, 0.01)
        return [cx - minw / 2, cy - (v[3] - v[1]) * k / 2, cx + minw / 2, cy + (v[3] - v[1]) * k / 2]
    v0, v1 = widen(m["view_from"]), widen(m.get("view_to", m["view_from"]))
    lon_a, lat_a = min(v0[0], v1[0]) - 2, min(v0[1], v1[1]) - 2
    lon_b, lat_b = max(v0[2], v1[2]) + 2, max(v0[3], v1[3]) + 2
    kx = math.cos(math.radians((lat_a + lat_b) / 2))
    # 全体の下地（経度×kx を横、緯度を縦にした正距円筒）
    px_per_deg = W * SS / ((v1[2] - v1[0]) * kx)   # 終わりの範囲で画面幅いっぱいの解像度
    bw = int((lon_b - lon_a) * kx * px_per_deg); bh = int((lat_b - lat_a) * px_per_deg)
    bw, bh = min(bw, 16000), min(bh, 16000)
    sx = bw / ((lon_b - lon_a) * kx); sy = bh / (lat_b - lat_a)

    def P(lon, lat):
        return ((lon - lon_a) * kx * sx, (lat_b - lat) * sy)
    base = Image.new("RGB", (bw, bh), SEA)
    d = ImageDraw.Draw(base)
    for f in LAND["features"]:
        for ring in _rings(f["geometry"]):
            xs = [c[0] for c in ring]; ys = [c[1] for c in ring]
            if max(xs) < lon_a or min(xs) > lon_b or max(ys) < lat_a or min(ys) > lat_b:
                continue
            pts = [P(*c) for c in ring]
            d.polygon(pts, fill=LANDC)
            d.line(pts + [pts[0]], fill=COAST, width=max(2, SS * 2))
    for f in RIVERS["features"]:
        for ln in _lines(f["geometry"]):
            if any(lon_a < c[0] < lon_b and lat_a < c[1] < lat_b for c in ln):
                d.line([P(*c) for c in ln], fill=RIVER, width=2 * SS)
    # 紙の質感（かすかなまだら）
    noise = np.random.default_rng(3).normal(0, 1, (bh // 24 + 1, bw // 24 + 1))
    noise = np.asarray(Image.fromarray(((noise * 18) + 128).clip(0, 255).astype(np.uint8)).resize((bw, bh), Image.BICUBIC), dtype=np.float32)
    base = Image.fromarray((np.asarray(base, dtype=np.float32) + (noise[..., None] - 128) * 0.25).clip(0, 255).astype(np.uint8))

    pts = {p["name"]: p for p in m.get("points", [])}
    n = int(round(dur * FPS))
    wr = pipe_writer(out)
    lab_font = font(40)
    for i in range(n):
        t = i / FPS
        e = ease(t / max(0.01, dur))
        v = [v0[j] + (v1[j] - v0[j]) * e for j in range(4)]
        x0, y0 = P(v[0], v[3]); x1, y1 = P(v[2], v[1])
        # 16:9 に合わせる
        cw = x1 - x0; ch = cw * H / W; cy = (y0 + y1) / 2
        crop = base.crop((int(x0), int(cy - ch / 2), int(x1), int(cy + ch / 2))).resize((W, H), Image.LANCZOS)
        frame = crop.convert("RGBA")
        k = W / cw

        def S(lon, lat):
            x, y = P(lon, lat)
            return ((x - x0) * k, (y - (cy - ch / 2)) * k)
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
        for r in m.get("routes", []):
            a, b = pts[r["from"]], pts[r["to"]]
            pr = ease((t - r.get("at", 0.5)) / r.get("dur", 2.0))
            if pr <= 0:
                continue
            (ax, ay), (bx, by) = S(a["lon"], a["lat"]), S(b["lon"], b["lat"])
            mx, my = (ax + bx) / 2, min(ay, by) - abs(bx - ax) * 0.15   # ゆるい弧
            seg = []
            for j in range(41):
                u = j / 40 * pr
                seg.append(((1 - u) ** 2 * ax + 2 * (1 - u) * u * mx + u * u * bx, (1 - u) ** 2 * ay + 2 * (1 - u) * u * my + u * u * by))
            od.line(seg, fill=RED + (255,), width=6, joint="curve")
        glow = ov.filter(ImageFilter.GaussianBlur(8))
        frame.alpha_composite(glow); frame.alpha_composite(ov)
        placed = []
        for p in m.get("points", []):
            at = p.get("at", 0.3)
            if t < at:
                continue
            a = min(1, (t - at) / 0.3)
            x, y = S(p["lon"], p["lat"])
            lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
            ring = 14 + ((t - at) % 1.2) / 1.2 * 30
            ld.ellipse([x - ring, y - ring, x + ring, y + ring], outline=RED + (int(255 * (1 - ((t - at) % 1.2) / 1.2) * a),), width=3)
            ld.ellipse([x - 9, y - 9, x + 9, y + 9], fill=RED + (int(255 * a),))
            name = p["name"]

            tw = ld.textlength(name, font=lab_font)
            lx = x + 22
            if lx + tw > W - 40:   # 右端からはみ出すならピンの左に書く
                lx = x - 22 - tw
            # 先に書いた地名と重なるなら上下へずらす
            def hit(a, ty):
                return any(a < bx + bw and bx < a + tw and abs(ty - by) < 46 for bx, by, bw in placed)
            ty = y
            for bx, by, bw in placed:   # 重なる地名があれば、その地名から上下に離す（北にある方を上へ）
                if hit(lx, ty) and abs(ty - by) < 46:
                    ty = by - 50 if y <= by else by + 50
            placed.append((lx, ty, tw))
            y_lab = ty

            def draw(dd, dx, dy, ovc, lx=lx, y=y_lab, name=name):
                dd.text((lx + dx, y - 26 + dy), name, font=lab_font, fill=ovc or WHITE)
            tl = shadowed((W, H), draw, blur=6)
            if a < 1:
                tl.putalpha(Image.eval(tl.getchannel("A"), lambda q, a=a: int(q * a)))
            lay.alpha_composite(tl)
            frame.alpha_composite(lay)
        wr.stdin.write(np.asarray(frame.convert("RGB")).tobytes())
    wr.stdin.close(); wr.wait()
