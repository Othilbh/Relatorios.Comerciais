"""Parser do relatório Estoque Físico - Othil-Bh (pdftotext -layout)."""
import re
import datetime

_NUM_RE    = re.compile(r'\b[\d]+(?:\.\d{3})*,\d+\b')
_DATE_RE   = re.compile(r'\b(\d{2}/\d{2}/\d{4})\b')
_CODE_RE   = re.compile(r'^\s{1,8}(\w[\w\./]*)(\s+)')
_EMIS_RE   = re.compile(r'Emiss[aã]o[:\s]+(\d{2}/\d{2}/\d{4})')
_PERIOD_RE = re.compile(r'Per[ií]odo de\s+(\d{2}/\d{2}/\d{4})')

_SKIP_STARTS = (
    'Empresa', 'Emiss', 'Par', 'Listando', 'Lista', 'Agrupa',
    'Produto', 'Código', 'Cód', 'Saldos', 'Qtde', 'Custo',
    'Total', 'c:\\app', 'Estoque', 'Usuário', 'Usu', 'Página',
    'Não', 'Nao', 'PREVIS', 'Depós',
)


def _pfloat(s):
    return float(s.replace('.', '').replace(',', '.'))


def _try_parse(line, produto_prefix=''):
    """Tenta extrair um produto de uma linha completa (ou continuação)."""
    nums = _NUM_RE.findall(line)
    if len(nums) < 5:
        return None
    date_m = _DATE_RE.search(line)
    if not date_m:
        return None

    # 5 últimos números: saldo_atual, anterior, qtd_vendida, custo_unit, md_venda
    saldo_atual = _pfloat(nums[-5])
    anterior    = _pfloat(nums[-4])
    qtd_vendida = _pfloat(nums[-3])
    custo_unit  = _pfloat(nums[-2])
    md_venda    = _pfloat(nums[-1])

    before_date = line[:date_m.start()].strip()

    if produto_prefix:
        # linha de continuação: before_date contém apenas o complemento
        codigo      = ''           # preenchido pelo chamador
        produto     = produto_prefix.strip()
        complemento = before_date.strip()
    else:
        code_m = _CODE_RE.match(line)
        if not code_m:
            return None
        codigo = code_m.group(1)
        rest   = line[code_m.end():date_m.start()].strip()
        parts  = rest.split()
        if parts:
            complemento = parts[-1]
            produto     = ' '.join(parts[:-1])
        else:
            complemento = ''
            produto     = ''

    data_str  = date_m.group(1)
    data_date = datetime.datetime.strptime(data_str, '%d/%m/%Y').date()

    return {
        'codigo':           codigo,
        'produto':          produto,
        'complemento':      complemento,
        'data_entrada_str': data_str,
        'data_entrada':     data_date,
        'saldo_atual':      saldo_atual,
        'anterior':         anterior,
        'qtd_vendida':      qtd_vendida,
        'custo_unit':       custo_unit,
        'md_venda':         md_venda,
        'valor_estoque':    round(saldo_atual * custo_unit, 2),
    }


def parse_estoque_fisico(text):
    """
    Parseia o texto extraído pelo pdftotext -layout do Estoque Físico.

    Retorna dict com:
      emissao        - string DD/MM/YYYY
      emissao_date   - datetime.date
      periodo        - string DD/MM/YYYY (início do período, se disponível)
      produtos       - lista de dicts com os campos do produto
    """
    lines       = text.split('\n')
    emissao_str = None
    periodo_str = None

    for line in lines[:30]:
        m = _EMIS_RE.search(line)
        if m:
            emissao_str = m.group(1)
        m = _PERIOD_RE.search(line)
        if m:
            periodo_str = m.group(1)

    emissao_date = (
        datetime.datetime.strptime(emissao_str, '%d/%m/%Y').date()
        if emissao_str
        else datetime.date.today()
    )

    produtos        = []
    pending_code    = None
    pending_produto = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            pending_code = pending_produto = None
            continue

        if any(stripped.startswith(k) or k in stripped[:30] for k in _SKIP_STARTS):
            pending_code = pending_produto = None
            continue

        has_date = bool(_DATE_RE.search(line))

        if has_date:
            if pending_code and not _CODE_RE.match(line):
                # Continuação de produto multi-linha
                r = _try_parse(line, produto_prefix=pending_produto)
                if r:
                    r['codigo'] = pending_code
                    produtos.append(r)
            else:
                # Linha completa normal
                r = _try_parse(line)
                if r:
                    produtos.append(r)
            pending_code = pending_produto = None
        else:
            # Possível início de produto multi-linha
            code_m = _CODE_RE.match(line)
            if code_m:
                pending_code    = code_m.group(1)
                pending_produto = line[code_m.end():].strip()
            else:
                pending_code = pending_produto = None

    return {
        'emissao':      emissao_str,
        'emissao_date': emissao_date,
        'periodo':      periodo_str,
        'produtos':     produtos,
    }
