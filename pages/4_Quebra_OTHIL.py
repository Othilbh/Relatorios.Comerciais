"""OTHIL — Módulo de Quebras
Upload semanal/mensal do PDF de Quebra (Resumo do Estoque filtrado por QUEBRA).
Gera KPIs por grupo de produto e categoria, com histórico navegável.
"""
import io
import os
import json
import datetime
import streamlit as st
import pandas as pd

from parser_quebra import parse_quebra
import acesso
import comparativo
import data_store as ds
import metas_gerais as mg
import periodo as periodo_mod

def _fmt_num(v, casas=0):
    return f"{v:,.{casas}f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def _fmt_moeda(v):
    return f"R$ {_fmt_num(v, 2)}"


MODULO = 'quebra'

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


def _salvar(dados: dict, tipo: str, slug: str, usuario: str = None):
    dados['slug'] = slug
    dados['tipo'] = tipo
    dados['gerado_em'] = datetime.datetime.now().isoformat()
    path = os.path.join(_dir_tipo(tipo), f"{slug}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    # Persistência real e versionada (sobrevive a restart do Streamlit Cloud;
    # antes só existia em gerencia_data/, que é apagado a cada restart)
    try:
        ds.save_record(modulo=MODULO, tipo_periodo=tipo, periodo_ref=slug,
                        valores=dados, usuario=usuario)
    except Exception as e:
        st.warning(f'Salvo localmente, mas houve um problema ao salvar de forma permanente: {e}')


def _listar(tipo: str) -> list[tuple[str, dict]]:
    """Lista os períodos salvos, mais recente primeiro. Lê da persistência
    real (data_store) primeiro; arquivos locais entram como complemento
    (períodos salvos antes desta migração, ou se a gravação remota falhar)."""
    items = {}
    try:
        for slug in ds.list_periodos(MODULO, tipo):
            registro = ds.load_current(MODULO, tipo, slug)
            if registro:
                items[slug] = registro['valores']
    except Exception:
        pass

    d = _dir_tipo(tipo)
    for fname in os.listdir(d):
        if not fname.endswith('.json'):
            continue
        slug = fname.replace('.json', '')
        if slug in items:
            continue
        try:
            with open(os.path.join(d, fname), 'r', encoding='utf-8') as f:
                items[slug] = json.load(f)
        except Exception:
            pass

    return sorted(items.items(), key=lambda kv: kv[0], reverse=True)


# ── Dashboard ─────────────────────────────────────────────────────────────────

def _render_dashboard(dados: dict, tipo: str, slug: str, dados_ant: dict = None, label_ant: str = None):
    total = dados.get('total_cx', 0)
    periodo = dados.get('periodo', '-')
    emissao = dados.get('emissao', '-')

    st.caption(f"Período: {periodo}  |  Emissão: {emissao}")

    # KPI principal
    col1, col2 = st.columns(2)
    col1.metric('Total CX Quebradas', f"{_fmt_num(total, 0)} cx")
    categorias = dados.get('categorias', [])
    if categorias:
        top_cat = categorias[0]
        col2.metric(
            f'Maior Categoria: {top_cat["categoria"]}',
            f"{_fmt_num(top_cat['cx'], 0)} cx"
        )

    # ── Comparativo automático vs período anterior salvo (menor é melhor)
    if dados_ant is not None:
        st.divider()
        total_ant = dados_ant.get('total_cx', 0)
        comp_auto = comparativo.calcular(total, total_ant, menor_e_melhor=True)
        st.metric(
            f'📊 vs período anterior ({label_ant})',
            f"{_fmt_num(total, 0)} cx",
            delta=comparativo.formatar_variacao(comp_auto, casas=1),
            delta_color='inverse',
        )

    st.divider()

    # Filtro + gráfico + tabela + download agrupados visualmente: o filtro
    # de categoria abaixo controla tudo dentro deste container.
    with st.container(border=True):
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

        st.divider()

        # Gráfico por categoria
        if categorias_filtradas:
            st.subheader('Por Categoria de Produto')
            df_cat = pd.DataFrame(categorias_filtradas, columns=['categoria', 'cx']).set_index('categoria')
            st.bar_chart(df_cat['cx'], color='#2D6A4F')

        st.divider()

        # Tabela por grupo
        if grupos_filtrados:
            st.subheader('Por Grupo de Produto')
            df_g = pd.DataFrame(grupos_filtrados)[['grupo', 'categoria', 'cx']]
            df_g.columns = ['Grupo', 'Categoria', 'CX Quebradas']
            st.dataframe(df_g, use_container_width=True, hide_index=True)
        elif cats_sel:
            st.info('Nenhum grupo encontrado para a seleção.')

        # Download JSON — respeita o filtro de categoria aplicado na tela (antes
        # a exportação sempre baixava os dados completos, ignorando o filtro)
        dados_export = dict(dados)
        dados_export['grupos'] = grupos_filtrados
        dados_export['categorias'] = [{'categoria': c, 'cx': v} for c, v in categorias_filtradas]
        dados_export['total_cx'] = sum(g['cx'] for g in grupos_filtrados)
        dados_export['filtro_categorias_aplicado'] = cats_sel
        dados_export['gerado_em_exportacao'] = datetime.datetime.now().isoformat(timespec='seconds')
        st.download_button(
            f'⬇️ Baixar dados filtrados ({_label_slug(slug, tipo)})',
            data=json.dumps(dados_export, ensure_ascii=False, indent=2).encode('utf-8'),
            file_name=f'quebra_{tipo}_{slug}_OTHIL.json',
            mime='application/json',
            key=f'dl_{tipo}_{slug}',
        )


# ── Tab ───────────────────────────────────────────────────────────────────────

def _render_tab(tipo: str, label_tipo: str):
    st.header(f'📋 {label_tipo}')

    st.subheader('📤 Enviar novo relatório')
    st.caption('PDF de Quebra (Resumo do Estoque, classificação QUEBRA).')
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
                    _salvar(dados, tipo, slug, usuario=st.session_state.get('usuario_nome'))
                    st.success(
                        f"✅ Salvo! {_label_slug(slug, tipo)} — "
                        f"{_fmt_num(dados['total_cx'], 0)} CX quebradas  |  "
                        f"Período: {dados.get('periodo', '-')}"
                    )
                    st.session_state[f'qbr_{tipo}_idx'] = 0
                    # Fluxo Upload -> Gerência (pedido da Ingrid, 27/08/2026):
                    # nunca fica numa tela de Dashboard depois de enviar o PDF.
                    acesso.redirecionar_pos_upload()
                except Exception as e:
                    st.error(f'Erro ao processar PDF: {e}')

    # Perfil de upload (27/08/2026, pedido da Ingrid): nunca vê o
    # histórico/dashboard de Quebra aqui -- só na Gerência. SEMPRE
    # bloqueado, independente de já ter processado um PDF ou não nesta
    # sessão.
    #
    # Usa deve_esconder_apos_upload() em vez de parar_se_upload() aqui --
    # mesmo bug real encontrado em 29/08/2026 (e corrigido do mesmo jeito
    # em 1_Relatorio_Diario_OTHIL.py): esta página tem 3 abas
    # (Semanal/Mensal/Comparativo), e _render_tab() é compartilhada pelas
    # duas primeiras. parar_se_upload() usa st.stop(), que mata o script
    # INTEIRO -- ao rodar a aba Semanal (que vem antes das outras no
    # código), o st.stop() impedia as abas Mensal e Comparativo de sequer
    # aparecerem (nem o uploader delas).
    if not acesso.deve_esconder_apos_upload():
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

        col_prev, col_sel, col_next = st.columns([1, 6, 1], vertical_alignment='bottom')
        with col_prev:
            if st.button('◀', key=f'qbr_prev_{tipo}', help='Período anterior'):
                st.session_state[idx_key] = min(st.session_state[idx_key] + 1, len(slugs) - 1)
        with col_next:
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
        dados_ant = historico[idx + 1][1] if idx + 1 < len(historico) else None
        label_ant = _label_slug(slugs[idx + 1], tipo) if idx + 1 < len(historico) else None

        _render_dashboard(dados_sel, tipo, slug_sel, dados_ant=dados_ant, label_ant=label_ant)


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

    # ── KPIs totais (componente central comparativo.py — Quebra é um
    # indicador onde MENOR é melhor) ───────────────────────────────────────
    total_a = dados_a.get('total_cx', 0)
    total_b = dados_b.get('total_cx', 0)
    comp = comparativo.calcular(total_b, total_a, menor_e_melhor=True)

    c1, c2, c3 = st.columns(3)
    c1.metric(f'Total CX — {label_a}', f"{_fmt_num(total_a, 0)} cx")
    c2.metric(f'Total CX — {label_b}', f"{_fmt_num(total_b, 0)} cx")
    c3.metric(
        'Variação (B − A)',
        f"{'+' if comp['diferenca_absoluta'] >= 0 else ''}{_fmt_num(comp['diferenca_absoluta'], 0)} cx",
        delta=comparativo.formatar_variacao(comp, casas=1),
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
    df_cat_tbl[label_a]      = df_cat_tbl[label_a].map(lambda x: _fmt_num(x, 0))
    df_cat_tbl[label_b]      = df_cat_tbl[label_b].map(lambda x: _fmt_num(x, 0))
    df_cat_tbl['Δ (B − A)']  = df_cat_tbl['Δ (B − A)'].map(
        lambda x: f"{'+' if x >= 0 else ''}{_fmt_num(x, 0)}")
    st.dataframe(df_cat_tbl, use_container_width=True, hide_index=True)

    st.divider()

    # ── Comparativo por grupo ─────────────────────────────────────────────
    st.subheader('Por Grupo de Produto')
    # Sem gráfico aqui de propósito: "grupo" é bem mais granular que
    # "categoria" (dezenas de grupos por período, contra ~20 categorias
    # fixas em categorias.py), então uma barra por grupo ficaria ilegível.
    st.caption('Gráfico omitido aqui — muitos grupos tornariam a barra ilegível; veja a tabela abaixo.')

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

    if not rows:
        st.info('Nenhum grupo de produto registrado nesses dois períodos.')
    else:
        df_grp = pd.DataFrame(rows).sort_values('Δ (B − A)', ascending=False)
        df_grp_fmt = df_grp.copy()
        df_grp_fmt[label_a]     = df_grp_fmt[label_a].map(lambda x: _fmt_num(x, 0))
        df_grp_fmt[label_b]     = df_grp_fmt[label_b].map(lambda x: _fmt_num(x, 0))
        df_grp_fmt['Δ (B − A)'] = df_grp_fmt['Δ (B − A)'].map(
            lambda x: f"{'+' if x >= 0 else ''}{_fmt_num(x, 0)}")
        st.dataframe(df_grp_fmt, use_container_width=True, hide_index=True)


# ── Page ──────────────────────────────────────────────────────────────────────

st.title('📦 Quebras')
st.caption('Upload do relatório Resumo do Estoque filtrado por classificação QUEBRA.')

st.session_state.setdefault('usuario_nome', 'Ingrid')

tab_s, tab_m, tab_comp = st.tabs(['📅 Semanal', '🗓️ Mensal', '🔀 Comparativo'])

with tab_s:
    _render_tab('semanal', 'Semanal')

with tab_m:
    _render_tab('mensal', 'Mensal')

    st.divider()

    # ── Meta Geral — Realizado (Quebra) ──────────────────────────────────────
    # Publica DIRETO no painel "🌐 Meta Geral" da Gerência -- pedido explícito
    # da Ingrid, 29/08/2026 ("o mesmo para a quebra"): mesmo tipo de PDF do
    # envio Mensal acima, mas publicação INDEPENDENTE (metas_gerais.
    # MOD_MG_QUEBRA -- não depende de ter sido salvo acima, e o envio Mensal
    # acima não alimenta isto). Movido pra cá em 03/09/2026, pedido da
    # Ingrid: "na gerência não é para ficar upload de nada, apenas os
    # resultados -- upload são todos nos módulos" (antes ficava dentro da
    # própria Gerência). O resultado publicado aqui só aparece na aba
    # "🌐 Meta Geral" da Gerência, nunca nesta página -- mesma política de
    # acesso de 27/08/2026 (ver acesso.py).
    with st.expander('📤 Publicar Realizado da Meta Geral (Quebra)'):
        st.caption(
            'Sobe o mesmo tipo de PDF (Resumo do Estoque, classificação QUEBRA) do envio '
            'Mensal acima, mas publica DIRETO na Meta Geral (Gerência) -- independente do '
            'envio Mensal acima.'
        )
        pdf_mg_q = st.file_uploader('PDF Resumo do Estoque (Quebra)', type='pdf', key='mg_q_upload')
        if pdf_mg_q is not None:
            _raw_mg_q = pdf_mg_q.getvalue()
            try:
                _prev_mg_q = parse_quebra(io.BytesIO(_raw_mg_q))
            except Exception as _e_prev_q:
                st.error(f'Não foi possível ler este PDF: {_e_prev_q}')
                _prev_mg_q = None
            if _prev_mg_q is not None:
                puc1, puc2 = st.columns(2)
                puc1.metric('CX quebradas no PDF', _fmt_num(_prev_mg_q.get('total_cx', 0), 0))
                puc2.metric('Custo no PDF',
                            _fmt_moeda(_prev_mg_q['total_custo'])
                            if _prev_mg_q.get('total_custo') is not None else '—')

                _mes_detect_q = mg.mes_do_periodo_pdf(
                    _prev_mg_q.get('periodo'), _prev_mg_q.get('emissao'))
                _opcoes_mes_q = periodo_mod.listar_periodos('mensal', n=15)
                if _mes_detect_q not in _opcoes_mes_q:
                    _opcoes_mes_q = sorted(set(_opcoes_mes_q) | {_mes_detect_q}, reverse=True)
                _mes_escolhido_q = st.selectbox(
                    'Mês de referência (Meta Geral)', _opcoes_mes_q,
                    index=_opcoes_mes_q.index(_mes_detect_q),
                    format_func=lambda r: periodo_mod.rotulo('mensal', r), key='mg_q_mes_sel',
                    help=f"Detectado pelo período do PDF "
                         f"({_prev_mg_q.get('periodo') or _prev_mg_q.get('emissao') or '?'}). "
                         f"Corrija aqui se necessário.",
                )
                if st.button('📊 Processar e publicar na Meta Geral', key='mg_q_btn'):
                    with st.spinner('Publicando...'):
                        try:
                            _reg_mg_q = mg.publicar_quebra_pdf(
                                _mes_escolhido_q, io.BytesIO(_raw_mg_q),
                                usuario=st.session_state.get('usuario_nome'))
                            _erro_mg_q = _reg_mg_q.get('_erro_persistencia_remota') if _reg_mg_q else None
                            if _erro_mg_q:
                                st.warning(
                                    f'Publicado localmente, mas houve um problema ao salvar de '
                                    f'forma permanente: {_erro_mg_q}')
                            else:
                                st.success(
                                    f"✅ Publicado na Meta Geral -- "
                                    f"{periodo_mod.rotulo('mensal', _mes_escolhido_q)}.")
                            acesso.redirecionar_pos_upload()
                        except Exception as _e_pub_q:
                            st.error(f'Erro ao publicar: {_e_pub_q}')

with tab_comp:
    _render_comparativo()
