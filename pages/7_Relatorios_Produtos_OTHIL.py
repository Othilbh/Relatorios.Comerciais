"""OTHIL — Relatórios de Produtos (Projeto 2)

Análise de desempenho, vendas, faturamento e evolução dos produtos.
Reaproveita 100% a base histórica consolidada de rentabilidade.py/
produtos.py (mesma fonte de dados do Relatório Diário/Semanal/Mensal, já
sem duplicidade entre uploads) -- nenhuma lógica de faturamento, custo ou
consolidação de período foi duplicada aqui.
"""
import io

import pandas as pd
import streamlit as st

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import comparativo
import data_store as ds
import periodo as periodo_mod
import produtos as pr

MODULO = 'relatorios_produtos'


# ── Formatação (padrão brasileiro, igual às demais páginas) ─────────────────

def _brl(v):
    v = v or 0.0
    s = f"{abs(v):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"R$ {'-' if v < 0 else ''}{s}"


def _pct(v):
    v = v or 0.0
    s = f"{v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"{s}%"


def _qtd(v):
    v = v or 0.0
    s = f"{v:,.3f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return s


_COLS_LABELS = {
    'faturamento': 'Faturamento R$', 'custo': 'Custo R$', 'margem_rs': 'Margem R$',
    'margem_pct': 'Margem %', 'volume': 'Volume (cx)', 'clientes': 'Clientes',
    'ticket_medio': 'Ticket Médio', 'categoria': 'Categoria',
    'participacao_faturamento': '% do Faturamento', 'participacao_margem': '% da Margem',
}


def _tabela_dim(linhas, nome_chave, colunas=None):
    if not linhas:
        return pd.DataFrame()
    df = pd.DataFrame(linhas).rename(columns={'chave': nome_chave, **_COLS_LABELS})
    if colunas:
        df = df[[c for c in colunas if c in df.columns]]
    df.insert(0, '#', range(1, len(df) + 1))
    return df


def _estilo(df):
    """Formata automaticamente qualquer coluna monetária/percentual/qtd
    pelo nome -- funciona tanto para as tabelas padrão quanto para
    colunas de participação com nomes variáveis (ex.: '% do Produto')."""
    if df is None or df.empty:
        return df
    fmt = {}
    for col in df.columns:
        if col in ('Faturamento R$', 'Custo R$', 'Margem R$', 'Ticket Médio', 'Ticket Médio por Produto',
                    'Atual', 'Anterior', 'Diferença'):
            fmt[col] = _brl
        elif col == 'Volume (cx)':
            fmt[col] = _qtd
        elif col == 'Margem %' or (isinstance(col, str) and col.startswith('%')) or col == 'Variação %':
            fmt[col] = _pct
    return df.style.format(fmt)


def _botoes_exportar(df, nome_base):
    if df is None or df.empty:
        return
    df_export = df.drop(columns=['#'], errors='ignore')
    colA, colB = st.columns(2)
    csv = df_export.to_csv(index=False, sep=';').encode('utf-8-sig')
    colA.download_button('⬇️ CSV', data=csv, file_name=f'{nome_base}.csv', mime='text/csv',
                          key=f'dl_csv_{nome_base}')
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df_export.to_excel(writer, index=False, sheet_name='Dados')
    colB.download_button(
        '⬇️ Excel', data=buf.getvalue(), file_name=f'{nome_base}.xlsx',
        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        key=f'dlx_{nome_base}')


def _tabela_cresc(linhas):
    return pd.DataFrame([{
        'Produto': l['chave'], 'Atual': l['faturamento'], 'Anterior': l['valor_anterior'],
        'Diferença': l['diferenca'], 'Variação %': l['crescimento_pct'],
    } for l in linhas])


_GRAN_POR_TIPO = {
    'semanal': ['dia', 'semana'], 'mensal': ['dia', 'semana', 'mes'],
    'trimestral': ['semana', 'mes'], 'semestral': ['mes'], 'anual': ['mes'],
}
_GRAN_LABELS = {'dia': 'Dia', 'semana': 'Semana', 'mes': 'Mês'}


# ── Cabeçalho ─────────────────────────────────────────────────────────────

