"""OTHIL — Módulo de Quebras
Upload semanal/mensal do PDF de Quebra (Resumo do Estoque filtrado por QUEBRA).
Gera KPIs por grupo de produto e categoria, com histórico navegável.
"""
import os
import json
import datetime
import streamlit as st
import pandas as pd

from parser_quebra import parse_quebra

_QUEBRA_DIR = os.path.join(os.path.dirname(__file__), '..', 'gerencia_data', 'quebra')

_MESES = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']


# ── Storage ───────────────────────────────────────────────────────────────────

def _dir_tipo(tipo: str) -> str:
    d = os.path.join(_QUEBRA_DIR, tipo)
    os.makedirs(d, exist_ok=True)
    return d


def _slug_semanal(data: datetime.date) -> str:
    iso = data.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _slug_mensal(data: datetime.date) -> str:
    return f"{data.year}-{data.month:02d}"


def _label_slug(slug: str, tipo: str) -> str:
    try:
        if tipo == 'semanal':
            year, week = slug.split('-W')
            return f"Semana {int(week):02d} / {year}"
        elif tipo == 'mensal':
            year, mon = slug.split('-')
            return f"{_MESES[int(mon)-1]} / {year}"
    except Exception:
        pass
    return slug


def _salvar(dados: dict, tipo: str, slug: str):
    dados['slug'] = slug
    dados['tipo'] = tipo
    dados['gerado_em'] = datetime.datetime.now().isoformat()
    path = os.path.join(_dir_tipo(tipo), f"{slug}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def _listar(tipo: str) -> list[tuple[str, dict]]:
    d = _dir_tipo(tipo)
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


# ── Dashboard ─────────────────────────────────────────────────────────────────

def _render_dashboard(dados: dict, tipo: str, slug: str):
    total = dados.get('total_cx', 0)
    periodo = dados.get('periodo', '-')
    emissao = dados.get('emissao', '-')

    st.caption(f"Período: {periodo}  |  Emissão: {emissao}")

    # KPI principal
    col1, col2 = st.columns(2)
    col1.metric('Total CX Quebradas', f"{total:,.0f} cx")
    categorias = dados.get('categorias', [])
    if categorias:
        top_cat = categorias[0]
        col2.metric(
            f'Maior Categoria: {top_cat["categoria"]}',
            f"{top_cat['cx']:,.0f} cx"
        )

    # Filtro por categoria
    grupos = dados.get('grupos', [])
    categorias_disponiveis = sorted({g['categoria'] for g in grupos})

    cats_sel = st.multiselect(
        '🔍 Filtrar por categoria:',
        options=categorias_disponiveis,
        default=categorias_disponiveis,
        key=f'qbr_cat_filter_{slug}',
    )

    grupos_filtrados = [g for g in grupos if g['categoria'] in cats_sel] if cats_sel else []

    # Recalcula categorias com base no filtro
    cat_dict: dict[str, float] = {}
    for g in grupos_filtrados:
        cat_dict[g['categoria']] = cat_dict.get(g['categoria'], 0.0) + g['cx']
    categorias_filtradas = sorted(cat_dict.items(), key=lambda x: -x[1])

    # Gráfico por categoria
    if categorias_filtradas:
        st.subheader('Por Categoria de Produto')
        df_cat = pd.DataFrame(categorias_filtradas, columns=['categoria', 'cx']).set_index('categoria')
        st.bar_chart(df_cat['cx'], color='#2D6A4F')

    # Tabela por grupo
    if grupos_filtrados:
        st.subheader('Por Grupo de Produto')
        df_g = pd.DataFrame(grupos_filtrados)[['grupo', 'categoria', 'cx']]
        df_g.columns = ['Grupo', 'Categoria', 'CX Quebradas']
        st.dataframe(df_g, use_container_width=True, hide_index=True)
    elif cats_sel:
        st.info('Nenhum grupo encontrado para a seleção.')

    # Download JSON
    st.download_button(
        f'⬇️ Baixar dados ({_label_slug(slug, tipo)})',
        data=json.dumps(dados, ensure_ascii=False, indent=2).encode('utf-8'),
        file_name=f'quebra_{tipo}_{slug}_OTHIL.json',
        mime='application/json',
        key=f'dl_{tipo}_{slug}',
    )


# ── Tab ───────────────────────────────────────────────────────────────────────

def _render_tab(tipo: str, label_tipo: str):
    st.header(f'📋 {label_tipo}')

    with st.expander('📤 Enviar novo relatório', expanded=True):
        pdf_up = st.file_uploader(
            'PDF de Quebra (Resumo do Estoque)',
            type='pdf',
            key=f'qbr_{tipo}_pdf',
        )
        data_ref = st.date_input(
            'Data de referência (qualquer dia do período)',
            value=datetime.date.today(),
            key=f'qbr_{tipo}_data',
        )
        if pdf_up:
            if st.button('📊 Processar e Salvar', key=f'qbr_{tipo}_btn', type='primary'):
                with st.spinner('Processando PDF...'):
                    try:
                        dados = parse_quebra(pdf_up)
                        slug = _slug_semanal(data_ref) if tipo == 'semanal' else _slug_mensal(data_ref)
                        _salvar(dados, tipo, slug)
                        st.success(
                            f"✅ Salvo! {_label_slug(slug, tipo)} — "
                            f"{dados['total_cx']:,.0f} CX quebradas  |  "
                            f"Período: {dados.get('periodo', '-')}"
                        )
                        st.session_state[f'qbr_{tipo}_idx'] = 0
                        st.rerun()
                    except Exception as e:
                        st.error(f'Erro ao processar PDF: {e}')

    st.divider()

    # Histórico
    historico = _listar(tipo)
    if not historico:
        st.info('Nenhum relatório salvo ainda. Envie um PDF acima.')
        return

    slugs  = [s for s, _ in historico]
    labels = [
        f"{_label_slug(s, tipo)}  —  {m.get('periodo', '-')}"
        for s, m in historico
    ]

    idx_key = f'qbr_{tipo}_idx'
    if idx_key not in st.session_state:
        st.session_state[idx_key] = 0

    col_prev, col_sel, col_next = st.columns([1, 6, 1])
    with col_prev:
        st.write('')
        if st.button('◀', key=f'qbr_prev_{tipo}', help='Período anterior'):
            st.session_state[idx_key] = min(st.session_state[idx_key] + 1, len(slugs) - 1)
    with col_next:
        st.write('')
        if st.button('▶', key=f'qbr_next_{tipo}', help='Próximo período'):
            st.session_state[idx_key] = max(st.session_state[idx_key] - 1, 0)
    with col_sel:
        escolha = st.selectbox(
            f'{len(historico)} período(s) salvo(s):',
            labels,
            index=min(st.session_state[idx_key], len(labels) - 1),
            key=f'qbr_sel_{tipo}',
        )
        st.session_state[idx_key] = labels.index(escolha)

    idx = st.session_state[idx_key]
    slug_sel = slugs[idx]
    dados_sel = historico[idx][1]

    _render_dashboard(dados_sel, tipo, slug_sel)


# ── Comparativo ───────────────────────────────────────────────────────────────

def _render_comparativo():
    st.header('🔀 Comparativo entre Períodos')

    tipo = st.radio(
        'Tipo de período:',
        ['semanal', 'mensal'],
        format_func=lambda x: 'Semanal' if x == 'semanal' else 'Mensal',
        horizontal=True,
        key='comp_tipo',
    )

    historico = _listar(tipo)
    if len(historico) < 2:
        st.info('Necessário ter pelo menos 2 períodos salvos para comparar. Envie mais PDFs nas abas Semanal ou Mensal.')
        return

    slugs  = [s for s, _ in historico]
    labels = [f"{_label_slug(s, tipo)}  —  {m.get('periodo', '-')}" for s, m in historico]

    col_a, col_b = st.columns(2)
    with col_a:
        escolha_a = st.selectbox('Período A (base):', labels, index=0, key='comp_sel_a')
    with col_b:
        # Default: segundo período mais recente
        default_b = 1 if len(labels) > 1 else 0
        escolha_b = st.selectbox('Período B (comparar):', labels, index=default_b, key='comp_sel_b')

    if escolha_a == escolha_b:
        st.warning('Selecione períodos diferentes para comparar.')
        return

    idx_a = labels.index(escolha_a)
    idx_b = labels.index(escolha_b)
    dados_a = historico[idx_a][1]
    dados_b = historico[idx_b][1]
    label_a = _label_slug(slugs[idx_a], tipo)
    label_b = _label_slug(slugs[idx_b], tipo)

    st.divider()

    # ── KPIs totais ───────────────────────────────────────────────────────
    total_a = dados_a.get('total_cx', 0)
    total_b = dados_b.get('total_cx', 0)
    delta   = total_b - total_a
    delta_pct = (delta / total_a * 100) if total_a else 0

    c1, c2, c3 = st.columns(3)
    c1.metric(f'Total CX — {label_a}', f"{total_a:,.0f} cx")
    c2.metric(f'Total CX — {label_b}', f"{total_b:,.0f} cx")
    c3.metric(
        'Variação (B − A)',
        f"{delta:+,.0f} cx",
        delta=f"{delta_pct:+.1f}%",
        delta_color='inverse',   # vermelho = mais quebra = ruim
    )

    st.divider()

    # ── Comparativo por categoria ─────────────────────────────────────────
    st.subheader('Por Categoria de Produto')

    cat_a = {c['categoria']: c['cx'] for c in dados_a.get('categorias', [])}
    cat_b = {c['categoria']: c['cx'] for c in dados_b.get('categorias', [])}
    todas_cats = sorted(set(cat_a) | set(cat_b))

    df_comp = pd.DataFrame({
        label_a: [cat_a.get(c, 0) for c in todas_cats],
        label_b: [cat_b.get(c, 0) for c in todas_cats],
    }, index=todas_cats)

    st.bar_chart(df_comp, color=['#2D6A4F', '#74C69D'])

    # Tabela categoria com delta
    df_cat_tbl = df_comp.copy()
    df_cat_tbl['Δ (B − A)'] = df_cat_tbl[label_b] - df_cat_tbl[label_a]
    df_cat_tbl['Δ %'] = df_cat_tbl.apply(
        lambda r: f"{r['Δ (B − A)'] / r[label_a] * 100:+.1f}%" if r[label_a] else '—',
        axis=1,
    )
    df_cat_tbl = df_cat_tbl.reset_index().rename(columns={'index': 'Categoria'})
    df_cat_tbl[label_a]      = df_cat_tbl[label_a].map(lambda x: f"{x:,.0f}")
    df_cat_tbl[label_b]      = df_cat_tbl[label_b].map(lambda x: f"{x:,.0f}")
    df_cat_tbl['Δ (B − A)']  = df_cat_tbl['Δ (B − A)'].map(lambda x: f"{x:+,.0f}")
    st.dataframe(df_cat_tbl, use_container_width=True, hide_index=True)

    st.divider()

    # ── Comparativo por grupo ─────────────────────────────────────────────
    st.subheader('Por Grupo de Produto')

    grp_a = {g['grupo']: g for g in dados_a.get('grupos', [])}
    grp_b = {g['grupo']: g for g in dados_b.get('grupos', [])}
    todos_grps = sorted(set(grp_a) | set(grp_b))

    rows = []
    for grp in todos_grps:
        ga = grp_a.get(grp, {})
        gb = grp_b.get(grp, {})
        cx_a = ga.get('cx', 0)
        cx_b = gb.get('cx', 0)
        dif  = cx_b - cx_a
        cat  = ga.get('categoria') or gb.get('categoria', '—')
        rows.append({
            'Grupo':        grp,
            'Categoria':    cat,
            label_a:        cx_a,
            label_b:        cx_b,
            'Δ (B − A)':   dif,
        })

    df_grp = pd.DataFrame(rows).sort_values('Δ (B − A)', ascending=False)
    df_grp_fmt = df_grp.copy()
    df_grp_fmt[label_a]     = df_grp_fmt[label_a].map(lambda x: f"{x:,.0f}")
    df_grp_fmt[label_b]     = df_grp_fmt[label_b].map(lambda x: f"{x:,.0f}")
    df_grp_fmt['Δ (B − A)'] = df_grp_fmt['Δ (B − A)'].map(lambda x: f"{x:+,.0f}")
    st.dataframe(df_grp_fmt, use_container_width=True, hide_index=True)


# ── Page ──────────────────────────────────────────────────────────────────────

st.title('📦 Quebras')
st.caption('Upload do relatório Resumo do Estoque filtrado por classificação QUEBRA.')

tab_s, tab_m, tab_comp = st.tabs(['📅 Semanal', '🗓️ Mensal', '🔀 Comparativo'])

with tab_s:
    _render_tab('semanal', 'Semanal')

with tab_m:
    _render_tab('mensal', 'Mensal')

with tab_comp:
    _render_comparativo()
