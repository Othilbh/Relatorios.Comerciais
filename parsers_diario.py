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
import unicodedata

MONEY2 = r'-?\d{1,3}(?:\.\d{3})*,\d{2}'
QTY3 = r'-?\d{1,3}(?:\.\d{3})*,\d{3}'

_SEQ = [3, 2, 2, 3, 2, 2, 3, 2, 2, 2, 2, 2, 2, 2, 3, 2]

VENDOR_RE = re.compile(r'^Vendedor:\s*\d+\s*-\s*(.+)$')
CLIENTE_RE = re.compile(r'^Cliente:\s*([\w*]+)\s*-\s*(.+?)\s{2,}Cidade:')
TOT_CLIENTE_RE = re.compile(r'^\s*Totais do Cliente - (.+):\s+(\S.*)$')
TOT_VENDEDOR_RE = re.compile(r'^\s*Totais do Vendedor - (.+):\s+(\S.*)$')
TOTAL_GERAL_RE = re.compile(r'^\s*Total Geral:\s+(\S.*)$')
EMISSAO_RE = re.compile(r'Emissão:\s*(\d{2}/\d{2}/\d{4})')
PERIODO_RE = re.compile(r'Período\s*:\s*(\d{2}/\d{2}/\d{4}[^N]*?\d{2}/\d{2}/\d{4})')

VENDOR_ALIASES = {
    'ADILSON-DORA': 'Dora',
    'AFANAIS': 'Afanais',
    'CLAUDIA': 'Claudia',
    'FARLEY': 'Farley',
    'JULIANA AUGUSTA': 'Juliana',
    'LUCA-VENDEDOR': 'Luca',
    'LUCIANO': 'Luciano',
    'REGINALDO': 'Reginaldo',
    'RONISTONIS': 'Roni',
}

_KNOWN_COMPLEMENTOS = sorted([
    'ADILSON', 'AFANAIS', 'CLAUDIA', 'FARLEY', 'JULIANA AUGUSTA', 'JULIANA',
    'LUCA VENDEDOR', 'LUCA', 'LUCIANO', 'REGINALDO', 'RONISTONIS', 'RONI', 'DORA',
], key=len, reverse=True)

# Sem '\b' antes de "CX": quando o nome do vendedor/complemento é longo o
# bastante para preencher a coluna até encostar em "CX" (ex.: "RONISTONIS"
# -- "...RONISTONISCX       2,000..."), não sobra espaço nenhum entre o
# texto e "CX", e um '\b' ali exigiria uma fronteira \w->\W que não existe
# entre "S" e "C" (ambos caracteres de palavra). Com o '\b' a linha inteira
# não era reconhecida como linha de produto: vazava pra "pending_lines" e
# contaminava o produto seguinte (que "herdava" o código errado, e o
# produto de verdade -- cujo texto tinha vazado -- desaparecia do
# cálculo). "CX" só marca a coluna de unidade nesse relatório, então não
# há necessidade de exigir fronteira de palavra antes dele.
#
# O nome do vendedor responsável também pode aparecer DEPOIS de "CX", colado
# direto na quantidade -- às vezes sem espaço nenhum em nenhum dos dois lados
# (ex.: "CX REGINALDO31,000", ou até "CXREGINALDO1,000" totalmente colado).
# É o mesmo bug de caracteres embaralhados perto da junção com o nome do
# vendedor responsável citado no topo do arquivo. Sem tolerar esse nome
# opcional entre "CX" e o número, a linha inteira não batia com CX_RE e a
# venda inteira era perdida (não sobrava nem fallback: o pdftotext é tentado
# primeiro e só cai pra pdfplumber se a lista de linhas vier vazia, o que não
# acontece aqui porque outros produtos da mesma página continuam batendo).
#
# Terceiro caso (achado com um PDF real da Ingrid, 28/08/2026): quando a
# descrição é comprida demais, a linha do produto quebra e a quantidade
# inteira fica sozinha na linha física SEGUINTE -- ex.: uma linha termina
# em "...AMARELO-LUCIANO -CX    LUCIANO" (SEM nenhum número, nem colado) e
# só a linha de baixo tem "112,000   0,000   13.440,00...". O código já
# tinha um mecanismo pronto pra esperar a quantidade na linha seguinte
# (pending_qty, ver mais abaixo), mas ele só era acionado quando CX_RE
# batia NA linha (exigindo um dígito logo depois de "CX"/complemento) --
# aqui não tem dígito nenhum na linha, então CX_RE nunca batia, a linha
# inteira vazava pra "pending_lines" (texto solto) SEM acionar o
# pending_qty, e o código/descrição certos se perdiam: o próximo produto
# que realmente batesse com CX_RE "herdava" por engano o código da linha
# vazada (o dígito inicial de "pending_lines" acumulado), fazendo os dois
# produtos ficarem errados ao mesmo tempo. Adicionando "|\s*$" no lookahead
# faz CX_RE também bater nesse caso (fim de linha logo após "CX"/nome), o
# que aciona corretamente o pending_qty já existente -- tail fica vazio,
# _extrai_qtde_fat_tail(tail) retorna None como já era esperado, e a
# quantidade é recuperada certinho na linha seguinte.
_COMPLEMENTO_ALT = '|'.join(re.escape(n) for n in _KNOWN_COMPLEMENTOS)
CX_RE = re.compile(r'CX\s*(?:(?:' + _COMPLEMENTO_ALT + r')\s*)?(?=[\d\-,.]|\s*$)')


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