st.title('📦 Relatórios de Produtos')
st.caption('Análise de desempenho, vendas, faturamento e evolução dos produtos')

with st.spinner('Carregando histórico...'):
    itens_base, avisos = pr.carregar_base_consolidada()

if not itens_base:
    st.info('Ainda não há dados suficientes para montar os Relatórios de Produtos. Faça upload de '
            'pelo menos um Relatório Diário, Semanal ou Mensal na página **Relatório Diário** primeiro.')
    st.stop()

if avisos:
    with st.expander(f'ℹ️ {len(avisos)} registro(s) não incluído(s) no histórico consolidado '
                      f'(evita contar a mesma venda duas vezes)'):
        for a in avisos:
            st.caption('• ' + a)

# ── Filtros ───────────────────────────────────────────────────────────────

st.subheader('Filtros')
c1, c2 = st.columns([1, 2])
with c1:
    tipo_periodo = st.selectbox(
        'Período', periodo_mod.TIPOS_PERIODO, format_func=periodo_mod.rotulo_tipo,
        index=1, key='prod_tipo')

opcoes_periodo = pr.periodos_disponiveis(itens_base, tipo_periodo)
if not opcoes_periodo:
    st.warning('Nenhum dado disponível para esse tipo de período.')
    st.stop()

with c2:
    periodo_ref_sel = st.selectbox(
        'Referência', opcoes_periodo,
        format_func=lambda r: periodo_mod.rotulo(tipo_periodo, r), key='prod_periodo_ref')

vendedores_op, clientes_op, produtos_op, categorias_op = pr.opcoes_dimensoes(itens_base)
fc1, fc2, fc3, fc4 = st.columns(4)
with fc1:
    f_produtos = st.multiselect('Produto', produtos_op, key='prod_f_prod')
with fc2:
    f_categorias = st.multiselect('Categoria', categorias_op, key='prod_f_cat')
with fc3:
    f_vendedores = st.multiselect('Vendedor', vendedores_op, key='prod_f_vend')
with fc4:
    f_clientes = st.multiselect('Cliente', clientes_op, key='prod_f_cli')

itens_periodo = pr.filtrar_periodo(itens_base, tipo_periodo, periodo_ref_sel)
itens_filtrados = pr.filtrar_dimensoes(itens_periodo, f_vendedores, f_clientes, f_produtos, f_categorias)

periodo_ant_ref = periodo_mod.periodo_anterior(tipo_periodo, periodo_ref_sel)
itens_periodo_ant = pr.filtrar_periodo(itens_base, tipo_periodo, periodo_ant_ref)
itens_filtrados_ant = pr.filtrar_dimensoes(itens_periodo_ant, f_vendedores, f_clientes, f_produtos, f_categorias)

if not itens_filtrados:
    st.warning(f'Nenhum dado para os filtros selecionados em '
               f'{periodo_mod.rotulo(tipo_periodo, periodo_ref_sel)}.')
    st.stop()

st.caption(f'{len(itens_filtrados)} item(ns) de venda no recorte selecionado.')

kpi_atual = pr.kpis_produto(itens_filtrados)
kpi_anterior = pr.kpis_produto(itens_filtrados_ant) if itens_filtrados_ant else None


def _comp(chave):
    if kpi_anterior is None:
        return None
    return comparativo.calcular(kpi_atual.get(chave), kpi_anterior.get(chave))


# ── KPIs ──────────────────────────────────────────────────────────────────

st.divider()
st.subheader(f'📊 KPIs — {periodo_mod.rotulo(tipo_periodo, periodo_ref_sel)}')

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric('Produtos Vendidos (SKUs)', f"{kpi_atual['skus']}",
          delta=comparativo.formatar_variacao(_comp('skus')) if kpi_anterior else None,
          help='Quantidade de produtos distintos vendidos -- não confundir com o volume em caixas.')
k2.metric('Volume Total (cx)', _qtd(kpi_atual['volume']),
          delta=comparativo.formatar_variacao(_comp('volume')) if kpi_anterior else None)
