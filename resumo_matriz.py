"""Matriz Produto × Vendedor agrupada por prioridade -- a mesma visão do
'Resumo Geral' (PDF gerado em pdfgen.generate_resumo_geral). Extraído para
cá para ter UMA SÓ implementação usada tanto na prévia de Metas Semanais
(antes de fechar a semana) quanto na tela de Fechamentos Semanais da
Gerência (depois de fechada) -- duas cópias divergentes foi exatamente o
tipo de bug que já mordeu esse app antes (ver calc.map_vendedor), então
aqui fica centralizado.

`resultados` é a lista no formato de calc.compute_metas() / salvo em
'produtos' pelo fechamento: [{'produto', 'estoque_total', 'prioridade',
'linhas': [{'vendedor', 'meta', 'vendido', 'atingido', ...}, ...]}, ...]

Renderizado como UMA tabela HTML única (pedido explícito da Ingrid,
28/08/2026: "preciso que dê para abrir num todo" -- antes cada grupo de
prioridade e o Total Geral eram st.dataframe SEPARADOS, cada um com seu
próprio scroll/estado, o que quebrava a visão de conjunto), com as MESMAS
cores por prioridade e do Total Geral usadas no PDF (pdfgen._PRIO_BG_RG /
_PRIO_TITLE_COLOR_RG / HEADER_BG), pra ficar visualmente igual ao PDF
("quero que a visibilidade melhore, que fique igual quando emitimos o PDF
do resumo, com cor e tudo mais"). Os NÚMEROS e a lógica de cálculo em si
não mudaram nada aqui -- só a apresentação.
"""
import html as _html

import streamlit as st

_PRIO_KEYS = ['🚨 Grande Urgência', '🔥 Alta Prioridade', 'Normal']

# Mesmas cores do PDF (pdfgen.py: _PRIO_BG_RG / _PRIO_TITLE_COLOR_RG / HEADER_BG).
_PRIO_BG_HTML = {
    '🚨 Grande Urgência': '#922b21',
    '🔥 Alta Prioridade':  '#784212',
    'Normal':              '#2c3e50',
}
_PRIO_LABEL = {
    '🚨 Grande Urgência': 'GRANDE URGÊNCIA',
    '🔥 Alta Prioridade':  'ALTA PRIORIDADE',
    'Normal':              'NORMAL',
}
_SUBTOTAL_BG = '#dfe6e9'   # mesma cor do PDF (linha SUBTOTAL)
_TOTAL_BG    = '#1B4332'   # mesmo verde OTHIL do PDF (linha TOTAL GERAL)
_ZEBRA_BG    = '#f4f6f7'   # mesma cor do PDF (LIGHT_BG, linhas alternadas)
_HEADER_BG   = '#2D6A4F'   # verde OTHIL do cabeçalho de coluna (padrão do app)


def _vendedores_de(resultados: list) -> list:
    """Lista de vendedores na ordem em que aparecem no primeiro produto
    (mesma ordem configurada em Percentuais dos Vendedores); usa a união
    de todos os produtos como fallback caso o primeiro esteja incompleto."""
    for r in resultados:
        linhas = r.get('linhas') or []
        if linhas:
            return [l['vendedor'] for l in linhas]
    return sorted({l['vendedor'] for r in resultados for l in r.get('linhas', [])})


def _esc(v) -> str:
    return _html.escape(str(v))


