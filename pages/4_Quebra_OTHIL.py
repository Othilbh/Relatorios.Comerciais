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

    # Gráfico por categoria
    if categorias:
        st.subheader('Por Categoria de Produto')
        df_cat = pd.DataFrame(categorias).set_index('categoria')
        st.bar_chart(df_cat['cx'], color='#2D6A4F')

    # Tabela por grupo
    grupos = dados.get('grupos', [])
    if grupos:
        st.subheader('Por Grupo de Produto')
        df_g = pd.DataFrame(grupos)[['grupo', 'categoria', 'cx']]
        df_g.columns = ['Grupo', 'Categoria', 'CX Quebradas']
        st.dataframe(df_g, use_container_width=True, hide_index=True)

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


# ── Page ──────────────────────────────────────────────────────────────────────

st.title('📦 Quebras')
st.caption('Upload do relatório Resumo do Estoque filtrado por classificação QUEBRA.')

tab_s, tab_m = st.tabs(['📅 Semanal', '🗓️ Mensal'])

with tab_s:
    _render_tab('semanal', 'Semanal')

with tab_m:
    _render_tab('mensal', 'Mensal')