k3.metric('Faturamento Total', _brl(kpi_atual['faturamento']),
          delta=comparativo.formatar_variacao(_comp('faturamento')) if kpi_anterior else None)
k4.metric('Ticket Médio por Produto', _brl(kpi_atual['ticket_medio_produto']),
          delta=comparativo.formatar_variacao(_comp('ticket_medio_produto')) if kpi_anterior else None,
          help='Faturamento Total ÷ nº de SKUs (produtos distintos) vendidos no período.')
with k5:
    if kpi_atual['produto_lider']:
        st.metric('Produto Líder', kpi_atual['produto_lider'],
                   help=f"Maior faturamento no período: {_brl(kpi_atual['produto_lider_faturamento'])}. "
                        f"Ranking definido por Faturamento -- veja a aba Ranking para outros critérios.")
    else:
        st.metric('Produto Líder', '-')

if kpi_anterior:
    st.caption(f'Comparando com {periodo_mod.rotulo(tipo_periodo, periodo_ant_ref)}.')
else:
    st.caption(f'Sem dado disponível em {periodo_mod.rotulo(tipo_periodo, periodo_ant_ref)} '
               f'para comparar (indicadores mostrados sem variação).')

with st.expander('📈 Comparativo detalhado — período atual x período anterior'):
    linhas_cmp = []
    for label, chave, fmt in [
        ('Produtos Vendidos (SKUs)', 'skus', lambda v: f'{v:.0f}'),
        ('Volume Total', 'volume', _qtd), ('Faturamento Total', 'faturamento', _brl),
        ('Ticket Médio por Produto', 'ticket_medio_produto', _brl),
    ]:
        comp = _comp(chave)
        linhas_cmp.append({
            'Indicador': label,
            'Atual': fmt(kpi_atual.get(chave) or 0),
            'Anterior': fmt(kpi_anterior.get(chave) or 0) if kpi_anterior else 'n/d',
            'Diferença': (fmt(comp['diferenca_absoluta'])
                          if comp and comp.get('diferenca_absoluta') is not None else 'n/d'),
            'Variação %': comparativo.formatar_variacao(comp) if comp else 'n/d',
        })
    st.dataframe(pd.DataFrame(linhas_cmp), use_container_width=True, hide_index=True)
    st.caption(f'Base de comparação: {periodo_mod.rotulo(tipo_periodo, periodo_ant_ref)}.')

# ── Destaques do período (sempre visíveis, no topo) ─────────────────────────

dest = pr.destaques(itens_filtrados, itens_filtrados_ant or None)
if dest:
    st.subheader('⭐ Destaques do Período')

    def _card_destaque(col, titulo, item, campo, fmt):
        with col:
            if item is None:
                st.markdown(f'**{titulo}**')
                st.caption('Não há dados suficientes para calcular.')
            else:
                valor = item.get(campo)
                st.markdown(f"**{titulo}**  \n{item['chave']}" + (f"  \n{fmt(valor)}" if valor is not None else ''))

    d1, d2, d3 = st.columns(3)
    _card_destaque(d1, '🔝 Mais vendido (volume)', dest.get('mais_vendido'), 'volume', _qtd)
    _card_destaque(d2, '💰 Maior faturamento', dest.get('maior_faturamento'), 'faturamento', _brl)
    _card_destaque(d3, '📊 Maior participação', dest.get('maior_participacao'), 'participacao_faturamento', _pct)
    d4, d5, d6 = st.columns(3)
    _card_destaque(d4, '📈 Maior crescimento', dest.get('maior_crescimento'), 'crescimento_pct', _pct)
    _card_destaque(d5, '📉 Maior queda', dest.get('maior_queda'), 'crescimento_pct', _pct)
    _card_destaque(d6, '🏷️ Categoria líder', dest.get('categoria_lider'), 'faturamento', _brl)

# ── Abas ──────────────────────────────────────────────────────────────────

(tab_rank, tab_top, tab_evo, tab_part, tab_pxv, tab_pxc, tab_matriz,
 tab_alertas, tab_hist) = st.tabs([
    '🏆 Ranking', '📈 Top / Atenção / Crescimento', '📉 Evolução', '🥧 Participação',
    '👤 Produto × Vendedor', '🧑‍💼 Produto × Cliente', '🧭 Matrizes',
    '🚨 Pontos de Atenção', '🕓 Histórico',
])

