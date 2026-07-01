"""Gera o dashboard HTML gerencial 'dashboard_gerencial_othil_DDMMAAAA.html'.

Dois indicadores:
  MC R$  = Faturamento − Custo_PDF  (valor monetário do prejuízo/lucro)
  Resultado Real % = MC% + 15pp  (= Resultado%_PDF + 15pp de despesa adm)

  Filtro de Alertas: MC % < −15%  (inclui todos os itens com margem ruim)
"""
import json
import os
from categorias import map_categoria

_CHARTJS_PATH = os.path.join(os.path.dirname(__file__), 'chart_umd.js')
with open(_CHARTJS_PATH, encoding='utf-8') as _f:
    _CHARTJS_SRC = _f.read()

VERDE_BG,    VERDE_FG    = '#D8EFE3', '#1B4332'
AMARELO_BG,  AMARELO_FG  = '#FEF9C3', '#7D6608'
VERMELHO_BG, VERMELHO_FG = '#FADADD', '#7A1F2B'
HEADER_BG,   HEADER_FG   = '#2D6A4F', '#FFFFFF'


def _calc(faturamento, custo_pdf):
    """(mc_rs, mc_pct, resultado_real_pct)"""
    mc_rs  = faturamento - custo_pdf
    mc_pct = mc_rs / custo_pdf * 100 if custo_pdf else 0.0
    return round(mc_rs, 2), round(mc_pct, 2), round(mc_pct + 15, 2)


def _status(resultado_real_pct):
    if resultado_real_pct >= 15: return 'OK',      VERDE_BG,    VERDE_FG
    if resultado_real_pct >= 0:  return 'Atenção', AMARELO_BG,  AMARELO_FG
    return                        'Crítico', VERMELHO_BG, VERMELHO_FG