def _tokenize_tail(tail: str, seq=None):
    """seq: sequência de nº de casas decimais esperada por campo (3=Qtd,
    2=Dinheiro). Default (None) usa a global _SEQ, calibrada pro relatório
    'Lucratividade por Vendedor-Cliente' (COM traço, Relatório Diário) --
    ver _SEQ_META abaixo para o layout do relatório SEM traço (Metas)."""
    if seq is None:
        seq = _SEQ
    pos, n, vals = 0, len(tail), []
    for dec in seq:
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
    'Outras Saidas', 'Total das Saidas', 'Custo Unit', 'Resultado Unit',
    'Emissao', 'Emiss',
]


def _strip_accents(s: str) -> str:
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')


def _is_junk_line(line: str) -> bool:
    """Reconhece linhas de cabeçalho/rodapé repetidas (empresa, período,
    cabeçalho de coluna 'Código Descrição...', etc.) que aparecem entre
    clientes/páginas e não são produto. Compara sem acento porque o PDF usa
    acentuação (ex.: 'Código Descrição', 'Saídas por Vendas') enquanto
    _JUNK_MARKERS está em ASCII — sem essa normalização essas linhas
    "vazam" pro nome do produto seguinte.

    Também normaliza espaços internos (colapsa sequências de espaços em um
    só): o `pdftotext -layout` alinha cabeçalhos largos (ex.: 'Saídas por
    Vendas') sobre 3 sub-colunas estreitas (Qtd/Unit/Total), inserindo
    espaços extra entre as palavras do próprio cabeçalho (ex.: 'Saídas
    por     Vendas'). Sem colapsar, o marcador com espaço único não bate
    e a linha inteira vaza pro nome do produto seguinte."""
    line_na = _strip_accents(line)
    line_na = re.sub(r'\s+', ' ', line_na).strip()
    if line_na.startswith('Codigo Descricao'):
        return True
    stripped = line.strip()
    if not stripped:
        return False
    return any(marker in line_na for marker in _JUNK_MARKERS)


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


# ---------------------------------------------------------------------------
# Parser de Lucratividade por Vendedor (formato sem traço — relatório de metas)
# ---------------------------------------------------------------------------

# "Vendedor: 11  REGINALDO"  (sem traço entre número e nome)
_VENDOR_RE_META = re.compile(r'^Vendedor:\s*\d+\s+(.+)$')