# ---- Ranking -----------------------------------------------------------
with tab_rank:
    st.subheader('Ranking de Produtos')
    ordem_r = st.selectbox('Ordenar por', ['Maior faturamento', 'Maior volume',
                                            'Maior crescimento', 'Maior participação'], key='prod_ord_rank')
    ranking_full = pr.ranking_com_crescimento(itens_filtrados, itens_filtrados_ant or None, indicador='faturamento')
    ranking_ordenado = pr.top_produtos(ranking_full, ordem_r, n=len(ranking_full))

    linhas_show = []
    for l in ranking_ordenado:
        itens_prod = [it for it in itens_filtrados if it.get('produto') == l['chave']]
        vends = pr.por_vendedor(itens_prod)
        clis = pr.por_cliente(itens_prod)
        vend_principal = max(vends, key=lambda v: v['faturamento'])['chave'] if vends else '-'
        cli_principal = max(clis, key=lambda c: c['faturamento'])['chave'] if clis else '-'
        if l['crescimento_pct'] is not None:
            cresc_fmt = _pct(l['crescimento_pct'])
        elif l['status_crescimento'] == 'novo':
            cresc_fmt = 'novo no período'
        else:
            cresc_fmt = 'n/d'
        linhas_show.append({
            'Produto': l['chave'], 'Categoria': l['categoria'], 'Volume (cx)': l['volume'],
            'Faturamento R$': l['faturamento'], '% do Faturamento': l['participacao_faturamento'],
            'Crescimento/Queda': cresc_fmt, 'Vendedor principal': vend_principal, 'Cliente principal': cli_principal,
        })
    df_rank = pd.DataFrame(linhas_show)
    df_rank.insert(0, '#', range(1, len(df_rank) + 1))
    st.dataframe(df_rank.style.format({'Volume (cx)': _qtd, 'Faturamento R$': _brl, '% do Faturamento': _pct}),
                 use_container_width=True, hide_index=True)
    st.caption('Vendedor/Cliente principal = quem mais fatura para aquele produto no recorte '
               '(um produto pode ter mais de um vendedor/cliente).')
    _botoes_exportar(df_rank, 'produtos_ranking')

# ---- Top / Atenção / Crescimento ----------------------------------------
with tab_top:
    st.subheader('Top Produtos')
    ranking_full = pr.ranking_com_crescimento(itens_filtrados, itens_filtrados_ant or None, indicador='faturamento')
    n_top = st.slider('Quantidade', 3, 30, 10, key='prod_top_n')
    criterio_top = st.selectbox('Critério', ['Maior faturamento', 'Maior volume',
                                              'Maior crescimento', 'Maior participação'], key='prod_top_crit')
    top = pr.top_produtos(ranking_full, criterio_top, n=n_top)
    df_top = _tabela_dim(top, 'Produto', ['#', 'Produto', 'Faturamento R$', 'Volume (cx)', '% do Faturamento'])
    st.dataframe(_estilo(df_top), use_container_width=True, hide_index=True)
    _botoes_exportar(df_top, 'produtos_top')

    st.divider()
    st.subheader('Produtos que Precisam de Atenção')
    st.caption('Vender pouco não significa necessariamente que o produto é ruim -- '
               'o critério usado está sempre explícito no seletor abaixo.')
    n_at = st.slider('Quantidade', 3, 30, 10, key='prod_at_n')
    criterio_at = st.selectbox('Critério', ['Menor faturamento', 'Menor volume', 'Maior queda'], key='prod_at_crit')
    atencao = pr.produtos_atencao(ranking_full, criterio_at, n=n_at)
    if not atencao:
        st.info(f'Nenhum produto se enquadra no critério "{criterio_at}" neste recorte.')
    else:
        df_at = _tabela_dim(atencao, 'Produto', ['#', 'Produto', 'Faturamento R$', 'Volume (cx)', '% do Faturamento'])
        st.dataframe(_estilo(df_at), use_container_width=True, hide_index=True)
        _botoes_exportar(df_at, 'produtos_atencao')

    st.divider()
    st.subheader('Crescimento e Queda (vs período anterior)')
    if not itens_filtrados_ant:
        st.info(f'Sem dado disponível em {periodo_mod.rotulo(tipo_periodo, periodo_ant_ref)} para comparar.')
    else:
        crescimento_list = sorted([l for l in ranking_full if l['status_crescimento'] == 'crescimento'],
                                   key=lambda l: -l['crescimento_pct'])
        queda_list = sorted([l for l in ranking_full if l['status_crescimento'] == 'queda'],
                             key=lambda l: l['crescimento_pct'])
        colg, colq = st.columns(2)
        with colg:
            st.markdown(f'**📈 Em crescimento ({len(crescimento_list)})**')
            if crescimento_list:
                st.dataframe(_estilo(_tabela_cresc(crescimento_list)), use_container_width=True, hide_index=True)
            else:
                st.caption('Nenhum produto em crescimento neste recorte.')
        with colq:
            st.markdown(f'**📉 Em queda ({len(queda_list)})**')
            if queda_list:
                st.dataframe(_estilo(_tabela_cresc(queda_list)), use_container_width=True, hide_index=True)
            else:
                st.caption('Nenhum produto em queda neste recorte.')
        novos_list = [l for l in ranking_full if l['status_crescimento'] == 'novo']
        if novos_list:
            st.caption(f"+ {len(novos_list)} produto(s) novo(s) no período (sem venda no período anterior "
                       f"para comparar): " + ', '.join(l['chave'] for l in novos_list[:10])
                       + (' ...' if len(novos_list) > 10 else ''))

