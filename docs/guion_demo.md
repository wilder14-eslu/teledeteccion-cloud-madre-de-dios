# Guion de la demostración en vivo (15 min)

## Preparación (el día anterior)

1. Ejecutar los notebooks 00 a 06 completos en Databricks para que todas las tablas Delta existan.
2. Dejar abiertas las pestañas: Catalog Explorer (esquema `madre_dios_rs`), notebook 01, notebook 03, notebook 06 y el experimento MLflow.
3. Copia de respaldo: exportar `figures/` del Volume y tener el dataset `gold/h3_features.csv` en local por si falla la conexión.

## Propuestas de demostración

### A. "Del archivo al mapa en 3 minutos" (recomendada para abrir)
- Mostrar en Catalog Explorer el Volume con cientos de GeoTIFF y la tabla `bronze_s2_files`.
- Ejecutar en vivo la celda de `binaryFile` del notebook 00: Spark lista y cuenta los archivos sin abrirlos.
- Mostrar la vista rápida en color verdadero junto a la capa SCL (nubes).
- **Mensaje:** el dato satelital crudo vive en la nube y se consulta como una tabla.

### B. "Spark vs la laptop" (el momento Big Data)
- En el notebook 01, ejecutar `applyInPandas` sobre un solo año con `.filter("year = 2024")`.
- Abrir la Spark UI: ver las tareas en paralelo, una por tesela.
- Comparar con el cálculo: 6.3 M píxeles × 7 bandas × N escenas por año; en una laptop no entra en memoria todo junto.
- **Mensaje:** dividir por teselas y distribuir es lo que hace posible la teledetección a gran escala.

### C. "SQL geoespacial interactivo" (el público participa)
- En una celda SQL, consultar `gold_h3_anual` con `h3_longlatash3string` y pedir al público un distrito o una distancia al río.
- Ejemplo: hexágonos con más del 50 % perturbado a menos de 1 km de un río, por año.
- Visualizar el resultado con el mapa nativo de Databricks (`display` → visualización de mapa).
- **Mensaje:** el analista no necesita saber de GIS para hacer preguntas espaciales sobre millones de píxeles.

### D. "La estadística espacial confirma lo que vemos" (conecta con la teoría)
- Notebook 03: I de Moran y mapa LISA en vivo.
- Mostrar que el Gi* calculado en Spark SQL coincide con esda (correlación ≈ 1).
- **Mensaje:** los mismos estadísticos clásicos, implementados para escalar.

### E. "Rellenar lo que las nubes ocultan" (geoestadística aplicada)
- Notebook 04: variograma, tabla kriging vs IDW y mapa de varianza de kriging.

### F. "El modelo engaña si no respeta el espacio" (cierre con impacto)
- Notebook 06: comparar AUC aleatorio vs AUC por bloques espaciales y abrir la corrida en MLflow.
- **Mensaje:** en datos espaciales, la validación también debe ser espacial.

## Secuencia sugerida

| Minuto | Bloque | Responsable |
|---|---|---|
| 0-3 | A. Del archivo al mapa | Integrante 1 |
| 3-7 | B. Spark en paralelo | Integrante 2 |
| 7-9 | C. SQL geoespacial | Integrante 3 |
| 9-12 | D + E. Dependencia y kriging | Integrante 4 |
| 12-15 | F. ML con validación espacial y conclusiones | Integrante 5 |

## Plan B si falla el cómputo

Las figuras quedan guardadas en `/Volumes/workspace/madre_dios_rs/raw/figures/`, y el dataset Gold
se puede abrir en local con pandas o geopandas.