def _montar_dados(parsed):
    itens = parsed['itens']

    fat_total    = sum(it['faturamento'] for it in itens)
    custo_total  = sum(it['custo_total'] for it in itens)
    caixas_total = sum(it['qtd']         for it in itens)
    mc_rs_total, mc_pct_total, res_real_total = _calc(fat_total, custo_total)
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
        custo  = sum(it['custo_total'] for it in d['itens'])
        caixas = sum(it['qtd']         for it in d['itens'])
        mc_rs, _, res_real = _calc(fat, custo)
        status, bg, fg = _status(res_real)
        ranking.append({
            'vendedor': vname, 'clientes': len(d['clientes']),
            'caixas': round(caixas, 3), 'faturamento': round(fat, 2),
            'mc_rs': mc_rs, 'resultado_real_pct': res_real,
            'status': status, 'bg': bg, 'fg': fg,
        })
    ranking.sort(key=lambda r: -r['faturamento'])
    vendedores_ativos = len(ranking)

    # ---- categorias ----------------------------------------------------
    por_categoria = {}
    for it in itens:
        cat = map_categoria(it['produto'])
        d = por_categoria.setdefault(cat, {'fat': 0.0, 'custo': 0.0})
        d['fat']   += it['faturamento']
        d['custo'] += it['custo_total']
    categorias_lista = []
    for cat, d in sorted(por_categoria.items(), key=lambda x: -x[1]['fat']):
        mc_rs_cat, _, res_real_cat = _calc(d['fat'], d['custo'])
        categorias_lista.append({
            'categoria': cat, 'faturamento': round(d['fat'], 2),
            'mc_rs': mc_rs_cat, 'resultado_real_pct': res_real_cat,
        })

    # ---- top 10 clientes -----------------------------------------------
    por_cliente = {}
    for it in itens:
        cod = it['cliente_codigo']
        d = por_cliente.setdefault(cod, {'nome': it['cliente_nome'], 'fat': 0.0, 'custo': 0.0})
        d['fat']   += it['faturamento']
        d['custo'] += it['custo_total']
    top_clientes = []
    for cod, d in sorted(por_cliente.items(), key=lambda x: -x[1]['fat'])[:10]:
        mc_rs_cli, _, res_real_cli = _calc(d['fat'], d['custo'])
        top_clientes.append({
            'cliente': d['nome'], 'codigo': cod,
            'faturamento': round(d['fat'], 2),
            'mc_rs': mc_rs_cli, 'resultado_real_pct': res_real_cli,
        })

    # ---- alertas: MC % < -15% ------------------------------------------
    alertas = []
    alertas_fat   = 0.0
    alertas_mc_rs = 0.0
    alertas_custo = 0.0
    for it in itens:
        mc_rs_it, mc_pct_it, res_real_it = _calc(it['faturamento'], it['custo_total'])
        if mc_pct_it < -15:
            qtd = it['qtd']
            venda_unit = it['faturamento'] / qtd if qtd else 0.0
            status, bg, fg = _status(res_real_it)
            alertas.append({
                'vendedor':       it['vendedor'] or it['vendedor_raw'],
                'cliente':        it['cliente_nome'],
                'produto':        it['produto'],
                'qtd':            round(qtd, 3),
                'custo_unit':     round(it['custo_unit'], 2),
                'venda_unit':     round(venda_unit, 2),
                'mc_rs':          round(mc_rs_it, 2),
                'resultado_real': round(res_real_it, 2),
                'status': status, 'bg': bg, 'fg': fg,
            })
            alertas_fat   += it['faturamento']
            alertas_mc_rs += mc_rs_it
            alertas_custo += it['custo_total']
    alertas.sort(key=lambda a: a['resultado_real'])

    # ---- impacto -------------------------------------------------------
    pct_fat_alertas = alertas_fat / fat_total * 100 if fat_total else 0.0
    custo_sem = custo_total - alertas_custo
    mc_rs_sem = mc_rs_total - alertas_mc_rs
    mc_pct_sem = mc_rs_sem / custo_sem * 100 if custo_sem else 0.0
    res_real_sem = mc_pct_sem + 15
    impacto_pp = res_real_sem - res_real_total

    impacto = {
        'fat_alertas':          round(alertas_fat, 2),
        'pct_fat_alertas':      round(pct_fat_alertas, 2),
        'mc_rs_alertas':        round(alertas_mc_rs, 2),
        'res_real_total':       res_real_total,
        'res_real_sem_alertas': round(res_real_sem, 2),
        'impacto_pp':           round(impacto_pp, 2),
        'n_alertas':            len(alertas),
    }

    return {
        'data_emissao': parsed.get('data_emissao'),
        'periodo':      parsed.get('periodo'),
        'kpis': {
            'faturamento':        round(fat_total, 2),
            'mc_rs':              mc_rs_total,
            'resultado_real_pct': res_real_total,
            'caixas':             round(caixas_total, 3),
            'clientes':           clientes_distintos,
            'vendedores_ativos':  vendedores_ativos,
        },
        'ranking':      ranking,
        'categorias':   categorias_lista,
        'top_clientes': top_clientes,
        'alertas':      alertas,
        'impacto':      impacto,
    }


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Dashboard Gerencial OTHIL — __DATA_EMISSAO__</title>
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
  td { white-space: nowrap; }
  td.wrap { white-space: normal; max-width: 180px; }
  td.num, th.num { text-align: right; }
  tr:hover td { background: #FAFAFA; }
  .badge { display: inline-block; padding: 2px 7px; border-radius: 10px;
           font-weight: bold; font-size: 11px; white-space: nowrap; }
  .table-scroll { max-height: 420px; overflow-y: auto; border: 1px solid #EEE;
    border-radius: 6px; overflow-x: auto; }
  .impacto-cards { display: grid; grid-template-columns: repeat(4,1fr); gap: 10px; }
  .impacto-card { border-radius: 8px; padding: 12px; text-align: center; }
  .impacto-card .label { font-size: 10px; color: #555; text-transform: uppercase; }
  .impacto-card .value { font-size: 18px; font-weight: bold; margin-top: 6px; }
  .impacto-note { margin-top: 12px; padding: 10px 14px; background: #FEF9C3;
    border-radius: 8px; font-size: 12px; color: #5a4a00; border-left: 4px solid #D4AC0D; }
  footer { text-align: center; font-size: 11px; color: #999; padding: 14px; }
  .btn-print { position: fixed; bottom: 24px; right: 24px; z-index: 999;
    background: var(--header-bg); color: #fff; border: none; border-radius: 50px;
    padding: 10px 20px; font-size: 13px; font-weight: bold; cursor: pointer;
    box-shadow: 0 2px 8px rgba(0,0,0,0.25); }
  .btn-print:hover { opacity: 0.88; }
  @media (max-width: 1100px) {
    .kpis { grid-template-columns: repeat(3,1fr); }
    .grid2 { grid-template-columns: 1fr; }
    .impacto-cards { grid-template-columns: repeat(2,1fr); }
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
    /* Oculta gráficos — dados já estão nas tabelas */
    .chart-wrap, canvas { display: none !important; }
    /* Empilha as duas colunas lado a lado sem os gráficos */
    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .table-scroll { max-height: none !important; overflow: visible !important;
      border: 1px solid #ddd; margin-top: 0 !important; }
    table { font-size: 9px; width: 100%; }
    th, td { padding: 3px 6px; }
    .impacto-cards { gap: 6px; }
    .impacto-card { padding: 8px; }
    .impacto-card .value { font-size: 13px; }
    .impacto-note { font-size: 10px; padding: 8px 10px; }
    footer { font-size: 9px; padding: 6px; }
    * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
  }
</style>
</head>
<body>
<header>
  <h1>Relatório Diário de Vendas OTHIL — Dashboard Gerencial</h1>
  <p>Dia: __DATA_EMISSAO__ &nbsp;|&nbsp; Período: __PERIODO__
     &nbsp;|&nbsp;
     <small>MC R$ = Fat − Custo &nbsp;|&nbsp; Resultado Real % = (MC R$ / Custo × 100) + 15pp</small></p>
</header>
<main>

  <div class="kpis" id="kpis"></div>

  <section>
    <h2>Faturamento por vendedor</h2>
    <div class="grid2">
      <div class="chart-wrap"><canvas id="chartVendedores"></canvas></div>
      <div class="table-scroll">
        <table id="tabelaRanking">
          <thead><tr>
            <th>Vendedor</th><th class="num">Clientes</th><th class="num">Caixas</th>
            <th class="num">Faturamento R$</th><th class="num">MC R$</th>
            <th class="num">Resultado Real %</th><th>Status</th>
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
              <th>Categoria</th><th class="num">Faturamento R$</th>
              <th class="num">MC R$</th><th class="num">Resultado Real %</th>
            </tr></thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
      <div>
        <h2>Top 10 clientes do dia</h2>
        <div class="chart-wrap small"><canvas id="chartClientes"></canvas></div>
        <div class="table-scroll" style="margin-top:10px;max-height:180px;">
          <table id="tabelaClientes">
            <thead><tr>
              <th>Cliente</th><th class="num">Faturamento R$</th>
              <th class="num">MC R$</th><th class="num">Resultado Real %</th>
            </tr></thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
    </div>
  </section>

  <section>
    <h2>Alertas — MC % abaixo de −15% (<span id="qtdAlertas"></span> itens, pior para o melhor)</h2>
    <div class="table-scroll">
      <table id="tabelaAlertas">
        <thead><tr>
          <th>Vendedor</th><th>Cliente</th><th>Produto</th>
          <th class="num">Qtd</th>
          <th class="num">Custo Unit.</th><th class="num">Venda Unit.</th>
          <th class="num">MC R$</th><th class="num">Resultado Real %</th><th>Situação</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <section id="secaoImpacto">
    <h2>Impacto das vendas com MC % &lt;−15% na margem do dia</h2>
    <div class="impacto-cards" id="impactoCards"></div>
    <div class="impacto-note" id="impactoNota"></div>
  </section>

</main>
<button class="btn-print" onclick="window.print()">🖨️ Imprimir / Salvar PDF</button>
<footer>Gerado automaticamente — PDF "Lucratividade por Vendedor-Cliente no Previsão" (Mercatus).
MC R$ = Faturamento − Custo &nbsp;|&nbsp; Resultado Real % = MC% + 15pp.</footer>

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

function montarKpis() {
  const k = DADOS.kpis;
  const cards = [
    ['Faturamento',       fmtMoney(k.faturamento)],
    ['MC R$',             fmtMoney(k.mc_rs)],
    ['Resultado Real %',  fmtPct(k.resultado_real_pct)],
    ['Caixas',            fmtQty(k.caixas)],
    ['Clientes',          k.clientes],
    ['Vendedores Ativos', k.vendedores_ativos],
  ];
  document.getElementById('kpis').innerHTML = cards.map(([label, value]) =>
    `<div class="kpi"><div class="label">${label}</div><div class="value">${value}</div></div>`
  ).join('');
}

function montarRanking() {
  const tbody = document.querySelector('#tabelaRanking tbody');
  tbody.innerHTML = DADOS.ranking.map(r => {
    const cRes = resColor(r.resultado_real_pct);
    const mcNeg = r.mc_rs < 0;
    return `<tr>
      <td><strong>${r.vendedor}</strong></td>
      <td class="num">${r.clientes}</td>
      <td class="num">${fmtQty(r.caixas)}</td>
      <td class="num">${fmtMoney(r.faturamento)}</td>
      <td class="num" style="color:${mcNeg?'__VERMELHO_FG__':'inherit'};font-weight:${mcNeg?'bold':'normal'};">${fmtMoney(r.mc_rs)}</td>
      <td class="num" style="background:${cRes.bg};color:${cRes.fg};font-weight:bold;">${fmtPct(r.resultado_real_pct)}</td>
      <td><span class="badge" style="background:${r.bg};color:${r.fg};">${r.status}</span></td>
    </tr>`;
  }).join('');

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
  } catch(e) { console.error('Erro gráfico vendedores:', e); }
}

function montarCategorias() {
  const palette = ['__HEADER_BG__','#52B788','#95D5B2','#74A892','#B7E4C7',
                   '#40916C','#2D6A4F','#1B4332','#84A98C','#CAD2C5',
                   '#A3B18A','#588157','#3A5A40','#344E41','#6B9080',
                   '#A4C3B2','#EAF4F4','#CCE3DE'];
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
          tooltip:{ callbacks:{ label: ctx=>`${ctx.label}: ${fmtMoney(ctx.parsed)}` } } } },
    });
  } catch(e) { console.error('Erro gráfico categorias:', e); }

  const tbody = document.querySelector('#tabelaCategorias tbody');
  tbody.innerHTML = DADOS.categorias.map(c => {
    const cRes = resColor(c.resultado_real_pct);
    const mcNeg = c.mc_rs < 0;
    return `<tr>
      <td>${c.categoria}</td>
      <td class="num">${fmtMoney(c.faturamento)}</td>
      <td class="num" style="color:${mcNeg?'__VERMELHO_FG__':'inherit'};font-weight:${mcNeg?'bold':'normal'};">${fmtMoney(c.mc_rs)}</td>
      <td class="num" style="background:${cRes.bg};color:${cRes.fg};font-weight:bold;">${fmtPct(c.resultado_real_pct)}</td>
    </tr>`;
  }).join('');
}

