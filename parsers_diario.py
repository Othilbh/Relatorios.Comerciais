"""Parser do relatório 'Lucratividade por Vendedor-Cliente no Previsão'
(Mercatus) usado no módulo Relatório Diário de Vendas OTHIL.

Diferente de parsers.py (que usa pdfplumber/posição de palavra), aqui o
texto é extraído com `pdftotext -layout` por exigência da Ingrid, porque
esse relatório específico cola números adjacentes sem espaço quando a
coluna anterior já preenche toda a largura (ex.: "500,00166,10" é
"500,00" + "166,10"). Para separar corretamente sem depender de espaços,
cada linha de números é tokenizada por POSIÇÃO esperada no layout: a
sequência de campos é sempre [Qtd(3 dec), Unit(2 dec), Total(2 dec)] três
vezes (Saídas por Vendas / Outras Saídas / Total das Saídas), depois
Custo Unit./Total (2 dec), Desconto (2 dec), Resultado Unit./Total (2 dec),
Resultado % (3 dec) e, só nas linhas de totais, Comissão Total (2 dec).
"""
import re
import subprocess
import tempfile
import os

MONEY2 = r'-?\d{1,3}(?:\.\d{3})*,\d{2}'
QTY3 = r'-?\d{1,3}(?:\.\d{3})*,\d{3}'

_SEQ = [3, 2, 2, 3, 2, 2, 3, 2, 2, 2, 2, 2, 2, 2, 3, 2]

VENDOR_RE = re.compile(r'^Vendedor:\s*\d+\s*-\s*(.+)$')
CLIENTE_RE = re.compile(r'^Cliente:\s*([\w*]+)\s*-\s*(.+?)\s{2,}Cidade:')
TOT_CLIENTE_RE = re.compile(r'^\s*Totais do Cliente - (.+):\s+(\S.*)$')
TOT_VENDEDOR_RE = re.compile(r'^\s*Totais do Vendedor - (.+):\s+(\S.*)$')
TOTAL_GERAL_RE = re.compile(r'^\s*Total Geral:\s+(\S.*)$')
CX_RE = re.compile(r'\bCX\s+(?=[\d\-,.])')
EMISSAO_RE = re.compile(r'Emissão:\s*(\d{2}/\d{2}/\d{4})')
PERIODO_RE = re.compile(r'Período\s*:\s*(\d{2}/\d{2}/\d{4}[^N]*?\d{2}/\d{2}/\d{4})')

VENDOR_ALIASES = {
    'ADILSON-DORA': 'Dora',
    'AFANAIS': 'Afanais',
    'FARLEY': 'Farley',
    'JULIANA AUGUSTA': 'Juliana',
    'LUCA - VENDEDOR': 'Luca',
    'LUCIANO': 'Luciano',
    'REGINALDO': 'Reginaldo',
    'RONISTONIS': 'Roni',
}

_KNOWN_COMPLEMENTOS = sorted([
    'ADILSON', 'AFANAIS', 'FARLEY', 'JULIANA AUGUSTA', 'JULIANA',
    'LUCA VENDEDOR', 'LUCA', 'LUCIANO', 'REGINALDO', 'RONISTONIS', 'RONI', 'DORA',
], key=len, reverse=True)


class ValidationError(Exception):
    def __init__(self, divergencias):
        self.divergencias = divergencias
        super().__init__(f'{len(divergencias)} divergencia(s) na validacao')


def _norm_vendor_key(raw: str) -> str:
    s = raw.strip().upper()
    s = re.sub(r'\s*-\s*', '-', s)
    s = re.sub(r'\s+', ' ', s)
    return s


def map_vendedor(raw: str):
    return VENDOR_ALIASES.get(_norm_vendor_key(raw))


def _to_float(s: str) -> float:
    return float(s.replace('.', '').replace(',', '.'))


def _tokenize_tail(tail: str):
    pos, n, vals = 0, len(tail), []
    for dec in _SEQ:
        while pos < n and tail[pos].isspace():
            pos += 1
        if pos >= n:
            break
        pat = QTY3 if dec == 3 else MONEY2
        m = re.match(pat, tail[pos:])
        if not m:
            break
        vals.append(_to_float(m.group(0)))
        pos += m.end()
    return vals


def _strip_trailing_complemento(text: str) -> str:
    t = text.rstrip()
    t_u = t.upper()
    for name in _KNOWN_COMPLEMENTOS:
        if t_u.endswith(name):
            return t[:len(t) - len(name)].rstrip()
    return t


def _strip_leading_code(text: str) -> str:
    return re.sub(r'^\d[\d.]*\s*', '', text).strip()


def _clean_produto(raw: str) -> str:
    return _strip_leading_code(_strip_trailing_complemento(raw)) or raw.strip()


_JUNK_MARKERS = [
    'Empresa/Filial', 'Emissao:', 'Lucratividade por Vendedor', 'Usuario:',
    'recursos\\relatorios', '.rtm', 'Parametros:', 'Vendedor(es):',
    'Pessoa(s):', 'Produto(s):', 'Base para Percentual', 'Quebra e Avaria',
    'Considera frete', 'Classificacao :', 'Saidas por Vendas',
    'Emissao', 'Emiss',
]


def _is_junk_line(line: str) -> bool:
    if line.lstrip().startswith('Codigo Descricao'):
        return True
    stripped = line.strip()
    if not stripped:
        return False
    return any(marker in line for marker in _JUNK_MARKERS)


