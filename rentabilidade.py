"""Componente central de RENTABILIDADE E MARGENS — Projeto 3.

Consolida o histórico de itens vendidos (módulo 'relatorio_diario', que já
alimenta o Relatório Diário/Semanal/Mensal) numa base única de fatos, sem
duplicar faturamento entre os três tipos de upload -- Diário, Semanal e
Mensal são relatórios INDEPENDENTES (não um derivado do outro): a Ingrid
normalmente sobe o Diário todo dia útil, mas em alguns períodos sobe só o
Semanal ou o Mensal para cobrir um intervalo sem upload diário.

Regra de prioridade por dia calendário (a mais granular sempre vence, e um
período mais amplo só entra se NENHUM dos dias que ele cobre já tiver
dado mais granular -- isso evita contar a mesma venda duas vezes):

    1) Diário   -- 1 upload = 1 dia. Sempre incluído.
    2) Semanal  -- incluído só se nenhum dos 7 dias da semana já estiver
                   coberto por um Diário.
    3) Mensal   -- incluído só se nenhum dia do mês já estiver coberto por
                   Diário ou por um Semanal já incluído.

Um Semanal/Mensal ignorado por sobreposição parcial não é descartado
silenciosamente: fica registrado na lista de avisos retornada por
`carregar_base_consolidada()`, para a tela poder avisar a usuária.

Definições usadas neste módulo (podem ser diferentes das de outros
dashboards do app, que calculam margem sobre o CUSTO -- aqui a margem é
sobre o FATURAMENTO, que é a definição pedida para este módulo):

    Margem R$   = Faturamento - Custo
    Margem %    = (Margem R$ / Faturamento) x 100   (0,0 se Faturamento==0)
    Ticket Médio = Faturamento / nº de clientes distintos no recorte

Nunca gera NaN/Infinity: toda divisão é protegida contra denominador zero.
"""
import datetime as _dt
import re as _re

import streamlit as st

import data_store as ds
import periodo as periodo_mod
from categorias import map_categoria

MOD_RELATORIO_DIARIO = 'relatorio_diario'
MOD_RENTABILIDADE = 'rentabilidade'


def _fmt_moeda(v):
    s = f"{abs(v):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"R$ {'-' if v < 0 else ''}{s}"


def _fmt_num(v, casas=2):
    s = f"{abs(v):,.{casas}f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"{'-' if v < 0 else ''}{s}"

# Limiares padrão dos alertas gerenciais (secção 16 do briefing: não são
# regra de negócio fixa -- são parâmetros ajustáveis, com um valor inicial
# razoável, já que nenhuma regra de "margem mínima sobre faturamento"
# existe hoje em nenhum outro módulo do app).
LIMIAR_MARGEM_ATENCAO_PADRAO = 10.0   # margem % abaixo disso = ponto de atenção
LIMIAR_MARGEM_CRITICO_PADRAO = 0.0    # margem % abaixo disso = crítico
LIMIAR_QUEDA_PP_PADRAO = 5.0          # queda de X p.p. entre períodos = alerta


# ---------------------------------------------------------------------------
# Consolidação da base histórica
# ---------------------------------------------------------------------------

def _parse_data_br(s):
    """'13/08/2026' -> date(2026,8,13). None se não achar uma data válida."""
    if not s:
        return None
    m = _re.search(r'(\d{2})/(\d{2})/(\d{4})', s)
    if not m:
        return None
    try:
        d, mth, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _dt.date(a, mth, d)
    except Exception:
        return None


def _intervalo_registro(tipo, valores):
    """(data_inicio, data_fim) cobertos por um registro salvo. Para
    'diario', inicio == fim. Tenta 'emissao' primeiro e cai para 'periodo'
    quando necessário (ambos os campos usam formato brasileiro DD/MM/AAAA,
    o 'periodo' às vezes vem como intervalo "DD/MM/AAAA a DD/MM/AAAA")."""
    periodo_txt = valores.get('periodo') or ''
    if tipo == 'diario':
        d = _parse_data_br(valores.get('emissao')) or _parse_data_br(periodo_txt)
        return (d, d) if d else (None, None)
    datas = _re.findall(r'\d{2}/\d{2}/\d{4}', periodo_txt)
    if len(datas) >= 2:
        return _parse_data_br(datas[0]), _parse_data_br(datas[-1])
    if len(datas) == 1:
        d = _parse_data_br(datas[0])
        return d, d
    d = _parse_data_br(valores.get('emissao'))
    return (d, d) if d else (None, None)


