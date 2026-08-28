"""Matriz Produto × Vendedor agrupada por prioridade -- a mesma visão do
'Resumo Geral' (PDF gerado em pdfgen.generate_resumo_geral). Extraído para
cá para ter UMA SÓ implementação usada tanto na prévia de Metas Semanais
(antes de fechar a semana) quanto na tela de Fechamentos Semanais da
Gerência (depois de fechada) -- duas cópias divergentes foi exatamente o
tipo de bug que já mordeu esse app antes (ver calc.map_vendedor), então
aqui fica centralizado.

`resultados` é a lista no formato de calc.compute_metas() / salvo em
'produtos' pelo fechamento: [{'produto', 'estoque_total', 'prioridade',
'linhas': [{'vendedor', 'meta', 'vendido', 'atingido', ...}, ...],
'media_rs_cx', 'media_rs_cx_soma_ponderada', 'media_rs_cx_peso',
'media_custo_cx', 'media_custo_cx_soma_ponderada', 'media_custo_cx_peso'},
...] ('media_rs_cx*'/'media_custo_cx*' podem não existir em fechamentos
salvos antes desses campos existirem -- sempre acessados via .get() com
fallback, nunca inventados.)

Renderizado como um bloco HTML único (pedido explícito da Ingrid,
28/08/2026: "preciso que dê para abrir num todo" -- antes cada grupo de
prioridade e o Total Geral eram st.dataframe SEPARADOS, cada um com seu
próprio scroll/estado, o que quebrava a visão de conjunto), replicando a
MESMA estrutura visual do PDF Resumo Geral (pdfgen._build_resumo_geral,
28/08/2026: Ingrid mandou print do PDF e confirmou "Assim é no PDF, e
assim preciso que fique"): uma linha de totais gerais no topo, e um mini
bloco por prioridade -- título colorido + tabela própria com cabeçalho
colorido (Produto/Qtde/vendedores/TOTAL[Vend,%,Venda Méd/cx,Custo Méd/cx])
e linha de SUBTOTAL -- seguido da tabela TOTAL GERAL (verde OTHIL). Mesmas
cores/fórmulas do PDF (pdfgen._PRIO_BG_RG / _PRIO_TITLE_COLOR_RG / _totais
/ _produto_totais / _subtotal_row). A coluna 'Custo Méd/cx' foi adicionada
depois (28/08/2026, pedido explícito da Ingrid: "Preciso que tenha a média
de custo e a média de venda R$"), usando o mesmo padrão de média ponderada
de 'media_rs_cx' (calc.compute_metas -- ver 'media_custo_cx'). Os NÚMEROS
e a lógica de cálculo em si não mudaram nada aqui -- só a apresentação,
agora tudo num bloco só (sem exigir abrir/rolar cada grupo separadamente)."""
import html as _html

import streamlit as st

_PRIO_KEYS = ['🚨 Grande Urgência', '🔥 Alta Prioridade', 'Normal']

# Mesmas cores do PDF (pdfgen.py: _PRIO_BG_RG / _PRIO_TITLE_COLOR_RG).
_PRIO_BG_HTML = {
    '🚨 Grande Urgência': '#922b21',
    '🔥 Alta Prioridade':  '#784212',
    'Normal':              '#2c3e50',
}
_PRIO_TITLE_COLOR = {
    '🚨 Grande Urgência': '#922b21',
    '🔥 Alta Prioridade':  '#784212',
    'Normal':              '#1B4332',
}
_PRIO_LABEL = {
    '🚨 Grande Urgência': 'GRANDE URGÊNCIA',
    '🔥 Alta Prioridade':  'ALTA PRIORIDADE',
    'Normal':              'NORMAL',
}
_SUBTOTAL_BG = '#dfe6e9'   # mesma cor do PDF (linha SUBTOTAL)
_TOTAL_BG    = '#1B4332'   # mesmo verde OTHIL do PDF (linha/tabela TOTAL GERAL)
_ZEBRA_BG    = '#f4f6f7'   # mesma cor do PDF (LIGHT_BG, linhas alternadas)


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


