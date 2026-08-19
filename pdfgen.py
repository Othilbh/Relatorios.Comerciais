"""Geração dos 3 PDFs de saída das Metas Semanais, replicando o layout dos
relatórios de exemplo da Ingrid:
  - Relatório por Vendedor (estoque do vendedor + tabela de metas)
  - Dashboard (ranking de vendedores + produtos críticos)
  - Resumo Geral (matriz Produto × Vendedor)
"""
import io
import pdfplumber
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                 Paragraph, Spacer)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER

from calc import map_vendedor, VENDEDORES_PADRAO, soma_falta

STYLES = getSampleStyleSheet()
TITLE_STYLE = ParagraphStyle('OthilTitle', parent=STYLES['Heading1'],
                              fontSize=14, spaceAfter=4)
SUB_STYLE = ParagraphStyle('OthilSub', parent=STYLES['Normal'],
                           fontSize=9, textColor=colors.grey)
SECTION_STYLE = ParagraphStyle('OthilSection', parent=STYLES['Heading2'],
                                fontSize=11, spaceBefore=10, spaceAfter=4)

GREEN = colors.HexColor('#1e7e34')
RED = colors.HexColor('#c0392b')
HEADER_BG = colors.HexColor('#2c3e50')
LIGHT_BG = colors.HexColor('#f4f6f7')

FOOTER_TEXT = [
    "É DE RESPONSABILIDADE DO VENDEDOR:",
    "AVALIAR DIARIAMENTE A QUALIDADE E ARMAZENAGEM DE CADA PRODUTO DE SUA RESPONSABILIDADE.",
    "CONFERIR O QUE ESTA EM CADA PAVILHÃO",
    "CONFERIR O QUE ESTA NA VENDA FUTURA E ACOMPANHAR DIARIAMENTE",
    "CONFERIR O QUE ESTA ARMAZENADO EM OUTROS FRIGORIFICOS",
    "VENDER ATÉ A ÚLTIMA CAIXA",
    "DEVOLUCAO SO SE FOR NO MESMO DIA",
    "MERCADORIAS NO SOL",
    "CAMINHOES REFRIGERADOS SEMPRE FECHADOS",
]


def _fmt_money(v):
    return f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def _fmt_pct(v):
    return f"{v*100:.1f}%"


def _totais(metas_results):
    # Meta geral = soma do 'estoque_total' real de cada produto, NUNCA a
    # soma das metas individuais por vendedor (essa soma é inflada pelo
    # arredondamento pra cima de cada meta individual -- ver calc.compute_metas).
    meta_total = sum(r.get('estoque_total', 0) for r in metas_results)
    vendido_total = sum(l['vendido'] for r in metas_results for l in r['linhas'])
    falta_total = soma_falta([l for r in metas_results for l in r['linhas']])
    pct_total = (vendido_total / meta_total) if meta_total else 0.0
    return meta_total, vendido_total, falta_total, pct_total


def _produto_totais(produto_result):
    # Meta do produto = 'estoque_total' real, não a soma das metas
    # individuais dos vendedores (mesma regra de _totais acima).
    meta = produto_result.get('estoque_total', 0)
    vendido = sum(l['vendido'] for l in produto_result['linhas'])
    falta = soma_falta(produto_result['linhas'])
    pct = (vendido / meta) if meta else 0.0
    return meta, vendido, falta, pct


def _melhor_vendedor(produto_result):
    best_v, best_q = None, -1
    for l in produto_result['linhas']:
        if l['vendido'] > best_q:
            best_q = l['vendido']
            best_v = l['vendedor']
    return best_v


# --------------------------------------------------------------------------
# 1) Relatório por Vendedor
# --------------------------------------------------------------------------