# ---- Evolução ------------------------------------------------------------
with tab_evo:
    st.subheader('Evolução das Vendas por Produto')
    produtos_disp_evo = sorted({it.get('produto') for it in itens_filtrados if it.get('produto')})
    top5_default = [p['chave'] for p in sorted(pr.por_produto(itens_filtrados),
                                                key=lambda l: -l['faturamento'])[:5]]
    produtos_evo = st.multiselect('Produtos para comparar', produtos_disp_evo,
                                   default=top5_default, key='prod_evo_sel')
    metrica_evo = st.radio('Métrica', ['Faturamento', 'Volume'], horizontal=True, key='prod_evo_metrica')
    grans_validas = _GRAN_POR_TIPO.get(tipo_periodo, ['dia', 'semana', 'mes'])
    gran_evo = st.radio('Granularidade', grans_validas, format_func=lambda g: _GRAN_LABELS[g],
                         horizontal=True, key='prod_evo_gran')

    if not produtos_evo:
        st.info('Selecione ao menos um produto para ver a evolução.')
    else:
        serie_map = pr.evolucao_por_produto(
            itens_filtrados, produtos_evo, granularidade=gran_evo,
            metrica='faturamento' if metrica_evo == 'Faturamento' else 'volume')
        rotulo_ord = {}
        for serie in serie_map.values():
            for p in serie:
                rotulo_ord[p['rotulo']] = p['data_ord']
        rotulos_ordenados = sorted(rotulo_ord, key=lambda r: rotulo_ord[r])
        df_evo = pd.DataFrame(index=rotulos_ordenados)
        for produto, serie in serie_map.items():
            valores_por_rotulo = {p['rotulo']: p['valor'] for p in serie}
            df_evo[produto] = [valores_por_rotulo.get(r, 0.0) for r in rotulos_ordenados]

        if df_evo.empty:
            st.info('Sem dados para os produtos/período selecionados.')
        else:
            st.line_chart(df_evo)
            fmt_evo = _brl if metrica_evo == 'Faturamento' else _qtd
            st.dataframe(df_evo.style.format(fmt_evo), use_container_width=True)
            df_export_evo = df_evo.reset_index().rename(columns={'index': 'Período'})
            df_export_evo.insert(0, '#', range(1, len(df_export_evo) + 1))
            _botoes_exportar(df_export_evo, 'produtos_evolucao')
            if gran_evo == 'dia':
                st.caption('Períodos cobertos apenas por upload Semanal/Mensal aparecem como um único ponto '
                           '(sem detalhe diário), pois o relatório de origem não traz a quebra por dia.')

