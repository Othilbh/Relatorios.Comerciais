"""Gera o dashboard HTML "Margem Real" -- mesma estrutura visual do
Dashboard Gerencial (dashboard_diario.py), mas com uma margem calculada
diferente, pedido explícito da Ingrid (24/08/2026):

  Custo real  = Custo do relatório ÷ (1 + % administrativo do produto / 100)
                (retira do Custo a despesa administrativa que já vem
                embutida nele, variável por produto -- ver margem_produto.py)
  MC R$ real  = Faturamento - Custo real
  MC % real   = MC R$ real / Custo real x 100

Diferente do Resultado Real % usado no resto do app, aqui NÃO se soma o
+15pp operacional -- a Ingrid confirmou que é outra coisa, sem relação
("é como se fosse uma despesa fixa, operacional" -- não tem nada a ver com
a despesa administrativa variável por produto que já está embutida no
Custo do relatório).

Reutiliza os MESMOS itens já salvos no histórico do Relatório Diário /
Semanal / Mensal (modulo 'relatorio_diario' em data_store.py) -- não
precisa de nenhum passo novo de "publicar"; a navegação por dia/semana/mês
em pages/gerencia.py é a mesma já usada pro Dashboard Gerencial.

O % de cada produto é sempre o MAIS ATUAL do cadastro (margem_produto.py)
no momento em que a tela é aberta, mesmo pra dias antigos -- decisão
explícita da Ingrid, pra não ter que se preocupar com % "congelado".
Produto sem % cadastrado usa margem_produto.PADRAO_PCT e fica listado à
parte, claramente sinalizado (nunca escondido dentro da média geral sem
aviso).
"""
import json
import os
from categorias import map_categoria
import margem_produto as mp

_CHARTJS_PATH = os.path.join(os.path.dirname(__file__), 'chart_umd.js')
with open(_CHARTJS_PATH, encoding='utf-8') as _f:
    _CHARTJS_SRC = _f.read()

VERDE_BG,    VERDE_FG    = '#D8EFE3', '#1B4332'
AMARELO_BG,  AMARELO_FG  = '#FEF9C3', '#7D6608'
VERMELHO_BG, VERMELHO_FG = '#FADADD', '#7A1F2B'
HEADER_BG,   HEADER_FG   = '#5A3E85', '#FFFFFF'  # roxo -- cor diferente do
                                                   # Dashboard Gerencial (verde),
                                                   # pra nunca confundir as duas
                                                   # telas visualmente.


def _custo_real_item(it: dict, tabela: dict):
    """(custo_real, pct_usado, encontrado) de UM item."""
    pct, encontrado = mp.pct_admin(it.get('produto'), tabela)
    custo_real = it['custo_total'] / (1 + pct / 100) if pct else it['custo_total']
    return custo_real, pct, encontrado


def _agg(itens, tabela):
    """Agrega uma lista de itens em (mc_rs_real, mc_pct_real) usando o
    custo REAL (após retirar a despesa administrativa por produto), sem
    nenhum acréscimo por cima (sem +15pp -- ver docstring do módulo)."""
    fat_total = sum(it['faturamento'] for it in itens)
    custo_real_total = sum(_custo_real_item(it, tabela)[0] for it in itens)

    mc_rs  = fat_total - custo_real_total
    mc_pct = mc_rs / custo_real_total * 100 if custo_real_total else 0.0
    return round(mc_rs, 2), round(mc_pct, 2)


def _status(mc_pct_real):
    if mc_pct_real >= 15: return 'OK',      VERDE_BG,    VERDE_FG
    if mc_pct_real >= 0:  return 'Atencao', AMARELO_BG,  AMARELO_FG
    return                       'Critico', VERMELHO_BG, VERMELHO_FG


def _produtos_sem_cadastro(itens, tabela):
    """Lista (produto, caixas, faturamento) dos produtos distintos que
    caíram no PADRAO_PCT por falta de % cadastrado -- pra Ingrid saber
    exatamente o que precisa adicionar em Cadastro de Marcas, e ter
    ciência de que o número desses itens está usando um % aproximado."""
    agg = {}
    for it in itens:
        _, _, encontrado = _custo_real_item(it, tabela)
        if encontrado:
            continue
        d = agg.setdefault(it['produto'], {'qtd': 0.0, 'faturamento': 0.0})
        d['qtd']         += it['qtd']
        d['faturamento'] += it['faturamento']
    return sorted(
        [{'produto': p, 'qtd': round(d['qtd'], 3), 'faturamento': round(d['faturamento'], 2)}
         for p, d in agg.items()],
        key=lambda x: -x['faturamento'],
    )


