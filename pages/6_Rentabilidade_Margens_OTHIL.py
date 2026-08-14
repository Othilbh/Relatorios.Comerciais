"""OTHIL — Rentabilidade e Margens (Projeto 3)

Consolida o histórico já salvo pelo Relatório Diário/Semanal/Mensal
(módulo relatorio_diario, via data_store) numa base única e analisa
faturamento, custo, margem R$ e margem % por vendedor, cliente e produto,
com comparativo entre períodos, matriz Faturamento x Margem, evolução
temporal, rankings, alertas gerenciais e histórico versionado.

Não faz upload próprio de PDF -- reaproveita 100% os dados já persistidos
pelo módulo Relatório Diário (nenhuma lógica de faturamento/custo/margem
foi duplicada; toda ela vive em rentabilidade.py, o motor de cálculo
central deste módulo).
"""
import io

import pandas as pd
import streamlit as st

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import comparativo
import data_store as ds
import periodo as periodo_mod
import rentabilidade as rt

MODULO = 'rentabilidade'


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
    'ticket_medio': 'Ticket Médio', 'participacao_faturamento': '% do Faturamento',
    'participacao_margem': '% da Margem', 'vendedor_responsavel': 'Vendedor Responsável',
    'categoria': 'Categoria', 'quadrante': 'Quadrante',
}


def _tabela_dim(linhas, nome_chave, colunas=None):
    """Converte a saída de rentabilidade.agregar_por() num DataFrame pronto
    p/ exibição, com coluna de ranking (#) e nomes amigáveis."""
    if not linhas:
        return pd.DataFrame()
    df = pd.DataFrame(linhas).rename(columns={'chave': nome_chave, **_COLS_LABELS})
    if colunas:
        df = df[[c for c in colunas if c in df.columns]]
    df.insert(0, '#', range(1, len(df) + 1))
    return df


def _estilo(df):
    if df.empty:
        return df
    fmt = {}
    for col, f in [('Faturamento R$', _brl), ('Custo R$', _brl), ('Margem R$', _brl),
                    ('Margem %', _pct), ('Volume (cx)', _qtd), ('Ticket Médio', _brl),
                    ('% do Faturamento', _pct), ('% da Margem', _pct)]:
        if col in df.columns:
            fmt[col] = f
    return df.style.format(fmt)


def _ordenar(linhas, opcao):
    chaves = {
        'Maior margem R$': 'margem_rs', 'Maior faturamento': 'faturamento',
        'Maior margem %': 'margem_pct', 'Maior volume': 'volume',
    }
    return sorted(linhas, key=lambda l: l.get(chaves.get(opcao, 'margem_rs'), 0), reverse=True)


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


# ── Cabeçalho ─────────────────────────────────────────────────────────────

st.title('💰 Rentabilidade e Margens')
st.caption('Análise de faturamento, custos, margem e rentabilidade comercial')

with st.spinner('Carregando histórico...'):
    itens_base, avisos = rt.carregar_base_consolidada()

if not itens_base:
    st.info('Ainda não há dados suficientes para montar a Rentabilidade. Faça upload de pelo '
            'menos um Relatório Diário, Semanal ou Mensal na página **Relatório Diário** primeiro.')
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
        index=1, key='rent_tipo')

opcoes_periodo = rt.periodos_disponiveis(itens_base, tipo_periodo)
if not opcoes_periodo:
    st.warning('Nenhum dado disponível para esse tipo de período.')
    st.stop()

with c2:
    periodo_ref_sel = st.selectbox(
        'Referência', opcoes_periodo,
        format_func=lambda r: periodo_mod.rotulo(tipo_periodo, r), key='rent_periodo_ref')

vendedores_op, clientes_op, produtos_op, categorias_op = rt.opcoes_dimensoes(itens_base)
fc1, fc2, fc3, fc4 = st.columns(4)
with fc1:
    f_vendedores = st.multiselect('Vendedor', vendedores_op, key='rent_f_vend')
with fc2:
    f_clientes = st.multiselect('Cliente', clientes_op, key='rent_f_cli')
with fc3:
    f_produtos = st.multiselect('Produto', produtos_op, key='rent_f_prod')
with fc4:
    f_categorias = st.multiselect('Categoria', categorias_op, key='rent_f_cat')

