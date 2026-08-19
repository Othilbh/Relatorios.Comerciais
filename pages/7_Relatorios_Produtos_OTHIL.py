"""OTHIL — Relatórios de Produtos (Projeto 2)

Análise de desempenho, vendas, faturamento e evolução dos produtos.

Fonte de dados: upload direto, nesta página, do relatório "Resumo do
Estoque" (PDF do Plus) -- a pedido explícito da Ingrid, porque a base de
Vendedor-Cliente só cobre os clientes cadastrados naquele módulo, e este
relatório traz o total de saída (venda) de TODOS os produtos, incluindo
os Grupos oficiais do ERP (muito mais precisos que o chute por palavra-
chave de categorias.py). Isso é uma fonte DIFERENTE da usada em
Rentabilidade/Vendedor-Cliente/Gerência -- nenhum desses outros módulos
foi alterado. Toda a lógica de agregação/margem/comparação é reaproveitada
de rentabilidade.py via produtos.py -- nada foi duplicado aqui.
"""
import io
import os
import subprocess
import tempfile

import pandas as pd
import streamlit as st

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import comparativo
import data_store as ds
import periodo as periodo_mod
import produtos as pr
import parsers_estoque

MODULO = 'relatorios_produtos'


def _pdf_to_text(uploaded_file):
    """Mesma técnica usada em Prevenção de Perdas (pdftotext -layout via
    subprocess) -- reaproveitada aqui, não reimplementada."""
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
        tmp.write(uploaded_file.read())
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            ['pdftotext', '-layout', tmp_path, '-'],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout if result.returncode == 0 else None
    except Exception:
        return None
    finally:
        os.unlink(tmp_path)


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


def _pp(v):
    """Formata diferença de margem % em PONTOS PERCENTUAIS -- não confundir
    com variação percentual comum (ver seção 'Comparativo de Margem')."""
    if v is None:
        return 'n/d'
    sinal = '+' if v >= 0 else ''
    s = f"{v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"{sinal}{s} p.p."


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
st.caption('Análise de desempenho, vendas, faturamento e evolução dos produtos — '
           'fonte: Resumo do Estoque (upload abaixo)')

# ── Upload do Resumo do Estoque ─────────────────────────────────────────────

itens_base, avisos = pr.carregar_base_estoque()

with st.expander('📤 Enviar novo Resumo do Estoque (PDF)', expanded=not itens_base):
    st.caption('Relatório do Plus: Estoque → Resumo do Estoque. Cada envio cobre 1 mês '
               '(o mês é identificado pela data de Emissão do próprio relatório) e some com '
               'os meses já enviados anteriormente -- não substitui outro mês, só o dele.')
    arquivo_estoque = st.file_uploader('Resumo do Estoque (PDF)', type='pdf', key='prod_upload_resumo_estoque')
    if arquivo_estoque is not None:
        texto_pdf = _pdf_to_text(arquivo_estoque)
        if not texto_pdf:
            st.error('Não foi possível ler o texto deste PDF (pdftotext falhou). Confirme que é o '
                     'relatório "Resumo do Estoque" exportado em PDF pelo Plus.')
        else:
            parsed = parsers_estoque.parse_resumo_estoque(texto_pdf)
            if not parsed['itens']:
                st.error('Não foi possível reconhecer nenhum produto neste PDF. Confirme que é o '
                         'relatório "Resumo do Estoque" (com seções "Grupo: ..." e coluna "Resultado").')
            else:
                periodo_ref_prev = periodo_mod.periodo_ref('mensal', parsed['emissao_date'])
                uc1, uc2, uc3 = st.columns(3)
                uc1.metric('Produtos reconhecidos', len(parsed['itens']))
                uc2.metric('Grupos oficiais', len(parsed['grupos']))
                uc3.metric('Mês identificado', periodo_mod.rotulo('mensal', periodo_ref_prev))
                if parsed['avisos']:
                    with st.expander(f"⚠️ {len(parsed['avisos'])} observação(ões) na leitura deste PDF "
                                      f"(nenhum dado foi inventado ou descartado)"):
                        for a in parsed['avisos']:
                            st.caption('• ' + a)
                if ds.has_data(pr.MOD_PRODUTOS_ESTOQUE, 'mensal', periodo_ref_prev):
                    st.warning(f"Já existe um Resumo do Estoque salvo para "
                               f"{periodo_mod.rotulo('mensal', periodo_ref_prev)}. Salvar de novo cria uma "
                               f"nova versão no histórico (a versão anterior NÃO é apagada).")
                if st.button('💾 Salvar este Resumo do Estoque', key='prod_salvar_resumo_estoque'):
                    periodo_ref_salvo, registro = pr.salvar_resumo_estoque(
                        parsed, usuario=st.session_state.get('usuario_nome', 'Ingrid'))
                    if registro.get('_erro_persistencia_remota'):
                        st.warning('Salvo localmente, mas houve um problema ao salvar de forma permanente: '
                                   f"{registro['_erro_persistencia_remota']}")
                    else:
                        st.success(f"Resumo do Estoque de {periodo_mod.rotulo('mensal', periodo_ref_salvo)} "
                                   f"salvo (versão {registro['versao']}).")
                    st.rerun()