function montarClientes() {
  try {
    new Chart(document.getElementById('chartClientes'), {
      type: 'bar',
      data: {
        labels: DADOS.top_clientes.map(c => c.cliente),
        datasets: [{ label:'Faturamento R$', data: DADOS.top_clientes.map(c=>c.faturamento),
          backgroundColor:'#40916C' }],
      },
      options: { indexAxis:'y', responsive:true, maintainAspectRatio:false,
        plugins: { legend:{display:false},
          tooltip: { callbacks: { afterLabel: ctx => {
            const c = DADOS.top_clientes[ctx.dataIndex];
            return `MC: ${fmtMoney(c.mc_rs)} | Res. Real: ${fmtPct(c.resultado_real_pct)}`;
          }}}},
        scales: { x:{ beginAtZero:true, ticks:{ callback: v=>'R$'+v.toLocaleString('pt-BR') } } } },
    });
  } catch(e) { console.error('Erro gráfico clientes:', e); }

  const tbody = document.querySelector('#tabelaClientes tbody');
  tbody.innerHTML = DADOS.top_clientes.map(c => {
    const cRes = resColor(c.resultado_real_pct);
    const mcNeg = c.mc_rs < 0;
    return `<tr>
      <td class="wrap">${c.cliente}</td>
      <td class="num">${fmtMoney(c.faturamento)}</td>
      <td class="num" style="color:${mcNeg?'__VERMELHO_FG__':'inherit'};font-weight:${mcNeg?'bold':'normal'};">${fmtMoney(c.mc_rs)}</td>
      <td class="num" style="background:${cRes.bg};color:${cRes.fg};font-weight:bold;">${fmtPct(c.resultado_real_pct)}</td>
    </tr>`;
  }).join('');
}

