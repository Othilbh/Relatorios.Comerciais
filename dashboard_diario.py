"""Gera o dashboard HTML gerencial 'dashboard_gerencial_othil_DDMMAAAA.html'
a partir do resultado de parsers_diario.parse_relatorio_diario().

Arquivo único, 100% autocontido (Chart.js embutido inline, sem depender de
nenhum CDN externo — funciona até sem acesso à internet), com:
  - KPIs do dia + ranking de vendedores (gráfico de barras)
  - Faturamento por categoria de produto (rosca, via categorias.map_categoria)
  - Top 10 clientes do dia (consolidados por código de cliente)
  - Lista de alertas <-15% (mesmo conteúdo da aba Alertas_<-15% do Excel)

Mesma paleta de cores do Excel (verde/amarelo/vermelho) para manter a leitura
consistente entre os dois arquivos do módulo.
"""
import json
import os
from categorias import map_categoria

_CHARTJS_PATH = os.path.join(os.path.dirname(__file__), 'chart_umd.js')
with open(_CHARTJS_PATH, encoding='utf-8') as _f:
    _CHARTJS_SRC = _f.read()

VERDE_BG, VERDE_FG = '#D8EFE3', '#1B4332'
AMARELO_BG, AMARELO_FG = '#FEF9C3', '#7D6608'
VERMELHO_BG, VERMELHO_FG = '#FADADD', '#7A1F2B'
HEADER_BG, HEADER_FG = '#2D6A4F', '#FFFFFF'


def _pct(faturamento, custo):
    return (faturamento - custo) / custo * 100 if custo else 0.0


def _status(pct):
    if pct >= 15:
        return 'OK', VERDE_BG, VERDE_FG
    if pct >= 0:
        return 'Atenção', AMARELO_BG, AMARELO_FG
    return 'Crítico', VERMELHO_BG, VERMELHO_FG


