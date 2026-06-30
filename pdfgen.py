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

from calc import map_vendedor, VENDEDORES_PADRAO

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
    meta_total = sum(l['meta'] for r in metas_results for l in r['linhas'])
    vendido_total = sum(l['vendido'] for r in metas_results for l in r['linhas'])
    falta_total = meta_total - vendido_total
    pct_total = (vendido_total / meta_total) if meta_total else 0.0
    return meta_total, vendido_total, falta_total, pct_total


def _produto_totais(produto_result):
    meta = sum(l['meta'] for l in produto_result['linhas'])
    vendido = sum(l['vendido'] for l in produto_result['linhas'])
    falta = meta - vendido
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
        mdata.append([r['produto'], f"{linha['meta']:.0f}", f"{linha['vendido']:.1f}",
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

def generate_dashboard(periodo: str, metas_results: list, vendedor_pcts: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                             topMargin=1.2*cm, bottomMargin=1.2*cm,
                             leftMargin=1.2*cm, rightMargin=1.2*cm)
    elems = [Paragraph(f"OTHIL — DASHBOARD DE METAS | {periodo}", TITLE_STYLE)]

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
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.lightgrey),
    ]))
    elems.append(card)

    # Ranking de vendedores
    elems.append(Paragraph("RANKING DE VENDEDORES", SECTION_STYLE))
    vend_agg = {}
    for v in vendedor_pcts:
        m = sum(l['meta'] for r in metas_results for l in r['linhas'] if l['vendedor'] == v)
        ve = sum(l['vendido'] for r in metas_results for l in r['linhas'] if l['vendedor'] == v)
        vend_agg[v] = (m, ve, m - ve, (ve / m if m else 0.0))
    ranking = sorted(vend_agg.items(), key=lambda kv: kv[1][3], reverse=True)

    rheader = ['#', 'Vendedor', 'Meta (cx)', 'Vendido (cx)', 'Falta (cx)',
               '% Atingido', 'Status', '% Meta']
    rdata = [rheader]
    for i, (v, (m, ve, f, p)) in enumerate(ranking, start=1):
        status = 'Andamento' if p >= 0.5 else 'Abaixo'
        rdata.append([f"{i}°", v, f"{m:.0f}", f"{ve:.1f}", f"{f:.1f}",
                      _fmt_pct(p), status, f"{vendedor_pcts[v]:.0f}%"])
    rt = Table(rdata, repeatRows=1, colWidths=[1.2*cm, 4*cm, 3*cm, 3*cm, 3*cm, 3*cm, 3.2*cm, 2.5*cm])
    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
    ]
    for i, (v, (m, ve, f, p)) in enumerate(ranking, start=1):
        color = GREEN if p >= 0.5 else RED
        style_cmds.append(('TEXTCOLOR', (6, i), (6, i), color))
    rt.setStyle(TableStyle(style_cmds))
    elems.append(rt)

    # Produtos críticos
    elems.append(Paragraph("PRODUTOS CRITICOS — ABAIXO DE 50%", SECTION_STYLE))
    crit_sorted = sorted(criticos, key=lambda r: _produto_totais(r)[3])
    cheader = ['Produto', 'Meta Total', 'Vendido', 'Falta', '% Geral', 'Melhor Vendedor']
    cdata = [cheader]
    for r in crit_sorted:
        m, ve, f, p = _produto_totais(r)
        cdata.append([r['produto'], f"{m:.0f}", f"{ve:.1f}", f"{f:.1f}",
                      _fmt_pct(p), _melhor_vendedor(r) or '-'])
    ct = Table(cdata, repeatRows=1, colWidths=[6*cm, 3*cm, 3*cm, 3*cm, 3*cm, 4*cm])
    ct.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.lightgrey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
    ]))
    elems.append(ct)

    doc.build(elems)
    return buf.getvalue()


# --------------------------------------------------------------------------
# 3) Resumo Geral
# --------------------------------------------------------------------------

def generate_resumo_geral(periodo: str, data_emissao: str, metas_results: list,
                           vendedor_pcts: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                             topMargin=1.0*cm, bottomMargin=1.0*cm,
                             leftMargin=1.0*cm, rightMargin=1.0*cm)
    elems = [Paragraph(f"OTHIL — RESUMO GERAL DE METAS | {periodo} | {data_emissao}",
                        TITLE_STYLE)]

    estoque_total = sum(r['estoque_total'] for r in metas_results)
    meta_total, vendido_total, falta_total, pct_total = _totais(metas_results)
    elems.append(Paragraph(
        f"Estoque Total: {estoque_total:,.0f} cx &nbsp;&nbsp; "
        f"Meta Total: {meta_total:,.0f} cx &nbsp;&nbsp; "
        f"Vendido Total: {vendido_total:,.0f} cx &nbsp;&nbsp; "
        f"Falta: {falta_total:,.0f} cx &nbsp;&nbsp; "
        f"% Geral Atingido: {_fmt_pct(pct_total)}",
        SUB_STYLE))
    elems.append(Spacer(1, 0.3*cm))

    vendedores = list(vendedor_pcts.keys())
    header_row1 = ['Produto', 'Estoque']
    header_row2 = ['', '']
    for v in vendedores:
        header_row1 += [v, '']
        header_row2 += ['Vend', '%']
    header_row1 += ['TOTAL', '']
    header_row2 += ['Vend', '%']

    data = [header_row1, header_row2]
    for r in metas_results:
        row = [r['produto'], f"{r['estoque_total']:.0f}"]
        for v in vendedores:
            linha = next((l for l in r['linhas'] if l['vendedor'] == v), None)
            vendido = linha['vendido'] if linha else 0.0
            pct = linha['atingido'] if linha else 0.0
            row += [f"{vendido:.1f}", _fmt_pct(pct)]
        m, ve, f, p = _produto_totais(r)
        row += [f"{ve:.1f}", _fmt_pct(p)]
        data.append(row)

    # linha TOTAL
    total_row = ['TOTAL', f"{estoque_total:.0f}"]
    for v in vendedores:
        ve_v = sum(l['vendido'] for r in metas_results for l in r['linhas'] if l['vendedor'] == v)
        m_v = sum(l['meta'] for r in metas_results for l in r['linhas'] if l['vendedor'] == v)
        p_v = (ve_v / m_v) if m_v else 0.0
        total_row += [f"{ve_v:.1f}", _fmt_pct(p_v)]
    total_row += [f"{vendido_total:.1f}", _fmt_pct(pct_total)]
    data.append(total_row)

    n_cols = len(header_row1)
    col_widths = [4.2*cm, 1.8*cm] + [1.3*cm, 1.1*cm] * (len(vendedores) + 1)
    t = Table(data, repeatRows=2, colWidths=col_widths[:n_cols])
    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 1), HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 1), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 6.5),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.lightgrey),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#dfe6e9')),
        ('ROWBACKGROUNDS', (0, 2), (-1, -2), [colors.white, LIGHT_BG]),
        ('SPAN', (0, 0), (0, 1)),
        ('SPAN', (1, 0), (1, 1)),
    ]
    col = 2
    for _ in vendedores:
        style_cmds.append(('SPAN', (col, 0), (col + 1, 0)))
        col += 2
    style_cmds.append(('SPAN', (col, 0), (col + 1, 0)))
    t.setStyle(TableStyle(style_cmds))
    elems.append(t)

    doc.build(elems)
    return buf.getvalue()
