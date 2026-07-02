"""Página de Gerência OTHIL — acesso restrito por senha."""
import json
import os

import streamlit as st
import streamlit.components.v1 as components

_GERENCIA_DIR = os.path.join(os.path.dirname(__file__), '..', 'gerencia_data')
_REC_JSON     = os.path.join(_GERENCIA_DIR, 'recorrencia_latest.json')
_SENHA_FALLBACK = 'othil2024'


def _get_senha() -> str:
    try:
        return st.secrets['gerencia_senha']
    except Exception:
        return _SENHA_FALLBACK


def _check_auth() -> bool:
    if st.session_state.get('_gerencia_auth'):
        return True

    st.markdown("""
    <div style="text-align:center; padding:3rem 0 1rem;">
        <div style="display:inline-block; background:#2D6A4F; color:white;
                    padding:0.5rem 1.6rem; border-radius:10px; margin-bottom:1rem;">
            <span style="font-size:1rem; font-weight:600; letter-spacing:0.08em;">OTHIL</span>
        </div>
        <h2 style="color:#1B4332; margin:0.4rem 0;">Área de Gerência</h2>
        <p style="color:#666; font-size:0.9rem;">Acesso restrito</p>
    </div>
    """, unsafe_allow_html=True)

    col = st.columns([1, 2, 1])[1]
    with col:
        pwd = st.text_input('Senha', type='password', key='_gerencia_pwd',
                            label_visibility='collapsed', placeholder='Digite a senha de acesso')
        if st.button('Entrar', type='primary', use_container_width=True):
            if pwd == _get_senha():
                st.session_state['_gerencia_auth'] = True
                st.rerun()
            else:
                st.error('Senha incorreta.')
    return False


def _listar_dashboards():
    """Retorna lista de (slug, meta_dict) ordenada do mais recente para o mais antigo."""
    if not os.path.exists(_GERENCIA_DIR):
        return []
    items = []
    for fname in os.listdir(_GERENCIA_DIR):
        if fname.startswith('dashboard_') and fname.endswith('.json'):
            try:
                with open(os.path.join(_GERENCIA_DIR, fname), 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                slug = meta.get('slug') or fname.replace('dashboard_', '').replace('.json', '')
                html_path = os.path.join(_GERENCIA_DIR, f'dashboard_{slug}.html')
                if os.path.exists(html_path):
                    items.append((slug, meta))
            except Exception:
                pass
    items.sort(key=lambda x: x[0], reverse=True)
    return items


# ── Auth ──────────────────────────────────────────────────────────────────────
if not _check_auth():
    st.stop()

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="display:flex; align-items:center; gap:1rem; margin-bottom:1rem;">
    <div style="background:#2D6A4F; color:white; padding:0.3rem 1rem;
                border-radius:8px; font-weight:600; font-size:0.9rem;">OTHIL</div>
    <h1 style="margin:0; color:#1B4332; font-size:1.6rem;">Área de Gerência</h1>
</div>
""", unsafe_allow_html=True)

if st.button('🔒 Sair', key='_gerencia_logout'):
    st.session_state['_gerencia_auth'] = False
    st.rerun()

st.divider()

# ── Dashboards Diários ────────────────────────────────────────────────────────
st.header('📊 Dashboards Diários')

dashboards = _listar_dashboards()

if dashboards:
    opcoes = {
        f"{m.get('emissao', slug)}  —  {m.get('periodo', '')}": slug
        for slug, m in dashboards
    }
    escolha_label = st.selectbox(
        f'{len(dashboards)} dashboard(s) salvos — selecione o dia:',
        list(opcoes.keys()),
    )
    slug_sel = opcoes[escolha_label]
    meta_sel = next(m for s, m in dashboards if s == slug_sel)

    gerado = meta_sel.get('gerado_em', '')[:16].replace('T', ' ')
    st.caption(f'Gerado em: {gerado}')

    html_path = os.path.join(_GERENCIA_DIR, f'dashboard_{slug_sel}.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        html_text = f.read()

    components.html(html_text, height=1400, scrolling=True)

    st.download_button(
        '⬇️ Baixar este dashboard (HTML)',
        data=html_text.encode('utf-8'),
        file_name=f'dashboard_othil_{slug_sel}.html',
        mime='text/html',
    )
else:
    st.info('Nenhum dashboard disponível. Gere um na página **Relatório Diário** primeiro.')

st.divider()

# ── Ranking de Clientes (Recorrência) ─────────────────────────────────────────
st.header('👥 Último Ranking de Clientes — Recorrência')

if os.path.exists(_REC_JSON):
    try:
        with open(_REC_JSON, 'r', encoding='utf-8') as f:
            rec = json.load(f)
    except Exception as e:
        st.error(f'Erro ao carregar dados de recorrência: {e}')
        rec = None

    if rec:
        periodo_r = rec.get('periodo', '-')
        emissao_r = rec.get('emissao', '-')
        gerado_r  = rec.get('gerado_em', '')[:16].replace('T', ' ')
        totais    = rec.get('totais', {})

        st.caption(f'Período: {periodo_r}  |  Emissão: {emissao_r}  |  Gerado em: {gerado_r}')

        if totais:
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric('Faturamento', f'R$ {totais.get("faturamento", 0):,.2f}')
            c2.metric('MC R$', f'R$ {totais.get("mc_rs", 0):,.2f}')
            c3.metric('MC %', f'{totais.get("mc_pct", 0):.2f}%')
            c4.metric('Total CX', f'{totais.get("caixas", 0):,.3f}')
            c5.metric('Clientes', totais.get('n_clientes', '-'))

        clientes = rec.get('clientes', [])
        if clientes:
            import pandas as pd

            df = pd.DataFrame(clientes)

            top30 = df.head(30).set_index('Cliente')[['Faturamento R$']]
            st.subheader('Top 30 por Faturamento')
            st.bar_chart(top30, color='#2D6A4F')

            st.subheader(f'Todos os clientes ({len(df)})')
            styled = df.style.format({
                'Faturamento R$': 'R$ {:,.2f}',
                'Caixas': '{:,.3f}',
                'MC R$': 'R$ {:,.2f}',
                'MC %': '{:.2f}%',
            }).background_gradient(
                subset=['Faturamento R$'], cmap='Greens'
            ).background_gradient(
                subset=['MC %'], cmap='RdYlGn', vmin=-30, vmax=30
            )
            st.dataframe(styled, use_container_width=True, hide_index=True)

            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                '⬇️ Baixar ranking CSV',
                data=csv,
                file_name=f'ranking_clientes_{emissao_r.replace("/","")}.csv',
                mime='text/csv',
            )
else:
    st.info('Nenhum ranking disponível. Processe um PDF na página **Recorrência** primeiro.')
