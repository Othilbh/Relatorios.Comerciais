"""Página de Gerência OTHIL — acesso restrito por senha."""
import json
import os
import re
import datetime

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

_GERENCIA_DIR  = os.path.join(os.path.dirname(__file__), '..', 'gerencia_data')
_QUEBRA_DIR    = os.path.join(_GERENCIA_DIR, 'quebra')
_MESES_QBR     = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']
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


def _dir_tipo(tipo):
    d = os.path.join(_GERENCIA_DIR, tipo)
    os.makedirs(d, exist_ok=True)
    return d


def _listar_dashboards(tipo):
    d = _dir_tipo(tipo)
    items = []
    for fname in os.listdir(d):
        if fname.endswith('.json'):
            try:
                with open(os.path.join(d, fname), 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                slug = meta.get('slug') or fname.replace('.json', '')
                if os.path.exists(os.path.join(d, f'{slug}.html')):
                    items.append((slug, meta))
            except Exception:
                pass
    items.sort(key=lambda x: x[0], reverse=True)
    return items


def _label_slug(slug, tipo):
    try:
        if tipo == 'semanal':
            year, week = slug.split('-W')
            return f'Semana {int(week):02d} / {year}'
        elif tipo == 'mensal':
            year, mon = slug.split('-')
            meses = ['Jan','Fev','Mar','Abr','Mai','Jun',
                     'Jul','Ago','Set','Out','Nov','Dez']
            return f'{meses[int(mon)-1]} / {year}'
        else:
            return slug
    except Exception:
        return slug


def _render_secao_dash(tipo, titulo_secao, emoji):
    st.header(f'{emoji} {titulo_secao}')
    dashboards = _listar_dashboards(tipo)

    if not dashboards:
        tipo_label = {'diario': 'Relatório Diário', 'semanal': 'aba Semanal', 'mensal': 'aba Mensal'}
        st.info(f'Nenhum dashboard disponível. Gere um na página **{tipo_label.get(tipo,tipo)}** primeiro.')
        return

    slugs  = [s for s, _ in dashboards]
    if tipo == 'diario':
        labels = [f"{m.get('emissao', s)}  —  {m.get('periodo','-')}" for s, m in dashboards]
    else:
        labels = [_label_slug(s, tipo) + f"  ({m.get('periodo','-')})" for s, m in dashboards]

    idx_key = f'_ger_idx_{tipo}'
    if idx_key not in st.session_state:
        st.session_state[idx_key] = 0

    col_prev, col_sel, col_next = st.columns([1, 6, 1])
    with col_prev:
        st.write('')
        if st.button('◀', key=f'ger_prev_{tipo}', help='Período anterior'):
            st.session_state[idx_key] = min(st.session_state[idx_key] + 1, len(slugs) - 1)
    with col_next:
        st.write('')
        if st.button('▶', key=f'ger_next_{tipo}', help='Próximo período'):
            st.session_state[idx_key] = max(st.session_state[idx_key] - 1, 0)
    with col_sel:
        escolha = st.selectbox(
            f'{len(dashboards)} período(s) salvo(s):',
            labels,
            index=min(st.session_state[idx_key], len(labels)-1),
            key=f'ger_sel_{tipo}',
        )
        st.session_state[idx_key] = labels.index(escolha)

    idx     = st.session_state[idx_key]
    slug_h  = slugs[idx]
    meta_h  = dashboards[idx][1]
    gerado  = meta_h.get('gerado_em', '')[:16].replace('T', ' ')
    st.caption(f'Período: {meta_h.get("periodo","-")}  |  Gerado em: {gerado}')

    html_path = os.path.join(_dir_tipo(tipo), f'{slug_h}.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        html_text = f.read()

    components.html(html_text, height=1400, scrolling=True)
    st.download_button(
        f'⬇️ Baixar {_label_slug(slug_h, tipo) if tipo != "diario" else slug_h}',
        data=html_text.encode('utf-8'),
        file_name=f'dashboard_{tipo}_{slug_h}_OTHIL.html',
        mime='text/html',
        key=f'ger_dl_{tipo}',
    )


# ── Quebra helpers ────────────────────────────────────────────────────────────

def _qbr_dir(tipo: str) -> str:
    d = os.path.join(_QUEBRA_DIR, tipo)
    os.makedirs(d, exist_ok=True)
    return d


def _qbr_label(slug: str, tipo: str) -> str:
    try:
        if tipo == 'semanal':
            year, week = slug.split('-W')
            return f"Semana {int(week):02d} / {year}"
        elif tipo == 'mensal':
            year, mon = slug.split('-')
            return f"{_MESES_QBR[int(mon)-1]} / {year}"
    except Exception:
        pass
    return slug


def _qbr_listar(tipo: str) -> list:
    d = _qbr_dir(tipo)
    items = []
    for fname in sorted(os.listdir(d), reverse=True):
        if not fname.endswith('.json'):
            continue
        try:
            with open(os.path.join(d, fname), 'r', encoding='utf-8') as f:
                meta = json.load(f)
            items.append((fname.replace('.json', ''), meta))
        except Exception:
            pass
    return items


def _render_quebra_comparativo():
    st.header('🔀 Comparativo de Quebras')

    tipo = st.radio(
        'Tipo de período:',
        ['semanal', 'mensal'],
        format_func=lambda x: 'Semanal' if x == 'semanal' else 'Mensal',
        horizontal=True,
        key='ger_comp_tipo',
    )

    historico = _qbr_listar(tipo)
    if len(historico) < 2:
        st.info('Necessário ter pelo menos 2 períodos salvos para comparar.')
        return

    slugs  = [s for s, _ in historico]
    labels = [f"{_qbr_label(s, tipo)}  —  {m.get('periodo', '-')}" for s, m in historico]

    col_a, col_b = st.columns(2)
    with col_a:
        escolha_a = st.selectbox('Período A (base):', labels, index=0, key='ger_comp_sel_a')
    with col_b:
        default_b = 1 if len(labels) > 1 else 0
        escolha_b = st.selectbox('Período B (comparar):', labels, index=default_b, key='ger_comp_sel_b')

    if escolha_a == escolha_b:
        st.warning('Selecione períodos diferentes para comparar.')
        return

    dados_a = historico[labels.index(escolha_a)][1]
    dados_b = historico[labels.index(escolha_b)][1]
    label_a = _qbr_label(slugs[labels.index(escolha_a)], tipo)
    label_b = _qbr_label(slugs[labels.index(escolha_b)], tipo)

    st.divider()

    total_a = dados_a.get('total_cx', 0)
    total_b = dados_b.get('total_cx', 0)
    delta   = total_b - total_a
    delta_pct = (delta / total_a * 100) if total_a else 0

    c1, c2, c3 = st.columns(3)
    c1.metric(f'Total CX — {label_a}', f"{total_a:,.0f} cx")
    c2.metric(f'Total CX — {label_b}', f"{total_b:,.0f} cx")
    c3.metric('Variação (B − A)', f"{delta:+,.0f} cx",
              delta=f"{delta_pct:+.1f}%", delta_color='inverse')

    st.divider()
    st.subheader('Por Categoria de Produto')

    cat_a = {c['categoria']: c['cx'] for c in dados_a.get('categorias', [])}
    cat_b = {c['categoria']: c['cx'] for c in dados_b.get('categorias', [])}
    todas_cats = sorted(set(cat_a) | set(cat_b))

    df_comp = pd.DataFrame({
        label_a: [cat_a.get(c, 0) for c in todas_cats],
        label_b: [cat_b.get(c, 0) for c in todas_cats],
    }, index=todas_cats)
    st.bar_chart(df_comp, color=['#2D6A4F', '#74C69D'])

    df_cat_tbl = df_comp.copy()
    df_cat_tbl['Δ (B − A)'] = df_cat_tbl[label_b] - df_cat_tbl[label_a]
    df_cat_tbl['Δ %'] = df_cat_tbl.apply(
        lambda r: f"{r['Δ (B − A)'] / r[label_a] * 100:+.1f}%" if r[label_a] else '—', axis=1)
    df_cat_tbl = df_cat_tbl.reset_index().rename(columns={'index': 'Categoria'})
    df_cat_tbl[label_a]     = df_cat_tbl[label_a].map(lambda x: f"{x:,.0f}")
    df_cat_tbl[label_b]     = df_cat_tbl[label_b].map(lambda x: f"{x:,.0f}")
    df_cat_tbl['Δ (B − A)'] = df_cat_tbl['Δ (B − A)'].map(lambda x: f"{x:+,.0f}")
    st.dataframe(df_cat_tbl, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader('Por Grupo de Produto')

    grp_a = {g['grupo']: g for g in dados_a.get('grupos', [])}
    grp_b = {g['grupo']: g for g in dados_b.get('grupos', [])}
    rows = []
    for grp in sorted(set(grp_a) | set(grp_b)):
        ga, gb = grp_a.get(grp, {}), grp_b.get(grp, {})
        cx_a, cx_b = ga.get('cx', 0), gb.get('cx', 0)
        rows.append({
            'Grupo':     grp,
            'Categoria': ga.get('categoria') or gb.get('categoria', '—'),
            label_a:     cx_a,
            label_b:     cx_b,
            'Δ (B − A)': cx_b - cx_a,
        })

    df_grp = pd.DataFrame(rows).sort_values('Δ (B − A)', ascending=False)
    df_grp[label_a]     = df_grp[label_a].map(lambda x: f"{x:,.0f}")
    df_grp[label_b]     = df_grp[label_b].map(lambda x: f"{x:,.0f}")
    df_grp['Δ (B − A)'] = df_grp['Δ (B − A)'].map(lambda x: f"{x:+,.0f}")
    st.dataframe(df_grp, use_container_width=True, hide_index=True)


def _render_quebra_secao(tipo: str, titulo: str, emoji: str):
    st.header(f'{emoji} {titulo}')
    historico = _qbr_listar(tipo)
    if not historico:
        st.info(f'Nenhum relatório de quebra disponível. Envie um PDF na página **Quebras** primeiro.')
        return

    slugs  = [s for s, _ in historico]
    labels = [f"{_qbr_label(s, tipo)}  —  {m.get('periodo', '-')}" for s, m in historico]

    idx_key = f'_ger_qbr_idx_{tipo}'
    if idx_key not in st.session_state:
        st.session_state[idx_key] = 0

    col_prev, col_sel, col_next = st.columns([1, 6, 1])
    with col_prev:
        st.write('')
        if st.button('◀', key=f'ger_qbr_prev_{tipo}'):
            st.session_state[idx_key] = min(st.session_state[idx_key] + 1, len(slugs) - 1)
    with col_next:
        st.write('')
        if st.button('▶', key=f'ger_qbr_next_{tipo}'):
            st.session_state[idx_key] = max(st.session_state[idx_key] - 1, 0)
    with col_sel:
        escolha = st.selectbox(
            f'{len(historico)} período(s) salvo(s):',
            labels,
            index=min(st.session_state[idx_key], len(labels) - 1),
            key=f'ger_qbr_sel_{tipo}',
        )
        st.session_state[idx_key] = labels.index(escolha)

    idx = st.session_state[idx_key]
    slug_sel = slugs[idx]
    dados = historico[idx][1]

    st.caption(f'Período: {dados.get("periodo", "-")}  |  Emissão: {dados.get("emissao", "-")}')

    total = dados.get('total_cx', 0)
    categorias = dados.get('categorias', [])
    grupos = dados.get('grupos', [])

    col1, col2 = st.columns(2)
    col1.metric('Total CX Quebradas', f"{total:,.0f} cx")
    if categorias:
        top = categorias[0]
        col2.metric(f'Maior: {top["categoria"]}', f"{top['cx']:,.0f} cx")

    if categorias:
        df_cat = pd.DataFrame(categorias).set_index('categoria')
        st.bar_chart(df_cat['cx'], color='#2D6A4F')

    if grupos:
        df_g = pd.DataFrame(grupos)[['grupo', 'categoria', 'cx']]
        df_g.columns = ['Grupo', 'Categoria', 'CX Quebradas']
        st.dataframe(df_g, use_container_width=True, hide_index=True)


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

# ── Abas ─────────────────────────────────────────────────────────────────────
tab_d, tab_s, tab_m, tab_rec, tab_qbr_s, tab_qbr_m, tab_qbr_comp = st.tabs([
    '📅 Dashboards Diários',
    '📆 Dashboards Semanais',
    '🗓️ Dashboards Mensais',
    '👥 Ranking Recorrência',
    '📦 Quebras Semanais',
    '📦 Quebras Mensais',
    '🔀 Quebras Comparativo',
])

with tab_d:
    _render_secao_dash('diario', 'Dashboards Diários', '📅')

with tab_s:
    _render_secao_dash('semanal', 'Dashboards Semanais', '📆')

with tab_m:
    _render_secao_dash('mensal', 'Dashboards Mensais', '🗓️')

with tab_rec:
    st.header('👥 Último Ranking de Clientes — Recorrência')
    _REC_JSON = os.path.join(_GERENCIA_DIR, 'recorrencia_latest.json')
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
                })
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

with tab_qbr_s:
    _render_quebra_secao('semanal', 'Quebras Semanais', '📦')

with tab_qbr_m:
    _render_quebra_secao('mensal', 'Quebras Mensais', '📦')

with tab_qbr_comp:
    _render_quebra_comparativo()
