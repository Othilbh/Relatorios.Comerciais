"""Gera o dashboard HTML gerencial 'dashboard_gerencial_othil_DDMMAAAA.html'.

Regra de Margem de Contribuição (MC):
  Custo real = Custo_PDF / 1,15  (15% de despesa adm embutida)
  MC R$ = Faturamento - Custo_real
  MC %  = MC_R$ / Custo_real * 100

Seções do dashboard:
  - KPIs do dia (Faturamento, MC R$, MC %, Caixas, Clientes, Vendedores)
  - Ranking de vendedores (gráfico + tabela com MC)
  - Faturamento + MC % por categoria de produto
  - Top 10 clientes (faturamento + MC %)
  - Alertas MC < -15% (Qtd, Custo Unit, Venda Unit, MC %)
  - Impacto das vendas abaixo de -15% na margem do dia
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
DESP_ADM = 1.15


def _mc_calc(faturamento, custo_pdf):
    custo_real = custo_pdf / DESP_ADM if custo_pdf else 0.0
    mc_rs  = faturamento - custo_real
    mc_pct = mc_rs / custo_real * 100 if custo_real else 0.0
    return round(mc_rs, 2), round(mc_pct, 2)


def _status(mc_pct):
    if mc_pct >= 15: return 'OK',      VERDE_BG,    VERDE_FG
    if mc_pct >= 0:  return 'Atenção', AMARELO_BG,  AMARELO_FG
    return                  'Crítico', VERMELHO_BG, VERMELHO_FG


def _montar_dados(parsed):
    itens = parsed['itens']

    fat_total   = sum(it['faturamento'] for it in itens)
    custo_total = sum(it['custo_total'] for it in itens)
    caixas_total = sum(it['qtd'] for it in itens)
    mc_rs_total, mc_pct_total = _mc_calc(fat_total, custo_total)
    clientes_distintos = len(set(it['cliente_codigo'] for it in itens))
    custo_real_total = custo_total / DESP_ADM if custo_total else 0.0

    # ---- ranking de vendedores -----------------------------------------
    por_vendedor = {}
    for it in itens:
        vname = it['vendedor'] or it['vendedor_raw']
        d = por_vendedor.setdefault(vname, {'itens': [], 'clientes': set()})
        d['itens'].append(it)
        d['clientes'].add(it['cliente_codigo'])

    ranking = []
    for vname, d in por_vendedor.items():
        fat   = sum(it['faturamento'] for it in d['itens'])
        custo = sum(it['custo_total'] for it in d['itens'])
        caixas = sum(it['qtd'] for it in d['itens'])
        mc_rs, mc_pct = _mc_calc(fat, custo)
        status, bg, fg = _status(mc_pct)
        ranking.append({
            'vendedor': vname, 'clientes': len(d['clientes']),
            'caixas': round(caixas, 3), 'faturamento': round(fat, 2),
            'mc_rs': mc_rs, 'mc_pct': mc_pct,
            'status': status, 'bg': bg, 'fg': fg,
        })
    ranking.sort(key=lambda r: -r['faturamento'])
    vendedores_ativos = len(ranking)

    # ---- faturamento + MC % por categoria ------------------------------
    por_categoria = {}
    for it in itens:
        cat = map_categoria(it['produto'])
        d = por_categoria.setdefault(cat, {'fat': 0.0, 'custo': 0.0})
        d['fat']   += it['faturamento']
        d['custo'] += it['custo_total']
    categorias_lista = []
    for cat, d in sorted(por_categoria.items(), key=lambda x: -x[1]['fat']):
        _, mc_pct_cat = _mc_calc(d['fat'], d['custo'])
        categorias_lista.append({
            'categoria': cat, 'faturamento': round(d['fat'], 2), 'mc_pct': mc_pct_cat,
        })

    # ---- top 10 clientes (por código, com MC %) ------------------------
    por_cliente = {}
    for it in itens:
        cod = it['cliente_codigo']
        d = por_cliente.setdefault(cod, {'nome': it['cliente_nome'], 'fat': 0.0, 'custo': 0.0})
        d['fat']   += it['faturamento']
        d['custo'] += it['custo_total']
    top_clientes = []
    for cod, d in sorted(por_cliente.items(), key=lambda x: -x[1]['fat'])[:10]:
        _, mc_pct_cli = _mc_calc(d['fat'], d['custo'])
        top_clientes.append({
            'cliente': d['nome'], 'codigo': cod,
            'faturamento': round(d['fat'], 2), 'mc_pct': mc_pct_cli,
        })

    # ---- alertas MC < -15% (Qtd, Custo Unit, Venda Unit, MC %) --------
    alertas = []
    alertas_fat   = 0.0
    alertas_mc_rs = 0.0
    alertas_custo_real = 0.0
    for it in itens:
        mc_rs_it, mc_pct_it = _mc_calc(it['faturamento'], it['custo_total'])
        if mc_pct_it < -15:
            qtd = it['qtd']
            venda_unit = it['faturamento'] / qtd if qtd else 0.0
            status, bg, fg = _status(mc_pct_it)
            alertas.append({
                'vendedor': it['vendedor'] or it['vendedor_raw'],
                'cliente':  it['cliente_nome'],
                'produto':  it['produto'],
                'qtd':      round(qtd, 3),
                'custo_unit': round(it['custo_unit'], 2),
                'venda_unit': round(venda_unit, 2),
                'mc_pct':   mc_pct_it,
                'status': status, 'bg': bg, 'fg': fg,
            })
            alertas_fat       += it['faturamento']
            alertas_mc_rs     += mc_rs_it
            alertas_custo_real += it['custo_total'] / DESP_ADM
    alertas.sort(key=lambda a: a['mc_pct'])

    # ---- impacto das vendas <-15% na margem ----------------------------
    pct_fat_alertas = alertas_fat / fat_total * 100 if fat_total else 0.0
    mc_rs_sem_alertas = mc_rs_total - alertas_mc_rs
    cr_sem_alertas    = custo_real_total - alertas_custo_real
    mc_pct_sem_alertas = mc_rs_sem_alertas / cr_sem_alertas * 100 if cr_sem_alertas else 0.0
    impacto_pp = mc_pct_sem_alertas - mc_pct_total

    impacto = {
        'fat_total':          round(fat_total, 2),
        'fat_alertas':        round(alertas_fat, 2),
        'pct_fat_alertas':    round(pct_fat_alertas, 2),
        'mc_rs_alertas':      round(alertas_mc_rs, 2),
        'mc_pct_total':       mc_pct_total,
        'mc_pct_sem_alertas': round(mc_pct_sem_alertas, 2),
        'impacto_pp':         round(impacto_pp, 2),
        'n_alertas':          len(alertas),
    }

    return {
        'data_emissao': parsed.get('data_emissao'),
        'periodo':      parsed.get('periodo'),
        'kpis': {
            'faturamento':    round(fat_total, 2),
            'mc_rs':          mc_rs_total,
            'mc_pct':         mc_pct_total,
            'caixas':         round(caixas_total, 3),
            'clientes':       clientes_distintos,
            'vendedores_ativos': vendedores_ativos,
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
    background: #F4F6F5; color: #1A1A1A; }
  header { background: var(--header-bg); color: var(--header-fg); padding: 20px 28px; }
  header h1 { margin: 0; font-size: 22px; }
  header p  { margin: 4px 0 0; font-size: 13px; opacity: 0.9; }
  main { padding: 24px 28px 48px; max-width: 1400px; margin: 0 auto; }
  .kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 28px; }
  .kpi  { background: #fff; border-radius: 8px; padding: 14px 12px; text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  .kpi .label { font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: .03em; }
  .kpi .value { font-size: 19px; font-weight: bold; color: var(--header-bg); margin-top: 4px; }
  section { background: #fff; border-radius: 8px; padding: 18px 20px; margin-bottom: 24px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  section h2 { margin: 0 0 14px; font-size: 16px; color: var(--header-bg); }
  .grid2 { display: grid; grid-template-columns: 1.4fr 1fr; gap: 20px; }
  .chart-wrap { position: relative; height: 320px; }
  .chart-wrap.small { height: 280px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 7px 10px; border-bottom: 1px solid #E5E5E5; text-align: left; white-space: nowrap; }
  th { background: var(--header-bg); color: var(--header-fg); font-weight: bold; position: sticky; top: 0; }
  td.num, th.num { text-align: right; }
  tr:hover td { background: #FAFAFA; }
  .badge { display: inline-block; padding: 2px 9px; border-radius: 10px; font-weight: bold; font-size: 12px; }
  .table-scroll { max-height: 480px; overflow-y: auto; border: 1px solid #EEE; border-radius: 6px; }
  .impacto-cards { display: grid; grid-template-columns: repeat(4,1fr); gap: 12px; }
  .impacto-card { border-radius: 8px; padding: 14px; text-align: center; }
  .impacto-card .label { font-size: 11px; color: #555; text-transform: uppercase; }
  .impacto-card .value { font-size: 20px; font-weight: bold; margin-top: 6px; }
  .impacto-note { margin-top: 14px; padding: 12px 16px; background: #FEF9C3; border-radius: 8px;
    font-size: 13px; color: #5a4a00; border-left: 4px solid #D4AC0D; }
  footer { text-align: center; font-size: 11px; color: #999; padding: 16px; }
  @media (max-width: 1000px) {
    .kpis { grid-template-columns: repeat(3,1fr); }
    .grid2 { grid-template-columns: 1fr; }
    .impacto-cards { grid-template-columns: repeat(2,1fr); }
  }
</style>
</head>
<body>
<header>
  <h1>Relatório Diário de Vendas OTHIL — Dashboard Gerencial</h1>
  <p>Dia: __DATA_EMISSAO__ &nbsp;&nbsp;|&nbsp;&nbsp; Período: __PERIODO__
     &nbsp;&nbsp;|&nbsp;&nbsp; <small>MC % = Margem de Contribuição (custo real = custo PDF ÷ 1,15)</small></p>
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
            <th class="num">MC %</th><th>Status</th>
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
        <div class="table-scroll" style="margin-top:12px;max-height:200px;">
          <table id="tabelaCategorias">
            <thead><tr>
              <th>Categoria</th><th class="num">Faturamento R$</th><th class="num">MC %</th>
            </tr></thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
      <div>
        <h2>Top 10 clientes do dia</h2>
        <div class="chart-wrap small"><canvas id="chartClientes"></canvas></div>
        <div class="table-scroll" style="margin-top:12px;max-height:200px;">
          <table id="tabelaClientes">
            <thead><tr>
              <th>Cliente</th><th class="num">Faturamento R$</th><th class="num">MC %</th>
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
          <th class="num">Custo Unit. R$</th><th class="num">Venda Unit. R$</th>
          <th class="num">MC %</th><th>Situação</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <section id="secaoImpacto">
    <h2>Impacto das vendas MC &lt;−15% na margem do dia</h2>
    <div class="impacto-cards" id="impactoCards"></div>
    <div class="impacto-note" id="impactoNota"></div>
  </section>

</main>
<footer>Gerado automaticamente a partir do PDF "Lucratividade por Vendedor-Cliente no Previsão" (Mercatus).
Margem de Contribuição: Custo real = Custo PDF ÷ 1,15.</footer>

<script>
const DADOS = __DADOS_JSON__;
const fmtMoney = v => 'R$ ' + v.toLocaleString('pt-BR', {minimumFractionDigits:2, maximumFractionDigits:2});
const fmtPct   = v => v.toLocaleString('pt-BR', {minimumFractionDigits:2, maximumFractionDigits:2}) + '%';
const fmtQty   = v => v.toLocaleString('pt-BR', {minimumFractionDigits:3, maximumFractionDigits:3});
const fmtPctSimple = v => v.toLocaleString('pt-BR', {minimumFractionDigits:1, maximumFractionDigits:1}) + '%';

function mcColor(pct) {
  if (pct >= 15) return {bg:'__VERDE_BG__',   fg:'__VERDE_FG__'};
  if (pct >= 0)  return {bg:'__AMARELO_BG__', fg:'__AMARELO_FG__'};
  return              {bg:'__VERMELHO_BG__', fg:'__VERMELHO_FG__'};
}

function montarKpis() {
  const k = DADOS.kpis;
  const cards = [
    ['Faturamento',       fmtMoney(k.faturamento)],
    ['MC R$',             fmtMoney(k.mc_rs)],
    ['MC %',              fmtPct(k.mc_pct)],
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
  tbody.innerHTML = DADOS.ranking.map(r => `
    <tr>
      <td><strong>${r.vendedor}</strong></td>
      <td class="num">${r.clientes}</td>
      <td class="num">${fmtQty(r.caixas)}</td>
      <td class="num">${fmtMoney(r.faturamento)}</td>
      <td class="num">${fmtMoney(r.mc_rs)}</td>
      <td class="num" style="background:${r.bg};color:${r.fg};font-weight:bold;">${fmtPct(r.mc_pct)}</td>
      <td><span class="badge" style="background:${r.bg};color:${r.fg};">${r.status}</span></td>
    </tr>`).join('');

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
  } catch(e) { console.error('Erro no gráfico vendedores:', e); }
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
        plugins: { legend:{position:'right', labels:{boxWidth:12,font:{size:11}}},
          tooltip:{ callbacks:{ label: ctx=>`${ctx.label}: ${fmtMoney(ctx.parsed)}` } } } },
    });
  } catch(e) { console.error('Erro no gráfico categorias:', e); }

  // Tabela de categorias
  const tbody = document.querySelector('#tabelaCategorias tbody');
  tbody.innerHTML = DADOS.categorias.map(c => {
    const col = mcColor(c.mc_pct);
    return `<tr>
      <td>${c.categoria}</td>
      <td class="num">${fmtMoney(c.faturamento)}</td>
      <td class="num" style="background:${col.bg};color:${col.fg};font-weight:bold;">${fmtPct(c.mc_pct)}</td>
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
          tooltip: { callbacks: { afterLabel: ctx => `MC %: ${fmtPct(DADOS.top_clientes[ctx.dataIndex].mc_pct)}` } } },
        scales: { x:{ beginAtZero:true, ticks:{ callback: v=>'R$ '+v.toLocaleString('pt-BR') } } } },
    });
  } catch(e) { console.error('Erro no gráfico clientes:', e); }

  // Tabela de clientes
  const tbody = document.querySelector('#tabelaClientes tbody');
  tbody.innerHTML = DADOS.top_clientes.map(c => {
    const col = mcColor(c.mc_pct);
    return `<tr>
      <td>${c.cliente}</td>
      <td class="num">${fmtMoney(c.faturamento)}</td>
      <td class="num" style="background:${col.bg};color:${col.fg};font-weight:bold;">${fmtPct(c.mc_pct)}</td>
    </tr>`;
  }).join('');
}

function montarAlertas() {
  document.getElementById('qtdAlertas').textContent = DADOS.alertas.length;
  const tbody = document.querySelector('#tabelaAlertas tbody');
  tbody.innerHTML = DADOS.alertas.map(a => `
    <tr>
      <td>${a.vendedor}</td><td>${a.cliente}</td><td>${a.produto}</td>
      <td class="num">${fmtQty(a.qtd)}</td>
      <td class="num">${fmtMoney(a.custo_unit)}</td>
      <td class="num">${fmtMoney(a.venda_unit)}</td>
      <td class="num" style="background:${a.bg};color:${a.fg};font-weight:bold;">${fmtPct(a.mc_pct)}</td>
      <td><span class="badge" style="background:${a.bg};color:${a.fg};">${a.status}</span></td>
    </tr>`).join('');
}

function montarImpacto() {
  const imp = DADOS.impacto;
  if (!imp || imp.n_alertas === 0) {
    document.getElementById('secaoImpacto').style.display = 'none';
    return;
  }
  const mcRsNeg = imp.mc_rs_alertas < 0;
  const cards = [
    { label:'Faturamento <−15%', value: fmtMoney(imp.fat_alertas),
      bg: '__VERMELHO_BG__', fg: '__VERMELHO_FG__' },
    { label:'% do Fat. Total', value: fmtPctSimple(imp.pct_fat_alertas),
      bg: '__AMARELO_BG__', fg: '__AMARELO_FG__' },
    { label:'MC R$ acumulada', value: fmtMoney(imp.mc_rs_alertas),
      bg: mcRsNeg ? '__VERMELHO_BG__' : '__VERDE_BG__',
      fg: mcRsNeg ? '__VERMELHO_FG__' : '__VERDE_FG__' },
    { label:'Impacto na MC', value: (imp.impacto_pp > 0 ? '+' : '') + fmtPctSimple(imp.impacto_pp) + ' pp',
      bg: '__AMARELO_BG__', fg: '__AMARELO_FG__' },
  ];
  document.getElementById('impactoCards').innerHTML = cards.map(c =>
    `<div class="impacto-card" style="background:${c.bg};color:${c.fg};">
      <div class="label">${c.label}</div>
      <div class="value">${c.value}</div>
    </div>`
  ).join('');

  const direcao = imp.impacto_pp > 0 ? 'subiria' : 'cairia';
  document.getElementById('impactoNota').innerHTML =
    `<strong>Análise:</strong> As ${imp.n_alertas} vendas com MC abaixo de −15% representam
    <strong>${fmtPctSimple(imp.pct_fat_alertas)}</strong> do faturamento do dia
    (${fmtMoney(imp.fat_alertas)}) e acumulam uma MC de <strong>${fmtMoney(imp.mc_rs_alertas)}</strong>.
    Sem essas vendas, a MC do dia ${direcao} de
    <strong>${fmtPct(imp.mc_pct_total)}</strong> para
    <strong>${fmtPct(imp.mc_pct_sem_alertas)}</strong>
    (impacto de <strong>${imp.impacto_pp > 0 ? '+' : ''}${fmtPctSimple(imp.impacto_pp)} pp</strong>).`;
}

[montarKpis, montarRanking, montarCategorias, montarClientes, montarAlertas, montarImpacto].forEach(fn => {
  try { fn(); } catch(e) { console.error('Erro ao montar seção:', e); }
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