def _montar_dados(parsed, tabela):
    itens = parsed['itens']

    caixas_total = sum(it['qtd'] for it in itens)
    mc_rs_total, mc_pct_total = _agg(itens, tabela)
    clientes_distintos = len(set(it['cliente_codigo'] for it in itens))

    # ---- ranking de vendedores -----------------------------------------
    por_vendedor = {}
    for it in itens:
        vname = it['vendedor'] or it['vendedor_raw']
        d = por_vendedor.setdefault(vname, {'itens': [], 'clientes': set()})
        d['itens'].append(it)
        d['clientes'].add(it['cliente_codigo'])

    ranking = []
    for vname, d in por_vendedor.items():
        fat    = sum(it['faturamento'] for it in d['itens'])
        caixas = sum(it['qtd']         for it in d['itens'])
        mc_rs, mc_pct = _agg(d['itens'], tabela)
        status, bg, fg = _status(mc_pct)
        ranking.append({
            'vendedor': vname, 'clientes': len(d['clientes']),
            'caixas': round(caixas, 3), 'faturamento': round(fat, 2),
            'mc_rs': mc_rs, 'mc_pct_real': mc_pct,
            'status': status, 'bg': bg, 'fg': fg,
        })
    ranking.sort(key=lambda r: -r['faturamento'])
    vendedores_ativos = len(ranking)

    # ---- categorias ----------------------------------------------------
    por_categoria = {}
    for it in itens:
        cat = map_categoria(it['produto'])
        por_categoria.setdefault(cat, []).append(it)
    categorias_lista = []
    for cat, itens_cat in sorted(por_categoria.items(),
                                  key=lambda x: -sum(i['faturamento'] for i in x[1])):
        fat_cat = sum(i['faturamento'] for i in itens_cat)
        mc_rs_cat, mc_pct_cat = _agg(itens_cat, tabela)
        categorias_lista.append({
            'categoria': cat, 'faturamento': round(fat_cat, 2),
            'mc_rs': mc_rs_cat, 'mc_pct_real': mc_pct_cat,
        })

    # ---- clientes do dia (ranking completo) -----------------------------
    # 'todos_clientes' = TODOS os clientes com movimentação no dia
    # selecionado (pedido explícito da Ingrid, 26/08/2026: "exibir 100% dos
    # clientes do dia... se houver 50 clientes no dia, exibir os 50; se
    # houver 100, exibir os 100" -- usado na TABELA). 'top_clientes'
    # continua limitado aos 10 primeiros (por faturamento) -- usado só no
    # GRÁFICO de barras, que fica ilegível com dezenas de clientes; ela
    # confirmou "manter o top 10".
    por_cliente = {}
    for it in itens:
        cod = it['cliente_codigo']
        d = por_cliente.setdefault(cod, {'nome': it['cliente_nome'], 'itens': []})
        d['itens'].append(it)
    todos_clientes = []
    for cod, d in sorted(por_cliente.items(),
                          key=lambda x: -sum(i['faturamento'] for i in x[1]['itens'])):
        fat_cli = sum(i['faturamento'] for i in d['itens'])
        mc_rs_cli, mc_pct_cli = _agg(d['itens'], tabela)
        todos_clientes.append({
            'cliente': d['nome'], 'codigo': cod,
            'faturamento': round(fat_cli, 2),
            'mc_rs': mc_rs_cli, 'mc_pct_real': mc_pct_cli,
        })
    top_clientes = todos_clientes[:10]

    # ---- alertas: MC % real < 0 (vendendo abaixo do custo real) --------
    alertas = []
    itens_alertas_idx = set()
    for idx, it in enumerate(itens):
        mc_rs_it, mc_pct_it = _agg([it], tabela)
        if mc_pct_it < 0:
            itens_alertas_idx.add(idx)
            custo_real_it, pct_usado, encontrado = _custo_real_item(it, tabela)
            qtd = it['qtd']
            venda_unit = it['faturamento'] / qtd if qtd else 0.0
            custo_real_unit = custo_real_it / qtd if qtd else 0.0
            status, bg, fg = _status(mc_pct_it)
            alertas.append({
                'vendedor':        it['vendedor'] or it['vendedor_raw'],
                'cliente':         it['cliente_nome'],
                'produto':         it['produto'],
                'qtd':             round(qtd, 3),
                'custo_real_unit': round(custo_real_unit, 2),
                'venda_unit':      round(venda_unit, 2),
                'mc_rs':           round(mc_rs_it, 2),
                'mc_pct_real':     round(mc_pct_it, 2),
                'pct_usado':       pct_usado,
                'sem_cadastro':    not encontrado,
                'status': status, 'bg': bg, 'fg': fg,
            })
    alertas.sort(key=lambda a: a['mc_pct_real'])

    # ---- impacto ---------------------------------------------------------
    itens_com_alerta = [itens[i] for i in itens_alertas_idx]
    itens_sem_alerta = [itens[i] for i in range(len(itens)) if i not in itens_alertas_idx]
    fat_total       = sum(it['faturamento'] for it in itens)
    alertas_fat     = sum(it['faturamento'] for it in itens_com_alerta)
    alertas_mc_rs   = sum(_agg([it], tabela)[0] for it in itens_com_alerta)
    alertas_caixas  = sum(it['qtd'] for it in itens_com_alerta)
    pct_fat_alertas = alertas_fat / fat_total * 100 if fat_total else 0.0
    _mc_rs_sem, mc_pct_sem = _agg(itens_sem_alerta, tabela)
    impacto_pp = mc_pct_sem - mc_pct_total

    impacto = {
        'fat_alertas':      round(alertas_fat, 2),
        'pct_fat_alertas':  round(pct_fat_alertas, 2),
        'mc_rs_alertas':    round(alertas_mc_rs, 2),
        'caixas_alertas':   round(alertas_caixas, 3),
        'mc_pct_total':     mc_pct_total,
        'mc_pct_sem_alertas': round(mc_pct_sem, 2),
        'impacto_pp':       round(impacto_pp, 2),
        'n_alertas':        len(alertas),
    }

    return {
        'data_emissao': parsed.get('data_emissao'),
        'periodo':      parsed.get('periodo'),
        'kpis': {
            'faturamento':       round(fat_total, 2),
            'mc_rs':             mc_rs_total,
            'mc_pct_real':       mc_pct_total,
            'caixas':            round(caixas_total, 3),
            'clientes':          clientes_distintos,
            'vendedores_ativos': vendedores_ativos,
        },
        'ranking':           ranking,
        'categorias':        categorias_lista,
        'top_clientes':      top_clientes,
        'todos_clientes':    todos_clientes,
        'alertas':           alertas,
        'impacto':           impacto,
        'sem_cadastro':      _produtos_sem_cadastro(itens, tabela),
    }


