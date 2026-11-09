"""
Descarga satelital directa desde catálogos en la nube a la capa Bronze.

Sentinel-2 L2A (Earth Search / AWS Open Data) y Hansen GFC (Google Cloud Storage)
se leen como Cloud Optimized GeoTIFF: solo se transfieren los bloques que caen
dentro del área de estudio, nunca la escena completa.

Se ejecuta igual en Databricks (escribiendo en el Volume) o en una PC local.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling

from . import config as C
from .gridio import GDAL_ENV, write_tiles, warp_to_grid


def has_internet(urls=(C.STAC_URL, C.HANSEN_BASE + "/lossyear.txt"), timeout=10) -> dict:
    """Comprueba si el cómputo actual puede llegar a cada catálogo."""
    import requests
    out = {}
    for u in urls:
        try:
            out[u] = requests.get(u, timeout=timeout).status_code < 400
        except Exception:
            out[u] = False
    return out


# ---------------------------------------------------------------------------
# Sentinel-2
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
        print(f"[S2] {y}: {len(items)} escenas en {used_col}, {len(df)} seleccionadas "
              f"({n_tiles} teselas MGRS, nubosidad media {df.cloud.mean():.1f}%)")
        for _, r in df.iterrows():
            selected.append((y, used_col, r["item"], r["mgrs"], r["cloud"], r["aoi_frac"]))
    return selected


def scale_offset(item, asset_key):
    """
    Escala y offset a reflectancia de superficie.

    Desde el processing baseline 04.00 (enero 2022) ESA suma +1000 a los DN (offset -0.1).
    En la colección antigua 'sentinel-2-l2a' de Earth Search ese offset YA viene aplicado
    (propiedad earthsearch:boa_offset_applied = true); aplicarlo de nuevo vuelve negativa la
    reflectancia y dispara el NDVI fuera de [-1, 1].
    """
    rb = item.assets[asset_key].extra_fields.get("raster:bands") or [{}]
    scale, offset = rb[0].get("scale"), rb[0].get("offset")
    if scale is None:
        scale = 1e-4
    if item.properties.get("earthsearch:boa_offset_applied") is True:
        return scale, 0.0
    if offset is None:
        baseline = float(item.properties.get("s2:processing_baseline", "0") or 0)
        offset = -0.1 if baseline >= 4.0 else 0.0
    return scale, offset


def _to_reflectance(dn, s, o):
    """DN -> reflectancia*1e4 (int16). Devuelve también la fracción de píxeles válidos negativos."""
    valid = dn > 0
    refl = np.where(valid, np.round((dn * s + o) * 10_000), C.NODATA_INT16)
    neg = float((refl[valid] < 0).mean()) if valid.any() else 0.0
    return refl, neg


def download_item(bronze: Path, year, col, item, mgrs, cloud, frac) -> dict:
    out_name = f"{item.id}.tif"
    if list((bronze / "s2" / f"year={year}").glob(f"tile=*/{out_name}")):
        return {"item_id": item.id, "year": year, "status": "ya existía"}
    bands, offset_fix = [], False
    with rasterio.Env(**GDAL_ENV):
        for key in C.S2_ASSETS[:-1]:
            dn = warp_to_grid(item.assets[key].href, Resampling.average, nodata=0).astype(np.float32)
            s, o = scale_offset(item, key)
            refl, neg = _to_reflectance(dn, s, o)
            # Control de calidad: si el offset deja >20 % de reflectancias negativas, ya venía aplicado
            if o != 0 and neg > 0.20:
                refl, neg = _to_reflectance(dn, s, 0.0)
                offset_fix = True
            bands.append(np.clip(refl, -2000, 30000).astype(np.int16))
        scl = warp_to_grid(item.assets["scl"].href, Resampling.nearest, nodata=0).astype(np.int16)
    n = write_tiles(np.stack(bands + [scl]),
                    lambda tr, tc: bronze / "s2" / f"year={year}" / f"tile=r{tr:02d}_c{tc:02d}",
                    out_name, "int16", C.NODATA_INT16,
                    skip_fn=lambda sub: not np.isin(sub[-1], C.SCL_VALID).any())
    return {"item_id": item.id, "year": year, "collection": col, "mgrs": mgrs,
            "datetime": item.properties.get("datetime"), "cloud_cover": cloud,
            "aoi_fraction": round(frac, 3), "tiles": n, "status": "descargado",
            "offset_aplicado_por_proveedor": bool(item.properties.get("earthsearch:boa_offset_applied")) or offset_fix}


def purge_years(bronze, years):
    """Borra las teselas y metadatos de los años indicados para volver a descargarlos."""
    import shutil
    bronze = Path(bronze)
    for y in years:
        d = bronze / "s2" / f"year={y}"
        if d.exists():
            shutil.rmtree(d)
            print(f"[S2] {y}: teselas anteriores eliminadas")
    meta = bronze / "s2_items.csv"
    if meta.exists():
        df = pd.read_csv(meta)
        df[~df["year"].isin(years)].to_csv(meta, index=False)


def run_s2(bronze, years=None, max_items=None, workers=4):
    bronze = Path(bronze)
    selected = search_items(years or C.YEARS, max_items or C.MAX_ITEMS_PER_YEAR)
    meta = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(download_item, bronze, *s): s[2].id for s in selected}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                m = f.result()
            except Exception as e:
                m = {"item_id": futs[f], "status": f"error: {e}"}
            meta.append(m)
            print(f"  [{i}/{len(futs)}] {m['item_id']}: {m['status']}")
    path = bronze / "s2_items.csv"
    new = pd.DataFrame(meta)
    new = new[new.status == "descargado"]
    if path.exists():
        new = pd.concat([pd.read_csv(path), new]).drop_duplicates("item_id", keep="last")
    new.to_csv(path, index=False)
    return new


# ---------------------------------------------------------------------------
# Hansen GFC
# ---------------------------------------------------------------------------
def run_hansen(bronze):
    bronze = Path(bronze)
    layers = []
    with rasterio.Env(**GDAL_ENV):
        for layer in C.HANSEN_LAYERS:
            merged = None
            for t in C.HANSEN_TILES:
                url = f"/vsicurl/{C.HANSEN_BASE}/Hansen_{C.HANSEN_VERSION}_{layer}_{t}.tif"
                print(f"[Hansen] {layer} {t} (lectura por ventanas remotas)")
                arr = warp_to_grid(url, Resampling.nearest, nodata=255)
                merged = arr if merged is None else np.where(merged == 255, arr, merged)
            layers.append(merged)
    n = write_tiles(np.stack(layers).astype(np.uint8),
                    lambda tr, tc: bronze / "hansen" / f"tile=r{tr:02d}_c{tc:02d}", "hansen.tif", "uint8", 255)
    print(f"[Hansen] {n} teselas")
