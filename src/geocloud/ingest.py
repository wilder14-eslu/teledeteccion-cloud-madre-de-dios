"""
Ingesta landing → bronze de las fuentes oficiales, ejecutada en la nube.

La zona *landing* recibe los archivos tal como los publica cada institución
(zip con shapefiles o rasters nacionales). Aquí se descomprimen, se recortan al
área de estudio y se alinean a la grilla común:

  landing/sernanp/*.zip        -> bronze/vector/areas_protegidas_sernanp.geojson
                                  bronze/vector/zonas_amortiguamiento.geojson
  landing/gadm/*.zip           -> bronze/vector/distritos_madre_de_dios.geojson
  landing/osm_geofabrik/*.zip  -> bronze/vector/vias.geojson, rios.geojson
  landing/geobosques/*.zip     -> bronze/geobosques/tile=rRR_cCC/geobosques.tif
                                  (b1 pérdida 2001-2025, b2 cobertura 2025, b3 riesgo de deforestación)
  landing/geobosques/*.xlsx    -> bronze/tablas/
"""
import shutil
import tempfile
import zipfile
from pathlib import Path

import numpy as np

from . import config as C
from .gridio import write_tiles, warp_to_grid

# Codificación oficial Geobosques (tabla de atributos del raster)
GEOBOSQUES_PERDIDA = {**{v: f"Pérdida {2000 + v}" for v in range(1, 25)},
                      25: "Pérdida antrópica (deforestación) 2025", 26: "Pérdida natural 2025"}
GEOBOSQUES_COBERTURA = {1: "Hidrografía", 2: "Pérdida 2001-2024", 3: "Pérdida antrópica 2025",
                        4: "Bosque 2025", 5: "No bosque 2000"}
GEOBOSQUES_RIESGO = {1: "Muy bajo", 2: "Bajo", 3: "Medio", 4: "Alto", 5: "Muy alto"}


def _aoi(buffer_deg=0.15):
    from shapely.geometry import box
    return box(*C.AOI_BBOX_WGS84).buffer(buffer_deg)


def _first(landing: Path, sub: str, pattern: str):
    found = sorted((landing / sub).glob(pattern)) if (landing / sub).exists() else []
    return found[0] if found else None


def _read_zip_layer(zip_path: Path, member_suffix: str, bbox=None):
    """Lee una capa vectorial dentro de un zip sin descomprimir todo (GDAL /vsizip)."""
    import geopandas as gpd
    with zipfile.ZipFile(zip_path) as z:
        member = next(n for n in z.namelist() if n.lower().endswith(member_suffix.lower()))
    return gpd.read_file(f"/vsizip/{zip_path}/{member}", bbox=bbox)


def _save(gdf, bronze: Path, name: str):
    out = bronze / "vector" / f"{name}.geojson"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp()) / out.name
    gdf.to_file(tmp, driver="GeoJSON")
    shutil.copyfile(tmp, out)
    return out


def ingest_sernanp(landing: Path, bronze: Path):
    aoi = _aoi()
    res = {}
    for name, pattern, suffix in [("areas_protegidas_sernanp", "*ANP*Definitiva*.zip", ".shp"),
                                  ("zonas_amortiguamiento", "*Amortiguamiento*.zip", ".shp")]:
        z = _first(landing, "sernanp", pattern)
        if z is None:
            print(f"[SERNANP] {name}: no está en landing (opcional)")
            continue
        g = _read_zip_layer(z, suffix).to_crs(4326)
        g = g[g.intersects(aoi)].copy()
        keep = [c for c in ["anp_codi", "anp_nomb", "anp_cate", "c_nomb"] if c in g.columns]
        _save(g[keep + ["geometry"]], bronze, name)
        res[name] = len(g)
        print(f"[SERNANP] {name}: {len(g)} polígonos -> {', '.join(g['anp_nomb'].astype(str).unique()[:4])}")
    return res


def ingest_gadm(landing: Path, bronze: Path):
    """
    Distritos de TODOS los departamentos que toca el área de estudio (Madre de Dios y limítrofes)
    y el límite departamental recortado al área, para no confundir territorios en mapas y tablas.
    """
    import geopandas as gpd
    z = _first(landing, "gadm", "*.zip")
    if z is None:
        print("[GADM] no está en landing")
        return 0
    with zipfile.ZipFile(z) as zz:
        member = next(n for n in zz.namelist() if n.endswith(".json"))
    g = gpd.read_file(f"/vsizip/{z}/{member}")
    g = g[g.intersects(_aoi(0.05))]
    g = g[["GID_3", "NAME_1", "NAME_2", "NAME_3", "geometry"]].rename(
        columns={"NAME_1": "departamento", "NAME_2": "provincia", "NAME_3": "distrito"})
    # GADM escribe "MadredeDios": se normaliza el nombre
    g["departamento"] = g["departamento"].replace({"MadredeDios": "Madre de Dios"})
    _save(g, bronze, "distritos")
    dep = g.dissolve(by="departamento").reset_index()[["departamento", "geometry"]]
    dep["geometry"] = dep.geometry.intersection(_aoi(0.15))
    _save(dep, bronze, "departamentos")
    resumen = g.groupby("departamento")["distrito"].apply(lambda s: ", ".join(sorted(s))).to_dict()
    for d, ds in resumen.items():
        print(f"[GADM] {d}: {ds}")
    return len(g)