def _montar_dados(parsed):
    itens = parsed['itens']

    faturamento_total = sum(it['faturamento'] for it in itens)
    custo_total = sum(it['custo_total'] for it in itens)
    caixas_total = sum(it['qtd'] for it in itens)
    resultado_total = faturamento_total - custo_total
    resultado_pct_total = _pct(faturamento_total, custo_total)
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
        fat = sum(it['faturamento'] for it in d['itens'])
        custo = sum(it['custo_total'] for it in d['itens'])
        caixas = sum(it['qtd'] for it in d['itens'])
        pct = _pct(fat, custo)
        status, bg, fg = _status(pct)
        ranking.append({
            'vendedor': vname, 'clientes': len(d['clientes']), 'caixas': round(caixas, 3),
            'faturamento': round(fat, 2), 'custo': round(custo, 2),
            'resultado': round(fat - custo, 2), 'pct': round(pct, 2),
            'status': status, 'bg': bg, 'fg': fg,
        })
    ranking.sort(key=lambda r: -r['faturamento'])
    vendedores_ativos = len(ranking)

    # ---- faturamento por categoria -------------------------------------
    por_categoria = {}
    for it in itens:
        cat = map_categoria(it['produto'])
        por_categoria[cat] = por_categoria.get(cat, 0.0) + it['faturamento']
    categorias_lista = sorted(
        ({'categoria': k, 'faturamento': round(v, 2)} for k, v in por_categoria.items()),
        key=lambda x: -x['faturamento'],
    )

    # ---- top 10 clientes do dia (consolidado por código) ----------------
    por_cliente = {}
    for it in itens:
        cod = it['cliente_codigo']
        d = por_cliente.setdefault(cod, {'nome': it['cliente_nome'], 'fat': 0.0, 'custo': 0.0})
        d['fat'] += it['faturamento']
        d['custo'] += it['custo_total']
    top_clientes = sorted(
        ({'cliente': v['nome'], 'codigo': k, 'faturamento': round(v['fat'], 2),
          'pct': round(_pct(v['fat'], v['custo']), 2)} for k, v in por_cliente.items()),
        key=lambda x: -x['faturamento'],
    )[:10]

    # ---- alertas <-15% (mesma regra/ordem da aba Alertas_<-15% do Excel) --
    alertas = []
    for it in itens:
        pct = _pct(it['faturamento'], it['custo_total'])
        if pct < -15:
            status, bg, fg = _status(pct)
            alertas.append({
                'vendedor': it['vendedor'] or it['vendedor_raw'],
                'cliente': it['cliente_nome'], 'produto': it['produto'],
                'qtd': round(it['qtd'], 3), 'faturamento': round(it['faturamento'], 2),
                'custo': round(it['custo_total'], 2),
                'resultado': round(it['faturamento'] - it['custo_total'], 2),
                'pct': round(pct, 2), 'status': status, 'bg': bg, 'fg': fg,
            })
    alertas.sort(key=lambda a: a['pct'])

    return {
        'data_emissao': parsed.get('data_emissao'),
        'periodo': parsed.get('periodo'),
        'kpis': {
            'faturamento': round(faturamento_total, 2),
            'resultado_rs': round(resultado_total, 2),
            'resultado_pct': round(resultado_pct_total, 2),
            'caixas': round(caixas_total, 3),
            'clientes': clientes_distintos,
            'vendedores_ativos': vendedores_ativos,
        },
        'ranking': ranking,
        'categorias': categorias_lista,
        'top_clientes': top_clientes,
        'alertas': alertas,
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
  body {
    font-family: Arial, Helvetica, sans-serif; margin: 0; padding: 0;
    background: #F4F6F5; color: #1A1A1A;
  }
  header {
    background: var(--header-bg); color: var(--header-fg);
    padding: 20px 28px;
  }
  header h1 { margin: 0; font-size: 22px; }
  header p { margin: 4px 0 0; font-size: 13px; opacity: 0.9; }
  main { padding: 24px 28px 48px; max-width: 1280px; margin: 0 auto; }
  .kpis {
    display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 28px;
  }
  .kpi {
    background: #fff; border-radius: 8px; padding: 14px 12px; text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }
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
  footer { text-align: center; font-size: 11px; color: #999; padding: 16px; }
  @media (max-width: 1000px) {
    .kpis { grid-template-columns: repeat(3, 1fr); }
    .grid2 { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<header>
  <h1>Relatório Diário de Vendas OTHIL — Dashboard Gerencial</h1>
  <p>Dia: __DATA_EMISSAO__ &nbsp;&nbsp;|&nbsp;&nbsp; Período: __PERIODO__</p>
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
            <th class="num">Faturamento R$</th><th class="num">Resultado R$</th>
            <th class="num">Resultado %</th><th>Status</th>
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
      </div>
      <div>
        <h2>Top 10 clientes do dia</h2>
        <div class="chart-wrap small"><canvas id="chartClientes"></canvas></div>
      </div>
    </div>
  </section>

  <section>
    <h2>Alertas — Resultado % abaixo de -15% (<span id="qtdAlertas"></span> itens, pior para o melhor)</h2>
    <div class="table-scroll">
      <table id="tabelaAlertas">
        <thead><tr>
          <th>Vendedor</th><th>Cliente</th><th>Produto</th><th class="num">Qtd</th>
          <th class="num">Faturamento R$</th><th class="num">Custo R$</th>
          <th class="num">Resultado R$</th><th class="num">Resultado %</th><th>Situação</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

</main>
<footer>Gerado automaticamente a partir do PDF "Lucratividade por Vendedor-Cliente no Previsão" (Mercatus) do dia. Categorização por palavra-chave; consolidação de clientes por código Mercatus.</footer>

<script>
const DADOS = __DADOS_JSON__;
const fmtMoney = v => 'R$ ' + v.toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const fmtPct = v => v.toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '%';
const fmtQty = v => v.toLocaleString('pt-BR', {minimumFractionDigits: 3, maximumFractionDigits: 3});

function montarKpis() {
  const k = DADOS.kpis;
  const cards = [
    ['Faturamento', fmtMoney(k.faturamento)],
    ['Resultado R$', fmtMoney(k.resultado_rs)],
    ['Resultado %', fmtPct(k.resultado_pct)],
    ['Caixas', fmtQty(k.caixas)],
    ['Clientes', k.clientes],
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
      <td class="num">${fmtMoney(r.resultado)}</td>
      <td class="num" style="background:${r.bg};color:${r.fg};font-weight:bold;">${fmtPct(r.pct)}</td>
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
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { callback: v => 'R$ ' + v.toLocaleString('pt-BR') } } } },
    });
  } catch (e) { console.error('Erro no gráfico de vendedores:', e); }
}

