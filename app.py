"""OTHIL — Relatórios Comerciais — ponto de entrada (router)."""
import os
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
/* Reduzir margem superior do conteúdo */
.block-container {
    padding-top: 1.5rem !important;
}
</style>
""", unsafe_allow_html=True)

# Navigation
# Data/hora do último deploy_github.ps1, gravada em VERSION.txt pelo
# próprio script no momento do envio. Mostrar isso na barra lateral resolve
# um problema recorrente: não tinha como confirmar, olhando de fora, se um
# deploy realmente chegou no app publicado ou não (o cache do GitHub podia
# mostrar conteúdo antigo por minutos mesmo depois de um deploy que já
# tinha funcionado). Agora é só olhar o próprio app rodando.
try:
    _version_path = os.path.join(os.path.dirname(__file__), 'VERSION.txt')
    with open(_version_path, 'r', encoding='utf-8') as _vf:
        _versao = _vf.read().strip()
    if _versao:
        st.sidebar.caption(f'🕓 Publicado em: {_versao}')
except FileNotFoundError:
    pass

pg = st.navigation(
    {
        "": [
            st.Page("pages/home.py", title="Início", icon="🏠", default=True),
        ],
        "Módulos": [
            st.Page("pages/metas_semanais.py", title="Metas Semanais", icon="🎯"),
            st.Page("pages/1_Relatorio_Diario_OTHIL.py", title="Relatório Diário", icon="📊"),
            st.Page("pages/2_Recorrencia_OTHIL.py", title="Recorrência", icon="🔄"),
            st.Page("pages/3_Vendedor_Cliente_OTHIL.py", title="Vendedor-Cliente", icon="👥"),
            st.Page("pages/4_Quebra_OTHIL.py", title="Quebras", icon="📦"),
            st.Page("pages/5_Prevencao_Perdas_OTHIL.py", title="Prevenção de Perdas", icon="🚨"),
            st.Page("pages/6_Rentabilidade_Margens_OTHIL.py", title="Rentabilidade e Margens", icon="💰"),
            st.Page("pages/7_Relatorios_Produtos_OTHIL.py", title="Resultado de Produtos", icon="📈"),
        ],
        "Administração": [
            st.Page("pages/gerencia.py", title="Gerência", icon="🔐"),
            st.Page("pages/8_Cadastro_Produtos_OTHIL.py", title="Cadastro de Marcas", icon="🏷️"),
        ],
    }
)
pg.run()
