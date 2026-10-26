"""Componente central de RELATÓRIOS DE PRODUTOS — Projeto 2.

Reaproveita 100% a base histórica consolidada e os filtros já construídos
em rentabilidade.py (Projeto 3) -- mesma fonte de dados (módulo
'relatorio_diario', via data_store), mesma regra de prioridade Diário >
Semanal > Mensal para nunca contar a mesma venda duas vezes. Este módulo
NÃO reimplementa a consolidação nem os cálculos de agregação/margem: só
adiciona o que é específico da análise por produto (ranking com
crescimento/queda, top/bottom, evolução multi-produto, participação,
Produto x Vendedor, Produto x Cliente, matrizes pivotadas, destaques e
alertas).

Unidade: a base não tem campo explícito de unidade -- 'qtd' representa
caixas (cx) em todo o app (mesma convenção usada em dashboard_diario.py,
xlsx_diario.py, etc.). Este módulo segue a mesma convenção; se um dia a
base ganhar um campo de unidade por produto, é só passar a usá-lo aqui.
"""
import datetime as _dt

import data_store as ds
import periodo as periodo_mod
import rentabilidade as rt
import categorias

# Reexporta o necessário da base -- quem usa produtos.py não precisa
# importar rentabilidade.py também para as operações comuns.
carregar_base_consolidada = rt.carregar_base_consolidada
periodos_disponiveis = rt.periodos_disponiveis
filtrar_periodo = rt.filtrar_periodo
agregar = rt.agregar
por_vendedor = rt.por_vendedor
por_cliente = rt.por_cliente
evolucao = rt.evolucao

def _fmt_moeda(v):
    s = f"{abs(v):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"R$ {'-' if v < 0 else ''}{s}"


UNIDADE_PADRAO = 'cx'

# Fonte de dados do Resumo do Estoque (upload de PDF direto nesta página --
# ver itens_de_resumo_estoque()/carregar_base_estoque() mais abaixo).
MOD_PRODUTOS_ESTOQUE = 'produtos_estoque'


# ---------------------------------------------------------------------------
# categoria: usa o Grupo oficial do item quando presente (fonte Resumo do
# Estoque), senão cai pro chute por palavra-chave de categorias.py (fonte
# antiga, Vendedor-Cliente/Relatório Diário -- comportamento IDÊNTICO ao
# de antes, já que esses itens nunca têm campo 'categoria').
# ---------------------------------------------------------------------------

def _categoria_de(it):
    return it.get('categoria') or categorias.map_categoria(it.get('produto', ''))


def por_produto(itens):
    def extra(sub):
        return {'categoria': _categoria_de(sub[0])} if sub else {'categoria': '(sem categoria)'}
    return rt.agregar_por(itens, lambda it: it.get('produto'), extra)


def por_categoria(itens):
    return rt.agregar_por(itens, _categoria_de)


def filtrar_dimensoes(itens, vendedores=None, clientes=None, produtos=None, categorias_sel=None):
    out = rt.filtrar_dimensoes(itens, vendedores=vendedores, clientes=clientes, produtos=produtos)
    if categorias_sel:
        cats = set(categorias_sel)
        out = [it for it in out if _categoria_de(it) in cats]
    return out


def opcoes_dimensoes(itens):
    vendedores, clientes, produtos, _ = rt.opcoes_dimensoes(itens)
    categorias_op = sorted({_categoria_de(it) for it in itens})
    return vendedores, clientes, produtos, categorias_op


# ---------------------------------------------------------------------------
# Fonte de dados: Resumo do Estoque (Projeto 2 -- substitui, só nesta
# página, a base de Vendedor-Cliente: essa fonte só cobre os clientes
# cadastrados no módulo Vendedor-Cliente, e a Ingrid precisa do total de
# vendas de TODOS os clientes -- pedido explícito dela).
# ---------------------------------------------------------------------------

