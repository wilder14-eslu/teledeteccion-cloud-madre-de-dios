"""
Descarga y prepara la capa Bronze del proyecto.

Fuentes:
  1. Sentinel-2 L2A (Earth Search / AWS Open Data): escenas de temporada seca,
     recortadas a la grilla del AOI (UTM 19S, 20 m) y partidas en teselas.
  2. Hansen Global Forest Change v1.12: lossyear y treecover2000 en la misma grilla.
  3. GADM 4.1: distritos de Madre de Dios.
  4. OpenStreetMap: vías principales, ríos y áreas naturales protegidas.

Uso:
    python scripts/download_data.py                  # todo
    python scripts/download_data.py --years 2018 2024 --max-items 8
    python scripts/download_data.py --skip-s2        # solo Hansen y vectores

Salida (data/bronze/):
    s2/year=YYYY/tile=rRR_cCC/<item_id>.tif   7 bandas int16 (6 reflectancias*1e4 + SCL)
    hansen/tile=rRR_cCC/hansen.tif           2 bandas uint8 (lossyear, treecover2000)
    vector/*.geojson
    s2_items.csv, grid.json
"""
import argparse
import io
import json
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import requests
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from geocloud import config as C  # noqa: E402

BRONZE = ROOT / "data" / "bronze"
GRID = C.Grid()

GDAL_ENV = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    AWS_NO_SIGN_REQUEST="YES",
    GDAL_HTTP_MAX_RETRY="5",
    GDAL_HTTP_RETRY_DELAY="2",
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF,.tiff",
    VSI_CACHE="TRUE",
)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def warp_to_grid(href: str, resampling: Resampling, nodata=None) -> np.ndarray:
    """Lee un raster remoto (COG) directamente reproyectado y recortado a la grilla del AOI."""
    with rasterio.open(href) as src:
        vrt_opts = dict(crs=GRID.crs, transform=GRID.transform(), width=GRID.width,
                        height=GRID.height, resampling=resampling)
        if nodata is not None:
            vrt_opts["nodata"] = nodata
        with WarpedVRT(src, **vrt_opts) as vrt:
            return vrt.read(1)


def write_tiles(stack: np.ndarray, out_dir_fn, filename: str, dtype: str, nodata, skip_fn=None) -> int:
    """Parte un stack (bandas, H, W) en teselas GeoTIFF comprimidas."""
    n = 0
    for tr, tc, win in GRID.tile_windows():
        sub = stack[:, win.row_off:win.row_off + win.height, win.col_off:win.col_off + win.width]
        if skip_fn is not None and skip_fn(sub):
            continue
        out_dir = out_dir_fn(tr, tc)
        out_dir.mkdir(parents=True, exist_ok=True)
        profile = dict(driver="GTiff", height=win.height, width=win.width, count=sub.shape[0],
                       dtype=dtype, crs=GRID.crs, transform=rasterio.windows.transform(win, GRID.transform()),
                       compress="deflate", predictor=2, tiled=True, blockxsize=256, blockysize=256,
                       nodata=nodata)
        with rasterio.open(out_dir / filename, "w", **profile) as dst:
            dst.write(sub.astype(dtype))
        n += 1
    return n