def render_matriz_produto_vendedor(resultados: list, titulo: str = 'Resumo Geral — Matriz Produto × Vendedor'):
    """Renderiza a matriz Produto × Vendedor, agrupada por prioridade com
    linha de SUBTOTAL por grupo -- igual ao PDF Resumo Geral, numa tabela
    HTML única (não mais vários st.dataframe separados).

    Cada célula de vendedor mostra SÓ o vendido (pedido explícito da
    Ingrid: célula com vendido/meta/% junto ficava poluída). A meta de cada
    linha/subtotal fica na coluna 'Qtde', o vendido total na coluna
    'Vendido Total' e o percentual na coluna '% Atingido' -- SEM combinar
    vendido/meta no mesmo campo (ex.: "275/618"), também por pedido
    explícito da Ingrid. 'Qtde' sempre usa a meta REAL do produto
    ('estoque_total'), nunca a soma das metas individuais dos vendedores
    (ver correção de meta geral)."""
    if not resultados:
        st.info('Sem dados para montar o Resumo Geral.')
        return

    vendedores = _vendedores_de(resultados)
    if not vendedores:
        st.info('Sem dados para montar o Resumo Geral.')
        return

    st.markdown(f'**{titulo}**')

    grupos_prio: dict = {}
    for r in resultados:
        prio = r.get('prioridade', 'Normal')
        grupos_prio.setdefault(prio, []).append(r)

    n_cols = 2 + len(vendedores) + 2  # Produto, Qtde, [vendedores...], Vendido Total, % Atingido

    linhas_html = []

    # Cabeçalho de coluna único (fixo pro topo da tabela inteira, verde
    # OTHIL padrão do app -- as cores por prioridade do PDF entram como
    # linhas de seção logo abaixo, não substituem este cabeçalho).
    ths = ['<th style="padding:6px 8px; text-align:left;">Produto</th>',
           '<th style="padding:6px 8px; text-align:center;">Qtde</th>']
    for v in vendedores:
        ths.append(f'<th style="padding:6px 8px; text-align:center;">{_esc(v)}</th>')
    ths.append('<th style="padding:6px 8px; text-align:center;">Vendido Total</th>')
    ths.append('<th style="padding:6px 8px; text-align:center;">% Atingido</th>')
    linhas_html.append(
        f'<tr style="background:{_HEADER_BG}; color:white;">' + ''.join(ths) + '</tr>'
    )

    def _td(v, align='center', bold=False):
        weight = 'font-weight:600;' if bold else ''
        return f'<td style="padding:5px 8px; text-align:{align}; {weight}">{_esc(v)}</td>'

    for prio_key in _PRIO_KEYS:
        grupo = grupos_prio.get(prio_key)
        if not grupo:
            continue
        prio_bg = _PRIO_BG_HTML[prio_key]

        # Linha de seção (cor igual ao PDF pra essa prioridade)
        linhas_html.append(
            f'<tr style="background:{prio_bg}; color:white;">'
            f'<td colspan="{n_cols}" style="padding:6px 8px; font-weight:700;">'
            f'{_esc(_PRIO_LABEL[prio_key])}</td></tr>'
        )

        for i, r in enumerate(grupo):
            p_meta = r.get('estoque_total', 0)
            p_vend = 0.0
            linhas_por_vend = {l['vendedor']: l for l in r.get('linhas', [])}
            zebra = _ZEBRA_BG if i % 2 == 1 else 'white'
            cells = [_td(r['produto'], align='left')]
            cells.append(_td(f"{p_meta:.0f}"))
            for v in vendedores:
                l = linhas_por_vend.get(v)
                if l:
                    cells.append(_td(f"{l['vendido']:.0f}"))
                    p_vend += l['vendido']
                else:
                    cells.append(_td('-'))
            cells.append(_td(f"{p_vend:.0f}"))
            pct_txt = f"{p_vend/p_meta*100:.0f}%" if p_meta else '—'
            cells.append(_td(pct_txt))
            linhas_html.append(f'<tr style="background:{zebra};">' + ''.join(cells) + '</tr>')

        # Linha de SUBTOTAL -- mesma regra: a meta do grupo (coluna Qtde) usa
        # a soma do 'estoque_total' real dos produtos do grupo, não a soma
        # das metas individuais. Já a meta de CADA vendedor continua sendo a
        # soma das metas dele mesmo nos produtos do grupo.
        gm = sum(r.get('estoque_total', 0) for r in grupo)
        sub_cells = [_td('SUBTOTAL', align='left', bold=True), _td(f"{gm:.0f}", bold=True)]
        for v in vendedores:
            sv = sum(l['vendido'] for r in grupo for l in r.get('linhas', []) if l['vendedor'] == v)
            sub_cells.append(_td(f"{sv:.0f}", bold=True))
        gv = sum(l['vendido'] for r in grupo for l in r.get('linhas', []))
        sub_cells.append(_td(f"{gv:.0f}", bold=True))
        sub_pct = f"{gv/gm*100:.0f}%" if gm else '—'
        sub_cells.append(_td(sub_pct, bold=True))
        linhas_html.append(f'<tr style="background:{_SUBTOTAL_BG};">' + ''.join(sub_cells) + '</tr>')

    # Total Geral -- soma de todos os grupos de prioridade juntos. Mesma
    # regra: meta geral = soma do 'estoque_total' real de todos os produtos,
    # não a soma das metas individuais dos vendedores. Mesma cor do PDF
    # (verde OTHIL escuro).
    gm_all = sum(r.get('estoque_total', 0) for r in resultados)
    tot_cells = [
        '<td style="padding:6px 8px; text-align:left; font-weight:700;">TOTAL GERAL</td>',
        f'<td style="padding:6px 8px; text-align:center; font-weight:700;">{gm_all:.0f}</td>',
    ]
    for v in vendedores:
        tv = sum(l['vendido'] for r in resultados for l in r.get('linhas', []) if l['vendedor'] == v)
        tot_cells.append(f'<td style="padding:6px 8px; text-align:center; font-weight:700;">{tv:.0f}</td>')
    gv_all = sum(l['vendido'] for r in resultados for l in r.get('linhas', []))
    tot_cells.append(f'<td style="padding:6px 8px; text-align:center; font-weight:700;">{gv_all:.0f}</td>')
    tot_pct = f"{gv_all/gm_all*100:.0f}%" if gm_all else '—'
    tot_cells.append(f'<td style="padding:6px 8px; text-align:center; font-weight:700;">{tot_pct}</td>')
    linhas_html.append(
        f'<tr style="background:{_TOTAL_BG}; color:white;">' + ''.join(tot_cells) + '</tr>'
    )

    table_html = (
        '<div style="overflow-x:auto;">'
        '<table style="width:100%; border-collapse:collapse; font-size:0.85rem;">'
        + ''.join(linhas_html) +
        '</table></div>'
    )
    st.markdown(table_html, unsafe_allow_html=True)
