"""OTHIL — Módulo Metas Semanais e Responsáveis

Faz upload dos PDFs de Estoque Físico e de Lucratividade por
Vendedor, permite configurar os produtos da semana (nome + códigos/SKU) e os
percentuais de cada vendedor, calcula Meta/Vendido/Falta/% e gera os 3 PDFs
de saída (relatório por vendedor, dashboard e resumo geral).
"""
import io
import json
import math
import os
import datetime
import streamlit as st
import pandas as pd

from parsers import parse_estoque, parse_vendas, normalize_codigo
from parsers_vendedor import parse_totais_vendedor
from calc import compute_metas, VENDEDORES_PADRAO, parse_codigos_input, map_vendedor, codigo_matches
from pdfgen import generate_relatorio_vendedor, generate_dashboard, generate_resumo_geral
import storage

CONFIG_PATH = 'config_semanal.json'
_FECHAMENTOS_DIR = os.path.join(os.path.dirname(__file__), '..', 'gerencia_data', 'fechamentos')

# ---------------------------------------------------------------------------
# Persistência da configuração da semana
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    'produtos': [
        {'nome': 'Melão Gaia', 'codigos_texto': '3102006*', 'estoque': 0},
        {'nome': 'Goiaba', 'codigos_texto': '300200208,300200203', 'estoque': 0},
    ],
    'vendedor_pcts': dict(VENDEDORES_PADRAO),
}


def load_config():
    remote = storage.load_config_remote()
    if remote is not None:
        return remote
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg, show_feedback=True):
    ok, motivo = storage.save_config_remote(cfg)
    if show_feedback:
        if ok:
            st.success('Configuração salva — vai continuar disponível a semana toda.')
        else:
            st.warning(f'Não foi possível salvar de forma permanente: {motivo}')
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return ok


# ---------------------------------------------------------------------------
# Fechamento helpers
# ---------------------------------------------------------------------------

def _slug_semana(data: datetime.date) -> str:
    iso = data.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _label_semana(slug: str) -> str:
    try:
        year, week = slug.split('-W')
        return f"Semana {int(week):02d} / {year}"
    except Exception:
        return slug