def _num(v, casas: int = 0) -> str:
    """Formata número no padrão BR (ponto de milhar, vírgula decimal) --
    mesma lógica de pdfgen._num."""
    return f"{v:,.{casas}f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def _fmt_money(v) -> str:
    """Mesma lógica de pdfgen._fmt_money."""
    return f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def _fmt_pct(v) -> str:
    """`v` é fração (0-1) -- mesma lógica de pdfgen._fmt_pct."""
    return f"{v * 100:.1f}%"


def _media_rs_cx_grupo(group: list):
    """Média ponderada de Venda R$/cx do grupo -- soma dos R$ ponderados ÷
    soma dos pesos (nunca a média simples das médias de cada produto, que
    distorceria quando os produtos têm volumes bem diferentes). None
    quando nenhum produto do grupo tem essa informação (PDF de Estoque
    Físico não enviado, ou fechamento salvo antes desse campo existir)."""
    fat = sum(r.get('media_rs_cx_soma_ponderada', 0.0) or 0.0 for r in group)
    peso = sum(r.get('media_rs_cx_peso', 0.0) or 0.0 for r in group)
    return (fat / peso) if peso else None


def _media_custo_cx_grupo(group: list):
    """Mesma lógica de _media_rs_cx_grupo, mas para o custo unitário médio
    ponderado do grupo (calc.compute_metas: 'media_custo_cx*')."""
    fat = sum(r.get('media_custo_cx_soma_ponderada', 0.0) or 0.0 for r in group)
    peso = sum(r.get('media_custo_cx_peso', 0.0) or 0.0 for r in group)
    return (fat / peso) if peso else None


