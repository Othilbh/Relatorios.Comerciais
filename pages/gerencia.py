"""Página de Gerência OTHIL — acesso restrito por senha."""
import json
import math
import os
import re
import datetime
import tempfile

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from categorias import map_categoria
from dashboard_diario import gerar_dashboard
import periodo as periodo_mod
import comparativo
import on_track
import data_store as ds
import metas_gerais as mg
import rentabilidade as rent

MOD_RELATORIO_DIARIO = 'relatorio_diario'
MOD_FECHAMENTO = 'metas_semanais_fechamento'
MOD_ONTRACK_METAS = 'metas_semanais_ontrack'
MOD_QUEBRA = 'quebra'
MOD_ONTRACK_CLI = 'vendedor_cliente_ontrack'
MOD_PREVPERDAS = 'prevencao_perdas'
MOD_RECORRENCIA = 'recorrencia'
TIPO_RECORRENCIA = 'livre'

_GERENCIA_DIR     = os.path.join(os.path.dirname(__file__), '..', 'gerencia_data')
_ONTRACK_PUB_FILE = os.path.join(_GERENCIA_DIR, 'ontrack_publicado.json')
_ONTRACK_CLI_FILE = os.path.join(_GERENCIA_DIR, 'ontrack_clientes_publicado.json')
_ONTRACK_META_DIR = os.path.join(_GERENCIA_DIR, 'ontrack_metas')
_ONTRACK_CLI_DIR  = os.path.join(_GERENCIA_DIR, 'ontrack_clientes')
_QUEBRA_DIR       = os.path.join(_GERENCIA_DIR, 'quebra')
_PREVPERDAS_DIR   = os.path.join(_GERENCIA_DIR, 'prevencao_perdas')
_PERDAS_DIR       = os.path.join(_GERENCIA_DIR, 'perdas_realizadas')
_MESES_QBR     = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']
_SENHA_FALLBACK = 'othil2024'


def _get_senha() -> str:
    try:
        return st.secrets['gerencia_senha']
    except Exception:
        return _SENHA_FALLBACK


def _check_auth() -> bool:
    if st.session_state.get('_gerencia_auth'):
        return True
    st.markdown("""
    <div style="text-align:center; padding:3rem 0 1rem;">
        <div style="display:inline-block; background:#2D6A4F; color:white;
                    padding:0.5rem 1.6rem; border-radius:10px; margin-bottom:1rem;">
            <span style="font-size:1rem; font-weight:600; letter-spacing:0.08em;">OTHIL</span>
        </div>
        <h2 style="color:#1B4332; margin:0.4rem 0;">Área de Gerência</h2>
        <p style="color:#666; font-size:0.9rem;">Acesso restrito</p>
    </div>
    """, unsafe_allow_html=True)
    col = st.columns([1, 2, 1])[1]
    with col:
        pwd = st.text_input('Senha', type='password', key='_gerencia_pwd',
                            label_visibility='collapsed', placeholder='Digite a senha de acesso')
        if st.button('Entrar', type='primary', use_container_width=True):
            if pwd == _get_senha():
                st.session_state['_gerencia_auth'] = True
                st.rerun()
            else:
                st.error('Senha incorreta.')
    return False


def _dir_tipo(tipo):
    d = os.path.join(_GERENCIA_DIR, tipo)
    os.makedirs(d, exist_ok=True)
    return d