# Níveis de compactação testados em ordem: o primeiro que resultar em uma
# única página é usado. Cada nível reduz margens, fontes e espaçamentos para
# caber relatórios de vendedores com mais itens de estoque numa folha só.
_RELATORIO_COMPACT_LEVELS = [
    {'margin': 1.2*cm, 'title_font': 14, 'section_font': 11,
     'est_font': 7, 'est_pad': 3, 'meta_font': 8, 'meta_pad': 3,
     'card_font': 9, 'footer_font': 7.5, 'footer_leading': 9,
     'spacer1': 0.5*cm, 'spacer2': 0.5*cm},
    {'margin': 0.9*cm, 'title_font': 13, 'section_font': 10,
     'est_font': 6.3, 'est_pad': 2, 'meta_font': 7.5, 'meta_pad': 2,
     'card_font': 8.5, 'footer_font': 6.8, 'footer_leading': 8,
     'spacer1': 0.3*cm, 'spacer2': 0.3*cm},
    {'margin': 0.6*cm, 'title_font': 12, 'section_font': 9.5,
     'est_font': 5.6, 'est_pad': 1.2, 'meta_font': 7, 'meta_pad': 1.5,
     'card_font': 8, 'footer_font': 6.2, 'footer_leading': 7.2,
     'spacer1': 0.2*cm, 'spacer2': 0.2*cm},
    {'margin': 0.4*cm, 'title_font': 11, 'section_font': 9,
     'est_font': 5, 'est_pad': 0.8, 'meta_font': 6.3, 'meta_pad': 1,
     'card_font': 7.3, 'footer_font': 5.6, 'footer_leading': 6.5,
     'spacer1': 0.1*cm, 'spacer2': 0.1*cm},
]


def _count_pages(pdf_bytes: bytes) -> int:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return len(pdf.pages)


def _footer_paragraph(font_size: float, leading: float) -> Paragraph:
    """Bloco único de rodapé (em vez de um Paragraph por linha) para reduzir
    o espaçamento extra entre flowables e ajudar a caber numa página."""
    bold_line = f"<b>{FOOTER_TEXT[0]}</b>"
    rest = "<br/>".join(FOOTER_TEXT[1:])
    style = ParagraphStyle('foot_compact', parent=STYLES['Normal'],
                            fontSize=font_size, leading=leading)
    return Paragraph(bold_line + "<br/>" + rest, style)