itens_periodo = rt.filtrar_periodo(itens_base, tipo_periodo, periodo_ref_sel)
itens_filtrados = rt.filtrar_dimensoes(itens_periodo, f_vendedores, f_clientes, f_produtos, f_categorias)

periodo_ant_ref = periodo_mod.periodo_anterior(tipo_periodo, periodo_ref_sel)
itens_periodo_ant = rt.filtrar_periodo(itens_base, tipo_periodo, periodo_ant_ref)
itens_filtrados_ant = rt.filtrar_dimensoes(itens_periodo_ant, f_vendedores, f_clientes, f_produtos, f_categorias)

if not itens_filtrados:
    st.warning(f'Nenhum dado para os filtros selecionados em '
               f'{periodo_mod.rotulo(tipo_periodo, periodo_ref_sel)}.')
    st.stop()

st.caption(f'{len(itens_filtrados)} item(ns) de venda no recorte selecionado.')

kpi_atual = rt.agregar(itens_filtrados)
kpi_anterior = rt.agregar(itens_filtrados_ant) if itens_filtrados_ant else None


def _comp(chave):
    if kpi_anterior is None:
        return None
    return comparativo.calcular(kpi_atual[chave], kpi_anterior[chave])


# ── KPIs ──────────────────────────────────────────────────────────────────

st.divider()
st.subheader(f'📊 KPIs — {periodo_mod.rotulo(tipo_periodo, periodo_ref_sel)}')

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric('Faturamento Total', _brl(kpi_atual['faturamento']),
          delta=comparativo.formatar_variacao(_comp('faturamento')) if kpi_anterior else None)
k2.metric('Custo Total', _brl(kpi_atual['custo']),
          delta=comparativo.formatar_variacao(_comp('custo')) if kpi_anterior else None,
          delta_color='inverse')
k3.metric('Margem de Contribuição', _brl(kpi_atual['margem_rs']),
          delta=comparativo.formatar_variacao(_comp('margem_rs')) if kpi_anterior else None)
k4.metric('Margem %', _pct(kpi_atual['margem_pct']),
          delta=comparativo.formatar_variacao(_comp('margem_pct')) if kpi_anterior else None)
k5.metric('Volume Vendido (cx)', _qtd(kpi_atual['volume']),
          delta=comparativo.formatar_variacao(_comp('volume')) if kpi_anterior else None)
k6.metric('Ticket Médio', _brl(kpi_atual['ticket_medio']),
          delta=comparativo.formatar_variacao(_comp('ticket_medio')) if kpi_anterior else None)

if kpi_anterior:
    st.caption(f'Comparando com {periodo_mod.rotulo(tipo_periodo, periodo_ant_ref)}.')
else:
    st.caption(f'Sem dado disponível em {periodo_mod.rotulo(tipo_periodo, periodo_ant_ref)} '
               f'para comparar (indicadores mostrados sem variação).')

with st.expander('📈 Comparativo detalhado — período atual x período anterior'):
    linhas_cmp = []
    for label, chave, fmt in [
        ('Faturamento', 'faturamento', _brl), ('Custo', 'custo', _brl),
        ('Margem R$', 'margem_rs', _brl), ('Margem %', 'margem_pct', _pct),
        ('Volume', 'volume', _qtd), ('Ticket Médio', 'ticket_medio', _brl),
    ]:
        comp = _comp(chave)
        linhas_cmp.append({
            'Indicador': label,
            'Atual': fmt(kpi_atual[chave]),
            'Anterior': fmt(kpi_anterior[chave]) if kpi_anterior else 'n/d',
            'Diferença': (fmt(comp['diferenca_absoluta'])
                          if comp and comp.get('diferenca_absoluta') is not None else 'n/d'),
            'Variação %': comparativo.formatar_variacao(comp) if comp else 'n/d',
        })
    st.dataframe(pd.DataFrame(linhas_cmp), use_container_width=True, hide_index=True)
    st.caption(f'Base de comparação: {periodo_mod.rotulo(tipo_periodo, periodo_ant_ref)}.')

# ── Abas ──────────────────────────────────────────────────────────────────

