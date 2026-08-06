"""Página inicial — OTHIL Relatórios Comerciais."""
import os
import datetime
import streamlit as st

# ── Data formatada ────────────────────────────────────────────────────────────
hoje = datetime.date.today()
dias_pt   = ["Segunda-feira","Terça-feira","Quarta-feira","Quinta-feira",
             "Sexta-feira","Sábado","Domingo"]
meses_pt  = ["janeiro","fevereiro","março","abril","maio","junho",
             "julho","agosto","setembro","outubro","novembro","dezembro"]
data_fmt  = f"{dias_pt[hoje.weekday()]}, {hoje.day} de {meses_pt[hoje.month-1]} de {hoje.year}"

# ── Logo ──────────────────────────────────────────────────────────────────────
_LOGO = os.path.join(os.path.dirname(__file__), '..', 'assets', 'logo_othil.png')

st.markdown("<div style='height:1.5rem;'></div>", unsafe_allow_html=True)

col_l, col_c, col_r = st.columns([1, 2, 1])
with col_c:
    if os.path.exists(_LOGO):
        st.image(_LOGO, use_container_width=True)
    else:
        st.markdown("""
        <div style="text-align:center; font-size:2.4rem; font-weight:700;
                    color:#1B4332; letter-spacing:0.08em;">OTHIL</div>
        """, unsafe_allow_html=True)

# ── Subtítulo e data ──────────────────────────────────────────────────────────
st.markdown(f"""
<div style="text-align:center; padding: 0.6rem 0 0.4rem;">
    <div style="color:#1B4332; font-size:1.15rem; font-weight:600;
                letter-spacing:0.04em; margin-bottom:0.5rem;">
        Relatórios Comerciais
    </div>
    <div style="display:inline-block; background:#2D6A4F; color:#c8ebd6;
                padding:0.3rem 1.2rem; border-radius:20px;
                font-size:0.82rem; font-weight:500;">
        {data_fmt}
    </div>
</div>
""", unsafe_allow_html=True)

# ── Linha verde decorativa ────────────────────────────────────────────────────
st.markdown("""
<div style="margin: 1.4rem auto; width: 60px; height: 3px;
            background: #2D6A4F; border-radius: 2px;"></div>
""", unsafe_allow_html=True)

# ── Atalhos rápidos ───────────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center; color:#666; font-size:0.85rem; margin-bottom:1.2rem;">
    Use o menu lateral para acessar os módulos
</div>
""", unsafe_allow_html=True)

atalhos = [
    ("🎯", "Metas Semanais"),
    ("📊", "Relatório Diário"),
    ("👥", "Vendedor-Cliente"),
    ("🔄", "Recorrência"),
    ("🏢", "Gerência"),
]

cols = st.columns(len(atalhos), gap="small")
for col, (icon, nome) in zip(cols, atalhos):
    with col:
        st.markdown(f"""
        <div style="text-align:center; padding:0.7rem 0.3rem;
                    background:#F4F6F5; border:1px solid #d4e6db;
                    border-top: 3px solid #2D6A4F;
                    border-radius:8px;">
            <div style="font-size:1.4rem; margin-bottom:0.2rem;">{icon}</div>
            <div style="font-size:0.72rem; color:#1B4332; font-weight:600;
                        line-height:1.3;">{nome}</div>
        </div>
        """, unsafe_allow_html=True)