# BUG REAL corrigido 04/09/2026, reportado pela Ingrid ("A meta semanal
# continua errada com a dole" -- Reginaldo saindo 63cx/Afanais 73cx em vez
# dos 99cx/83cx confirmados). _extrai_qtde_fat_tail() reusava _SEQ/_QTY_INDICES
# (calibrados pro relatório "Lucratividade por Vendedor-CLIENTE", COM traço,
# usado no Relatório Diário -- 3 trincas Qtd/Unit/Total: Saídas por Vendas /
# Outras Saídas / Total das Saídas, 16 campos ao todo) só que aplicado ao
# relatório "Lucratividade por VENDEDOR", SEM traço, usado aqui nas Metas
# Semanais -- um relatório com layout DIFERENTE (conferido linha a linha no
# PDF real da Ingrid via `pdftotext -layout`, mesmo texto que este parser lê):
# "Qtd Vendida Devoluções Total Vendas Val.Unit. Custo Total Lucro Liq.
# Lucro Unit. Lucro %" -- 8 campos, sendo só os DOIS primeiros de quantidade
# (3 casas): Qtd Vendida (índice 0) e Devoluções (índice 1, quase sempre
# 0,000) -- os 6 seguintes são todos dinheiro/percentual (2 casas). Ao
# tokenizar com a sequência ERRADA (16 campos, começando com 3 trincas de
# 3,2,2), o segundo campo real (Devoluções, 3 casas) não batia com o padrão
# de DINHEIRO (2 casas) esperado naquela posição e a tokenização quebrava
# cedo -- e mesmo quando não quebrava, o índice usado (_QTY_INDICES, pensado
# pro "Total das Saídas Qtd" do OUTRO relatório) não correspondia a nada
# útil neste. Resultado: quantidade errada silenciosamente pra quase toda
# linha. Diferente de parsers.py (que usa pdfplumber e sofre embaralhamento
# de caracteres perto do nome do vendedor), aqui o `pdftotext -layout` extrai
# os números da coluna "CX ..." limpos, numa linha física própria -- então
# não precisa da recuperação por token colado nem da verificação cruzada via
# Total Vendas ÷ Val.Unit. feitas em parsers.py; só a sequência de campos
# certa (_SEQ_META) já resolve.
_SEQ_META = [3, 3, 2, 2, 2, 2, 2, 2]
_QTY_INDEX_META = 0   # Qtd Vendida (a PRIMEIRA das duas colunas de 3 casas)
_FAT_INDEX_META = 2   # Total Vendas (R$)

# Casa uma quantidade (3 casas decimais) colada no FINAL da linha de
# descrição (ver comentário em parse_vendas_pdftotext, produto 010110090 /
# Complemento "RONISTONIS") -- mesmo padrão de QTY3_TAIL_RE em parsers.py.
_QTY3_TAIL_RE = re.compile(r'(-?\d[\d.]*,\d{3})$')


def _extrai_qtde_tail(tail: str):
    """Tenta extrair a Qtd Vendida de um trecho de texto que deveria conter
    os números de uma linha de produto (o que vem depois de "CX "). Retorna
    None se não achar nenhum número aproveitável.

    Estratégia:
      - Tokeniza posicionalmente com _SEQ_META (layout do relatório "Lucra-
        tividade por Vendedor", sem traço) e pega o campo de índice
        _QTY_INDEX_META (Qtd Vendida).
      - Se a tokenização posicional falhar (relatório com "--------" nas
        colunas zeradas), cai para extrair por regex os números com 3 casas
        decimais (ou, na falta deles, qualquer número) e pega o PRIMEIRO
        (Qtd Vendida vem antes de Devoluções na linha).
    """
    return _extrai_qtde_fat_tail(tail)[0]