function montarCategorias() {
  const palette = ['__HEADER_BG__', '#52B788', '#95D5B2', '#74A892', '#B7E4C7',
                    '#40916C', '#2D6A4F', '#1B4332', '#84A98C', '#CAD2C5',
                    '#A3B18A', '#588157', '#3A5A40', '#344E41', '#6B9080',
                    '#A4C3B2', '#EAF4F4', '#CCE3DE'];
  try {
    new Chart(document.getElementById('chartCategorias'), {
      type: 'doughnut',
      data: {
        labels: DADOS.categorias.map(c => c.categoria),
        datasets: [{ data: DADOS.categorias.map(c => c.faturamento),
          backgroundColor: DADOS.categorias.map((_, i) => palette[i % palette.length]) }],
      },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'right', labels: { boxWidth: 12, font: { size: 11 } } },
          tooltip: { callbacks: { label: ctx => `${ctx.label}: ${fmtMoney(ctx.parsed)}` } } } },
    });
  } catch (e) { console.error('Erro no gráfico de categorias:', e); }
}

function montarClientes() {
  try {
    new Chart(document.getElementById('chartClientes'), {
      type: 'bar',
      data: {
        labels: DADOS.top_clientes.map(c => c.cliente),
        datasets: [{ label: 'Faturamento R$', data: DADOS.top_clientes.map(c => c.faturamento),
          backgroundColor: '#40916C' }],
      },
      options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true, ticks: { callback: v => 'R$ ' + v.toLocaleString('pt-BR') } } } },
    });
  } catch (e) { console.error('Erro no gráfico de clientes:', e); }
}

function montarAlertas() {
  document.getElementById('qtdAlertas').textContent = DADOS.alertas.length;
  const tbody = document.querySelector('#tabelaAlertas tbody');
  tbody.innerHTML = DADOS.alertas.map(a => `
    <tr>
      <td>${a.vendedor}</td><td>${a.cliente}</td><td>${a.produto}</td>
      <td class="num">${fmtQty(a.qtd)}</td>
      <td class="num">${fmtMoney(a.faturamento)}</td>
      <td class="num">${fmtMoney(a.custo)}</td>
      <td class="num">${fmtMoney(a.resultado)}</td>
      <td class="num" style="background:${a.bg};color:${a.fg};font-weight:bold;">${fmtPct(a.pct)}</td>
      <td><span class="badge" style="background:${a.bg};color:${a.fg};">${a.status}</span></td>
    </tr>`).join('');
}

[montarKpis, montarRanking, montarCategorias, montarClientes, montarAlertas].forEach(fn => {
  try { fn(); } catch (e) { console.error('Erro ao montar seção do dashboard:', e); }
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
            .replace('__PERIODO__', dados['periodo'] or '-')
            .replace('__VERDE_BG__', VERDE_BG).replace('__VERDE_FG__', VERDE_FG)
            .replace('__AMARELO_BG__', AMARELO_BG).replace('__AMARELO_FG__', AMARELO_FG)
            .replace('__VERMELHO_BG__', VERMELHO_BG).replace('__VERMELHO_FG__', VERMELHO_FG)
            .replace('__HEADER_BG__', HEADER_BG).replace('__HEADER_FG__', HEADER_FG)
            .replace('__DADOS_JSON__', json.dumps(dados, ensure_ascii=False)))
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return output_path