def itens_de_resumo_estoque(parsed, data_ref):
    """Converte a saída de parsers_estoque.parse_resumo_estoque() pro
    formato de 'item' usado em todo este módulo (mesmos campos de
    rentabilidade.py: faturamento, custo_total, qtd, vendedor,
    cliente_codigo, _data_ref) -- assim TODAS as funções de agregação/
    ranking/comparação já existentes funcionam sem nenhuma mudança.

    Usa o Grupo oficial do PDF como 'categoria' (em vez do chute por
    palavra-chave). NÃO inventa cliente: esta fonte é um resumo de
    estoque por produto, sem detalhamento por cliente -- cliente_codigo/
    cliente_nome ficam sempre None (ver aviso na tela). 'vendedor' usa o
    campo Complemento do relatório (consignatário/fornecedor do lote,
    mesmo conjunto de nomes de xlsx_vendedor_cliente.VENDOR_TAB).

    Margem é calculada do mesmo jeito que em todo o resto do app
    (margem_rs = faturamento - custo, margem_pct = margem_rs/faturamento
    x 100 -- via rentabilidade.agregar()), e não pela fórmula do próprio
    relatório (Resultado / Custo Saída x 100, margem sobre CUSTO) -- os
    dois batem em R$ (Resultado do PDF == faturamento - custo aqui), só
    o jeito de calcular o % é diferente; o valor original do PDF fica
    guardado em 'pct_sobre_custo_origem' só como referência."""
    itens = []
    for it in parsed['itens']:
        itens.append({
            'produto': it['produto'],
            'categoria': it['grupo_nome'],
            'codigo_produto': it['codigo'],
            'grupo_codigo': it['grupo_codigo'],
            'vendedor': it['complemento'] or None,
            'cliente_codigo': None,
            'cliente_nome': None,
            'faturamento': it['valor_saida'],
            'custo_total': it['custo_saida'],
            'qtd': it['saida'],
            'un': it['un'],
            'pct_sobre_custo_origem': it['pct_sobre_custo'],
            '_data_ref': data_ref,
            '_origem_tipo': 'resumo_estoque',
        })
    return itens


def salvar_resumo_estoque(parsed, usuario=None):
    """Persiste um upload de Resumo do Estoque via data_store (histórico
    completo, nunca sobrescreve -- ds.save_record já move a versão atual
    pra history). periodo_ref é sempre mensal, derivado da data de
    emissão do próprio relatório. Retorna (periodo_ref, registro)."""
    data_ref = parsed.get('emissao_date') or _dt.date.today()
    periodo_ref_str = periodo_mod.periodo_ref('mensal', data_ref)
    itens = itens_de_resumo_estoque(parsed, data_ref)
    # data_store persiste em JSON -- date não é serializável, salva como
    # ISO string e converte de volta na leitura (carregar_base_estoque).
    itens_serializaveis = [{**it, '_data_ref': it['_data_ref'].isoformat()} for it in itens]
    valores = {
        'itens': itens_serializaveis,
        'avisos': parsed.get('avisos') or [],
        'grupos': parsed.get('grupos') or {},
        'emissao': parsed.get('emissao'),
        'n_itens': len(itens),
    }
    registro = ds.save_record(modulo=MOD_PRODUTOS_ESTOQUE, tipo_periodo='mensal',
                               periodo_ref=periodo_ref_str, valores=valores, usuario=usuario)
    return periodo_ref_str, registro


def carregar_base_estoque():
    """Junta os itens de TODOS os Resumos do Estoque já salvos (um por
    mês, cada upload substitui só o mês que ele cobre -- meses diferentes
    se somam). Mesmo formato de retorno de carregar_base_consolidada()
    (itens, avisos), pra ser um substituto direto na tela."""
    itens = []
    avisos = []
    for periodo_ref_str in ds.list_periodos(MOD_PRODUTOS_ESTOQUE, 'mensal'):
        reg = ds.load_current(MOD_PRODUTOS_ESTOQUE, 'mensal', periodo_ref_str)
        if not reg:
            continue
        valores = reg.get('valores', {}) or {}
        for it in (valores.get('itens') or []):
            it = dict(it)
            dref = it.get('_data_ref')
            if isinstance(dref, str):
                it['_data_ref'] = _dt.date.fromisoformat(dref)
            itens.append(it)
        for a in (valores.get('avisos') or []):
            avisos.append(f"[{periodo_ref_str}] {a}")
    return itens, avisos

