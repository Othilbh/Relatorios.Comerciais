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
import rentabilidade as rt

# Reexporta o necessário da base -- quem usa produtos.py não precisa
# importar rentabilidade.py também para as operações comuns.
carregar_base_consolidada = rt.carregar_base_consolidada
periodos_disponiveis = rt.periodos_disponiveis
filtrar_periodo = rt.filtrar_periodo
filtrar_dimensoes = rt.filtrar_dimensoes
opcoes_dimensoes = rt.opcoes_dimensoes
agregar = rt.agregar
por_produto = rt.por_produto
por_vendedor = rt.por_vendedor
por_cliente = rt.por_cliente
por_categoria = rt.por_categoria
evolucao = rt.evolucao

UNIDADE_PADRAO = 'cx'

# Limiares padrão dos alertas (ajustáveis na tela -- não há regra de
# negócio fixa definida hoje para nenhum destes critérios).
LIMIAR_QUEDA_PCT_PADRAO = 20.0                  # queda de X% no indicador = alerta
LIMIAR_CONCENTRACAO_PCT_PADRAO = 50.0           # top 3 produtos concentrando >= X% do faturamento
LIMIAR_VOLUME_ALTO_FAT_BAIXO_PADRAO = 10.0      # % mínima de participação em volume p/ avaliar desproporção


# ---------------------------------------------------------------------------
# KPIs específicos de produto
# ---------------------------------------------------------------------------

def kpis_produto(itens):
    """KPIs do módulo: agregados gerais (agregar()) + SKUs distintos
    vendidos (contagem de produtos diferentes, NÃO confundir com volume em
    caixas) + ticket médio por produto (Faturamento / nº de SKUs) +
    produto líder (maior faturamento no recorte)."""
    base = rt.agregar(itens)
    skus = len({it.get('produto') for it in itens if it.get('produto')})
    ticket_medio_produto = (base['faturamento'] / skus) if skus else 0.0
    prods = por_produto(itens)
    lider = max(prods, key=lambda p: p['faturamento']) if prods else None
    return {
        **base,
        'skus': skus,
        'unidade': UNIDADE_PADRAO,
        'ticket_medio_produto': round(ticket_medio_produto, 2),
        'produto_lider': lider['chave'] if lider else None,
        'produto_lider_faturamento': lider['faturamento'] if lider else 0.0,
    }


# ---------------------------------------------------------------------------
# Ranking com crescimento/queda vs período anterior
# ---------------------------------------------------------------------------

def ranking_com_crescimento(itens_atual, itens_anterior=None, indicador='faturamento'):
    """por_produto(atual), acrescido de comparação com por_produto(anterior)
    pela chave (nome do produto). indicador: 'faturamento' | 'volume' |
    'margem_rs'. Produtos sem contrapartida no período anterior entram com
    crescimento_pct=None e status_crescimento='novo' (não é tratado como
    queda nem inventa um valor)."""
    atual = por_produto(itens_atual)
    anterior_map = {p['chave']: p for p in por_produto(itens_anterior)} if itens_anterior else {}
    linhas = []
    for p in atual:
        ant = anterior_map.get(p['chave'])
        if ant is None:
            linhas.append({**p, 'valor_anterior': None, 'diferenca': None,
                           'crescimento_pct': None, 'status_crescimento': 'novo'})
            continue
        val_atual = p.get(indicador, 0.0)
        val_ant = ant.get(indicador, 0.0)
        diff = val_atual - val_ant
        if val_ant:
            cresc = diff / val_ant * 100
        else:
            cresc = 100.0 if val_atual > 0 else 0.0
        status = 'crescimento' if diff > 1e-9 else ('queda' if diff < -1e-9 else 'estavel')
        linhas.append({**p, 'valor_anterior': round(val_ant, 2), 'diferenca': round(diff, 2),
                       'crescimento_pct': round(cresc, 2), 'status_crescimento': status})
    return linhas


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
        'maior_participacao': maior_participacao,
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
            'detalhe': f"{p['chave']} teve {p['faturamento']:,.2f} de faturamento no período anterior "
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
