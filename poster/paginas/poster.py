"""Página 1: póster científico."""
from comun import (T, REPO, ASSETS, CAP, ANIOS, AOI, HA_PX, DATA, LISA_COLORES, cargar_hex, cargar_resumen,
                   cargar_capas, capas_contexto, colorear, figura, ha, seccion)
import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

hexs = cargar_hex()
resumen = cargar_resumen()
capas = cargar_capas() if (DATA / "capas").exists() else {}

# ---------------------------------------------------------------------------
# Cabecera
# ---------------------------------------------------------------------------
escudo = ASSETS / "escudo_unmsm.png"
c_logo, c_tit, c_qr = st.columns([1, 8, 1.2], vertical_alignment="center")
with c_logo:
    if escudo.exists():
        st.image(str(escudo), width=110)
with c_tit:
    st.markdown(f"""
<div class='cabecera'>
  <div class='inst'>{T.UNIVERSIDAD} · {T.FACULTAD}</div>
  <div class='inst'>Curso: {T.CURSO} · Docente: {T.DOCENTE} · Tema: {T.TEMA}</div>
  <h1>{T.TITULO}</h1>
  <div class='sub'>{T.SUBTITULO}</div>
  <div class='autores'><b>Integrantes:</b> {' · '.join(T.INTEGRANTES)}</div>
</div>""", unsafe_allow_html=True)
with c_qr:
    if (ASSETS / "qr_repo.png").exists():
        st.image(str(ASSETS / "qr_repo.png"), caption="Código y notebooks", width="stretch")

# Cifras clave
# Superficie evaluada en el notebook 06 sobre píxeles no usados en el entrenamiento
perdida_of, perdida_mod = 24516, 24844
kpis = [
    ("31.7 M", "píxeles de 20 m procesados en Spark"),
    (f"{resumen.get('hexagonos', 21854):,}".replace(",", " "), "hexágonos H3 (≈0.1 km²)"),
    ("0.75", "I de Moran del cambio de NDVI"),
    (f"{resumen.get('frentes_lisa', 973):,}".replace(",", " "), "hexágonos en frentes activos (LISA)"),
    (ha(perdida_of), "pérdida oficial 2019-2025"),
    (f"{(perdida_mod / perdida_of - 1) * 100:+.1f} %", "error del modelo en superficie"),
    ("17 min", "pipeline completo en la nube"),
]
for col, (v, e) in zip(st.columns(len(kpis)), kpis):
    col.markdown(f"<div class='kpi'><div class='v'>{v}</div><div class='e'>{e}</div></div>", unsafe_allow_html=True)

l1, l2, _ = st.columns([1, 1, 3])
l1.page_link("paginas/visor.py", label="Abrir el visor completo de hexágonos", icon="🗺️")
l2.page_link("paginas/modelo.py", label="Probar el modelo entrenado en vivo", icon="🤖")

# ---------------------------------------------------------------------------
# Resumen, introducción, datos y método
# ---------------------------------------------------------------------------
c1, c2, c3 = st.columns([1.05, 1, 1.15], gap="large")
with c1:
    seccion("Resumen")
    st.markdown(T.RESUMEN)
    seccion("Introducción")
    st.markdown(T.INTRODUCCION)
with c2:
    seccion("Datos")
    st.markdown("| Fuente | Contenido | Integración |\n|---|---|---|\n" +
                "\n".join(f"| **{a}** | {b} | {c} |" for a, b, c in T.FUENTES))
    st.markdown("""
**Área de estudio:** ≈2 500 km² entre −70.45 y −69.85 de longitud y −13.15 y −12.80 de latitud: el corredor de la
Interoceánica entre Mazuko y La Pampa y la cuenca de Huepetuhe, con la Reserva Nacional Tambopata y su zona de
amortiguamiento.
**Periodo:** 2018, 2020, 2022, 2024 y 2025 (temporada seca, junio-setiembre).
**Unidad de análisis:** píxel de 20 m (6.3 millones por año) agregado a hexágonos H3 de resolución 9 y 8.
""")
with c3:
    seccion("Método")
    st.markdown(T.METODO)

_, c_arq, _ = st.columns([0.08, 1, 0.08])
with c_arq:
    figura("arquitectura.png", "Arquitectura medallion en Databricks: de las fuentes a la estadística espacial", REPO / "docs")

# ---------------------------------------------------------------------------
# Mapa interactivo
# ---------------------------------------------------------------------------
seccion("Resultados · Mapa interactivo del modelo")
INDICADORES = {
    "Pérdida oficial 2019-2025 (Geobosques)": ("tasa_perdida_oficial", "Reds", 0, 1),
    "Cambio de NDVI 2018-2025": ("d_ndvi", "RdBu", -0.6, 0.6),
    "Clusters LISA": ("lisa", None, None, None),
    "Puntos calientes Gi*": ("gi_z", "coolwarm", -6, 6),
    "Probabilidad de pérdida (Random Forest)": ("prob_modelo", "Reds", 0, 1),
    "Perturbación nueva (Sentinel-2)": ("d_pert", "Oranges", 0, 1),
    "Riesgo de deforestación (MINAM)": ("riesgo_deforestacion", "YlOrRd", 1, 5),
    "NDVI por año": (None, "RdYlGn", 0, 0.9),
}

