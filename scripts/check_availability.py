"""
Verifica la disponibilidad de todas las fuentes de datos antes de descargar.

Uso:
    python scripts/check_availability.py

Genera data/availability_report.csv con el inventario de escenas Sentinel-2
por año y colección, y comprueba el acceso a Hansen GFC, GADM y OpenStreetMap.
"""
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from geocloud import config as C  # noqa: E402


def check_stac() -> pd.DataFrame:
    from pystac_client import Client

    client = Client.open(C.STAC_URL)
    rows = []
    for col in C.STAC_COLLECTIONS:
        for y in C.YEARS:
            dt = f"{y}-{C.SEASON[0]}/{y}-{C.SEASON[1]}"
            try:
                items = list(client.search(collections=[col], bbox=C.AOI_BBOX_WGS84, datetime=dt,
                                           max_items=500).items())
            except Exception as e:  # colección inexistente o error de red
                rows.append({"fuente": col, "anio": y, "escenas": 0, "detalle": f"error: {e}"})
                continue
            clouds = [i.properties.get("eo:cloud_cover", 100) for i in items]
            tiles = sorted({i.properties.get("s2:mgrs_tile") or i.properties.get("grid:code", "?") for i in items})
            usable = sum(c < C.MAX_CLOUD for c in clouds)
            rows.append({
                "fuente": col, "anio": y, "escenas": len(items), "escenas_usables": usable,
                "nubosidad_min": round(min(clouds), 1) if clouds else None,
                "nubosidad_mediana": round(pd.Series(clouds).median(), 1) if clouds else None,
                "teselas_mgrs": ",".join(map(str, tiles)), "detalle": "ok" if items else "sin escenas",
            })
            print(f"  {col:20s} {y}: {len(items):3d} escenas ({usable} con nubosidad < {C.MAX_CLOUD}%)")
    return pd.DataFrame(rows)


def check_url(name: str, url: str) -> dict:
    try:
        r = requests.head(url, timeout=30, allow_redirects=True)
        ok = r.status_code < 400
        size = int(r.headers.get("Content-Length", 0)) / 1e6
        detail = f"HTTP {r.status_code}" + (f", {size:.1f} MB" if size else "")
    except Exception as e:
        ok, detail = False, str(e)
    print(f"  {name:35s} {'OK ' if ok else 'ERR'} {detail}")
    return {"fuente": name, "anio": None, "escenas": None, "detalle": detail if ok else f"error: {detail}"}


def main():
    print("Sentinel-2 L2A (Earth Search, AWS Open Data):")
    df = check_stac()
    extra = []
    print("\nHansen Global Forest Change:")
    for t in C.HANSEN_TILES:
        for layer in C.HANSEN_LAYERS:
            url = f"{C.HANSEN_BASE}/Hansen_{C.HANSEN_VERSION}_{layer}_{t}.tif"
            extra.append(check_url(f"Hansen {layer} {t}", url))
    print("\nLímites administrativos:")
    extra.append(check_url("GADM 4.1 Perú nivel 3 (distritos)", C.GADM_URL))
    print("\nOpenStreetMap (Overpass):")
    extra.append(check_url("Overpass API", "https://overpass-api.de/api/status"))

    report = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)
    out = ROOT / "data" / "availability_report.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(out, index=False, encoding="utf-8")
    print(f"\nReporte guardado en {out}")


if __name__ == "__main__":
    main()
