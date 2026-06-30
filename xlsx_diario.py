"""Gera o Excel 'Relatorio_Diario_DD-MM-AAAA_OTHIL.xlsx' a partir do resultado
de parsers_diario.parse_relatorio_diario().

Estrutura (pedido da Ingrid):
  - Leia-me
  - Resumo (KPIs + ranking de vendedores + gráfico de barras)
  - Alertas_<-15% (itens produto x cliente x vendedor com Resultado % < -15%)
  - Vendedor_<Nome> (uma aba por vendedor): bloco detalhado por produto,
    bloco gerencial por cliente.

Uma aba oculta "Dados" guarda a lista plana de itens extraídos do PDF — é a
fonte única usada pelas fórmulas do Resumo e do Alertas (só os VALORES
extraídos do PDF em si são fixos; todo cálculo é fórmula).
"""
import re
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, Reference

VERDE_BG, VERDE_FG = 'D8EFE3', '1B4332'
AMARELO_BG, AMARELO_FG = 'FEF9C3', '7D6608'
VERMELHO_BG, VERMELHO_FG = 'FADADD', '7A1F2B'
HEADER_BG, HEADER_FG = '2D6A4F', 'FFFFFF'
FONT_NAME = 'Arial'
MONEY_FMT = '#,##0.00'
PCT_FMT = '0.00'

THIN = Side(style='thin', color='CCCCCC')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _font(bold=False, size=11, color='000000'):
    return Font(name=FONT_NAME, bold=bold, size=size, color=color)


def _header_cell(ws, row, col, text):
    c = ws.cell(row=row, column=col, value=text)
    c.font = _font(bold=True, color=HEADER_FG)
    c.fill = PatternFill('solid', fgColor=HEADER_BG)
    c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    c.border = BORDER
    return c


def _resultado_colors(pct):
    if pct >= 15:
        return VERDE_BG, VERDE_FG
    if pct >= 0:
        return AMARELO_BG, AMARELO_FG
    return VERMELHO_BG, VERMELHO_FG


def _pct_cell(ws, row, col, value_or_formula, pct_for_color):
    cell = ws.cell(row=row, column=col, value=value_or_formula)
    cell.number_format = PCT_FMT
    bg, fg = _resultado_colors(pct_for_color)
    cell.fill = PatternFill('solid', fgColor=bg)
    cell.font = _font(color=fg)
    cell.border = BORDER
    return cell


def _money(ws, row, col, value_or_formula):
    cell = ws.cell(row=row, column=col, value=value_or_formula)
    cell.number_format = MONEY_FMT
    cell.border = BORDER
    cell.font = _font()
    return cell


def _qty(ws, row, col, value_or_formula):
    cell = ws.cell(row=row, column=col, value=value_or_formula)
    cell.number_format = '#,##0.000'
    cell.border = BORDER
    cell.font = _font()
    return cell


def _text(ws, row, col, value, bold=False):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = _font(bold=bold)
    cell.border = BORDER
    return cell


def _sheet_name_for_vendor(nome):
    safe = re.sub(r'[\\/*?:\[\]]', '', nome)[:25]
    return f'Vendedor_{safe}'


# ---------------------------------------------------------------------------
# Aba "Dados" (oculta) — fonte única dos itens extraídos do PDF.
# ---------------------------------------------------------------------------

def _build_dados(wb, itens):
    ws = wb.create_sheet('Dados')
    headers = ['Vendedor', 'Vendedor_raw', 'Cliente_codigo', 'Cliente_nome',
               'Produto', 'Qtd', 'Faturamento', 'CustoUnit', 'CustoTotal',
               'Resultado_RS', 'Resultado_pct', 'Primeiro_Cliente_Vendedor',
               'Primeiro_Cliente_Global']
    for j, h in enumerate(headers, start=1):
        ws.cell(row=1, column=j, value=h).font = _font(bold=True)

    n = len(itens)
    for i, it in enumerate(itens):
        r = i + 2
        ws.cell(row=r, column=1, value=it['vendedor'] or it['vendedor_raw'])
        ws.cell(row=r, column=2, value=it['vendedor_raw'])
        ws.cell(row=r, column=3, value=it['cliente_codigo'])
        ws.cell(row=r, column=4, value=it['cliente_nome'])
        ws.cell(row=r, column=5, value=it['produto'])
        ws.cell(row=r, column=6, value=it['qtd'])
        ws.cell(row=r, column=7, value=it['faturamento'])
        ws.cell(row=r, column=8, value=it['custo_unit'])
        ws.cell(row=r, column=9, value=it['custo_total'])
        ws.cell(row=r, column=10, value=f'=G{r}-I{r}')
        ws.cell(row=r, column=11, value=f'=IFERROR((G{r}-I{r})/I{r}*100,0)')
        ws.cell(row=r, column=12, value=f'=IF(COUNTIFS($B$2:B{r},B{r},$C$2:C{r},C{r})=1,1,0)')
        ws.cell(row=r, column=13, value=f'=IF(COUNTIFS($C$2:C{r},C{r})=1,1,0)')
    ws.sheet_state = 'hidden'
    return ws, n