def _todos_dias(inicio, fim):
    dias = set()
    d = inicio
    while d <= fim:
        dias.add(d)
        d += _dt.timedelta(days=1)
    return dias


@st.cache_data(ttl=60, show_spinner=False)
def _carregar_registros_cache():
    """Lê todos os registros salvos em relatorio_diario (diario/semanal/
    mensal), já com o intervalo de datas resolvido. Cache curto (60s) --
    a página de Rentabilidade chama isso a cada interação de filtro."""
    out = {'diario': [], 'semanal': [], 'mensal': []}
    for tipo in ('diario', 'semanal', 'mensal'):
        for slug in ds.list_periodos(MOD_RELATORIO_DIARIO, tipo):
            reg = ds.load_current(MOD_RELATORIO_DIARIO, tipo, slug)
            if not reg:
                continue
            valores = reg.get('valores', {}) or {}
            itens = valores.get('itens') or []
            if not itens:
                continue
            inicio, fim = _intervalo_registro(tipo, valores)
            if not inicio or not fim:
                continue
            out[tipo].append({
                'slug': slug, 'periodo_txt': valores.get('periodo'),
                'itens': itens, 'inicio': inicio, 'fim': fim,
            })
    return out


def carregar_base_consolidada():
    """Monta a lista consolidada de itens (fato único p/ Rentabilidade),
    aplicando a prioridade Diário > Semanal > Mensal.

    Retorna (itens_consolidados, avisos):
      itens_consolidados -- cada item é uma cópia do item original + 3
        campos: '_data_ref' (data representativa, p/ localizar em
        qualquer período), '_origem_tipo', '_origem_slug'.
      avisos -- lista de strings sobre registros Semanal/Mensal ignorados
        por sobreposição com dado mais granular (transparência total, sem
        descarte silencioso -- item 28 do briefing)."""
    registros = _carregar_registros_cache()
    avisos = []
    dias_cobertos = set()
    consolidado = []

    for r in registros['diario']:
        for it in r['itens']:
            novo = dict(it)
            novo['_data_ref'] = r['inicio']
            novo['_origem_tipo'] = 'diario'
            novo['_origem_slug'] = r['slug']
            consolidado.append(novo)
        dias_cobertos.add(r['inicio'])

    for r in sorted(registros['semanal'], key=lambda x: x['inicio']):
        dias = _todos_dias(r['inicio'], r['fim'])
        if dias & dias_cobertos:
            avisos.append(
                f"Semanal '{r['slug']}' ({r['inicio']:%d/%m/%Y} a {r['fim']:%d/%m/%Y}) "
                f"não entrou no histórico consolidado -- já existe dado Diário no mesmo período."
            )
            continue
        for it in r['itens']:
            novo = dict(it)
            novo['_data_ref'] = r['inicio']
            novo['_origem_tipo'] = 'semanal'
            novo['_origem_slug'] = r['slug']
            consolidado.append(novo)
        dias_cobertos |= dias

    for r in sorted(registros['mensal'], key=lambda x: x['inicio']):
        dias = _todos_dias(r['inicio'], r['fim'])
        if dias & dias_cobertos:
            avisos.append(
                f"Mensal '{r['slug']}' ({r['inicio']:%d/%m/%Y} a {r['fim']:%d/%m/%Y}) "
                f"não entrou no histórico consolidado -- já existe dado Diário/Semanal no mesmo período."
            )
            continue
        for it in r['itens']:
            novo = dict(it)
            novo['_data_ref'] = r['inicio']
            novo['_origem_tipo'] = 'mensal'
            novo['_origem_slug'] = r['slug']
            consolidado.append(novo)
        dias_cobertos |= dias

    return consolidado, avisos


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------

