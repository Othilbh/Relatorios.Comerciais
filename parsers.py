"""Parsers para os relatórios em PDF do ERP da Othil (Estoque Físico e
Lucratividade por Vendedor / "vendas acumuladas").

Os PDFs são gerados por um sistema legado que renderiza o texto com posições
de caractere pouco confiáveis (ex.: "PREMIUM"+"DORA" pode sair como
"PREMIUDMORA"). Por isso, em vez de confiar no texto corrido, agrupamos as
*palavras* por posição vertical (linha) e horizontal (coluna), e identificamos
os campos numéricos pelo formato (####,###) em vez de por nome de coluna.
"""
import re
import pdfplumber

NUM_RE = re.compile(r'^-?[\d.]+,\d+$')
DATE_RE = re.compile(r'^\d{2}/\d{2}/\d{4}$')
VENDOR_LINE_RE = re.compile(r'^Vendedor:\s*(\d+)\s+(.+)$')


def cluster_rows(words, tol=3.0):
    """Agrupa palavras em linhas usando a primeira palavra do grupo como
    âncora vertical (em vez de média corrente, que deriva e funde linhas
    próximas de ~10pt de altura)."""
    words = sorted(words, key=lambda w: w['top'])
    rows, cur, anchor = [], [], None
    for w in words:
        if cur and abs(w['top'] - anchor) > tol:
            rows.append(cur)
            cur = []
            anchor = None
        cur.append(w)
        if anchor is None:
            anchor = w['top']
    if cur:
        rows.append(cur)
    return rows


def to_float(s):
    return float(s.replace('.', '').replace(',', '.'))


def parse_estoque(file) -> list[dict]:
    """Parseia o relatório 'Estoque Físico'.

    Retorna lista de dicts: codigo, produto, complemento (vendedor
    responsável), data_entrada, saldo_atual, saldo_anterior, qtde_vendida,
    custo_unitario, md_venda.
    """
    rows_out = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=1.5, use_text_flow=False)
            data_words = [w for w in words if w['top'] > 165]
            for r in cluster_rows(data_words):
                r.sort(key=lambda w: w['x0'])
                toks = [w['text'] for w in r]
                if len(toks) < 7:
                    continue
                if not re.match(r'^\d', toks[0]):
                    continue
                if not DATE_RE.match(toks[-6]) or not NUM_RE.match(toks[-1]):
                    continue
                codigo = toks[0]
                complemento = toks[-7]
                data = toks[-6]
                atual, anterior, vendida, custo, md = toks[-5:]
                produto = ' '.join(toks[1:-7])
                rows_out.append({
                    'codigo': codigo,
                    'produto': produto,
                    'complemento': complemento,
                    'data_entrada': data,
                    'saldo_atual': to_float(atual),
                    'saldo_anterior': to_float(anterior),
                    'qtde_vendida': to_float(vendida),
                    'custo_unitario': to_float(custo),
                    'md_venda': to_float(md),
                })
    return rows_out


def parse_vendas(file) -> list[dict]:
    """Parseia o relatório 'Lucratividade por Vendedor' (vendas acumuladas).

    Retorna lista de dicts: vendedor, codigo, qtde_vendida.
    Apenas código + quantidade vendida são extraídos com confiança total —
    a descrição é ignorada pois sofre o mesmo problema de caracteres
    embaralhados perto da junção com o nome do vendedor responsável.
    """
    rows_out = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=1.5, use_text_flow=False)
            current_vendor = None
            for r in cluster_rows(words):
                r.sort(key=lambda w: w['x0'])
                toks = [w['text'] for w in r]
                line = ' '.join(toks)
                m = VENDOR_LINE_RE.match(line)
                if m:
                    current_vendor = m.group(2).strip()
                    continue
                if current_vendor is None or not toks:
                    continue
                first = toks[0]
                codematch = re.match(r'^(\d[\d.]*[XYZ]?)', first)
                if not codematch:
                    continue
                codigo = codematch.group(1)
                nums = [t for t in toks if NUM_RE.match(t)]
                if not nums:
                    continue
                qtde = to_float(nums[0])
                rows_out.append({
                    'vendedor': current_vendor,
                    'codigo': codigo,
                    'qtde_vendida': qtde,
                })
    return rows_out


def normalize_codigo(codigo: str) -> str:
    """Remove sufixo decimal (.1, .2...) e zeros à esquerda para comparação
    entre os dois relatórios, que às vezes formatam o mesmo código de forma
    diferente (com/sem zero à esquerda)."""
    base = codigo.split('.')[0]
    m = re.match(r'^0*(\d+)([A-Z]*)$', base)
    if m:
        return m.group(1) + m.group(2)
    return base