_HTML_TEMPLATE = (
"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Dashboard Margem Real OTHIL -- __DATA_EMISSAO__</title>
<script>__CHARTJS_SRC__</script>
<style>
  :root {
    --verde-bg: __VERDE_BG__; --verde-fg: __VERDE_FG__;
    --amarelo-bg: __AMARELO_BG__; --amarelo-fg: __AMARELO_FG__;
    --vermelho-bg: __VERMELHO_BG__; --vermelho-fg: __VERMELHO_FG__;
    --header-bg: __HEADER_BG__; --header-fg: __HEADER_FG__;
  }
  * { box-sizing: border-box; }
  body { font-family: Arial, Helvetica, sans-serif; margin: 0; padding: 0;
    background: #F4F6F5; color: #1A1A1A; font-size: 13px; }
  header { background: var(--header-bg); color: var(--header-fg); padding: 16px 24px; }
  header h1 { margin: 0; font-size: 20px; }
  header p  { margin: 4px 0 0; font-size: 12px; opacity: 0.9; }
  main { padding: 20px 24px 40px; max-width: 1400px; margin: 0 auto; }
  .kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-bottom: 24px; }
  .kpi  { background: #fff; border-radius: 8px; padding: 12px 10px; text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  .kpi .label { font-size: 10px; color: #666; text-transform: uppercase; letter-spacing: .03em; }
  .kpi .value { font-size: 18px; font-weight: bold; color: var(--header-bg); margin-top: 4px; }
  section { background: #fff; border-radius: 8px; padding: 16px 18px; margin-bottom: 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  section h2 { margin: 0 0 12px; font-size: 15px; color: var(--header-bg); }
  .grid2 { display: grid; grid-template-columns: 1.4fr 1fr; gap: 16px; }
  .chart-wrap { position: relative; height: 300px; }
  .chart-wrap.small { height: 240px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { padding: 5px 8px; border-bottom: 1px solid #E5E5E5; text-align: left; }
  th { background: var(--header-bg); color: var(--header-fg); font-weight: bold;
       position: sticky; top: 0; white-space: nowrap; }
  th.sortable { cursor: pointer; user-select: none; }
  th.sortable:hover { opacity: 0.85; }
  th.sortable .arrow { display: inline-block; width: 10px; font-size: 9px; opacity: 0.85; }
  td { white-space: nowrap; }
  td.wrap { white-space: normal; max-width: 180px; }
  td.num, th.num { text-align: right; }
  tr:hover td { background: #FAFAFA; }
  .badge { display: inline-block; padding: 2px 7px; border-radius: 10px;
           font-weight: bold; font-size: 11px; white-space: nowrap; }
  .table-scroll { max-height: 420px; overflow-y: auto; border: 1px solid #EEE;
    border-radius: 6px; overflow-x: auto; }
  .impacto-cards { display: grid; grid-template-columns: repeat(5,1fr); gap: 10px; }
  .impacto-card { border-radius: 8px; padding: 12px; text-align: center; }
  .impacto-card .label { font-size: 10px; color: #555; text-transform: uppercase; }
  .impacto-card .value { font-size: 18px; font-weight: bold; margin-top: 6px; }
  .impacto-note { margin-top: 12px; padding: 10px 14px; background: #FEF9C3;
    border-radius: 8px; font-size: 12px; color: #5a4a00; border-left: 4px solid #D4AC0D; }
  .aviso-note { margin-top: 0; padding: 10px 14px; background: #EAE3F5;
    border-radius: 8px; font-size: 12px; color: #3D2A5C; border-left: 4px solid #5A3E85; }
  footer { text-align: center; font-size: 11px; color: #999; padding: 14px; }
  .btn-print { position: fixed; bottom: 24px; right: 24px; z-index: 999;
    background: var(--header-bg); color: #fff; border: none; border-radius: 50px;
    padding: 10px 20px; font-size: 13px; font-weight: bold; cursor: pointer;
    box-shadow: 0 2px 8px rgba(0,0,0,0.25); }
  .btn-print:hover { opacity: 0.88; }
  @media (max-width: 1100px) {
    .kpis { grid-template-columns: repeat(3,1fr); }
    .grid2 { grid-template-columns: 1fr; }
    .impacto-cards { grid-template-columns: repeat(3,1fr); }
  }
  @media print {
    @page { size: A4 landscape; margin: 12mm 10mm; }
    body { background: #fff; font-size: 10px; }
    header { padding: 8px 12px; }
    header h1 { font-size: 14px; }
    header p  { font-size: 9px; }
    main { padding: 8px 0; max-width: 100%; }
    .btn-print { display: none; }
    section { box-shadow: none; border: 1px solid #ddd; padding: 10px 12px;
      margin-bottom: 10px; break-inside: avoid; }
    section h2 { font-size: 11px; margin-bottom: 6px; }
    .kpis { gap: 5px; margin-bottom: 10px; }
    .kpi { padding: 7px 5px; box-shadow: none; border: 1px solid #ddd; }
    .kpi .value { font-size: 13px; }
    .kpi .label { font-size: 8px; }
    .chart-wrap, canvas { display: none !important; }
    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .table-scroll { max-height: none !important; overflow: visible !important;
      border: 1px solid #ddd; margin-top: 0 !important; }
    table { font-size: 9px; width: 100%; }
    th, td { padding: 3px 6px; }
    .impacto-cards { gap: 6px; }
    .impacto-card { padding: 8px; }
    .impacto-card .value { font-size: 13px; }
    .impacto-note, .aviso-note { font-size: 10px; padding: 8px 10px; }
    footer { font-size: 9px; padding: 6px; }
    * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
  }
</style>
</head>
<body>
<header>
  <h1>Dashboard Margem Real OTHIL -- __TIPO_LABEL__</h1>
  <p>__PREFIXO__: __DATA_EMISSAO__ &nbsp;|&nbsp; Periodo: __PERIODO__
     &nbsp;|&nbsp;
     <small>Custo real = Custo &divide; (1 + % administrativo do produto) &nbsp;|&nbsp;
     MC R$ real = Fat - Custo real &nbsp;|&nbsp; MC % real = MC R$ real / Custo real x 100
     (sem os 15pp operacionais de outros indicadores)</small></p>
</header>
<main>

  <div class="kpis" id="kpis"></div>

  <section id="secaoSemCadastro" style="display:none;">
    <h2>&#9888; Produtos sem % administrativo cadastrado (usando __PADRAO_PCT__% padrão)</h2>
    <div class="aviso-note">Estes produtos ainda não têm percentual cadastrado em
      <strong>Cadastro de Marcas</strong> -- o número deles nesta tela está usando um
      percentual aproximado (__PADRAO_PCT__%), não o real. Cadastre o produto certo assim
      que possível pra este número ficar exato.</div>
    <div class="table-scroll" style="margin-top:10px;max-height:200px;">
      <table id="tabelaSemCadastro">
        <thead><tr><th>Produto</th><th class="num">Caixas</th><th class="num">Faturamento R$</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>Faturamento por vendedor</h2>
    <div class="grid2">
      <div class="chart-wrap"><canvas id="chartVendedores"></canvas></div>
      <div class="table-scroll">
        <table id="tabelaRanking">
          <thead><tr>
            <th class="sortable" data-key="vendedor" data-type="str">Vendedor</th>
            <th class="num sortable" data-key="clientes" data-type="num">Clientes</th>
            <th class="num sortable" data-key="caixas" data-type="num">Caixas</th>
            <th class="num sortable" data-key="faturamento" data-type="num">Faturamento R$</th>
            <th class="num sortable" data-key="mc_rs" data-type="num">MC R$ real</th>
            <th class="num sortable" data-key="mc_pct_real" data-type="num">MC % real</th>
            <th>Status</th>
          </tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>
  </section>

  <section>
    <div class="grid2">
      <div>
        <h2>Faturamento por categoria de produto</h2>
        <div class="chart-wrap small"><canvas id="chartCategorias"></canvas></div>
        <div class="table-scroll" style="margin-top:10px;max-height:180px;">
          <table id="tabelaCategorias">
            <thead><tr>
              <th class="sortable" data-key="categoria" data-type="str">Categoria</th>
              <th class="num sortable" data-key="faturamento" data-type="num">Faturamento R$</th>
              <th class="num sortable" data-key="mc_rs" data-type="num">MC R$ real</th>
              <th class="num sortable" data-key="mc_pct_real" data-type="num">MC % real</th>
            </tr></thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
      <div>
        <h2>Top 10 clientes</h2>
        <div class="chart-wrap small"><canvas id="chartClientes"></canvas></div>
        <h2 style="margin-top:14px;">Todos os clientes do dia (<span id="qtdClientes"></span>)</h2>
        <div class="table-scroll" style="margin-top:10px;max-height:320px;">
          <table id="tabelaClientes">
            <thead><tr>
              <th class="sortable" data-key="cliente" data-type="str">Cliente</th>
              <th class="num sortable" data-key="faturamento" data-type="num">Faturamento R$</th>
              <th class="num sortable" data-key="mc_rs" data-type="num">MC R$ real</th>
              <th class="num sortable" data-key="mc_pct_real" data-type="num">MC % real</th>
            </tr></thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
    </div>
  </section>

  <section>
    <h2>Alertas -- MC % real abaixo de 0% (vendendo abaixo do custo real) (<span id="qtdAlertas"></span> itens, pior para o melhor)</h2>
    <div class="table-scroll">
      <table id="tabelaAlertas">
        <thead><tr>
          <th>Vendedor</th><th>Cliente</th><th>Produto</th>
          <th class="num">Qtd</th>
          <th class="num">Custo Real Unit.</th><th class="num">Venda Unit.</th>
          <th class="num">MC R$ real</th><th class="num">MC % real</th><th>Situacao</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <section id="secaoImpacto">
    <h2>Impacto das vendas com MC % real &lt;0% na margem do periodo</h2>
    <div class="impacto-cards" id="impactoCards"></div>
    <div class="impacto-note" id="impactoNota"></div>
  </section>

</main>
<button class="btn-print" onclick="window.print()">Imprimir / Salvar PDF</button>
<footer>Gerado automaticamente -- PDF Lucratividade por Vendedor-Cliente no Previsao (Mercatus).
Custo real = Custo &divide; (1 + % administrativo do produto) &nbsp;|&nbsp; MC % real = MC R$ real / Custo real x 100.</footer>

<script>
const DADOS = __DADOS_JSON__;
const fmtMoney  = v => 'R$ ' + v.toLocaleString('pt-BR', {minimumFractionDigits:2, maximumFractionDigits:2});
const fmtPct    = v => v.toLocaleString('pt-BR', {minimumFractionDigits:2, maximumFractionDigits:2}) + '%';
const fmtQty    = v => v.toLocaleString('pt-BR', {minimumFractionDigits:3, maximumFractionDigits:3});
const fmtSimple = v => v.toLocaleString('pt-BR', {minimumFractionDigits:1, maximumFractionDigits:1}) + '%';

function resColor(pct) {
  if (pct >= 15) return {bg:'__VERDE_BG__',    fg:'__VERDE_FG__'};
  if (pct >= 0)  return {bg:'__AMARELO_BG__',  fg:'__AMARELO_FG__'};
  return              {bg:'__VERMELHO_BG__', fg:'__VERMELHO_FG__'};
}

// Ordenação por clique no cabeçalho (pedido Ingrid, 31/08/2026: "opção de
// ordenar por margem de MC" na aba Margem Real) -- genérico pra qualquer
// tabela marcada com th.sortable[data-key]: clica ordena por aquela coluna
// (asc: primeiro clique / desc: segundo clique no mesmo cabeçalho), com uma
// seta indicando a coluna/direção atual. Ordena o array de dados em si (não
// só o DOM), então reflete o valor real -- e como cada tabela recebe sua
// própria renderFn (só recria as linhas, não o gráfico), o gráfico ao lado
// continua mostrando a ordem original dos dados, sem duplicar.
const _sortState = {};
function attachSort(tableId, arr, renderFn) {
  const table = document.getElementById(tableId);
  if (!table) return;
  const ths = table.querySelectorAll('thead th.sortable');
  ths.forEach(th => {
    const arrow = document.createElement('span');
    arrow.className = 'arrow';
    th.appendChild(document.createTextNode(' '));
    th.appendChild(arrow);
    th.addEventListener('click', () => {
      const key = th.dataset.key;
      const tipo = th.dataset.type;
      const atual = _sortState[tableId];
      const dir = (atual && atual.key === key && atual.dir === 'asc') ? 'desc' : 'asc';
      arr.sort((a, b) => {
        let va = a[key], vb = b[key];
        if (tipo === 'num') {
          va = Number(va) || 0; vb = Number(vb) || 0;
        } else {
          va = String(va || '').toLowerCase(); vb = String(vb || '').toLowerCase();
        }
        if (va < vb) return dir === 'asc' ? -1 : 1;
        if (va > vb) return dir === 'asc' ? 1 : -1;
        return 0;
      });
      _sortState[tableId] = {key, dir};
      ths.forEach(t => { t.querySelector('.arrow').textContent = ''; });
      arrow.textContent = dir === 'asc' ? '▲' : '▼';
      renderFn();
    });
  });
}

function montarKpis() {
  const k = DADOS.kpis;
  const cards = [
    ['Faturamento',       fmtMoney(k.faturamento)],
    ['MC R$ real',        fmtMoney(k.mc_rs)],
    ['MC % real',         fmtPct(k.mc_pct_real)],
    ['Caixas',            fmtQty(k.caixas)],
    ['Clientes',          k.clientes],
    ['Vendedores Ativos', k.vendedores_ativos],
  ];
  document.getElementById('kpis').innerHTML = cards.map(([label, value]) =>
    '<div class="kpi"><div class="label">' + label + '</div><div class="value">' + value + '</div></div>'
  ).join('');
}

function montarSemCadastro() {
  if (!DADOS.sem_cadastro || DADOS.sem_cadastro.length === 0) return;
  document.getElementById('secaoSemCadastro').style.display = '';
  const tbody = document.querySelector('#tabelaSemCadastro tbody');
  tbody.innerHTML = DADOS.sem_cadastro.map(p =>
    '<tr><td class="wrap">' + p.produto + '</td>' +
    '<td class="num">' + fmtQty(p.qtd) + '</td>' +
    '<td class="num">' + fmtMoney(p.faturamento) + '</td></tr>'
  ).join('');
}

function renderTabelaRanking() {
  const tbody = document.querySelector('#tabelaRanking tbody');
  tbody.innerHTML = DADOS.ranking.map(r => {
    const cRes = resColor(r.mc_pct_real);
    const mcNeg = r.mc_rs < 0;
    return '<tr>' +
      '<td><strong>' + r.vendedor + '</strong></td>' +
      '<td class="num">' + r.clientes + '</td>' +
      '<td class="num">' + fmtQty(r.caixas) + '</td>' +
      '<td class="num">' + fmtMoney(r.faturamento) + '</td>' +
      '<td class="num" style="color:' + (mcNeg?'__VERMELHO_FG__':'inherit') + ';font-weight:' + (mcNeg?'bold':'normal') + ';">' + fmtMoney(r.mc_rs) + '</td>' +
      '<td class="num" style="background:' + cRes.bg + ';color:' + cRes.fg + ';font-weight:bold;">' + fmtPct(r.mc_pct_real) + '</td>' +
      '<td><span class="badge" style="background:' + r.bg + ';color:' + r.fg + ';">' + r.status + '</span></td>' +
      '</tr>';
  }).join('');
}

function montarRanking() {
  renderTabelaRanking();

  try {
    new Chart(document.getElementById('chartVendedores'), {
      type: 'bar',
      data: {
        labels: DADOS.ranking.map(r => r.vendedor),
        datasets: [{ label: 'Faturamento R$', data: DADOS.ranking.map(r => r.faturamento),
          backgroundColor: '__HEADER_BG__' }],
      },
      options: { responsive:true, maintainAspectRatio:false,
        plugins: { legend:{display:false} },
        scales: { y: { beginAtZero:true, ticks:{ callback: v=>'R$ '+v.toLocaleString('pt-BR') } } } },
    });
  } catch(e) { console.error('Erro grafico vendedores:', e); }

  attachSort('tabelaRanking', DADOS.ranking, renderTabelaRanking);
}

function montarCategorias() {
  const palette = ['__HEADER_BG__','#8467AC','#A78BC9','#4A2E70','#C3AEDD',
                   '#6B4B96','#3D2A5C','#2A1D42','#9578B8','#D9CCE8',
                   '#7B5EA0','#5C4080','#402C5E','#33223F','#846FA8',
                   '#B29FCD','#F1EAF7','#E4D9F0'];
  try {
    new Chart(document.getElementById('chartCategorias'), {
      type: 'doughnut',
      data: {
        labels: DADOS.categorias.map(c => c.categoria),
        datasets: [{ data: DADOS.categorias.map(c => c.faturamento),
          backgroundColor: DADOS.categorias.map((_,i) => palette[i%palette.length]) }],
      },
      options: { responsive:true, maintainAspectRatio:false,
        plugins: { legend:{position:'right', labels:{boxWidth:10,font:{size:10}}},
          tooltip:{ callbacks:{ label: ctx=>ctx.label + ': ' + fmtMoney(ctx.parsed) } } } },
    });
  } catch(e) { console.error('Erro grafico categorias:', e); }

  renderTabelaCategorias();
  attachSort('tabelaCategorias', DADOS.categorias, renderTabelaCategorias);
}

function renderTabelaCategorias() {
  const tbody = document.querySelector('#tabelaCategorias tbody');
  tbody.innerHTML = DADOS.categorias.map(c => {
    const cRes = resColor(c.mc_pct_real);
    const mcNeg = c.mc_rs < 0;
    return '<tr>' +
      '<td>' + c.categoria + '</td>' +
      '<td class="num">' + fmtMoney(c.faturamento) + '</td>' +
      '<td class="num" style="color:' + (mcNeg?'__VERMELHO_FG__':'inherit') + ';font-weight:' + (mcNeg?'bold':'normal') + ';">' + fmtMoney(c.mc_rs) + '</td>' +
      '<td class="num" style="background:' + cRes.bg + ';color:' + cRes.fg + ';font-weight:bold;">' + fmtPct(c.mc_pct_real) + '</td>' +
      '</tr>';
  }).join('');
}

function montarClientes() {
  try {
    new Chart(document.getElementById('chartClientes'), {
      type: 'bar',
      data: {
        labels: DADOS.top_clientes.map(c => c.cliente),
        datasets: [{ label:'Faturamento R$', data: DADOS.top_clientes.map(c=>c.faturamento),
          backgroundColor:'#6B4B96' }],
      },
      options: { indexAxis:'y', responsive:true, maintainAspectRatio:false,
        plugins: { legend:{display:false},
          tooltip: { callbacks: { afterLabel: ctx => {
            const c = DADOS.top_clientes[ctx.dataIndex];
            return 'MC real: ' + fmtMoney(c.mc_rs) + ' | MC % real: ' + fmtPct(c.mc_pct_real);
          }}}},
        scales: { x:{ beginAtZero:true, ticks:{ callback: v=>'R$'+v.toLocaleString('pt-BR') } } } },
    });
  } catch(e) { console.error('Erro grafico clientes:', e); }

  document.getElementById('qtdClientes').textContent = DADOS.todos_clientes.length;
  renderTabelaClientes();
  attachSort('tabelaClientes', DADOS.todos_clientes, renderTabelaClientes);
}

function renderTabelaClientes() {
  const tbody = document.querySelector('#tabelaClientes tbody');
  tbody.innerHTML = DADOS.todos_clientes.map(c => {
    const cRes = resColor(c.mc_pct_real);
    const mcNeg = c.mc_rs < 0;
    return '<tr>' +
      '<td class="wrap">' + c.cliente + '</td>' +
      '<td class="num">' + fmtMoney(c.faturamento) + '</td>' +
      '<td class="num" style="color:' + (mcNeg?'__VERMELHO_FG__':'inherit') + ';font-weight:' + (mcNeg?'bold':'normal') + ';">' + fmtMoney(c.mc_rs) + '</td>' +
      '<td class="num" style="background:' + cRes.bg + ';color:' + cRes.fg + ';font-weight:bold;">' + fmtPct(c.mc_pct_real) + '</td>' +
      '</tr>';
  }).join('');
}

function montarAlertas() {
  document.getElementById('qtdAlertas').textContent = DADOS.alertas.length;
  const tbody = document.querySelector('#tabelaAlertas tbody');
  tbody.innerHTML = DADOS.alertas.map(a => {
    const cRes = resColor(a.mc_pct_real);
    const cadastroTag = a.sem_cadastro ? ' <span class="badge" style="background:__AMARELO_BG__;color:__AMARELO_FG__;">sem % cadastrado</span>' : '';
    return '<tr>' +
      '<td>' + a.vendedor + '</td>' +
      '<td class="wrap">' + a.cliente + '</td>' +
      '<td class="wrap">' + a.produto + cadastroTag + '</td>' +
      '<td class="num">' + fmtQty(a.qtd) + '</td>' +
      '<td class="num">' + fmtMoney(a.custo_real_unit) + '</td>' +
      '<td class="num">' + fmtMoney(a.venda_unit) + '</td>' +
      '<td class="num" style="color:__VERMELHO_FG__;font-weight:bold;">' + fmtMoney(a.mc_rs) + '</td>' +
      '<td class="num" style="background:' + cRes.bg + ';color:' + cRes.fg + ';font-weight:bold;">' + fmtPct(a.mc_pct_real) + '</td>' +
      '<td><span class="badge" style="background:' + a.bg + ';color:' + a.fg + ';">' + a.status + '</span></td>' +
      '</tr>';
  }).join('');
}

function montarImpacto() {
  const imp = DADOS.impacto;
  if (!imp || imp.n_alertas === 0) {
    document.getElementById('secaoImpacto').style.display = 'none';
    return;
  }
  const mcNeg = imp.mc_rs_alertas < 0;
  const cards = [
    { label:'Fat. alertas (MC real <0%)', value: fmtMoney(imp.fat_alertas),
      bg:'__VERMELHO_BG__', fg:'__VERMELHO_FG__' },
    { label:'Caixas (MC real <0%)',        value: fmtQty(imp.caixas_alertas),
      bg:'__VERMELHO_BG__', fg:'__VERMELHO_FG__' },
    { label:'% do Fat. Total',             value: fmtSimple(imp.pct_fat_alertas),
      bg:'__AMARELO_BG__',  fg:'__AMARELO_FG__' },
    { label:'MC R$ real acumulada',        value: fmtMoney(imp.mc_rs_alertas),
      bg: mcNeg?'__VERMELHO_BG__':'__VERDE_BG__',
      fg: mcNeg?'__VERMELHO_FG__':'__VERDE_FG__' },
    { label:'Impacto na MC % real',        value: (imp.impacto_pp>0?'+':'') + fmtSimple(imp.impacto_pp) + ' pp',
      bg:'__AMARELO_BG__',  fg:'__AMARELO_FG__' },
  ];
  document.getElementById('impactoCards').innerHTML = cards.map(c =>
    '<div class="impacto-card" style="background:' + c.bg + ';color:' + c.fg + ';">' +
    '<div class="label">' + c.label + '</div><div class="value">' + c.value + '</div>' +
    '</div>'
  ).join('');

  const dir = imp.impacto_pp > 0 ? 'subiria' : 'cairia';
  document.getElementById('impactoNota').innerHTML =
    '<strong>Analise:</strong> As ' + imp.n_alertas + ' vendas com MC % real abaixo de 0% representam ' +
    '<strong>' + fmtSimple(imp.pct_fat_alertas) + '</strong> do faturamento (' + fmtMoney(imp.fat_alertas) + ') ' +
    'e acumulam MC real de <strong>' + fmtMoney(imp.mc_rs_alertas) + '</strong>. ' +
    'Sem essas vendas, a MC % real ' + dir + ' de ' +
    '<strong>' + fmtPct(imp.mc_pct_total) + '</strong> para ' +
    '<strong>' + fmtPct(imp.mc_pct_sem_alertas) + '</strong> ' +
    '(impacto de <strong>' + (imp.impacto_pp>0?'+':'') + fmtSimple(imp.impacto_pp) + ' pp</strong>).';
}

[montarKpis, montarSemCadastro, montarRanking, montarCategorias, montarClientes, montarAlertas, montarImpacto].forEach(fn => {
  try { fn(); } catch(e) { console.error('Erro:', e); }
});
</script>
</body>
</html>"""
)


def gerar_dashboard(parsed, tabela, output_path, tipo='diario'):
    """tipo: 'diario' | 'semanal' | 'mensal'. `tabela` é o cadastro de
    marcas já carregado (margem_produto.carregar_marcas()) -- passado
    de fora pra quem gera vários dashboards em sequência poder carregar uma
    vez só, em vez de ler a persistência central a cada chamada."""
    dados = _montar_dados(parsed, tabela)
    _titulos = {
        'diario':  'Dashboard Diario -- Margem Real',
        'semanal': 'Dashboard Semanal -- Margem Real',
        'mensal':  'Dashboard Mensal -- Margem Real',
    }
    _prefixos = {'diario': 'Dia', 'semanal': 'Semana', 'mensal': 'Mes'}
    html = (_HTML_TEMPLATE
            .replace('__TIPO_LABEL__',   _titulos.get(tipo, 'Dashboard Margem Real'))
            .replace('__PREFIXO__',      _prefixos.get(tipo, 'Periodo'))
            .replace('__PADRAO_PCT__',   f'{mp.PADRAO_PCT:g}')
            .replace('__CHARTJS_SRC__',  _CHARTJS_SRC)
            .replace('__DATA_EMISSAO__', dados['data_emissao'] or '-')
            .replace('__PERIODO__',      dados['periodo'] or '-')
            .replace('__VERDE_BG__',     VERDE_BG)   .replace('__VERDE_FG__',    VERDE_FG)
            .replace('__AMARELO_BG__',   AMARELO_BG) .replace('__AMARELO_FG__',  AMARELO_FG)
            .replace('__VERMELHO_BG__',  VERMELHO_BG).replace('__VERMELHO_FG__', VERMELHO_FG)
            .replace('__HEADER_BG__',    HEADER_BG)  .replace('__HEADER_FG__',   HEADER_FG)
            .replace('__DADOS_JSON__',   json.dumps(dados, ensure_ascii=False)))
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return output_path