def render_matriz_produto_vendedor(resultados: list, titulo: str = 'Resumo Geral — Matriz Produto × Vendedor'):
    """Renderiza a matriz Produto × Vendedor, agrupada por prioridade com
    linha de SUBTOTAL por grupo e tabela final TOTAL GERAL -- igual ao PDF
    Resumo Geral (pdfgen._build_resumo_geral), num bloco HTML único (não
    mais vários st.dataframe separados).

    Cada célula de vendedor mostra SÓ o vendido (pedido explícito da
    Ingrid: célula com vendido/meta/% junto ficava poluída). A meta de
    cada linha/subtotal fica na coluna 'Qtde', e a coluna 'TOTAL' traz
    Vendido/%/Venda Méd por caixa/Custo Méd por caixa -- SEM combinar
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

    def _td(v, align='center', bold=False, color=None):
        weight = 'font-weight:700;' if bold else ''
        col = f'color:{color};' if color else ''
        return f'<td style="padding:5px 8px; text-align:{align}; {weight}{col}">{_esc(v)}</td>'

    def _th(v, align='center', colspan=1, rowspan=1):
        extra = ''
        if colspan > 1:
            extra += f' colspan="{colspan}"'
        if rowspan > 1:
            extra += f' rowspan="{rowspan}"'
        return f'<th style="padding:6px 8px; text-align:{align};"{extra}>{_esc(v)}</th>'

    def _header_rows(bg):
        r1 = (f'<tr style="background:{bg}; color:white;">'
              + _th('Produto', align='left', rowspan=2)
              + _th('Qtde', rowspan=2))
        for v in vendedores:
            r1 += _th(v, rowspan=2)
        r1 += _th('TOTAL', colspan=4) + '</tr>'
        r2 = (f'<tr style="background:{bg}; color:white;">'
              + _th('Vend') + _th('%') + _th('Venda Méd/cx') + _th('Custo Méd/cx') + '</tr>')
        return r1 + r2

    def _linhas_grupo(group):
        rows_html = []
        for i, r in enumerate(group):
            p_meta = r.get('estoque_total', 0)
            linhas_por_vend = {l['vendedor']: l for l in r.get('linhas', [])}
            p_vend = sum(l['vendido'] for l in r.get('linhas', []))
            zebra = _ZEBRA_BG if i % 2 == 1 else 'white'
            cells = [_td(r['produto'], align='left'), _td(f"{p_meta:.0f}")]
            for v in vendedores:
                l = linhas_por_vend.get(v)
                cells.append(_td(f"{l['vendido']:.1f}") if l else _td('-'))
            pct_txt = _fmt_pct(p_vend / p_meta) if p_meta else '—'
            media_venda = r.get('media_rs_cx')
            media_custo = r.get('media_custo_cx')
            cells.append(_td(f"{p_vend:.1f}"))
            cells.append(_td(pct_txt))
            cells.append(_td(_fmt_money(media_venda) if media_venda is not None else '—'))
            cells.append(_td(_fmt_money(media_custo) if media_custo is not None else '—'))
            rows_html.append(f'<tr style="background:{zebra};">' + ''.join(cells) + '</tr>')
        return rows_html

    def _subtotal_row(label, group, bg, color=None):
        gm = sum(r.get('estoque_total', 0) for r in group)
        cells = [_td(label, align='left', bold=True, color=color),
                 _td(f"{gm:.0f}", bold=True, color=color)]
        for v in vendedores:
            sv = sum(l['vendido'] for r in group for l in r.get('linhas', []) if l['vendedor'] == v)
            cells.append(_td(f"{sv:.1f}", bold=True, color=color))
        gv = sum(l['vendido'] for r in group for l in r.get('linhas', []))
        cells.append(_td(f"{gv:.1f}", bold=True, color=color))
        cells.append(_td(_fmt_pct(gv / gm) if gm else '—', bold=True, color=color))
        media_venda_g = _media_rs_cx_grupo(group)
        cells.append(_td(_fmt_money(media_venda_g) if media_venda_g is not None else '—', bold=True, color=color))
        media_custo_g = _media_custo_cx_grupo(group)
        cells.append(_td(_fmt_money(media_custo_g) if media_custo_g is not None else '—', bold=True, color=color))
        return f'<tr style="background:{bg};">' + ''.join(cells) + '</tr>'

    blocks_html = []

    # Linha de totais gerais no topo -- mesma fórmula de pdfgen._totais.
    meta_total = sum(r.get('estoque_total', 0) for r in resultados)
    vendido_total = sum(l['vendido'] for r in resultados for l in r.get('linhas', []))
    falta_total = sum(max(l.get('meta', 0) - l['vendido'], 0.0)
                       for r in resultados for l in r.get('linhas', []))
    pct_total = (vendido_total / meta_total) if meta_total else 0.0
    blocks_html.append(
        f'<div style="color:#555; font-size:0.85rem; margin:-0.3rem 0 0.6rem;">'
        f'Quantidade Total: {_num(meta_total)} cx &nbsp;&nbsp; '
        f'Vendido Total: {_num(vendido_total)} cx &nbsp;&nbsp; '
        f'Falta: {_num(falta_total)} cx &nbsp;&nbsp; '
        f'% Geral Atingido: {_fmt_pct(pct_total)}</div>'
    )

    for prio_key in _PRIO_KEYS:
        grupo = grupos_prio.get(prio_key)
        if not grupo:
            continue
        prio_bg = _PRIO_BG_HTML[prio_key]
        title_color = _PRIO_TITLE_COLOR[prio_key]

        table_rows = (_header_rows(prio_bg)
                      + ''.join(_linhas_grupo(grupo))
                      + _subtotal_row('SUBTOTAL', grupo, _SUBTOTAL_BG))
        blocks_html.append(
            f'<div style="color:{title_color}; font-weight:700; font-size:1rem; '
            f'margin:0.9rem 0 0.3rem;">{_esc(_PRIO_LABEL[prio_key])}</div>'
            f'<div style="overflow-x:auto;">'
            f'<table style="width:100%; border-collapse:collapse; font-size:0.85rem;">'
            f'{table_rows}</table></div>'
        )

    # Total Geral -- tabela própria no final (uma linha só, sem cabeçalho
    # próprio -- igual ao PDF), somando todos os grupos de prioridade juntos.
    # Mesma cor do PDF (verde OTHIL escuro).
    tot_table = _subtotal_row('TOTAL GERAL', resultados, _TOTAL_BG, color='white')
    blocks_html.append(
        f'<div style="color:#1B4332; font-weight:700; font-size:1rem; '
        f'margin:0.9rem 0 0.3rem;">TOTAL GERAL</div>'
        f'<div style="overflow-x:auto;">'
        f'<table style="width:100%; border-collapse:collapse; font-size:0.85rem;">'
        f'{tot_table}</table></div>'
    )

    st.markdown(''.join(blocks_html), unsafe_allow_html=True)