# ---------------------------------------------------------------------------
# 1. Sentinel-2
# ---------------------------------------------------------------------------
def search_items(years, max_items):
    from pystac_client import Client
    from shapely.geometry import box, shape

    client = Client.open(C.STAC_URL)
    aoi = box(*C.AOI_BBOX_WGS84)
    selected = []
    for y in years:
        dt = f"{y}-{C.SEASON[0]}/{y}-{C.SEASON[1]}"
        items, used_col = [], None
        for col in C.STAC_COLLECTIONS:
            items = list(client.search(collections=[col], bbox=C.AOI_BBOX_WGS84, datetime=dt,
                                       query={"eo:cloud_cover": {"lt": C.MAX_CLOUD}}, max_items=500).items())
            if items:
                used_col = col
                break
        if not items:
            print(f"[S2] {y}: sin escenas disponibles")
            continue
        rows = []
        for it in items:
            frac = shape(it.geometry).intersection(aoi).area / aoi.area
            rows.append((it, it.properties.get("s2:mgrs_tile") or it.properties.get("grid:code", "?"),
                         it.properties.get("eo:cloud_cover", 100), frac))
        df = pd.DataFrame(rows, columns=["item", "mgrs", "cloud", "aoi_frac"])
        df = df[df.aoi_frac > 0.05]
        n_tiles = max(df.mgrs.nunique(), 1)
        per_tile = max(2, -(-max_items // n_tiles))
        df = df.sort_values("cloud").groupby("mgrs", group_keys=False).head(per_tile)
        print(f"[S2] {y}: {len(items)} escenas encontradas en {used_col}, {len(df)} seleccionadas "
              f"({n_tiles} teselas MGRS, nubosidad media {df.cloud.mean():.1f}%)")
        for _, r in df.iterrows():
            selected.append((y, used_col, r["item"], r["mgrs"], r["cloud"], r["aoi_frac"]))
    return selected


def scale_offset(item, asset_key):
    """Factor de escala y offset a reflectancia (cambio de baseline 04.00 en 2022)."""
    rb = item.assets[asset_key].extra_fields.get("raster:bands") or [{}]
    scale = rb[0].get("scale")
    offset = rb[0].get("offset")
    if scale is None:
        scale = 1e-4
    if offset is None:
        baseline = float(item.properties.get("s2:processing_baseline", "0") or 0)
        offset = -0.1 if baseline >= 4.0 else 0.0
    return scale, offset


def download_item(year, col, item, mgrs, cloud, frac) -> dict:
    out_name = f"{item.id}.tif"
    existing = list((BRONZE / "s2" / f"year={year}").glob(f"tile=*/{out_name}"))
    if existing:
        return {"item_id": item.id, "year": year, "status": "ya existía", "tiles": len(existing)}
    bands = []
    with rasterio.Env(**GDAL_ENV):
        for key in C.S2_ASSETS[:-1]:
            dn = warp_to_grid(item.assets[key].href, Resampling.average, nodata=0).astype(np.float32)
            s, o = scale_offset(item, key)
            refl = np.where(dn > 0, np.round((dn * s + o) * 10_000), C.NODATA_INT16)
            bands.append(np.clip(refl, -2000, 30000).astype(np.int16))
        scl = warp_to_grid(item.assets["scl"].href, Resampling.nearest, nodata=0).astype(np.int16)
    stack = np.stack(bands + [scl])
    n = write_tiles(stack,
                    lambda tr, tc: BRONZE / "s2" / f"year={year}" / f"tile=r{tr:02d}_c{tc:02d}",
                    out_name, "int16", C.NODATA_INT16,
                    skip_fn=lambda sub: not np.isin(sub[-1], C.SCL_VALID).any())
    return {"item_id": item.id, "year": year, "collection": col, "mgrs": mgrs,
            "datetime": item.properties.get("datetime"), "cloud_cover": cloud,
            "aoi_fraction": round(frac, 3), "tiles": n, "status": "descargado"}


def run_s2(years, max_items, workers):
    selected = search_items(years, max_items)
    meta = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(download_item, *s): s[2].id for s in selected}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                m = f.result()
            except Exception as e:
                m = {"item_id": futs[f], "status": f"error: {e}"}
            meta.append(m)
            print(f"  [{i}/{len(futs)}] {m['item_id']}: {m['status']} ({m.get('tiles', 0)} teselas)")
    path = BRONZE / "s2_items.csv"
    new = pd.DataFrame(meta)
    if path.exists():
        old = pd.read_csv(path)
        new = pd.concat([old, new[new.status == "descargado"]]).drop_duplicates("item_id", keep="last")
    new.to_csv(path, index=False)


# ---------------------------------------------------------------------------
# 2. Hansen GFC
# ---------------------------------------------------------------------------
def run_hansen():
    layers = []
    with rasterio.Env(**GDAL_ENV):
        for layer in C.HANSEN_LAYERS:
            merged = None
            for t in C.HANSEN_TILES:
                url = f"/vsicurl/{C.HANSEN_BASE}/Hansen_{C.HANSEN_VERSION}_{layer}_{t}.tif"
                print(f"[Hansen] leyendo {layer} {t} (lectura por ventanas remotas)...")
                arr = warp_to_grid(url, Resampling.nearest, nodata=255)
                merged = arr if merged is None else np.where(merged == 255, arr, merged)
            layers.append(merged)
    stack = np.stack(layers).astype(np.uint8)
    n = write_tiles(stack, lambda tr, tc: BRONZE / "hansen" / f"tile=r{tr:02d}_c{tc:02d}",
                    "hansen.tif", "uint8", 255)
    print(f"[Hansen] {n} teselas escritas")


# ---------------------------------------------------------------------------
# 3. Vectores
# ---------------------------------------------------------------------------
def run_vectors():
    import geopandas as gpd
    from shapely.geometry import box

    out = BRONZE / "vector"
    out.mkdir(parents=True, exist_ok=True)
    aoi = box(*C.AOI_BBOX_WGS84)

    print("[GADM] descargando distritos del Perú...")
    r = requests.get(C.GADM_URL, timeout=300)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name = [n for n in z.namelist() if n.endswith(".json")][0]
        gdf = gpd.read_file(io.BytesIO(z.read(name)))
    gdf = gdf[gdf["NAME_1"].str.replace(" ", "").str.lower() == "madrededios"]
    gdf = gdf[["GID_3", "NAME_1", "NAME_2", "NAME_3", "geometry"]].rename(
        columns={"NAME_1": "departamento", "NAME_2": "provincia", "NAME_3": "distrito"})
    gdf.to_file(out / "distritos_madre_de_dios.geojson", driver="GeoJSON")
    print(f"[GADM] {len(gdf)} distritos de Madre de Dios")

    import osmnx as ox
    ox.settings.requests_timeout = 300
    bbox = C.AOI_BBOX_WGS84  # (left, bottom, right, top)
    big = (bbox[0] - 0.15, bbox[1] - 0.15, bbox[2] + 0.15, bbox[3] + 0.15)
    layers = {
        "vias": ({"highway": ["trunk", "primary", "secondary"]}, ["name", "ref", "highway"], bbox),
        "rios": ({"waterway": ["river"]}, ["name", "waterway"], bbox),
        "areas_protegidas": ({"boundary": "protected_area", "leisure": "nature_reserve"},
                             ["name", "protect_class", "boundary", "leisure"], big),
    }
    for name, (tags, cols, bb) in layers.items():
        print(f"[OSM] {name}...")
        try:
            g = ox.features_from_bbox(bbox=bb, tags=tags).reset_index()
        except Exception as e:
            print(f"[OSM] {name}: error {e}")
            continue
        keep = [c for c in cols if c in g.columns]
        g = g[keep + ["geometry"]].copy()
        for c in keep:
            g[c] = g[c].astype(str).replace("nan", None)
        if name == "areas_protegidas":
            g = g[g.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
        else:
            g = g[g.geometry.geom_type.isin(["LineString", "MultiLineString"])]
            g = g[g.intersects(aoi.buffer(0.05))]
        g.to_file(out / f"{name}.geojson", driver="GeoJSON")
        print(f"[OSM] {name}: {len(g)} geometrías")


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", nargs="+", type=int, default=C.YEARS)
    ap.add_argument("--max-items", type=int, default=C.MAX_ITEMS_PER_YEAR)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--skip-s2", action="store_true")
    ap.add_argument("--skip-hansen", action="store_true")
    ap.add_argument("--skip-vectors", action="store_true")
    a = ap.parse_args()

    BRONZE.mkdir(parents=True, exist_ok=True)
    grid_meta = {"crs": GRID.crs, "bounds": GRID.bounds, "res": GRID.res, "width": GRID.width,
                 "height": GRID.height, "tile_px": GRID.tile, "n_tiles": GRID.n_tiles,
                 "aoi_bbox_wgs84": C.AOI_BBOX_WGS84, "years": a.years,
                 "created": datetime.now().isoformat(timespec="seconds")}
    (BRONZE / "grid.json").write_text(json.dumps(grid_meta, indent=2))
    print(f"Grilla: {GRID.width} x {GRID.height} px a {GRID.res} m, {GRID.n_tiles} teselas de {GRID.tile} px")

    if not a.skip_vectors:
        run_vectors()
    if not a.skip_hansen:
        run_hansen()
    if not a.skip_s2:
        run_s2(a.years, a.max_items, a.workers)
    total = sum(f.stat().st_size for f in BRONZE.rglob("*") if f.is_file()) / 1e9
    print(f"\nListo. Capa Bronze en {BRONZE} ({total:.2f} GB)")


if __name__ == "__main__":
    main()
