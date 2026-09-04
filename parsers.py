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

NUM_RE  = re.compile(r'^-?[\d.]+,\d+$')
QTY3_RE = re.compile(r'^-?\d[\d.]*,\d{3}$')  # números com 3 casas decimais (quantidades)
# Casa uma quantidade (3 casas decimais) colada no FINAL de um token maior,
# ex.: "REGINALDO31,000" ou "CXREGINALDO1,000" — ver _extrair_qtde() abaixo.
QTY3_TAIL_RE = re.compile(r'(-?\d[\d.]*,\d{3})$')
MONEY2_RE = re.compile(r'^-?[\d.]+,\d{2}$')  # números com 2 casas decimais (dinheiro)
DATE_RE = re.compile(r'^\d{2}/\d{2}/\d{4}$')
VENDOR_LINE_RE = re.compile(r'^Vendedor:\s*(\d+)\s+(.+)$')

# Nomes dos vendedores que aparecem no campo Complemento do Estoque Físico.
# Mantido em sincronia manualmente com os aliases de VENDEDORES_PADRAO em
# calc.py (não importamos de lá para evitar import circular).
# Ordenado do nome mais longo pro mais curto, pra casar o nome mais
# específico primeiro quando houver ambiguidade.
KNOWN_VENDOR_NAMES = sorted(
    ['REGINALDO', 'AFANAIS', 'LUCIANO', 'CLAUDIA', 'JULIANA', 'FARLEY', 'DORA', 'RONI'],
    key=len, reverse=True,
)


def _clean_complemento(token: str) -> str:
    """O Complemento (vendedor responsável) às vezes sai colado com texto da
    coluna do Produto e embaralha 1-2 letras na fronteira (o mesmo bug de
    caracteres descrito no topo do arquivo: "PREMIUM"+"DORA" sai
    "PREMIUDMORA", "RONI" sai "RONISTONIS" etc.). Procura um nome de
    vendedor conhecido dentro do token — primeiro por igualdade exata de
    substring, depois por aproximação (até 1-2 letras diferentes na ponta,
    pra cobrir o embaralhamento) — e devolve só o nome limpo. Se nada bater,
    devolve o token original sem alteração."""
    raw_u = token.upper()
    for name in KNOWN_VENDOR_NAMES:
        if name in raw_u:
            return name
    for name in KNOWN_VENDOR_NAMES:
        if len(raw_u) < len(name):
            continue
        window = raw_u[-len(name):]
        mismatches = sum(1 for a, b in zip(window, name) if a != b)
        threshold = 1 if len(name) <= 5 else 2
        if mismatches <= threshold:
            return name
    return token


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
                complemento = _clean_complemento(toks[-7])
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
                # Às vezes a quantidade vendida sai colada sem espaço no nome do
                # vendedor responsável (mesmo bug de caracteres embaralhados citado
                # no docstring, ex.: "REGINALDO31,000" ou "CXREGINALDO1,000") — nesse
                # caso o token inteiro não bate com QTY3_RE e a quantidade real
                # desaparecia silenciosamente. Recuperamos ela procurando um número
                # de 3 casas decimais colado no FINAL de qualquer token da linha.
                glued_qty = None
                qty_nums = []
                for t in toks:
                    if QTY3_RE.match(t):
                        qty_nums.append(t)
                        continue
                    m = QTY3_TAIL_RE.search(t)
                    if m and glued_qty is None:
                        glued_qty = m.group(1)
                # BUG REAL corrigido 04/09/2026, reportado pela Ingrid ("A dole, não
                # está puxando toda a venda... Reginaldo vendeu 99 cx. Afanais vendeu
                # 83", print do relatório mostrando bem menos). Cabeçalho REAL deste
                # relatório (conferido linha a linha no PDF que ela enviou): "Código
                # Descrição UN Qtd Vendida Devoluções Total Vendas Val.Unit. Custo
                # Total Lucro Liq. Lucro Unit. Lucro %" -- ou seja, existem
                # exatamente DUAS colunas com 3 casas decimais (formato quantidade:
                # 5,000): Qtd Vendida (a PRIMEIRA) e Devoluções (a segunda, sempre
                # 0,000 neste relatório) -- "Total Vendas" é uma coluna de DINHEIRO
                # (2 casas decimais, R$), não uma 3ª coluna de quantidade. O código
                # antigo assumia o contrário (comentário antigo dizia "o último
                # desses é sempre o Total das Saídas Qtd") e pegava sempre o ÚLTIMO
                # número de 3 casas -- que na prática é quase sempre Devoluções =
                # 0,000, zerando silenciosamente a Qtd Vendida de quase toda linha
                # "saudável" (sem o bug de colagem acima).
                qtde_primaria = to_float(glued_qty) if glued_qty is not None else (
                    to_float(qty_nums[0]) if qty_nums else None
                )
                # Verificação cruzada / recuperação via colunas de dinheiro:
                # "Total Vendas" (2 casas) sempre vem logo após "Devoluções" (o
                # último token que bate QTY3_RE), seguido de "Val.Unit." (2 casas).
                # Nas linhas saudáveis deste relatório, Total Vendas ÷ Val.Unit. =
                # Qtd Vendida EXATAMENTE (confirmado em 104 linhas limpas reais,
                # nenhuma divergência) -- essa é uma identidade aritmética do
                # próprio ERP (Total Vendas = Qtd Vendida × Val.Unit.), não um
                # número inventado, então serve tanto pra RECUPERAR a Qtd Vendida
                # quando ela está irrecuperável no texto (ex.: linhas com
                # complemento "-RONISTONIS", onde as letras do nome do vendedor mais
                # longo do sistema se intercalam DENTRO dos dígitos, sobrando só a
                # Devolução "0,000" reconhecível) quanto pra CORRIGIR um valor colado
                # truncado (ex.: "CRXEGINALD1O3,000" pro vendedor FARLEY/produto
                # 8707112 -- o dígito "1" fica preso antes da letra "O" e o regex de
                # cauda só recupera o "3,000" final, quando o valor real, confirmado
                # por Total Vendas 780,00 ÷ Val.Unit. 60,00, é 13 -- mesmo padrão de
                # embaralhamento do docstring, "PREMIUM"+"DORA"->"PREMIUDMORA",
                # aplicado a um número em vez de uma palavra).
                qtde_dinheiro = None
                if qty_nums:
                    idx_devol = toks.index(qty_nums[-1])
                    if idx_devol + 2 < len(toks):
                        tot_tok, val_tok = toks[idx_devol + 1], toks[idx_devol + 2]
                        if MONEY2_RE.match(tot_tok) and MONEY2_RE.match(val_tok):
                            val_unit = to_float(val_tok)
                            if val_unit:
                                derived = to_float(tot_tok) / val_unit
                                if abs(derived - round(derived)) < 0.05:
                                    qtde_dinheiro = round(derived)
                if qtde_dinheiro is not None and (
                    qtde_primaria is None or abs(qtde_primaria - qtde_dinheiro) > 0.5
                ):
                    qtde = float(qtde_dinheiro)
                elif qtde_primaria is not None:
                    qtde = qtde_primaria
                else:
                    continue
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