def extract_text(file) -> str:
    tmp_path = None
    try:
        if hasattr(file, 'read'):
            data = file.read()
            fd, tmp_path = tempfile.mkstemp(suffix='.pdf')
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
            pdf_path = tmp_path
        else:
            pdf_path = file
        result = subprocess.run(
            ['pdftotext', '-layout', pdf_path, '-'],
            capture_output=True, check=True,
        )
        return result.stdout.decode('utf-8', errors='replace')
    finally:
        if tmp_path:
            os.remove(tmp_path)


def parse_relatorio_diario(file, tolerancia=1.0):
    text = extract_text(file)
    lines = text.split('\n')

    cur_vendor_raw = None
    cur_cliente_codigo = None
    cur_cliente_nome = None
    itens = []
    cliente_oficiais = {}
    vendedor_oficiais = {}
    total_geral = None
    data_emissao = None
    periodo = None
    pending_lines = []

    for line in lines:
        if data_emissao is None:
            m = EMISSAO_RE.search(line)
            if m:
                data_emissao = m.group(1)
        if periodo is None:
            m = PERIODO_RE.search(line)
            if m:
                periodo = m.group(1).strip()

        m = VENDOR_RE.match(line)
        if m:
            cur_vendor_raw = m.group(1).strip()
            pending_lines = []
            continue
        m = CLIENTE_RE.match(line)
        if m:
            cur_cliente_codigo = m.group(1)
            cur_cliente_nome = m.group(2).strip()
            pending_lines = []
            continue
        m = TOT_CLIENTE_RE.match(line)
        if m:
            vals = _tokenize_tail(m.group(2))
            if len(vals) >= 14 and cur_vendor_raw and cur_cliente_codigo:
                cliente_oficiais[(cur_vendor_raw, cur_cliente_codigo)] = {
                    'qtd': vals[6], 'faturamento': vals[8],
                    'custo_total': vals[10],
                }
            pending_lines = []
            continue
        m = TOT_VENDEDOR_RE.match(line)
        if m:
            vals = _tokenize_tail(m.group(2))
            if len(vals) >= 14 and cur_vendor_raw:
                vendedor_oficiais[cur_vendor_raw] = {
                    'qtd': vals[6], 'faturamento': vals[8],
                    'custo_total': vals[10],
                }
            pending_lines = []
            continue
        m = TOTAL_GERAL_RE.match(line)
        if m:
            vals = _tokenize_tail(m.group(1))
            if len(vals) >= 14:
                total_geral = {'qtd': vals[6], 'faturamento': vals[8],
                               'custo_total': vals[10], 'resultado': vals[13]}
            pending_lines = []
            continue

        if _is_junk_line(line):
            pending_lines = []
            continue

        cxm = CX_RE.search(line)
        if cxm:
            if not (cur_vendor_raw and cur_cliente_codigo):
                pending_lines = []
                continue
            before = line[:cxm.start()].strip()
            full_desc = ' '.join(pending_lines + ([before] if before else []))
            pending_lines = []
            if not full_desc:
                full_desc = '(produto)'
            tail = line[cxm.end():]
            vals = _tokenize_tail(tail)
            if len(vals) < 14:
                continue
            itens.append({
                'vendedor_raw': cur_vendor_raw,
                'vendedor': map_vendedor(cur_vendor_raw),
                'cliente_codigo': cur_cliente_codigo,
                'cliente_nome': cur_cliente_nome,
                'produto': _clean_produto(full_desc),
                'qtd': vals[6],
                'faturamento': vals[8],
                'custo_unit': vals[9],
                'custo_total': vals[10],
                'resultado': vals[13],
            })
            continue

        stripped = line.strip()
        if stripped:
            pending_lines.append(stripped)

    divergencias = []
    agg_cliente = {}
    agg_vendedor = {}
    for it in itens:
        kc = (it['vendedor_raw'], it['cliente_codigo'])
        ac = agg_cliente.setdefault(kc, {'faturamento': 0.0, 'custo_total': 0.0})
        ac['faturamento'] += it['faturamento']
        ac['custo_total'] += it['custo_total']
        av = agg_vendedor.setdefault(it['vendedor_raw'], {'faturamento': 0.0, 'custo_total': 0.0})
        av['faturamento'] += it['faturamento']
        av['custo_total'] += it['custo_total']

    for k, oficial in cliente_oficiais.items():
        extraido = agg_cliente.get(k, {'faturamento': 0.0, 'custo_total': 0.0})
        df = abs(extraido['faturamento'] - oficial['faturamento'])
        dc = abs(extraido['custo_total'] - oficial['custo_total'])
        if df > tolerancia or dc > tolerancia:
            divergencias.append({
                'nivel': 'cliente', 'vendedor_raw': k[0], 'cliente_codigo': k[1],
                'faturamento_extraido': extraido['faturamento'], 'faturamento_oficial': oficial['faturamento'],
                'custo_extraido': extraido['custo_total'], 'custo_oficial': oficial['custo_total'],
            })
    for k, oficial in vendedor_oficiais.items():
        extraido = agg_vendedor.get(k, {'faturamento': 0.0, 'custo_total': 0.0})
        df = abs(extraido['faturamento'] - oficial['faturamento'])
        dc = abs(extraido['custo_total'] - oficial['custo_total'])
        if df > tolerancia or dc > tolerancia:
            divergencias.append({
                'nivel': 'vendedor', 'vendedor_raw': k,
                'faturamento_extraido': extraido['faturamento'], 'faturamento_oficial': oficial['faturamento'],
                'custo_extraido': extraido['custo_total'], 'custo_oficial': oficial['custo_total'],
            })

    return {
        'data_emissao': data_emissao,
        'periodo': periodo,
        'itens': itens,
        'total_geral': total_geral,
        'divergencias': divergencias,
    }