# Limiares padrão dos alertas (ajustáveis na tela -- não há regra de
# negócio fixa definida hoje para nenhum destes critérios).
LIMIAR_QUEDA_PCT_PADRAO = 20.0                  # queda de X% no indicador = alerta
LIMIAR_CONCENTRACAO_PCT_PADRAO = 50.0           # top 3 produtos concentrando >= X% do faturamento
LIMIAR_VOLUME_ALTO_FAT_BAIXO_PADRAO = 10.0      # % mínima de participação em volume p/ avaliar desproporção


# ---------------------------------------------------------------------------
# KPIs específicos de produto
# ---------------------------------------------------------------------------

def kpis_produto(itens):
    """KPIs do módulo: agregados gerais (agregar() -- já inclui faturamento,
    custo, margem_rs, margem_pct, volume, etc.) + SKUs distintos vendidos
    (contagem de produtos diferentes, NÃO confundir com volume em caixas) +
    ticket médio por produto (Faturamento / nº de SKUs) + produto líder
    (maior faturamento no recorte) + grupo líder (categoria com maior
    faturamento no recorte -- ver categorias.py)."""
    base = rt.agregar(itens)
    skus = len({it.get('produto') for it in itens if it.get('produto')})
    ticket_medio_produto = (base['faturamento'] / skus) if skus else 0.0
    prods = por_produto(itens)
    lider = max(prods, key=lambda p: p['faturamento']) if prods else None
    cats = por_categoria(itens)
    grupo_lider = max(cats, key=lambda c: c['faturamento']) if cats else None
    return {
        **base,
        'skus': skus,
        'unidade': UNIDADE_PADRAO,
        'ticket_medio_produto': round(ticket_medio_produto, 2),
        'produto_lider': lider['chave'] if lider else None,
        'produto_lider_faturamento': lider['faturamento'] if lider else 0.0,
        'grupo_lider': grupo_lider['chave'] if grupo_lider else None,
        'grupo_lider_faturamento': grupo_lider['faturamento'] if grupo_lider else 0.0,
    }


# ---------------------------------------------------------------------------
# Ranking com crescimento/queda vs período anterior
# ---------------------------------------------------------------------------

def _ranking_generico(itens_atual, itens_anterior, por_fn, indicador='faturamento'):
    """Base comum de ranking-com-comparação, parametrizada pela função de
    agregação (por_produto ou por_categoria) -- evita duplicar a mesma
    lógica de comparação para produto e para grupo (categoria).

    Além do crescimento/queda do `indicador` escolhido, SEMPRE acrescenta a
    comparação de margem (margem_rs_anterior/diferença e
    margem_pct_anterior/variação -- esta última em PONTOS PERCENTUAIS, não
    confundir com variação percentual comum) quando houver contrapartida no
    período anterior. Linhas sem contrapartida entram com
    status_crescimento='novo' e todos os campos de comparação em None (não
    inventa valor)."""
    atual = por_fn(itens_atual)
    anterior_map = {l['chave']: l for l in por_fn(itens_anterior)} if itens_anterior else {}
    linhas = []
    for l in atual:
        ant = anterior_map.get(l['chave'])
        if ant is None:
            linhas.append({
                **l, 'valor_anterior': None, 'diferenca': None,
                'crescimento_pct': None, 'status_crescimento': 'novo',
                'margem_rs_anterior': None, 'margem_rs_diferenca': None,
                'margem_pct_anterior': None, 'margem_pct_variacao_pp': None,
            })
            continue
        val_atual = l.get(indicador, 0.0)
        val_ant = ant.get(indicador, 0.0)
        diff = val_atual - val_ant
        if val_ant:
            cresc = diff / val_ant * 100
        else:
            cresc = 100.0 if val_atual > 0 else 0.0
        status = 'crescimento' if diff > 1e-9 else ('queda' if diff < -1e-9 else 'estavel')

        margem_rs_ant = ant.get('margem_rs', 0.0)
        margem_rs_diff = l.get('margem_rs', 0.0) - margem_rs_ant
        margem_pct_ant = ant.get('margem_pct', 0.0)
        margem_pct_pp = l.get('margem_pct', 0.0) - margem_pct_ant

        linhas.append({
            **l, 'valor_anterior': round(val_ant, 2), 'diferenca': round(diff, 2),
            'crescimento_pct': round(cresc, 2), 'status_crescimento': status,
            'margem_rs_anterior': round(margem_rs_ant, 2), 'margem_rs_diferenca': round(margem_rs_diff, 2),
            'margem_pct_anterior': round(margem_pct_ant, 2), 'margem_pct_variacao_pp': round(margem_pct_pp, 2),
        })
    return linhas


