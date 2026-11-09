"""Página 3: el Random Forest entrenado en Databricks, puntuando píxeles reales en vivo."""
import json

import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

from comun import DATA, FIG, capas_contexto, cargar_capas, figura, ha, seccion

MOD = DATA / "modelo"


@st.cache_resource(show_spinner="Cargando el modelo entrenado en Databricks...")
def cargar_modelo():
    import joblib
    meta = json.loads((MOD / "modelo_meta.json").read_text(encoding="utf-8"))
    return joblib.load(MOD / "rf_perdida.joblib"), meta


@st.cache_data(show_spinner="Puntuando la zona con el Random Forest...")
def puntuar(_modelo, feats, pi):
    zona = pd.read_parquet(MOD / "zona_demo.parquet")
    raw = _modelo.predict_proba(zona[feats].fillna(0).to_numpy())[:, 1]
    a = raw * pi / 0.5                                     # misma calibración por prevalencia que el notebook 06
    zona["prob"] = a / (a + (1 - raw) * (1 - pi) / 0.5)
    return zona


st.title("🤖 Modelo en vivo: Random Forest de pérdida de bosque")
st.caption("El modelo se entrenó y validó en Databricks (notebook 06, registrado en MLflow) y se exportó con el "
           "notebook 07. Aquí se carga el mismo modelo y se ejecuta en este servidor sobre píxeles reales de 20 m.")

if not (MOD / "rf_perdida.joblib").exists():
    st.info("Aún no se exportó el modelo (poster/data/modelo/). Ejecuta el notebook 07 en Databricks y luego "
            "scripts/exportar_resultados.ps1.")
    figura("06_prediccion.png", "Predicción del modelo calculada en Databricks")
    st.stop()

try:
    modelo, meta = cargar_modelo()
except Exception as e:  # versión de scikit-learn distinta a la de Databricks
    st.error(f"No se pudo cargar el modelo: {e}. Revisa que poster/requirements.txt fije scikit-learn "
             f"y numpy en las versiones de modelo_meta.json.")
    st.stop()

feats, pi = meta["features"], float(meta["prevalencia"])
zona = puntuar(modelo, feats, pi)

c_ctl, c_kpi = st.columns([1, 3], gap="large")
with c_ctl:
    umbral = st.slider("Umbral de decisión", 0.05, 0.95, float(round(meta.get("umbral", 0.33), 2)), 0.01,
                       help="Probabilidad calibrada a partir de la cual un píxel se clasifica como pérdida. "
                            f"El umbral que maximiza F1 en la validación por bloques fue {meta.get('umbral', 0.33):.3f}.")
    vista_mapa = st.radio("Mapa", ["Probabilidad del modelo", "Clasificación vs oficial", "Pérdida oficial"])
    st.caption(f"Modelo: {meta.get('origen', '')} · scikit-learn {meta.get('sklearn', '')} · "
               f"{len(feats)} variables (6 bandas y 5 índices en {meta.get('y0')}, {meta.get('y1')} y su cambio)")

y, p = zona["label"].to_numpy(), zona["prob"].to_numpy()
pred = (p >= umbral).astype(int)
tp, fp = int(((pred == 1) & (y == 1)).sum()), int(((pred == 1) & (y == 0)).sum())
fn, tn = int(((pred == 0) & (y == 1)).sum()), int(((pred == 0) & (y == 0)).sum())
prec = tp / (tp + fp) if tp + fp else np.nan
rec = tp / (tp + fn) if tp + fn else np.nan
f1 = 2 * prec * rec / (prec + rec) if prec + rec else np.nan

with c_kpi:
    k = st.columns(5)
    k[0].metric("Píxeles de bosque en la zona", f"{len(zona):,}".replace(",", " "))
    k[1].metric("Pérdida oficial", ha(y.sum() * 0.04))
    k[2].metric("Esperada por el modelo (Σ prob.)", ha(p.sum() * 0.04),
                delta=f"{p.sum() / max(y.sum(), 1) - 1:+.1%} vs oficial", delta_color="off")
    k[3].metric("Clasificada con el umbral", ha(pred.sum() * 0.04))
    k[4].metric("F1 en la zona", f"{f1:.3f}" if not np.isnan(f1) else "s/d")
    k2 = st.columns(4)
    k2[0].metric("Precisión", f"{prec:.3f}" if not np.isnan(prec) else "s/d")
    k2[1].metric("Sensibilidad", f"{rec:.3f}" if not np.isnan(rec) else "s/d")
    k2[2].metric("AUC por bloques (Databricks)", f"{meta['auc_bloques']:.3f}" if "auc_bloques" in meta else "0.912")
    k2[3].metric("Prevalencia real π", f"{pi:.3f}")

