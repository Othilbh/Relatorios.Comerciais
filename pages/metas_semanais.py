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
from parsers_diario import parse_vendas_pdftotext
from parsers_vendedor import parse_totais_vendedor
from calc import (compute_metas, VENDEDORES_PADRAO, parse_codigos_input, map_vendedor,
                   codigo_matches, soma_falta, sugestao_codigo_por_nome)
from pdfgen import generate_relatorio_vendedor, generate_dashboard, generate_resumo_geral
import storage
import comparativo
import on_track
import data_store as ds
import resumo_matriz

# ── Formatação numérica em padrão brasileiro ────────────────────────────────
# Mesmo idioma já usado em pdfgen.py, pages/1_Relatorio_Diario_OTHIL.py,
# pages/3_Vendedor_Cliente_OTHIL.py e pages/gerencia.py -- esta página ainda
# usava o formato padrão do Python (separador de milhar ',' e decimal '.',
# ex.: "R$ 12,345.67"), que fica invertido em relação ao padrão brasileiro
# usado no resto do app (ex.: "R$ 12.345,67") -- reclamação explícita da
# Ingrid de que "fica horrível a visualização".
def _fmt_num(v, casas=0):
    return f"{v:,.{casas}f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def _fmt_moeda(v):
    return f"R$ {_fmt_num(v, 2)}"


MODULO = 'metas_semanais_fechamento'
MODULO_ONTRACK = 'metas_semanais_ontrack'

CONFIG_PATH = 'config_semanal.json'
_FECHAMENTOS_DIR  = os.path.join(os.path.dirname(__file__), '..', 'gerencia_data', 'fechamentos')
_ONTRACK_PUB_FILE = os.path.join(os.path.dirname(__file__), '..', 'gerencia_data', 'ontrack_publicado.json')
_ONTRACK_META_DIR = os.path.join(os.path.dirname(__file__), '..', 'gerencia_data', 'ontrack_metas')

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
    """periodo_ref da semana COMERCIAL desta página: sexta a sexta (8 dias
    corridos, contando as duas sextas -- a que abre e a que fecha/já abre
    a semana seguinte), pedido explícito da Ingrid só para o módulo Metas
    Semanais ("Hj na meta semanal, nossa semana vai de segunda a sexta,
    preciso que passe a ser de sexta a sexta... na sexta encerra a semana
    e na sexta mesmo, já será definido as metas da proxima semana").
    ISSO É LOCAL A ESTA PÁGINA -- não usa nem altera periodo.py (que
    continua semana ISO segunda-domingo, usado por Quebra, Vendedor-
    Cliente e outros módulos; ela confirmou o escopo: "Só Metas Semanais").

    O identificador é a data (ISO, "AAAA-MM-DD") da sexta-feira de
    ABERTURA da semana. Se `data` cair numa sexta-feira, ela é tratada
    como a sexta de abertura da semana que começa NAQUELA data (mesmo dia
    em que a semana anterior fecha e as novas metas são definidas) -- ela
    confirmou que essa sexta conta "das duas ao mesmo tempo", mas pra
    decidir default de tela numa data ambígua o app assume a semana que
    está abrindo."""
    dias_desde_sexta = (data.weekday() - 4) % 7  # segunda=0 ... sexta=4 -> 0
    sexta_abertura = data - datetime.timedelta(days=dias_desde_sexta)
    return sexta_abertura.isoformat()


def _intervalo_semana(slug: str):
    """(sexta_abertura, sexta_fechamento) da semana `slug` -- 8 dias
    corridos, incluindo as duas sextas (confirmado com a Ingrid: "8 dias
    corridos, porém 07 [dias de venda] pq no domingo não tem venda")."""
    inicio = datetime.date.fromisoformat(slug)
    fim = inicio + datetime.timedelta(days=7)
    return inicio, fim


def _label_semana(slug: str) -> str:
    try:
        inicio, fim = _intervalo_semana(slug)
        return f"Semana {inicio.strftime('%d/%m')} a {fim.strftime('%d/%m')}"
    except Exception:
        return slug


def _semana_anterior(slug: str) -> str:
    """periodo_ref da semana comercial imediatamente anterior."""
    inicio, _ = _intervalo_semana(slug)
    return (inicio - datetime.timedelta(days=7)).isoformat()


def _semana_ano_anterior(slug: str) -> str:
    """periodo_ref da mesma semana comercial um ano antes -- aproximação
    por 364 dias (52 semanas exatas) em vez de 365/366, pra preservar a
    sexta-feira como dia da semana (mesma lógica de aproximação que
    periodo.periodo_ano_anterior já usa pro tipo 'semanal')."""
    inicio, _ = _intervalo_semana(slug)
    return (inicio - datetime.timedelta(days=364)).isoformat()


def _dia_semana_atual(data: datetime.date = None) -> int:
    """Dia de venda (1..7) dentro da semana sexta-a-sexta que contém
    `data` (hoje, por padrão) -- pula domingo, que não tem venda. Substitui
    o antigo conceito de 'dia útil 1..5 (segunda a sexta)', que deixou de
    fazer sentido com a semana agora começando na sexta-feira."""
    if data is None:
        data = datetime.date.today()
    inicio, _ = _intervalo_semana(_slug_semana(data))
    dia = 0
    d = inicio
    while d <= data:
        if d.weekday() != 6:  # domingo
            dia += 1
        d += datetime.timedelta(days=1)
    return max(1, min(dia, 7))