def ranking_com_crescimento(itens_atual, itens_anterior=None, indicador='faturamento'):
    """por_produto(atual), acrescido de comparação com por_produto(anterior)
    pela chave (nome do produto). indicador: 'faturamento' | 'volume' |
    'margem_rs'. Produtos sem contrapartida no período anterior entram com
    crescimento_pct=None e status_crescimento='novo' (não é tratado como
    queda nem inventa um valor). Também acrescenta comparação de margem
    (R$ e p.p.) independente do `indicador` escolhido -- ver
    `_ranking_generico`."""
    return _ranking_generico(itens_atual, itens_anterior, por_produto, indicador)


def ranking_categorias_com_crescimento(itens_atual, itens_anterior=None, indicador='faturamento'):
    """Mesma lógica de `ranking_com_crescimento`, mas agrupada por grupo de
    produtos (categoria -- ver categorias.py) em vez de por produto
    individual. Usado no Nível 1 do drill-down por grupo (Entrega 3)."""
    return _ranking_generico(itens_atual, itens_anterior, por_categoria, indicador)


def contagem_crescimento_queda(linhas_ranking):
    """Conta quantas linhas de um ranking-com-crescimento estão em
    crescimento/queda/estável/novo -- usado nos resumos executivos (KPIs e
    Gerência) para responder 'quantos produtos cresceram vs caíram' sem
    listar cada um."""
    out = {'crescimento': 0, 'queda': 0, 'estavel': 0, 'novo': 0}
    for l in linhas_ranking:
        out[l.get('status_crescimento', 'novo')] = out.get(l.get('status_crescimento', 'novo'), 0) + 1
    return out


def produtos_sem_venda_no_periodo(itens_atual, itens_anterior):
    """Produtos que tinham venda no período anterior e não têm nenhuma no
    atual (informação explícita, não some silenciosamente)."""
    if not itens_anterior:
        return []
    atuais_chaves = {it.get('produto') for it in itens_atual if it.get('produto')}
    anterior_prod = por_produto(itens_anterior)
    return [p for p in anterior_prod if p['chave'] not in atuais_chaves]


# ---------------------------------------------------------------------------
# Top / atenção
# ---------------------------------------------------------------------------

def top_produtos(linhas_ranking, criterio='Maior faturamento', n=10):
    chaves = {'Maior volume': 'volume', 'Maior faturamento': 'faturamento',
              'Maior crescimento': 'crescimento_pct', 'Maior participação': 'participacao_faturamento'}
    chave = chaves.get(criterio, 'faturamento')

    def _key(l):
        v = l.get(chave)
        return v if v is not None else float('-inf')
    return sorted(linhas_ranking, key=_key, reverse=True)[:n]


def produtos_atencao(linhas_ranking, criterio='Menor faturamento', n=10):
    """criterio: 'Menor volume' | 'Menor faturamento' | 'Maior queda'.
    NUNCA rotula um produto como "ruim" -- só ordena pelo critério
    explicitamente escolhido pela usuária, e a tela deixa claro qual foi
    usado (item 9 do briefing: vender pouco não é necessariamente ruim)."""
    if criterio == 'Menor volume':
        return sorted(linhas_ranking, key=lambda l: l.get('volume', 0.0))[:n]
    if criterio == 'Menor faturamento':
        return sorted(linhas_ranking, key=lambda l: l.get('faturamento', 0.0))[:n]
    if criterio == 'Maior queda':
        quedas = [l for l in linhas_ranking
                  if l.get('crescimento_pct') is not None and l['crescimento_pct'] < 0]
        return sorted(quedas, key=lambda l: l['crescimento_pct'])[:n]
    return linhas_ranking[:n]


# ---------------------------------------------------------------------------
# Evolução multi-produto
# ---------------------------------------------------------------------------