function montarAlertas() {
  document.getElementById('qtdAlertas').textContent = DADOS.alertas.length;
  const tbody = document.querySelector('#tabelaAlertas tbody');
  tbody.innerHTML = DADOS.alertas.map(a => {
    const cRes = resColor(a.resultado_real);
    return `<tr>
      <td>${a.vendedor}</td>
      <td class="wrap">${a.cliente}</td>
      <td class="wrap">${a.produto}</td>
      <td class="num">${fmtQty(a.qtd)}</td>
      <td class="num">${fmtMoney(a.custo_unit)}</td>
      <td class="num">${fmtMoney(a.venda_unit)}</td>
      <td class="num" style="color:__VERMELHO_FG__;font-weight:bold;">${fmtMoney(a.mc_rs)}</td>
      <td class="num" style="background:${cRes.bg};color:${cRes.fg};font-weight:bold;">${fmtPct(a.resultado_real)}</td>
      <td><span class="badge" style="background:${a.bg};color:${a.fg};">${a.status}</span></td>
    </tr>`;
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
    { label:'Fat. alertas (MC <−15%)',   value: fmtMoney(imp.fat_alertas),
      bg:'__VERMELHO_BG__', fg:'__VERMELHO_FG__' },
    { label:'% do Fat. Total',            value: fmtSimple(imp.pct_fat_alertas),
      bg:'__AMARELO_BG__',  fg:'__AMARELO_FG__' },
    { label:'MC R$ acumulada',            value: fmtMoney(imp.mc_rs_alertas),
      bg: mcNeg?'__VERMELHO_BG__':'__VERDE_BG__',
      fg: mcNeg?'__VERMELHO_FG__':'__VERDE_FG__' },
    { label:'Impacto no Res. Real',       value: (imp.impacto_pp>0?'+':'') + fmtSimple(imp.impacto_pp) + ' pp',
      bg:'__AMARELO_BG__',  fg:'__AMARELO_FG__' },
  ];
  document.getElementById('impactoCards').innerHTML = cards.map(c =>
    `<div class="impacto-card" style="background:${c.bg};color:${c.fg};">
      <div class="label">${c.label}</div><div class="value">${c.value}</div>
    </div>`
  ).join('');

  const dir = imp.impacto_pp > 0 ? 'subiria' : 'cairia';
  document.getElementById('impactoNota').innerHTML =
    `<strong>Análise:</strong> As ${imp.n_alertas} vendas com MC % abaixo de −15% representam
    <strong>${fmtSimple(imp.pct_fat_alertas)}</strong> do faturamento (${fmtMoney(imp.fat_alertas)})
    e acumulam MC de <strong>${fmtMoney(imp.mc_rs_alertas)}</strong>.
    Sem essas vendas, o Resultado Real ${dir} de
    <strong>${fmtPct(imp.res_real_total)}</strong> para
    <strong>${fmtPct(imp.res_real_sem_alertas)}</strong>
    (impacto de <strong>${imp.impacto_pp>0?'+':''}${fmtSimple(imp.impacto_pp)} pp</strong>).`;
}

[montarKpis, montarRanking, montarCategorias, montarClientes, montarAlertas, montarImpacto].forEach(fn => {
  try { fn(); } catch(e) { console.error('Erro:', e); }
});
</script>
</body>
</html>
"""


def gerar_dashboard(parsed, output_path):
    dados = _montar_dados(parsed)
    html = (_HTML_TEMPLATE
            .replace('__CHARTJS_SRC__', _CHARTJS_SRC)
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
