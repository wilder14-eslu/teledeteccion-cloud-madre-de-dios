"""
Visor de minería aurífera y deforestación en Madre de Dios.

Databricks App (Streamlit) que consulta las tablas Gold de Unity Catalog a través de
un SQL Warehouse serverless. No copia datos: cada consulta va a la nube y se cachea.

Variables de entorno:
  DATABRICKS_WAREHOUSE_ID   inyectada por Databricks Apps desde el recurso "sql-warehouse"
  GEOCLOUD_SCHEMA           esquema de las tablas (por defecto workspace.madre_dios_rs)
  GEOCLOUD_LOCAL            ruta a un directorio con tablas Parquet (solo pruebas locales)
"""
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

SCHEMA = os.getenv("GEOCLOUD_SCHEMA", "workspace.madre_dios_rs")
HA_PX = 0.04                      # hectáreas por píxel de 20 m
ANIOS = [2018, 2020, 2022, 2024, 2025]
AOI = (-70.45, -13.15, -69.85, -12.80)   # área de estudio (lon_min, lat_min, lon_max, lat_max)

st.set_page_config(page_title="Minería y deforestación | Madre de Dios", page_icon="🛰️", layout="wide")


# ---------------------------------------------------------------------------
# Acceso a datos
# ---------------------------------------------------------------------------
def _query_databricks(q: str) -> pd.DataFrame:
    from databricks import sql
    from databricks.sdk.core import Config
    cfg = Config()
    with sql.connect(server_hostname=cfg.host,
                     http_path=f"/sql/1.0/warehouses/{os.environ['DATABRICKS_WAREHOUSE_ID']}",
                     credentials_provider=lambda: cfg.authenticate) as conn:
        with conn.cursor() as cur:
            cur.execute(q)
            return cur.fetchall_arrow().to_pandas()


def _query_local(q: str) -> pd.DataFrame:
    import duckdb
    con = duckdb.connect()
    base = Path(os.environ["GEOCLOUD_LOCAL"])
    schema = SCHEMA.split(".")[-1]
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    for d in base.iterdir():
        if d.is_dir():
            con.execute(f"CREATE VIEW {schema}.{d.name} AS SELECT * FROM read_parquet('{d}/**/*.parquet', "
                        f"hive_partitioning=true)")
    return con.execute(q.replace(SCHEMA, schema)).df()


@st.cache_data(ttl=3600, show_spinner="Consultando Unity Catalog...")
def query(q: str) -> pd.DataFrame:
    return _query_local(q) if os.getenv("GEOCLOUD_LOCAL") else _query_databricks(q)


@st.cache_data(ttl=3600, show_spinner=False)
def cargar_datos():
    feat = query(f"SELECT * FROM {SCHEMA}.gold_h3_features")
    for c in ["departamento", "provincia", "distrito"]:          # GADM escribe algunos nombres sin espacios
        if c in feat:
            feat[c] = feat[c].replace({"MadredeDios": "Madre de Dios"})
    try:
        cl = query(f"SELECT h3, lisa, gi_z, hotspot FROM {SCHEMA}.gold_h3_clusters")
        feat = feat.merge(cl, on="h3", how="left")
    except Exception:
        feat["lisa"], feat["gi_z"], feat["hotspot"] = None, np.nan, None
    try:
        pr = query(f"SELECT h3, prob_modelo, frac_predicha, n AS n_px_modelo FROM {SCHEMA}.gold_h3_prediccion")
        feat = feat.merge(pr, on="h3", how="left")
    except Exception:
        feat["prob_modelo"], feat["frac_predicha"], feat["n_px_modelo"] = np.nan, np.nan, np.nan
    return feat