def _build_relatorio_vendedor(vendedor: str, data_emissao: str,
                               estoque_rows: list, metas_results: list,
                               level: dict) -> bytes:
    buf = io.BytesIO()
    m = level['margin']
    doc = SimpleDocTemplate(buf, pagesize=A4,
                             topMargin=m, bottomMargin=m,
                             leftMargin=m, rightMargin=m)
    title_style = ParagraphStyle('title_c', parent=STYLES['Heading1'],
                                  fontSize=level['title_font'], spaceAfter=3)
    section_style = ParagraphStyle('section_c', parent=STYLES['Heading2'],
                                    fontSize=level['section_font'],
                                    spaceBefore=6, spaceAfter=3)

    elems = []
    elems.append(Paragraph(f"Vendedor : {vendedor.upper()}  —  Data: {data_emissao}",
                            title_style))

    # Tabela de estoque do vendedor (todas as linhas do relatório de
    # estoque cujo "Complemento" pertence a este vendedor). Produtos com
    # saldo atual zerado não entram no relatório individual.
    linhas_estoque = [r for r in estoque_rows
                       if map_vendedor(r['complemento']) == vendedor and r['saldo_atual'] != 0]
    header = ['Produto', 'Complemento', 'Dt.Entrada', 'Saldo', 'Qtde Vend',
              'Custo Unit', 'Md Venda']
    data = [header]
    for r in linhas_estoque:
        data.append([
            r['produto'], r['complemento'], r['data_entrada'],
            f"{r['saldo_atual']:.1f}", f"{r['qtde_vendida']:.1f}",
            _fmt_money(r['custo_unitario']), _fmt_money(r['md_venda']),
        ])
    if len(data) > 1:
        t = Table(data, repeatRows=1, colWidths=[5.2*cm, 2.6*cm, 1.9*cm, 1.6*cm, 1.9*cm, 2.0*cm, 2.0*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), level['est_font']),
            ('TOPPADDING', (0, 0), (-1, -1), level['est_pad']),
            ('BOTTOMPADDING', (0, 0), (-1, -1), level['est_pad']),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.lightgrey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elems.append(t)
    else:
        elems.append(Paragraph("Sem itens de estoque para este vendedor.", STYLES['Normal']))

    elems.append(Paragraph(f"METAS SEMANAIS — {vendedor.upper()} — {data_emissao}",
                            section_style))
    mheader = ['Produto', 'Meta (cx)', 'Vendido (cx)', 'Falta (cx)', '%']
    mdata = [mheader]
    meta_t = vendido_t = falta_t = 0.0
    for r in metas_results:
        linha = next((l for l in r['linhas'] if l['vendedor'] == vendedor), None)
        if not linha:
            continue
        meta_t += linha['meta']
        vendido_t += linha['vendido']
        falta_t += linha['falta']
        prio = r.get('prioridade', 'Normal')
        nome_prod = f"{prio} {r['produto']}" if prio != 'Normal' else r['produto']
        mdata.append([nome_prod, f"{linha['meta']:.0f}", f"{linha['vendido']:.1f}",
                      f"{linha['falta']:.1f}", _fmt_pct(linha['atingido'])])
    pct_t = (vendido_t / meta_t) if meta_t else 0.0
    mdata.append(['TOTAL', f"{meta_t:.0f}", f"{vendido_t:.1f}", f"{falta_t:.1f}", _fmt_pct(pct_t)])

    mt = Table(mdata, repeatRows=1, colWidths=[7*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2*cm])
    mt.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), level['meta_font']),
        ('TOPPADDING', (0, 0), (-1, -1), level['meta_pad']),
        ('BOTTOMPADDING', (0, 0), (-1, -1), level['meta_pad']),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#dfe6e9')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, LIGHT_BG]),
    ]))
    elems.append(mt)
    elems.append(Spacer(1, level['spacer1']))

    card = Table([
        ['Meta Total', 'Vendido', 'Falta', '% Atingido'],
        [f"{meta_t:.0f} cx", f"{vendido_t:.0f} cx", f"{falta_t:.0f} cx", _fmt_pct(pct_t)],
    ], colWidths=[3.5*cm]*4)
    card.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), level['card_font']),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.lightgrey),
    ]))
    elems.append(card)
    elems.append(Spacer(1, level['spacer2']))

    elems.append(_footer_paragraph(level['footer_font'], level['footer_leading']))

    doc.build(elems)
    return buf.getvalue()


def generate_relatorio_vendedor(vendedor: str, data_emissao: str,
                                 estoque_rows: list, metas_results: list) -> bytes:
    """Gera o relatório individual do vendedor, encolhendo automaticamente
    fontes/margens/espaçamentos até caber em uma única folha A4 (para
    impressão). Se nem no nível mais compacto couber, retorna a versão mais
    compacta mesmo assim (melhor esforço)."""
    last_bytes = None
    for level in _RELATORIO_COMPACT_LEVELS:
        last_bytes = _build_relatorio_vendedor(vendedor, data_emissao, estoque_rows,
                                                metas_results, level)
        if _count_pages(last_bytes) <= 1:
            return last_bytes
    return last_bytes


# --------------------------------------------------------------------------
# 2) Dashboard
# --------------------------------------------------------------------------

_PRIO_LABEL_TXT = {
    '🚨 Grande Urgência': 'Grande Urgência',
    '🔥 Alta Prioridade': 'Alta Prioridade',
    'Normal': '',
}

_DASHBOARD_LEVELS = [
    dict(margin=1.2*cm, font=9,   crit_col=7.5*cm, pad=3),
    dict(margin=0.9*cm, font=8,   crit_col=7.0*cm, pad=2),
    dict(margin=0.6*cm, font=7.5, crit_col=6.5*cm, pad=1.5),
    dict(margin=0.4*cm, font=7,   crit_col=6.0*cm, pad=1),
]


