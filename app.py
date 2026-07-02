"""OTHIL — Relatórios Comerciais — ponto de entrada (router)."""
import streamlit as st

st.set_page_config(
    page_title='OTHIL — Relatórios Comerciais',
    page_icon='🌿',
    layout='wide',
)

# Verde OTHIL CSS
st.markdown("""
<style>
/* Sidebar background */
[data-testid="stSidebar"] {
    background-color: #1B4332 !important;
}
[data-testid="stSidebar"] * {
    color: #E8F5E9 !important;
}
/* Active nav link */
[data-testid="stSidebarNavLink"][aria-current="page"] {
    background-color: #2D6A4F !important;
    border-left: 3px solid #74C69D;
    border-radius: 6px;
}
/* Nav links hover */
[data-testid="stSidebarNavLink"]:hover {
    background-color: #2D6A4F99 !important;
    border-radius: 6px;
}
/* Sidebar logo/title area */
[data-testid="stSidebarHeader"] {
    background-color: #1B4332 !important;
    border-bottom: 1px solid #2D6A4F;
    padding: 1rem;
}
/* Primary buttons */
.stButton > button[kind="primary"] {
    background-color: #2D6A4F !important;
    border-color: #2D6A4F !important;
    color: white !important;
}
.stButton > button[kind="primary"]:hover {
    background-color: #1B4332 !important;
    border-color: #74C69D !important;
}
/* Section headers */
h1, h2, h3 {
    color: #1B4332;
}
</style>
""", unsafe_allow_html=True)

# Navigation
pg = st.navigation(
    {
        "": [
            st.Page("pages/home.py", title="Início", icon="🏠", default=True),
        ],
        "Módulos": [
            st.Page("pages/metas_semanais.py", title="Metas Semanais e Responsáveis", icon="🎯"),
            st.Page("pages/1_Relatorio_Diario_OTHIL.py", title="Relatório Diário", icon="📊"),
            st.Page("pages/2_Recorrencia_OTHIL.py", title="Recorrência", icon="🔄"),
            st.Page("pages/3_Vendedor_Cliente_OTHIL.py", title="Vendedor-Cliente", icon="👥"),
        ],
        "Administração": [
            st.Page("pages/gerencia.py", title="Gerência", icon="🔐"),
        ],
    }
)
pg.run()