def _extrai_qtde_fat_tail(tail: str):
    """Como _extrai_qtde_tail, mas também tenta extrair o Faturamento (Total
    Vendas R$, índice _FAT_INDEX_META de _SEQ_META) da mesma linha. Retorna
    (qtde, faturamento) -- faturamento vem None quando a tokenização
    posicional falha (ex.: relatório com "--------" nas colunas zeradas) ou
    quando a linha tem menos campos que o necessário; nesses casos ainda dá
    pra recuperar ao menos a quantidade via regex, mas o Faturamento fica
    indisponível pra aquela linha específica -- nunca inventa um valor.
    Usada pelo cálculo de 'R$ Médio por caixa' das Metas Semanais."""
    vals = _tokenize_tail(tail, seq=_SEQ_META)
    if vals:
        qtde = vals[_QTY_INDEX_META] if _QTY_INDEX_META < len(vals) else vals[0]
        faturamento = vals[_FAT_INDEX_META] if len(vals) > _FAT_INDEX_META else None
        return qtde, faturamento

    qty3_matches = re.findall(r'\b\d[\d.]*,\d{3}\b', tail)
    if qty3_matches:
        return _to_float(qty3_matches[0]), None
    any_nums = re.findall(r'\b\d[\d.]*,\d+\b', tail)
    if any_nums:
        return _to_float(any_nums[0]), None
    return None, None