def periodos_disponiveis(itens, tipo_periodo):
    """periodo_ref distintos (mais recente primeiro) presentes na base,
    para o tipo de período escolhido -- usado para popular o seletor de
    período sem oferecer períodos sem nenhum dado."""
    refs = {periodo_mod.periodo_ref(tipo_periodo, it['_data_ref'])
            for it in itens if it.get('_data_ref')}
    return sorted(refs, reverse=True)


def filtrar_periodo(itens, tipo_periodo, periodo_ref):
    if not periodo_ref:
        return []
    inicio, fim = periodo_mod.intervalo_datas(tipo_periodo, periodo_ref)
    return [it for it in itens if it.get('_data_ref') and inicio <= it['_data_ref'] <= fim]


def filtrar_dimensoes(itens, vendedores=None, clientes=None, produtos=None, categorias=None):
    out = itens
    if vendedores:
        vs = set(vendedores)
        out = [it for it in out if (it.get('vendedor') or it.get('vendedor_raw') or '(não identificado)') in vs]
    if clientes:
        cs = set(clientes)
        out = [it for it in out if (it.get('cliente_nome') or '(não identificado)') in cs]
    if produtos:
        ps = set(produtos)
        out = [it for it in out if (it.get('produto') or '(não identificado)') in ps]
    if categorias:
        cats = set(categorias)
        out = [it for it in out if map_categoria(it.get('produto', '')) in cats]
    return out


def opcoes_dimensoes(itens):
    """Listas (ordenadas) de vendedores/clientes/produtos/categorias
    presentes na base, p/ popular os multiselects de filtro."""
    vendedores = sorted({(it.get('vendedor') or it.get('vendedor_raw') or '(não identificado)') for it in itens})
    clientes = sorted({(it.get('cliente_nome') or '(não identificado)') for it in itens})
    produtos = sorted({(it.get('produto') or '(não identificado)') for it in itens})
    categorias = sorted({map_categoria(it.get('produto', '')) for it in itens})
    return vendedores, clientes, produtos, categorias


# ---------------------------------------------------------------------------
# Cálculos
# ---------------------------------------------------------------------------

def agregar(itens):
    """KPIs agregados do recorte: faturamento, custo, margem R$, margem %,
    volume, nº de clientes distintos, ticket médio. Protegido contra
    divisão por zero -- nunca retorna NaN/Infinity."""
    fat = sum(it.get('faturamento') or 0.0 for it in itens)
    custo = sum(it.get('custo_total') or 0.0 for it in itens)
    margem_rs = fat - custo
    margem_pct = (margem_rs / fat * 100) if fat else 0.0
    volume = sum(it.get('qtd') or 0.0 for it in itens)
    clientes = len({it.get('cliente_codigo') for it in itens if it.get('cliente_codigo')})
    ticket_medio = (fat / clientes) if clientes else 0.0
    return {
        'faturamento': round(fat, 2), 'custo': round(custo, 2),
        'margem_rs': round(margem_rs, 2), 'margem_pct': round(margem_pct, 2),
        'volume': round(volume, 3), 'clientes': clientes,
        'ticket_medio': round(ticket_medio, 2),
    }


def agregar_por(itens, chave_fn, rotulo_extra_fn=None):
    """Agrupa por chave_fn(item) e agrega cada grupo (agregar()) + a
    participação de cada grupo no faturamento/margem total do conjunto."""
    grupos = {}
    for it in itens:
        k = chave_fn(it) or '(não identificado)'
        grupos.setdefault(k, []).append(it)
    total = agregar(itens)
    linhas = []
    for k, sub in grupos.items():
        ag = agregar(sub)
        part_fat = (ag['faturamento'] / total['faturamento'] * 100) if total['faturamento'] else 0.0
        part_mrg = (ag['margem_rs'] / total['margem_rs'] * 100) if total['margem_rs'] else 0.0
        linha = {'chave': k, **ag,
                  'participacao_faturamento': round(part_fat, 2),
                  'participacao_margem': round(part_mrg, 2)}
        if rotulo_extra_fn:
            linha.update(rotulo_extra_fn(sub))
        linhas.append(linha)
    return linhas