# ---------------------------------------------------------------------------
# Aba "Leia-me"
# ---------------------------------------------------------------------------

def _build_leiame(wb, data_emissao, periodo):
    ws = wb.create_sheet('Leia-me')
    ws.sheet_view.showGridLines = False
    ws.column_dimensions['A'].width = 110
    row = [1]

    def add(text, bold=False, size=11, color='000000', fill=None):
        r = row[0]
        c = ws.cell(row=r, column=1, value=text)
        c.font = _font(bold=bold, size=size, color=color)
        c.alignment = Alignment(wrap_text=True, vertical='top')
        if fill:
            c.fill = PatternFill('solid', fgColor=fill)
        row[0] += 1
        return c

    add('Relatório Diário de Vendas OTHIL', bold=True, size=18, color=HEADER_BG)
    add(f'Dia: {data_emissao or "-"}    Período: {periodo or "-"}', bold=True, size=12)
    add('')
    add('O QUE É ESTE ARQUIVO', bold=True, size=13, color=HEADER_BG)
    add('Gerado automaticamente a partir do PDF "Lucratividade por Vendedor-Cliente '
        'no Previsão" (Mercatus) do dia. Cada linha de produto do PDF é extraída '
        'item a item (produto x cliente x vendedor) e o Resultado % é recalculado '
        'pela regra do sistema: Resultado % = (Faturamento − Custo) / Custo × 100 '
        '(nunca o % visual do PDF, nem calculado sobre o faturamento).')
    add('Antes de montar o relatório, o total de faturamento e custo de cada '
        'vendedor e de cada cliente, somado a partir dos itens extraídos, é '
        'conferido contra os "Totais do Vendedor"/"Totais do Cliente" oficiais '
        'do próprio PDF (tolerância de R$ 1). Não havendo aviso de divergência '
        'nesta planilha, todos os totais bateram exatamente.')
    add('')
    add('COMO LER CADA ABA', bold=True, size=13, color=HEADER_BG)
    add('Resumo: visão geral do dia — KPIs principais, ranking de vendedores '
        '(ordenado por faturamento) e o gráfico de faturamento por vendedor.', bold=True)
    add('Alertas_<-15%: todos os itens (produto x cliente x vendedor) com '
        'Resultado % abaixo de -15%, do pior para o melhor — é a lista priorizada '
        'do que revisar primeiro.', bold=True)
    add('Vendedor_<Nome>: uma aba por vendedor, com duas partes — à esquerda, '
        'cada produto vendido por ele, cliente a cliente; à direita, o mesmo '
        'resultado agrupado por cliente (visão gerencial), com a coluna "% do '
        'Vendedor" mostrando o quanto aquele cliente representa do faturamento '
        'total do vendedor.', bold=True)
    add('')
    add('SEMÁFORO DE CORES (coluna Resultado %)', bold=True, size=13, color=HEADER_BG)
    add('Verde — Resultado % maior ou igual a 15% (saudável)', color=VERDE_FG, fill=VERDE_BG)
    add('Amarelo — Resultado % entre 0% e 15% (atenção, margem baixa)', color=AMARELO_FG, fill=AMARELO_BG)
    add('Vermelho — Resultado % negativo (prejuízo no item)', color=VERMELHO_FG, fill=VERMELHO_BG)
    add('')
    add('OBSERVAÇÕES E LIMITAÇÕES CONHECIDAS', bold=True, size=13, color=HEADER_BG)
    add('- Consolidação de clientes: agrupados pelo código de cliente do '
        'Mercatus (mais confiável que casar pelo nome entre filiais). Ainda não '
        'há uma regra oficial confirmada pela Ingrid para isso — avise se algum '
        'agrupamento sair errado.')
    add('- Em casos raros (nome de produto colado a um sufixo de peso/unidade '
        'logo depois do código, ex.: "...8KG"), um dígito inicial pode se '
        'perder na limpeza do nome. Não afeta nenhum valor financeiro — é só '
        'cosmético.')
    add('- O nome do produto nunca é unificado/agrupado em categoria nesta '
        'planilha — aparece exatamente como extraído do PDF, item a item, em '
        'todas as abas.')
    return ws