# ---- Participação ---------------------------------------------------------
with tab_part:
    st.subheader('Participação no Faturamento')
    prods_part = sorted(pr.por_produto(itens_filtrados), key=lambda l: -l['participacao_faturamento'])
    soma_part = sum(p['participacao_faturamento'] for p in prods_part)
    df_part = _tabela_dim(prods_part, 'Produto', ['#', 'Produto', 'Categoria', 'Faturamento R$', '% do Faturamento'])
    st.dataframe(_estilo(df_part), use_container_width=True, hide_index=True)
    st.caption(f'Soma das participações no recorte: {soma_part:.2f}% '
               f'(pode variar poucos centésimos por arredondamento).')
    if prods_part:
        n_chart = min(15, len(prods_part))
        df_chart = pd.DataFrame(prods_part[:n_chart])[['chave', 'participacao_faturamento']].set_index('chave')
        df_chart.columns = ['% do Faturamento']
        st.bar_chart(df_chart, color='#2D6A4F')
    _botoes_exportar(df_part, 'produtos_participacao')

# ---- Produto x Vendedor ----------------------------------------------------
with tab_pxv:
    st.subheader('Desempenho dos Produtos por Vendedor')
    produtos_disp_pxv = sorted({it.get('produto') for it in itens_filtrados if it.get('produto')})
    produto_sel_pxv = st.selectbox('Produto específico (opcional)', ['Todos'] + produtos_disp_pxv, key='prod_pxv_sel')
    base_pxv = (itens_filtrados if produto_sel_pxv == 'Todos'
                else [it for it in itens_filtrados if it.get('produto') == produto_sel_pxv])
    tabela_pxv = pr.produto_x_vendedor_tabela(base_pxv)
    if not tabela_pxv:
        st.info('Sem dados para este recorte.')
    else:
        ordenar_pxv = st.selectbox('Ordenar por', ['Faturamento', 'Volume'], key='prod_pxv_ord')
        df_pxv = pd.DataFrame(tabela_pxv).sort_values(
            'faturamento' if ordenar_pxv == 'Faturamento' else 'volume', ascending=False)
        df_pxv = df_pxv.rename(columns=_COLS_LABELS)
        df_pxv.insert(0, '#', range(1, len(df_pxv) + 1))
        cols_show = [c for c in ['#', 'Produto', 'Vendedor', 'Volume (cx)', 'Faturamento R$', '% do Produto']
                     if c in df_pxv.columns]
        st.dataframe(_estilo(df_pxv[cols_show]), use_container_width=True, hide_index=True)
        _botoes_exportar(df_pxv[cols_show], 'produtos_x_vendedor')

# ---- Produto x Cliente -----------------------------------------------------
with tab_pxc:
    st.subheader('Desempenho dos Produtos por Cliente')
    produtos_disp_pxc = sorted({it.get('produto') for it in itens_filtrados if it.get('produto')})
    produto_sel_pxc = st.selectbox('Produto específico (opcional)', ['Todos'] + produtos_disp_pxc, key='prod_pxc_sel')
    base_pxc = (itens_filtrados if produto_sel_pxc == 'Todos'
                else [it for it in itens_filtrados if it.get('produto') == produto_sel_pxc])
    tabela_pxc = pr.produto_x_cliente_tabela(base_pxc)
    if not tabela_pxc:
        st.info('Sem dados para este recorte.')
    else:
        ordenar_pxc = st.selectbox('Ordenar por', ['Faturamento', 'Volume'], key='prod_pxc_ord')
        df_pxc = pd.DataFrame(tabela_pxc).sort_values(
            'faturamento' if ordenar_pxc == 'Faturamento' else 'volume', ascending=False)
        df_pxc = df_pxc.rename(columns=_COLS_LABELS)
        df_pxc.insert(0, '#', range(1, len(df_pxc) + 1))
        cols_show = [c for c in ['#', 'Produto', 'Cliente', 'Vendedor', 'Volume (cx)',
                                  'Faturamento R$', '% do Produto'] if c in df_pxc.columns]
        st.dataframe(_estilo(df_pxc[cols_show]), use_container_width=True, hide_index=True)
        _botoes_exportar(df_pxc[cols_show], 'produtos_x_cliente')
        if len(df_pxc) > 200:
            st.caption(f'Mostrando todas as {len(df_pxc)} combinações produto-cliente do recorte. '
                       'Use o filtro "Produto específico" acima para reduzir, se necessário.')

