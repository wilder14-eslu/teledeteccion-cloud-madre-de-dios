"""
Entrada/salida raster sobre la grilla fija del área de estudio.

- warp_to_grid: lee cualquier raster (local, /Volumes, http o /vsizip) ya
  reproyectado y recortado a la grilla UTM 19S de 20 m.
- write_tiles: parte un stack en teselas GeoTIFF comprimidas. Escribe primero
  en disco local y luego copia, porque los Volumes de Unity Catalog no admiten
  la escritura aleatoria que necesita GDAL.
"""
import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.vrt import WarpedVRT

from .config import Grid

GRID = Grid()

GDAL_ENV = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    AWS_NO_SIGN_REQUEST="YES",
    GDAL_HTTP_MAX_RETRY="5",
    GDAL_HTTP_RETRY_DELAY="2",
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF,.tiff",
    VSI_CACHE="TRUE",
)


def warp_to_grid(href: str, resampling, nodata=None, band: int = 1) -> np.ndarray:
    """Lee una banda reproyectada y recortada a la grilla del AOI."""
    with rasterio.open(href) as src:
        opts = dict(crs=GRID.crs, transform=GRID.transform(), width=GRID.width,
                    height=GRID.height, resampling=resampling)
        if nodata is not None:
            opts["nodata"] = nodata
        with WarpedVRT(src, **opts) as vrt:
            return vrt.read(band)


def write_tiles(stack: np.ndarray, out_dir_fn, filename: str, dtype: str, nodata, skip_fn=None) -> int:
    """Parte un stack (bandas, H, W) en teselas GeoTIFF; devuelve el número escrito."""
    n = 0
    tmpdir = Path(tempfile.mkdtemp(prefix="geocloud_"))
    try:
        for tr, tc, win in GRID.tile_windows():
            sub = stack[:, win.row_off:win.row_off + win.height, win.col_off:win.col_off + win.width]
            if skip_fn is not None and skip_fn(sub):
                continue
            profile = dict(driver="GTiff", height=win.height, width=win.width, count=sub.shape[0],
                           dtype=dtype, crs=GRID.crs,
                           transform=rasterio.windows.transform(win, GRID.transform()),
                           compress="deflate", predictor=2, tiled=True, blockxsize=256, blockysize=256,
                           nodata=nodata)
            tmp = tmpdir / f"{tr}_{tc}_{filename}"
            with rasterio.open(tmp, "w", **profile) as dst:
                dst.write(sub.astype(dtype))
            out_dir = Path(out_dir_fn(tr, tc))
            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(tmp, out_dir / filename)
            os.remove(tmp)
            n += 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return n
