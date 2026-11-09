"""Página 2: visor de hexágonos (misma funcionalidad que la Databricks App, sobre el paquete exportado)."""
import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

from comun import (ANIOS, AOI, HA_PX, LISA_COLORES, cargar_capas, cargar_hex, capas_contexto, colorear, ha,
                   sin_datos)

feat = cargar_hex()
if feat is None:
    sin_datos()
    st.stop()
capas = cargar_capas()

deptos = sorted(feat["departamento"].dropna().unique()) if "departamento" in feat else []
otros = [d for d in deptos if d != "Madre de Dios"]
st.title("🗺️ Visor: minería aurífera y deforestación en el corredor La Pampa, Huepetuhe y Mazuko")
st.caption("Sur de Madre de Dios" + (f", con sectores limítrofes de {' y '.join(otros)}" if otros else "") +
           " · tablas Gold calculadas en Databricks (Spark, Delta Lake, H3) y exportadas por el notebook 07")

INDICADORES = {
    "Cambio de NDVI 2018-2025": ("d_ndvi", "RdBu", -0.6, 0.6),
    "Pérdida antrópica oficial 2019-2025 (Geobosques)": ("tasa_perdida_oficial", "Reds", 0, 1),
    "Perturbación nueva en bosque (Sentinel-2)": ("d_pert", "Oranges", 0, 1),
    "NDVI de un año": (None, "RdYlGn", 0, 0.9),
    "Probabilidad de pérdida (Random Forest)": ("prob_modelo", "Reds", 0, 1),
    "Riesgo de deforestación (MINAM)": ("riesgo_deforestacion", "YlOrRd", 1, 5),
    "Clusters LISA": ("lisa", None, None, None),
    "Puntos calientes Getis-Ord Gi*": ("gi_z", "coolwarm", -6, 6),
}

c_filtros, c_mapa = st.columns([1, 3.3], gap="medium")
with c_filtros:
    nombre = st.selectbox("Variable del mapa", list(INDICADORES))
    col, cmap, vmin, vmax = INDICADORES[nombre]
    if nombre == "NDVI de un año":
        disponibles = [a for a in ANIOS if f"ndvi_{a}" in feat]
        col = f"ndvi_{st.select_slider('Año', options=disponibles, value=disponibles[-1])}"
    sel_dep = st.multiselect("Departamento", deptos, default=deptos)
    base = feat[feat["departamento"].isin(sel_dep)] if deptos else feat
    distritos = sorted(base["distrito"].dropna().unique()) if "distrito" in feat else []
    sel_dist = st.multiselect("Distrito", distritos, default=distritos)
    ambito = st.radio("Ámbito", ["Todo", "Dentro de ANP", "Zona de amortiguamiento", "Fuera de ANP"])
    tope = float(np.ceil(feat["dist_cauce_km"].max())) if "dist_cauce_km" in feat else 20.0
    max_cauce = st.slider("Distancia máxima a ríos y quebradas (km)", 0.0, tope, tope, 0.5)
    solo_bosque = st.toggle("Solo hexágonos de bosque en 2018", value=True)
    ver_ctx = st.toggle("Ríos, vía y áreas protegidas", value=True)

f = feat.copy()
if deptos:
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