@st.cache_data(ttl=3600, show_spinner=False)
def cargar_capas():
    from shapely import wkt
    from shapely.geometry import box
    caja = box(*AOI).buffer(0.03)                     # todo se recorta al área de estudio
    capas = {}
    for nombre in ["departamentos", "rios", "vias", "areas_protegidas_sernanp", "zonas_amortiguamiento", "poblados"]:
        try:
            df = query(f"SELECT * FROM {SCHEMA}.bronze_vec_{nombre}")
        except Exception:
            continue
        geoms = [wkt.loads(w) for w in df["wkt"]]
        if nombre == "departamentos":
            etiquetas = []
            for d, g in zip(df["departamento"], geoms):
                parte = g.intersection(box(*AOI))
                if not parte.is_empty and parte.area > 0.03 * box(*AOI).area:
                    p = parte.representative_point()
                    etiquetas.append({"name": str(d).upper(), "lon": p.x, "lat": p.y})
            capas["departamentos_etiquetas"] = pd.DataFrame(etiquetas)
        geoms = [g.intersection(caja) if nombre != "poblados" else g for g in geoms]
        if nombre == "poblados":
            capas[nombre] = pd.DataFrame({"name": df["name"], "lon": [g.x for g in geoms], "lat": [g.y for g in geoms]})
            continue
        paths = []
        for g in geoms:
            if g.is_empty:
                continue
            for p in getattr(g, "geoms", [g]):
                if p.geom_type == "Polygon":
                    linea = p.exterior
                elif p.geom_type in ("LineString", "LinearRing"):
                    linea = p
                else:
                    continue
                paths.append({"path": [list(c[:2]) for c in linea.coords]})
        capas[nombre] = pd.DataFrame(paths)
    return capas


# ---------------------------------------------------------------------------
# Utilidades de color
# ---------------------------------------------------------------------------
def colorear(serie: pd.Series, cmap: str, vmin: float, vmax: float, alpha: int = 200):
    import matplotlib
    cm = matplotlib.colormaps[cmap]
    x = ((serie.astype(float) - vmin) / (vmax - vmin)).clip(0, 1)
    rgba = (cm(x.fillna(0).values)[:, :3] * 255).astype(int)
    out = [[int(x) for x in c] + [alpha] for c in rgba]   # int nativo: pydeck serializa numpy.int64 como texto
    return [c if not np.isnan(v) else [200, 200, 200, 60] for c, v in zip(out, serie.astype(float))]


LISA_COLORES = {"Pérdida-Pérdida (frente activo)": [178, 24, 43, 220], "Aumento-Aumento (mayor verdor)": [33, 102, 172, 200],
                "Pérdida aislada": [244, 165, 130, 200], "Aumento aislado": [146, 197, 222, 200],
                "No significativo": [235, 235, 235, 90]}


# ---------------------------------------------------------------------------
# Interfaz
# ---------------------------------------------------------------------------
feat = cargar_datos()
capas = cargar_capas()

deptos_area = sorted(feat["departamento"].dropna().unique()) if "departamento" in feat else ["Madre de Dios"]
otros = [d for d in deptos_area if d != "Madre de Dios"]
st.title("🛰️ Minería aurífera y deforestación en el corredor La Pampa, Huepetuhe y Mazuko")
st.caption("Sur de Madre de Dios" + (f", con sectores limítrofes de {' y '.join(otros)}" if otros else "") +
           " · Sentinel-2, Geobosques (MINAM), SERNANP · procesado en Databricks (Spark, Delta Lake, H3) "
           "y servido desde Unity Catalog")