def por_vendedor(itens):
    return agregar_por(itens, lambda it: it.get('vendedor') or it.get('vendedor_raw'))


def por_cliente(itens):
    def extra(sub):
        acc = {}
        for it in sub:
            v = it.get('vendedor') or it.get('vendedor_raw') or '(não identificado)'
            acc[v] = acc.get(v, 0.0) + (it.get('faturamento') or 0.0)
        resp = max(acc, key=acc.get) if acc else '(não identificado)'
        return {'vendedor_responsavel': resp}
    return agregar_por(itens, lambda it: it.get('cliente_nome'), extra)


def por_produto(itens):
    def extra(sub):
        return {'categoria': map_categoria(sub[0].get('produto', '')) if sub else '(sem categoria)'}
    return agregar_por(itens, lambda it: it.get('produto'), extra)


def por_categoria(itens):
    return agregar_por(itens, lambda it: map_categoria(it.get('produto', '')))


# ---------------------------------------------------------------------------
# Matriz Faturamento x Margem
# ---------------------------------------------------------------------------

def _mediana(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return 0.0
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def matriz_quadrantes(linhas, corte_fat=None, corte_margem_pct=None):
    """Classifica cada linha (de agregar_por) num dos 4 quadrantes
    gerenciais, usando a MEDIANA de faturamento e de margem % do próprio
    conjunto como corte (salvo se limiares explícitos forem passados)."""
    if not linhas:
        return [], 0.0, 0.0
    corte_fat = corte_fat if corte_fat is not None else _mediana([l['faturamento'] for l in linhas])
    corte_mrg = corte_margem_pct if corte_margem_pct is not None else _mediana([l['margem_pct'] for l in linhas])
    out = []
    for l in linhas:
        alto_fat = l['faturamento'] >= corte_fat
        alta_mrg = l['margem_pct'] >= corte_mrg
        if alto_fat and alta_mrg:
            quad = 'Estratégico (alto faturamento + alta margem)'
        elif alto_fat and not alta_mrg:
            quad = 'Atenção (alto faturamento + baixa margem)'
        elif not alto_fat and alta_mrg:
            quad = 'Oportunidade (baixo faturamento + alta margem)'
        else:
            quad = 'Avaliar (baixo faturamento + baixa margem)'
        out.append({**l, 'quadrante': quad})
    return out, corte_fat, corte_mrg


# ---------------------------------------------------------------------------
# Evolução temporal
# ---------------------------------------------------------------------------

def evolucao(itens, granularidade='dia'):
    """Série temporal de faturamento/custo/margem, agrupada por dia, semana
    ISO ou mês (conforme `granularidade`). Retorna lista ordenada por data
    de dicts {'rotulo', 'data_ord', 'faturamento', 'custo', 'margem_rs',
    'margem_pct'}."""
    grupos = {}
    for it in itens:
        d = it.get('_data_ref')
        if not d:
            continue
        if granularidade == 'semana':
            chave = periodo_mod.periodo_ref('semanal', d)
            data_ord = periodo_mod.intervalo_datas('semanal', chave)[0]
        elif granularidade == 'mes':
            chave = periodo_mod.periodo_ref('mensal', d)
            data_ord = periodo_mod.intervalo_datas('mensal', chave)[0]
        else:
            chave = d.strftime('%d/%m/%Y')
            data_ord = d
        grupos.setdefault(chave, {'data_ord': data_ord, 'itens': []})['itens'].append(it)

    out = []
    for chave, g in sorted(grupos.items(), key=lambda kv: kv[1]['data_ord']):
        ag = agregar(g['itens'])
        out.append({'rotulo': chave, 'data_ord': g['data_ord'], **ag})
    return out


# ---------------------------------------------------------------------------
# Alertas gerenciais
# ---------------------------------------------------------------------------

def alertas_gerenciais(itens_atual, itens_anterior=None,
                        limiar_atencao=LIMIAR_MARGEM_ATENCAO_PADRAO,
                        limiar_critico=LIMIAR_MARGEM_CRITICO_PADRAO,
                        limiar_queda_pp=LIMIAR_QUEDA_PP_PADRAO):
    """Gera pontos de atenção automáticos. Limiares são parâmetros
    ajustáveis (não há regra de negócio fixa definida para este módulo
    ainda) -- ver docstring do módulo."""
    alertas = []
    if not itens_atual:
        return alertas

    total = agregar(itens_atual)
    if total['margem_pct'] < limiar_critico:
        alertas.append({
            'tipo': 'Margem geral crítica',
            'detalhe': f"Margem % geral do período está em {total['margem_pct']:.2f}%, "
                       f"abaixo do limiar crítico ({limiar_critico:.2f}%).",
            'severidade': 'critico',
        })
    elif total['margem_pct'] < limiar_atencao:
        alertas.append({
            'tipo': 'Margem geral em atenção',
            'detalhe': f"Margem % geral do período está em {total['margem_pct']:.2f}%, "
                       f"abaixo do limiar de atenção ({limiar_atencao:.2f}%).",
            'severidade': 'atencao',
        })

    clientes = por_cliente(itens_atual)
    corte_fat_cli = _mediana([c['faturamento'] for c in clientes]) if clientes else 0.0
    for c in clientes:
        if c['faturamento'] >= corte_fat_cli and c['margem_pct'] < limiar_atencao and c['faturamento'] > 0:
            alertas.append({
                'tipo': 'Cliente: alto faturamento + baixa margem',
                'detalhe': f"{c['chave']} — faturamento {_fmt_moeda(c['faturamento'])}, margem {c['margem_pct']:.2f}%.",
                'severidade': 'critico' if c['margem_pct'] < limiar_critico else 'atencao',
            })

    produtos = por_produto(itens_atual)
    corte_vol_prod = _mediana([p['volume'] for p in produtos]) if produtos else 0.0
    for p in produtos:
        if p['volume'] >= corte_vol_prod and p['margem_pct'] < limiar_atencao and p['volume'] > 0:
            alertas.append({
                'tipo': 'Produto: alto volume + baixa margem',
                'detalhe': f"{p['chave']} — volume {_fmt_num(p['volume'], 3)}, margem {p['margem_pct']:.2f}%.",
                'severidade': 'critico' if p['margem_pct'] < limiar_critico else 'atencao',
            })

    if itens_anterior:
        vend_atual = {v['chave']: v for v in por_vendedor(itens_atual)}
        vend_anterior = {v['chave']: v for v in por_vendedor(itens_anterior)}
        for chave, v in vend_atual.items():
            v_ant = vend_anterior.get(chave)
            if v_ant is None:
                continue
            queda = v_ant['margem_pct'] - v['margem_pct']
            if queda >= limiar_queda_pp:
                alertas.append({
                    'tipo': 'Vendedor: queda de margem',
                    'detalhe': f"{chave} — margem caiu {queda:.2f} p.p. "
                               f"({v_ant['margem_pct']:.2f}% -> {v['margem_pct']:.2f}%) vs período anterior.",
                    'severidade': 'atencao',
                })
        queda_geral = None
        total_ant = agregar(itens_anterior)
        if total_ant['faturamento'] or total['faturamento']:
            queda_geral = total_ant['margem_pct'] - total['margem_pct']
        if queda_geral is not None and queda_geral >= limiar_queda_pp:
            alertas.append({
                'tipo': 'Queda relevante de margem entre períodos',
                'detalhe': f"Margem geral caiu {queda_geral:.2f} p.p. "
                           f"({total_ant['margem_pct']:.2f}% -> {total['margem_pct']:.2f}%) vs período anterior.",
                'severidade': 'atencao',
            })

    ordem_sev = {'critico': 0, 'atencao': 1}
    alertas.sort(key=lambda a: ordem_sev.get(a['severidade'], 2))
    return alertas