tab_vend, tab_cli, tab_prod, tab_matriz, tab_evo, tab_topbottom, tab_alertas, tab_hist = st.tabs([
    '👤 Por Vendedor', '🧑‍💼 Por Cliente', '📦 Por Produto', '🧭 Matriz Fat x Margem',
    '📈 Evolução', '🏆 Top / Bottom', '🚨 Pontos de Atenção', '🕓 Histórico',
])

with tab_vend:
    st.subheader('Rentabilidade por Vendedor')
    ordem_v = st.selectbox('Ordenar por', ['Maior margem R$', 'Maior faturamento',
                                            'Maior margem %', 'Maior volume'], key='rent_ord_vend')
    linhas_v = _ordenar(rt.por_vendedor(itens_filtrados), ordem_v)
    df_v = _tabela_dim(linhas_v, 'Vendedor', ['#', 'Vendedor', 'Faturamento R$', 'Custo R$',
                                               'Margem R$', 'Margem %', 'Volume (cx)',
                                               '% do Faturamento', '% da Margem'])
    st.dataframe(_estilo(df_v), use_container_width=True, hide_index=True)
    _botoes_exportar(df_v, 'rentabilidade_por_vendedor')

with tab_cli:
    st.subheader('Rentabilidade por Cliente')
    ordem_c = st.selectbox('Ordenar por', ['Maior margem R$', 'Maior faturamento',
                                            'Maior margem %', 'Maior volume'], key='rent_ord_cli')
    linhas_c = _ordenar(rt.por_cliente(itens_filtrados), ordem_c)
    df_c = _tabela_dim(linhas_c, 'Cliente', ['#', 'Cliente', 'Vendedor Responsável',
                                              'Faturamento R$', 'Custo R$', 'Margem R$', 'Margem %',
                                              'Volume (cx)', '% do Faturamento', '% da Margem'])
    st.dataframe(_estilo(df_c), use_container_width=True, hide_index=True)
    _botoes_exportar(df_c, 'rentabilidade_por_cliente')
    st.caption('Veja a aba **Matriz Fat x Margem** para o cruzamento alto/baixo faturamento x margem por cliente.')

with tab_prod:
    st.subheader('Rentabilidade por Produto')
    ordem_p = st.selectbox('Ordenar por', ['Maior margem R$', 'Maior faturamento',
                                            'Maior margem %', 'Maior volume'], key='rent_ord_prod')
    linhas_p = _ordenar(rt.por_produto(itens_filtrados), ordem_p)
    df_p = _tabela_dim(linhas_p, 'Produto', ['#', 'Produto', 'Categoria', 'Volume (cx)',
                                              'Faturamento R$', 'Custo R$', 'Margem R$', 'Margem %',
                                              '% do Faturamento', '% da Margem'])
    st.dataframe(_estilo(df_p), use_container_width=True, hide_index=True)
    _botoes_exportar(df_p, 'rentabilidade_por_produto')

with tab_matriz:
    st.subheader('Matriz Faturamento x Margem')
    dim_escolha = st.radio('Dimensão', ['Cliente', 'Produto', 'Vendedor'], horizontal=True, key='rent_matriz_dim')
    fn_dim = {'Cliente': rt.por_cliente, 'Produto': rt.por_produto, 'Vendedor': rt.por_vendedor}[dim_escolha]
    linhas_dim = fn_dim(itens_filtrados)
    matriz, corte_fat, corte_mrg = rt.matriz_quadrantes(linhas_dim)
    if not matriz:
        st.info('Sem dados suficientes para montar a matriz neste recorte.')
    else:
        st.caption(f'Corte usado (mediana do conjunto filtrado): Faturamento ≥ {_brl(corte_fat)} '
                   f'e Margem % ≥ {_pct(corte_mrg)}.')
        df_mat = pd.DataFrame(matriz)
        try:
            st.scatter_chart(df_mat, x='faturamento', y='margem_pct', color='quadrante',
                              size='volume' if (df_mat['volume'] > 0).any() else None)
        except Exception:
            st.caption('(gráfico de dispersão indisponível nesta versão do Streamlit — tabelas abaixo mostram o mesmo cruzamento)')
        for quad in sorted(df_mat['quadrante'].unique()):
            sub = [m for m in matriz if m['quadrante'] == quad]
            with st.expander(f'{quad} — {len(sub)} {dim_escolha.lower()}(s)'):
                df_q = _tabela_dim(sorted(sub, key=lambda l: -l['margem_rs']), dim_escolha,
                                    ['#', dim_escolha, 'Faturamento R$', 'Margem R$', 'Margem %'])
                st.dataframe(_estilo(df_q), use_container_width=True, hide_index=True)