with st.sidebar:
    st.header("Indicador")
    indicadores = {
        "Cambio de NDVI 2018-2025": ("d_ndvi", "RdBu", -0.6, 0.6),
        "Pérdida antrópica oficial 2019-2025 (Geobosques)": ("tasa_perdida_oficial", "Reds", 0, 1),
        "Perturbación nueva en bosque (Sentinel-2)": ("d_pert", "Oranges", 0, 1),
        "NDVI de un año": (None, "RdYlGn", 0, 0.9),
        "Probabilidad de pérdida (modelo Random Forest)": ("prob_modelo", "Reds", 0, 1),
        "Riesgo de deforestación (MINAM)": ("riesgo_deforestacion", "YlOrRd", 1, 5),
        "Clusters LISA": ("lisa", None, None, None),
        "Puntos calientes Getis-Ord Gi*": ("gi_z", "coolwarm", -6, 6),
    }
    nombre_ind = st.radio("Variable del mapa", list(indicadores), index=0)
    col, cmap, vmin, vmax = indicadores[nombre_ind]
    if nombre_ind == "NDVI de un año":
        disponibles = [a for a in ANIOS if f"ndvi_{a}" in feat]
        anio = st.select_slider("Año", options=disponibles, value=disponibles[-1])
        col = f"ndvi_{anio}"

    st.header("Filtros")
    sel_dep = st.multiselect("Departamento", deptos_area, default=deptos_area)
    base_dist = feat[feat["departamento"].isin(sel_dep)] if "departamento" in feat else feat
    distritos = sorted(base_dist["distrito"].dropna().unique()) if "distrito" in feat else []
    sel_dist = st.multiselect("Distrito", distritos, default=distritos)
    ambito = st.radio("Ámbito", ["Todo", "Dentro de ANP", "Zona de amortiguamiento", "Fuera de ANP"], horizontal=False)
    max_cauce = st.slider("Distancia máxima a ríos y quebradas (km)", 0.0,
                          float(np.ceil(feat["dist_cauce_km"].max())) if "dist_cauce_km" in feat else 20.0,
                          float(np.ceil(feat["dist_cauce_km"].max())) if "dist_cauce_km" in feat else 20.0, 0.5)
    solo_bosque = st.checkbox("Solo hexágonos de bosque en 2018", value=True)
    st.header("Capas de contexto")
    ver_rios = st.checkbox("Ríos", True)
    ver_vias = st.checkbox("Vía Interoceánica", True)
    ver_anp = st.checkbox("ANP y zonas de amortiguamiento", True)

f = feat.copy()
if "departamento" in f:
    f = f[f["departamento"].isin(sel_dep)]
if sel_dist and "distrito" in f:
    f = f[f["distrito"].isin(sel_dist) | f["distrito"].isna()]
if ambito == "Dentro de ANP" and "en_anp" in f:
    f = f[f["en_anp"] == 1]
elif ambito == "Zona de amortiguamiento" and "en_za" in f:
    f = f[f["en_za"] == 1]
elif ambito == "Fuera de ANP" and "en_anp" in f:
    f = f[f["en_anp"] == 0]
if "dist_cauce_km" in f:
    f = f[f["dist_cauce_km"] <= max_cauce]
if solo_bosque and "frac_bosque_y0" in f:
    f = f[f["frac_bosque_y0"] >= 0.5]

# KPIs
k = st.columns(5)
perdida_ha = (f["frac_perdida_oficial"] * f["n_px_total"]).sum() * HA_PX if "frac_perdida_oficial" in f else np.nan
modelo_ha = (f["prob_modelo"] * f["n_px_modelo"]).sum() * HA_PX if f["prob_modelo"].notna().any() else np.nan
k[0].metric("Hexágonos (≈0.1 km²)", f"{len(f):,}")
k[1].metric("Pérdida oficial 2019-2025", f"{perdida_ha:,.0f} ha")
k[2].metric("Pérdida estimada por el modelo", f"{modelo_ha:,.0f} ha" if not np.isnan(modelo_ha) else "s/d",
            delta=f"{(modelo_ha / perdida_ha - 1):+.1%} vs oficial" if perdida_ha and not np.isnan(modelo_ha) else None,
            delta_color="off")
k[3].metric("Frentes activos (LISA)", f"{(f['lisa'] == 'Pérdida-Pérdida (frente activo)').sum():,}")
k[4].metric("Puntos calientes Gi* 99 %", f"{(f['hotspot'] == 'Caliente 99%').sum():,}")

tab_mapa, tab_evol, tab_dist, tab_hex, tab_info = st.tabs(
    ["🗺️ Mapa", "📈 Evolución 2018-2025", "🏘️ Por distrito", "🔎 Explorar hexágono", "ℹ️ Acerca de"])