def evolucao_por_produto(itens, produtos_selecionados, granularidade='dia', metrica='faturamento'):
    """{produto: [{'rotulo', 'data_ord', 'valor'}, ...]} -- uma série
    temporal por produto selecionado, para comparação lado a lado (Produto
    A x B x C)."""
    out = {}
    for p in produtos_selecionados:
        itens_p = [it for it in itens if it.get('produto') == p]
        serie = evolucao(itens_p, granularidade=granularidade)
        out[p] = [{'rotulo': s['rotulo'], 'data_ord': s['data_ord'], 'valor': s.get(metrica, 0.0)}
                  for s in serie]
    return out


# ---------------------------------------------------------------------------
# Cruzamentos Produto x Vendedor / Produto x Cliente
# ---------------------------------------------------------------------------

def cruzamento(itens, dim1_fn, dim2_fn, rotulo1='Dim1', rotulo2='Dim2', extra_fn=None):
    """Agrupa itens por (dim1, dim2) e agrega cada grupo, incluindo a
    participação de cada linha dentro do total de dim1 (ex.: participação
    do vendedor nas vendas DAQUELE produto)."""
    grupos = {}
    por_dim1 = {}
    for it in itens:
        k1 = dim1_fn(it) or '(não identificado)'
        k2 = dim2_fn(it) or '(não identificado)'
        grupos.setdefault((k1, k2), []).append(it)
        por_dim1.setdefault(k1, []).append(it)

    col_part = f'% do {rotulo1}'
    linhas = []
    for (k1, k2), sub in grupos.items():
        ag = agregar(sub)
        total_dim1 = agregar(por_dim1[k1])
        part = (ag['faturamento'] / total_dim1['faturamento'] * 100) if total_dim1['faturamento'] else 0.0
        linha = {rotulo1: k1, rotulo2: k2, **ag, col_part: round(part, 2)}
        if extra_fn:
            linha.update(extra_fn(sub))
        linhas.append(linha)
    return linhas


def produto_x_vendedor_tabela(itens):
    return cruzamento(itens, lambda it: it.get('produto'),
                       lambda it: it.get('vendedor') or it.get('vendedor_raw'),
                       'Produto', 'Vendedor')


def produto_x_cliente_tabela(itens):
    def _extra(sub):
        acc = {}
        for it in sub:
            v = it.get('vendedor') or it.get('vendedor_raw') or '(não identificado)'
            acc[v] = acc.get(v, 0.0) + (it.get('faturamento') or 0.0)
        return {'Vendedor': max(acc, key=acc.get) if acc else '(não identificado)'}
    return cruzamento(itens, lambda it: it.get('produto'), lambda it: it.get('cliente_nome'),
                       'Produto', 'Cliente', extra_fn=_extra)


# ---------------------------------------------------------------------------
# Matrizes pivotadas Produto x Vendedor / Produto x Cliente
# ---------------------------------------------------------------------------

def matriz_pivot(itens, metrica='faturamento', linha_fn=None, coluna_fn=None,
                  top_linhas=None, top_colunas=None):
    """Pivot genérico: linhas = produto (padrão), colunas = vendedor
    (padrão). metrica: 'faturamento' | 'volume'. top_linhas/top_colunas
    limita a quantidade (maiores primeiro), pra evitar tabela ilegível
    quando há muitos produtos/clientes (item 17 do briefing)."""
    linha_fn = linha_fn or (lambda it: it.get('produto'))
    coluna_fn = coluna_fn or (lambda it: it.get('vendedor') or it.get('vendedor_raw'))

    valores, linhas_tot, colunas_tot = {}, {}, {}
    for it in itens:
        l = linha_fn(it) or '(não identificado)'
        c = coluna_fn(it) or '(não identificado)'
        v = (it.get('qtd') if metrica == 'volume' else it.get('faturamento')) or 0.0
        valores[(l, c)] = valores.get((l, c), 0.0) + v
        linhas_tot[l] = linhas_tot.get(l, 0.0) + v
        colunas_tot[c] = colunas_tot.get(c, 0.0) + v

    linhas_ordenadas = sorted(linhas_tot, key=linhas_tot.get, reverse=True)
    colunas_ordenadas = sorted(colunas_tot, key=colunas_tot.get, reverse=True)
    if top_linhas:
        linhas_ordenadas = linhas_ordenadas[:top_linhas]
    if top_colunas:
        colunas_ordenadas = colunas_ordenadas[:top_colunas]

    return {
        'linhas': linhas_ordenadas, 'colunas': colunas_ordenadas, 'valores': valores,
        'linhas_tot': linhas_tot, 'colunas_tot': colunas_tot, 'metrica': metrica,
    }


