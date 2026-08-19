"""Parsers de relatórios de Estoque - Othil-Bh (pdftotext -layout).

Dois formatos distintos neste arquivo, cada um com sua função própria
(NÃO são intercambiáveis -- estruturas de coluna diferentes):

  parse_estoque_fisico()  -- relatório "Estoque Físico" (1 data por linha
                              de produto, usado em Prevenção de Perdas).
  parse_resumo_estoque()  -- relatório "Resumo do Estoque" (sem data por
                              linha; produtos agrupados sob cabeçalhos
                              "Grupo: <código> <nome oficial>", 13 campos
                              numéricos por linha: Saldo Inicial, Entrada,
                              Saída, Transf. Saí, Saldo Final, Custo, Total
                              Saída, Valor Saí., Méd.Saí., Custo Saída,
                              Méd.Cto., Resultado, %). Usado em Relatórios
                              de Produtos (Projeto 2).
"""
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


# ---------------------------------------------------------------------------
# Resumo do Estoque -- Relatórios de Produtos (Projeto 2)
# ---------------------------------------------------------------------------

_NUM_TOKEN_RE = re.compile(r'^-?\d{1,3}(?:\.\d{3})*(?:,\d+)?$')
_GRUPO_RE = re.compile(r'^Grupo:\s+(\S+)\s+(.*)$')

# Nomes conhecidos de "Complemento" (consignatário/fornecedor do lote) --
# mesmo conjunto usado em xlsx_vendedor_cliente.VENDOR_TAB, mais nomes
# observados neste relatório que ainda não estão lá (ex.: ADILSON, RONI,
# REINALDO). Usado só para separar Produto de Complemento quando as duas
# colunas ficam coladas ou muito próximas no texto extraído do PDF -- o
# layout de largura fixa não é confiável nesses casos porque o nome do
# produto às vezes invade o espaço da coluna Complemento. Se um nome novo
# aparecer fora desta lista, ele fica dentro do nome do produto (nunca é
# descartado) e é sinalizado nos avisos, pra não inventar dado.
_COMPLEMENTOS_CONHECIDOS = [
    'AFANAIS', 'CLAUDIA', 'DORA', 'FARLEY', 'JULIANA', 'LUCA', 'LUCIANO',
    'REGINALDO', 'REINALDO', 'RONISTONIS', 'RONI', 'ADILSON',
]
_COMPLEMENTOS_ORDENADOS = sorted(_COMPLEMENTOS_CONHECIDOS, key=len, reverse=True)
_COMPLEMENTO_TOKEN_RE = re.compile(
    r'^(?:' + '|'.join(_COMPLEMENTOS_CONHECIDOS) +
    r')(?:/(?:' + '|'.join(_COMPLEMENTOS_CONHECIDOS) + r'))*$'
)


def _pnum_resumo(s):
    return float(s.replace('.', '').replace(',', '.'))


def _split_trailing_numeros(line, n=13):
    """Separa os últimos `n` tokens numéricos (formato BR) do resto da
    linha. None se a linha não terminar com exatamente esse padrão --
    usado pra reconhecer linha de produto completa vs. cabeçalho/Sub-Total/
    linha quebrada em duas."""
    partes = line.rsplit(None, n)
    if len(partes) != n + 1:
        return None
    cauda = partes[1:]
    if not all(_NUM_TOKEN_RE.match(t) for t in cauda):
        return None
    return partes[0], [_pnum_resumo(t) for t in cauda]