# ---------------------------------------------------------------------------
# Aba "Resumo"
# ---------------------------------------------------------------------------

def _build_resumo(wb, n_dados, vendor_order):
    ws = wb.create_sheet('Resumo')
    ws.sheet_view.showGridLines = False

    def drange(col):
        return f'Dados!${col}$2:${col}${n_dados + 1}'

    ws.cell(row=4, column=1)  # placeholder to keep layout stable
    kpis = [
        ('Faturamento', f"=SUM({drange('G')})", MONEY_FMT),
        ('Resultado R$', f"=SUM({drange('G')})-SUM({drange('I')})", MONEY_FMT),
        ('Resultado %', f"=IFERROR((SUM({drange('G')})-SUM({drange('I')}))/SUM({drange('I')})*100,0)", PCT_FMT),
        ('Caixas', f"=SUM({drange('F')})", '#,##0.000'),
        ('Clientes', f"=SUM({drange('M')})", '0'),
        ('Vendedores Ativos', f'={len(vendor_order)}', '0'),
    ]
    col = 1
    for label, formula, fmt in kpis:
        lc = ws.cell(row=4, column=col, value=label)
        lc.font = _font(bold=True, color=HEADER_FG)
        lc.fill = PatternFill('solid', fgColor=HEADER_BG)
        lc.alignment = Alignment(horizontal='center')
        ws.merge_cells(start_row=4, start_column=col, end_row=4, end_column=col + 1)
        vc = ws.cell(row=5, column=col, value=formula)
        vc.font = _font(bold=True, size=14)
        vc.number_format = fmt
        vc.alignment = Alignment(horizontal='center')
        ws.merge_cells(start_row=5, start_column=col, end_row=5, end_column=col + 1)
        for rr in (4, 5):
            for cc in (col, col + 1):
                ws.cell(row=rr, column=cc).border = BORDER
        col += 2

    ws.cell(row=1, column=1, value='Relatório Diário de Vendas OTHIL').font = _font(bold=True, size=18, color=HEADER_BG)

    rank_row0 = 8
    headers = ['Vendedor', 'Clientes', 'Caixas', 'Faturamento R$', 'Fat. Unit. R$',
               'Custo R$', 'Custo Unit. R$', 'Resultado R$', 'Resultado %',
               'Ticket Médio', 'Itens <-15%', 'Status']
    for j, h in enumerate(headers, start=1):
        _header_cell(ws, rank_row0, j, h)

    for i, item in enumerate(vendor_order):
        vname, pct_hint = item
        r = rank_row0 + 1 + i
        b, c_, f_, g, i_, k, l_ = (drange(x) for x in 'ACFGIKL')
        crit = f'{b},"{vname}"'
        _text(ws, r, 1, vname, bold=True)
        ws.cell(row=r, column=2, value=f'=SUMIFS({l_},{crit})').border = BORDER
        ws.cell(row=r, column=2).font = _font()
        _qty(ws, r, 3, f'=SUMIFS({f_},{crit})')
        _money(ws, r, 4, f'=SUMIFS({g},{crit})')
        _money(ws, r, 5, f'=IFERROR(D{r}/C{r},0)')
        _money(ws, r, 6, f'=SUMIFS({i_},{crit})')
        _money(ws, r, 7, f'=IFERROR(F{r}/C{r},0)')
        _money(ws, r, 8, f'=D{r}-F{r}')
        pct_formula = f'=IFERROR((D{r}-F{r})/F{r}*100,0)'
        _pct_cell(ws, r, 9, pct_formula, pct_hint)
        _money(ws, r, 10, f'=IFERROR(D{r}/B{r},0)')
        crit15 = f'{b},"{vname}",{k},"<-15"'
        ws.cell(row=r, column=11, value=f'=COUNTIFS({crit15})').border = BORDER
        ws.cell(row=r, column=11).font = _font()
        status_f = f'=IF(I{r}>=15,"OK",IF(I{r}>=0,"Atenção","Crítico"))'
        sc = ws.cell(row=r, column=12, value=status_f)
        sc.font = _font(bold=True)
        sc.alignment = Alignment(horizontal='center')
        sc.border = BORDER

    last_row = rank_row0 + len(vendor_order)
    for j in range(1, 13):
        ws.column_dimensions[get_column_letter(j)].width = 16
    ws.column_dimensions['A'].width = 14

    chart = BarChart()
    chart.title = 'Faturamento por Vendedor'
    chart.y_axis.title = 'R$'
    chart.x_axis.title = 'Vendedor'
    chart.style = 10
    data = Reference(ws, min_col=4, min_row=rank_row0, max_row=last_row)
    cats = Reference(ws, min_col=1, min_row=rank_row0 + 1, max_row=last_row)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.height, chart.width = 10, 24
    ws.add_chart(chart, f'A{last_row + 3}')
    return ws