# Mapa de píxeles: se pinta como imagen (una celda por píxel de 20 m) sobre el mapa base
H, W = int(zona["row"].max()) + 1, int(zona["col"].max()) + 1
img = np.zeros((H, W, 4), dtype=np.uint8)
r_, c_ = zona["row"].to_numpy(), zona["col"].to_numpy()
if vista_mapa == "Probabilidad del modelo":
    import matplotlib
    rgba = (matplotlib.colormaps["Reds"](np.clip(p, 0, 1)) * 255).astype(np.uint8)
    rgba[:, 3] = (60 + 195 * np.clip(p, 0, 1)).astype(np.uint8)
    img[r_, c_] = rgba
elif vista_mapa == "Clasificación vs oficial":
    tipos = np.select([(pred == 1) & (y == 1), (pred == 1) & (y == 0), (pred == 0) & (y == 1)], [0, 1, 2], 3)
    paleta = np.array([[178, 24, 43, 240], [255, 165, 0, 240], [33, 102, 172, 240], [200, 225, 200, 90]], np.uint8)
    img[r_, c_] = paleta[tipos]
else:
    img[r_, c_] = np.where((y == 1)[:, None], [[178, 24, 43, 240]], [[200, 225, 200, 90]]).astype(np.uint8)


@st.cache_data(show_spinner=False)
def esquinas(_z):
    """Coordenadas de las esquinas de la ventana a partir de los centros de píxel (ajuste lineal)."""
    A = np.c_[np.ones(len(_z)), _z["row"], _z["col"]]
    clon = np.linalg.lstsq(A, _z["lon"], rcond=None)[0]
    clat = np.linalg.lstsq(A, _z["lat"], rcond=None)[0]
    f = lambda r, c: [float(clon @ [1, r, c]), float(clat @ [1, r, c])]  # noqa: E731
    return [f(H - 0.5, -0.5), f(-0.5, -0.5), f(-0.5, W - 0.5), f(H - 0.5, W - 0.5)]   # SO, NO, NE, SE (deck.gl)


import base64, io  # noqa: E401,E402
from PIL import Image  # noqa: E402
buf = io.BytesIO()
Image.fromarray(img, "RGBA").save(buf, format="PNG")
url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
capa = pdk.Layer("BitmapLayer", image=f"'{url}'",   # entre comillas: pydeck no lo trata como expresión
                 bounds=esquinas(zona[["row", "col", "lon", "lat"]]))
vista = pdk.ViewState(latitude=float(zona.lat.mean()), longitude=float(zona.lon.mean()), zoom=12.3, min_zoom=9)
st.pydeck_chart(pdk.Deck(layers=[capa] + capas_contexto(cargar_capas(), True), initial_view_state=vista,
                         map_provider="carto", map_style="light"), width="stretch", height=560)
if vista_mapa == "Probabilidad del modelo":
    st.caption("Rojo más intenso: mayor probabilidad calibrada de pérdida.")
if vista_mapa == "Clasificación vs oficial":
    st.markdown("<span style='color:#b2182b'>■</span> acierto de pérdida · <span style='color:#ffa500'>■</span> "
                "falsa alarma · <span style='color:#2166ac'>■</span> omisión · "
                "<span style='color:#9cbf9c'>■</span> bosque bien clasificado", unsafe_allow_html=True)
st.caption("Zona de 5 × 5 km con mayor pérdida oficial del área de estudio (cada punto es un píxel de 20 m de bosque "
           "en el año base). Etiqueta: pérdida antrópica de Geobosques, MINAM. Parte de los píxeles de pérdida pudo "
           "estar en la muestra de entrenamiento; las métricas honestas son las de la validación por bloques.")

seccion("Cómo decide el modelo")
c1, c2 = st.columns([1.1, 1], gap="large")
with c1:
    curva = []
    for t in np.round(np.arange(0.05, 0.96, 0.05), 2):
        pr_ = (p >= t)
        tp_ = (pr_ & (y == 1)).sum()
        pc, rc = (tp_ / pr_.sum() if pr_.sum() else np.nan), (tp_ / y.sum() if y.sum() else np.nan)
        curva.append({"umbral": t, "precisión": pc, "sensibilidad": rc,
                      "F1": 2 * pc * rc / (pc + rc) if pc + rc else np.nan})
    st.markdown("**Precisión, sensibilidad y F1 según el umbral (zona demo)**")
    st.line_chart(pd.DataFrame(curva).set_index("umbral"), height=300)
    st.caption("Subir el umbral reduce falsas alarmas pero omite más pérdida. Para estimar superficie se usa la suma "
               "de probabilidades calibradas, que no depende del umbral.")
with c2:
    imp = pd.Series(meta.get("importancias", {})).sort_values(ascending=False).head(12)
    if len(imp):
        st.markdown("**Variables más importantes**")
        st.bar_chart(imp.sort_values(), horizontal=True, height=320)
        st.caption("Sufijos: _t0 año base, _t1 año final, _d cambio. Las variables de cambio en SWIR y en los "
                   "índices de suelo desnudo (BSI) y vegetación (NDVI, NBR) capturan la huella minera.")
    else:
        figura("06_importancia.png", "Importancia de variables")