def _separar_produto_complemento(miolo):
    """miolo = texto entre o código e a UN (produto [+ complemento])."""
    tokens = miolo.split()
    if not tokens:
        return '', '', None

    ultimo = tokens[-1]
    if _COMPLEMENTO_TOKEN_RE.match(ultimo):
        return ' '.join(tokens[:-1]), ultimo, None

    # caso "colado" (estouro de coluna): o complemento fica grudado no
    # fim da última palavra, sem espaço (ex.: "200GRREGINALDO")
    for nome in _COMPLEMENTOS_ORDENADOS:
        if ultimo.endswith(nome) and len(ultimo) > len(nome):
            prefixo_colado = ultimo[: -len(nome)]
            novos_tokens = tokens[:-1] + ([prefixo_colado] if prefixo_colado else [])
            return ' '.join(novos_tokens), nome, None

    # não achou complemento reconhecido -> tudo vira produto; sinaliza
    # como aviso (pode ser um novo nome de consignatário fora da lista)
    return ' '.join(tokens), '', ultimo


def parse_resumo_estoque(texto):
    """Parseia o texto (pdftotext -layout) do relatório "Resumo do
    Estoque". Estrutura: seções "Grupo: <código> <nome oficial>" (o nome
    oficial do grupo de produtos do ERP -- muito mais preciso que o chute
    por palavra-chave de categorias.py), cada uma com N linhas de produto
    (Código, Produto, Complemento, UN + 13 campos numéricos: Saldo
    Inicial, Entrada, Saída, Transf. Saí, Saldo Final, Custo, Total
    Saída, Valor Saí., Méd.Saí., Custo Saída, Méd.Cto., Resultado, %) e
    uma linha "Sub-Total"; termina com uma linha "Total Geral".

    Retorna dict:
      itens   -- lista de dicts, um por linha de produto (ver campos
                 abaixo), na ordem em que aparecem no relatório.
      grupos  -- {código_do_grupo: nome_oficial}
      avisos  -- linhas/nomes que não puderam ser interpretados com
                 confiança total (nunca descartados silenciosamente --
                 ver módulo produtos.py sobre como isso é exibido).
      emissao / emissao_date -- data de emissão do relatório (cabeçalho).

    Cada item de `itens`: codigo, produto, complemento, un, grupo_codigo,
    grupo_nome, saldo_inicial, entrada, saida, transf_saida, saldo_final,
    custo (custo unitário médio do saldo), total_saida, valor_saida
    (faturamento das saídas), med_saida, custo_saida, med_custo,
    resultado (= valor_saida - custo_saida), pct_sobre_custo (=
    resultado/custo_saida*100 -- é a definição usada NO PRÓPRIO
    relatório, diferente da convenção margem%=margem/faturamento usada
    no resto do app; ver produtos.itens_de_resumo_estoque()).

    Reconciliação: a soma de saida/valor_saida/custo_saida/resultado de
    todos os itens bate exatamente com a linha "Total Geral" do relatório
    (testado com o PDF real de 14/08/2026 -- 288 itens em 100 grupos)."""
    linhas = texto.split('\n')
    grupos = {}
    ordem_grupos = []
    grupo_atual = None
    pendente = None
    avisos = []
    emissao_str = None

    for linha in linhas:
        s = linha.rstrip('\n')
        if not s.strip():
            continue

        if emissao_str is None:
            m = _EMIS_RE.search(s)
            if m:
                emissao_str = m.group(1)

        if s.strip().startswith(('Empresa/Filial', 'Emiss', 'Resumo do Estoque',
                                  'c:\\app', 'Clique aqui', 'Código', 'Usuário',
                                  'Página')):
            continue

        gm = _GRUPO_RE.match(s.strip())
        if gm:
            codigo_g = gm.group(1)
            resto = gm.group(2)
            # a linha do Grupo às vezes traz um "complemento fantasma" do
            # 1º produto colado no fim (artefato de layout) -- pega só a
            # 1ª "coluna" (separada por 2+ espaços) como nome do grupo.
            nome_g = re.split(r'\s{2,}', resto.strip())[0].strip()
            if codigo_g not in grupos:
                grupos[codigo_g] = {'nome': nome_g, 'itens': []}
                ordem_grupos.append(codigo_g)
            grupo_atual = codigo_g
            pendente = None
            continue

        if 'Sub-Total' in s or 'Total Geral' in s:
            pendente = None
            continue

        resultado = _split_trailing_numeros(s, 13)
        if resultado is None:
            partes = s.split(None, 1)
            if grupo_atual and partes and re.match(r'^[\w./]+$', partes[0]):
                codigo_cand = partes[0]
                texto_cand = partes[1].strip() if len(partes) > 1 else ''
                # o complemento às vezes já vem nesta 1ª linha (quando só
                # o nome do produto é longo o bastante pra quebrar em
                # duas linhas) -- tenta separar aqui também, em vez de
                # assumir que ele só vai aparecer na linha de continuação.
                produto_cand, complemento_cand, _ = _separar_produto_complemento(texto_cand)
                pendente = (codigo_cand, produto_cand, complemento_cand)
            elif grupo_atual:
                avisos.append(f'Linha não reconhecida (ignorada): {s[:80]!r}')
            continue

        prefixo, nums = resultado
        (saldo_ini, entrada, saida, transf_sai, saldo_fin, custo,
         total_saida, valor_sai, med_sai, custo_saida, med_cto,
         resultado_rs, pct) = nums

        prefixo = prefixo.strip()
        m_un = re.search(r'(.*\S)\s+(\S+)\s*$', prefixo)
        if m_un:
            resto_sem_un, un = m_un.group(1), m_un.group(2)
        else:
            resto_sem_un, un = '', prefixo

        aviso_nome = None
        if pendente is not None:
            codigo, produto, complemento_1a_linha = pendente
            complemento_cont = resto_sem_un.strip()
            if complemento_1a_linha:
                complemento = complemento_1a_linha
                if complemento_cont:
                    avisos.append(
                        f"Produto {codigo!r}: texto extra {complemento_cont!r} "
                        f"na linha de continuação, ignorado (complemento já "
                        f"veio da 1ª linha: {complemento_1a_linha!r})."
                    )
            else:
                complemento = complemento_cont
                if complemento and not _COMPLEMENTO_TOKEN_RE.match(complemento):
                    aviso_nome = complemento
            pendente = None
        else:
            partes = resto_sem_un.split(None, 1)
            if not partes:
                avisos.append(f'Linha sem código reconhecível: {s[:80]!r}')
                continue
            codigo = partes[0]
            miolo = partes[1] if len(partes) > 1 else ''
            produto, complemento, aviso_nome = _separar_produto_complemento(miolo)

        if aviso_nome:
            avisos.append(
                f"Possível nome de complemento não catalogado ({aviso_nome!r}) "
                f"na linha do produto {codigo!r} — mantido dentro do nome do "
                f"produto por segurança."
            )

        if not grupo_atual:
            avisos.append(f'Produto fora de qualquer Grupo (ignorado): {s[:80]!r}')
            continue

        grupos[grupo_atual]['itens'].append({
            'codigo': codigo, 'produto': produto, 'complemento': complemento,
            'un': un, 'grupo_codigo': grupo_atual,
            'grupo_nome': grupos[grupo_atual]['nome'],
            'saldo_inicial': saldo_ini, 'entrada': entrada, 'saida': saida,
            'transf_saida': transf_sai, 'saldo_final': saldo_fin,
            'custo': custo, 'total_saida': total_saida,
            'valor_saida': valor_sai, 'med_saida': med_sai,
            'custo_saida': custo_saida, 'med_custo': med_cto,
            'resultado': resultado_rs, 'pct_sobre_custo': pct,
        })

    itens = []
    for cod in ordem_grupos:
        itens.extend(grupos[cod]['itens'])

    emissao_date = (
        datetime.datetime.strptime(emissao_str, '%d/%m/%Y').date()
        if emissao_str else datetime.date.today()
    )
    return {
        'itens': itens,
        'grupos': {c: grupos[c]['nome'] for c in ordem_grupos},
        'avisos': avisos,
        'emissao': emissao_str,
        'emissao_date': emissao_date,
    }