def _salvar_fechamento(resultados: list, totais_rs: dict, periodo_txt: str, slug: str,
                        usuario: str = None):
    """Salva o fechamento da semana. Grava local (compatibilidade com a
    leitura já existente na página de Gerência) E na camada central de
    persistência (data_store — sobrevive a restart do Streamlit Cloud e
    mantém histórico versionado: fechar a mesma semana de novo não apaga
    o fechamento anterior, ele fica disponível em 'histórico de versões')."""
    os.makedirs(_FECHAMENTOS_DIR, exist_ok=True)
    payload = {
        'slug': slug,
        'periodo': periodo_txt,
        'gerado_em': datetime.datetime.now().isoformat(),
        'produtos': resultados,
        'totais_rs': totais_rs,
    }
    path = os.path.join(_FECHAMENTOS_DIR, f'{slug}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    try:
        ds.save_record(
            modulo=MODULO, tipo_periodo='semanal', periodo_ref=slug,
            valores={'periodo': periodo_txt, 'produtos': resultados, 'totais_rs': totais_rs},
            usuario=usuario,
        )
    except Exception as e:
        st.warning(
            f'O fechamento foi salvo localmente, mas houve um problema ao salvar '
            f'de forma permanente (histórico pode não sobreviver a um restart do '
            f'app): {e}'
        )


def _listar_fechamentos():
    """Lista os fechamentos salvos, mais recente primeiro. A fonte
    principal é a persistência real (data_store), que sobrevive a um
    restart do app; arquivos locais antigos (salvos antes desta migração,
    ou se a gravação remota falhar) entram como complemento."""
    items = {}
    try:
        for slug in ds.list_periodos(MODULO, 'semanal'):
            registro = ds.load_current(MODULO, 'semanal', slug)
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


def _diagnostico_vendedores_excluidos(vendas_rows: list, produtos_config: list,
                                       vendedor_pcts: dict) -> list:
    """Retorna vendedores que o relatório RECONHECE (têm alias mapeado em
    map_vendedor) mas que não fazem parte da lista de vendedores com meta
    semanal configurada (vendedor_pcts) -- ou seja, as vendas deles são
    silenciosamente excluídas do 'Vendido', mesmo quando o CÓDIGO do produto
    está certinho e o vendedor aparece normalmente no PDF. Já aconteceu antes
    (histórico: Luca ficou de fora quando foi cadastrado, e as vendas dele
    sumiam sem nenhum aviso) -- esse diagnóstico existe pra isso nunca mais
    passar despercebido, em vez de descobrir só quando o número não bate.

    Só conta linhas cujo código casa com algum produto configurado (linhas de
    código não reconhecido já aparecem no diagnóstico de códigos, e vendas de
    um vendedor não-rastreado num produto não configurado não afetam nenhuma
    meta de qualquer forma)."""
    from collections import defaultdict
    agg = defaultdict(lambda: {'qtde': 0.0, 'produtos': set()})
    for row in vendas_rows:
        disp = map_vendedor(row['vendedor'])
        if not disp or disp in vendedor_pcts:
            continue
        cn = normalize_codigo(row['codigo'])
        for p in produtos_config:
            if any(codigo_matches(cn, e) for e in p['codigos']):
                agg[disp]['qtde'] += row['qtde_vendida']
                agg[disp]['produtos'].add(p['nome'])
                break
    if not agg:
        return []
    return [
        {
            'Vendedor': vend,
            'CX fora do cálculo': dados['qtde'],
            'Produtos afetados': ', '.join(sorted(dados['produtos'])),
        }
        for vend, dados in sorted(agg.items(), key=lambda x: -x[1]['qtde'])
    ]


# ---------------------------------------------------------------------------
# On Track helpers
# ---------------------------------------------------------------------------

_STATUS_COR = {
    on_track.STATUS_VERDE:    '#2D6A4F',
    on_track.STATUS_ATENCAO:  '#B8860B',
    on_track.STATUS_FORA:     '#C00000',
    on_track.STATUS_SEM_META: '#6c757d',
}


def _on_track_status(atingido: float, dia: int, total_dias: int = 7):
    """Retorna (emoji, label, hex_color) usando a lógica CENTRAL de On Track
    (on_track.py — a mesma usada por todos os módulos do app), com o tempo
    decorrido calculado em dias de venda da semana comercial (1..total_dias,
    sexta a sexta, sem domingo -- ver `_dia_semana_atual`), que é a
    convenção já usada aqui (em vez de dias corridos do calendário).
    `atingido` já vem como fração (vendido/meta) calculada pelo chamador."""
    pct_tempo = (dia / total_dias) if total_dias else 0.0
    r = on_track.calcular(
        meta=1.0, realizado=atingido, tipo_periodo='semanal',
        periodo_ref='(dias uteis)', pct_tempo_decorrido=pct_tempo,
    )
    return r['emoji'], r['label'], _STATUS_COR[r['status']]


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
            min_value=1, max_value=7,
            value=_dia_semana_atual(),
            format='Dia %d de 7',
            help='Semana comercial sexta a sexta (sem domingo, que não tem '
                 'venda): Sexta=1  Sábado=2  Segunda=3  Terça=4  Quarta=5  '
                 'Quinta=6  Sexta (fecha a semana)=7',
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
    # IMPORTANTE: a meta GERAL nunca é a soma das metas individuais dos
    # vendedores (cada uma é round_up(pct% do estoque), e a soma de vários
    # arredondamentos pra cima estoura o total real). A meta geral é o
    # 'estoque_total' de cada produto -- o valor real configurado -- somado
    # entre os produtos. O vendido geral continua sendo a soma do que foi
    # realmente vendido (isso sim é sempre correto somar).
    total_meta   = sum(r.get('estoque_total', 0) for r in resultados)
    total_vend   = sum(l['vendido'] for r in resultados for l in r['linhas'])
    total_falta  = soma_falta([l for r in resultados for l in r['linhas']])
    ating_geral  = total_vend / total_meta if total_meta else 0
    proj_cx      = math.ceil(total_vend / dia_semana * 7) if dia_semana > 0 else 0
    delta_proj   = proj_cx - total_meta

    on_em, on_lb, on_cor = _on_track_status(ating_geral, dia_semana)

    st.markdown(
        f'<div style="background:{on_cor}; color:white; padding:0.55rem 1.2rem; '
        f'border-radius:10px; display:inline-block; margin-bottom:0.8rem; '
        f'font-size:1.05rem; font-weight:600;">'
        f'{on_em} {on_lb} — {ating_geral*100:.1f}% atingido (dia {dia_semana}/7)'
        f'</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric('Meta total (cx)',  _fmt_num(total_meta, 0))
    c2.metric('Vendido (cx)',     _fmt_num(total_vend, 0))
    c3.metric('% Atingido',      f'{ating_geral*100:.1f}%')
    c4.metric('Falta (cx)',      _fmt_num(total_falta, 0))
    c5.metric(
        'Projeção semana (cx)',   _fmt_num(proj_cx, 0),
        delta=f"{'+' if delta_proj >= 0 else ''}{_fmt_num(delta_proj, 0)} vs meta",
        delta_color='normal',
    )

    # R$ gerais
    tg = totais_rs.get('total_geral', {})
    if tg:
        st.subheader('Faturamento Geral (R$)')
        r1, r2, r3 = st.columns(3)
        r1.metric('Faturamento', _fmt_moeda(tg.get('fat', 0)))
        r2.metric('MC R$',       _fmt_moeda(tg.get('mc_rs', 0)))
        r3.metric('MC %',        f"{tg.get('resultado_real', 0):.2f}%")

    st.divider()

    # ── On Track por Vendedor ─────────────────────────────────────────────
    st.subheader('On Track por Vendedor')

    vend_agg = {}
    for r in resultados:
        for l in r['linhas']:
            v = l['vendedor']
            if v not in vend_agg:
                vend_agg[v] = {'meta': 0, 'vendido': 0, 'linhas': []}
            vend_agg[v]['meta']    += l['meta']
            vend_agg[v]['vendido'] += l['vendido']
            vend_agg[v]['linhas'].append(l)

    vend_rs = totais_rs.get('vendedores', {})
    rows = []
    for v, ag in vend_agg.items():
        meta_v = ag['meta']
        vend_v = ag['vendido']
        atg_v  = vend_v / meta_v if meta_v else 0
        proj_v = math.ceil(vend_v / dia_semana * 7) if dia_semana > 0 else 0
        em, lb, _ = _on_track_status(atg_v, dia_semana)
        rs = vend_rs.get(v, {})
        rows.append({
            'Vendedor':     v,
            'Meta (cx)':    meta_v,
            'Vendido (cx)': vend_v,
            '% Atingido':   atg_v,
            'Falta (cx)':   soma_falta(ag['linhas']),
            'Projeção (cx)': proj_v,
            'Fat R$':       rs.get('fat'),
            'MC R$':        rs.get('mc_rs'),
            'MC %':         rs.get('resultado_real'),
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
    df_vend['Meta (cx)']     = df_vend['Meta (cx)'].map(lambda x: _fmt_num(x, 0))
    df_vend['Vendido (cx)']  = df_vend['Vendido (cx)'].map(lambda x: _fmt_num(x, 0))
    df_vend['Falta (cx)']    = df_vend['Falta (cx)'].map(lambda x: _fmt_num(x, 0))
    df_vend['Projeção (cx)'] = df_vend['Projeção (cx)'].map(lambda x: _fmt_num(x, 0))
    df_vend['Fat R$']  = df_vend['Fat R$'].map(lambda x: _fmt_moeda(x) if x is not None else '—')
    df_vend['MC R$']   = df_vend['MC R$'].map(lambda x: _fmt_moeda(x) if x is not None else '—')
    df_vend['MC %']    = df_vend['MC %'].map(lambda x: f'{x:.2f}%' if x is not None else '—')

    st.dataframe(df_vend, use_container_width=True, hide_index=True)

    st.divider()

    # ── On Track por Produto ────────────────────────────────────────────────
    # Mesmo padrão visual/estrutural do "On Track por Vendedor" acima (uma
    # tabela via st.dataframe, não mais uma lista de accordions) -- pedido
    # explícito da Ingrid pra deixar os dois blocos com a mesma cara. As
    # colunas usam Meta/Vendido em CAIXAS (cx), não em R$: não existe hoje
    # nenhum Faturamento/MC calculado por PRODUTO no app (só por vendedor,
    # vindo do PDF de Lucratividade) -- confirmado com a Ingrid antes desta
    # mudança, pra não inventar um valor em R$ que não existe de verdade.
    st.subheader('On Track por Produto')

    sort_by_prod = st.selectbox(
        'Ordenar produtos por',
        ['Maior % atingido', 'Maior volume (cx)', 'Alfabético'],
        key='ont_sort_prod',
    )

    rows_prod = []
    for r in resultados:
        # Meta do produto = 'estoque_total' (o valor real configurado pra
        # esse produto), NUNCA a soma das metas individuais por vendedor
        # (essa soma é inflada pelo arredondamento pra cima de cada uma).
        p_meta = r.get('estoque_total', 0)
        p_vend = sum(l['vendido'] for l in r['linhas'])
        p_atg  = p_vend / p_meta if p_meta else 0
        p_em, p_lb, _ = _on_track_status(p_atg, dia_semana)
        rows_prod.append({
            'Produto':      r['produto'],
            'Meta (cx)':    p_meta,
            'Vendido (cx)': p_vend,
            '% Atingido':   p_atg,
            'Status':       f'{p_em} {p_lb}',
        })

    if sort_by_prod == 'Maior % atingido':
        rows_prod.sort(key=lambda r: r['% Atingido'], reverse=True)
    elif sort_by_prod == 'Maior volume (cx)':
        rows_prod.sort(key=lambda r: r['Vendido (cx)'], reverse=True)
    else:
        rows_prod.sort(key=lambda r: r['Produto'])

    df_prod = pd.DataFrame(rows_prod)
    df_prod['Meta (cx)']    = df_prod['Meta (cx)'].map(lambda x: _fmt_num(x, 0))
    df_prod['Vendido (cx)'] = df_prod['Vendido (cx)'].map(lambda x: _fmt_num(x, 0))
    df_prod['% Atingido']   = df_prod['% Atingido'].map(lambda x: f'{x*100:.1f}%')

    st.dataframe(df_prod, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Render: Fechamento Semanal
# ---------------------------------------------------------------------------

def _render_resumo_geral_inline(resultados: list, totais_rs: dict, dia: int = 7):
    """Exibe o Resumo Geral (On Track + matriz produto × vendedor) inline."""
    if not resultados:
        return

    # ── On Track KPIs ────────────────────────────────────────────────────
    # Meta geral = soma do 'estoque_total' real de cada produto, não a soma
    # das metas individuais por vendedor (ver nota em _render_ontrack acima).
    total_meta  = sum(r.get('estoque_total', 0) for r in resultados)
    total_vend  = sum(l['vendido'] for r in resultados for l in r['linhas'])
    ating_geral = total_vend / total_meta if total_meta else 0
    proj_cx     = math.ceil(total_vend / dia * 7) if dia > 0 else 0
    on_em, on_lb, on_cor = _on_track_status(ating_geral, dia)

    st.markdown(
        f'<div style="background:{on_cor}; color:white; padding:0.45rem 1rem; '
        f'border-radius:8px; display:inline-block; margin-bottom:0.6rem; font-weight:600;">'
        f'{on_em} {on_lb} — {ating_geral*100:.1f}%</div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric('Meta total (cx)',    _fmt_num(total_meta, 0))
    c2.metric('Vendido (cx)',       _fmt_num(total_vend, 0))
    c3.metric('% Atingido',        f'{ating_geral*100:.1f}%')
    c4.metric('Falta (cx)',        _fmt_num(soma_falta([l for r in resultados for l in r['linhas']]), 0))
    c5.metric('Projeção semana (cx)', _fmt_num(proj_cx, 0))

    tg = totais_rs.get('total_geral', {})
    if tg:
        f1, f2, f3 = st.columns(3)
        f1.metric('Faturamento', _fmt_moeda(tg.get('fat', 0)))
        f2.metric('MC R$',       _fmt_moeda(tg.get('mc_rs', 0)))
        f3.metric('MC %',        f"{tg.get('resultado_real', 0):.2f}%")

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
        proj_v = math.ceil(vend_v / dia * 7) if dia > 0 else 0
        em, lb, _ = _on_track_status(atg_v, dia)
        rs = vend_rs.get(v, {})
        vrows.append({
            'Vendedor':     v,
            'Meta (cx)':   _fmt_num(meta_v, 0),
            'Vendido (cx)': _fmt_num(vend_v, 0),
            '% Atingido':  f'{atg_v*100:.1f}%',
            'Projeção (cx)': _fmt_num(proj_v, 0),
            'Fat R$':      _fmt_moeda(rs['fat']) if rs.get('fat') is not None else '—',
            'MC %':        f"{rs['resultado_real']:.2f}%" if rs.get('resultado_real') is not None else '—',
            'Status':      f'{em} {lb}',
        })
    st.dataframe(pd.DataFrame(vrows), use_container_width=True, hide_index=True)

    st.divider()

    # ── Resumo Geral: Matriz Produto × Vendedor ───────────────────────────
    # (implementação central em resumo_matriz.py -- usada aqui e também na
    # tela de Fechamentos Semanais da Gerência, pra nunca ficarem diferentes)
    resumo_matriz.render_matriz_produto_vendedor(resultados)


def _render_comparativo_semanal(resultados: list, totais_rs: dict, slug_atual: str):
    """Comparativo padrão (componente central comparativo.py): semana atual
    × semana anterior, e semana atual × mesma semana no ano anterior —
    usando o histórico real salvo em data_store (sobrevive a restart do app,
    diferente do que estava em session_state antes)."""
    st.subheader('📊 Comparativo')

    total_vend_atual = sum(l['vendido'] for r in resultados for l in r['linhas'])
    fat_atual = totais_rs.get('total_geral', {}).get('fat')

    def _totais_do_registro(registro):
        if not registro:
            return None, None
        prods = registro['valores'].get('produtos', [])
        vend = sum(l['vendido'] for r in prods for l in r.get('linhas', []))
        fat = registro['valores'].get('totais_rs', {}).get('total_geral', {}).get('fat')
        return vend, fat

    slug_ant = _semana_anterior(slug_atual)
    slug_ano_ant = _semana_ano_anterior(slug_atual)

    reg_ant = ds.load_current(MODULO, 'semanal', slug_ant)
    reg_ano_ant = ds.load_current(MODULO, 'semanal', slug_ano_ant)
    vend_ant, fat_ant = _totais_do_registro(reg_ant)
    vend_ano_ant, fat_ano_ant = _totais_do_registro(reg_ano_ant)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f'**Semana atual × {_label_semana(slug_ant)}**')
        if vend_ant is None:
            st.caption('Ainda não há fechamento salvo da semana anterior para comparar.')
        else:
            comp_v = comparativo.calcular(total_vend_atual, vend_ant)
            st.metric('Vendido (cx)', _fmt_num(total_vend_atual, 0),
                       delta=f"{comparativo.formatar_variacao(comp_v)} vs semana anterior")
            if fat_atual is not None and fat_ant is not None:
                comp_f = comparativo.calcular(fat_atual, fat_ant)
                st.metric('Faturamento', _fmt_moeda(fat_atual),
                           delta=f"{comparativo.formatar_variacao(comp_f)} vs semana anterior")
    with col2:
        st.markdown(f'**Semana atual × {_label_semana(slug_ano_ant)} (ano anterior)**')
        if vend_ano_ant is None:
            st.caption('Ainda não há fechamento salvo da mesma semana no ano anterior.')
        else:
            comp_v2 = comparativo.calcular(total_vend_atual, vend_ano_ant)
            st.metric('Vendido (cx)', _fmt_num(total_vend_atual, 0),
                       delta=f"{comparativo.formatar_variacao(comp_v2)} vs ano anterior")
            if fat_atual is not None and fat_ano_ant is not None:
                comp_f2 = comparativo.calcular(fat_atual, fat_ano_ant)
                st.metric('Faturamento', _fmt_moeda(fat_atual),
                           delta=f"{comparativo.formatar_variacao(comp_f2)} vs ano anterior")


def _render_fechamento_semanal():
    st.header('📅 Fechamento Semanal')

    resultados = st.session_state.get('resultados')
    cfg_atual  = st.session_state.get('config', {})
    periodo_texto = cfg_atual.get('periodo', '')

    # ── Fechar semana atual (ou retroativa) ──────────────────────────────
    if resultados:
        data_ref = st.date_input(
            'Semana a fechar (data de referência)',
            value=datetime.date.today(),
            format='DD/MM/YYYY',
            help='Deixe em hoje para a semana atual. Para fechar uma semana '
                 'atrasada/retroativa (ex.: PDFs enviados depois), escolha uma '
                 'data dentro daquela semana — o fechamento fica salvo no '
                 'histórico daquela semana específica, não na de hoje.',
            key='fech_data_ref',
        )
        slug_atual  = _slug_semana(data_ref)
        label_atual = _label_semana(slug_atual)
        retroativo  = data_ref != datetime.date.today()

        st.subheader(f'Fechar: {label_atual}' + (' (retroativo)' if retroativo else ''))
        st.caption(
            'Semana comercial: sexta a sexta (8 dias corridos, sem contar domingo, '
            'que não tem venda) — a sexta é o dia de fechar a semana atual e já '
            'abrir a próxima. Se hoje for sexta e você quiser fechar a semana que '
            'está terminando (em vez de já abrir a nova), escolha ontem (quinta) '
            'como data de referência acima.'
        )
        st.caption(f'Período configurado: **{periodo_texto or "(não informado)"}**')

        # Dia da semana (para o On Track inline) -- se for retroativo, assume
        # semana inteira decorrida (dia 7) por padrão, já que já passou.
        dia_fech = st.slider(
            'Dia da semana (para projeção)', 1, 7,
            value=7 if retroativo else _dia_semana_atual(),
            format='Dia %d de 7',
            key='fech_dia',
        )

        totais_rs = st.session_state.get('totais_rs', {})

        # Resumo inline completo
        _render_resumo_geral_inline(resultados, totais_rs, dia_fech)

        st.divider()
        _render_comparativo_semanal(resultados, totais_rs, slug_atual)

        st.divider()
        label_botao = '💾 Fechar Semana e Salvar no Histórico' if not retroativo \
            else f'💾 Fechar {label_atual} (retroativo) e Salvar no Histórico'
        if st.button(label_botao, type='primary', key='btn_fechar'):
            try:
                _salvar_fechamento(resultados, totais_rs, periodo_texto, slug_atual,
                                    usuario=st.session_state.get('usuario_nome', 'Ingrid'))
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
    usuario_reg = dados.get('usuario')
    versao_reg = dados.get('versao')
    extra = []
    if usuario_reg:
        extra.append(f'por {usuario_reg}')
    if versao_reg:
        extra.append(f'versão {versao_reg}')
    sufixo = f"  ({', '.join(extra)})" if extra else ''
    st.caption(f"Período: {dados.get('periodo', '-')}  |  Salvo em: {gerado}{sufixo}")

    slug_sel = slugs[idx]
    versoes_antigas = ds.load_history(MODULO, 'semanal', slug_sel)
    if versoes_antigas:
        with st.expander(f'🕓 Ver {len(versoes_antigas)} versão(ões) anterior(es) desta semana'):
            for v in reversed(versoes_antigas):
                v_prods = v.get('valores', {}).get('produtos', [])
                v_meta = sum(r.get('estoque_total', 0) for r in v_prods)
                v_vend = sum(l['vendido'] for r in v_prods for l in r.get('linhas', []))
                v_quando = (v.get('atualizado_em') or '')[:16].replace('T', ' ')
                st.markdown(
                    f"- **v{v.get('versao')}** — {v_quando} por {v.get('usuario', 'não identificado')} "
                    f"— Meta {_fmt_num(v_meta, 0)} cx, Vendido {_fmt_num(v_vend, 0)} cx"
                )

    prods      = dados.get('produtos', [])
    h_meta     = sum(r.get('estoque_total', 0) for r in prods)
    h_vend     = sum(l['vendido'] for r in prods for l in r.get('linhas', []))
    h_atg      = h_vend / h_meta if h_meta else 0

    h1, h2, h3 = st.columns(3)
    h1.metric('Meta (cx)',  _fmt_num(h_meta, 0))
    h2.metric('Vendido (cx)', _fmt_num(h_vend, 0))
    h3.metric('% Atingido', f'{h_atg*100:.1f}%')

    tg_h = dados.get('totais_rs', {}).get('total_geral', {})
    if tg_h:
        f1, f2, f3 = st.columns(3)
        f1.metric('Faturamento', _fmt_moeda(tg_h.get('fat', 0)))
        f2.metric('MC R$',      _fmt_moeda(tg_h.get('mc_rs', 0)))
        f3.metric('MC %',       f"{tg_h.get('resultado_real', 0):.2f}%")

    st.divider()
    resumo_matriz.render_matriz_produto_vendedor(prods)


# ---------------------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------------------

if 'config' not in st.session_state:
    st.session_state.config = load_config()

cfg = st.session_state.config

if not storage.is_configured():
    st.info(
        '⚠️ Persistência permanente ainda não configurada: a configuração e o '
        'histórico deste módulo só ficam salvos enquanto o app não '
        'reiniciar/dormir. Para manter os dados disponíveis permanentemente '
        '(inclusive entre restarts do Streamlit Cloud), configure o GITHUB_TOKEN '
        'nos Secrets do Streamlit Cloud (instruções no topo do arquivo storage.py).'
    )

st.title('Metas Semanais')
st.caption('Metas semanais por vendedor e configuração de responsáveis/percentuais.')

st.session_state.setdefault('usuario_nome', 'Ingrid')

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
        # Mesma causa raiz do bug já corrigido na importação de configuração
        # (ver comentário abaixo, em '_cfg_upload_processado'): as keys dos
        # widgets (nome_i, cod_i, est_i, prio_i) são posicionais. Remover um
        # produto do meio da lista desloca o índice de todos os que vêm
        # depois, mas os widgets recriados nesses índices ignoram o novo
        # `value=` porque a key já existe no session_state — cada produto
        # após o removido passava a exibir os dados do produto anterior a
        # ele (nome/código/estoque "grudados"), e esse valor errado podia
        # até ser salvo de volta na configuração. Limpar aqui garante que
        # cada widget reinicialize do zero com os dados corretos da lista já
        # atualizada.
        for _k in list(st.session_state.keys()):
            if _k.startswith(('nome_', 'cod_', 'est_', 'prio_')):
                del st.session_state[_k]
        st.rerun()

    cb1, cb2 = st.columns([1, 3])
    with cb1:
        if st.button('💾 Salvar configuração', use_container_width=True):
            save_config(cfg)

    with st.expander('⚙️ Percentuais de meta por vendedor — normalmente não precisa alterar'):
        pct_cols = st.columns(len(cfg['vendedor_pcts']))
        for col, (vend, pct) in zip(pct_cols, list(cfg['vendedor_pcts'].items())):
            with col:
                cfg['vendedor_pcts'][vend] = st.number_input(
                    vend, min_value=0, max_value=200,
                    value=int(pct), key=f'pct_{vend}',
                )

    with st.expander('📤 Exportar / Importar configuração (JSON)'):
        st.download_button(
            '⬇️ Exportar configuração',
            data=json.dumps(cfg, ensure_ascii=False, indent=2),
            file_name=f"config_metas_{datetime.date.today().isoformat()}.json",
            mime='application/json',
        )
        up_cfg = st.file_uploader('⬆️ Importar configuração', type='json', key='cfg_upload')
        # Processa cada arquivo enviado só uma vez (guarda o file_id já
        # processado): sem isso, como o file_uploader continua retornando o
        # mesmo arquivo em TODO rerun até o usuário removê-lo manualmente, o
        # st.rerun() logo abaixo entrava em loop infinito assim que um
        # arquivo era importado (a página nunca terminava de "Running...").
        if up_cfg is not None and st.session_state.get('_cfg_upload_processado') != up_cfg.file_id:
            # Valida/normaliza o conteúdo importado ANTES de aceitar. Sem
            # isso, um JSON editado à mão, exportado de uma versão antiga do
            # app, ou simplesmente inválido, derrubava a página inteira com
            # um traceback técnico (ex.: "vendedor_pcts" vazio/ausente vira
            # st.columns(0) mais abaixo -> StreamlitInvalidColumnSpecError;
            # um produto sem "nome"/"codigos_texto" vira KeyError na hora de
            # renderizar) em vez de avisar a Ingrid de forma compreensível.
            try:
                bruto = json.load(up_cfg)
                if not isinstance(bruto, dict) or not isinstance(bruto.get('produtos'), list) \
                        or not bruto['produtos']:
                    raise ValueError('o arquivo precisa ter uma lista "produtos" com pelo menos 1 item')
                produtos_importados = []
                for item in bruto['produtos']:
                    if not isinstance(item, dict):
                        continue
                    prioridade = item.get('prioridade')
                    produtos_importados.append({
                        'nome': str(item.get('nome', '')),
                        'codigos_texto': str(item.get('codigos_texto', '')),
                        'estoque': int(item.get('estoque') or 0),
                        'prioridade': prioridade if prioridade in _PRIORIDADES else 'Normal',
                    })
                if not produtos_importados:
                    raise ValueError('nenhum produto válido encontrado no arquivo')
                vendedor_pcts_importado = bruto.get('vendedor_pcts')
                if not isinstance(vendedor_pcts_importado, dict) or not vendedor_pcts_importado:
                    # Sem "vendedor_pcts" válido, cai para o padrão em vez de
                    # travar a tela (dict vazio -> st.columns(0) mais abaixo).
                    vendedor_pcts_importado = dict(VENDEDORES_PADRAO)
                else:
                    vendedor_pcts_importado = {str(k): int(v or 0)
                                                for k, v in vendedor_pcts_importado.items()}
            except (json.JSONDecodeError, ValueError, TypeError, AttributeError) as e:
                st.error(f'Não foi possível importar este arquivo: {e}. Verifique se é um JSON de '
                         'configuração exportado por este mesmo app (botão "⬇️ Exportar configuração").')
            else:
                st.session_state.config = {
                    'produtos': produtos_importados,
                    'vendedor_pcts': vendedor_pcts_importado,
                }
                save_config(st.session_state.config, show_feedback=False)
                st.session_state['_cfg_upload_processado'] = up_cfg.file_id
                # Limpa o estado dos widgets por produto/vendedor (nome_i, cod_i,
                # est_i, prio_i, pct_vend) guardado da config ANTERIOR. Sem isso,
                # um widget com 'key' já existente ignora o `value=`/`index=` em
                # reruns seguintes e continua mostrando o valor antigo -- então
                # um produto que ocupa o mesmo índice na config antiga e na
                # importada continuava exibindo nome/código antigos mesmo depois
                # do import (e esse valor velho é que ia pro cálculo e podia até
                # ser salvo de volta, sobrescrevendo o import). Isso combina
                # exatamente com "alguns códigos não puxam, e outros puxaram
                # errado" -- limpar aqui garante que cada widget reinicialize do
                # zero com os dados recém-importados.
                for _k in list(st.session_state.keys()):
                    if _k.startswith(('nome_', 'cod_', 'est_', 'prio_', 'pct_')):
                        del st.session_state[_k]
                st.rerun()

    st.divider()

    # ── Calcular ─────────────────────────────────────────────────────────
    st.header('3. Calcular metas e gerar relatórios')

    _pc1, _pc2 = st.columns(2)
    with _pc1:
        periodo_texto = st.text_input(
            'Período (ex.: 22/06/2026 a 26/06/2026)',
            value=cfg.get('periodo', ''),
        )
    with _pc2:
        data_emissao = st.text_input(
            'Data de emissão (ex.: 29/06/2026)',
            value=datetime.date.today().strftime('%d/%m/%Y'),
        )
    cfg['periodo'] = periodo_texto

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
                    # Usa pdftotext -layout (mais confiável para colunas adjacentes)
                    vendas_rows = parse_vendas_pdftotext(io.BytesIO(vendas_bytes))
                    # Fallback para pdfplumber se pdftotext não encontrou linhas
                    if not vendas_rows:
                        vendas_rows = parse_vendas(io.BytesIO(vendas_bytes))
                except Exception:
                    try:
                        vendas_rows = parse_vendas(io.BytesIO(vendas_bytes))
                    except Exception:
                        st.error(
                            'Não foi possível ler o PDF de Vendas/Lucratividade enviado. '
                            'Verifique se o arquivo não está corrompido ou protegido por '
                            'senha e tente enviar novamente.'
                        )
                        vendas_rows = None
                        # Não apaga um 'resultados' de um cálculo anterior bem-sucedido
                        # (evita perder o último trabalho válido), mas marca que ele está
                        # desatualizado -- sem isso, a seção "Resultados" mais abaixo
                        # continuava mostrando os números antigos como se fossem deste
                        # envio, sem nenhum aviso de que o PDF atual falhou.
                        if 'resultados' in st.session_state:
                            st.session_state['_resultados_desatualizados'] = True

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
                resultados = compute_metas(vendas_rows, produtos_config, cfg['vendedor_pcts'], estoque_rows=estoque_rows)
                _prio_map = {p['nome']: p.get('prioridade', 'Normal') for p in produtos_config}
                for _r in resultados:
                    _r['prioridade'] = _prio_map.get(_r['produto'], 'Normal')
                st.session_state['estoque_rows']    = estoque_rows
                st.session_state['vendas_rows']     = vendas_rows
                st.session_state['vendas_bytes']    = vendas_bytes
                st.session_state['resultados']      = resultados
                st.session_state['produtos_config'] = produtos_config
                st.session_state['_resultados_desatualizados'] = False
                save_config(cfg, show_feedback=False)
                st.success('Cálculo concluído. Confira a aba **📊 On Track** para o dashboard.')

    # ── Resultados ────────────────────────────────────────────────────────
    if 'resultados' in st.session_state:
        if st.session_state.get('_resultados_desatualizados'):
            st.warning(
                '⚠️ O último PDF enviado não pôde ser lido. Os resultados abaixo são de um '
                'cálculo anterior e NÃO refletem o arquivo mais recente — corrija/reenvie o '
                'PDF e clique em "▶️ Calcular metas" novamente antes de usar estes números.'
            )
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
                f'— {_fmt_num(total_nao_rec, 0)} cx fora do cálculo',
                expanded=True,
            ):
                st.caption(
                    'Esses códigos aparecem no PDF mas não casaram com nenhum produto '
                    'configurado. Se fizerem parte das metas desta semana, adicione ou '
                    'corrija os códigos na seção **2. Produtos da semana** acima.'
                )
                df_diag = pd.DataFrame(nao_rec)
                df_diag['CX não reconhecidas'] = df_diag['CX não reconhecidas'].map(
                    lambda x: _fmt_num(x, 0)
                )
                st.dataframe(df_diag, use_container_width=True, hide_index=True)
        else:
            st.success('✅ Todos os códigos do PDF foram reconhecidos — nenhuma cx perdida.')

        # Diagnóstico de vendedores reconhecidos mas fora da lista de metas
        # (ex.: aconteceu com o Luca -- vendas dele sumiam do Vendido sem
        # nenhum aviso, mesmo com o código do produto certinho)
        vend_excl = _diagnostico_vendedores_excluidos(
            vendas_rows_diag, produtos_config_diag, cfg['vendedor_pcts'])
        if vend_excl:
            total_vend_excl = sum(r['CX fora do cálculo'] for r in vend_excl)
            with st.expander(
                f'⚠️ {len(vend_excl)} vendedor(es) reconhecido(s) mas sem meta configurada '
                f'— {_fmt_num(total_vend_excl, 0)} cx fora do cálculo',
                expanded=True,
            ):
                st.caption(
                    'Esses vendedores aparecem no PDF e o app sabe quem são, mas não estão na '
                    'lista de "Percentuais de meta por vendedor" abaixo — então as vendas deles '
                    'não entram no Vendido de nenhum produto, mesmo com o código certo. Se '
                    'devem contar nas metas desta semana, adicione o vendedor no expansor '
                    '**"⚙️ Percentuais de meta por vendedor"** acima (com o percentual que você '
                    'quiser aplicar) e calcule de novo.'
                )
                df_vend = pd.DataFrame(vend_excl)
                df_vend['CX fora do cálculo'] = df_vend['CX fora do cálculo'].map(
                    lambda x: _fmt_num(x, 0)
                )
                st.dataframe(df_vend, use_container_width=True, hide_index=True)

        # Diagnóstico de possível erro de digitação no código: pra cada
        # produto configurado que não bateu com NENHUMA venda, procura no
        # PDF um nome parecido usando um código diferente do configurado.
        # Você digita nome E código propositalmente pra evitar erro -- isso
        # aqui usa os dois: se o nome bate com uma linha do PDF mas o código
        # configurado é outro, é sinal de erro de digitação no código (não
        # de o produto simplesmente não ter vendido nada essa semana), e o
        # app agora avisa sozinho em vez de precisar conferir na mão.
        possiveis_typos = []
        for p in produtos_config_diag:
            tem_venda = any(
                codigo_matches(normalize_codigo(r['codigo']), e)
                for r in vendas_rows_diag for e in p['codigos']
            )
            if tem_venda:
                continue
            candidatos = sugestao_codigo_por_nome(p['nome'], vendas_rows_diag)
            # só sinaliza candidatos com um código DIFERENTE de todos os já
            # configurados pra esse produto (evita "sugerir" o próprio
            # código certo de volta, ex. quando bate por prefixo)
            candidatos = [c for c in candidatos if c['codigo'] not in p['codigos']]
            for c in candidatos:
                possiveis_typos.append({
                    'Produto configurado': p['nome'],
                    'Código configurado': ', '.join(p['codigos']) or '(vazio)',
                    'Nome encontrado no PDF': c['descricao'],
                    'Código encontrado no PDF': c['codigo'],
                    'Cx sob esse código': c['qtde'],
                })
        if possiveis_typos:
            with st.expander(
                f'🚨 {len(possiveis_typos)} produto(s) com possível erro de digitação no código',
                expanded=True,
            ):
                st.caption(
                    'O NOME desses produtos bate com uma venda no PDF, mas o CÓDIGO configurado '
                    'é diferente do código daquela venda -- ou seja, o produto provavelmente '
                    'vendeu normalmente, só que sob um código diferente do que está cadastrado. '
                    'Confira e corrija o código na seção **2. Produtos da semana** acima.'
                )
                df_typo = pd.DataFrame(possiveis_typos)
                df_typo['Cx sob esse código'] = df_typo['Cx sob esse código'].map(
                    lambda x: _fmt_num(x, 0)
                )
                st.dataframe(df_typo, use_container_width=True, hide_index=True)

        # Diagnóstico por produto: mostra linhas brutas extraídas do PDF
        with st.expander('🔍 Diagnóstico por produto (linhas brutas do PDF)'):
            for p in produtos_config_diag:
                linhas_brutas = [
                    row for row in vendas_rows_diag
                    if any(codigo_matches(normalize_codigo(row['codigo']), e) for e in p['codigos'])
                ]
                total = sum(r['qtde_vendida'] for r in linhas_brutas)
                st.markdown(f"**{p['nome']}** — {len(linhas_brutas)} linha(s) — total bruto: `{total:.3f} cx`")
                if linhas_brutas:
                    df_bruto = pd.DataFrame([{
                        'Código':   r['codigo'],
                        'Vendedor Raw': r['vendedor'],
                        'Vendedor Mapeado': map_vendedor(r['vendedor']) or '❓ NÃO MAPEADO',
                        'CX Extraída': r['qtde_vendida'],
                    } for r in linhas_brutas])
                    st.dataframe(df_bruto, use_container_width=True, hide_index=True)
                else:
                    st.caption('— nenhuma linha encontrada')

        # Diagnóstico RAW: mostra exatamente o que o pdftotext extrai do PDF
        vendas_bytes_diag = st.session_state.get('vendas_bytes')
        if vendas_bytes_diag:
            with st.expander('🔬 Diagnóstico RAW pdftotext (para depuração)'):
                try:
                    from parsers_diario import extract_text as _extract_text
                    raw_text = _extract_text(io.BytesIO(vendas_bytes_diag))
                    raw_lines = raw_text.split('\n')
                    for p in produtos_config_diag:
                        codigos_busca = [c.rstrip('*') for c in p['codigos']]
                        linhas_encontradas = [
                            l for l in raw_lines
                            if any(cod in l for cod in codigos_busca)
                        ]
                        st.markdown(f"**{p['nome']}** — {len(linhas_encontradas)} linha(s) no pdftotext:")
                        if linhas_encontradas:
                            for l in linhas_encontradas:
                                st.code(repr(l))
                        else:
                            st.caption('— código não encontrado no texto extraído pelo pdftotext')
                except Exception as e:
                    st.error(f'Erro ao extrair texto: {e}')

        # ── Publicar para Gerência ────────────────────────────────────────
        st.divider()
        st.caption(
            'Semana de referência para a publicação — deixe em hoje para a semana atual. '
            'Se estiver calculando/publicando com atraso (PDFs de uma semana anterior), '
            'escolha uma data dentro daquela semana para o On Track não ser gravado por '
            'engano sob a semana de hoje.'
        )
        data_ref_pub = st.date_input(
            'Semana a publicar (data de referência)', value=datetime.date.today(),
            format='DD/MM/YYYY', key='ontrack_pub_data_ref',
        )
        pub_col, _ = st.columns([2, 4])
        with pub_col:
            if st.button('📤 Publicar On Track para Gerência', use_container_width=True):
                try:
                    os.makedirs(os.path.dirname(_ONTRACK_PUB_FILE), exist_ok=True)
                    os.makedirs(_ONTRACK_META_DIR, exist_ok=True)
                    snapshot = {
                        'publicado_em': datetime.datetime.now().isoformat(timespec='seconds'),
                        'periodo':      st.session_state.get('config', {}).get('periodo', ''),
                        'resultados':   resultados,
                        'totais_rs':    st.session_state.get('totais_rs', {}),
                    }
                    # Arquivo atual (compatibilidade)
                    with open(_ONTRACK_PUB_FILE, 'w', encoding='utf-8') as f:
                        json.dump(snapshot, f, ensure_ascii=False, indent=2)
                    # Histórico por semana ISO (arquivo local — compatibilidade).
                    # Usa a semana ESCOLHIDA acima, não periodo.periodo_atual('semanal')
                    # (que sempre seria a semana de hoje, mesmo publicando com atraso
                    # dados de uma semana anterior -- sobrescrevendo por engano o On
                    # Track real da semana corrente).
                    slug_sem = _slug_semana(data_ref_pub)
                    hist_path = os.path.join(_ONTRACK_META_DIR, f'{slug_sem}.json')
                    with open(hist_path, 'w', encoding='utf-8') as f:
                        json.dump(snapshot, f, ensure_ascii=False, indent=2)
                    # Persistência real e versionada (sobrevive a restart do app)
                    try:
                        ds.save_record(
                            modulo=MODULO_ONTRACK, tipo_periodo='semanal', periodo_ref=slug_sem,
                            valores=snapshot, usuario=st.session_state.get('usuario_nome'),
                        )
                    except Exception as e2:
                        st.warning(f'Publicado localmente, mas houve um problema ao salvar de forma permanente: {e2}')
                    st.success('✅ On Track publicado — disponível na aba Gerência.')
                except Exception as e:
                    st.error(f'Erro ao publicar: {e}')

        st.subheader('Resultado por produto')

        # Tabela resumo compacta -- a meta do produto é sempre 'estoque_total'
        # (o valor real configurado), nunca a soma das metas individuais dos
        # vendedores (essa soma é inflada pelo arredondamento pra cima de
        # cada uma). Falta segue usando essa mesma meta real como base.
        resumo_rows = []
        for r in resultados:
            p_meta = r.get('estoque_total', 0)
            p_vend = sum(l['vendido'] for l in r['linhas'])
            p_atg  = p_vend / p_meta * 100 if p_meta else 0
            p_falt = max(p_meta - p_vend, 0)
            p_media = r.get('media_rs_cx')
            resumo_rows.append({
                'Produto':      r['produto'],
                'Prioridade':   r.get('prioridade', 'Normal'),
                'Meta (cx)':    f"{p_meta:.0f}",
                'Vendido (cx)': f"{p_vend:.0f}",
                'Falta (cx)':   f"{p_falt:.0f}",
                '% Atingido':   f"{p_atg:.1f}%",
                'R$ Médio/cx':  _fmt_moeda(p_media) if p_media is not None else '—',
            })
        st.dataframe(pd.DataFrame(resumo_rows), use_container_width=True, hide_index=True)
        if any(r.get('media_rs_cx') is None for r in resultados):
            st.caption(
                '— na coluna **R$ Médio/cx** significa que não há "Md Venda" desse produto '
                'para calcular a média: ou o PDF de Estoque Físico não foi enviado (é opcional '
                'nesta tela), ou nenhuma linha dele que bate com os códigos desse produto tem '
                'Qtde Vendida maior que zero. O restante da meta (Vendido/Falta/%) continua '
                'correto mesmo assim.'
            )

        # Detalhe por vendedor (colapsado)
        st.caption('Clique em um produto para ver o detalhe por vendedor:')
        for r in resultados:
            p_meta = r.get('estoque_total', 0)
            p_vend = sum(l['vendido'] for l in r['linhas'])
            p_atg  = p_vend / p_meta * 100 if p_meta else 0
            prio   = r.get('prioridade', 'Normal')
            badge  = f' — {prio}' if prio != 'Normal' else ''
            with st.expander(
                f"{r['produto']}{badge}  |  Meta {p_meta:.0f} cx — Vendido {p_vend:.0f} cx ({p_atg:.1f}%)",
                expanded=False,
            ):
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
            pdf_bytes = generate_dashboard(periodo_texto, resultados, cfg['vendedor_pcts'])
            st.download_button(
                '⬇️ Dashboard', data=pdf_bytes,
                file_name=f'Dashboard_{datetime.date.today().strftime("%d%m%Y")}.pdf',
                mime='application/pdf',
            )
        with pcol3:
            pdf_bytes = generate_resumo_geral(periodo_texto, data_emissao, resultados, cfg['vendedor_pcts'])
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
