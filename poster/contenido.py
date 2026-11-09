"""
Contenido editable del póster (textos, integrantes y resultados de la corrida final en Databricks).
Para cambiar un texto o un nombre, editar solo este archivo.
"""

UNIVERSIDAD = "Universidad Nacional Mayor de San Marcos"
FACULTAD = "Facultad de Ciencias Matemáticas · Escuela Profesional de Estadística"
CURSO = "Estadística Espacial"
DOCENTE = "Misael Erikson Maguiña Palma, Ph. D."
INTEGRANTES = ["Briceño Ypanaque", "Espinoza Luna", "Isase Camara", "Montoya Juro", "Pablo Machaca", "Polastre Mamani"]
TEMA = "Integración de plataformas Cloud Computing para el análisis de Big Data en teledetección a gran escala"

TITULO = ("Minería aurífera y deforestación en el corredor La Pampa, Huepetuhe y Mazuko, 2018-2025: "
          "teledetección a gran escala en la nube")
SUBTITULO = "Sur de Madre de Dios con sectores limítrofes de Cusco y Puno · Sentinel-2, Geobosques (MINAM), SERNANP"
REPO = "https://github.com/wilder14-eslu/teledeteccion-cloud-madre-de-dios"

RESUMEN = """
Se construyó un pipeline de Big Data geoespacial en **Databricks** (Spark, Delta Lake, Unity Catalog, H3 y MLflow)
que integra 60 escenas **Sentinel-2** leídas directamente desde AWS, la pérdida de bosque oficial de **Geobosques**
(MINAM), Hansen GFC (UMD), áreas protegidas de **SERNANP**, límites de GADM y la red vial y fluvial de OpenStreetMap.
Sobre 31.7 millones de píxeles agregados a 21 854 hexágonos se aplicaron autocorrelación espacial (Moran, Geary,
LISA, Getis-Ord Gi*), geoestadística (variograma y kriging), patrones puntuales (KDE, Ripley) y regresión espacial
(SLM, SEM). La pérdida de vegetación está fuertemente agrupada (I de Moran = 0.75), su concentración espacial creció
de 2018 a 2025, los nuevos frentes se ubican más cerca de ríos y quebradas, y las ANP reducen la perturbación. Un
Random Forest validado por bloques espaciales (AUC = 0.91) estima la superficie perdida con 1.3 % de error frente a
la cifra oficial. Todo el flujo corre como un Job serverless orquestado como código.
"""

INTRODUCCION = """
La minería aurífera aluvial es la principal causa de deforestación en el sur de Madre de Dios; el sector de
La Pampa, a lo largo de la Carretera Interoceánica y en la zona de amortiguamiento de la Reserva Nacional
Tambopata, es uno de sus frentes más activos (Caballero Espejo et al., 2018).

Monitorearlo exige procesar series de imágenes satelitales de alta resolución bajo nubosidad casi permanente:
un volumen y una complejidad que superan a una computadora personal. **Objetivo:** demostrar cómo una plataforma
cloud integra fuentes satelitales, oficiales e internacionales, escala el procesamiento y permite aplicar la
estadística espacial completa sobre el resultado.
"""

FUENTES = [
    ("Sentinel-2 L2A (ESA)", "Imágenes 10-20 m, 6 bandas + máscara de nubes", "AWS Open Data, lectura cloud-to-cloud"),
    ("Geobosques (MINAM)", "Pérdida 2001-2025, bosque 2025, riesgo de deforestación", "Landing en Unity Catalog"),
    ("Hansen GFC v1.12 (UMD)", "Pérdida 2001-2024, cobertura 2000", "Google Cloud Storage, cloud-to-cloud"),
    ("SERNANP", "ANP nacionales y zonas de amortiguamiento", "Landing"),
    ("GADM 4.1", "Distritos y límite departamental", "Landing"),
    ("OpenStreetMap", "Vía Interoceánica, ríos, quebradas, poblados", "Landing"),
]

METODO = """
**Arquitectura medallion en Databricks serverless**

1. **Landing → Bronze:** archivos oficiales en un Volume de Unity Catalog; Sentinel-2 y Hansen se leen como
   Cloud Optimized GeoTIFF, transfiriendo solo los bloques que cubren el área. Todo se alinea a una
   grilla UTM 19S de 20 m en 28 teselas.
2. **Silver:** compuesto anual por mediana sin nubes (máscara SCL) e índices NDVI, NBR, NDWI, MNDWI y BSI, calculados
   en paralelo con `binaryFile` + `applyInPandas`; control de calidad radiométrico automático.
3. **Gold:** agregación a hexágonos H3 (res. 9, ≈0.1 km²) con funciones nativas de Spark SQL; covariables y máscara
   de bosque del año base.
4. **Análisis:** Moran, Geary, LISA y Gi* (también en Spark SQL), variograma y kriging por oclusión, parches y
   función K de Ripley con CSR condicionado al bosque, MCO / SLM / SEM, Random Forest con validación por bloques y
   calibración a la prevalencia real (MLflow).
5. **Orquestación y servicio:** Job serverless definido como código (Databricks Asset Bundle) y aplicación web.
"""

