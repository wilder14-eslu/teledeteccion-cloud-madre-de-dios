"""
Póster interactivo: minería aurífera y deforestación en Madre de Dios (Estadística Espacial, UNMSM).

Se publica en Streamlit Community Cloud directamente desde GitHub (archivo principal: poster/streamlit_app.py).
No necesita Databricks: lee el paquete liviano que el notebook 07 exporta desde las tablas Gold
(poster/data/) y las figuras generadas en la nube (docs/figuras, docs/capturas).

Prueba local:
    pip install -r poster/requirements.txt
    streamlit run poster/streamlit_app.py
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import contenido as T  # noqa: E402

REPO = AQUI.parent
DATA = Path(os.getenv("POSTER_DATA", AQUI / "data"))
FIG = REPO / "docs" / "figuras"
CAP = REPO / "docs" / "capturas"
ASSETS = AQUI / "assets"
HA_PX = 0.04                                  # hectáreas por píxel de 20 m
ANIOS = [2018, 2020, 2022, 2024, 2025]
AOI = (-70.45, -13.15, -69.85, -12.80)

st.set_page_config(page_title="Póster | Minería y deforestación en Madre de Dios", page_icon="🛰️",
                   layout="wide", initial_sidebar_state="collapsed")

VERDE, VERDE_CLARO, OCRE, GRIS = "#1b4332", "#2d6a4f", "#b5651d", "#495057"
st.markdown(f"""
<style>
  .block-container {{padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1600px;}}
  .cabecera {{background: linear-gradient(120deg, {VERDE} 0%, {VERDE_CLARO} 60%, {OCRE} 140%);
              color: white; border-radius: 14px; padding: 22px 30px; margin-bottom: 14px;}}
  .cabecera h1 {{color: white; font-size: 2.05rem; line-height: 1.2; margin: 6px 0 6px 0;}}
  .cabecera .inst {{font-size: 0.95rem; opacity: 0.9; letter-spacing: 0.3px;}}
  .cabecera .sub {{font-size: 1.05rem; opacity: 0.95;}}
  .cabecera .autores {{font-size: 0.98rem; margin-top: 10px;}}
  .seccion {{border-left: 6px solid {OCRE}; padding: 2px 0 2px 12px; margin: 18px 0 8px 0;
             font-size: 1.45rem; font-weight: 700; color: {VERDE};}}
  .kpi {{background: #f1f5f2; border-radius: 12px; padding: 12px 14px; text-align: center; height: 100%;
         border: 1px solid #dbe5de;}}
  .kpi .v {{font-size: 1.75rem; font-weight: 800; color: {VERDE};}}
  .kpi .e {{font-size: 0.85rem; color: {GRIS};}}
  .caja {{background: #fbfbf8; border: 1px solid #e6e2d8; border-radius: 12px; padding: 14px 18px;}}
  .pie {{font-size: 0.85rem; color: {GRIS};}}
  div[data-testid="stImageCaption"] {{font-size: 0.85rem;}}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Cargando hexágonos...")
def cargar_hex():
    f = DATA / "h3_poster.parquet"
    return pd.read_parquet(f) if f.exists() else None


@st.cache_data(show_spinner=False)
def cargar_resumen():
    f = DATA / "resumen.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _lineas(geom):
    """Convierte una geometría GeoJSON en listas de coordenadas para PathLayer."""
    t, c = geom["type"], geom["coordinates"]
    if t == "LineString":
        return [c]
    if t == "MultiLineString":
        return list(c)
    if t == "Polygon":
        return [c[0]]
    if t == "MultiPolygon":
        return [p[0] for p in c]
    if t == "GeometryCollection":
        return [l for g in geom["geometries"] for l in _lineas(g)]
    return []


@st.cache_data(show_spinner=False)
def cargar_capas():
    capas = {}
    for f in sorted((DATA / "capas").glob("*.geojson")):
        gj = json.loads(f.read_text(encoding="utf-8"))
        feats = [x for x in gj.get("features", []) if x.get("geometry")]
        if f.stem == "poblados":
            capas["poblados"] = pd.DataFrame([{"name": x["properties"].get("name", ""),
                                               "lon": x["geometry"]["coordinates"][0],
                                               "lat": x["geometry"]["coordinates"][1]} for x in feats
                                              if x["geometry"]["type"] == "Point"])
            continue
        paths = [{"path": [p[:2] for p in l], "nombre": str(x["properties"].get("anp_nomb") or
                                                          x["properties"].get("departamento") or
                                                          x["properties"].get("name") or "")}
                 for x in feats for l in _lineas(x["geometry"])]
        capas[f.stem] = pd.DataFrame(paths)
        if f.stem == "departamentos":
            etiquetas = []
            for x in feats:
                pts = np.array([p[:2] for l in _lineas(x["geometry"]) for p in l])
                pts = pts[(pts[:, 0] > AOI[0]) & (pts[:, 0] < AOI[2]) & (pts[:, 1] > AOI[1]) & (pts[:, 1] < AOI[3])]
                if len(pts) > 20:
                    etiquetas.append({"name": str(x["properties"].get("departamento", "")).upper()})
            capas["departamentos_nombres"] = [e["name"] for e in etiquetas]
    return capas


def colorear(serie, cmap, vmin, vmax, alpha=205):
    import matplotlib
    cm = matplotlib.colormaps[cmap]
    v = serie.astype(float).to_numpy()
    x = np.clip((v - vmin) / (vmax - vmin), 0, 1)
    rgba = (cm(np.nan_to_num(x))[:, :3] * 255).astype(int)
    return [[int(x) for x in c] + [alpha] if not np.isnan(val) else [200, 200, 200, 50] for c, val in zip(rgba, v)]


def figura(nombre, pie, carpeta=FIG):
    f = carpeta / nombre
    if f.exists():
        st.image(str(f), caption=pie, width="stretch")
    else:
        st.caption(f"(figura {nombre} no disponible)")


def ha(x):
    return f"{x:,.0f} ha".replace(",", " ")


def seccion(texto):
    st.markdown(f"<div class='seccion'>{texto}</div>", unsafe_allow_html=True)


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
perdida_of = resumen.get("perdida_oficial_ha", 24516)
perdida_mod = resumen.get("perdida_modelo_ha", 24844)
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
LISA_COLORES = {"Pérdida-Pérdida (frente activo)": [178, 24, 43, 225], "Aumento-Aumento (mayor verdor)": [33, 102, 172, 200],
                "Pérdida aislada": [244, 165, 130, 210], "Aumento aislado": [146, 197, 222, 210],
                "No significativo": [235, 235, 235, 70]}

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
    if "departamentos" in capas:
        capas_deck.append(pdk.Layer("PathLayer", capas["departamentos"], get_path="path", get_color=[50, 50, 50],
                                    width_min_pixels=3))
    if ver_ctx:
        for n, c, w in [("rios", [31, 120, 180], 1.5), ("vias", [20, 20, 20], 2.5),
                        ("areas_protegidas_sernanp", [128, 0, 128], 2), ("zonas_amortiguamiento", [255, 140, 0], 2)]:
            if n in capas and len(capas[n]):
                capas_deck.append(pdk.Layer("PathLayer", capas[n], get_path="path", get_color=c, width_min_pixels=w))
    if "poblados" in capas and len(capas["poblados"]):
        capas_deck.append(pdk.Layer("TextLayer", capas["poblados"], get_position=["lon", "lat"], get_text="name",
                                    get_size=13, get_color=[0, 0, 0], get_alignment_baseline="'bottom'"))
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
