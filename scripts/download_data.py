"""
Descarga local de respaldo (plan B).

El flujo principal corre en Databricks (notebook 00): la descarga satelital y la
ingesta de las fuentes oficiales se hacen directamente en la nube. Este script
solo se usa si el workspace no tiene salida a internet (Databricks Free Edition
sin verificar): descarga Sentinel-2 y Hansen a data/bronze para luego subirlos
con la Databricks CLI.

Uso:
    python scripts/download_data.py                       # Sentinel-2 + Hansen
    python scripts/download_data.py --years 2018 2025 --max-items 6
    python scripts/download_data.py --solo-landing        # procesa data/landing localmente
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from geocloud import config as C  # noqa: E402
from geocloud import download, ingest  # noqa: E402

BRONZE = ROOT / "data" / "bronze"
LANDING = ROOT / "data" / "landing"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", nargs="+", type=int, default=C.YEARS)
    ap.add_argument("--max-items", type=int, default=C.MAX_ITEMS_PER_YEAR)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--skip-s2", action="store_true")
    ap.add_argument("--skip-hansen", action="store_true")
    ap.add_argument("--solo-landing", action="store_true", help="solo ingesta de data/landing (sin internet)")
    a = ap.parse_args()

    BRONZE.mkdir(parents=True, exist_ok=True)
    g = C.Grid()
    (BRONZE / "grid.json").write_text(json.dumps(
        {"crs": g.crs, "bounds": g.bounds, "res": g.res, "width": g.width, "height": g.height,
         "tile_px": g.tile, "n_tiles": g.n_tiles, "aoi_bbox_wgs84": C.AOI_BBOX_WGS84, "years": a.years,
         "created": datetime.now().isoformat(timespec="seconds")}, indent=2))
    print(f"Grilla: {g.width} x {g.height} px a {g.res} m, {g.n_tiles} teselas de {g.tile} px")

    if a.solo_landing:
        ingest.ingest_all(LANDING, BRONZE)
        return
    if not a.skip_hansen:
        download.run_hansen(BRONZE)
    if not a.skip_s2:
        download.run_s2(BRONZE, a.years, a.max_items, a.workers)
    total = sum(f.stat().st_size for f in BRONZE.rglob("*") if f.is_file()) / 1e9
    print(f"\nListo. Bronze local en {BRONZE} ({total:.2f} GB)")


if __name__ == "__main__":
    main()