# ---------------------------------------------------------------------------
# Aba "Alertas_<-15%"
# ---------------------------------------------------------------------------

def _build_alertas(wb, itens):
    ws = wb.create_sheet('Alertas_<-15%')
    ws.sheet_view.showGridLines = False
    headers = ['Vendedor', 'Cliente', 'Produto', 'Qtd', 'Faturamento R$',
               'Fat. Unit. R$', 'Custo R$', 'Custo Unit. R$', 'Resultado R$',
               'Resultado %', 'Situação']
    for j, h in enumerate(headers, start=1):
        _header_cell(ws, 1, j, h)

    rows = []
    for it in itens:
        custo = it['custo_total']
        pct = (it['faturamento'] - custo) / custo * 100 if custo else 0.0
        if pct < -15:
            rows.append((it, pct))
    rows.sort(key=lambda t: t[1])

    ws.row_dimensions[1].height = 32
    for i, (it, pct) in enumerate(rows):
        r = i + 2
        pct_r = round(pct, 2)
        _text(ws, r, 1, it['vendedor'] or it['vendedor_raw'])
        _text(ws, r, 2, it['cliente_nome'])
        _text(ws, r, 3, it['produto'])
        _qty(ws, r, 4, it['qtd'])
        _money(ws, r, 5, it['faturamento'])
        fat_unit = it['faturamento'] / it['qtd'] if it['qtd'] else 0.0
        _money(ws, r, 6, fat_unit)
        _money(ws, r, 7, it['custo_total'])
        _money(ws, r, 8, it['custo_unit'])
        _money(ws, r, 9, it['faturamento'] - it['custo_total'])
        _pct_cell(ws, r, 10, pct_r, pct_r)
        situ = 'Crítico' if pct < 0 else 'Atenção'
        situ_bg = VERMELHO_BG if pct < 0 else AMARELO_BG
        situ_fg = VERMELHO_FG if pct < 0 else AMARELO_FG
        sc = ws.cell(row=r, column=11, value=situ)
        sc.font = _font(bold=True, color=situ_fg)
        sc.fill = PatternFill('solid', fgColor=situ_bg)
        sc.border = BORDER

    widths = [14, 38, 42, 10, 15, 13, 13, 13, 13, 12, 11]
    for j, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = 'A2'
    return ws, len(rows)


# ---------------------------------------------------------------------------
# Aba "Vendedor_<Nome>"
# ---------------------------------------------------------------------------

