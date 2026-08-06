"""Página inicial — OTHIL Relatórios Comerciais."""
import streamlit as st
import datetime

# --- Hero ---
hoje = datetime.date.today()
dias_pt = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
           "Sexta-feira", "Sábado", "Domingo"]
meses_pt = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
            "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
dia_semana = dias_pt[hoje.weekday()]
data_fmt = f"{dia_semana}, {hoje.day} de {meses_pt[hoje.month - 1]} de {hoje.year}"

st.markdown(f"""
<div style="
    background: linear-gradient(135deg, #1B4332 0%, #2D6A4F 100%);
    border-radius: 14px;
    padding: 1.4rem 1.8rem;
    margin-bottom: 1.6rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
">
    <div>
        <div style="display:inline-block; background:rgba(255,255,255,0.15);
                    color:#a8e6be; padding:0.3rem 1rem; border-radius:8px;
                    font-size:0.85rem; font-weight:600; letter-spacing:0.1em;
                    margin-bottom:0.6rem;">
            ⬡ OTHIL
        </div>
        <div style="color:#fff; font-size:1.35rem; font-weight:600; margin-bottom:0.2rem;">
            Relatórios Comerciais
        </div>
        <div style="color:rgba(255,255,255,0.6); font-size:0.88rem;">
            {data_fmt}
        </div>
    </div>
    <div style="color:rgba(255,255,255,0.35); font-size:2.2rem; font-weight:700;
                letter-spacing:-0.02em;">
        OTHIL
    </div>
</div>
""", unsafe_allow_html=True)

# --- Cards de módulos ---
cols = st.columns(2, gap="large")

modulos = [
    {
        "icon": "🎯",
        "titulo": "Metas Semanais e Responsáveis",
        "desc": "Configure os produtos da semana, percentuais por vendedor e gere os relatórios PDF de meta vs. realizado.",
    },
    {
        "icon": "📊",
        "titulo": "Relatório Diário",
        "desc": "Faça upload do PDF diário de Lucratividade e visualize o dashboard com KPIs, alertas e impacto por vendedor.",
    },
    {
        "icon": "🔄",
        "titulo": "Recorrência de Vendas",
        "desc": "Analise a recorrência de clientes ao longo do período com a matriz cliente × produto.",
    },
    {
        "icon": "👥",
        "titulo": "Vendedor-Cliente",
        "desc": "Compare desempenho de vendedores por cliente com histórico, metas e resultado real.",
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

st.caption("Use o menu lateral para navegar entre os módulos.")