if not itens_base:
    st.info('Ainda não há nenhum Resumo do Estoque salvo. Envie o PDF acima para montar os '
            'Relatórios de Produtos.')
    st.stop()

if avisos:
    with st.expander(f'ℹ️ {len(avisos)} observação(ões) na leitura dos Resumos do Estoque salvos'):
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
    if clientes_op == ['(não identificado)']:
        st.caption('Fonte sem detalhamento por cliente.')

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

k1, k2, k3, k4 = st.columns(4)
k1.metric('Produtos Trabalhados (SKUs)', f"{kpi_atual['skus']}",
          delta=comparativo.formatar_variacao(_comp('skus')) if kpi_anterior else None,
          help='Quantidade de produtos distintos vendidos -- não confundir com o volume em caixas.')
k2.metric('Volume Total (cx)', _qtd(kpi_atual['volume']),
          delta=comparativo.formatar_variacao(_comp('volume')) if kpi_anterior else None)
k3.metric('Faturamento Total', _brl(kpi_atual['faturamento']),
          delta=comparativo.formatar_variacao(_comp('faturamento')) if kpi_anterior else None)
k4.metric('Margem de Contribuição', _brl(kpi_atual['margem_rs']),
          delta=comparativo.formatar_variacao(_comp('margem_rs')) if kpi_anterior else None,
          help='Margem R$ = Faturamento - Custo, somada de todos os produtos do recorte.')

k5, k6, k7, k8 = st.columns(4)
margem_pp = None
if kpi_anterior is not None:
    margem_pp = kpi_atual['margem_pct'] - kpi_anterior['margem_pct']
k5.metric('Margem %', _pct(kpi_atual['margem_pct']),
          delta=(_pp(margem_pp) if margem_pp is not None else None),
          help='Margem % = Margem R$ ÷ Faturamento × 100. Variação mostrada em pontos percentuais (p.p.), '
               'não em variação percentual comum.')
with k6:
    if kpi_atual['grupo_lider']:
        st.metric('Grupo Líder', kpi_atual['grupo_lider'],
                   help=f"Maior faturamento no período: {_brl(kpi_atual['grupo_lider_faturamento'])}.")
    else:
        st.metric('Grupo Líder', '-')
with k7:
    if kpi_atual['produto_lider']:
        st.metric('Produto Líder', kpi_atual['produto_lider'],
                   help=f"Maior faturamento no período: {_brl(kpi_atual['produto_lider_faturamento'])}. "
                        f"Ranking definido por Faturamento -- veja a aba Resumo por Produto para outros critérios.")
    else:
        st.metric('Produto Líder', '-')
k8.metric('Ticket Médio por Produto', _brl(kpi_atual['ticket_medio_produto']),
          delta=comparativo.formatar_variacao(_comp('ticket_medio_produto')) if kpi_anterior else None,
          help='Faturamento Total ÷ nº de SKUs (produtos distintos) vendidos no período.')

if kpi_anterior:
    st.caption(f'Comparando com {periodo_mod.rotulo(tipo_periodo, periodo_ant_ref)}.')
else:
    st.caption(f'Sem dado disponível em {periodo_mod.rotulo(tipo_periodo, periodo_ant_ref)} '
               f'para comparar (indicadores mostrados sem variação).')