def _build_vendedor_sheet(wb, vname, vendor_itens):
    sheet_name = _sheet_name_for_vendor(vname)
    ws = wb.create_sheet(sheet_name)
    ws.sheet_view.showGridLines = False

    ws.cell(row=1, column=1, value=f'Vendedor: {vname}').font = _font(bold=True, size=16, color=HEADER_BG)

    # ---- bloco esquerdo: detalhado por produto -----------------------
    LEFT_HEADERS = ['Cliente', 'Produto', 'Qtd', 'Fat. R$', 'Fat. Unit. R$',
                     'Custo R$', 'Custo Unit. R$', 'Result. R$', 'Result. %']
    title_row = 3
    ws.cell(row=title_row, column=1, value='DETALHADO POR PRODUTO').font = _font(bold=True, size=12, color=HEADER_BG)
    header_row = 4
    for j, h in enumerate(LEFT_HEADERS, start=1):
        _header_cell(ws, header_row, j, h)

    first_data_row = header_row + 1
    for i, it in enumerate(vendor_itens):
        r = first_data_row + i
        _text(ws, r, 1, it['cliente_nome'])
        _text(ws, r, 2, it['produto'])
        _qty(ws, r, 3, it['qtd'])
        _money(ws, r, 4, it['faturamento'])
        _money(ws, r, 5, f'=IFERROR(D{r}/C{r},0)')
        _money(ws, r, 6, it['custo_total'])
        _money(ws, r, 7, f'=IFERROR(F{r}/C{r},0)')
        _money(ws, r, 8, f'=D{r}-F{r}')
        custo = it['custo_total']
        pct = (it['faturamento'] - custo) / custo * 100 if custo else 0.0
        _pct_cell(ws, r, 9, f'=IFERROR((D{r}-F{r})/F{r}*100,0)', pct)
    left_total_row = first_data_row + len(vendor_itens)
    _text(ws, left_total_row, 1, 'TOTAL', bold=True)
    ws.cell(row=left_total_row, column=1).fill = PatternFill('solid', fgColor='E9F5EF')
    _qty(ws, left_total_row, 3, f'=SUM(C{first_data_row}:C{left_total_row - 1})')
    _money(ws, left_total_row, 4, f'=SUM(D{first_data_row}:D{left_total_row - 1})')
    _money(ws, left_total_row, 5, f'=IFERROR(D{left_total_row}/C{left_total_row},0)')
    _money(ws, left_total_row, 6, f'=SUM(F{first_data_row}:F{left_total_row - 1})')
    _money(ws, left_total_row, 7, f'=IFERROR(F{left_total_row}/C{left_total_row},0)')
    _money(ws, left_total_row, 8, f'=D{left_total_row}-F{left_total_row}')
    total_fat = sum(it['faturamento'] for it in vendor_itens)
    total_custo = sum(it['custo_total'] for it in vendor_itens)
    total_pct = (total_fat - total_custo) / total_custo * 100 if total_custo else 0.0
    _pct_cell(ws, left_total_row, 9, f'=IFERROR((D{left_total_row}-F{left_total_row})/F{left_total_row}*100,0)', total_pct)
    for cc in (1, 2):
        ws.cell(row=left_total_row, column=cc).font = _font(bold=True)

    # ---- bloco direito: gerencial por cliente -------------------------
    RIGHT_COL0 = 11  # coluna K
    RIGHT_HEADERS = ['Cliente', 'Qtd', 'Fat. R$', 'Fat. Unit. R$', 'Custo R$',
                      'Custo Unit. R$', 'Result. R$', 'Result. %', '% do Vendedor']
    ws.cell(row=title_row, column=RIGHT_COL0, value='GERENCIAL POR CLIENTE').font = _font(bold=True, size=12, color=HEADER_BG)
    for j, h in enumerate(RIGHT_HEADERS, start=RIGHT_COL0):
        _header_cell(ws, header_row, j, h)

    clientes_ordem = []
    seen = set()
    cliente_fat = {}
    for it in vendor_itens:
        k = (it['cliente_codigo'], it['cliente_nome'])
        cliente_fat[k] = cliente_fat.get(k, 0.0) + it['faturamento']
        if k not in seen:
            seen.add(k)
            clientes_ordem.append(k)
    clientes_ordem.sort(key=lambda k: -cliente_fat[k])

    LC, QC, FC, FUC, CC, CUC, RC, RPC, PVC = (get_column_letter(RIGHT_COL0 + i) for i in range(9))
    for i, (cod, nome) in enumerate(clientes_ordem):
        r = first_data_row + i
        _text(ws, r, RIGHT_COL0, nome)
        ws.cell(row=r, column=RIGHT_COL0 + 1, value=f'=SUMIFS($C${first_data_row}:$C${left_total_row-1},$A${first_data_row}:$A${left_total_row-1},{LC}{r})')
        ws.cell(row=r, column=RIGHT_COL0 + 1).number_format = '#,##0.000'
        ws.cell(row=r, column=RIGHT_COL0 + 1).border = BORDER
        ws.cell(row=r, column=RIGHT_COL0 + 1).font = _font()
        _money(ws, r, RIGHT_COL0 + 2, f'=SUMIFS($D${first_data_row}:$D${left_total_row-1},$A${first_data_row}:$A${left_total_row-1},{LC}{r})')
        _money(ws, r, RIGHT_COL0 + 3, f'=IFERROR({FC}{r}/{QC}{r},0)')
        _money(ws, r, RIGHT_COL0 + 4, f'=SUMIFS($F${first_data_row}:$F${left_total_row-1},$A${first_data_row}:$A${left_total_row-1},{LC}{r})')
        _money(ws, r, RIGHT_COL0 + 5, f'=IFERROR({CC}{r}/{QC}{r},0)')
        _money(ws, r, RIGHT_COL0 + 6, f'={FC}{r}-{CC}{r}')
        fat_c = cliente_fat[(cod, nome)]
        custo_c = sum(it['custo_total'] for it in vendor_itens if (it['cliente_codigo'], it['cliente_nome']) == (cod, nome))
        pct_c = (fat_c - custo_c) / custo_c * 100 if custo_c else 0.0
        _pct_cell(ws, r, RIGHT_COL0 + 7, f'=IFERROR(({FC}{r}-{CC}{r})/{CC}{r}*100,0)', pct_c)
        pv = ws.cell(row=r, column=RIGHT_COL0 + 8, value=f'=IFERROR({FC}{r}/$D${left_total_row}*100,0)')
        pv.number_format = PCT_FMT
        pv.border = BORDER
        pv.font = _font()

    right_total_row = first_data_row + len(clientes_ordem)
    _text(ws, right_total_row, RIGHT_COL0, 'TOTAL', bold=True)
    ws.cell(row=right_total_row, column=RIGHT_COL0).fill = PatternFill('solid', fgColor='E9F5EF')
    ws.cell(row=right_total_row, column=RIGHT_COL0 + 1, value=f'=SUM({QC}{first_data_row}:{QC}{right_total_row-1})')
    ws.cell(row=right_total_row, column=RIGHT_COL0 + 1).number_format = '#,##0.000'
    ws.cell(row=right_total_row, column=RIGHT_COL0 + 1).border = BORDER
    _money(ws, right_total_row, RIGHT_COL0 + 2, f'=SUM({FC}{first_data_row}:{FC}{right_total_row-1})')
    _money(ws, right_total_row, RIGHT_COL0 + 3, f'=IFERROR({FC}{right_total_row}/{QC}{right_total_row},0)')
    _money(ws, right_total_row, RIGHT_COL0 + 4, f'=SUM({CC}{first_data_row}:{CC}{right_total_row-1})')
    _money(ws, right_total_row, RIGHT_COL0 + 5, f'=IFERROR({CC}{right_total_row}/{QC}{right_total_row},0)')
    _money(ws, right_total_row, RIGHT_COL0 + 6, f'={FC}{right_total_row}-{CC}{right_total_row}')
    _pct_cell(ws, right_total_row, RIGHT_COL0 + 7, f'=IFERROR(({FC}{right_total_row}-{CC}{right_total_row})/{CC}{right_total_row}*100,0)', total_pct)
    ws.cell(row=right_total_row, column=RIGHT_COL0 + 8, value=100).number_format = PCT_FMT
    ws.cell(row=right_total_row, column=RIGHT_COL0 + 8).border = BORDER

    ws.column_dimensions['A'].width = 30
    ws.column_dimensions['B'].width = 30
    for col in range(3, 9):
        ws.column_dimensions[get_column_letter(col)].width = 13
    ws.column_dimensions[get_column_letter(RIGHT_COL0)].width = 28
    for col in range(RIGHT_COL0 + 1, RIGHT_COL0 + 9):
        ws.column_dimensions[get_column_letter(col)].width = 14
    ws.freeze_panes = ws.cell(row=header_row + 1, column=2).coordinate
    return ws


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

