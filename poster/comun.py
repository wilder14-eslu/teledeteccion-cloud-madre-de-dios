"""Rutas, carga de datos y utilidades compartidas por las páginas del póster."""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

AQUI = Path(__file__).resolve().parent
if str(AQUI) not in sys.path:
    sys.path.insert(0, str(AQUI))
import contenido as T  # noqa: E402,F401

REPO = AQUI.parent
DATA = Path(os.getenv("POSTER_DATA", AQUI / "data"))
FIG = REPO / "docs" / "figuras"
CAP = REPO / "docs" / "capturas"
ASSETS = AQUI / "assets"
HA_PX = 0.04                                  # hectáreas por píxel de 20 m
ANIOS = [2018, 2020, 2022, 2024, 2025]
AOI = (-70.45, -13.15, -69.85, -12.80)
LISA_COLORES = {"Pérdida-Pérdida (frente activo)": [178, 24, 43, 225], "Aumento-Aumento (mayor verdor)": [33, 102, 172, 200],
                "Pérdida aislada": [244, 165, 130, 210], "Aumento aislado": [146, 197, 222, 210],
                "No significativo": [235, 235, 235, 70]}


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Cargando hexágonos...")
def cargar_hex():
    f = DATA / "h3_poster.parquet"
    if not f.exists():
        return None
    df = pd.read_parquet(f)
    for c in ["departamento", "provincia", "distrito"]:          # GADM escribe algunos nombres sin espacios
        if c in df:
            df[c] = df[c].replace({"MadredeDios": "Madre de Dios"})
    return df


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


def estilo():
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


def capas_contexto(capas, ver_ctx=True):
    """Capas pydeck de límite departamental, ríos, vía, ANP, zonas de amortiguamiento y poblados."""
    out = []
    if "departamentos" in capas:
        out.append(pdk.Layer("PathLayer", capas["departamentos"], get_path="path", get_color=[50, 50, 50],
                             width_min_pixels=3))
    if ver_ctx:
        for n, c, w in [("rios", [31, 120, 180], 1.5), ("vias", [20, 20, 20], 2.5),
                        ("areas_protegidas_sernanp", [128, 0, 128], 2), ("zonas_amortiguamiento", [255, 140, 0], 2)]:
            if n in capas and len(capas[n]):
                out.append(pdk.Layer("PathLayer", capas[n], get_path="path", get_color=c, width_min_pixels=w))
    if "poblados" in capas and len(capas["poblados"]):
        out.append(pdk.Layer("TextLayer", capas["poblados"], get_position=["lon", "lat"], get_text="name",
                             get_size=13, get_color=[0, 0, 0], get_alignment_baseline="'bottom'"))
    return out


def sin_datos():
    st.info("Aún no se exportaron los datos (poster/data/). Ejecuta el notebook 07 en Databricks y luego "
            "scripts/exportar_resultados.ps1.")