with tab_evo:
    st.subheader('Evolução da margem')
    _gran_por_tipo = {
        'semanal': ['dia', 'semana'], 'mensal': ['dia', 'semana', 'mes'],
        'trimestral': ['semana', 'mes'], 'semestral': ['mes'], 'anual': ['mes'],
    }
    _gran_labels = {'dia': 'Dia', 'semana': 'Semana', 'mes': 'Mês'}
    grans_validas = _gran_por_tipo.get(tipo_periodo, ['dia', 'semana', 'mes'])
    granularidade = st.radio('Granularidade', grans_validas, format_func=lambda g: _gran_labels[g],
                              horizontal=True, key='rent_gran')
    serie = rt.evolucao(itens_filtrados, granularidade=granularidade)
    if not serie:
        st.info('Sem dados para montar a evolução no recorte atual.')
    else:
        df_ev = pd.DataFrame(serie).set_index('rotulo')
        cc1, cc2 = st.columns(2)
        with cc1:
            st.bar_chart(df_ev[['faturamento']].rename(columns={'faturamento': 'Faturamento R$'}), color='#2D6A4F')
        with cc2:
            st.bar_chart(df_ev[['margem_rs']].rename(columns={'margem_rs': 'Margem R$'}), color='#40916C')
        st.line_chart(df_ev[['margem_pct']].rename(columns={'margem_pct': 'Margem %'}), color='#7A1F2B')
        df_show = pd.DataFrame(serie)[['rotulo', 'faturamento', 'custo', 'margem_rs', 'margem_pct', 'volume']]
        df_show.columns = ['Período', 'Faturamento R$', 'Custo R$', 'Margem R$', 'Margem %', 'Volume (cx)']
        st.dataframe(_estilo(df_show), use_container_width=True, hide_index=True)
        _botoes_exportar(df_show.assign(**{'#': range(1, len(df_show) + 1)}), 'rentabilidade_evolucao')
        if granularidade == 'dia':
            st.caption('Períodos cobertos apenas por upload Semanal/Mensal aparecem como um único ponto '
                       '(sem detalhe diário), pois o relatório de origem não traz a quebra por dia.')

with tab_topbottom:
    st.subheader('Top e Bottom')
    n_top = st.slider('Quantidade', min_value=3, max_value=20, value=10, key='rent_topn')
    for nome_dim_pl, nome_dim_sg, fn in [
        ('Vendedores', 'Vendedor', rt.por_vendedor),
        ('Clientes', 'Cliente', rt.por_cliente),
        ('Produtos', 'Produto', rt.por_produto),
    ]:
        linhas = fn(itens_filtrados)
        if not linhas:
            continue
        ordenadas = sorted(linhas, key=lambda l: l['margem_rs'], reverse=True)
        top = ordenadas[:n_top]
        bottom = list(reversed(ordenadas[-n_top:])) if len(ordenadas) > n_top else list(reversed(ordenadas))
        colT, colB = st.columns(2)
        with colT:
            st.markdown(f'**🏆 Top {len(top)} {nome_dim_pl} por Margem R$**')
            df_top = _tabela_dim(top, nome_dim_sg, ['#', nome_dim_sg, 'Faturamento R$', 'Margem R$', 'Margem %'])
            st.dataframe(_estilo(df_top), use_container_width=True, hide_index=True)
        with colB:
            st.markdown(f'**⚠️ Bottom {len(bottom)} {nome_dim_pl} por Margem R$**')
            df_bot = _tabela_dim(bottom, nome_dim_sg, ['#', nome_dim_sg, 'Faturamento R$', 'Margem R$', 'Margem %'])
            st.dataframe(_estilo(df_bot), use_container_width=True, hide_index=True)
        st.divider()