def parse_vendas_pdftotext(file) -> list[dict]:
    """Parseia o relatório 'Lucratividade por Vendedor' (formato sem traço no
    cabeçalho do vendedor) usando pdftotext -layout.

    Retorna lista de dicts: {'vendedor': str, 'codigo': str, 'qtde_vendida': float,
    'descricao': str, 'faturamento': float | None} — mesmo formato de
    parse_vendas() em parsers.py (mais os campos 'descricao', usado por
    calc.sugestao_codigo_por_nome para detectar código configurado errado
    quando o NOME do produto bate mas o código não, e 'faturamento', usado
    pelo cálculo de 'R$ Médio por caixa' das Metas Semanais -- None quando a
    linha não permitiu extrair o valor com confiança, nunca inventado),
    usando a tokenização posicional de _tokenize_tail para não depender de
    espaços entre colunas.
    """
    text = extract_text(file)
    rows_out = []
    cur_vendor_raw = None
    pending_lines = []
    # Guarda {'codigo', 'vendedor'} quando uma linha de produto tem "CX" mas
    # NENHUM número em seguida na mesma linha (layout raro em que a
    # quantidade fica sozinha, sem "CX", na linha física seguinte — visto em
    # produtos cuja Qtd de "Saídas por Vendas" fica em branco/"-", o que
    # desloca o "CX" pra colar direto na descrição). Sem esse tratamento, a
    # venda desse produto era perdida (linha descartada) E o número da linha
    # seguinte "vazava" como se fosse o CÓDIGO do próximo produto (ex.: um
    # "1,000" órfão virava um código fantasma "1"), fazendo o próximo produto
    # de verdade desaparecer do cálculo também.
    pending_qty = None

    for line in text.split('\n'):
        # Cabeçalho de vendedor
        m = _VENDOR_RE_META.match(line)
        if m:
            cur_vendor_raw = m.group(1).strip()
            pending_lines = []
            pending_qty = None
            continue

        if _is_junk_line(line):
            pending_lines = []
            pending_qty = None
            continue

        # Uma linha de produto anterior ficou esperando a quantidade (ver
        # comentário acima) -- tenta consumir esta linha como sendo ela,
        # antes de tratá-la como início de um novo produto.
        if pending_qty is not None:
            qtde_pendente, fat_pendente = _extrai_qtde_fat_tail(line)
            if qtde_pendente is not None:
                rows_out.append({
                    'vendedor': pending_qty['vendedor'],
                    'codigo': pending_qty['codigo'],
                    'qtde_vendida': qtde_pendente,
                    'descricao': pending_qty['descricao'],
                    'faturamento': fat_pendente,
                })
                pending_qty = None
                continue
            # Sem número nesta linha. Visto em PDF real (28/08/2026): às
            # vezes o nome do vendedor responsável TAMBÉM quebra sozinho
            # pra sua própria linha física (ex.: "- REGINALDO", sem "CX" e
            # sem nenhum número), entre a linha do código/CX e a linha dos
            # números -- ou seja, a quantidade pode estar a MAIS de uma
            # linha de distância. Se esta linha for só texto solto (não
            # começa com dígito -- não parece início de outro código -- e
            # não bate com CX_RE -- não é a linha "CX" de outro produto),
            # continua esperando na próxima linha em vez de desistir na
            # primeira tentativa; só desiste quando a linha parecer
            # claramente outra coisa (outro produto começando, ou vazia),
            # pra não arriscar interpretar errado uma linha sem relação.
            stripped_wait = line.strip()
            if stripped_wait and not re.match(r'^\d', stripped_wait) and not CX_RE.search(line):
                continue
            pending_qty = None

        # Linha de produto (tem "CX " seguido de número)
        cxm = CX_RE.search(line)
        if cxm and cur_vendor_raw:
            before = line[:cxm.start()].strip()
            full_desc = ' '.join(pending_lines + ([before] if before else []))
            pending_lines = []

            # BUG REAL corrigido 04/09/2026 (pedido da Ingrid, "a meta
            # semanal continua errada com a dole" -- Reginaldo/Afanais
            # divergindo por exatamente 36cx e 10cx). Confirmado no PDF real
            # dela: quando o Complemento é "RONISTONIS" num produto
            # específico (010110090, Dole 90 Ponto Azul), a Qtd Vendida sai
            # colada no FINAL da linha de DESCRIÇÃO (uma linha ANTES da
            # linha "CX ..."), ex.: "...AZUL-RONISTONIS - RONISTONIS36,000"
            # -- e a linha "CX" seguinte começa direto em Devoluções, sem
            # nenhuma Qtd Vendida nela. Mesmo bug-irmão do que já existe em
            # parsers.py (número colado sem espaço perto do nome do
            # vendedor responsável), só que aqui colado na descrição em vez
            # de na quantidade em si. Sem este tratamento a linha inteira
            # tokenizava a partir de Devoluções (0,000) como se fosse Qtd
            # Vendida, zerando a venda real.
            m_glued_desc = _QTY3_TAIL_RE.search(full_desc)
            glued_qtde = _to_float(m_glued_desc.group(1)) if m_glued_desc else None
            full_desc_sem_qtd = full_desc[:m_glued_desc.start()].rstrip() if m_glued_desc else full_desc

            # Extrai código do início da descrição
            cm = re.match(r'^(\d[\d.]*)', full_desc_sem_qtd.strip())
            if not cm:
                continue
            codigo = cm.group(1)
            descricao = _clean_produto(full_desc_sem_qtd)

            tail = line[cxm.end():]
            if glued_qtde is not None:
                # A Qtd Vendida já foi recuperada da descrição -- o "tail"
                # desta linha começa direto em Devoluções (Qtd Vendida
                # ausente aqui), então tokeniza pulando o primeiro campo da
                # sequência esperada.
                vals_sem_qtd = _tokenize_tail(tail, seq=_SEQ_META[1:])
                qtde = glued_qtde
                faturamento = vals_sem_qtd[1] if len(vals_sem_qtd) > 1 else None
            else:
                qtde, faturamento = _extrai_qtde_fat_tail(tail)

            if qtde is None:
                # A quantidade não veio nesta linha -- provavelmente está
                # sozinha na linha seguinte (ver comentário no topo da
                # função). Guarda o código/vendedor pra tentar de novo no
                # próximo laço, em vez de descartar a venda.
                pending_qty = {'codigo': codigo, 'vendedor': cur_vendor_raw, 'descricao': descricao}
                continue

            rows_out.append({
                'vendedor': cur_vendor_raw,
                'codigo': codigo,
                'qtde_vendida': qtde,
                'descricao': descricao,
                'faturamento': faturamento,
            })
            continue

        stripped = line.strip()
        if stripped:
            pending_lines.append(stripped)

    return rows_out