# ---------------------------------------------------------------------------
# Destaques gerenciais
# ---------------------------------------------------------------------------

def destaques(itens_atual, itens_anterior=None):
    """Só usa dados reais do recorte -- nenhum valor inventado. Retorna {}
    se não houver produtos no recorte."""
    ranking = ranking_com_crescimento(itens_atual, itens_anterior, indicador='faturamento')
    if not ranking:
        return {}
    mais_vendido = max(ranking, key=lambda l: l['volume'])
    maior_faturamento = max(ranking, key=lambda l: l['faturamento'])
    maior_margem = max(ranking, key=lambda l: l['margem_rs'])
    maior_participacao = max(ranking, key=lambda l: l['participacao_faturamento'])
    com_variacao = [l for l in ranking if l.get('crescimento_pct') is not None]
    crescimentos = [l for l in com_variacao if l['crescimento_pct'] > 0]
    quedas = [l for l in com_variacao if l['crescimento_pct'] < 0]
    maior_crescimento = max(crescimentos, key=lambda l: l['crescimento_pct']) if crescimentos else None
    maior_queda = min(quedas, key=lambda l: l['crescimento_pct']) if quedas else None
    cats = por_categoria(itens_atual)
    categoria_lider = max(cats, key=lambda c: c['faturamento']) if cats else None
    return {
        'mais_vendido': mais_vendido, 'maior_faturamento': maior_faturamento,
        'maior_margem': maior_margem, 'maior_participacao': maior_participacao,
        'maior_crescimento': maior_crescimento, 'maior_queda': maior_queda,
        'categoria_lider': categoria_lider,
    }


# ---------------------------------------------------------------------------
# Alertas (pontos de atenção)
# ---------------------------------------------------------------------------

def alertas_produtos(itens_atual, itens_anterior=None,
                      limiar_queda_pct=LIMIAR_QUEDA_PCT_PADRAO,
                      limiar_concentracao_pct=LIMIAR_CONCENTRACAO_PCT_PADRAO,
                      limiar_volume_alto_pct=LIMIAR_VOLUME_ALTO_FAT_BAIXO_PADRAO):
    """Limiares são parâmetros ajustáveis (ver docstring do módulo) --
    nenhum deles é uma regra de negócio fixa já validada."""
    alertas = []
    ranking = ranking_com_crescimento(itens_atual, itens_anterior, indicador='faturamento')
    if not ranking:
        return alertas

    for l in ranking:
        if l.get('crescimento_pct') is not None and l['crescimento_pct'] <= -limiar_queda_pct:
            alertas.append({
                'tipo': 'Queda significativa', 'produto': l['chave'],
                'detalhe': f"{l['chave']} caiu {abs(l['crescimento_pct']):.2f}% em faturamento "
                           f"vs período anterior.",
                'severidade': 'atencao',
            })

    for p in produtos_sem_venda_no_periodo(itens_atual, itens_anterior):
        alertas.append({
            'tipo': 'Deixou de vender', 'produto': p['chave'],
            'detalhe': f"{p['chave']} teve {_fmt_moeda(p['faturamento'])} de faturamento no período anterior "
                       f"e nenhuma venda no período atual.",
            'severidade': 'critico',
        })

    top3 = sorted(ranking, key=lambda l: -l['faturamento'])[:3]
    conc = sum(l['participacao_faturamento'] for l in top3)
    if conc >= limiar_concentracao_pct:
        nomes = ', '.join(l['chave'] for l in top3)
        alertas.append({
            'tipo': 'Concentração excessiva', 'produto': nomes,
            'detalhe': f"Os 3 principais produtos ({nomes}) concentram {conc:.2f}% do faturamento do período.",
            'severidade': 'atencao',
        })

    total_vol = sum(l['volume'] for l in ranking) or 0.0
    for l in ranking:
        part_vol = (l['volume'] / total_vol * 100) if total_vol else 0.0
        if part_vol >= limiar_volume_alto_pct and l['participacao_faturamento'] < part_vol / 2:
            alertas.append({
                'tipo': 'Volume alto, faturamento proporcionalmente baixo', 'produto': l['chave'],
                'detalhe': f"{l['chave']} representa {part_vol:.2f}% do volume vendido, mas apenas "
                           f"{l['participacao_faturamento']:.2f}% do faturamento.",
                'severidade': 'atencao',
            })

    ordem_sev = {'critico': 0, 'atencao': 1}
    alertas.sort(key=lambda a: ordem_sev.get(a['severidade'], 2))
    return alertas