# ---- Matrizes ---------------------------------------------------------
with tab_matriz:
    st.subheader('Matriz Produto × Vendedor / Produto × Cliente')
    dim_m = st.radio('Comparar com', ['Vendedor', 'Cliente'], horizontal=True, key='prod_mat_dim')
    metrica_m = st.radio('Métrica', ['Faturamento', 'Volume'], horizontal=True, key='prod_mat_metrica')
    max_linhas = st.slider('Máx. de produtos (linhas)', 5, 50, 15, key='prod_mat_maxl')
    max_colunas = st.slider(f'Máx. de {dim_m.lower()}s (colunas)', 3, 30, 10, key='prod_mat_maxc')

    coluna_fn = ((lambda it: it.get('vendedor') or it.get('vendedor_raw')) if dim_m == 'Vendedor'
                 else (lambda it: it.get('cliente_nome')))
    mat = pr.matriz_pivot(itens_filtrados, metrica='faturamento' if metrica_m == 'Faturamento' else 'volume',
                           coluna_fn=coluna_fn, top_linhas=max_linhas, top_colunas=max_colunas)
    if not mat['linhas'] or not mat['colunas']:
        st.info('Sem dados suficientes para montar a matriz neste recorte.')
    else:
        dados_tab = []
        for lin in mat['linhas']:
            row = {'Produto': lin}
            for col in mat['colunas']:
                row[col] = mat['valores'].get((lin, col), 0.0)
            row['Total'] = mat['linhas_tot'][lin]
            dados_tab.append(row)
        df_mat = pd.DataFrame(dados_tab).set_index('Produto')
        fmt_fn = _brl if metrica_m == 'Faturamento' else _qtd
        st.dataframe(df_mat.style.format(fmt_fn), use_container_width=True)
        df_export_mat = df_mat.reset_index()
        df_export_mat.insert(0, '#', range(1, len(df_export_mat) + 1))
        _botoes_exportar(df_export_mat, 'produtos_matriz')
        st.caption(f"Mostrando os {len(mat['linhas'])} produtos e {len(mat['colunas'])} {dim_m.lower()}(s) "
                   f"de maior {metrica_m.lower()} no recorte. Ajuste os controles acima para ver mais/menos "
                   f"(evita tabela ilegível quando há muitos produtos/{dim_m.lower()}s).")

# ---- Pontos de Atenção -----------------------------------------------------
with tab_alertas:
    st.subheader('Pontos de Atenção')
    st.caption('Os limiares abaixo são ajustáveis -- não há regra de negócio fixa definida para nenhum '
               'destes critérios ainda.')
    with st.expander('⚙️ Ajustar limiares'):
        ca1, ca2, ca3 = st.columns(3)
        limiar_queda = ca1.number_input('Queda de faturamento (%) para alertar',
                                         value=pr.LIMIAR_QUEDA_PCT_PADRAO, step=1.0, key='prod_lim_queda')
        limiar_conc = ca2.number_input('Concentração dos 3 principais produtos (%) para alertar',
                                        value=pr.LIMIAR_CONCENTRACAO_PCT_PADRAO, step=1.0, key='prod_lim_conc')
        limiar_vol = ca3.number_input('% mínima de participação em volume p/ avaliar desproporção',
                                       value=pr.LIMIAR_VOLUME_ALTO_FAT_BAIXO_PADRAO, step=1.0, key='prod_lim_vol')
    alertas = pr.alertas_produtos(itens_filtrados, itens_filtrados_ant or None,
                                   limiar_queda_pct=limiar_queda, limiar_concentracao_pct=limiar_conc,
                                   limiar_volume_alto_pct=limiar_vol)
    if not alertas:
        st.success('Nenhum ponto de atenção identificado com os limiares atuais.')
    else:
        for a in alertas:
            icone = '🔴' if a['severidade'] == 'critico' else '🟡'
            st.markdown(f"{icone} **{a['tipo']}** — {a['detalhe']}")