def _build_dashboard(periodo: str, metas_results: list, vendedor_pcts: dict,
                     level: dict) -> bytes:
    fs   = level['font']
    pad  = level['pad']
    mrg  = level['margin']
    ccol = level['crit_col']

    prod_style = ParagraphStyle('dp', parent=STYLES['Normal'],
                                fontSize=fs, leading=fs * 1.2, wordWrap='LTR')
    hdr_style = ParagraphStyle('dh', parent=STYLES['Normal'],
                               fontSize=fs, leading=fs * 1.2, textColor=colors.white)
    sec_style = ParagraphStyle('ds', parent=STYLES['Heading2'],
                               fontSize=fs + 2, spaceBefore=8, spaceAfter=4)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                             topMargin=mrg, bottomMargin=mrg,
                             leftMargin=mrg, rightMargin=mrg)

    elems = [Paragraph(f"OTHIL — DASHBOARD DE METAS | {periodo}",
                       ParagraphStyle('dt', parent=STYLES['Heading1'],
                                      fontSize=14, spaceAfter=4))]

    meta_total, vendido_total, falta_total, pct_total = _totais(metas_results)
    criticos = [r for r in metas_results if _produto_totais(r)[3] < 0.5]

    card = Table([
        ['Meta Total', 'Vendido', 'Falta', '% Atingido', 'Criticos <50%', 'Produtos'],
        [f"{meta_total:,.0f} cx", f"{vendido_total:,.0f} cx", f"{falta_total:,.0f} cx",
         _fmt_pct(pct_total), str(len(criticos)), str(len(metas_results))],
    ], colWidths=[4*cm]*6)
    card.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), fs),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), pad),
        ('BOTTOMPADDING', (0, 0), (-1, -1), pad),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.lightgrey),
    ]))
    elems.append(card)

    # Ranking de vendedores
    elems.append(Paragraph("RANKING DE VENDEDORES", sec_style))
    vend_agg = {}
    for v in vendedor_pcts:
        linhas_v = [l for r in metas_results for l in r['linhas'] if l['vendedor'] == v]
        m = sum(l['meta'] for l in linhas_v)
        ve = sum(l['vendido'] for l in linhas_v)
        vend_agg[v] = (m, ve, soma_falta(linhas_v), (ve / m if m else 0.0))
    ranking = sorted(vend_agg.items(), key=lambda kv: kv[1][3], reverse=True)

    rheader = ['#', 'Vendedor', 'Meta (cx)', 'Vendido (cx)', 'Falta (cx)',
               '% Atingido', 'Status', '% Meta']
    rdata = [rheader]
    for i, (v, (m, ve, f, p)) in enumerate(ranking, start=1):
        status = 'Andamento' if p >= 0.5 else 'Abaixo'
        rdata.append([f"{i}°", v, f"{m:.0f}", f"{ve:.1f}", f"{f:.1f}",
                      _fmt_pct(p), status, f"{vendedor_pcts[v]:.0f}%"])
    rt = Table(rdata, repeatRows=1,
               colWidths=[1.2*cm, 4*cm, 2.8*cm, 2.8*cm, 2.8*cm, 2.8*cm, 3*cm, 2.3*cm])
    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), fs),
        ('TOPPADDING', (0, 0), (-1, -1), pad),
        ('BOTTOMPADDING', (0, 0), (-1, -1), pad),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
    ]
    for i, (v, (m, ve, f, p)) in enumerate(ranking, start=1):
        color = GREEN if p >= 0.5 else RED
        style_cmds.append(('TEXTCOLOR', (6, i), (6, i), color))
    rt.setStyle(TableStyle(style_cmds))
    elems.append(rt)

    # Produtos críticos — usa Paragraph no nome para evitar overflow
    elems.append(Paragraph("PRODUTOS CRITICOS — ABAIXO DE 50%", sec_style))
    _PRIO_ORDER = {'🚨 Grande Urgência': 0, '🔥 Alta Prioridade': 1, 'Normal': 2}
    crit_sorted = sorted(criticos, key=lambda r: (
        _PRIO_ORDER.get(r.get('prioridade', 'Normal'), 2), _produto_totais(r)[3]))
    cheader = [Paragraph('Produto', hdr_style), 'Meta Total', 'Vendido',
               'Falta', '% Geral', 'Melhor Vendedor']
    cdata = [cheader]
    for r in crit_sorted:
        m, ve, f, p = _produto_totais(r)
        prio = r.get('prioridade', 'Normal')
        prio_txt = _PRIO_LABEL_TXT.get(prio, prio)
        nome_raw = f"{prio_txt} {r['produto']}".strip() if prio_txt else r['produto']
        cdata.append([Paragraph(nome_raw, prod_style),
                      f"{m:.0f}", f"{ve:.1f}", f"{f:.1f}",
                      _fmt_pct(p), _melhor_vendedor(r) or '-'])
    # Distribui espaço restante após colunas numéricas
    num_cols = [2.2*cm, 2.2*cm, 2.2*cm, 2.2*cm, 3.0*cm]
    ct = Table(cdata, repeatRows=1, colWidths=[ccol] + num_cols)
    ct.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), fs),
        ('TOPPADDING', (0, 0), (-1, -1), pad),
        ('BOTTOMPADDING', (0, 0), (-1, -1), pad),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elems.append(ct)

    doc.build(elems)
    return buf.getvalue()