if hexs is None:
    st.info("Aún no se exportaron los datos del póster (poster/data/h3_poster.parquet). Ejecuta el notebook 07 en "
            "Databricks y luego scripts/exportar_resultados.ps1. Mientras tanto se muestran las figuras.")
    figura("02_mapas.png", "Mapas del área de estudio generados en Databricks")
else:
    cm1, cm2 = st.columns([3.2, 1], gap="medium")
    with cm2:
        nombre = st.radio("Variable", list(INDICADORES), index=0)
        col, cmap, vmin, vmax = INDICADORES[nombre]
        if nombre == "NDVI por año":
            anios = [a for a in ANIOS if f"ndvi_{a}" in hexs]
            col = f"ndvi_{st.select_slider('Año', options=anios, value=anios[-1])}"
        deps = sorted(hexs["departamento"].dropna().unique()) if "departamento" in hexs else []
        sel = st.multiselect("Departamento", deps, default=deps) if deps else []
        solo_bosque = st.toggle("Solo bosque en 2018", value=True)
        ver_ctx = st.toggle("Ríos, vía y áreas protegidas", value=True)
    f = hexs
    if sel and "departamento" in f:
        f = f[f["departamento"].isin(sel)]
    if solo_bosque and "frac_bosque_y0" in f:
        f = f[f["frac_bosque_y0"] >= 0.5]
    if col not in f:
        st.warning(f"La variable {col} no está en los datos exportados.")
    m = f.copy()
    if col == "lisa":
        m["color"] = m["lisa"].map(LISA_COLORES).apply(lambda c: c if isinstance(c, list) else [200, 200, 200, 40])
        m["valor"] = m["lisa"].fillna("s/d")
    elif col in m:
        m["color"] = colorear(m[col], cmap, vmin, vmax)
        m["valor"] = m[col].round(3).astype(str)
    else:
        m["color"], m["valor"] = [[200, 200, 200, 50]] * len(m), "s/d"
    for c in ["departamento", "distrito"]:
        m[c] = m[c].fillna("s/d") if c in m else ""
    capas_deck = [pdk.Layer("H3HexagonLayer", m[["h3", "color", "valor", "departamento", "distrito"]],
                            get_hexagon="h3", get_fill_color="color", stroked=False, pickable=True, opacity=0.85)]
    capas_deck += capas_contexto(capas, ver_ctx)
    vista = pdk.ViewState(latitude=(AOI[1] + AOI[3]) / 2, longitude=(AOI[0] + AOI[2]) / 2, zoom=9.5, min_zoom=7)
    with cm1:
        st.pydeck_chart(pdk.Deck(layers=capas_deck, initial_view_state=vista, map_provider="carto", map_style="light",
                                 tooltip={"text": "{departamento} · {distrito}\n" + nombre + ": {valor}"}),
                        width="stretch", height=560)
    with cm2:
        if col == "lisa":
            st.markdown("<br>".join(f"<span style='color:rgb({c[0]},{c[1]},{c[2]});font-size:1.2rem'>■</span> {k}"
                                    for k, c in LISA_COLORES.items()), unsafe_allow_html=True)
        else:
            st.caption(f"Escala {vmin} a {vmax} ({cmap}). Gris: sin dato.")
        st.caption("Gris oscuro: límite departamental · azul: ríos · negro: Interoceánica · morado: ANP · "
                   "naranja: zona de amortiguamiento.")
        perd = (f["frac_perdida_oficial"] * f["n_px_total"]).sum() * HA_PX
        st.metric("Pérdida oficial en la selección", ha(perd))
        if "prob_modelo" in f and f["prob_modelo"].notna().any():
            mod = (f["prob_modelo"] * f["n_px_modelo"]).sum() * HA_PX
            st.metric("Estimada por el modelo", ha(mod), delta=f"{mod / perd - 1:+.1%}" if perd else None,
                      delta_color="off")

# ---------------------------------------------------------------------------
# Resultados por etapa
# ---------------------------------------------------------------------------
seccion("Resultados · Estadística espacial a escala")
r1, r2 = st.columns([1, 1.6], gap="large")
with r1:
    st.dataframe(pd.DataFrame(T.RESULTADOS.items(), columns=["Indicador", "Resultado"]), hide_index=True,
                 width="stretch", height=35 * (len(T.RESULTADOS) + 1) + 3)
