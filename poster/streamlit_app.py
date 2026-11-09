"""
Póster interactivo: minería aurífera y deforestación en Madre de Dios (Estadística Espacial, UNMSM).

Se publica en Streamlit Community Cloud directamente desde GitHub (archivo principal: poster/streamlit_app.py).
No necesita Databricks: lee el paquete que el notebook 07 exporta desde las tablas Gold y el modelo de MLflow
(poster/data/) y las figuras generadas en la nube (docs/figuras, docs/capturas).

Páginas:
  1. Póster             resumen científico completo con mapa interactivo
  2. Visor              el visor de la Databricks App (indicadores, filtros, evolución, distritos, ficha de hexágono)
  3. Modelo en vivo     el Random Forest entrenado en Databricks puntuando píxeles reales en este servidor

Prueba local:
    pip install -r poster/requirements.txt
    streamlit run poster/streamlit_app.py
"""
import sys
from pathlib import Path

import streamlit as st

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
from comun import estilo  # noqa: E402

st.set_page_config(page_title="Minería y deforestación en Madre de Dios", page_icon="🛰️", layout="wide",
                   initial_sidebar_state="collapsed")
estilo()

pg = st.navigation([
    st.Page(AQUI / "paginas" / "poster.py", title="Póster", icon="🧾", default=True),
    st.Page(AQUI / "paginas" / "visor.py", title="Visor de hexágonos", icon="🗺️"),
    st.Page(AQUI / "paginas" / "modelo.py", title="Modelo en vivo", icon="🤖"),
], position="top")
pg.run()