def generate_dashboard(periodo: str, metas_results: list, vendedor_pcts: dict) -> bytes:
    """Gera o Dashboard, reduzindo automaticamente até caber em uma única folha."""
    last = None
    for lv in _DASHBOARD_LEVELS:
        last = _build_dashboard(periodo, metas_results, vendedor_pcts, lv)
        if _count_pages(last) <= 1:
            return last
    return last


# --------------------------------------------------------------------------
# 3) Resumo Geral
# --------------------------------------------------------------------------

_PRIO_ORDER_RG = {'🚨 Grande Urgência': 0, '🔥 Alta Prioridade': 1, 'Normal': 2}
_PRIO_LABEL_RG = {
    '🚨 Grande Urgência': 'GRANDE URGENCIA',
    '🔥 Alta Prioridade': 'ALTA PRIORIDADE',
    'Normal': 'NORMAL',
}
_PRIO_BG_RG = {
    '🚨 Grande Urgência': colors.HexColor('#922b21'),
    '🔥 Alta Prioridade': colors.HexColor('#784212'),
    'Normal': HEADER_BG,
}
_PRIO_TITLE_COLOR_RG = {
    '🚨 Grande Urgência': colors.HexColor('#922b21'),
    '🔥 Alta Prioridade': colors.HexColor('#784212'),
    'Normal': colors.HexColor('#1B4332'),
}

# Níveis de compactação: tenta do primeiro (mais espaçoso) ao último (mais denso).
# Landscape A4 disponível (com margens): ~27.7 cm largura, ~19.5 cm altura.
_RESUMO_LEVELS = [
    dict(margin=1.0*cm, font=7,   prod_col=4.2*cm, qtde_col=1.6*cm,
         num_col=1.25*cm, pct_col=1.0*cm, pad=2.5, lpad=3, rpad=3,
         spacer=0.4*cm, sec_font=10),
    dict(margin=0.8*cm, font=6.5, prod_col=4.0*cm, qtde_col=1.5*cm,
         num_col=1.18*cm, pct_col=0.93*cm, pad=2.0, lpad=2, rpad=2,
         spacer=0.3*cm, sec_font=9.5),
    dict(margin=0.6*cm, font=6,   prod_col=3.7*cm, qtde_col=1.4*cm,
         num_col=1.1*cm,  pct_col=0.87*cm, pad=1.5, lpad=2, rpad=2,
         spacer=0.2*cm, sec_font=9),
    dict(margin=0.4*cm, font=5.5, prod_col=3.4*cm, qtde_col=1.3*cm,
         num_col=1.02*cm, pct_col=0.8*cm,  pad=1.0, lpad=1, rpad=1,
         spacer=0.1*cm, sec_font=8.5),
]


