"""
Configuración central del proyecto.

Un solo lugar para el área de estudio, la grilla raster, los años y los
nombres de catálogo/esquema/volumen en Databricks. Lo usan tanto los
scripts locales (descarga) como los notebooks.
"""
from dataclasses import dataclass, field
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Área de estudio: corredor minero La Pampa - Huepetuhe - Mazuko (Madre de Dios)
# Atraviesa la Carretera Interoceánica y bordea la zona de amortiguamiento de
# la Reserva Nacional Tambopata.
# ---------------------------------------------------------------------------
AOI_NAME = "corredor_minero_mdd"
AOI_BBOX_WGS84: Tuple[float, float, float, float] = (-70.45, -13.15, -69.85, -12.80)  # (lon_min, lat_min, lon_max, lat_max)

# Grilla de trabajo en UTM 19S (EPSG:32719), alineada a múltiplos de 20 m
CRS_UTM = "EPSG:32719"
GRID_BOUNDS_UTM: Tuple[float, float, float, float] = (342_800.0, 8_545_800.0, 407_800.0, 8_584_800.0)  # xmin, ymin, xmax, ymax
RES_M = 20                    # resolución de trabajo (bandas 10 m se remuestrean a 20 m)
TILE_PX = 512                 # tamaño de tesela para el procesamiento distribuido

# ---------------------------------------------------------------------------
# Ventana temporal: temporada seca amazónica (menor nubosidad)
# ---------------------------------------------------------------------------
YEARS: List[int] = [2018, 2020, 2022, 2024, 2025]
SEASON = ("07-01", "09-30")
MAX_CLOUD = 60                # % nubosidad máxima por escena (luego se enmascara píxel a píxel con SCL)
MAX_ITEMS_PER_YEAR = 12       # escenas menos nubosas por año

# ---------------------------------------------------------------------------
# Fuentes
# ---------------------------------------------------------------------------
STAC_URL = "https://earth-search.aws.element84.com/v1"
STAC_COLLECTIONS = ["sentinel-2-c1-l2a", "sentinel-2-l2a"]   # Collection 1 primero; fallback a la colección original
S2_ASSETS = ["blue", "green", "red", "nir", "swir16", "swir22", "scl"]
S2_BANDS = ["B02", "B03", "B04", "B08", "B11", "B12"]       # nombres ESA, mismo orden que S2_ASSETS[:-1]

HANSEN_VERSION = "GFC-2024-v1.12"
HANSEN_BASE = f"https://storage.googleapis.com/earthenginepartners-hansen/{HANSEN_VERSION}"
HANSEN_TILES = ["10S_080W", "10S_070W"]                      # el AOI cruza el meridiano 70°W
HANSEN_LAYERS = ["lossyear", "treecover2000"]

GADM_URL = "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_PER_3.json.zip"

# Geobosques (MINAM): códigos del raster de pérdida. 1-24 = año 2001-2024, 25 = antrópica 2025, 26 = natural 2025
GEOBOSQUES_ANTROPICA_2025 = 25
GEOBOSQUES_NATURAL_2025 = 26


def geobosques_codes(y0: int, y1: int) -> List[int]:
    """Códigos de pérdida antrópica de Geobosques entre (y0, y1]."""
    codes = [y - 2000 for y in range(y0 + 1, min(y1, 2024) + 1)]
    if y1 >= 2025:
        codes.append(GEOBOSQUES_ANTROPICA_2025)
    return codes

# ---------------------------------------------------------------------------
# Databricks (Unity Catalog). En Free Edition el catálogo por defecto es "workspace".
# ---------------------------------------------------------------------------
CATALOG = "workspace"
SCHEMA = "madre_dios_rs"
VOLUME = "raw"
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
# Zonas del Volume: landing (archivos tal como los publica cada institución) -> bronze (alineado a la grilla)

# Clases SCL de Sentinel-2 consideradas válidas (4 vegetación, 5 suelo desnudo, 6 agua, 7 sin clasificar)
SCL_VALID = (4, 5, 6, 7)
NODATA_INT16 = -9999

H3_RES_FINE = 9     # ~0.105 km2 por hexágono: análisis de dependencia, LISA, kriging
H3_RES_COARSE = 8   # ~0.737 km2 por hexágono: regresión espacial


@dataclass
class Grid:
    """Grilla raster fija del AOI."""
    bounds: Tuple[float, float, float, float] = GRID_BOUNDS_UTM
    res: float = RES_M
    tile: int = TILE_PX
    crs: str = CRS_UTM

    @property
    def width(self) -> int:
        return int(round((self.bounds[2] - self.bounds[0]) / self.res))

    @property
    def height(self) -> int:
        return int(round((self.bounds[3] - self.bounds[1]) / self.res))

    @property
    def n_tiles(self) -> Tuple[int, int]:
        return (-(-self.height // self.tile), -(-self.width // self.tile))   # (filas, columnas)

    def transform(self):
        from rasterio.transform import from_origin
        return from_origin(self.bounds[0], self.bounds[3], self.res, self.res)

    def tile_windows(self):
        """Itera (tr, tc, Window) cubriendo toda la grilla."""
        from rasterio.windows import Window
        n_r, n_c = self.n_tiles
        for tr in range(n_r):
            for tc in range(n_c):
                r0, c0 = tr * self.tile, tc * self.tile
                h = min(self.tile, self.height - r0)
                w = min(self.tile, self.width - c0)
                yield tr, tc, Window(c0, r0, w, h)