with c_mapa:
    k = st.columns(5)
    perd = (f["frac_perdida_oficial"] * f["n_px_total"]).sum() * HA_PX
    mod = (f["prob_modelo"] * f["n_px_modelo"]).sum() * HA_PX if f["prob_modelo"].notna().any() else np.nan
    k[0].metric("Hexágonos (≈0.1 km²)", f"{len(f):,}".replace(",", " "))
    k[1].metric("Pérdida oficial 2019-2025", ha(perd))
    k[2].metric("Estimada por el modelo", ha(mod) if not np.isnan(mod) else "s/d",
                delta=f"{mod / perd - 1:+.1%} vs oficial" if perd and not np.isnan(mod) else None, delta_color="off")
    k[3].metric("Frentes activos (LISA)", f"{(f['lisa'] == 'Pérdida-Pérdida (frente activo)').sum():,}")
    k[4].metric("Puntos calientes Gi* 99 %", f"{(f['hotspot'] == 'Caliente 99%').sum():,}")

    tab_mapa, tab_evol, tab_dist, tab_hex = st.tabs(["Mapa", "Evolución 2018-2025", "Por distrito", "Explorar hexágono"])
    with tab_mapa:
        m = f.copy()
        if col == "lisa":
            m["color"] = m["lisa"].map(LISA_COLORES).apply(lambda c: c if isinstance(c, list) else [200, 200, 200, 40])
            m["valor"] = m["lisa"].fillna("s/d")
        else:
            m["color"] = colorear(m[col], cmap, vmin, vmax)
            m["valor"] = m[col].round(3).astype(str)
        for c in ["departamento", "distrito"]:
            m[c] = m[c].fillna("s/d") if c in m else ""
        capas_deck = [pdk.Layer("H3HexagonLayer", m[["h3", "color", "valor", "departamento", "distrito"]],
                                get_hexagon="h3", get_fill_color="color", stroked=False, pickable=True, opacity=0.85)]
        capas_deck += capas_contexto(capas, ver_ctx)
        vista = pdk.ViewState(latitude=(AOI[1] + AOI[3]) / 2, longitude=(AOI[0] + AOI[2]) / 2, zoom=9.5, min_zoom=7)
        st.pydeck_chart(pdk.Deck(layers=capas_deck, initial_view_state=vista, map_provider="carto", map_style="light",
                                 tooltip={"text": "{departamento} · {distrito}\n" + nombre + ": {valor}"}),
                        width="stretch", height=600)
        if col == "lisa":
            st.markdown(" · ".join(f"<span style='color:rgb({c[0]},{c[1]},{c[2]})'>■</span> {k}"
                                   for k, c in LISA_COLORES.items()), unsafe_allow_html=True)
        else:
            st.caption(f"Escala {vmin} a {vmax} ({cmap}). Gris: sin dato. Gris oscuro: límite departamental · "
                       "azul: ríos · negro: Interoceánica · morado: ANP · naranja: zona de amortiguamiento.")

    with tab_evol:
        filas = [{"Año": str(a), "NDVI medio": f[f"ndvi_{a}"].mean(),
                  "Bosque de 2018 perturbado": f[f"pert_{a}"].mean() if f"pert_{a}" in f else np.nan}
                 for a in ANIOS if f"ndvi_{a}" in f]
        ev = pd.DataFrame(filas).set_index("Año")
        c1, c2 = st.columns(2)
        c1.markdown("**NDVI medio (temporada seca)**")
        c1.line_chart(ev["NDVI medio"])
        c2.markdown("**Fracción del bosque de 2018 que aparece perturbada**")
        c2.line_chart(ev["Bosque de 2018 perturbado"])
        st.dataframe(ev.round(4), width="stretch")

    with tab_dist:
        if "distrito" in f and len(f):
            claves = ["departamento", "distrito"] if "departamento" in f else ["distrito"]
            g = f.groupby(claves).apply(lambda d: pd.Series({
                "hexágonos": len(d),
                "pérdida oficial (ha)": (d["frac_perdida_oficial"] * d["n_px_total"]).sum() * HA_PX,
                "pérdida modelo (ha)": (d["prob_modelo"] * d["n_px_modelo"]).sum() * HA_PX,
                "frentes activos (LISA)": (d["lisa"] == "Pérdida-Pérdida (frente activo)").sum(),
                "ΔNDVI medio": d["d_ndvi"].mean()}), include_groups=False).sort_values("pérdida oficial (ha)",
                                                                                       ascending=False)
            if isinstance(g.index, pd.MultiIndex):
                g.index = [f"{dis} ({dep})" for dep, dis in g.index]
            st.bar_chart(g[["pérdida oficial (ha)", "pérdida modelo (ha)"]])
            st.dataframe(g.round(2), width="stretch")

    with tab_hex:
        top = f.sort_values("tasa_perdida_oficial", ascending=False).head(50)
        elegido = st.selectbox("Hexágono (los 50 con mayor pérdida oficial en el filtro actual)", top["h3"].tolist()) \
            if len(top) else None
        if elegido:
            r = feat[feat["h3"] == elegido].iloc[0]
            c1, c2 = st.columns([1, 2])
            fmt = lambda v, p="{:.1%}": p.format(v) if pd.notna(v) else "s/d"  # noqa: E731
            datos = {"Departamento": r.get("departamento"), "Distrito": r.get("distrito"),
                     "Pérdida oficial": fmt(r.get("tasa_perdida_oficial")),
                     "Probabilidad modelo": fmt(r.get("prob_modelo")), "Cluster LISA": r.get("lisa"),
                     "Gi* (z)": fmt(r.get("gi_z"), "{:.2f}"),
                     "Riesgo MINAM (1-5)": fmt(r.get("riesgo_deforestacion"), "{:.1f}"),
                     "Distancia a ríos y quebradas": fmt(r.get("dist_cauce_km"), "{:.2f} km"),
                     "Distancia a la vía": fmt(r.get("dist_via_km"), "{:.2f} km"),
                     "Dentro de ANP": "Sí" if r.get("en_anp") == 1 else "No",
                     "Zona de amortiguamiento": "Sí" if r.get("en_za") == 1 else "No"}
            c1.table(pd.DataFrame({"Valor": [str(v) for v in datos.values()]}, index=list(datos.keys())))
            c2.markdown("**Serie de NDVI del hexágono**")
            c2.line_chart(pd.DataFrame({"NDVI": [r.get(f"ndvi_{a}") for a in ANIOS]}, index=[str(a) for a in ANIOS]))
            c2.caption(f"Celda H3 {elegido} · centro {r['lat']:.4f}, {r['lon']:.4f}")