with tab_mapa:
    m = f.copy()
    if col == "lisa":
        m["color"] = m["lisa"].map(LISA_COLORES).apply(lambda c: c if isinstance(c, list) else [200, 200, 200, 40])
    else:
        m["color"] = colorear(m[col], cmap, vmin, vmax)
    m["valor"] = m[col].round(3).astype(str) if col != "lisa" else m["lisa"].fillna("s/d")
    for c in ["departamento", "distrito"]:
        if c not in m:
            m[c] = ""
    m[["departamento", "distrito"]] = m[["departamento", "distrito"]].fillna("s/d")
    capas_deck = [pdk.Layer("H3HexagonLayer", m[["h3", "color", "valor", "departamento", "distrito"]], get_hexagon="h3",
                            get_fill_color="color", stroked=False, extruded=False, pickable=True, opacity=0.85)]
    if "departamentos" in capas:
        capas_deck.append(pdk.Layer("PathLayer", capas["departamentos"], get_path="path", get_color=[60, 60, 60],
                                    width_min_pixels=3))
        if len(capas.get("departamentos_etiquetas", [])):
            capas_deck.append(pdk.Layer("TextLayer", capas["departamentos_etiquetas"], get_position=["lon", "lat"],
                                        get_text="name", get_size=18, get_color=[60, 60, 60, 200]))
    if ver_rios and "rios" in capas:
        capas_deck.append(pdk.Layer("PathLayer", capas["rios"], get_path="path", get_color=[31, 120, 180],
                                    width_min_pixels=1.5))
    if ver_vias and "vias" in capas:
        capas_deck.append(pdk.Layer("PathLayer", capas["vias"], get_path="path", get_color=[20, 20, 20],
                                    width_min_pixels=2.5))
    if ver_anp:
        for n, c in [("areas_protegidas_sernanp", [128, 0, 128]), ("zonas_amortiguamiento", [255, 140, 0])]:
            if n in capas:
                capas_deck.append(pdk.Layer("PathLayer", capas[n], get_path="path", get_color=c, width_min_pixels=2))
    if "poblados" in capas:
        capas_deck.append(pdk.Layer("TextLayer", capas["poblados"], get_position=["lon", "lat"], get_text="name",
                                    get_size=12, get_color=[0, 0, 0], get_alignment_baseline="'bottom'"))
    vista = pdk.ViewState(latitude=(AOI[1] + AOI[3]) / 2, longitude=(AOI[0] + AOI[2]) / 2, zoom=9.6, min_zoom=8)
    st.pydeck_chart(pdk.Deck(layers=capas_deck, initial_view_state=vista, map_provider="carto", map_style="light",
                             tooltip={"text": "{departamento} · {distrito}\n" + nombre_ind + ": {valor}"}),
                    width="stretch", height=620)
    st.caption("Línea gris gruesa: límite departamental. Morado: ANP (SERNANP). Naranja: zona de amortiguamiento.")
    if col == "lisa":
        st.markdown(" · ".join(f"<span style='color:rgb({c[0]},{c[1]},{c[2]})'>■</span> {k}"
                               for k, c in LISA_COLORES.items()), unsafe_allow_html=True)
    else:
        st.caption(f"Escala de color: {vmin} a {vmax} ({cmap}). Gris: sin dato.")

with tab_evol:
    filas = []
    for a in ANIOS:
        if f"ndvi_{a}" in f:
            filas.append({"Año": a, "NDVI medio": f[f"ndvi_{a}"].mean(),
                          "Fracción de bosque 2018 perturbada": f.get(f"pert_{a}", pd.Series(dtype=float)).mean()})
    ev = pd.DataFrame(filas).set_index("Año")
    c1, c2 = st.columns(2)
    c1.subheader("NDVI medio (temporada seca)")
    c1.line_chart(ev["NDVI medio"])
    c2.subheader("Bosque de 2018 que aparece perturbado")
    c2.line_chart(ev["Fracción de bosque 2018 perturbada"])
    st.dataframe(ev.round(4), width="stretch")