def _salvar_fechamento(resultados: list, totais_rs: dict, periodo: str, slug: str):
    os.makedirs(_FECHAMENTOS_DIR, exist_ok=True)
    payload = {
        'slug': slug,
        'periodo': periodo,
        'gerado_em': datetime.datetime.now().isoformat(),
        'produtos': resultados,
        'totais_rs': totais_rs,
    }
    path = os.path.join(_FECHAMENTOS_DIR, f'{slug}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _listar_fechamentos():
    os.makedirs(_FECHAMENTOS_DIR, exist_ok=True)
    items = []
    for fname in sorted(os.listdir(_FECHAMENTOS_DIR), reverse=True):
        if not fname.endswith('.json'):
            continue
        try:
            with open(os.path.join(_FECHAMENTOS_DIR, fname), 'r', encoding='utf-8') as f:
                data = json.load(f)
            items.append((fname.replace('.json', ''), data))
        except Exception:
            pass
    return items


# ---------------------------------------------------------------------------
# Diagnóstico de códigos
# ---------------------------------------------------------------------------

def _diagnostico_codigos(vendas_rows: list, produtos_config: list) -> list:
    """Retorna lista de códigos do PDF que não casaram com nenhum produto configurado.

    Cada item: {'Código', 'CX não reconhecidas', 'Vendedores'}
    Ordenado por volume decrescente.
    """
    from collections import defaultdict
    agg = defaultdict(lambda: {'qtde': 0.0, 'vendedores': set()})
    for row in vendas_rows:
        cn = normalize_codigo(row['codigo'])
        matched = any(
            codigo_matches(cn, e)
            for p in produtos_config
            for e in p['codigos']
        )
        if not matched:
            agg[row['codigo']]['qtde']      += row['qtde_vendida']
            agg[row['codigo']]['vendedores'].add(
                map_vendedor(row['vendedor']) or row['vendedor']
            )
    if not agg:
        return []
    return [
        {
            'Código': cod,
            'CX não reconhecidas': dados['qtde'],
            'Vendedores': ', '.join(sorted(v for v in dados['vendedores'] if v)),
        }
        for cod, dados in sorted(agg.items(), key=lambda x: -x[1]['qtde'])
    ]


# ---------------------------------------------------------------------------
# On Track helpers
# ---------------------------------------------------------------------------

def _on_track_status(atingido: float, dia: int, total_dias: int = 5):
    """Retorna (emoji, label, hex_color)."""
    if dia <= 0:
        if atingido >= 0.80:
            return '🟢', 'On Track', '#2D6A4F'
        elif atingido >= 0.50:
            return '🟡', 'Atenção', '#B8860B'
        else:
            return '🔴', 'Atrasado', '#C00000'
    expected = dia / total_dias
    ratio = atingido / expected if expected > 0 else 0
    if ratio >= 0.85:
        return '🟢', 'On Track', '#2D6A4F'
    elif ratio >= 0.55:
        return '🟡', 'Atenção', '#B8860B'
    else:
        return '🔴', 'Atrasado', '#C00000'


# ---------------------------------------------------------------------------
# Render: On Track
# ---------------------------------------------------------------------------

def _render_on_track():
    if 'resultados' not in st.session_state:
        st.info('Calcule as metas na aba **⚙️ Configuração** primeiro.')
        return

    resultados = st.session_state['resultados']
    totais_rs  = st.session_state.get('totais_rs', {})

    st.header('📊 Dashboard On Track')

    col_dia, col_sort = st.columns([2, 3])
    with col_dia:
        dia_semana = st.slider(
            'Dia da semana atual',
            min_value=1, max_value=5,
            value=min(datetime.date.today().weekday() + 1, 5),
            format='Dia %d de 5',
            help='Segunda=1  Terça=2  Quarta=3  Quinta=4  Sexta=5',
            key='ont_dia',
        )
    with col_sort:
        sort_by = st.selectbox(
            'Ordenar vendedores por',
            ['Maior % atingido', 'Maior faturamento R$', 'Maior volume CX', 'Alfabético'],
            key='ont_sort',
        )

    st.divider()

    # ── KPIs Totais ───────────────────────────────────────────────────────
    total_meta   = sum(l['meta']    for r in resultados for l in r['linhas'])
    total_vend   = sum(l['vendido'] for r in resultados for l in r['linhas'])
    total_falta  = total_meta - total_vend
    ating_geral  = total_vend / total_meta if total_meta else 0
    proj_cx      = math.ceil(total_vend / dia_semana * 5) if dia_semana > 0 else 0
    delta_proj   = proj_cx - total_meta

    on_em, on_lb, on_cor = _on_track_status(ating_geral, dia_semana)

    st.markdown(
        f'<div style="background:{on_cor}; color:white; padding:0.55rem 1.2rem; '
        f'border-radius:10px; display:inline-block; margin-bottom:0.8rem; '
        f'font-size:1.05rem; font-weight:600;">'
        f'{on_em} {on_lb} — {ating_geral*100:.1f}% atingido (dia {dia_semana}/5)'
        f'</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric('Meta total (cx)',  f'{total_meta:,.0f}')
    c2.metric('Vendido (cx)',     f'{total_vend:,.0f}')
    c3.metric('% Atingido',      f'{ating_geral*100:.1f}%')
    c4.metric('Falta (cx)',      f'{total_falta:,.0f}')
    c5.metric(
        'Projeção semana (cx)',   f'{proj_cx:,.0f}',
        delta=f'{delta_proj:+,.0f} vs meta',
        delta_color='normal',
    )

    # R$ gerais
    tg = totais_rs.get('total_geral', {})
    if tg:
        st.subheader('Faturamento Geral (R$)')
        r1, r2, r3 = st.columns(3)
        r1.metric('Faturamento', f"R$ {tg.get('fat', 0):,.2f}")
        r2.metric('MC R$',       f"R$ {tg.get('mc_rs', 0):,.2f}")
        r3.metric('MC %',        f"{tg.get('mc_pct', 0):.2f}%")

    st.divider()

    # ── On Track por Vendedor ─────────────────────────────────────────────
    st.subheader('On Track por Vendedor')

    vend_agg = {}
    for r in resultados:
        for l in r['linhas']:
            v = l['vendedor']
            if v not in vend_agg:
                vend_agg[v] = {'meta': 0, 'vendido': 0}
            vend_agg[v]['meta']    += l['meta']
            vend_agg[v]['vendido'] += l['vendido']

    vend_rs = totais_rs.get('vendedores', {})
    rows = []
    for v, ag in vend_agg.items():
        meta_v = ag['meta']
        vend_v = ag['vendido']
        atg_v  = vend_v / meta_v if meta_v else 0
        proj_v = math.ceil(vend_v / dia_semana * 5) if dia_semana > 0 else 0
        em, lb, _ = _on_track_status(atg_v, dia_semana)
        rs = vend_rs.get(v, {})
        rows.append({
            'Vendedor':     v,
            'Meta (cx)':    meta_v,
            'Vendido (cx)': vend_v,
            '% Atingido':   atg_v,
            'Falta (cx)':   meta_v - vend_v,
            'Projeção (cx)': proj_v,
            'Fat R$':       rs.get('fat'),
            'MC R$':        rs.get('mc_rs'),
            'MC %':         rs.get('mc_pct'),
            'Status':       f'{em} {lb}',
        })

    if sort_by == 'Maior % atingido':
        rows.sort(key=lambda r: r['% Atingido'], reverse=True)
    elif sort_by == 'Maior faturamento R$':
        rows.sort(key=lambda r: (r['Fat R$'] or 0), reverse=True)
    elif sort_by == 'Maior volume CX':
        rows.sort(key=lambda r: r['Vendido (cx)'], reverse=True)
    else:
        rows.sort(key=lambda r: r['Vendedor'])

    df_vend = pd.DataFrame(rows)
    df_vend['% Atingido']    = df_vend['% Atingido'].map(lambda x: f'{x*100:.1f}%')
    df_vend['Meta (cx)']     = df_vend['Meta (cx)'].map(lambda x: f'{x:,.0f}')
    df_vend['Vendido (cx)']  = df_vend['Vendido (cx)'].map(lambda x: f'{x:,.0f}')
    df_vend['Falta (cx)']    = df_vend['Falta (cx)'].map(lambda x: f'{x:,.0f}')
    df_vend['Projeção (cx)'] = df_vend['Projeção (cx)'].map(lambda x: f'{x:,.0f}')
    df_vend['Fat R$']  = df_vend['Fat R$'].map(lambda x: f'R$ {x:,.2f}' if x is not None else '—')
    df_vend['MC R$']   = df_vend['MC R$'].map(lambda x: f'R$ {x:,.2f}' if x is not None else '—')
    df_vend['MC %']    = df_vend['MC %'].map(lambda x: f'{x:.2f}%' if x is not None else '—')

    st.dataframe(df_vend, use_container_width=True, hide_index=True)

    st.divider()

    # ── Detalhamento por Produto ──────────────────────────────────────────
    st.subheader('Detalhamento por Produto')
    for r in resultados:
        prio  = r.get('prioridade', 'Normal')
        badge = f' {prio}' if prio != 'Normal' else ''
        p_meta = sum(l['meta']    for l in r['linhas'])
        p_vend = sum(l['vendido'] for l in r['linhas'])
        p_atg  = p_vend / p_meta if p_meta else 0
        p_em, p_lb, _ = _on_track_status(p_atg, dia_semana)

        with st.expander(
            f"{r['produto']}{badge} — {r['estoque_total']:.0f} cx  |  "
            f"{p_vend:,.0f}/{p_meta:,.0f} cx ({p_atg*100:.1f}%)  {p_em} {p_lb}"
        ):
            df_prod = pd.DataFrame([{
                'Vendedor':     l['vendedor'],
                'Meta (cx)':   f"{l['meta']:,.0f}",
                'Vendido (cx)': f"{l['vendido']:,.0f}",
                'Falta (cx)':  f"{l['falta']:,.0f}",
                '% Atingido':  f"{l['atingido']*100:.1f}%",
            } for l in r['linhas']])
            st.dataframe(df_prod, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Render: Fechamento Semanal
# ---------------------------------------------------------------------------

def _render_resumo_geral_inline(resultados: list, totais_rs: dict, dia: int = 5):
    """Exibe o Resumo Geral (On Track + matriz produto × vendedor) inline."""
    if not resultados:
        return

    vendedores = [l['vendedor'] for l in resultados[0]['linhas']]

    # ── On Track KPIs ────────────────────────────────────────────────────
    total_meta  = sum(l['meta']    for r in resultados for l in r['linhas'])
    total_vend  = sum(l['vendido'] for r in resultados for l in r['linhas'])
    ating_geral = total_vend / total_meta if total_meta else 0
    proj_cx     = math.ceil(total_vend / dia * 5) if dia > 0 else 0
    on_em, on_lb, on_cor = _on_track_status(ating_geral, dia)

    st.markdown(
        f'<div style="background:{on_cor}; color:white; padding:0.45rem 1rem; '
        f'border-radius:8px; display:inline-block; margin-bottom:0.6rem; font-weight:600;">'
        f'{on_em} {on_lb} — {ating_geral*100:.1f}%</div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric('Meta total (cx)',    f'{total_meta:,.0f}')
    c2.metric('Vendido (cx)',       f'{total_vend:,.0f}')
    c3.metric('% Atingido',        f'{ating_geral*100:.1f}%')
    c4.metric('Falta (cx)',        f'{total_meta - total_vend:,.0f}')
    c5.metric('Projeção semana (cx)', f'{proj_cx:,.0f}')

    tg = totais_rs.get('total_geral', {})
    if tg:
        f1, f2, f3 = st.columns(3)
        f1.metric('Faturamento', f"R$ {tg.get('fat', 0):,.2f}")
        f2.metric('MC R$',       f"R$ {tg.get('mc_rs', 0):,.2f}")
        f3.metric('MC %',        f"{tg.get('mc_pct', 0):.2f}%")

    st.divider()

    # ── On Track por Vendedor ─────────────────────────────────────────────
    st.markdown('**On Track por Vendedor**')
    vend_agg = {}
    for r in resultados:
        for l in r['linhas']:
            v = l['vendedor']
            if v not in vend_agg:
                vend_agg[v] = {'meta': 0, 'vendido': 0}
            vend_agg[v]['meta']    += l['meta']
            vend_agg[v]['vendido'] += l['vendido']

    vend_rs = totais_rs.get('vendedores', {})
    vrows = []
    for v, ag in vend_agg.items():
        meta_v = ag['meta']
        vend_v = ag['vendido']
        atg_v  = vend_v / meta_v if meta_v else 0
        proj_v = math.ceil(vend_v / dia * 5) if dia > 0 else 0
        em, lb, _ = _on_track_status(atg_v, dia)
        rs = vend_rs.get(v, {})
        vrows.append({
            'Vendedor':     v,
            'Meta (cx)':   f'{meta_v:,.0f}',
            'Vendido (cx)': f'{vend_v:,.0f}',
            '% Atingido':  f'{atg_v*100:.1f}%',
            'Projeção (cx)': f'{proj_v:,.0f}',
            'Fat R$':      f"R$ {rs['fat']:,.2f}" if rs.get('fat') is not None else '—',
            'MC %':        f"{rs['mc_pct']:.2f}%" if rs.get('mc_pct') is not None else '—',
            'Status':      f'{em} {lb}',
        })
    st.dataframe(pd.DataFrame(vrows), use_container_width=True, hide_index=True)

    st.divider()

    # ── Resumo Geral: Matriz Produto × Vendedor ───────────────────────────
    st.markdown('**Resumo Geral — Matriz Produto × Vendedor**')

    _PRIO_ORDER = {'🚨 Grande Urgência': 0, '🔥 Alta Prioridade': 1, 'Normal': 2}
    grupos_prio: dict = {}
    for r in resultados:
        prio = r.get('prioridade', 'Normal')
        grupos_prio.setdefault(prio, []).append(r)

    for prio_key in ['🚨 Grande Urgência', '🔥 Alta Prioridade', 'Normal']:
        grupo = grupos_prio.get(prio_key)
        if not grupo:
            continue
        prio_label = prio_key.replace('🚨 ', '').replace('🔥 ', '')
        st.markdown(f'*{prio_label}*')

        rows_m = []
        for r in grupo:
            row = {'Produto': r['produto'], 'Qtde': f"{r['estoque_total']:.0f}"}
            p_meta = 0; p_vend = 0
            for l in r['linhas']:
                row[l['vendedor']] = f"{l['vendido']:.0f}/{l['meta']:.0f} ({l['atingido']*100:.0f}%)"
                p_meta += l['meta']; p_vend += l['vendido']
            row['TOTAL'] = f"{p_vend:.0f}/{p_meta:.0f} ({p_vend/p_meta*100:.0f}%)" if p_meta else '—'
            rows_m.append(row)

        # Linha de subtotal
        sub = {'Produto': 'SUBTOTAL', 'Qtde': f"{sum(r['estoque_total'] for r in grupo):.0f}"}
        for v in vendedores:
            sv = sum(l['vendido'] for r in grupo for l in r['linhas'] if l['vendedor'] == v)
            sm = sum(l['meta']    for r in grupo for l in r['linhas'] if l['vendedor'] == v)
            sub[v] = f"{sv:.0f}/{sm:.0f} ({sv/sm*100:.0f}%)" if sm else '—'
        gv = sum(l['vendido'] for r in grupo for l in r['linhas'])
        gm = sum(l['meta']    for r in grupo for l in r['linhas'])
        sub['TOTAL'] = f"{gv:.0f}/{gm:.0f} ({gv/gm*100:.0f}%)" if gm else '—'
        rows_m.append(sub)

        st.dataframe(pd.DataFrame(rows_m), use_container_width=True, hide_index=True)

    # Total Geral
    tot = {'Produto': 'TOTAL GERAL', 'Qtde': f"{sum(r['estoque_total'] for r in resultados):.0f}"}
    for v in vendedores:
        tv = sum(l['vendido'] for r in resultados for l in r['linhas'] if l['vendedor'] == v)
        tm = sum(l['meta']    for r in resultados for l in r['linhas'] if l['vendedor'] == v)
        tot[v] = f"{tv:.0f}/{tm:.0f} ({tv/tm*100:.0f}%)" if tm else '—'
    gv_all = sum(l['vendido'] for r in resultados for l in r['linhas'])
    gm_all = sum(l['meta']    for r in resultados for l in r['linhas'])
    tot['TOTAL'] = f"{gv_all:.0f}/{gm_all:.0f} ({gv_all/gm_all*100:.0f}%)" if gm_all else '—'
    st.dataframe(pd.DataFrame([tot]), use_container_width=True, hide_index=True)


def _render_fechamento_semanal():
    st.header('📅 Fechamento Semanal')

    resultados = st.session_state.get('resultados')
    cfg_atual  = st.session_state.get('config', {})
    periodo    = cfg_atual.get('periodo', '')

    # ── Fechar semana atual ──────────────────────────────────────────────
    if resultados:
        slug_atual  = _slug_semana(datetime.date.today())
        label_atual = _label_semana(slug_atual)

        st.subheader(f'Fechar: {label_atual}')
        st.caption(f'Período configurado: **{periodo or "(não informado)"}**')

        # Dia da semana (para o On Track inline)
        dia_fech = st.slider(
            'Dia da semana (para projeção)', 1, 5,
            value=min(datetime.date.today().weekday() + 1, 5),
            format='Dia %d de 5',
            key='fech_dia',
        )

        totais_rs = st.session_state.get('totais_rs', {})

        # Resumo inline completo
        _render_resumo_geral_inline(resultados, totais_rs, dia_fech)

        st.divider()
        if st.button('💾 Fechar Semana e Salvar no Histórico', type='primary', key='btn_fechar'):
            try:
                _salvar_fechamento(resultados, totais_rs, periodo, slug_atual)
                st.success(f'✅ {label_atual} salvo no histórico da Gerência.')
                st.rerun()
            except Exception as e:
                st.error(f'Erro ao salvar: {e}')
    else:
        st.info('Calcule as metas na aba **⚙️ Configuração** para poder fechar a semana.')

    st.divider()

    # ── Histórico ────────────────────────────────────────────────────────
    st.subheader('Histórico de Fechamentos Salvos')
    historico = _listar_fechamentos()

    if not historico:
        st.info('Nenhum fechamento salvo ainda. Clique em "Fechar Semana" após calcular as metas.')
        return

    slugs  = [s for s, _ in historico]
    labels = [f"{_label_semana(s)}  —  {d.get('periodo', '-')}" for s, d in historico]

    escolha = st.selectbox('Selecionar semana:', labels, key='fech_hist_sel')
    idx   = labels.index(escolha)
    dados = historico[idx][1]

    gerado = dados.get('gerado_em', '')[:16].replace('T', ' ')
    st.caption(f"Período: {dados.get('periodo', '-')}  |  Salvo em: {gerado}")

    prods      = dados.get('produtos', [])
    h_meta     = sum(l['meta']    for r in prods for l in r.get('linhas', []))
    h_vend     = sum(l['vendido'] for r in prods for l in r.get('linhas', []))
    h_atg      = h_vend / h_meta if h_meta else 0

    h1, h2, h3 = st.columns(3)
    h1.metric('Meta (cx)',  f'{h_meta:,.0f}')
    h2.metric('Vendido (cx)', f'{h_vend:,.0f}')
    h3.metric('% Atingido', f'{h_atg*100:.1f}%')

    tg_h = dados.get('totais_rs', {}).get('total_geral', {})
    if tg_h:
        f1, f2, f3 = st.columns(3)
        f1.metric('Faturamento', f"R$ {tg_h.get('fat', 0):,.2f}")
        f2.metric('MC R$',      f"R$ {tg_h.get('mc_rs', 0):,.2f}")
        f3.metric('MC %',       f"{tg_h.get('mc_pct', 0):.2f}%")

    # Tabela por produto
    prows = []
    for r in prods:
        pm = sum(l['meta']    for l in r.get('linhas', []))
        pv = sum(l['vendido'] for l in r.get('linhas', []))
        pa = pv / pm if pm else 0
        prows.append({
            'Produto':      r.get('produto', ''),
            'Prioridade':   r.get('prioridade', 'Normal'),
            'Meta (cx)':   f'{pm:,.0f}',
            'Vendido (cx)': f'{pv:,.0f}',
            '% Atingido':  f'{pa*100:.1f}%',
        })
    if prows:
        st.dataframe(pd.DataFrame(prows), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------------------

if 'config' not in st.session_state:
    st.session_state.config = load_config()

cfg = st.session_state.config

if not storage.is_configured():
    st.info(
        '⚠️ Persistência permanente ainda não configurada: a configuração desta '
        'semana só fica salva enquanto o app não reiniciar/dormir. Para manter os '
        'dados disponíveis a semana toda, configure o GITHUB_TOKEN nos Secrets do '
        'Streamlit Cloud (instruções no topo do arquivo storage.py).'
    )

st.title('Metas Semanais e Responsáveis')

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_cfg, tab_on_track, tab_fechamento = st.tabs([
    '⚙️ Configuração',
    '📊 On Track',
    '📅 Fechamento Semanal',
])

# ============================================================
# Tab 1 — Configuração e Cálculo (conteúdo original)
# ============================================================
with tab_cfg:
    st.header('1. Upload dos relatórios da semana')
    col1, col2 = st.columns(2)
    with col1:
        estoque_file = st.file_uploader(
            'Estoque Físico (PDF) — opcional, usado só para detalhar '
            'o estoque completo no relatório individual de cada vendedor',
            type='pdf', key='estoque',
        )
    with col2:
        vendas_file = st.file_uploader(
            'Lucratividade por Vendedor / Vendas Acumuladas (PDF) — obrigatório',
            type='pdf', key='vendas',
        )

    st.header('2. Produtos da semana')
    st.caption(
        'Cole os códigos do relatório de vendas separados por vírgula ou linha. '
        'Use "*" no final para prefixo (ex.: "3102006*"). Sem "*", código exato.'
    )

    if st.button('➕ Adicionar produto'):
        cfg['produtos'].append({'nome': '', 'codigos_texto': '', 'estoque': 0})

    _PRIORIDADES = ['Normal', '🔥 Alta Prioridade', '🚨 Grande Urgência']

    remover_idx = None
    for i, p in enumerate(cfg['produtos']):
        p.setdefault('estoque', 0)
        p.setdefault('prioridade', 'Normal')
        prio_label = f' {p["prioridade"]}' if p['prioridade'] != 'Normal' else ''
        with st.expander(f"Produto {i+1}: {p['nome'] or '(sem nome)'}{prio_label}", expanded=not bool(p['nome'])):
            c1, c2, c3, c4, c5 = st.columns([3, 4, 1.8, 2, 1])
            with c1:
                p['nome'] = st.text_input('Nome do produto', value=p['nome'], key=f'nome_{i}')
            with c2:
                p['codigos_texto'] = st.text_area(
                    'Códigos (vírgula ou linha; use * para prefixo) '
                    '— usados só para identificar as vendas',
                    value=p['codigos_texto'], key=f'cod_{i}', height=80,
                )
            with c3:
                p['estoque'] = st.number_input(
                    'Quantidade (cx)', min_value=0, step=1,
                    value=int(p['estoque']), key=f'est_{i}',
                )
            with c4:
                prio_idx = _PRIORIDADES.index(p['prioridade']) if p['prioridade'] in _PRIORIDADES else 0
                p['prioridade'] = st.selectbox(
                    'Prioridade', _PRIORIDADES, index=prio_idx, key=f'prio_{i}',
                )
            with c5:
                st.write('')
                st.write('')
                if st.button('🗑️', key=f'del_{i}'):
                    remover_idx = i

    if remover_idx is not None:
        cfg['produtos'].pop(remover_idx)
        st.rerun()

    st.subheader('Percentuais de meta por vendedor (% sobre o estoque digitado acima)')
    st.caption('Já vêm preenchidos com os percentuais fixos de cada vendedor — normalmente não precisa alterar.')
    pct_cols = st.columns(len(cfg['vendedor_pcts']))
    for col, (vend, pct) in zip(pct_cols, list(cfg['vendedor_pcts'].items())):
        with col:
            cfg['vendedor_pcts'][vend] = st.number_input(
                vend, min_value=0, max_value=200,
                value=int(pct), key=f'pct_{vend}',
            )

    cb1, cb2, cb3 = st.columns(3)
    with cb1:
        if st.button('💾 Salvar configuração desta semana'):
            save_config(cfg)
    with cb2:
        st.download_button(
            '⬇️ Exportar configuração (JSON)',
            data=json.dumps(cfg, ensure_ascii=False, indent=2),
            file_name=f"config_metas_{datetime.date.today().isoformat()}.json",
            mime='application/json',
        )
    with cb3:
        up_cfg = st.file_uploader('⬆️ Importar configuração (JSON)', type='json', key='cfg_upload')
        if up_cfg is not None:
            st.session_state.config = json.load(up_cfg)
            save_config(st.session_state.config, show_feedback=False)
            st.rerun()

    st.divider()

    # ── Calcular ─────────────────────────────────────────────────────────
    st.header('3. Calcular metas e gerar relatórios')

    periodo = st.text_input(
        'Período (ex.: 22/06/2026 a 26/06/2026)',
        value=cfg.get('periodo', ''),
    )
    data_emissao = st.text_input(
        'Data de emissão (ex.: 29/06/2026)',
        value=datetime.date.today().strftime('%d/%m/%Y'),
    )
    cfg['periodo'] = periodo

    if st.button('▶️ Calcular metas', type='primary'):
        if not vendas_file:
            st.error('Envie o PDF de Vendas (Lucratividade por Vendedor) antes de calcular.')
        elif not any(p['nome'].strip() for p in cfg['produtos']):
            st.error('Cadastre ao menos um produto com nome, estoque e códigos.')
        else:
            with st.spinner('Lendo PDFs e calculando metas...'):
                estoque_rows = []
                if estoque_file:
                    try:
                        estoque_rows = parse_estoque(estoque_file)
                    except Exception:
                        st.warning(
                            'Não foi possível ler o PDF de Estoque Físico enviado '
                            '(arquivo corrompido, protegido ou em formato inesperado). '
                            'A Meta não depende desse PDF, então o cálculo vai continuar '
                            'sem a lista detalhada de estoque no relatório individual.'
                        )

                # Lê os bytes uma vez para reusar nos dois parsers
                vendas_bytes = vendas_file.read()
                try:
                    vendas_rows = parse_vendas(io.BytesIO(vendas_bytes))
                except Exception:
                    st.error(
                        'Não foi possível ler o PDF de Vendas/Lucratividade enviado. '
                        'Verifique se o arquivo não está corrompido ou protegido por '
                        'senha e tente enviar novamente.'
                    )
                    vendas_rows = None

                # Tenta extrair dados em R$ do mesmo PDF (Lucratividade por Vendedor)
                if vendas_rows is not None:
                    try:
                        totais_res = parse_totais_vendedor(io.BytesIO(vendas_bytes))
                        st.session_state['totais_rs'] = totais_res
                    except Exception:
                        st.session_state.pop('totais_rs', None)

            if vendas_rows is not None:
                produtos_config = [
                    {
                        'nome': p['nome'],
                        'codigos': parse_codigos_input(p['codigos_texto']),
                        'estoque': p.get('estoque', 0),
                        'prioridade': p.get('prioridade', 'Normal'),
                    }
                    for p in cfg['produtos'] if p['nome'].strip()
                ]
                resultados = compute_metas(vendas_rows, produtos_config, cfg['vendedor_pcts'])
                _prio_map = {p['nome']: p.get('prioridade', 'Normal') for p in produtos_config}
                for _r in resultados:
                    _r['prioridade'] = _prio_map.get(_r['produto'], 'Normal')
                st.session_state['estoque_rows']    = estoque_rows
                st.session_state['vendas_rows']     = vendas_rows
                st.session_state['resultados']      = resultados
                st.session_state['produtos_config'] = produtos_config
                save_config(cfg, show_feedback=False)
                st.success('Cálculo concluído. Confira a aba **📊 On Track** para o dashboard.')

    # ── Resultados ────────────────────────────────────────────────────────
    if 'resultados' in st.session_state:
        resultados      = st.session_state['resultados']
        estoque_rows    = st.session_state['estoque_rows']
        vendas_rows_diag = st.session_state.get('vendas_rows', [])
        produtos_config_diag = st.session_state.get('produtos_config', [])

        # Diagnóstico de códigos não reconhecidos
        nao_rec = _diagnostico_codigos(vendas_rows_diag, produtos_config_diag)
        if nao_rec:
            total_nao_rec = sum(r['CX não reconhecidas'] for r in nao_rec)
            with st.expander(
                f'⚠️ {len(nao_rec)} código(s) do PDF não reconhecido(s) '
                f'— {total_nao_rec:,.0f} cx fora do cálculo',
                expanded=True,
            ):
                st.caption(
                    'Esses códigos aparecem no PDF mas não casaram com nenhum produto '
                    'configurado. Se fizerem parte das metas desta semana, adicione ou '
                    'corrija os códigos na seção **2. Produtos da semana** acima.'
                )
                df_diag = pd.DataFrame(nao_rec)
                df_diag['CX não reconhecidas'] = df_diag['CX não reconhecidas'].map(
                    lambda x: f'{x:,.0f}'
                )
                st.dataframe(df_diag, use_container_width=True, hide_index=True)
        else:
            st.success('✅ Todos os códigos do PDF foram reconhecidos — nenhuma cx perdida.')

        st.subheader('Resultado: Meta / Vendido / Falta por produto e vendedor')
        for r in resultados:
            prio = r.get('prioridade', 'Normal')
            prio_badge = f' &nbsp; {prio}' if prio != 'Normal' else ''
            st.markdown(
                f"**{r['produto']}**{prio_badge} — Quantidade: {r['estoque_total']:.0f} cx",
                unsafe_allow_html=True,
            )
            st.dataframe(
                [{'Vendedor': l['vendedor'], '% Meta': f"{l['pct']:.0f}%",
                  'Meta (cx)': l['meta'], 'Vendido (cx)': l['vendido'],
                  'Falta (cx)': l['falta'], '% Atingido': f"{l['atingido']*100:.1f}%"}
                 for l in r['linhas']],
                use_container_width=True, hide_index=True,
            )

        st.divider()
        st.subheader('Gerar PDFs')

        vendedores_disponiveis = list(cfg['vendedor_pcts'].keys())
        vendedor_sel = st.selectbox('Relatório individual do vendedor', vendedores_disponiveis)

        pcol1, pcol2, pcol3 = st.columns(3)
        with pcol1:
            pdf_bytes = generate_relatorio_vendedor(
                vendedor_sel, data_emissao, estoque_rows, resultados,
            )
            st.download_button(
                f'⬇️ Relatório — {vendedor_sel}', data=pdf_bytes,
                file_name=f'Relatorio_{vendedor_sel}_{datetime.date.today().strftime("%d%m%Y")}.pdf',
                mime='application/pdf',
            )
        with pcol2:
            pdf_bytes = generate_dashboard(periodo, resultados, cfg['vendedor_pcts'])
            st.download_button(
                '⬇️ Dashboard', data=pdf_bytes,
                file_name=f'Dashboard_{datetime.date.today().strftime("%d%m%Y")}.pdf',
                mime='application/pdf',
            )
        with pcol3:
            pdf_bytes = generate_resumo_geral(periodo, data_emissao, resultados, cfg['vendedor_pcts'])
            st.download_button(
                '⬇️ Resumo Geral', data=pdf_bytes,
                file_name=f'Resumo_Geral_{datetime.date.today().strftime("%d%m%Y")}.pdf',
                mime='application/pdf',
            )

        with st.expander('Gerar relatórios de TODOS os vendedores de uma vez'):
            if st.button('Gerar todos os PDFs individuais'):
                for v in vendedores_disponiveis:
                    pdf_bytes = generate_relatorio_vendedor(v, data_emissao, estoque_rows, resultados)
                    st.download_button(
                        f'⬇️ {v}', data=pdf_bytes,
                        file_name=f'Relatorio_{v}_{datetime.date.today().strftime("%d%m%Y")}.pdf',
                        mime='application/pdf', key=f'all_{v}',
                    )

# ============================================================
# Tab 2 — On Track
# ============================================================
with tab_on_track:
    _render_on_track()

# ============================================================
# Tab 3 — Fechamento Semanal
# ============================================================
with tab_fechamento:
    _render_fechamento_semanal()
