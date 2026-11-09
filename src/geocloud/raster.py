"""
Procesamiento raster por tesela.

Estas funciones se ejecutan dentro de los workers de Spark (applyInPandas):
cada tarea recibe los bytes de todas las escenas de una tesela y un año,
construye el compuesto por mediana sin nubes y devuelve una fila por píxel.
Son funciones puras (numpy + rasterio), por eso se pueden probar fuera de Spark.
"""
from typing import Dict, List

import numpy as np
import pandas as pd

from .config import GRID_BOUNDS_UTM, NODATA_INT16, S2_BANDS, SCL_VALID

EPS = 1e-6


def read_tif_bytes(content: bytes):
    """Abre un GeoTIFF desde bytes y devuelve (array, transform, crs)."""
    from rasterio.io import MemoryFile
    with MemoryFile(content) as mem:
        with mem.open() as ds:
            return ds.read(), ds.transform, ds.crs


def spectral_indices(b: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """
    Índices espectrales sobre reflectancia (0-1).

    NDVI  = (NIR - R) / (NIR + R)            vigor de la vegetación
    NBR   = (NIR - SWIR2) / (NIR + SWIR2)    perturbación / remoción de cobertura
    NDWI  = (G - NIR) / (G + NIR)            agua abierta (McFeeters)
    MNDWI = (G - SWIR1) / (G + SWIR1)        agua turbia: pozas mineras
    BSI   = ((SWIR1 + R) - (NIR + B)) / ((SWIR1 + R) + (NIR + B))   suelo desnudo
    """
    B, G, R, N, S1, S2 = (b[k] for k in S2_BANDS)
    return {
        "ndvi": (N - R) / (N + R + EPS),
        "nbr": (N - S2) / (N + S2 + EPS),
        "ndwi": (G - N) / (G + N + EPS),
        "mndwi": (G - S1) / (G + S1 + EPS),
        "bsi": ((S1 + R) - (N + B)) / ((S1 + R) + (N + B) + EPS),
    }


def median_composite(stacks: List[np.ndarray]) -> Dict[str, np.ndarray]:
    """
    Compuesto por mediana enmascarando nubes con la banda SCL.

    stacks: lista de arrays (7, h, w) int16 -> 6 bandas (reflectancia*10000) + SCL.
    Devuelve bandas medianas en reflectancia (float32) y el número de
    observaciones válidas por píxel.
    """
    data = np.stack(stacks).astype(np.float32)          # (n_escenas, 7, h, w)
    scl = data[:, -1]
    refl = data[:, :-1]
    valid = np.isin(scl, SCL_VALID) & np.all(refl != NODATA_INT16, axis=1)
    refl = np.where(valid[:, None], refl / 10_000.0, np.nan)
    n_obs = valid.sum(axis=0).astype(np.int16)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            med = np.nanmedian(refl, axis=0)            # (6, h, w)
    out = {band: med[i] for i, band in enumerate(S2_BANDS)}
    out["n_obs"] = n_obs
    return out


def pixel_frame(arrays: Dict[str, np.ndarray], transform, crs, row0: int, col0: int,
                drop_empty_key: str = None) -> pd.DataFrame:
    """
    Convierte arrays (h, w) a DataFrame de píxeles con coordenadas UTM y WGS84.
    row0/col0 son el desplazamiento de la tesela en la grilla global, de modo
    que (row, col) identifica el píxel de forma única en todo el AOI.
    """
    from pyproj import Transformer
    any_arr = next(iter(arrays.values()))
    h, w = any_arr.shape
    rr, cc = np.mgrid[0:h, 0:w]
    xs = transform.c + (cc + 0.5) * transform.a
    ys = transform.f + (rr + 0.5) * transform.e
    lon, lat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(xs.ravel(), ys.ravel())
    df = pd.DataFrame({
        "row": (rr.ravel() + row0).astype(np.int32),
        "col": (cc.ravel() + col0).astype(np.int32),
        "x": xs.ravel().astype(np.float64),
        "y": ys.ravel().astype(np.float64),
        "lon": np.asarray(lon, dtype=np.float64),
        "lat": np.asarray(lat, dtype=np.float64),
    })
    for k, v in arrays.items():
        df[k] = v.ravel()
    if drop_empty_key is not None:
        df = df[df[drop_empty_key] > 0]
    return df


def composite_tile_to_pixels(contents: List[bytes]) -> pd.DataFrame:
    """Pipeline completo de una tesela-año: bytes -> compuesto -> índices -> píxeles."""
    stacks, transform, crs = [], None, None
    for c in contents:
        arr, transform, crs = read_tif_bytes(c)
        stacks.append(arr)
    comp = median_composite(stacks)
    idx = spectral_indices({k: comp[k] for k in S2_BANDS})
    arrays = {k.lower(): comp[k].astype(np.float32) for k in S2_BANDS}
    arrays.update({k: v.astype(np.float32) for k, v in idx.items()})
    arrays["n_obs"] = comp["n_obs"]
    row0 = int(round((transform.f - _grid_top()) / transform.e))
    col0 = int(round((transform.c - _grid_left()) / transform.a))
    return pixel_frame(arrays, transform, crs, row0, col0, drop_empty_key="n_obs")


def hansen_tile_to_pixels(content: bytes) -> pd.DataFrame:
    """Tesela Hansen (2 bandas: lossyear, treecover2000) -> píxeles."""
    arr, transform, crs = read_tif_bytes(content)
    row0 = int(round((transform.f - _grid_top()) / transform.e))
    col0 = int(round((transform.c - _grid_left()) / transform.a))
    df = pixel_frame({"lossyear": arr[0].astype(np.int16), "treecover2000": arr[1].astype(np.int16)},
                     transform, crs, row0, col0)
    return df[["row", "col", "lon", "lat", "lossyear", "treecover2000"]]


def _grid_top() -> float:
    return GRID_BOUNDS_UTM[3]


def _grid_left() -> float:
    return GRID_BOUNDS_UTM[0]


def register_for_spark():
    """
    Serializa este módulo por valor para que los workers de Spark no necesiten
    tener el paquete geocloud instalado (clave en serverless).
    """
    import sys
    from pyspark import cloudpickle
    cloudpickle.register_pickle_by_value(sys.modules[__name__])