def ingest_geofabrik(landing: Path, bronze: Path):
    z = _first(landing, "osm_geofabrik", "*.zip")
    if z is None:
        print("[OSM] Geofabrik no está en landing")
        return 0
    bb = tuple(_aoi(0.05).bounds)
    roads = _read_zip_layer(z, "gis_osm_roads_free_1.shp", bbox=bb)
    roads = roads[roads["fclass"].isin(["trunk", "primary", "secondary", "trunk_link", "primary_link"])]
    roads = roads.rename(columns={"fclass": "highway"})[["name", "ref", "highway", "geometry"]]
    _save(roads, bronze, "vias")
    ww = _read_zip_layer(z, "gis_osm_waterways_free_1.shp", bbox=bb).rename(columns={"fclass": "waterway"})
    rios = ww[ww["waterway"] == "river"][["name", "waterway", "geometry"]]
    _save(rios, bronze, "rios")
    # Red de drenaje completa: la minería aluvial de La Pampa trabaja sobre quebradas, no solo ríos grandes
    cauces = ww[ww["waterway"].isin(["river", "stream"])][["name", "waterway", "geometry"]]
    _save(cauces, bronze, "cauces")
    pl = _read_zip_layer(z, "gis_osm_places_free_1.shp", bbox=bb)
    pl = pl[pl["fclass"].isin(["city", "town", "village"]) & pl["name"].notna()]
    keep = [c for c in ["name", "fclass", "population", "geometry"] if c in pl.columns]
    _save(pl[keep], bronze, "poblados")
    print(f"[OSM] vías principales: {len(roads)} | ríos: {len(rios)} | cauces (ríos + quebradas): {len(cauces)} "
          f"| poblados: {len(pl)} ({', '.join(pl['name'].astype(str).unique()[:6])})")
    return len(roads) + len(cauces) + len(pl)


def ingest_geobosques(landing: Path, bronze: Path):
    """Recorta los rasters nacionales de Geobosques a la grilla de 20 m (vecino más cercano)."""
    from rasterio.enums import Resampling

    specs = [("Perdida_2001_2025_Raster*.zip", "Perdida_2001_2025.tif"),
             ("Bosque_NoBosque_*Raster*.zip", "Bosque_No_Bosque_2025.tif"),
             ("*Riesgo*.zip", "Riesgo_Deforestacion_2018.tif")]
    tmp = Path(tempfile.mkdtemp(prefix="geobosques_"))
    layers = []
    try:
        for zip_hint, tif_name in specs:
            z = _first(landing, "geobosques", zip_hint)
            if z is None:
                print(f"[Geobosques] falta {zip_hint}; se rellena con 0")
                layers.append(np.zeros((C.Grid().height, C.Grid().width), np.uint8))
                continue
            with zipfile.ZipFile(z) as zz:
                members = [n for n in zz.namelist()
                           if not n.endswith("/") and Path(n).name.startswith(Path(tif_name).stem)]
                for m in members:                     # tif + tfw + ovr + aux: GDAL usa todos
                    target = tmp / Path(m).name
                    with zz.open(m) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
            arr = warp_to_grid(str(tmp / tif_name), Resampling.nearest)   # categórico: sin nodata para no alterar el 0
            layers.append(arr.astype(np.uint8))
            vals, cnt = np.unique(arr, return_counts=True)
            print(f"[Geobosques] {tif_name}: valores en el área {dict(zip(vals.tolist(), cnt.tolist()))}")
            for f in tmp.iterdir():
                f.unlink()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    n = write_tiles(np.stack(layers), lambda tr, tc: bronze / "geobosques" / f"tile=r{tr:02d}_c{tc:02d}",
                    "geobosques.tif", "uint8", 0)
    tables = list((landing / "geobosques").glob("*.xlsx")) if (landing / "geobosques").exists() else []
    for t in tables:
        (bronze / "tablas").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(t, bronze / "tablas" / t.name)
    print(f"[Geobosques] {n} teselas | {len(tables)} tablas oficiales copiadas")
    return n


def ingest_all(landing, bronze):
    landing, bronze = Path(landing), Path(bronze)
    return {"sernanp": ingest_sernanp(landing, bronze), "gadm": ingest_gadm(landing, bronze),
            "osm": ingest_geofabrik(landing, bronze), "geobosques": ingest_geobosques(landing, bronze)}