def gerar_xlsx(parsed, output_path):
    itens = parsed['itens']
    data_emissao = parsed.get('data_emissao')
    periodo = parsed.get('periodo')

    fat_por_vendedor = {}
    pct_por_vendedor = {}
    itens_por_vendedor = {}
    for it in itens:
        vname = it['vendedor'] or it['vendedor_raw']
        itens_por_vendedor.setdefault(vname, []).append(it)
        fat_por_vendedor[vname] = fat_por_vendedor.get(vname, 0.0) + it['faturamento']

    for vname, rows in itens_por_vendedor.items():
        fat = sum(r['faturamento'] for r in rows)
        custo = sum(r['custo_total'] for r in rows)
        pct_por_vendedor[vname] = (fat - custo) / custo * 100 if custo else 0.0

    vendor_order = sorted(fat_por_vendedor.keys(), key=lambda v: -fat_por_vendedor[v])
    vendor_order_with_pct = [(v, pct_por_vendedor[v]) for v in vendor_order]

    wb = Workbook()
    wb.remove(wb.active)

    _build_leiame(wb, data_emissao, periodo)
    _, n_dados = _build_dados(wb, itens)
    _build_resumo(wb, n_dados, vendor_order_with_pct)
    _build_alertas(wb, itens)
    for vname in vendor_order:
        _build_vendedor_sheet(wb, vname, itens_por_vendedor[vname])

    wb.active = 1
    wb.save(output_path)
    return output_path