with r2:
    moran = pd.DataFrame({"Año": [str(a) for a in ANIOS], "I de Moran NDVI": [0.3205, 0.4979, 0.6430, 0.7439, 0.7405],
                          "I de Moran perturbación": [0.1788, 0.5625, 0.6842, 0.7521, 0.7628]}).set_index("Año")
    st.markdown("**La concentración espacial creció año a año** (I de Moran global, hexágonos de bosque, p = 0.001)")
    st.line_chart(moran, height=230)
    a1, a2 = st.columns(2)
    with a1:
        st.markdown("**Superficie perdida 2019-2025 (ha)**")
        st.bar_chart(pd.DataFrame({"ha": [24516, 24844, 23275]},
                                  index=["Oficial", "Modelo (Σ prob.)", "Modelo (umbral F1)"]),
                     height=230, horizontal=True)
    with a2:
        st.markdown("**Regresión espacial (n = 2 410, H3 res. 8)**")
        st.dataframe(pd.DataFrame({"Modelo": ["MCO", "SLM (rezago)", "SEM (error)"],
                                   "AIC": [-3616, -5542, -5551], "ρ / λ": ["", "0.777", "0.779"]}),
                     hide_index=True, width="stretch")
        st.caption("I de Moran de residuos MCO = 0.68: el MCO ignora la dependencia espacial.")

t = st.tabs(["🛰️ Datos y Silver", "📊 AEDE", "🧭 Dependencia espacial", "🌐 Variograma y kriging",
             "📍 Patrones puntuales", "🤖 Regresión y ML", "⚙️ Orquestación en la nube"])
with t[0]:
    figura("01_ndvi_anual.png", "Compuestos anuales de NDVI sin nubes (mediana, máscara SCL), calculados con Spark")
    figura("00_control_calidad.png", "Control de calidad: color verdadero, máscara de nubes SCL y pérdida oficial")
with t[1]:
    figura("02_mapas.png", "Variables Gold por hexágono H3")
    a, b = st.columns(2)
    with a:
        figura("02_distribuciones.png", "Distribuciones de las variables")
    with b:
        figura("02_gradientes.png", "Perturbación según distancia a cauces y a la vía")
with t[2]:
    a, b = st.columns(2)
    with a:
        figura("03_lisa.png", "Clusters LISA del cambio de NDVI: frentes activos de pérdida")
    with b:
        figura("03_gi_star.png", "Puntos calientes Getis-Ord Gi* (también calculado en Spark SQL)")
    figura("03_moran_scatter.png", "Diagrama de dispersión de Moran")
with t[3]:
    a, b = st.columns([1, 1])
    with a:
        figura("04_variogramas.png", "Variogramas empíricos y modelos ajustados")
        figura("04_error_distancia.png", "Error de reconstrucción según distancia al dato visible")
    with b:
        figura("04_kriging.png", "Experimento de oclusión: kriging ordinario vs IDW bajo nubes simuladas")
with t[4]:
    a, b = st.columns(2)
    with a:
        figura("05_kde.png", "Densidad kernel de parches nuevos de perturbación")
        figura("05_tamanos.png", "Distribución de tamaños de parche")
    with b:
        figura("05_G_L.png", "Funciones G y L de Ripley con envolventes CSR condicionadas al bosque")
        figura("05_ecdf_covariables.png", "Distancia de los parches a cauces y vía vs bosque disponible")
with t[5]:
    figura("06_prediccion.png", "Pérdida oficial, probabilidad calibrada del Random Forest y error por hexágono")
    a, b = st.columns(2)
    with a:
        figura("06_importancia.png", "Importancia de variables del Random Forest")
    with b:
        st.markdown("""
**Validación honesta**
- Validación cruzada por **bloques espaciales** (H3 res. 6, 84 bloques): AUC 0.912 vs 0.915 aleatoria.
- Probabilidades **calibradas** a la prevalencia real (π = 0.14) y umbral por F1 = 0.331.
- Evaluación sobre **4.6 millones de píxeles** no usados en el entrenamiento: F1 0.716, exactitud 0.926.
- Correlación por hexágono entre pérdida predicha y oficial: **0.917**.
- Modelo registrado en **MLflow** y puntuado en paralelo con `mapInPandas`.
""")
with t[6]:
    a, b = st.columns([1.2, 1])
    with a:
        figura("job_grafo_detalle.png", "Job serverless definido como código (Databricks Asset Bundle)", CAP)
    with b:
        figura("job_timeline_paralelo.png", "Las tareas 03 a 06 corren en paralelo", CAP)
        figura("job_lista.png", "Historial de ejecuciones del Job", CAP)

# ---------------------------------------------------------------------------
# Discusión y conclusiones
# ---------------------------------------------------------------------------
d1, d2, d3 = st.columns(3, gap="large")
with d1:
    seccion("Discusión")
    st.markdown(T.DISCUSION)
with d2:
    seccion("Limitaciones")
    st.markdown(T.LIMITACIONES)
    seccion("Reproducibilidad")
    st.markdown(f"""
Código, notebooks ejecutados y datos limpios: [{T.REPO.replace('https://', '')}]({T.REPO}).
Pipeline: Databricks Free Edition (serverless), Unity Catalog, Delta Lake, H3, MLflow, Asset Bundles.
Este póster se actualiza solo con cada *push* al repositorio.
""")
with d3:
    seccion("Conclusiones")
    st.markdown(T.CONCLUSIONES)

seccion("Referencias")
st.markdown("\n".join(f"- {r}" for r in T.REFERENCIAS))
st.markdown(f"<div class='pie'>{T.UNIVERSIDAD} · {T.CURSO} · 2026</div>", unsafe_allow_html=True)

