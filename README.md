# Teledetección a gran escala en la nube: minería aurífera y deforestación en Madre de Dios

Pipeline Big Data en **Databricks** (Spark + Delta Lake + Unity Catalog + H3) que procesa imágenes
**Sentinel-2** para cuantificar la pérdida de bosque asociada a la minería aluvial en el corredor
**La Pampa, Huepetuhe y Mazuko** (Madre de Dios, Perú), y la analiza con estadística espacial,
geoestadística y Machine Learning.

![arquitectura](docs/arquitectura.png)

## Pregunta

¿Dónde y con qué patrón espacial avanzó la pérdida de vegetación entre 2018 y 2024 en el
principal frente de minería ilegal de la Amazonía peruana, y qué factores geográficos la explican?

## Área y datos

| Elemento | Detalle |
|---|---|
| Área de estudio | 65 × 39 km (≈ 2 500 km²), UTM 19S, entre −70.45° y −69.85° de longitud y −13.15° y −12.80° de latitud |
| Grilla | 3 250 × 1 950 píxeles de 20 m (6.3 M píxeles por banda), 28 teselas de 512 px |
| Periodo | Temporada seca (julio-setiembre) de 2018, 2020, 2022 y 2024 |

| Fuente | Uso | Acceso |
|---|---|---|
| Sentinel-2 L2A (ESA Copernicus), vía Earth Search / AWS Open Data | Bandas B2, B3, B4, B8, B11, B12 y máscara SCL | STAC público, sin credenciales |
| Hansen Global Forest Change v1.12 (UMD) | Pérdida anual de bosque 2001-2024 y cobertura 2000: validación y etiquetas | Google Cloud Storage público |
| GADM 4.1 | Distritos de Madre de Dios | Descarga directa |
| OpenStreetMap | Carretera Interoceánica, ríos, áreas protegidas | Overpass API |

## Arquitectura (medallion)

```
Earth Search STAC ──► scripts/download_data.py ──► data/bronze (GeoTIFF por tesela)
                                                       │  databricks fs cp
                                                       ▼
                     Unity Catalog Volume  /Volumes/workspace/madre_dios_rs/raw
                                                       │
  BRONZE  bronze_s2_files, bronze_s2_items, bronze_vec_*        (inventario, metadatos)
     │    binaryFile + groupBy(year, tile).applyInPandas
  SILVER  silver_s2_pixeles (≈25 M filas), silver_hansen_pixeles (compuestos e índices por píxel)
     │    h3_longlatash3string + agregaciones SQL
  GOLD    gold_h3_anual, gold_h3_features, gold_h3_ndvi_kriging, gold_pred_perdida_pixel
```

## Notebooks

| # | Notebook | Contenido |
|---|---|---|
| 00 | `00_config_y_bronze` | Unity Catalog, inventario distribuido de archivos, tablas Bronze, control de calidad visual |
| 01 | `01_silver_compuestos_spark` | Compuesto por mediana sin nubes e índices espectrales (NDVI, NBR, NDWI, MNDWI, BSI) distribuidos por teselas |
| 02 | `02_gold_h3_y_aede` | Agregación a hexágonos H3, covariables geográficas, exportación del dataset limpio, AEDE |
| 03 | `03_dependencia_espacial` | Matriz W sobre H3, I de Moran, C de Geary, LISA, Getis-Ord Gi* (esda y Spark SQL escalable) |
| 04 | `04_variograma_y_kriging` | Variograma empírico, modelos teóricos, anisotropía, kriging ordinario vs IDW, relleno de vacíos por nubes |
| 05 | `05_patrones_puntuales` | KDE, funciones G y L de Ripley con envolventes, Clark-Evans, dependencia de la distancia al río |
| 06 | `06_regresion_espacial_y_ml` | MCO, SLM y SEM con tests LM; Random Forest con validación por bloques espaciales y puntuación distribuida |

## Cómo reproducirlo

### 1. Entorno local (descarga de datos)

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Verificar disponibilidad y descargar

```powershell
python scripts\check_availability.py      # inventario de escenas por año y acceso a cada fuente
python scripts\download_data.py           # capa Bronze completa (≈1-2 GB)
# prueba rápida: python scripts\download_data.py --years 2018 2024 --max-items 6
```

### 3. Subir a Databricks con la CLI

```powershell
winget install Databricks.DatabricksCLI
.\scripts\databricks_setup.ps1 -WorkspaceUrl "https://<workspace>.cloud.databricks.com" `
                               -RepoUrl "https://github.com/<usuario>/teledeteccion-cloud-madre-de-dios"
```

El script autentica con OAuth, crea el esquema y el Volume, copia `data/bronze` al Volume y crea un
*Git folder* con este repositorio. Luego se ejecutan los notebooks en orden sobre cómputo serverless.

## Estructura

```
├── notebooks/            00 a 06 (Databricks, PySpark)
├── src/geocloud/         config, procesamiento raster, utilidades espaciales, compatibilidad Databricks/local
├── scripts/              verificación, descarga y despliegue con Databricks CLI
├── docs/                 guion de la demostración y figuras
└── data/                 (ignorado por git) bronze/ descargado localmente
```

## Notas técnicas

- **Nubes:** se usa la Scene Classification Layer (SCL) para enmascarar píxel a píxel y un compuesto por
  mediana por temporada; los hexágonos sin observación válida se rellenan por kriging.
- **Reflectancia:** se aplica escala y offset de cada escena (cambio de *processing baseline* 04.00 en 2022)
  para que los índices sean comparables entre años.
- **Validación espacial:** los modelos de ML se evalúan con validación cruzada por bloques H3 de resolución 6
  para no sobreestimar el desempeño por autocorrelación espacial.
- **Databricks Free Edition:** solo cómputo serverless y salida a internet restringida; por eso la descarga se
  hace fuera y los datos entran por el Volume.

## Referencias

- Anselin, L. (1995). Local indicators of spatial association: LISA. *Geographical Analysis, 27*(2), 93-115.
- Caballero Espejo, J., Messinger, M., Román-Dañobeytia, F., Ascorra, C., Fernandez, L. E., & Silman, M. (2018). Deforestation and forest degradation due to gold mining in the Peruvian Amazon: A 34-year perspective. *Remote Sensing, 10*(12), 1903.
- Drusch, M., et al. (2012). Sentinel-2: ESA's optical high-resolution mission for GMES operational services. *Remote Sensing of Environment, 120*, 25-36.
- Getis, A., & Ord, J. K. (1992). The analysis of spatial association by use of distance statistics. *Geographical Analysis, 24*(3), 189-206.
- Gorelick, N., et al. (2017). Google Earth Engine: Planetary-scale geospatial analysis for everyone. *Remote Sensing of Environment, 202*, 18-27.
- Hansen, M. C., et al. (2013). High-resolution global maps of 21st-century forest cover change. *Science, 342*(6160), 850-853.
- Matheron, G. (1963). Principles of geostatistics. *Economic Geology, 58*(8), 1246-1266.
- Ripley, B. D. (1977). Modelling spatial patterns. *Journal of the Royal Statistical Society: Series B, 39*(2), 172-192.
- Zaharia, M., et al. (2016). Apache Spark: A unified engine for big data processing. *Communications of the ACM, 59*(11), 56-65.