with st.expander('📈 Comparativo detalhado — período atual x período anterior'):
    linhas_cmp = []
    for label, chave, fmt in [
        ('Produtos Trabalhados (SKUs)', 'skus', lambda v: f'{v:.0f}'),
        ('Volume Total', 'volume', _qtd), ('Faturamento Total', 'faturamento', _brl),
        ('Margem de Contribuição R$', 'margem_rs', _brl),
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
    # Margem % compara em pontos percentuais (p.p.), não em variação percentual comum.
    linhas_cmp.append({
        'Indicador': 'Margem %',
        'Atual': _pct(kpi_atual.get('margem_pct') or 0),
        'Anterior': _pct(kpi_anterior.get('margem_pct') or 0) if kpi_anterior else 'n/d',
        'Diferença': _pp(margem_pp) if margem_pp is not None else 'n/d',
        'Variação %': '(ver Diferença em p.p.)',
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

    d1, d2, d3, d4 = st.columns(4)
    _card_destaque(d1, '🔝 Mais vendido (volume)', dest.get('mais_vendido'), 'volume', _qtd)
    _card_destaque(d2, '💰 Maior faturamento', dest.get('maior_faturamento'), 'faturamento', _brl)
    _card_destaque(d3, '💎 Maior margem (R$)', dest.get('maior_margem'), 'margem_rs', _brl)
    _card_destaque(d4, '📊 Maior participação', dest.get('maior_participacao'), 'participacao_faturamento', _pct)
    d5, d6, d7 = st.columns(3)
    _card_destaque(d5, '📈 Maior crescimento', dest.get('maior_crescimento'), 'crescimento_pct', _pct)
    _card_destaque(d6, '📉 Maior queda', dest.get('maior_queda'), 'crescimento_pct', _pct)
    _card_destaque(d7, '🏷️ Grupo líder', dest.get('categoria_lider'), 'faturamento', _brl)

# ── Abas ──────────────────────────────────────────────────────────────────

(tab_resumo, tab_margem, tab_drill, tab_trabalhados, tab_top, tab_evo, tab_part, tab_pxv, tab_pxc, tab_matriz,
 tab_alertas, tab_hist) = st.tabs([
    '1️⃣ Resumo por Produto', '2️⃣ Margem de Contribuição', '3️⃣ Drill-down por Grupo', '4️⃣ Mais Trabalhados',
    '📈 Top / Atenção / Crescimento', '📉 Evolução', '🥧 Participação',
    '👤 Produto × Vendedor', '🧑‍💼 Produto × Cliente', '🧭 Matrizes',
    '🚨 Pontos de Atenção', '🕓 Histórico',
])

# Ranking-com-crescimento do recorte completo -- base compartilhada pelas
# entregas 1 e 2 (não recalcula a mesma coisa duas vezes).
ranking_full = pr.ranking_com_crescimento(itens_filtrados, itens_filtrados_ant or None, indicador='faturamento')

_DESTAQUE_CHAVES = {
    (dest.get('maior_faturamento') or {}).get('chave'): '💰',
    (dest.get('mais_vendido') or {}).get('chave'): '🔝',
    (dest.get('maior_margem') or {}).get('chave'): '💎',
    (dest.get('maior_crescimento') or {}).get('chave'): '📈',
    (dest.get('maior_queda') or {}).get('chave'): '📉',
} if dest else {}
_DESTAQUE_CHAVES.pop(None, None)


def _marca(produto):
    return _DESTAQUE_CHAVES.get(produto, '')


# ---- ENTREGA 1: Resumo por Produto --------------------------------------
with tab_resumo:
    st.subheader('1. Resumo por Produto')
    st.caption('Visão consolidada de desempenho de cada produto no recorte selecionado (filtros + período '
               'no topo da página). Destaques: 💰 maior faturamento · 🔝 mais vendido (volume) · '
               '💎 maior margem R$ · 📈 maior crescimento · 📉 maior queda.')

    ordem_resumo = st.selectbox(
        'Ordenar por',
        ['Maior faturamento', 'Maior volume', 'Maior margem R$', 'Maior margem %',
         'Maior crescimento', 'Maior queda', 'Produto (A-Z)'],
        key='prod_ord_resumo')

    _ORDEM_CHAVE = {
        'Maior faturamento': ('faturamento', True), 'Maior volume': ('volume', True),
        'Maior margem R$': ('margem_rs', True), 'Maior margem %': ('margem_pct', True),
        'Produto (A-Z)': ('chave', False),
    }
    if ordem_resumo in _ORDEM_CHAVE:
        chave_ord, desc = _ORDEM_CHAVE[ordem_resumo]
        resumo_ordenado = sorted(ranking_full, key=lambda l: l.get(chave_ord) or 0, reverse=desc)
    elif ordem_resumo == 'Maior crescimento':
        com_cresc = [l for l in ranking_full if l.get('crescimento_pct') is not None]
        sem_cresc = [l for l in ranking_full if l.get('crescimento_pct') is None]
        resumo_ordenado = sorted(com_cresc, key=lambda l: l['crescimento_pct'], reverse=True) + sem_cresc
    else:  # Maior queda
        com_cresc = [l for l in ranking_full if l.get('crescimento_pct') is not None]
        sem_cresc = [l for l in ranking_full if l.get('crescimento_pct') is None]
        resumo_ordenado = sorted(com_cresc, key=lambda l: l['crescimento_pct']) + sem_cresc

    linhas_resumo = []
    for l in resumo_ordenado:
        if l['crescimento_pct'] is not None:
            cresc_fmt = _pct(l['crescimento_pct'])
        elif l['status_crescimento'] == 'novo':
            cresc_fmt = 'novo no período'
        else:
            cresc_fmt = 'n/d'
        linhas_resumo.append({
            '🏷️': _marca(l['chave']),
            'Produto': l['chave'], 'Grupo': l['categoria'], 'Quantidade (cx)': l['volume'],
            'Faturamento R$': l['faturamento'], '% do Faturamento': l['participacao_faturamento'],
            'Margem R$': l['margem_rs'], 'Margem %': l['margem_pct'],
            'Resultado Anterior': l['valor_anterior'] if l['valor_anterior'] is not None else 0.0,
            'Variação %': cresc_fmt,
        })
    df_resumo = pd.DataFrame(linhas_resumo)
    df_resumo.insert(0, '#', range(1, len(df_resumo) + 1))
    st.dataframe(
        df_resumo.style.format({
            'Quantidade (cx)': _qtd, 'Faturamento R$': _brl, '% do Faturamento': _pct,
            'Margem R$': _brl, 'Margem %': _pct, 'Resultado Anterior': _brl,
        }),
        use_container_width=True, hide_index=True)
    st.caption('"Resultado Anterior" e "Variação %" comparam o Faturamento com o mesmo tipo de período '
               'imediatamente anterior. Produtos sem venda no período anterior aparecem como "novo no período" '
               '(não é tratado como queda).')
    _botoes_exportar(df_resumo, 'produtos_resumo')

# ---- ENTREGA 2: Margem de Contribuição por Produto ------------------------
with tab_margem:
    st.subheader('2. Margem de Contribuição por Produto')
    st.caption(
        'Margem de Contribuição R$ = Faturamento − Custo. Margem de Contribuição % = Margem R$ ÷ Faturamento × 100. '
        'Faturamento zero, custo ausente ou valores inválidos resultam em margem 0,00 (nunca NaN, Infinity ou '
        'divisão por zero) -- ver rentabilidade.agregar().'
    )

    ordem_margem = st.selectbox('Ordenar tabela por', ['Maior margem R$', 'Maior margem %'], key='prod_ord_margem')
    chave_margem = 'margem_rs' if ordem_margem == 'Maior margem R$' else 'margem_pct'
    margem_ordenada = sorted(ranking_full, key=lambda l: l.get(chave_margem) or 0, reverse=True)

    linhas_margem = [{
        '🏷️': _marca(l['chave']),
        'Produto': l['chave'], 'Grupo': l['categoria'],
        'Faturamento R$': l['faturamento'], 'Custo R$': l['custo'],
        'Margem R$': l['margem_rs'], 'Margem %': l['margem_pct'], 'Quantidade (cx)': l['volume'],
    } for l in margem_ordenada]
    df_margem = pd.DataFrame(linhas_margem)
    df_margem.insert(0, '#', range(1, len(df_margem) + 1))
    st.dataframe(
        df_margem.style.format({
            'Faturamento R$': _brl, 'Custo R$': _brl, 'Margem R$': _brl,
            'Margem %': _pct, 'Quantidade (cx)': _qtd,
        }),
        use_container_width=True, hide_index=True)
    _botoes_exportar(df_margem, 'produtos_margem')

    st.divider()
    st.subheader('Ranking de Margem')
    criterio_rank_margem = st.radio('Critério', ['Maior margem R$', 'Maior margem %'],
                                     horizontal=True, key='prod_rank_margem_crit')
    chave_rm = 'margem_rs' if criterio_rank_margem == 'Maior margem R$' else 'margem_pct'
    fmt_rm = _brl if chave_rm == 'margem_rs' else _pct
    n_rm = st.slider('Quantidade em cada lista', 3, 30, 10, key='prod_rank_margem_n')
    com_margem = sorted(ranking_full, key=lambda l: l.get(chave_rm) or 0, reverse=True)
    maiores_margem = com_margem[:n_rm]
    menores_margem = list(reversed(com_margem[-n_rm:])) if len(com_margem) > n_rm else list(reversed(com_margem))
    colmax, colmin = st.columns(2)
    with colmax:
        st.markdown(f'**🔝 Maior margem — {criterio_rank_margem}**')
        df_maior = pd.DataFrame([{'Produto': l['chave'], criterio_rank_margem: l.get(chave_rm)}
                                  for l in maiores_margem])
        st.dataframe(df_maior.style.format({criterio_rank_margem: fmt_rm}), use_container_width=True, hide_index=True)
    with colmin:
        st.markdown(f'**🔻 Menor margem — {criterio_rank_margem}**')
        df_menor = pd.DataFrame([{'Produto': l['chave'], criterio_rank_margem: l.get(chave_rm)}
                                  for l in menores_margem])
        st.dataframe(df_menor.style.format({criterio_rank_margem: fmt_rm}), use_container_width=True, hide_index=True)
    st.caption('Margem R$ e Margem % medem coisas diferentes: um produto pode ter margem % alta mas gerar '
               'pouca margem absoluta (baixo volume/faturamento), e vice-versa. Use o critério acima para '
               'alternar entre as duas visões.')

    if maiores_margem:
        st.markdown(f'**Gráfico — Top {min(n_rm, len(maiores_margem))} produtos por {criterio_rank_margem.lower()}**')
        df_chart_m = pd.DataFrame([{'Produto': l['chave'], criterio_rank_margem: l.get(chave_rm)}
                                    for l in maiores_margem]).set_index('Produto')
        st.bar_chart(df_chart_m, color='#B08900')

    st.divider()
    st.subheader('📊 Comparativo de Margem vs Período Anterior')
    if not itens_filtrados_ant:
        st.info(f'Sem dado disponível em {periodo_mod.rotulo(tipo_periodo, periodo_ant_ref)} para comparar.')
    else:
        produtos_com_comp = [l for l in ranking_full if l['margem_pct_anterior'] is not None]
        if not produtos_com_comp:
            st.info('Nenhum produto do recorte atual também teve venda no período anterior.')
        else:
            produto_spot = st.selectbox('Ver detalhe de um produto', [l['chave'] for l in produtos_com_comp],
                                         key='prod_margem_spotlight')
            l_spot = next(l for l in produtos_com_comp if l['chave'] == produto_spot)
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric('Margem atual', _pct(l_spot['margem_pct']))
            sc2.metric('Margem anterior', _pct(l_spot['margem_pct_anterior']))
            sc3.metric('Variação', _pp(l_spot['margem_pct_variacao_pp']))

            df_comp_margem = pd.DataFrame([{
                'Produto': l['chave'], 'Margem Atual %': l['margem_pct'],
                'Margem Anterior %': l['margem_pct_anterior'], 'Variação (p.p.)': l['margem_pct_variacao_pp'],
                'Margem R$ Atual': l['margem_rs'], 'Margem R$ Anterior': l['margem_rs_anterior'],
            } for l in sorted(produtos_com_comp, key=lambda l: l['margem_pct_variacao_pp'], reverse=True)])
            df_comp_margem.insert(0, '#', range(1, len(df_comp_margem) + 1))
            st.dataframe(
                df_comp_margem.style.format({
                    'Margem Atual %': _pct, 'Margem Anterior %': _pct, 'Variação (p.p.)': _pp,
                    'Margem R$ Atual': _brl, 'Margem R$ Anterior': _brl,
                }),
                use_container_width=True, hide_index=True)
            st.caption(f'Base de comparação: {periodo_mod.rotulo(tipo_periodo, periodo_ant_ref)}. '
                       'Variação de margem % é sempre em pontos percentuais (p.p.), não em variação percentual comum.')
            _botoes_exportar(df_comp_margem, 'produtos_margem_comparativo')

# ---- ENTREGA 3: Drill-down por Grupo de Produtos ---------------------------
with tab_drill:
    st.subheader('3. Drill-down por Grupo de Produtos')
    st.caption('Grupo → Produto → Vendedor/Cliente. Os filtros gerais da página continuam aplicados em '
               'todos os níveis. "Grupo" = Grupo oficial do ERP, como vem no Resumo do Estoque '
               '(não é mais o chute por palavra-chave de categorias.py). "Cliente" não existe nesta '
               'fonte de dados (o Resumo do Estoque não detalha por cliente) -- só o vendedor '
               '(Complemento/consignatário) fica disponível; ver observação no Nível 3.')

    grupos_full = pr.ranking_categorias_com_crescimento(itens_filtrados, itens_filtrados_ant or None)
    grupos_ordenados = sorted(grupos_full, key=lambda l: -l['faturamento'])

    st.markdown('**Nível 1 — Grupos**')
    linhas_grupo = [{
        'Grupo': l['chave'], 'Quantidade (cx)': l['volume'], 'Faturamento R$': l['faturamento'],
        'Margem R$': l['margem_rs'], 'Margem %': l['margem_pct'],
        '% do Faturamento': l['participacao_faturamento'],
        'Variação %': (_pct(l['crescimento_pct']) if l['crescimento_pct'] is not None
                       else ('novo no período' if l['status_crescimento'] == 'novo' else 'n/d')),
    } for l in grupos_ordenados]
    df_grupo = pd.DataFrame(linhas_grupo)
    df_grupo.insert(0, '#', range(1, len(df_grupo) + 1))
    st.dataframe(
        df_grupo.style.format({
            'Quantidade (cx)': _qtd, 'Faturamento R$': _brl, 'Margem R$': _brl,
            'Margem %': _pct, '% do Faturamento': _pct,
        }),
        use_container_width=True, hide_index=True)
    _botoes_exportar(df_grupo, 'produtos_grupos')

    if grupos_ordenados:
        st.markdown('**Gráfico — Participação dos grupos no faturamento**')
        df_chart_g = pd.DataFrame([{'Grupo': l['chave'], '% do Faturamento': l['participacao_faturamento']}
                                    for l in grupos_ordenados]).set_index('Grupo')
        st.bar_chart(df_chart_g, color='#2D6A4F')

    st.divider()
    st.markdown('**Nível 2 — Produtos do Grupo**')
    nomes_grupos = ['— Selecione um grupo —'] + [l['chave'] for l in grupos_ordenados]
    grupo_sel = st.selectbox('Grupo', nomes_grupos, key='prod_drill_grupo')

    if grupo_sel == '— Selecione um grupo —':
        st.info('Selecione um grupo acima para ver os produtos que o compõem.')
    else:
        produtos_grupo = [l for l in ranking_full if l['categoria'] == grupo_sel]
        produtos_grupo = sorted(produtos_grupo, key=lambda l: -l['faturamento'])
        if not produtos_grupo:
            st.info(f'Nenhum produto do grupo "{grupo_sel}" neste recorte.')
        else:
            linhas_pg = [{
                'Produto': l['chave'], 'Quantidade (cx)': l['volume'], 'Faturamento R$': l['faturamento'],
                'Margem R$': l['margem_rs'], 'Margem %': l['margem_pct'],
                '% do Faturamento': l['participacao_faturamento'],
            } for l in produtos_grupo]
            df_pg = pd.DataFrame(linhas_pg)
            df_pg.insert(0, '#', range(1, len(df_pg) + 1))
            st.dataframe(
                df_pg.style.format({
                    'Quantidade (cx)': _qtd, 'Faturamento R$': _brl, 'Margem R$': _brl,
                    'Margem %': _pct, '% do Faturamento': _pct,
                }),
                use_container_width=True, hide_index=True)
            _botoes_exportar(df_pg, f'produtos_grupo_{grupo_sel}')

            st.divider()
            st.markdown('**Nível 3 — Detalhamento por Vendedor / Cliente**')
            nomes_produtos_grupo = ['— Selecione um produto —'] + [l['chave'] for l in produtos_grupo]
            produto_sel_drill = st.selectbox('Produto', nomes_produtos_grupo, key='prod_drill_produto')
            if produto_sel_drill == '— Selecione um produto —':
                st.info('Selecione um produto acima para ver o detalhamento por vendedor e cliente.')
            else:
                itens_produto_drill = [it for it in itens_filtrados if it.get('produto') == produto_sel_drill]
                dv1, dv2 = st.columns(2)
                with dv1:
                    st.markdown(f'**Vendedores de "{produto_sel_drill}"**')
                    vends_drill = sorted(pr.por_vendedor(itens_produto_drill), key=lambda v: -v['faturamento'])
                    df_vd = pd.DataFrame([{'Vendedor': v['chave'], 'Quantidade (cx)': v['volume'],
                                            'Faturamento R$': v['faturamento'], 'Margem R$': v['margem_rs']}
                                           for v in vends_drill])
                    if df_vd.empty:
                        st.caption('Sem dados de vendedor para este produto no recorte.')
                    else:
                        st.dataframe(df_vd.style.format({'Quantidade (cx)': _qtd, 'Faturamento R$': _brl,
                                                           'Margem R$': _brl}),
                                     use_container_width=True, hide_index=True)
                with dv2:
                    st.markdown(f'**Clientes de "{produto_sel_drill}"**')
                    st.caption('⚠️ Campo que não existe na base: o Resumo do Estoque não detalha vendas '
                               'por cliente (só por produto/grupo/consignatário). Este detalhamento fica '
                               'disponível quando a fonte de dados tiver cliente -- ver aba Vendedor-Cliente.')
                    clis_drill = sorted(pr.por_cliente(itens_produto_drill), key=lambda c: -c['faturamento'])
                    clis_drill = [c for c in clis_drill if c['chave'] != '(não identificado)']
                    df_cd = pd.DataFrame([{'Cliente': c['chave'], 'Quantidade (cx)': c['volume'],
                                            'Faturamento R$': c['faturamento'], 'Margem R$': c['margem_rs']}
                                          for c in clis_drill])
                    if df_cd.empty:
                        st.caption('Sem dados de cliente para este produto no recorte.')
                    else:
                        st.dataframe(df_cd.style.format({'Quantidade (cx)': _qtd, 'Faturamento R$': _brl,
                                                           'Margem R$': _brl}),
                                     use_container_width=True, hide_index=True)
                if st.button('🔙 Voltar para a lista de grupos', key='prod_drill_voltar'):
                    st.session_state['prod_drill_grupo'] = '— Selecione um grupo —'
                    st.session_state['prod_drill_produto'] = '— Selecione um produto —'
                    st.rerun()

# ---- ENTREGA 4: Produtos Mais Trabalhados ----------------------------------
with tab_trabalhados:
    st.subheader('4. Produtos Mais Trabalhados')
    st.caption(
        '"Mais trabalhado" é sobre presença comercial, não sobre faturamento ou margem (isso já está nas '
        'entregas 1 e 2). Usa só o que existe na base: nº de clientes distintos, nº de vendedores distintos '
        'e frequência (nº de datas distintas com venda no recorte). ⚠️ Campo que não existe nesta fonte: o '
        'Resumo do Estoque não detalha por cliente, então "Nº de Clientes" fica sempre 0 -- o Índice de '
        'Presença aqui reflete, na prática, Nº de Vendedores (consignatários) e Frequência (em quantos meses '
        'distintos, com Resumo do Estoque salvo, o produto teve saída). O "Índice de Presença Comercial" combina '
        'as três dimensões (cada uma normalizada pelo maior valor do recorte, média das três em escala 0-100) '
        '-- não é uma métrica de negócio validada, é só uma forma transparente de ordenar; você também pode '
        'ordenar por qualquer dimensão bruta abaixo.'
    )

    mais_trabalhados = pr.produtos_mais_trabalhados(itens_filtrados)
    ordem_mt = st.selectbox(
        'Ordenar por',
        ['Índice de Presença Comercial', 'Nº de Clientes', 'Nº de Vendedores', 'Frequência',
         'Quantidade (Volume)', 'Faturamento'],
        key='prod_ord_trabalhados')
    _ORDEM_MT = {
        'Índice de Presença Comercial': 'indice_presenca', 'Nº de Clientes': 'n_clientes',
        'Nº de Vendedores': 'n_vendedores', 'Frequência': 'frequencia',
        'Quantidade (Volume)': 'volume', 'Faturamento': 'faturamento',
    }
    mt_ordenado = sorted(mais_trabalhados, key=lambda l: l.get(_ORDEM_MT[ordem_mt]) or 0, reverse=True)

    linhas_mt = [{
        'Produto': l['chave'], 'Grupo': l.get('categoria', '-'), 'Quantidade (cx)': l.get('volume', 0.0),
        'Faturamento R$': l.get('faturamento', 0.0), 'Nº Clientes': l['n_clientes'],
        'Nº Vendedores': l['n_vendedores'], 'Frequência (dias)': l['frequencia'],
        'Margem R$': l.get('margem_rs', 0.0), '% do Faturamento': l.get('participacao_faturamento', 0.0),
        'Índice de Presença': l['indice_presenca'],
    } for l in mt_ordenado]
    df_mt = pd.DataFrame(linhas_mt)
    df_mt.insert(0, '#', range(1, len(df_mt) + 1))
    st.dataframe(
        df_mt.style.format({
            'Quantidade (cx)': _qtd, 'Faturamento R$': _brl, 'Margem R$': _brl,
            '% do Faturamento': _pct, 'Índice de Presença': lambda v: f'{v:.1f}',
        }),
        use_container_width=True, hide_index=True)
    _botoes_exportar(df_mt, 'produtos_mais_trabalhados')

    if mt_ordenado:
        n_chart_mt = min(15, len(mt_ordenado))
        st.markdown(f'**Ranking — Top {n_chart_mt} por {ordem_mt.lower()}**')
        df_chart_mt = pd.DataFrame([
            {'Produto': l['chave'], ordem_mt: l.get(_ORDEM_MT[ordem_mt]) or 0}
            for l in mt_ordenado[:n_chart_mt]
        ]).set_index('Produto')
        st.bar_chart(df_chart_mt, color='#6A4C93')

# ---- Top / Atenção / Crescimento ----------------------------------------
# ---- Top / Atenção / Crescimento ----------------------------------------
with tab_top:
    st.subheader('Top Produtos')
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
    metrica_evo = st.radio('Métrica', ['Faturamento', 'Volume', 'Margem R$', 'Margem %'],
                            horizontal=True, key='prod_evo_metrica')
    grans_validas = _GRAN_POR_TIPO.get(tipo_periodo, ['dia', 'semana', 'mes'])
    gran_evo = st.radio('Granularidade', grans_validas, format_func=lambda g: _GRAN_LABELS[g],
                         horizontal=True, key='prod_evo_gran')

    _METRICA_EVO_CHAVE = {'Faturamento': 'faturamento', 'Volume': 'volume',
                           'Margem R$': 'margem_rs', 'Margem %': 'margem_pct'}

    if not produtos_evo:
        st.info('Selecione ao menos um produto para ver a evolução.')
    else:
        serie_map = pr.evolucao_por_produto(
            itens_filtrados, produtos_evo, granularidade=gran_evo,
            metrica=_METRICA_EVO_CHAVE[metrica_evo])
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
            fmt_evo = {'Faturamento': _brl, 'Volume': _qtd, 'Margem R$': _brl, 'Margem %': _pct}[metrica_evo]
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
    st.caption('⚠️ Campo que não existe na base: o Resumo do Estoque não detalha por cliente, então tudo '
               'cai em "(não identificado)" aqui. Use a aba Vendedor-Cliente/Gerência para análise por cliente.')
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
    st.caption('⚠️ "Cliente" não existe nesta fonte de dados (Resumo do Estoque) -- use "Vendedor" '
               '(consignatário/Complemento do relatório).')
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
        ranking_snap = ranking_full
        grupos_snap = pr.ranking_categorias_com_crescimento(itens_filtrados, itens_filtrados_ant or None)
        trabalhados_snap = pr.produtos_mais_trabalhados(itens_filtrados)
        snapshot = {
            'periodo': periodo_mod.rotulo(tipo_periodo, periodo_ref_sel),
            'tipo_periodo': tipo_periodo, 'periodo_ref': periodo_ref_sel,
            'usuario': st.session_state.get('usuario_nome', 'Ingrid'),
            'filtros': {
                'produtos': f_produtos, 'categorias': f_categorias,
                'vendedores': f_vendedores, 'clientes': f_clientes,
            },
            'kpis': kpi_atual,
            'destaques': {k: (v['chave'] if isinstance(v, dict) else v) for k, v in dest.items()} if dest else {},
            # Entrega 1 — Resumo por Produto (top 10 por faturamento)
            'top_produtos': sorted(ranking_snap, key=lambda l: l['faturamento'], reverse=True)[:10],
            # Entrega 2 — Margem de Contribuição (top 10 por margem R$)
            'top_margem': sorted(ranking_snap, key=lambda l: l['margem_rs'], reverse=True)[:10],
            # Entrega 3 — Drill-down por Grupo (resumo por grupo, todos)
            'grupos': grupos_snap,
            # Entrega 4 — Mais Trabalhados (top 10 por índice de presença)
            'mais_trabalhados': trabalhados_snap[:10],
        }
        registro = ds.save_record(modulo=MODULO, tipo_periodo=tipo_periodo,
                                   periodo_ref=periodo_ref_sel, valores=snapshot,
                                   usuario=st.session_state.get('usuario_nome', 'Ingrid'))
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
            hc1, hc2, hc3, hc4, hc5 = st.columns(5)
            hc1.metric('SKUs', k.get('skus', 0))
            hc2.metric('Volume', _qtd(k.get('volume', 0)))
            hc3.metric('Faturamento', _brl(k.get('faturamento', 0)))
            hc4.metric('Margem R$', _brl(k.get('margem_rs', 0)))
            hc5.metric('Produto Líder', k.get('produto_lider') or '-')
            flt = v.get('filtros', {})
            partes = [f"{lbl}: {', '.join(vals)}" for lbl, vals in
                      [('Produto', flt.get('produtos') or []), ('Categoria', flt.get('categorias') or []),
                       ('Vendedor', flt.get('vendedores') or []), ('Cliente', flt.get('clientes') or [])]
                      if vals]
            st.caption('Filtros aplicados nesta versão: ' + ('; '.join(partes) if partes else 'nenhum (todos)') +
                       f" · Salvo por: {v.get('usuario', 'não identificado')}")

            top_v = v.get('top_produtos') or []
            top_margem_v = v.get('top_margem') or []
            grupos_v = v.get('grupos') or []
            trabalhados_v = v.get('mais_trabalhados') or []

            hv1, hv2, hv3, hv4 = st.tabs(['1. Resumo (top 10)', '2. Margem (top 10)',
                                           '3. Grupos', '4. Mais Trabalhados (top 10)'])
            with hv1:
                if top_v:
                    df_hv = _tabela_dim(top_v, 'Produto', ['#', 'Produto', 'Faturamento R$', 'Volume (cx)'])
                    st.dataframe(_estilo(df_hv), use_container_width=True, hide_index=True)
                else:
                    st.caption('Esta versão foi salva antes desta seção existir -- sem dado.')
            with hv2:
                if top_margem_v:
                    df_hm = _tabela_dim(top_margem_v, 'Produto',
                                         ['#', 'Produto', 'Margem R$', 'Margem %', 'Faturamento R$'])
                    st.dataframe(_estilo(df_hm), use_container_width=True, hide_index=True)
                else:
                    st.caption('Esta versão foi salva antes desta seção existir -- sem dado.')
            with hv3:
                if grupos_v:
                    df_hg = _tabela_dim(grupos_v, 'Grupo',
                                         ['#', 'Grupo', 'Faturamento R$', 'Margem R$', 'Margem %',
                                          '% do Faturamento'])
                    st.dataframe(_estilo(df_hg), use_container_width=True, hide_index=True)
                else:
                    st.caption('Esta versão foi salva antes desta seção existir -- sem dado.')
            with hv4:
                if trabalhados_v:
                    df_ht = pd.DataFrame([{'Produto': l['chave'], 'Nº Clientes': l.get('n_clientes'),
                                            'Nº Vendedores': l.get('n_vendedores'),
                                            'Frequência': l.get('frequencia'),
                                            'Índice de Presença': l.get('indice_presenca')}
                                          for l in trabalhados_v])
                    st.dataframe(df_ht, use_container_width=True, hide_index=True)
                else:
                    st.caption('Esta versão foi salva antes desta seção existir -- sem dado.')