# ---- Histórico --------------------------------------------------------
with tab_hist:
    st.subheader('Histórico de Relatórios de Produtos')
    st.caption('Salva o recorte atual (filtros + indicadores + top produtos) como um registro do histórico. '
               'Cada gravação preserva a versão anterior -- nada é sobrescrito ou apagado.')
    if st.button('💾 Salvar este relatório no histórico', key='prod_salvar'):
        ranking_snap = pr.ranking_com_crescimento(itens_filtrados, itens_filtrados_ant or None, indicador='faturamento')
        snapshot = {
            'periodo': periodo_mod.rotulo(tipo_periodo, periodo_ref_sel),
            'tipo_periodo': tipo_periodo, 'periodo_ref': periodo_ref_sel,
            'filtros': {
                'produtos': f_produtos, 'categorias': f_categorias,
                'vendedores': f_vendedores, 'clientes': f_clientes,
            },
            'kpis': kpi_atual,
            'destaques': {k: (v['chave'] if isinstance(v, dict) else v) for k, v in dest.items()} if dest else {},
            'top_produtos': sorted(ranking_snap, key=lambda l: l['faturamento'], reverse=True)[:10],
        }
        registro = ds.save_record(modulo=MODULO, tipo_periodo=tipo_periodo,
                                   periodo_ref=periodo_ref_sel, valores=snapshot, usuario='Ingrid')
        if registro.get('_erro_persistencia_remota'):
            st.warning('Salvo localmente, mas houve um problema ao salvar de forma permanente: '
                       f"{registro['_erro_persistencia_remota']}")
        else:
            st.success(f"Relatório salvo (versão {registro['versao']}).")

    st.divider()
    slugs_salvos = ds.list_periodos(MODULO, tipo_periodo)
    if not slugs_salvos:
        st.info('Nenhum relatório salvo ainda para este tipo de período.')
    else:
        slug_ver = st.selectbox('Ver relatório salvo', slugs_salvos,
                                 format_func=lambda r: periodo_mod.rotulo(tipo_periodo, r), key='prod_hist_sel')
        versoes = ds.load_all_versions(MODULO, tipo_periodo, slug_ver)
        if versoes:
            rotulos_v = [f"v{v.get('versao', '?')} — {(v.get('atualizado_em') or '')[:16].replace('T', ' ')} "
                         f"— {v.get('usuario', '')}" for v in versoes]
            v_idx = st.selectbox('Versão', list(range(len(versoes))), format_func=lambda i: rotulos_v[i],
                                  index=len(versoes) - 1, key='prod_hist_ver')
            v = versoes[v_idx].get('valores', {})
            k = v.get('kpis', {})
            hc1, hc2, hc3, hc4 = st.columns(4)
            hc1.metric('SKUs', k.get('skus', 0))
            hc2.metric('Volume', _qtd(k.get('volume', 0)))
            hc3.metric('Faturamento', _brl(k.get('faturamento', 0)))
            hc4.metric('Produto Líder', k.get('produto_lider') or '-')
            flt = v.get('filtros', {})
            partes = [f"{lbl}: {', '.join(vals)}" for lbl, vals in
                      [('Produto', flt.get('produtos') or []), ('Categoria', flt.get('categorias') or []),
                       ('Vendedor', flt.get('vendedores') or []), ('Cliente', flt.get('clientes') or [])]
                      if vals]
            st.caption('Filtros aplicados nesta versão: ' + ('; '.join(partes) if partes else 'nenhum (todos)'))

            top_v = v.get('top_produtos') or []
            if top_v:
                st.markdown('**Top produtos por faturamento (na data em que foi salvo)**')
                df_hv = _tabela_dim(top_v, 'Produto', ['#', 'Produto', 'Faturamento R$', 'Volume (cx)'])
                st.dataframe(_estilo(df_hv), use_container_width=True, hide_index=True)