with tab_dist:
    if "distrito" in f:
        claves = ["departamento", "distrito"] if "departamento" in f else ["distrito"]
        g = f.groupby(claves).apply(lambda d: pd.Series({
            "hexágonos": len(d),
            "pérdida oficial (ha)": (d["frac_perdida_oficial"] * d["n_px_total"]).sum() * HA_PX,
            "pérdida modelo (ha)": (d["prob_modelo"] * d["n_px_modelo"]).sum() * HA_PX,
            "frentes activos (LISA)": (d["lisa"] == "Pérdida-Pérdida (frente activo)").sum(),
            "ΔNDVI medio": d["d_ndvi"].mean()}), include_groups=False).sort_values("pérdida oficial (ha)", ascending=False)
        if isinstance(g.index, pd.MultiIndex):
            g.index = [f"{dis} ({dep})" for dep, dis in g.index]
        st.bar_chart(g[["pérdida oficial (ha)", "pérdida modelo (ha)"]])
        st.dataframe(g.round(2), width="stretch")

with tab_hex:
    top = f.sort_values("tasa_perdida_oficial", ascending=False).head(50) if "tasa_perdida_oficial" in f else f.head(50)
    opciones = top["h3"].tolist()
    elegido = st.selectbox("Hexágono (los 50 con mayor pérdida oficial en el filtro actual)", opciones) if opciones else None
    if elegido:
        r = feat[feat["h3"] == elegido].iloc[0]
        c1, c2 = st.columns([1, 2])
        datos = {"Departamento": r.get("departamento"), "Distrito": r.get("distrito"), "Pérdida oficial": f"{r.get('tasa_perdida_oficial', np.nan):.1%}",
                 "Probabilidad modelo": f"{r.get('prob_modelo', np.nan):.1%}", "Cluster LISA": r.get("lisa"),
                 "Gi* (z)": f"{r.get('gi_z', np.nan):.2f}", "Riesgo MINAM (1-5)": f"{r.get('riesgo_deforestacion', np.nan):.1f}",
                 "Distancia a ríos y quebradas": f"{r.get('dist_cauce_km', np.nan):.2f} km",
                 "Distancia a la vía": f"{r.get('dist_via_km', np.nan):.2f} km",
                 "Dentro de ANP": "Sí" if r.get("en_anp") == 1 else "No",
                 "Zona de amortiguamiento": "Sí" if r.get("en_za") == 1 else "No"}
        c1.table(pd.DataFrame(datos.items(), columns=["Atributo", "Valor"]).set_index("Atributo"))
        serie = pd.DataFrame({"NDVI": [r.get(f"ndvi_{a}") for a in ANIOS]}, index=ANIOS)
        c2.subheader("Serie de NDVI del hexágono")
        c2.line_chart(serie)
        c2.caption(f"Celda H3 {elegido} · centro {r['lat']:.4f}, {r['lon']:.4f}")

with tab_info:
    st.markdown("""
**Arquitectura en la nube**

1. **Landing → Bronze:** fuentes oficiales (SERNANP, Geobosques, GADM, OpenStreetMap) y descarga *cloud-to-cloud*
   de Sentinel-2 (AWS Open Data) y Hansen GFC (Google Cloud Storage) a un Volume de Unity Catalog.
2. **Silver:** compuestos anuales sin nubes e índices espectrales por píxel de 20 m con Spark (`applyInPandas`).
3. **Gold:** grilla hexagonal H3, covariables, estadística espacial (Moran, LISA, Gi*), kriging, patrones
   puntuales, regresión espacial y modelo de pérdida registrado en MLflow.
4. **Orquestación:** Databricks Job serverless definido como código (Asset Bundle).
5. **Servicio:** esta aplicación consulta las tablas Gold a través de un SQL Warehouse serverless.

**Fuentes:** Copernicus Sentinel-2 (ESA); Geobosques, MINAM; Hansen et al. (2013), Global Forest Change v1.12;
SERNANP; GADM 4.1; OpenStreetMap.
""")