def _build_resumo_geral(periodo: str, data_emissao: str, metas_results: list,
                         vendedor_pcts: dict, level: dict) -> bytes:
    fs      = level['font']
    pad     = level['pad']
    lpad    = level['lpad']
    rpad    = level['rpad']
    mrg     = level['margin']
    spacer  = level['spacer']
    sf      = level['sec_font']

    # Styles para células de produto (Paragraph habilita word-wrap automático)
    prod_style = ParagraphStyle(
        'rg_prod', parent=STYLES['Normal'],
        fontSize=fs, leading=fs * 1.2, wordWrap='LTR',
    )
    sub_style = ParagraphStyle(
        'rg_sub', parent=STYLES['Normal'],
        fontSize=fs, leading=fs * 1.2, fontName='Helvetica-Bold', wordWrap='LTR',
    )
    hdr_style = ParagraphStyle(
        'rg_hdr', parent=STYLES['Normal'],
        fontSize=fs, leading=fs * 1.2, textColor=colors.white,
    )

    vendedores  = list(vendedor_pcts.keys())
    col_widths  = [level['prod_col'], level['qtde_col']] + \
                  [level['num_col'], level['pct_col']] * (len(vendedores) + 1)

    def _header_rows():
        r1 = [Paragraph('Produto', hdr_style), Paragraph('Qtde', hdr_style)]
        r2 = ['', '']
        for v in vendedores:
            r1 += [Paragraph(v, hdr_style), '']
            r2 += ['Vend', '%']
        r1 += [Paragraph('TOTAL', hdr_style), '']
        r2 += ['Vend', '%']
        return r1, r2

    def _produto_row(r):
        row = [Paragraph(r['produto'], prod_style), f"{r['estoque_total']:.0f}"]
        for v in vendedores:
            l = next((x for x in r['linhas'] if x['vendedor'] == v), None)
            row += [f"{l['vendido']:.1f}" if l else '-',
                    _fmt_pct(l['atingido']) if l else '-']
        _, ve, _, p = _produto_totais(r)
        row += [f"{ve:.1f}", _fmt_pct(p)]
        return row

    def _subtotal_row(label, group):
        # 'est' (Qtde) e a meta do grupo/TOTAL usam a mesma base: soma do
        # 'estoque_total' real dos produtos, não a soma das metas
        # individuais (m_v continua individual -- meta do próprio vendedor
        # somada nos produtos do grupo, isso está correto).
        est = sum(r['estoque_total'] for r in group)
        row = [Paragraph(label, sub_style), f"{est:.0f}"]
        for v in vendedores:
            ve_v = sum(l['vendido'] for r in group for l in r['linhas'] if l['vendedor'] == v)
            m_v  = sum(l['meta']    for r in group for l in r['linhas'] if l['vendedor'] == v)
            row += [f"{ve_v:.1f}", _fmt_pct(ve_v / m_v if m_v else 0)]
        ve_g = sum(l['vendido'] for r in group for l in r['linhas'])
        m_g  = est
        row += [f"{ve_g:.1f}", _fmt_pct(ve_g / m_g if m_g else 0)]
        return row

    def _build_table(rows, bg_color):
        r1, r2 = _header_rows()
        data   = [r1, r2] + rows
        n_cols = len(r1)
        t = Table(data, repeatRows=2, colWidths=col_widths[:n_cols])
        cmds = [
            ('BACKGROUND',    (0, 0), (-1, 1),   bg_color),
            ('TEXTCOLOR',     (0, 0), (-1, 1),   colors.white),
            ('FONTSIZE',      (0, 0), (-1, -1),  fs),
            ('TOPPADDING',    (0, 0), (-1, -1),  pad),
            ('BOTTOMPADDING', (0, 0), (-1, -1),  pad),
            ('LEFTPADDING',   (0, 0), (-1, -1),  lpad),
            ('RIGHTPADDING',  (0, 0), (-1, -1),  rpad),
            ('GRID',          (0, 0), (-1, -1),  0.3, colors.lightgrey),
            ('ALIGN',         (1, 0), (-1, -1),  'CENTER'),
            ('VALIGN',        (0, 0), (-1, -1),  'MIDDLE'),
            ('FONTNAME',      (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('BACKGROUND',    (0, -1), (-1, -1), colors.HexColor('#dfe6e9')),
            ('ROWBACKGROUNDS',(0, 2), (-1, -2),  [colors.white, LIGHT_BG]),
            ('SPAN',          (0, 0), (0, 1)),
            ('SPAN',          (1, 0), (1, 1)),
        ]
        col = 2
        for _ in vendedores:
            cmds.append(('SPAN', (col, 0), (col + 1, 0)))
            col += 2
        cmds.append(('SPAN', (col, 0), (col + 1, 0)))
        t.setStyle(TableStyle(cmds))
        return t

    # Agrupar por prioridade
    groups: dict = {}
    for r in metas_results:
        prio = r.get('prioridade', 'Normal')
        groups.setdefault(prio, []).append(r)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                             topMargin=mrg, bottomMargin=mrg,
                             leftMargin=mrg, rightMargin=mrg)

    estoque_total = sum(r['estoque_total'] for r in metas_results)
    meta_total, vendido_total, falta_total, pct_total = _totais(metas_results)

    title_sty = ParagraphStyle('rg_title', parent=STYLES['Heading1'],
                               fontSize=14, spaceAfter=4)
    sub_info_sty = ParagraphStyle('rg_info', parent=STYLES['Normal'],
                                  fontSize=9, textColor=colors.grey)

    elems = [Paragraph(
        f"OTHIL — RESUMO GERAL DE METAS | {periodo} | {data_emissao}", title_sty)]
    elems.append(Paragraph(
        f"Quantidade Total: {estoque_total:,.0f} cx &nbsp;&nbsp; "
        f"Meta Total: {meta_total:,.0f} cx &nbsp;&nbsp; "
        f"Vendido Total: {vendido_total:,.0f} cx &nbsp;&nbsp; "
        f"Falta: {falta_total:,.0f} cx &nbsp;&nbsp; "
        f"% Geral Atingido: {_fmt_pct(pct_total)}",
        sub_info_sty))
    elems.append(Spacer(1, spacer * 0.8))

    for prio_key in ['🚨 Grande Urgência', '🔥 Alta Prioridade', 'Normal']:
        group = groups.get(prio_key)
        if not group:
            continue
        sec_sty = ParagraphStyle(
            f'rg_prio_{prio_key[:4]}',
            parent=STYLES['Heading2'],
            fontSize=sf, spaceBefore=6, spaceAfter=2,
            textColor=_PRIO_TITLE_COLOR_RG[prio_key],
        )
        elems.append(Paragraph(_PRIO_LABEL_RG[prio_key], sec_sty))
        rows = [_produto_row(r) for r in group]
        rows.append(_subtotal_row('SUBTOTAL', group))
        elems.append(_build_table(rows, _PRIO_BG_RG[prio_key]))
        elems.append(Spacer(1, spacer))

    # Total geral consolidado
    tot_sty = ParagraphStyle('rg_tot', parent=STYLES['Heading2'],
                              fontSize=sf, spaceBefore=4, spaceAfter=2,
                              textColor=colors.HexColor('#1B4332'))
    elems.append(Paragraph('TOTAL GERAL', tot_sty))

    total_row = _subtotal_row('TOTAL GERAL', metas_results)
    n_cols = 2 + (len(vendedores) + 1) * 2
    gt = Table([total_row], colWidths=col_widths[:n_cols])
    gt.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0), colors.HexColor('#1B4332')),
        ('TEXTCOLOR',     (0, 0), (-1, 0), colors.white),
        ('FONTNAME',      (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, 0), fs),
        ('ALIGN',         (1, 0), (-1, 0), 'CENTER'),
        ('VALIGN',        (0, 0), (-1, 0), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, 0), pad + 1),
        ('BOTTOMPADDING', (0, 0), (-1, 0), pad + 1),
        ('LEFTPADDING',   (0, 0), (-1, 0), lpad),
        ('RIGHTPADDING',  (0, 0), (-1, 0), rpad),
        ('GRID',          (0, 0), (-1, 0), 0.3, colors.lightgrey),
    ]))
    elems.append(gt)

    doc.build(elems)
    return buf.getvalue()


def generate_resumo_geral(periodo: str, data_emissao: str, metas_results: list,
                           vendedor_pcts: dict) -> bytes:
    """Gera o Resumo Geral, reduzindo automaticamente até caber em uma única folha."""
    last = None
    for lv in _RESUMO_LEVELS:
        last = _build_resumo_geral(periodo, data_emissao, metas_results, vendedor_pcts, lv)
        if _count_pages(last) <= 1:
            return last
    return last