# ---------------------------------------------------------------------------
# Produtos Mais Trabalhados (Entrega 4 do Projeto 2)
# ---------------------------------------------------------------------------
#
# "Mais trabalhado" aqui é sobre PRESENÇA COMERCIAL -- não é o mesmo que
# "maior faturamento" (Entrega 1) nem "maior margem" (Entrega 2). Usa só
# campos que existem de fato na base:
#   - nº de clientes distintos que compraram o produto (cliente_codigo)
#   - nº de vendedores distintos que trabalharam o produto (vendedor)
#   - frequência = nº de datas distintas (_data_ref) em que o produto teve
#     venda no recorte -- aproxima em quantos dias/relatórios diferentes o
#     produto apareceu (não existe um campo de "nº de pedidos" na base)
#   - volume (cx) e faturamento, já calculados em outras entregas
#
# Não existe uma fórmula de negócio validada pra combinar essas dimensões
# num único número (o próprio briefing pede pra não inventar uma métrica
# arbitrária). O "índice de presença comercial" abaixo é só uma forma
# transparente e ajustável de ordenar quando a usuária não escolhe um
# critério único: cada dimensão comercial (clientes, vendedores,
# frequência) é normalizada pelo maior valor do recorte (0 a 1) e a média
# das três vira um índice de 0 a 100. A tela sempre permite ordenar por
# qualquer uma das dimensões brutas também, sem passar pelo índice.

def produtos_mais_trabalhados(itens):
    """Uma linha por produto com: chave, categoria (grupo), faturamento,
    custo, margem_rs, margem_pct, volume, participacao_faturamento (via
    agregar_por), + n_clientes, n_vendedores, frequencia, indice_presenca
    (0-100). Produtos sem nenhuma data resolvida (_data_ref ausente em
    todos os itens) entram com frequencia=0 -- não é descartado, só fica
    marcado com o dado que falta."""
    grupos = {}
    for it in itens:
        p = it.get('produto') or '(não identificado)'
        grupos.setdefault(p, []).append(it)

    base_agregada = {l['chave']: l for l in por_produto(itens)}

    brutos = []
    for p, sub in grupos.items():
        n_clientes = len({it.get('cliente_codigo') for it in sub if it.get('cliente_codigo')})
        n_vendedores = len({(it.get('vendedor') or it.get('vendedor_raw'))
                             for it in sub if (it.get('vendedor') or it.get('vendedor_raw'))})
        datas = {it.get('_data_ref') for it in sub if it.get('_data_ref')}
        frequencia = len(datas)
        ag = base_agregada.get(p, {})
        brutos.append({
            **ag, 'chave': p,
            'n_clientes': n_clientes, 'n_vendedores': n_vendedores, 'frequencia': frequencia,
        })

    max_clientes = max((l['n_clientes'] for l in brutos), default=0) or 1
    max_vendedores = max((l['n_vendedores'] for l in brutos), default=0) or 1
    max_frequencia = max((l['frequencia'] for l in brutos), default=0) or 1

    for l in brutos:
        indice = (
            (l['n_clientes'] / max_clientes) +
            (l['n_vendedores'] / max_vendedores) +
            (l['frequencia'] / max_frequencia)
        ) / 3 * 100
        l['indice_presenca'] = round(indice, 2)

    return sorted(brutos, key=lambda l: l['indice_presenca'], reverse=True)
