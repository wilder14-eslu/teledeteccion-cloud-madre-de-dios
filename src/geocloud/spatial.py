"""
Utilidades de estadística espacial sobre la grilla hexagonal H3.

- Matriz de pesos W a partir de la vecindad k-ring de H3 (contigüidad tipo reina
  en hexágonos: cada celda tiene exactamente 6 vecinos de primer orden).
- Geometrías de hexágonos para mapas.
- Función K de Ripley con envolventes de Monte Carlo bajo CSR.
"""
from typing import Iterable, Tuple

import numpy as np
import pandas as pd


def h3_weights(cells: Iterable[str], k: int = 1, row_standardize: bool = True):
    """Construye libpysal.weights.W con vecinos H3 a distancia <= k."""
    import h3
    from libpysal.weights import W

    cells = list(cells)
    present = set(cells)
    neighbors = {}
    for c in cells:
        neigh = [n for n in h3.grid_disk(c, k) if n != c and n in present]
        neighbors[c] = neigh
    w = W(neighbors, id_order=cells, silence_warnings=True)
    if row_standardize:
        w.transform = "r"
    return w


def h3_to_geodataframe(df: pd.DataFrame, cell_col: str = "h3", crs_out: str = None):
    """Agrega la geometría poligonal de cada hexágono H3."""
    import geopandas as gpd
    import h3
    from shapely.geometry import Polygon

    geoms = [Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)]) for c in df[cell_col]]
    gdf = gpd.GeoDataFrame(df.copy(), geometry=geoms, crs="EPSG:4326")
    return gdf.to_crs(crs_out) if crs_out else gdf


def ripley_k(points: np.ndarray, bounds: Tuple[float, float, float, float], radii: np.ndarray) -> np.ndarray:
    """
    Estimador de K(r) con corrección de borde por 'buffer' (border method):
    solo se usan como centros los puntos a distancia >= r del borde.
    """
    from scipy.spatial import cKDTree

    xmin, ymin, xmax, ymax = bounds
    area = (xmax - xmin) * (ymax - ymin)
    n = len(points)
    lam = n / area
    tree = cKDTree(points)
    d_border = np.minimum.reduce([points[:, 0] - xmin, xmax - points[:, 0],
                                  points[:, 1] - ymin, ymax - points[:, 1]])
    k_vals = np.empty(len(radii))
    for i, r in enumerate(radii):
        centers = points[d_border >= r]
        if len(centers) == 0:
            k_vals[i] = np.nan
            continue
        counts = tree.query_ball_point(centers, r, return_length=True) - 1
        k_vals[i] = counts.mean() / lam
    return k_vals


def ripley_envelope(n: int, bounds, radii, n_sim: int = 99, seed: int = 42):
    """Envolventes de K(r) bajo Aleatoriedad Espacial Completa (CSR)."""
    rng = np.random.default_rng(seed)
    xmin, ymin, xmax, ymax = bounds
    sims = np.empty((n_sim, len(radii)))
    for s in range(n_sim):
        pts = np.column_stack([rng.uniform(xmin, xmax, n), rng.uniform(ymin, ymax, n)])
        sims[s] = ripley_k(pts, bounds, radii)
    return np.nanmin(sims, axis=0), np.nanmax(sims, axis=0)
