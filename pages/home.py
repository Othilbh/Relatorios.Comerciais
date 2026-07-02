"""Página inicial — OTHIL Relatórios Comerciais."""
import streamlit as st

st.markdown("""
<div style="text-align:center; padding: 2rem 0 1rem;">
    <div style="display:inline-block; background:#2D6A4F; color:white;
                padding:0.6rem 1.8rem; border-radius:12px; margin-bottom:1rem;">
        <span style="font-size:1.1rem; font-weight:600; letter-spacing:0.08em;">OTHIL</span>
    </div>
    <h1 style="margin:0.4rem 0 0.2rem; color:#1B4332; font-size:2rem;">Relatórios Comerciais</h1>
    <p style="color:#555; font-size:1rem; margin:0;">
        Plataforma interna de análise de vendas, metas e lucratividade.
    </p>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

cols = st.columns(2, gap="large")

modulos = [
    {
        "icon": "🎯",
        "titulo": "Metas Semanais e Responsáveis",
        "desc": "Configure os produtos da semana, percentuais por vendedor e gere os relatórios PDF de meta vs. realizado.",
        "pagina": "Metas Semanais e Responsáveis",
    },
    {
        "icon": "📊",
        "titulo": "Relatório Diário",
        "desc": "Faça upload do PDF diário de Lucratividade e visualize o dashboard com KPIs, alertas e impacto por vendedor.",
        "pagina": "Relatório Diário",
    },
    {
        "icon": "🔄",
        "titulo": "Recorrência de Vendas",
        "desc": "Analise a recorrência de clientes ao longo do período com a matriz cliente × produto.",
        "pagina": "Recorrência",
    },
    {
        "icon": "👥",
        "titulo": "Vendedor-Cliente",
        "desc": "Compare desempenho de vendedores por cliente com histórico, metas e resultado real.",
        "pagina": "Vendedor-Cliente",
    },
]

for i, mod in enumerate(modulos):
    col = cols[i % 2]
    with col:
        st.markdown(f"""
        <div style="
            background:#F4F6F5;
            border:1px solid #d4e6db;
            border-left: 4px solid #2D6A4F;
            border-radius:10px;
            padding:1.2rem 1.4rem;
            margin-bottom:1.2rem;
        ">
            <div style="font-size:1.8rem; margin-bottom:0.3rem;">{mod['icon']}</div>
            <div style="font-weight:600; color:#1B4332; font-size:1rem; margin-bottom:0.4rem;">
                {mod['titulo']}
            </div>
            <div style="color:#444; font-size:0.88rem; line-height:1.5;">
                {mod['desc']}
            </div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
st.caption("Use o menu lateral para navegar entre os módulos.")
