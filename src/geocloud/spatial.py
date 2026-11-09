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


def ripley_envelope_candidates(n: int, candidates: np.ndarray, jitter: float, bounds, radii,
                               n_sim: int = 99, seed: int = 42):
    """
    Envolventes de K(r) bajo CSR condicionado: los puntos simulados solo caen donde el
    proceso puede ocurrir (por ejemplo, donde había bosque). Se muestrean centros
    candidatos con reemplazo y se desplazan al azar dentro de su celda (jitter).
    """
    rng = np.random.default_rng(seed)
    sims = np.empty((n_sim, len(radii)))
    for s in range(n_sim):
        idx = rng.integers(0, len(candidates), n)
        pts = candidates[idx] + rng.uniform(-jitter, jitter, (n, 2))
        sims[s] = ripley_k(pts, bounds, radii)
    return np.nanmin(sims, axis=0), np.nanmax(sims, axis=0)


def patches_from_mask(mask: np.ndarray, x0: float, y_top: float, res: float, min_px: int = 25):
    """
    Parches (componentes conexos, vecindad de 8) de una máscara booleana raster.
    Devuelve un DataFrame con centroide UTM (km), área (ha) y número de píxeles.
    """
    from scipy import ndimage
    lab, n = ndimage.label(mask, structure=np.ones((3, 3), dtype=bool))
    if n == 0:
        return pd.DataFrame(columns=["x_km", "y_km", "area_ha", "n_px"])
    idx = np.arange(1, n + 1)
    sizes = ndimage.sum(mask, lab, idx)
    cents = np.array(ndimage.center_of_mass(mask, lab, idx))
    df = pd.DataFrame({"n_px": sizes.astype(int),
                       "x_km": (x0 + (cents[:, 1] + 0.5) * res) / 1000,
                       "y_km": (y_top - (cents[:, 0] + 0.5) * res) / 1000})
    df["area_ha"] = df.n_px * res * res / 10_000
    return df[df.n_px >= min_px].reset_index(drop=True)


def decorate_map(ax, bounds, vectors: dict = None, places=None, scale_km: int = 10, legend: bool = True,
                 legend_loc: str = "upper left"):
    """
    Cartografía estándar para mapas en UTM: capas de contexto con leyenda, topónimos,
    barra de escala y flecha de norte.
    vectors: {"Ríos": (gdf, dict(color=..., lw=...)), ...} en el mismo CRS del eje.
    """
    from matplotlib.lines import Line2D
    handles = []
    for label, (g, style) in (vectors or {}).items():
        if g is None or len(g) == 0:
            continue
        geom_type = g.geometry.geom_type.iloc[0]
        if "Polygon" in geom_type:
            g.boundary.plot(ax=ax, **style)
        else:
            g.plot(ax=ax, **style)
        handles.append(Line2D([0], [0], color=style.get("color", "k"), lw=style.get("lw", 1),
                              ls=style.get("ls", "-"), label=label))
    if places is not None and len(places):
        for _, r in places.iterrows():
            x, y = r.geometry.x, r.geometry.y
            if bounds[0] < x < bounds[2] and bounds[1] < y < bounds[3]:
                ax.plot(x, y, "o", ms=3, color="black", zorder=5)
                ax.annotate(str(r["name"]), (x, y), xytext=(3, 3), textcoords="offset points", fontsize=8,
                            fontweight="bold", zorder=6,
                            bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.7))
    xmin, ymin, xmax, ymax = bounds
    ax.set_xlim(xmin, xmax); ax.set_ylim(ymin, ymax)
    # Barra de escala
    x0, y0 = xmin + 0.04 * (xmax - xmin), ymin + 0.05 * (ymax - ymin)
    ax.plot([x0, x0 + scale_km * 1000], [y0, y0], color="black", lw=3, solid_capstyle="butt", zorder=7)
    ax.text(x0 + scale_km * 500, y0 + 0.015 * (ymax - ymin), f"{scale_km} km", ha="center", fontsize=8, zorder=7)
    # Norte
    xn, yn = xmax - 0.04 * (xmax - xmin), ymax - 0.16 * (ymax - ymin)
    ax.annotate("N", xy=(xn, yn + 0.1 * (ymax - ymin)), xytext=(xn, yn), ha="center", fontsize=10,
                fontweight="bold", arrowprops=dict(arrowstyle="-|>", color="black", lw=1.5), zorder=7)
    ax.set_xticks([]); ax.set_yticks([]); ax.set_xlabel(""); ax.set_ylabel("")
    if legend and handles:
        ax.legend(handles=handles, loc=legend_loc, fontsize=7, framealpha=0.85)
    return handles