def _listar_dashboards(tipo):
    """Lista os dashboards salvos, mais recente primeiro. Lê da persistência
    real (data_store — sobrevive a restart/redeploy/hibernação do Streamlit
    Cloud); quando o HTML local não existir mais, regenera automaticamente a
    partir dos itens persistidos, para o dashboard não "sumir" após um
    reboot. Arquivos locais entram como complemento/fallback."""
    d = _dir_tipo(tipo)
    items = {}

    try:
        for slug in ds.list_periodos(MOD_RELATORIO_DIARIO, tipo):
            registro = ds.load_current(MOD_RELATORIO_DIARIO, tipo, slug)
            if not registro:
                continue
            valores = registro['valores']
            meta = {
                'slug': slug, 'tipo': tipo,
                'periodo': valores.get('periodo'), 'emissao': valores.get('emissao'),
                'gerado_em': registro.get('atualizado_em', ''),
            }
            html_path = os.path.join(d, f'{slug}.html')
            if not os.path.exists(html_path) and valores.get('itens'):
                try:
                    with tempfile.NamedTemporaryFile(suffix='.html', delete=False,
                                                      mode='w', encoding='utf-8') as tmp:
                        pass
                    gerar_dashboard({'itens': valores['itens'], 'periodo': valores.get('periodo'),
                                      'data_emissao': valores.get('emissao')}, tmp.name, tipo=tipo)
                    with open(tmp.name, 'r', encoding='utf-8') as f_html:
                        html_regen = f_html.read()
                    with open(html_path, 'w', encoding='utf-8') as f_out:
                        f_out.write(html_regen)
                except Exception:
                    pass
            items[slug] = meta
    except Exception:
        pass

    for fname in os.listdir(d):
        if fname.endswith('.json'):
            try:
                with open(os.path.join(d, fname), 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                slug = meta.get('slug') or fname.replace('.json', '')
                if slug in items:
                    continue
                if os.path.exists(os.path.join(d, f'{slug}.html')):
                    items[slug] = meta
            except Exception:
                pass

    return sorted(items.items(), key=lambda kv: kv[0], reverse=True)


def _label_slug(slug, tipo):
    try:
        if tipo == 'semanal':
            year, week = slug.split('-W')
            return f'Semana {int(week):02d} / {year}'
        elif tipo == 'mensal':
            year, mon = slug.split('-')
            meses = ['Jan','Fev','Mar','Abr','Mai','Jun',
                     'Jul','Ago','Set','Out','Nov','Dez']
            return f'{meses[int(mon)-1]} / {year}'
        else:
            return slug
    except Exception:
        return slug


def _render_secao_dash(tipo, titulo_secao, emoji):
    st.header(f'{emoji} {titulo_secao}')
    dashboards = _listar_dashboards(tipo)

    if not dashboards:
        tipo_label = {'diario': 'Relatório Diário', 'semanal': 'aba Semanal', 'mensal': 'aba Mensal'}
        st.info(f'Nenhum dashboard disponível. Gere um na página **{tipo_label.get(tipo,tipo)}** primeiro.')
        return

    slugs  = [s for s, _ in dashboards]
    if tipo == 'diario':
        labels = [f"{m.get('emissao', s)}  —  {m.get('periodo','-')}" for s, m in dashboards]
    else:
        labels = [_label_slug(s, tipo) + f"  ({m.get('periodo','-')})" for s, m in dashboards]

    idx_key = f'_ger_idx_{tipo}'
    if idx_key not in st.session_state:
        st.session_state[idx_key] = 0

    col_prev, col_sel, col_next = st.columns([1, 6, 1])
    with col_prev:
        st.write('')
        if st.button('◀', key=f'ger_prev_{tipo}', help='Período anterior'):
            st.session_state[idx_key] = min(st.session_state[idx_key] + 1, len(slugs) - 1)
    with col_next:
        st.write('')
        if st.button('▶', key=f'ger_next_{tipo}', help='Próximo período'):
            st.session_state[idx_key] = max(st.session_state[idx_key] - 1, 0)
    with col_sel:
        escolha = st.selectbox(
            f'{len(dashboards)} período(s) salvo(s):',
            labels,
            index=min(st.session_state[idx_key], len(labels)-1),
            key=f'ger_sel_{tipo}',
        )
        st.session_state[idx_key] = labels.index(escolha)

    idx     = st.session_state[idx_key]
    slug_h  = slugs[idx]
    meta_h  = dashboards[idx][1]
    gerado  = meta_h.get('gerado_em', '')[:16].replace('T', ' ')
    st.caption(f'Período: {meta_h.get("periodo","-")}  |  Gerado em: {gerado}')

    html_path = os.path.join(_dir_tipo(tipo), f'{slug_h}.html')
    if not os.path.exists(html_path):
        st.warning('Este dashboard não pôde ser regenerado automaticamente '
                    '(dado antigo, salvo antes da persistência com histórico de itens). '
                    'Gere novamente na página de origem.')
        return
    with open(html_path, 'r', encoding='utf-8') as f:
        html_text = f.read()

    components.html(html_text, height=1400, scrolling=True)
    st.download_button(
        f'⬇️ Baixar {_label_slug(slug_h, tipo) if tipo != "diario" else slug_h}',
        data=html_text.encode('utf-8'),
        file_name=f'dashboard_{tipo}_{slug_h}_OTHIL.html',
        mime='text/html',
        key=f'ger_dl_{tipo}',
    )


def _listar_ontrack_hist(directory):
    """Lista snapshots de histórico de On Track de um diretório, mais recente primeiro."""
    if not os.path.isdir(directory):
        return []
    items = []
    for fname in sorted(os.listdir(directory), reverse=True):
        if not fname.endswith('.json'):
            continue
        try:
            with open(os.path.join(directory, fname), 'r', encoding='utf-8') as f:
                data = json.load(f)
            items.append((fname.replace('.json', ''), data))
        except Exception:
            pass
    return items


# ── Quebra helpers ────────────────────────────────────────────────────────────

def _qbr_dir(tipo: str) -> str:
    d = os.path.join(_QUEBRA_DIR, tipo)
    os.makedirs(d, exist_ok=True)
    return d


def _qbr_label(slug: str, tipo: str) -> str:
    try:
        if tipo == 'semanal':
            year, week = slug.split('-W')
            return f"Semana {int(week):02d} / {year}"
        elif tipo == 'mensal':
            year, mon = slug.split('-')
            return f"{_MESES_QBR[int(mon)-1]} / {year}"
    except Exception:
        pass
    return slug


def _qbr_listar(tipo: str) -> list:
    """Histórico de Quebras — lê da persistência real (data_store) primeiro;
    arquivos locais entram como complemento/fallback."""
    items = {}
    try:
        for slug in ds.list_periodos(MOD_QUEBRA, tipo):
            registro = ds.load_current(MOD_QUEBRA, tipo, slug)
            if registro:
                items[slug] = registro['valores']
    except Exception:
        pass
    d = _qbr_dir(tipo)
    for fname in sorted(os.listdir(d), reverse=True):
        if not fname.endswith('.json'):
            continue
        slug = fname.replace('.json', '')
        if slug in items:
            continue
        try:
            with open(os.path.join(d, fname), 'r', encoding='utf-8') as f:
                meta = json.load(f)
            items[slug] = meta
        except Exception:
            pass
    return sorted(items.items(), key=lambda kv: kv[0], reverse=True)


def _render_quebra_comparativo():
    st.header('🔀 Comparativo de Quebras')

    tipo = st.radio(
        'Tipo de período:',
        ['semanal', 'mensal'],
        format_func=lambda x: 'Semanal' if x == 'semanal' else 'Mensal',
        horizontal=True,
        key='ger_comp_tipo',
    )

    historico = _qbr_listar(tipo)
    if len(historico) < 2:
        st.info('Necessário ter pelo menos 2 períodos salvos para comparar.')
        return

    slugs  = [s for s, _ in historico]
    labels = [f"{_qbr_label(s, tipo)}  —  {m.get('periodo', '-')}" for s, m in historico]

    col_a, col_b = st.columns(2)
    with col_a:
        escolha_a = st.selectbox('Período A (base):', labels, index=0, key='ger_comp_sel_a')
    with col_b:
        default_b = 1 if len(labels) > 1 else 0
        escolha_b = st.selectbox('Período B (comparar):', labels, index=default_b, key='ger_comp_sel_b')

    if escolha_a == escolha_b:
        st.warning('Selecione períodos diferentes para comparar.')
        return

    dados_a = historico[labels.index(escolha_a)][1]
    dados_b = historico[labels.index(escolha_b)][1]
    label_a = _qbr_label(slugs[labels.index(escolha_a)], tipo)
    label_b = _qbr_label(slugs[labels.index(escolha_b)], tipo)

    st.divider()

    total_a = dados_a.get('total_cx', 0)
    total_b = dados_b.get('total_cx', 0)
    delta   = total_b - total_a
    delta_pct = (delta / total_a * 100) if total_a else 0

    c1, c2, c3 = st.columns(3)
    c1.metric(f'Total CX — {label_a}', f"{total_a:,.0f} cx")
    c2.metric(f'Total CX — {label_b}', f"{total_b:,.0f} cx")
    c3.metric('Variação (B − A)', f"{delta:+,.0f} cx",
              delta=f"{delta_pct:+.1f}%", delta_color='inverse')

    st.divider()
    st.subheader('Por Categoria de Produto')

    cat_a = {c['categoria']: c['cx'] for c in dados_a.get('categorias', [])}
    cat_b = {c['categoria']: c['cx'] for c in dados_b.get('categorias', [])}
    todas_cats = sorted(set(cat_a) | set(cat_b))

    df_comp = pd.DataFrame({
        label_a: [cat_a.get(c, 0) for c in todas_cats],
        label_b: [cat_b.get(c, 0) for c in todas_cats],
    }, index=todas_cats)
    st.bar_chart(df_comp, color=['#2D6A4F', '#74C69D'])

    df_cat_tbl = df_comp.copy()
    df_cat_tbl['Δ (B − A)'] = df_cat_tbl[label_b] - df_cat_tbl[label_a]
    df_cat_tbl['Δ %'] = df_cat_tbl.apply(
        lambda r: f"{r['Δ (B − A)'] / r[label_a] * 100:+.1f}%" if r[label_a] else '—', axis=1)
    df_cat_tbl = df_cat_tbl.reset_index().rename(columns={'index': 'Categoria'})
    df_cat_tbl[label_a]     = df_cat_tbl[label_a].map(lambda x: f"{x:,.0f}")
    df_cat_tbl[label_b]     = df_cat_tbl[label_b].map(lambda x: f"{x:,.0f}")
    df_cat_tbl['Δ (B − A)'] = df_cat_tbl['Δ (B − A)'].map(lambda x: f"{x:+,.0f}")
    st.dataframe(df_cat_tbl, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader('Por Grupo de Produto')

    grp_a = {g['grupo']: g for g in dados_a.get('grupos', [])}
    grp_b = {g['grupo']: g for g in dados_b.get('grupos', [])}
    rows = []
    for grp in sorted(set(grp_a) | set(grp_b)):
        ga, gb = grp_a.get(grp, {}), grp_b.get(grp, {})
        cx_a, cx_b = ga.get('cx', 0), gb.get('cx', 0)
        rows.append({
            'Grupo':     grp,
            'Categoria': ga.get('categoria') or gb.get('categoria', '—'),
            label_a:     cx_a,
            label_b:     cx_b,
            'Δ (B − A)': cx_b - cx_a,
        })

    if not rows:
        st.info('Nenhum grupo de produto registrado nesses dois períodos.')
    else:
        df_grp = pd.DataFrame(rows).sort_values('Δ (B − A)', ascending=False)
        df_grp[label_a]     = df_grp[label_a].map(lambda x: f"{x:,.0f}")
        df_grp[label_b]     = df_grp[label_b].map(lambda x: f"{x:,.0f}")
        df_grp['Δ (B − A)'] = df_grp['Δ (B − A)'].map(lambda x: f"{x:+,.0f}")
        st.dataframe(df_grp, use_container_width=True, hide_index=True)


def _render_quebra_secao(tipo: str, titulo: str, emoji: str):
    st.header(f'{emoji} {titulo}')
    historico = _qbr_listar(tipo)
    if not historico:
        st.info(f'Nenhum relatório de quebra disponível. Envie um PDF na página **Quebras** primeiro.')
        return

    slugs  = [s for s, _ in historico]
    labels = [f"{_qbr_label(s, tipo)}  —  {m.get('periodo', '-')}" for s, m in historico]

    idx_key = f'_ger_qbr_idx_{tipo}'
    if idx_key not in st.session_state:
        st.session_state[idx_key] = 0

    col_prev, col_sel, col_next = st.columns([1, 6, 1])
    with col_prev:
        st.write('')
        if st.button('◀', key=f'ger_qbr_prev_{tipo}'):
            st.session_state[idx_key] = min(st.session_state[idx_key] + 1, len(slugs) - 1)
    with col_next:
        st.write('')
        if st.button('▶', key=f'ger_qbr_next_{tipo}'):
            st.session_state[idx_key] = max(st.session_state[idx_key] - 1, 0)
    with col_sel:
        escolha = st.selectbox(
            f'{len(historico)} período(s) salvo(s):',
            labels,
            index=min(st.session_state[idx_key], len(labels) - 1),
            key=f'ger_qbr_sel_{tipo}',
        )
        st.session_state[idx_key] = labels.index(escolha)

    idx = st.session_state[idx_key]
    slug_sel = slugs[idx]
    dados = historico[idx][1]

    st.caption(f'Período: {dados.get("periodo", "-")}  |  Emissão: {dados.get("emissao", "-")}')

    total = dados.get('total_cx', 0)
    categorias = dados.get('categorias', [])
    grupos = dados.get('grupos', [])

    col1, col2 = st.columns(2)
    col1.metric('Total CX Quebradas', f"{total:,.0f} cx")
    if categorias:
        top = categorias[0]
        col2.metric(f'Maior: {top["categoria"]}', f"{top['cx']:,.0f} cx")

    # ── Comparativo automático vs período anterior salvo (menor é melhor)
    if idx + 1 < len(historico):
        dados_ant = historico[idx + 1][1]
        total_ant = dados_ant.get('total_cx', 0)
        comp_auto = comparativo.calcular(total, total_ant, menor_e_melhor=True)
        st.metric(
            f'📊 vs período anterior ({_qbr_label(slugs[idx + 1], tipo)})',
            f"{total:,.0f} cx",
            delta=comparativo.formatar_variacao(comp_auto, casas=1),
            delta_color='inverse',
        )

    if categorias:
        df_cat = pd.DataFrame(categorias).set_index('categoria')
        st.bar_chart(df_cat['cx'], color='#2D6A4F')

    if grupos:
        df_g = pd.DataFrame(grupos)[['grupo', 'categoria', 'cx']]
        df_g.columns = ['Grupo', 'Categoria', 'CX Quebradas']
        st.dataframe(df_g, use_container_width=True, hide_index=True)


# ── Recorrência helpers ────────────────────────────────────────────────────────

def _listar_recorrencias_ger():
    """Histórico de publicações de Recorrência — lê da persistência real
    (data_store) primeiro; arquivo local único antigo ('latest') entra como
    complemento/fallback quando não houver nenhum registro no data_store."""
    itens = []
    try:
        for slug in ds.list_periodos(MOD_RECORRENCIA, TIPO_RECORRENCIA):
            registro = ds.load_current(MOD_RECORRENCIA, TIPO_RECORRENCIA, slug)
            if registro:
                itens.append((slug, registro['valores'], registro.get('atualizado_em', '')))
    except Exception:
        pass
    if not itens:
        _rec_json = os.path.join(_GERENCIA_DIR, 'recorrencia_latest.json')
        if os.path.exists(_rec_json):
            try:
                with open(_rec_json, 'r', encoding='utf-8') as f:
                    rec = json.load(f)
                itens.append(('latest', rec, rec.get('gerado_em', '')))
            except Exception:
                pass
    itens.sort(key=lambda t: t[2], reverse=True)
    return itens


# ── Fechamentos Semanais ──────────────────────────────────────────────────────

_FECHAMENTOS_DIR = os.path.join(_GERENCIA_DIR, 'fechamentos')


_GER_STATUS_COR = {
    on_track.STATUS_VERDE:    '#2D6A4F',
    on_track.STATUS_ATENCAO:  '#B8860B',
    on_track.STATUS_FORA:     '#C00000',
    on_track.STATUS_SEM_META: '#6c757d',
}


def _on_track_status_ger(atingido: float, dia: int):
    """(emoji, label, hex_color) — via lógica central de On Track
    (on_track.py), tempo decorrido em dias úteis (1..5), mesma convenção
    já usada em Metas Semanais."""
    pct_tempo = dia / 5 if dia > 0 else 0.0
    r = on_track.calcular(
        meta=1.0, realizado=atingido, tipo_periodo='semanal',
        periodo_ref='(dias uteis)', pct_tempo_decorrido=pct_tempo,
    )
    return r['emoji'], r['label'], _GER_STATUS_COR[r['status']]


def _listar_ontrack_metas_hist():
    """Histórico de publicações de On Track de Metas Semanais — lê da
    persistência real (data_store) primeiro; arquivos locais (dir/arquivo
    único antigos) entram como complemento/fallback."""
    items = {}
    try:
        for slug in ds.list_periodos(MOD_ONTRACK_METAS, 'semanal'):
            registro = ds.load_current(MOD_ONTRACK_METAS, 'semanal', slug)
            if registro:
                items[slug] = registro['valores']
    except Exception:
        pass
    for slug, data in _listar_ontrack_hist(_ONTRACK_META_DIR):
        if slug not in items:
            items[slug] = data
    return sorted(items.items(), key=lambda kv: kv[0], reverse=True)


def _listar_ontrack_clientes_hist():
    """Histórico de publicações de On Track Vendedor×Cliente — lê da
    persistência real (data_store) primeiro; arquivos locais (dir antigo)
    entram como complemento/fallback. Antes desta correção, esta tela só
    lia o diretório local — e o diretório local é apagado a cada restart
    do Streamlit Cloud, então o histórico "desaparecia" nesse caso."""
    items = {}
    try:
        for slug in ds.list_periodos(MOD_ONTRACK_CLI, 'mensal'):
            registro = ds.load_current(MOD_ONTRACK_CLI, 'mensal', slug)
            if registro:
                items[slug] = registro['valores']
    except Exception:
        pass
    for slug, data in _listar_ontrack_hist(_ONTRACK_CLI_DIR):
        if slug not in items:
            items[slug] = data
    return sorted(items.items(), key=lambda kv: kv[0], reverse=True)


def _render_ontrack_publicado():
    st.header('📊 On Track Atual')

    historico_ot = _listar_ontrack_metas_hist()

    if not historico_ot:
        # backward compat: tentar arquivo único (publicações salvas antes
        # de existir o histórico versionado)
        if not os.path.exists(_ONTRACK_PUB_FILE):
            st.info(
                'Nenhum dado publicado ainda. Na página **Metas Semanais**, '
                'calcule as metas e clique em **"📤 Publicar On Track para Gerência"**.'
            )
            return
        with open(_ONTRACK_PUB_FILE, 'r', encoding='utf-8') as f:
            snap = json.load(f)
    else:
        labels_ot = [_label_fech(s) + f"  —  {d.get('periodo', '-')}" for s, d in historico_ot]
        escolha_ot = st.selectbox(
            f'{len(historico_ot)} semana(s) disponível(is):',
            labels_ot,
            index=0,
            key='ger_ot_meta_sel',
        )
        idx_ot = labels_ot.index(escolha_ot)
        snap = historico_ot[idx_ot][1]

    pub_em     = snap.get('publicado_em', '')[:16].replace('T', ' ')
    periodo    = snap.get('periodo', '—')
    resultados = snap.get('resultados', [])
    totais_rs  = snap.get('totais_rs', {})

    st.caption(f"Período: **{periodo}**  |  Publicado em: **{pub_em}**")

    dia = st.slider(
        'Dia da semana (para status On Track)', 1, 5,
        value=min(datetime.date.today().weekday() + 1, 5),
        format='Dia %d de 5', key='ger_ot_dia',
    )

    st.divider()

    # KPIs gerais
    total_meta = sum(l['meta']    for r in resultados for l in r.get('linhas', []))
    total_vend = sum(l['vendido'] for r in resultados for l in r.get('linhas', []))
    total_atg  = total_vend / total_meta if total_meta else 0
    proj_cx    = math.ceil(total_vend / dia * 5) if dia > 0 else total_vend
    em, lb, _  = _on_track_status_ger(total_atg, dia)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric('Meta (cx)',     f'{total_meta:,.0f}')
    k2.metric('Vendido (cx)',  f'{total_vend:,.0f}')
    k3.metric('% Atingido',    f'{total_atg*100:.1f}%')
    k4.metric('Projeção (cx)', f'{proj_cx:,.0f}')
    k5.metric('Status',        f'{em} {lb}')

    tg = totais_rs.get('total_geral', {})
    if tg:
        st.subheader('Faturamento Geral (R$)')
        r1, r2, r3 = st.columns(3)
        r1.metric('Faturamento', f"R$ {tg.get('fat', 0):,.2f}")
        r2.metric('MC R$',       f"R$ {tg.get('mc_rs', 0):,.2f}")
        r3.metric('MC %',        f"{tg.get('mc_pct', 0):.2f}%")

    # ── Comparativo vs semana anterior salva ────────────────────────────────
    if historico_ot and idx_ot + 1 < len(historico_ot):
        snap_ant_ot = historico_ot[idx_ot + 1][1]
        totais_rs_ant = snap_ant_ot.get('totais_rs', {})
        tg_ant = totais_rs_ant.get('total_geral', {})
        vend_ant_total = sum(l['vendido'] for r in snap_ant_ot.get('resultados', [])
                              for l in r.get('linhas', []))
        st.subheader('📊 Comparativo vs semana anterior')
        cc1, cc2, cc3 = st.columns(3)
        comp_vend = comparativo.calcular(total_vend, vend_ant_total)
        cc1.metric('Vendido (cx)', f'{total_vend:,.0f}', delta=comparativo.formatar_variacao(comp_vend))
        if tg and tg_ant:
            comp_fat = comparativo.calcular(tg.get('fat', 0), tg_ant.get('fat'))
            comp_mc  = comparativo.calcular(tg.get('mc_rs', 0), tg_ant.get('mc_rs'))
            cc2.metric('Faturamento', f"R$ {tg.get('fat', 0):,.2f}", delta=comparativo.formatar_variacao(comp_fat))
            cc3.metric('MC R$', f"R$ {tg.get('mc_rs', 0):,.2f}", delta=comparativo.formatar_variacao(comp_mc))
        st.caption(f'Base de comparação: {_label_fech(historico_ot[idx_ot + 1][0])}')

    st.divider()

    # Por produto
    st.subheader('Por Produto')
    for r in resultados:
        p_meta = sum(l['meta']    for l in r.get('linhas', []))
        p_vend = sum(l['vendido'] for l in r.get('linhas', []))
        p_atg  = p_vend / p_meta if p_meta else 0
        p_em, p_lb, _ = _on_track_status_ger(p_atg, dia)
        prio = r.get('prioridade', 'Normal')
        badge = f' — {prio}' if prio != 'Normal' else ''
        with st.expander(
            f"{p_em} {r.get('produto', '')}{badge}  |  "
            f"{p_vend:,.0f}/{p_meta:,.0f} cx ({p_atg*100:.1f}%)  —  {p_lb}",
            expanded=False,
        ):
            vrows = []
            for l in r.get('linhas', []):
                v_atg = l['vendido'] / l['meta'] if l['meta'] else 0
                v_em, v_lb, _ = _on_track_status_ger(v_atg, dia)
                vrows.append({
                    'Vendedor':     l.get('vendedor', ''),
                    'Meta (cx)':   f"{l['meta']:,.0f}",
                    'Vendido (cx)': f"{l['vendido']:,.0f}",
                    '% Atingido':  f"{v_atg*100:.1f}%",
                    'Status':      f'{v_em} {v_lb}',
                })
            st.dataframe(pd.DataFrame(vrows), use_container_width=True, hide_index=True)

    st.divider()

    # Por vendedor
    st.subheader('Por Vendedor')
    vend_agg = {}
    for r in resultados:
        for l in r.get('linhas', []):
            v = l.get('vendedor', '?')
            if v not in vend_agg:
                vend_agg[v] = {'meta': 0.0, 'vendido': 0.0}
            vend_agg[v]['meta']    += l.get('meta', 0)
            vend_agg[v]['vendido'] += l.get('vendido', 0)

    vend_rs = totais_rs.get('vendedores', {})
    vrows_all = []
    for v, ag in sorted(vend_agg.items()):
        v_atg = ag['vendido'] / ag['meta'] if ag['meta'] else 0
        v_em, v_lb, _ = _on_track_status_ger(v_atg, dia)
        rs = vend_rs.get(v, {})
        vrows_all.append({
            'Vendedor':     v,
            'Meta (cx)':   f"{ag['meta']:,.0f}",
            'Vendido (cx)': f"{ag['vendido']:,.0f}",
            '% Atingido':  f"{v_atg*100:.1f}%",
            'Status':      f'{v_em} {v_lb}',
            'Fat R$':      f"R$ {rs['fat']:,.2f}"   if rs.get('fat')    is not None else '—',
            'MC R$':       f"R$ {rs['mc_rs']:,.2f}" if rs.get('mc_rs') is not None else '—',
        })
    st.dataframe(pd.DataFrame(vrows_all), use_container_width=True, hide_index=True)


def _listar_fechamentos():
    """Lista os fechamentos salvos, mais recente primeiro. Lê da
    persistência real (data_store — sobrevive a restart do app); arquivos
    locais entram como complemento para fechamentos salvos antes desta
    migração ou se a gravação remota tiver falhado."""
    items = {}
    try:
        for slug in ds.list_periodos(MOD_FECHAMENTO, 'semanal'):
            registro = ds.load_current(MOD_FECHAMENTO, 'semanal', slug)
            if registro:
                items[slug] = {
                    'periodo': registro['valores'].get('periodo', ''),
                    'gerado_em': registro.get('atualizado_em', ''),
                    'produtos': registro['valores'].get('produtos', []),
                    'totais_rs': registro['valores'].get('totais_rs', {}),
                    'usuario': registro.get('usuario'),
                    'versao': registro.get('versao'),
                }
    except Exception:
        pass

    os.makedirs(_FECHAMENTOS_DIR, exist_ok=True)
    for fname in os.listdir(_FECHAMENTOS_DIR):
        if not fname.endswith('.json'):
            continue
        slug = fname.replace('.json', '')
        if slug in items:
            continue
        try:
            with open(os.path.join(_FECHAMENTOS_DIR, fname), 'r', encoding='utf-8') as f:
                items[slug] = json.load(f)
        except Exception:
            pass

    return sorted(items.items(), key=lambda kv: kv[0], reverse=True)


def _label_fech(slug: str) -> str:
    try:
        return periodo_mod.rotulo('semanal', slug)
    except Exception:
        return slug


def _render_fechamentos_semanais():
    st.header('🏁 Fechamentos Semanais')
    historico = _listar_fechamentos()

    if not historico:
        st.info(
            'Nenhum fechamento salvo ainda. Na página **Metas Semanais**, '
            'calcule as metas e clique em **"Fechar Semana"** na aba Fechamento Semanal.'
        )
        return

    slugs  = [s for s, _ in historico]
    labels = [f"{_label_fech(s)}  —  {d.get('periodo', '-')}" for s, d in historico]

    idx_key = '_ger_fech_idx'
    if idx_key not in st.session_state:
        st.session_state[idx_key] = 0

    col_prev, col_sel, col_next = st.columns([1, 6, 1])
    with col_prev:
        st.write('')
        if st.button('◀', key='ger_fech_prev', help='Semana anterior'):
            st.session_state[idx_key] = min(st.session_state[idx_key] + 1, len(slugs) - 1)
    with col_next:
        st.write('')
        if st.button('▶', key='ger_fech_next', help='Próxima semana'):
            st.session_state[idx_key] = max(st.session_state[idx_key] - 1, 0)
    with col_sel:
        escolha = st.selectbox(
            f'{len(historico)} fechamento(s) salvo(s):',
            labels,
            index=min(st.session_state[idx_key], len(labels) - 1),
            key='ger_fech_sel',
        )
        st.session_state[idx_key] = labels.index(escolha)

    idx   = st.session_state[idx_key]
    dados = historico[idx][1]

    gerado = dados.get('gerado_em', '')[:16].replace('T', ' ')
    st.caption(f"Período: {dados.get('periodo', '-')}  |  Salvo em: {gerado}")

    prods     = dados.get('produtos', [])
    h_meta    = sum(l['meta']    for r in prods for l in r.get('linhas', []))
    h_vend    = sum(l['vendido'] for r in prods for l in r.get('linhas', []))
    h_atg     = h_vend / h_meta if h_meta else 0

    c1, c2, c3 = st.columns(3)
    c1.metric('Meta total (cx)', f'{h_meta:,.0f}')
    c2.metric('Vendido (cx)',    f'{h_vend:,.0f}')
    c3.metric('% Atingido',     f'{h_atg*100:.1f}%')

    tg = dados.get('totais_rs', {}).get('total_geral', {})
    if tg:
        r1, r2, r3 = st.columns(3)
        r1.metric('Faturamento', f"R$ {tg.get('fat', 0):,.2f}")
        r2.metric('MC R$',       f"R$ {tg.get('mc_rs', 0):,.2f}")
        r3.metric('MC %',        f"{tg.get('mc_pct', 0):.2f}%")

    st.divider()

    # Tabela por produto
    prows = []
    for r in prods:
        pm = sum(l['meta']    for l in r.get('linhas', []))
        pv = sum(l['vendido'] for l in r.get('linhas', []))
        pa = pv / pm if pm else 0
        prows.append({
            'Produto':     r.get('produto', ''),
            'Prioridade':  r.get('prioridade', 'Normal'),
            'Meta (cx)':  f'{pm:,.0f}',
            'Vendido (cx)': f'{pv:,.0f}',
            '% Atingido': f'{pa*100:.1f}%',
        })
    if prows:
        st.subheader('Por Produto')
        st.dataframe(pd.DataFrame(prows), use_container_width=True, hide_index=True)

    # Tabela por vendedor
    vend_agg = {}
    for r in prods:
        for l in r.get('linhas', []):
            v = l.get('vendedor', '?')
            if v not in vend_agg:
                vend_agg[v] = {'meta': 0, 'vendido': 0}
            vend_agg[v]['meta']    += l.get('meta', 0)
            vend_agg[v]['vendido'] += l.get('vendido', 0)

    vend_rs = dados.get('totais_rs', {}).get('vendedores', {})
    vrows = []
    for v, ag in sorted(vend_agg.items()):
        meta_v = ag['meta']
        vend_v = ag['vendido']
        atg_v  = vend_v / meta_v if meta_v else 0
        rs = vend_rs.get(v, {})
        vrows.append({
            'Vendedor':     v,
            'Meta (cx)':   f'{meta_v:,.0f}',
            'Vendido (cx)': f'{vend_v:,.0f}',
            '% Atingido':  f'{atg_v*100:.1f}%',
            'Fat R$':      f"R$ {rs['fat']:,.2f}" if rs.get('fat') is not None else '—',
            'MC R$':       f"R$ {rs['mc_rs']:,.2f}" if rs.get('mc_rs') is not None else '—',
            'MC %':        f"{rs['mc_pct']:.2f}%" if rs.get('mc_pct') is not None else '—',
        })
    if vrows:
        st.subheader('Por Vendedor')
        st.dataframe(pd.DataFrame(vrows), use_container_width=True, hide_index=True)

    # Comparativo entre semanas (se houver mais de 1)
    if len(historico) >= 2:
        st.divider()
        st.subheader('Comparativo de Semanas')
        st.caption('Variação (Δ%) sempre em relação à semana anterior na lista (mais antiga primeiro).')

        historico_asc = sorted(historico, key=lambda kv: kv[0])  # mais antiga primeiro p/ calcular Δ
        comp_rows = []
        vend_anterior = None
        fat_anterior = None
        for s, d in historico_asc:
            dp    = d.get('produtos', [])
            dm    = sum(l['meta']    for r in dp for l in r.get('linhas', []))
            dv    = sum(l['vendido'] for r in dp for l in r.get('linhas', []))
            da    = dv / dm if dm else 0
            dtg   = d.get('totais_rs', {}).get('total_geral', {})
            fat   = dtg.get('fat') if dtg else None

            comp_v = comparativo.calcular(dv, vend_anterior)
            comp_f = comparativo.calcular(fat, fat_anterior) if fat is not None else None

            comp_rows.append({
                'Semana':        _label_fech(s),
                'Período':       d.get('periodo', '-'),
                'Meta (cx)':    f'{dm:,.0f}',
                'Vendido (cx)': f'{dv:,.0f}',
                'Δ Vendido':    comparativo.formatar_variacao(comp_v, casas=1),
                '% Atingido':   f'{da*100:.1f}%',
                'Fat R$':       f"R$ {fat:,.2f}" if fat is not None else '—',
                'Δ Fat':        comparativo.formatar_variacao(comp_f, casas=1) if comp_f else 'n/d',
                'MC %':         f"{dtg.get('mc_pct', 0):.2f}%" if dtg else '—',
            })
            vend_anterior = dv
            fat_anterior = fat

        st.dataframe(pd.DataFrame(list(reversed(comp_rows))), use_container_width=True, hide_index=True)


def _render_ontrack_clientes():
    st.header('👥 On Track Vendedor × Cliente')

    historico_cli = _listar_ontrack_clientes_hist()
    idx_cli = None

    if not historico_cli:
        # backward compat: tentar arquivo único
        if not os.path.exists(_ONTRACK_CLI_FILE):
            st.info(
                'Nenhum dado publicado ainda. Na página **Vendedor-Cliente**, '
                'gere o relatório semanal e clique em **"📤 Publicar On Track para Gerência"**.'
            )
            return
        with open(_ONTRACK_CLI_FILE, 'r', encoding='utf-8') as f:
            snap = json.load(f)
    else:
        labels_cli = [_label_slug(s, 'mensal') + f"  —  {d.get('periodo', '-')}" for s, d in historico_cli]
        escolha_cli = st.selectbox(
            f'{len(historico_cli)} mês(es) disponível(is):',
            labels_cli,
            index=0,
            key='ger_ot_cli_sel',
        )
        idx_cli = labels_cli.index(escolha_cli)
        snap = historico_cli[idx_cli][1]

    pub_em         = snap.get('publicado_em', '')[:16].replace('T', ' ')
    periodo        = snap.get('periodo', '—')
    days_elapsed   = snap.get('days_elapsed', 1)
    days_in_month  = snap.get('days_in_month', 30)
    days_remaining = snap.get('days_remaining', 0)
    elapsed_pct    = snap.get('elapsed_pct', 0)
    totais         = snap.get('totais', {})
    rows           = snap.get('rows', [])

    st.caption(f"Período: **{periodo}**  |  Publicado em: **{pub_em}**  |  Dia {days_elapsed} de {days_in_month}")

    if not rows:
        st.info('Nenhum dado disponível no snapshot publicado.')
        return

    def _brl(v):
        s = f"{abs(v):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        return f"R$ {'-' if v < 0 else ''}{s}"

    _COR = {'🟢': '#2D6A4F', '🟡': '#B8860B', '🔴': '#C00000', '—': '#888'}

    tot_fat  = totais.get('fat', 0)
    tot_meta = totais.get('meta', 0)
    tot_pct  = totais.get('pct', 0)
    tot_rest = totais.get('rest', 0)
    tot_proj = totais.get('proj', 0)
    tot_dif  = totais.get('dif', 0)

    def _ot_status_cli(pct, elp):
        ratio = pct / elp if elp > 0 else 1.0
        if ratio >= 0.85:   return '🟢', 'No Ritmo',    ratio
        elif ratio >= 0.55: return '🟡', 'Atenção',      ratio
        else:               return '🔴', 'Fora do Ritmo', ratio

    g_em, g_lb, _ = _ot_status_cli(tot_pct, elapsed_pct)
    cor_s  = _COR.get(g_em, '#888')
    cor_d  = '#2D6A4F' if tot_dif >= 0 else '#C00000'

    # Cards de resumo
    st.markdown(f"""
    <div style="display:grid; grid-template-columns:repeat(6,1fr); gap:10px; margin-bottom:14px;">
      <div style="background:#f8f9fa; border-left:4px solid #2D6A4F; border-radius:8px; padding:12px 10px;">
        <div style="font-size:10px; color:#666; font-weight:700;">META MENSAL</div>
        <div style="font-size:15px; font-weight:700; color:#1B4332; margin-top:4px;">{_brl(tot_meta)}</div>
      </div>
      <div style="background:#f8f9fa; border-left:4px solid #4472C4; border-radius:8px; padding:12px 10px;">
        <div style="font-size:10px; color:#666; font-weight:700;">FATURAMENTO</div>
        <div style="font-size:15px; font-weight:700; color:#1F4E79; margin-top:4px;">{_brl(tot_fat)}</div>
      </div>
      <div style="background:#f8f9fa; border-left:4px solid {cor_s}; border-radius:8px; padding:12px 10px;">
        <div style="font-size:10px; color:#666; font-weight:700;">% ATINGIDO</div>
        <div style="font-size:15px; font-weight:700; color:{cor_s}; margin-top:4px;">{tot_pct*100:.1f}% {g_em}</div>
      </div>
      <div style="background:#f8f9fa; border-left:4px solid #C00000; border-radius:8px; padding:12px 10px;">
        <div style="font-size:10px; color:#666; font-weight:700;">VALOR RESTANTE</div>
        <div style="font-size:15px; font-weight:700; color:#C00000; margin-top:4px;">{_brl(tot_rest)}</div>
      </div>
      <div style="background:#f8f9fa; border-left:4px solid #375623; border-radius:8px; padding:12px 10px;">
        <div style="font-size:10px; color:#666; font-weight:700;">PROJEÇÃO MÊS</div>
        <div style="font-size:15px; font-weight:700; color:#375623; margin-top:4px;">{_brl(tot_proj)}</div>
      </div>
      <div style="background:#f8f9fa; border-left:4px solid {cor_d}; border-radius:8px; padding:12px 10px;">
        <div style="font-size:10px; color:#666; font-weight:700;">DIFERENÇA PROJ.</div>
        <div style="font-size:15px; font-weight:700; color:{cor_d}; margin-top:4px;">{'▲' if tot_dif >= 0 else '▼'} {_brl(abs(tot_dif))}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Barra de progresso
    prog_w = min(tot_pct, 1.0) * 100
    exp_w  = elapsed_pct * 100
    st.markdown(f"""
    <div style="margin-bottom:16px;">
      <div style="background:#e0e0e0; border-radius:6px; height:18px; position:relative;">
        <div style="background:{cor_s}; width:{prog_w:.1f}%; height:18px; border-radius:6px;
                    display:flex; align-items:center; justify-content:flex-end; padding-right:6px;">
          <span style="color:white; font-weight:700; font-size:11px;">{prog_w:.1f}%</span>
        </div>
        <div style="position:absolute; top:0; left:{exp_w:.1f}%; width:2px; height:18px; background:#333; opacity:.4;"></div>
      </div>
      <div style="font-size:10px; color:#999; margin-top:2px;">▲ Ritmo esperado: {exp_w:.0f}%  |  {days_remaining} dias restantes</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Comparativo vs mês anterior salvo ────────────────────────────────
    if idx_cli is not None and idx_cli + 1 < len(historico_cli):
        snap_ant_cli = historico_cli[idx_cli + 1][1]
        totais_ant_cli = snap_ant_cli.get('totais', {})
        st.subheader('📊 Comparativo vs mês anterior')
        pc1, pc2 = st.columns(2)
        comp_fat_cli = comparativo.calcular(tot_fat, totais_ant_cli.get('fat'))
        pc1.metric('Faturamento', _brl(tot_fat), delta=comparativo.formatar_variacao(comp_fat_cli))
        if totais_ant_cli.get('meta'):
            pct_ant_cli = (totais_ant_cli.get('fat', 0) / totais_ant_cli['meta']) if totais_ant_cli['meta'] else 0
            comp_pct_cli = comparativo.calcular(tot_pct, pct_ant_cli)
            pc2.metric('% Atingido', f'{tot_pct*100:.1f}%', delta=comparativo.formatar_variacao(comp_pct_cli))
        st.caption(f'Base de comparação: {_label_slug(historico_cli[idx_cli + 1][0], "mensal")}')

    st.divider()

    # Ranking de vendedores
    st.subheader('🏆 Ranking de Vendedores')
    vend_agg: dict = {}
    for r in rows:
        v = r['Vendedor']
        if v not in vend_agg:
            vend_agg[v] = {'fat': 0.0, 'meta': 0.0, 'mc_rs': 0.0}
        vend_agg[v]['fat']   += r.get('fat', 0)
        vend_agg[v]['meta']  += r.get('meta', 0)
        vend_agg[v]['mc_rs'] += r.get('mc_rs', 0)

    rank_rows = []
    for v, d in vend_agg.items():
        pct = d['fat'] / d['meta'] if d['meta'] > 0 else 0.0
        em, lb, ratio = _ot_status_cli(pct, elapsed_pct)
        tend = '↑ Acima' if ratio >= 1.0 else ('→ No ritmo' if ratio >= 0.85 else '↓ Abaixo')
        tend_cor = '#2D6A4F' if ratio >= 1.0 else ('#B8860B' if ratio >= 0.85 else '#C00000')
        rank_rows.append({'v': v, 'fat': d['fat'], 'meta': d['meta'],
                          'pct': pct, 'em': em, 'lb': lb, 'tend': tend, 'tend_cor': tend_cor})
    rank_rows.sort(key=lambda x: x['pct'], reverse=True)

    medals = ['🥇', '🥈', '🥉']
    cards = '<div style="display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:12px; margin-bottom:16px;">'
    for i, rv in enumerate(rank_rows):
        medal = medals[i] if i < 3 else f'#{i+1}'
        cor   = _COR.get(rv['em'], '#888')
        prog  = min(rv['pct'], 1.0) * 100
        cards += f"""
        <div style="background:white; border:1px solid #e0e0e0; border-radius:10px; padding:14px;
                    box-shadow:0 1px 4px rgba(0,0,0,.07);">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <span style="font-size:14px; font-weight:700;">{medal} {rv['v']}</span>
            <span style="background:{cor}; color:white; padding:2px 8px; border-radius:12px;
                         font-size:10px; font-weight:700;">{rv['em']} {rv['lb']}</span>
          </div>
          <div style="font-size:12px; color:#444; margin-bottom:6px;">
            Fat: <b>{_brl(rv['fat'])}</b> / Meta: {_brl(rv['meta'])}
          </div>
          <div style="background:#e0e0e0; border-radius:4px; height:10px; position:relative; margin-bottom:4px;">
            <div style="background:{cor}; width:{prog:.1f}%; height:10px; border-radius:4px;"></div>
            <div style="position:absolute; top:0; left:{exp_w:.1f}%; width:2px; height:10px; background:#333; opacity:.4;"></div>
          </div>
          <div style="display:flex; justify-content:space-between; font-size:11px; color:#666;">
            <span>{rv['pct']*100:.1f}% atingido</span>
            <span style="color:{rv['tend_cor']}; font-weight:700;">{rv['tend']}</span>
          </div>
        </div>"""
    cards += '</div>'
    st.markdown(cards, unsafe_allow_html=True)

    st.divider()

    # Tabela detalhada
    st.subheader(f'Detalhamento — {len(rows)} cliente(s)')
    df_rows = []
    for r in rows:
        df_rows.append({
            'Vendedor':    r['Vendedor'],
            'Cliente':     r['Cliente'],
            'Meta':        _brl(r['meta']) if r.get('tem_meta') else '—',
            'Faturamento': _brl(r['fat']),
            '% Atingido':  f"{r['pct_atg']*100:.1f}%" if r.get('tem_meta') else '—',
            'Restante':    _brl(r['restante']) if r.get('tem_meta') else '—',
            'Projeção':    _brl(r['projecao']),
            'Dif. Proj.':  ('+' if r['diferenca'] >= 0 else '') + _brl(r['diferenca']) if r.get('tem_meta') else '—',
            'MC R$':       _brl(r['mc_rs']),
            'MC %':        f"{r['mc_pct']:.1f}%",
            'Status':      f"{r['em']} {r['lb']}",
        })
    st.dataframe(pd.DataFrame(df_rows), use_container_width=True, hide_index=True)


# ── Prevenção de Perdas ───────────────────────────────────────────────────────

_NIVEL_COR = {
    '🔴 Crítico':         '#FFDADA',
    '🟠 Alta Prioridade': '#FFE8CC',
    '🟡 Atenção':         '#FFF9CC',
    '🟢 Controlado':      '#D8F3DC',
}


def _render_cruzamento_quebra():
    st.header('🔗 Cruzamento com Quebra')
    st.caption('Produtos que aparecem TANTO no estoque parado QUANTO nos relatórios de quebra — duplo risco operacional.')

    # PP mais recente (qualquer tipo) — lê da persistência real (data_store),
    # com fallback local; sobrevive a restart/redeploy do Streamlit Cloud.
    hist_pp = _prevperdas_listar('sem_venda') + _prevperdas_listar('mes_estoque')
    if not hist_pp:
        st.info('Nenhum dado de Prevenção de Perdas publicado.')
        return
    hist_pp.sort(key=lambda kv: kv[0], reverse=True)
    _slug_pp, snap_pp = hist_pp[0]

    prods_pp = snap_pp.get('produtos', [])
    tipo_pp  = '1 Semana Sem Venda' if snap_pp.get('tipo') == 'sem_venda' else '1 Mês em Estoque'
    pub_pp   = snap_pp.get('publicado_em', '')[:10]

    # Quebra mais recente (semanal, ou mensal como fallback) — idem
    snap_qbr = None
    label_qbr = ''
    for tipo_q in ('semanal', 'mensal'):
        hist_q = _qbr_listar(tipo_q)
        if hist_q:
            _slug_q, snap_qbr = hist_q[0]
            label_qbr = f"Quebra {tipo_q} — {snap_qbr.get('periodo','-')}"
            break

    if not snap_qbr:
        st.info('Nenhum dado de Quebra disponível. Processe um PDF na página **Quebras** primeiro.')
        return

    st.caption(
        f"Prevenção de Perdas: **{tipo_pp}** (publicado {pub_pp})  ·  "
        f"Quebra: **{label_qbr}**"
    )

    # Grupos de quebra como palavras-chave
    grupos_qbr = snap_qbr.get('grupos', [])
    palavras_qbr = []
    for g in grupos_qbr:
        nome = g.get('grupo', '')
        for token in nome.upper().split():
            if len(token) >= 3:
                palavras_qbr.append((token, g.get('cx', 0), g.get('categoria', ''), nome))

    if not palavras_qbr:
        st.info('Os dados de Quebra não possuem grupos de produto para cruzar.')
        return

    # Cruzar por nome
    cruzados = []
    for p in prods_pp:
        nome_prod = p['produto'].upper()
        hits = [pw for pw in palavras_qbr if pw[0] in nome_prod]
        if hits:
            melhor = max(hits, key=lambda x: x[1])
            cruzados.append({
                'Prioridade PP':   p['prioridade'],
                'Produto':         p['produto'],
                'Categoria':       map_categoria(p['produto']),
                'Responsável':     p['responsavel'],
                'Valor Parado (R$)': p['valor_estoque'],
                'Grupo Quebra':    melhor[3],
                'CX Quebradas':    melhor[1],
                'Ação Recomendada': p['acao'],
            })

    if not cruzados:
        st.success('✅ Nenhum produto em comum entre o estoque parado e os relatórios de quebra.')
        return

    st.warning(f"⚠️ **{len(cruzados)} produto(s)** com duplo risco: parado em estoque E com quebra registrada.")

    df_cruz = pd.DataFrame(cruzados).sort_values('Valor Parado (R$)', ascending=False)
    st.dataframe(
        df_cruz,
        use_container_width=True,
        hide_index=True,
        column_config={
            'Valor Parado (R$)': st.column_config.NumberColumn(format='R$ %.2f'),
            'CX Quebradas':      st.column_config.NumberColumn(format='%.0f'),
        }
    )


def _render_perdas_realizadas_ger():
    st.header('📊 Histórico de Perdas Realizadas')

    if not os.path.isdir(_PERDAS_DIR):
        st.info('Nenhuma perda registrada ainda. Use a aba **📋 Registrar Perda** na página Prevenção de Perdas.')
        return

    arqs = sorted([f for f in os.listdir(_PERDAS_DIR) if f.endswith('.json')], reverse=True)
    if not arqs:
        st.info('Nenhuma perda registrada ainda.')
        return

    _MESES_PT = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']

    def _label_mes(slug):
        try:
            y, m = slug.split('-')
            return f"{_MESES_PT[int(m)-1]} / {y}"
        except Exception:
            return slug

    labels = [_label_mes(a.replace('.json','')) for a in arqs]
    escolha = st.selectbox(f'{len(arqs)} mês(es) com registros:', labels, index=0,
                            key='ger_perdas_sel')
    arq_sel = arqs[labels.index(escolha)]

    try:
        with open(os.path.join(_PERDAS_DIR, arq_sel), 'r', encoding='utf-8') as f:
            lista = json.load(f)
    except Exception:
        st.error('Erro ao carregar dados.')
        return

    if not lista:
        st.info('Nenhum registro neste mês.')
        return

    total_cx  = sum(r.get('quantidade_cx', 0) for r in lista)
    total_val = sum(r.get('valor_rs', 0) for r in lista)
    motivos   = {}
    for r in lista:
        m = r.get('motivo', 'Outro')
        motivos[m] = motivos.get(m, 0) + 1

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Registros",       len(lista))
    c2.metric("Total CX",        f"{total_cx:,.3f}".replace(',','X').replace('.',',').replace('X','.'))
    tv = f"R$ {total_val:,.2f}".replace(',','X').replace('.',',').replace('X','.')
    c3.metric("Valor Perdido",   tv)
    top_motivo = max(motivos, key=motivos.get) if motivos else '—'
    c4.metric("Motivo Principal", top_motivo)

    st.divider()

    # Breakdown por motivo
    if len(motivos) > 1:
        df_mot = pd.DataFrame([{'Motivo': k, 'Qtd': v} for k,v in sorted(motivos.items(), key=lambda x:-x[1])])
        st.subheader('Por Motivo')
        st.bar_chart(df_mot.set_index('Motivo')['Qtd'], color='#2D6A4F')

    # Tabela completa
    st.subheader(f'Todos os registros — {len(lista)}')
    df_p = pd.DataFrame(lista)
    cols_disp = ['data','produto','quantidade_cx','valor_rs','motivo','observacao']
    cols_disp = [c for c in cols_disp if c in df_p.columns]
    df_p = df_p[cols_disp].copy()
    df_p.columns = ['Data','Produto','CX','Valor (R$)','Motivo','Observação'][:len(cols_disp)]
    st.dataframe(df_p, use_container_width=True, hide_index=True,
                 column_config={
                     'CX':        st.column_config.NumberColumn(format='%.3f'),
                     'Valor (R$)':st.column_config.NumberColumn(format='R$ %.2f'),
                 })

    # Download CSV
    csv = df_p.to_csv(index=False, sep=';', decimal=',').encode('utf-8-sig')
    st.download_button('⬇️ Baixar CSV', data=csv,
                        file_name=f"perdas_{arq_sel.replace('.json','')}.csv",
                        mime='text/csv')


def _prevperdas_listar(tipo):
    """Lista snapshots de prevenção de perdas de um tipo (sem_venda / mes_estoque)
    — lê da persistência real (data_store) primeiro; arquivos locais entram
    como complemento/fallback."""
    items = {}
    try:
        for slug in ds.list_periodos(MOD_PREVPERDAS, 'diario'):
            if tipo not in slug:
                continue
            registro = ds.load_current(MOD_PREVPERDAS, 'diario', slug)
            if registro:
                items[slug] = registro['valores']
    except Exception:
        pass
    if os.path.isdir(_PREVPERDAS_DIR):
        for fname in sorted(os.listdir(_PREVPERDAS_DIR), reverse=True):
            if not fname.endswith('.json') or tipo not in fname:
                continue
            slug = fname.replace('.json', '')
            if slug in items:
                continue
            try:
                with open(os.path.join(_PREVPERDAS_DIR, fname), 'r', encoding='utf-8') as f:
                    data = json.load(f)
                items[slug] = data
            except Exception:
                pass
    return sorted(items.items(), key=lambda kv: kv[0], reverse=True)


def _render_prevperdas_secao(tipo, titulo):
    st.header(f'🚨 {titulo}')
    historico = _prevperdas_listar(tipo)

    if not historico:
        st.info(
            'Nenhum dado publicado ainda. Na página **Prevenção de Perdas**, '
            'processe um PDF e clique em **"📤 Publicar na Gerência"**.'
        )
        return

    # Selectbox de datas
    labels = []
    for slug, d in historico:
        data_str = slug.split('_')[0]  # YYYY-MM-DD
        try:
            dt = datetime.datetime.strptime(data_str, '%Y-%m-%d')
            label = dt.strftime('%d/%m/%Y')
        except Exception:
            label = data_str
        pub = d.get('publicado_em', '')[:16].replace('T', ' ')
        labels.append(f"{label}  —  Publicado: {pub}")

    escolha = st.selectbox(f'{len(historico)} publicação(ões):', labels, index=0,
                            key=f'ger_pp_sel_{tipo}')
    idx_pp = labels.index(escolha)
    snap = historico[idx_pp][1]

    resumo = snap.get('resumo', {})
    emissao = snap.get('emissao', '-')
    periodo = snap.get('periodo', '')

    st.caption(
        f"Emissão: **{emissao}**"
        + (f"  |  Período desde: **{periodo}**" if periodo else "")
        + f"  |  Publicado em: **{snap.get('publicado_em','')[:16].replace('T',' ')}**"
    )

    # Cards
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("📦 Total",             resumo.get('total', 0))
    c2.metric("🔴 Críticos",          resumo.get('criticos', 0))
    c3.metric("🟠 Alta Prioridade",   resumo.get('alta_prioridade', 0))
    c4.metric("🟡 Atenção",           resumo.get('atencao', 0))
    vr = resumo.get('valor_risco', 0)
    vr_fmt = f"R$ {vr:,.0f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    c5.metric("💰 Valor em Risco",    vr_fmt)
    c6.metric("📅 Estoque ≥ 30 dias", resumo.get('estoque_30d', 0))

    # ── Comparativo vs publicação anterior (menor é melhor — menos risco) ──
    if idx_pp + 1 < len(historico):
        resumo_ant = historico[idx_pp + 1][1].get('resumo', {})
        st.subheader('📊 Comparativo vs publicação anterior')
        pp1, pp2, pp3 = st.columns(3)
        comp_total_pp = comparativo.calcular(resumo.get('total', 0), resumo_ant.get('total'), menor_e_melhor=True)
        comp_crit_pp  = comparativo.calcular(resumo.get('criticos', 0), resumo_ant.get('criticos'), menor_e_melhor=True)
        comp_vr_pp    = comparativo.calcular(vr, resumo_ant.get('valor_risco'), menor_e_melhor=True)
        pp1.metric('📦 Total', resumo.get('total', 0), delta=comparativo.formatar_variacao(comp_total_pp, casas=1))
        pp2.metric('🔴 Críticos', resumo.get('criticos', 0), delta=comparativo.formatar_variacao(comp_crit_pp, casas=1))
        pp3.metric('💰 Valor em Risco', vr_fmt, delta=comparativo.formatar_variacao(comp_vr_pp, casas=1))
        st.caption('Base de comparação: publicação anterior')

    st.divider()

    # Tabela de produtos
    produtos = snap.get('produtos', [])
    if not produtos:
        st.info('Nenhum produto no snapshot.')
        return

    df_pp = pd.DataFrame(produtos)
    df_pp = df_pp.rename(columns={
        'prioridade':     'Prioridade',
        'produto':        'Produto',
        'responsavel':    'Responsável',
        'dias_estoque':   'Dias em Estoque',
        'dias_sem_venda': 'Dias sem Venda',
        'saldo_cx':       'Saldo (cx)',
        'qtd_vendida':    'Qtd Vendida',
        'valor_estoque':  'Valor em Estoque (R$)',
        'acao':           'Ação Recomendada',
    })

    _COR_PP = {
        '🔴 Crítico':        'background-color:#FFCCCC',
        '🟠 Alta Prioridade':'background-color:#FFE0B2',
        '🟡 Atenção':        'background-color:#FFFDE7',
        '🟢 Controlado':     'background-color:#E8F5E9',
    }

    def _colorir_linha(row):
        cor = _COR_PP.get(row.get('Prioridade', ''), '')
        return [cor] * len(row)

    styled = df_pp.style.apply(_colorir_linha, axis=1).format({
        'Saldo (cx)':           '{:.3f}',
        'Qtd Vendida':          '{:.3f}',
        'Valor em Estoque (R$)':'R$ {:.2f}',
        'Dias em Estoque':      '{:.0f}',
        'Dias sem Venda':       '{:.0f}',
    }, na_rep='-')

    st.dataframe(styled, use_container_width=True, hide_index=True)


# ── Metas Gerais ────────────────────────────────────────────────────────────

_GER_STATUS_LABEL_COR = {
    on_track.STATUS_VERDE:    ('#D8EFE3', '#1B4332'),
    on_track.STATUS_ATENCAO:  ('#FEF9C3', '#7D6608'),
    on_track.STATUS_FORA:     ('#FADADD', '#7A1F2B'),
    on_track.STATUS_SEM_META: ('#EDEDED', '#555555'),
}


def _render_indicador_mg(titulo, unidade_fmt, meta, realizado, ot, completude_msg=None):
    bg, fg = _GER_STATUS_LABEL_COR[ot['status']]
    st.markdown(f"""
    <div style="background:{bg}; color:{fg}; border-radius:10px; padding:0.9rem 1rem; margin-bottom:0.5rem;">
        <div style="font-weight:600; font-size:0.95rem;">{ot['emoji']} {titulo}</div>
        <div style="font-size:1.4rem; font-weight:700; margin-top:0.2rem;">
            {unidade_fmt(realizado) if realizado is not None else '—'}
        </div>
        <div style="font-size:0.82rem; opacity:0.85;">
            Meta: {unidade_fmt(meta) if meta else '—'}
            {'  |  ' + ot['label'] if meta else ''}
            {f"  |  {ot['pct_atingido']*100:.0f}% da meta" if ot.get('pct_atingido') is not None else ''}
        </div>
        {f'<div style="font-size:0.78rem; opacity:0.75; margin-top:0.2rem;">Projeção de fechamento: {unidade_fmt(ot["projecao_fechamento"])}</div>' if ot.get('projecao_fechamento') is not None else ''}
    </div>
    """, unsafe_allow_html=True)
    if completude_msg:
        st.caption(completude_msg)


def _render_metas_gerais():
    st.header('🌐 Meta Geral')
    st.caption(
        'Painel consolidado — Faturamento, Volume, Margem e Quebra da empresa inteira. '
        'Independente das Metas Semanais. O "Realizado" é somado automaticamente a partir '
        'dos módulos Vendedor-Cliente e Quebras (não precisa digitar de novo aqui).'
    )

    tipos_mg = [t for t in periodo_mod.TIPOS_PERIODO if t != 'semanal']
    col_tipo, col_periodo = st.columns([1, 2])
    with col_tipo:
        tipo_mg = st.selectbox(
            'Tipo de período', tipos_mg,
            format_func=periodo_mod.rotulo_tipo, index=0, key='mg_tipo',
        )
    with col_periodo:
        opcoes_periodo = periodo_mod.listar_periodos(tipo_mg, n=16)
        ref_mg = st.selectbox(
            'Período', opcoes_periodo,
            format_func=lambda r: periodo_mod.rotulo(tipo_mg, r), index=0, key='mg_periodo',
        )

    # ── Realizado (agregado automaticamente) ────────────────────────────────
    rv = mg.realizado_vendas(tipo_mg, ref_mg)
    rq = mg.realizado_quebra(tipo_mg, ref_mg)
    ref_ant_mg = periodo_mod.periodo_anterior(tipo_mg, ref_mg)
    rv_ant = mg.realizado_vendas(tipo_mg, ref_ant_mg)
    rq_ant = mg.realizado_quebra(tipo_mg, ref_ant_mg)

    tab_empresa, tab_vendedor = st.tabs(['🏢 Empresa', '👤 Vendedor'])

    # =========================================================================
    # ABA EMPRESA — consolidado (equivalente à aba "GERAL" do Vendedor-Cliente)
    # =========================================================================
    with tab_empresa:
        meta_atual = mg.carregar_meta(tipo_mg, ref_mg) or {}
        with st.expander(f'🎯 Definir/editar meta — {periodo_mod.rotulo(tipo_mg, ref_mg)}'):
            with st.form(key='mg_form_meta'):
                mc1, mc2 = st.columns(2)
                with mc1:
                    meta_fat = st.number_input('Meta Faturamento (R$)', min_value=0.0,
                                                value=float(meta_atual.get('faturamento') or 0.0), step=1000.0)
                    meta_vol = st.number_input('Meta Volume (CX)', min_value=0.0,
                                                value=float(meta_atual.get('volume') or 0.0), step=10.0)
                with mc2:
                    meta_marg = st.number_input('Meta Margem (%)', min_value=0.0,
                                                 value=float(meta_atual.get('margem_pct') or 0.0), step=1.0)
                    meta_qbr = st.number_input('Teto de Quebra (CX)', min_value=0.0,
                                                value=float(meta_atual.get('quebra_max_cx') or 0.0), step=10.0)
                if st.form_submit_button('💾 Salvar meta', type='primary'):
                    mg.salvar_meta(tipo_mg, ref_mg, meta_fat, meta_vol, meta_marg, meta_qbr,
                                    usuario=st.session_state.get('usuario_nome'))
                    st.success('Meta salva.')
                    st.rerun()

        pct_tempo_mg = periodo_mod.pct_tempo_decorrido(tipo_mg, ref_mg)
        _completude_msgs = {
            'sem_dado': f'⚪ Sem dado publicado ainda para {periodo_mod.rotulo(tipo_mg, ref_mg)} (fonte: {rv.get("origem","-")}).',
            'parcial':  f'🟡 Dado parcial: {len(rv.get("meses_com_dado", []))}/{len(rv.get("meses_total", []))} mês(es) do período têm publicação.',
            'completo': None,
        }

        st.subheader('Indicadores da Empresa')
        ic1, ic2, ic3, ic4 = st.columns(4)
        with ic1:
            ot_fat = on_track.calcular(meta_atual.get('faturamento') or 0, rv.get('faturamento') or 0,
                                        tipo_mg, ref_mg, pct_tempo_decorrido=pct_tempo_mg)
            _render_indicador_mg('Faturamento', lambda x: f'R$ {x:,.0f}',
                                  meta_atual.get('faturamento'), rv.get('faturamento'), ot_fat,
                                  _completude_msgs.get(rv['completude']))
        with ic2:
            ot_vol = on_track.calcular(meta_atual.get('volume') or 0, rv.get('volume') or 0,
                                        tipo_mg, ref_mg, pct_tempo_decorrido=pct_tempo_mg)
            _render_indicador_mg('Volume (CX)', lambda x: f'{x:,.0f} cx',
                                  meta_atual.get('volume'), rv.get('volume'), ot_vol)
        with ic3:
            ot_marg = on_track.calcular(meta_atual.get('margem_pct') or 0, rv.get('margem_pct') or 0,
                                         tipo_mg, ref_mg, pct_tempo_decorrido=pct_tempo_mg)
            _render_indicador_mg('Margem (%)', lambda x: f'{x:.2f}%',
                                  meta_atual.get('margem_pct'), rv.get('margem_pct'), ot_marg)
        with ic4:
            ot_qbr = mg.status_quebra(meta_atual.get('quebra_max_cx'), rq.get('total_cx'), tipo_mg, ref_mg)
            _render_indicador_mg('Quebra (CX)', lambda x: f'{x:,.0f} cx',
                                  meta_atual.get('quebra_max_cx'), rq.get('total_cx'), ot_qbr,
                                  _completude_msgs.get(rq['completude']))

        # ── Comparativo vs período anterior ──────────────────────────────────
        st.subheader('📊 Comparativo vs período anterior')
        if rv.get('faturamento') is not None and rv_ant.get('faturamento') is not None:
            cc1, cc2, cc3, cc4 = st.columns(4)
            for _col, _lab, _atual, _ant, _fmt, _menor_melhor in [
                (cc1, 'Faturamento', rv.get('faturamento'), rv_ant.get('faturamento'), lambda x: f'R$ {x:,.0f}', False),
                (cc2, 'Volume (CX)', rv.get('volume'), rv_ant.get('volume'), lambda x: f'{x:,.0f}', False),
                (cc3, 'Margem (%)', rv.get('margem_pct'), rv_ant.get('margem_pct'), lambda x: f'{x:.2f}%', False),
                (cc4, 'Quebra (CX)', rq.get('total_cx'), rq_ant.get('total_cx'), lambda x: f'{x:,.0f}', True),
            ]:
                if _atual is None:
                    continue
                _comp = comparativo.calcular(_atual, _ant, menor_e_melhor=_menor_melhor)
                _col.metric(_lab, _fmt(_atual), delta=comparativo.formatar_variacao(_comp))
            st.caption(f'Base de comparação: {periodo_mod.rotulo(tipo_mg, ref_ant_mg)}')
        else:
            st.info('Sem dado suficiente no período anterior para comparar.')

        # ── Evolução ──────────────────────────────────────────────────────────
        st.subheader('📈 Evolução')
        hist_refs = list(reversed(periodo_mod.listar_periodos(tipo_mg, n=8, ate=ref_mg)))
        evol_rows = []
        for r in hist_refs:
            rv_h = mg.realizado_vendas(tipo_mg, r)
            rq_h = mg.realizado_quebra(tipo_mg, r)
            evol_rows.append({
                'Período': periodo_mod.rotulo(tipo_mg, r),
                'Faturamento': rv_h.get('faturamento') or 0,
                'Quebra (CX)': rq_h.get('total_cx') or 0,
            })
        if evol_rows:
            import pandas as _pd
            df_evol = _pd.DataFrame(evol_rows).set_index('Período')
            ev1, ev2 = st.columns(2)
            with ev1:
                st.caption('Faturamento (R$)')
                st.bar_chart(df_evol[['Faturamento']], color='#2D6A4F')
            with ev2:
                st.caption('Quebra (CX)')
                st.bar_chart(df_evol[['Quebra (CX)']], color='#C00000')

    # =========================================================================
    # ABA VENDEDOR — ranking + detalhe individual (equivalente às abas por
    # vendedor do Vendedor-Cliente)
    # =========================================================================
    with tab_vendedor:
        vendedores_mg = rv.get('vendedores') or {}
        if not vendedores_mg:
            st.info('Sem dado de vendedores para este período ainda.')
        else:
            st.subheader('🏆 Ranking de Vendedores')
            ordenar_por = st.selectbox('Ordenar por', ['Faturamento', 'Volume (CX)', 'Margem %'],
                                        key='mg_rank_ordenar')
            fat_total_emp = sum(v.get('fat', 0) or 0 for v in vendedores_mg.values())
            rows_rank = []
            for nome, v in vendedores_mg.items():
                rows_rank.append({
                    'Vendedor': nome,
                    'Faturamento': v.get('fat', 0) or 0,
                    'Volume (CX)': v.get('vol', 0) or 0,
                    'Margem %': v.get('mc_pct', 0) or 0,
                    'Participação': (v.get('fat', 0) or 0) / fat_total_emp * 100 if fat_total_emp else 0,
                })
            chave_ord = {'Faturamento': 'Faturamento', 'Volume (CX)': 'Volume (CX)', 'Margem %': 'Margem %'}[ordenar_por]
            rows_rank.sort(key=lambda r: r[chave_ord], reverse=True)
            for i, r in enumerate(rows_rank, start=1):
                r['#'] = i
            df_rank = pd.DataFrame(rows_rank)[['#', 'Vendedor', 'Faturamento', 'Volume (CX)', 'Margem %', 'Participação']]
            styled_rank = df_rank.style.format({
                'Faturamento': 'R$ {:,.2f}', 'Volume (CX)': '{:,.3f}',
                'Margem %': '{:.2f}%', 'Participação': '{:.1f}%',
            })
            st.dataframe(styled_rank, use_container_width=True, hide_index=True)

            # Drill-down individual
            st.divider()
            st.subheader('🔎 Detalhe por vendedor')
            vend_sel_mg = st.selectbox('Selecionar vendedor', sorted(vendedores_mg.keys()), key='mg_vend_sel')
            v_sel = vendedores_mg.get(vend_sel_mg, {})
            vend_ant = (rv_ant.get('vendedores') or {}).get(vend_sel_mg, {})
            dc1, dc2, dc3, dc4 = st.columns(4)
            dc1.metric('Faturamento', f"R$ {v_sel.get('fat', 0):,.2f}")
            dc2.metric('Volume (CX)', f"{v_sel.get('vol', 0):,.3f}")
            dc3.metric('Margem %', f"{v_sel.get('mc_pct', 0):.2f}%")
            dc4.metric('Participação na empresa',
                       f"{(v_sel.get('fat', 0) / fat_total_emp * 100) if fat_total_emp else 0:.1f}%")
            if vend_ant:
                st.caption('Comparativo vs período anterior')
                comp_fat_v = comparativo.calcular(v_sel.get('fat', 0), vend_ant.get('fat'))
                comp_vol_v = comparativo.calcular(v_sel.get('vol', 0), vend_ant.get('vol'))
                dcc1, dcc2 = st.columns(2)
                dcc1.metric('Faturamento', f"R$ {v_sel.get('fat', 0):,.2f}",
                            delta=comparativo.formatar_variacao(comp_fat_v))
                dcc2.metric('Volume (CX)', f"{v_sel.get('vol', 0):,.3f}",
                            delta=comparativo.formatar_variacao(comp_vol_v))


# ── Auth ──────────────────────────────────────────────────────────────────────
if not _check_auth():
    st.stop()

def _render_rentabilidade_resumo():
    st.header('💰 Rentabilidade e Margens — Resumo')
    st.caption('Visão consolidada para a Gerência (reaproveita o mesmo motor de cálculo do módulo '
               'completo -- nenhuma lógica de faturamento/custo/margem foi duplicada aqui).')
    try:
        st.page_link('pages/6_Rentabilidade_Margens_OTHIL.py',
                      label='Abrir módulo completo (filtros, rankings, matriz, histórico) →', icon='💰')
    except Exception:
        pass

    itens_base, avisos = rent.carregar_base_consolidada()
    if not itens_base:
        st.info('Ainda não há dados suficientes. Faça upload de pelo menos um Relatório Diário, '
                'Semanal ou Mensal.')
        return
    if avisos:
        st.caption(f'ℹ️ {len(avisos)} registro(s) não incluído(s) no histórico consolidado (evita duplicidade).')

    col_tipo, col_periodo = st.columns([1, 2])
    with col_tipo:
        tipo_r = st.selectbox('Período', periodo_mod.TIPOS_PERIODO, format_func=periodo_mod.rotulo_tipo,
                               index=1, key='ger_rent_tipo')
    opcoes_r = rent.periodos_disponiveis(itens_base, tipo_r)
    if not opcoes_r:
        st.warning('Nenhum dado disponível para esse tipo de período.')
        return
    with col_periodo:
        ref_r = st.selectbox('Referência', opcoes_r, format_func=lambda r: periodo_mod.rotulo(tipo_r, r),
                              key='ger_rent_periodo')

    itens_p = rent.filtrar_periodo(itens_base, tipo_r, ref_r)
    if not itens_p:
        st.info('Sem dados para este período.')
        return
    kpi = rent.agregar(itens_p)
    ref_ant = periodo_mod.periodo_anterior(tipo_r, ref_r)
    itens_ant = rent.filtrar_periodo(itens_base, tipo_r, ref_ant)
    kpi_ant = rent.agregar(itens_ant) if itens_ant else None

    def _c(chave):
        return comparativo.calcular(kpi[chave], kpi_ant[chave]) if kpi_ant else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric('Faturamento', f"R$ {kpi['faturamento']:,.2f}",
              delta=comparativo.formatar_variacao(_c('faturamento')) if kpi_ant else None)
    c2.metric('Margem R$', f"R$ {kpi['margem_rs']:,.2f}",
              delta=comparativo.formatar_variacao(_c('margem_rs')) if kpi_ant else None)
    c3.metric('Margem %', f"{kpi['margem_pct']:.2f}%",
              delta=comparativo.formatar_variacao(_c('margem_pct')) if kpi_ant else None)
    c4.metric('Ticket Médio', f"R$ {kpi['ticket_medio']:,.2f}",
              delta=comparativo.formatar_variacao(_c('ticket_medio')) if kpi_ant else None)

    rcol1, rcol2, rcol3 = st.columns(3)
    with rcol1:
        st.markdown('**Top 5 Vendedores (Margem R$)**')
        top_v = sorted(rent.por_vendedor(itens_p), key=lambda l: l['margem_rs'], reverse=True)[:5]
        st.dataframe(pd.DataFrame([{'Vendedor': v['chave'], 'Margem R$': v['margem_rs'],
                                     'Margem %': v['margem_pct']} for v in top_v]),
                     use_container_width=True, hide_index=True)
    with rcol2:
        st.markdown('**Top 5 Clientes (Margem R$)**')
        top_c = sorted(rent.por_cliente(itens_p), key=lambda l: l['margem_rs'], reverse=True)[:5]
        st.dataframe(pd.DataFrame([{'Cliente': c['chave'], 'Margem R$': c['margem_rs'],
                                     'Margem %': c['margem_pct']} for c in top_c]),
                     use_container_width=True, hide_index=True)
    with rcol3:
        st.markdown('**Top 5 Produtos (Margem R$)**')
        top_p = sorted(rent.por_produto(itens_p), key=lambda l: l['margem_rs'], reverse=True)[:5]
        st.dataframe(pd.DataFrame([{'Produto': p['chave'], 'Margem R$': p['margem_rs'],
                                     'Margem %': p['margem_pct']} for p in top_p]),
                     use_container_width=True, hide_index=True)

    alertas = rent.alertas_gerenciais(itens_p, itens_ant or None)
    st.markdown('**🚨 Pontos de Atenção**')
    if not alertas:
        st.success('Nenhum ponto de atenção identificado.')
    else:
        for a in alertas[:5]:
            icone = '🔴' if a['severidade'] == 'critico' else '🟡'
            st.markdown(f"{icone} **{a['tipo']}** — {a['detalhe']}")
        if len(alertas) > 5:
            st.caption(f'+ {len(alertas) - 5} outro(s) ponto(s) de atenção. Veja o módulo completo para a lista inteira.')


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="display:flex; align-items:center; gap:1rem; margin-bottom:1rem;">
    <div style="background:#2D6A4F; color:white; padding:0.3rem 1rem;
                border-radius:8px; font-weight:600; font-size:0.9rem;">OTHIL</div>
    <h1 style="margin:0; color:#1B4332; font-size:1.6rem;">Área de Gerência</h1>
</div>
""", unsafe_allow_html=True)

if st.button('🔒 Sair', key='_gerencia_logout'):
    st.session_state['_gerencia_auth'] = False
    st.rerun()

st.divider()

# ── Grupos de abas ───────────────────────────────────────────────────────────
grp_vendas, grp_metas, grp_metas_gerais, grp_rentabilidade, grp_clientes, grp_quebras, grp_prevperdas = st.tabs([
    '📊 Dashboards',
    '🎯 Metas Semanais',
    '🌐 Metas Gerais',
    '💰 Rentabilidade',
    '👥 Clientes',
    '📦 Quebras',
    '🚨 Prevenção de Perdas',
])

# ── VENDAS ────────────────────────────────────────────────────────────────────
with grp_vendas:
    tab_d, tab_s, tab_m = st.tabs([
        '📅 Diário',
        '📆 Semanal',
        '🗓️ Mensal',
    ])
    with tab_d:
        _render_secao_dash('diario', 'Dashboards Diários', '📅')
    with tab_s:
        _render_secao_dash('semanal', 'Dashboards Semanais', '📆')
    with tab_m:
        _render_secao_dash('mensal', 'Dashboards Mensais', '🗓️')

# ── METAS ─────────────────────────────────────────────────────────────────────
with grp_metas:
    tab_ot, tab_fech = st.tabs([
        '📊 On Track',
        '🏁 Fechamentos Semanais',
    ])
    with tab_ot:
        _render_ontrack_publicado()
    with tab_fech:
        _render_fechamentos_semanais()

# ── METAS GERAIS ──────────────────────────────────────────────────────────────
with grp_metas_gerais:
    _render_metas_gerais()

# ── RENTABILIDADE ─────────────────────────────────────────────────────────────
with grp_rentabilidade:
    _render_rentabilidade_resumo()

# ── CLIENTES ──────────────────────────────────────────────────────────────────
with grp_clientes:
    tab_ot_cli, tab_rec = st.tabs([
        '👥 On Track Clientes',
        '🔄 Ranking Recorrência',
    ])
    with tab_ot_cli:
        _render_ontrack_clientes()
    with tab_rec:
        st.header('👥 Ranking de Clientes — Recorrência')
        _hist_rec_ger = _listar_recorrencias_ger()
        if not _hist_rec_ger:
            st.info('Nenhum ranking disponível. Processe um PDF na página **Recorrência** primeiro.')
        else:
            _labels_rec = [f"{v.get('periodo','-')}  —  emissão {v.get('emissao','-')}  "
                           f"({(ts or '')[:16].replace('T',' ')})" for _, v, ts in _hist_rec_ger]
            _escolha_rec = st.selectbox(f'{len(_hist_rec_ger)} publicação(ões):', _labels_rec,
                                         index=0, key='ger_rec_sel')
            _idx_rec = _labels_rec.index(_escolha_rec)
            rec = _hist_rec_ger[_idx_rec][1]

            periodo_r = rec.get('periodo', '-')
            emissao_r = rec.get('emissao', '-')
            gerado_r  = rec.get('gerado_em', '')[:16].replace('T', ' ')
            totais    = rec.get('totais', {})
            st.caption(f'Período: {periodo_r}  |  Emissão: {emissao_r}  |  Gerado em: {gerado_r}')
            if totais:
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric('Faturamento', f'R$ {totais.get("faturamento", 0):,.2f}')
                c2.metric('MC R$', f'R$ {totais.get("mc_rs", 0):,.2f}')
                c3.metric('MC %', f'{totais.get("mc_pct", 0):.2f}%')
                c4.metric('Total CX', f'{totais.get("caixas", 0):,.3f}')
                c5.metric('Clientes', totais.get('n_clientes', '-'))

            # Comparativo vs a publicação anterior na lista
            if _idx_rec + 1 < len(_hist_rec_ger):
                _val_ant_rec = _hist_rec_ger[_idx_rec + 1][1]
                _tot_ant_rec = _val_ant_rec.get('totais', {})
                st.subheader('📊 Comparativo vs período anterior')
                cc1, cc2, cc3, cc4 = st.columns(4)
                for _col, _lab, _chave, _fmt in [
                    (cc1, 'Faturamento', 'faturamento', lambda x: f'R$ {x:,.2f}'),
                    (cc2, 'MC R$',       'mc_rs',       lambda x: f'R$ {x:,.2f}'),
                    (cc3, 'Total CX',    'caixas',      lambda x: f'{x:,.3f}'),
                    (cc4, 'Clientes',    'n_clientes',  lambda x: f'{x:,.0f}'),
                ]:
                    _atual_v = totais.get(_chave, 0)
                    _comp = comparativo.calcular(_atual_v, _tot_ant_rec.get(_chave))
                    _col.metric(_lab, _fmt(_atual_v), delta=comparativo.formatar_variacao(_comp))
                st.caption(f'Base de comparação: {_val_ant_rec.get("periodo","-")}')

            clientes = rec.get('clientes', [])
            if clientes:
                df = pd.DataFrame(clientes)
                top30 = df.head(30).set_index('Cliente')[['Faturamento R$']]
                st.subheader('Top 30 por Faturamento')
                st.bar_chart(top30, color='#2D6A4F')
                st.subheader(f'Todos os clientes ({len(df)})')
                styled = df.style.format({
                    'Faturamento R$': 'R$ {:,.2f}',
                    'Caixas': '{:,.3f}',
                    'MC R$': 'R$ {:,.2f}',
                    'MC %': '{:.2f}%',
                })
                st.dataframe(styled, use_container_width=True, hide_index=True)
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    '⬇️ Baixar ranking CSV',
                    data=csv,
                    file_name=f'ranking_clientes_{emissao_r.replace("/","")}.csv',
                    mime='text/csv',
                )

# ── QUEBRAS ───────────────────────────────────────────────────────────────────
with grp_quebras:
    tab_qbr_s, tab_qbr_m, tab_qbr_comp = st.tabs([
        '📦 Semanal',
        '📦 Mensal',
        '🔀 Comparativo',
    ])
    with tab_qbr_s:
        _render_quebra_secao('semanal', 'Quebras Semanais', '📦')
    with tab_qbr_m:
        _render_quebra_secao('mensal', 'Quebras Mensais', '📦')
    with tab_qbr_comp:
        _render_quebra_comparativo()

# ── PREVENÇÃO DE PERDAS ───────────────────────────────────────────────────────
with grp_prevperdas:
    tab_pp_sv, tab_pp_me, tab_pp_cruz = st.tabs([
        '🕐 1 Semana Sem Venda',
        '📦 1 Mês em Estoque',
        '🔗 Cruzamento com Quebra',
    ])
    with tab_pp_sv:
        _render_prevperdas_secao('sem_venda', '1 Semana Sem Venda')
    with tab_pp_me:
        _render_prevperdas_secao('mes_estoque', '1 Mês em Estoque')
    with tab_pp_cruz:
        _render_cruzamento_quebra()