# Resultados de la corrida final en Databricks (09/11/2026)
RESULTADOS = {
    "Escenas Sentinel-2 procesadas": "60 (12 por año, temporada seca)",
    "Píxeles en Silver": "31.7 millones",
    "Hexágonos H3 analizados": "21 854 (16 601 de bosque en 2018)",
    "I de Moran del cambio de NDVI": "0.745 (p = 0.001)",
    "I de Moran de la pérdida oficial": "0.668 (p = 0.001)",
    "I de Moran del NDVI por año": "0.32 (2018) → 0.50 → 0.64 → 0.74 → 0.74 (2025)",
    "Frentes activos (LISA Pérdida-Pérdida)": "973 hexágonos",
    "Puntos calientes Gi* (99 % y 95 %)": "859 y 150 hexágonos",
    "Gi* en Spark SQL vs esda": "correlación 1.000 (dif. máx. 7e-14)",
    "Variograma (esférico)": "rango 14.1 km, pepita/meseta 0.28",
    "Kriging por oclusión (15 % oculto)": "RMSE 0.188 vs IDW 0.197; cobertura IC95 90 %",
    "Parches nuevos de perturbación (≥ 1 ha)": "598 parches, 5 291 ha; mayor 925 ha",
    "Clark-Evans": "R = 0.733 (agrupamiento)",
    "Distancia mediana a ríos y quebradas": "1.26 km parches vs 2.02 km bosque",
    "Mejor modelo de regresión espacial": "SEM (AIC −5 551); λ = 0.78",
    "Efecto ANP (SEM)": "−0.043 (p = 0.024)",
    "Efecto distancia a cauces (SEM)": "−0.022 (p = 0.017)",
    "Random Forest: AUC-ROC bloques / aleatorio": "0.912 / 0.915",
    "Random Forest: AUC-PR (azar = 0.14)": "0.75",
    "Random Forest: F1 / exactitud": "0.716 / 0.926",
    "Pérdida 2019-2025: oficial vs modelo": "24 516 ha vs 24 844 ha (+1.3 %)",
    "Job completo (7 tareas, 4 en paralelo)": "17 min 15 s",
}

DISCUSION = """
- **La pérdida no es aleatoria:** la autocorrelación es fuerte y su concentración espacial aumentó en el periodo,
  coherente con la expansión de frentes desde núcleos ya intervenidos (rezago espacial λ ≈ ρ ≈ 0.78).
- **Minería aluvial:** al usar la red de drenaje completa (ríos y quebradas), los nuevos frentes aparecen
  significativamente más cerca de los cauces que el bosque disponible; la cercanía a la vía pesa menos.
- **Áreas protegidas:** dentro de las ANP la perturbación es menor; la presión se concentra en la zona de
  amortiguamiento.
- **Fuentes complementarias:** Sentinel-2 capta la huella minera (suelo desnudo y pozas); Geobosques registra además
  la conversión agrícola. Hansen y Geobosques coinciden en el patrón (I de Moran 0.63 y 0.67).
- **Validación espacial:** con bloques espaciales el AUC baja muy poco; la calibración a la prevalencia real permite
  estimar superficies con error de 1.3 %.
"""

LIMITACIONES = """
- El kriging no recupera bordes abruptos (pozas) bajo nubes grandes: la solución operativa es combinar con radar
  Sentinel-1, que ve a través de las nubes.
- 2022 proviene de la colección antigua de Earth Search (corrección de offset verificada) y 2024 presenta un borde de
  pasada entre órbitas; la comparación principal es 2018 vs 2025.
- Los índices espectrales no distinguen minería de otros suelos desnudos sin apoyo de la fuente oficial.
"""

CONCLUSIONES = """
1. Una plataforma cloud permitió integrar seis fuentes heterogéneas y procesar 31.7 millones de píxeles-año de
   Sentinel-2 sin mover las imágenes a una computadora local; el mismo código escala de 2 500 km² a toda la Amazonía.
2. La deforestación del corredor forma conglomerados significativos y crecientes, ligados a la red de drenaje y
   atenuados por las áreas protegidas.
3. La estadística espacial clásica puede reexpresarse en SQL distribuido (Gi* en Spark) con resultados idénticos.
4. El pipeline completo es reproducible, versionado (Git + Delta Lake) y orquestado como código.
"""

REFERENCIAS = [
    "Anselin, L. (1995). Local indicators of spatial association: LISA. *Geographical Analysis, 27*(2), 93-115.",
    "Caballero Espejo, J., Messinger, M., Román-Dañobeytia, F., Ascorra, C., Fernandez, L. E., & Silman, M. (2018). "
    "Deforestation and forest degradation due to gold mining in the Peruvian Amazon: A 34-year perspective. "
    "*Remote Sensing, 10*(12), 1903.",
    "Drusch, M., et al. (2012). Sentinel-2: ESA's optical high-resolution mission for GMES operational services. "
    "*Remote Sensing of Environment, 120*, 25-36.",
    "Getis, A., & Ord, J. K. (1992). The analysis of spatial association by use of distance statistics. "
    "*Geographical Analysis, 24*(3), 189-206.",
    "Hansen, M. C., et al. (2013). High-resolution global maps of 21st-century forest cover change. "
    "*Science, 342*(6160), 850-853.",
    "Matheron, G. (1963). Principles of geostatistics. *Economic Geology, 58*(8), 1246-1266.",
    "Ministerio del Ambiente. (2025). *Cobertura y pérdida de bosque húmedo amazónico 2001-2025* [Conjunto de datos]. "
    "Geobosques. https://geobosques.minam.gob.pe",
    "Ripley, B. D. (1977). Modelling spatial patterns. *Journal of the Royal Statistical Society: Series B, 39*(2), 172-192.",
    "Servicio Nacional de Áreas Naturales Protegidas por el Estado. (2025). *ANP de administración nacional y zonas de "
    "amortiguamiento* [Conjunto de datos]. https://geo.sernanp.gob.pe",
    "Zaharia, M., et al. (2016). Apache Spark: A unified engine for big data processing. "
    "*Communications of the ACM, 59*(11), 56-65.",
]