with tab_alertas:
    st.subheader('Pontos de Atenção')
    st.caption('Os limiares abaixo são ajustáveis -- não existe hoje uma regra de negócio fixa de '
               '"margem mínima sobre faturamento" definida para este módulo.')
    with st.expander('⚙️ Ajustar limiares'):
        ca1, ca2, ca3 = st.columns(3)
        limiar_atencao = ca1.number_input('Margem % mínima (atenção)',
                                           value=rt.LIMIAR_MARGEM_ATENCAO_PADRAO, step=1.0, key='rent_lim_at')
        limiar_critico = ca2.number_input('Margem % mínima (crítico)',
                                           value=rt.LIMIAR_MARGEM_CRITICO_PADRAO, step=1.0, key='rent_lim_cr')
        limiar_queda = ca3.number_input('Queda de margem entre períodos (p.p.)',
                                         value=rt.LIMIAR_QUEDA_PP_PADRAO, step=1.0, key='rent_lim_qd')
    alertas = rt.alertas_gerenciais(itens_filtrados, itens_filtrados_ant or None,
                                     limiar_atencao=limiar_atencao, limiar_critico=limiar_critico,
                                     limiar_queda_pp=limiar_queda)
    if not alertas:
        st.success('Nenhum ponto de atenção identificado com os limiares atuais.')
    else:
        for a in alertas:
            icone = '🔴' if a['severidade'] == 'critico' else '🟡'
            st.markdown(f"{icone} **{a['tipo']}** — {a['detalhe']}")

with tab_hist:
    st.subheader('Histórico de Rentabilidade')
    st.caption('Salva o recorte atual (filtros + indicadores) como um registro do histórico. '
               'Cada gravação preserva a versão anterior -- nada é sobrescrito ou apagado.')
    if st.button('💾 Salvar este relatório no histórico', key='rent_salvar'):
        snapshot = {
            'periodo': periodo_mod.rotulo(tipo_periodo, periodo_ref_sel),
            'tipo_periodo': tipo_periodo, 'periodo_ref': periodo_ref_sel,
            'filtros': {
                'vendedores': f_vendedores, 'clientes': f_clientes,
                'produtos': f_produtos, 'categorias': f_categorias,
            },
            'kpis': kpi_atual,
            'top_vendedores': sorted(rt.por_vendedor(itens_filtrados),
                                      key=lambda l: l['margem_rs'], reverse=True)[:10],
            'top_clientes': sorted(rt.por_cliente(itens_filtrados),
                                    key=lambda l: l['margem_rs'], reverse=True)[:10],
            'top_produtos': sorted(rt.por_produto(itens_filtrados),
                                    key=lambda l: l['margem_rs'], reverse=True)[:10],
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
                                 format_func=lambda r: periodo_mod.rotulo(tipo_periodo, r), key='rent_hist_sel')
        versoes = ds.load_all_versions(MODULO, tipo_periodo, slug_ver)
        if versoes:
            rotulos_v = [f"v{v.get('versao','?')} — {(v.get('atualizado_em') or '')[:16].replace('T', ' ')} "
                         f"— {v.get('usuario','')}" for v in versoes]
            v_idx = st.selectbox('Versão', list(range(len(versoes))), format_func=lambda i: rotulos_v[i],
                                  index=len(versoes) - 1, key='rent_hist_ver')
            v = versoes[v_idx].get('valores', {})
            k = v.get('kpis', {})
            hc1, hc2, hc3, hc4 = st.columns(4)
            hc1.metric('Faturamento', _brl(k.get('faturamento', 0)))
            hc2.metric('Margem R$', _brl(k.get('margem_rs', 0)))
            hc3.metric('Margem %', _pct(k.get('margem_pct', 0)))
            hc4.metric('Ticket Médio', _brl(k.get('ticket_medio', 0)))
            flt = v.get('filtros', {})
            partes = [f"{lbl}: {', '.join(vals)}" for lbl, vals in
                      [('Vendedor', flt.get('vendedores') or []), ('Cliente', flt.get('clientes') or []),
                       ('Produto', flt.get('produtos') or []), ('Categoria', flt.get('categorias') or [])]
                      if vals]
            st.caption('Filtros aplicados nesta versão: ' + ('; '.join(partes) if partes else 'nenhum (todos)'))

            top_v = v.get('top_vendedores') or []
            if top_v:
                st.markdown('**Top vendedores por margem (na data em que foi salvo)**')
                df_hv = _tabela_dim(top_v, 'Vendedor', ['#', 'Vendedor', 'Faturamento R$', 'Margem R$', 'Margem %'])
                st.dataframe(_estilo(df_hv), use_container_width=True, hide_index=True)
