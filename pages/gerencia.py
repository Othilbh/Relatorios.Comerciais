"""Página de Gerência OTHIL — acesso restrito por senha."""
import json
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
from dashboard_custo_real import gerar_dashboard as gerar_dashboard_custo_real
import margem_produto as mp
import periodo as periodo_mod
import comparativo
import on_track
import data_store as ds
import metas_gerais as mg
import calc
import rentabilidade as rent
import produtos as prod
import resumo_matriz
from xlsx_vendedor_cliente import VENDOR_TAB, _normalize

MOD_RELATORIO_DIARIO = 'relatorio_diario'
MOD_FECHAMENTO = 'metas_semanais_fechamento'
MOD_ONTRACK_METAS = 'metas_semanais_ontrack'
MOD_QUEBRA = 'quebra'
MOD_ONTRACK_CLI = 'vendedor_cliente_ontrack'
MOD_VENDEDOR_CLIENTE = 'vendedor_cliente'
MOD_PREVPERDAS = 'prevencao_perdas'
MOD_RECORRENCIA = 'recorrencia'
TIPO_RECORRENCIA = 'livre'

_GERENCIA_DIR     = os.path.join(os.path.dirname(__file__), '..', 'gerencia_data')
_ONTRACK_PUB_FILE = os.path.join(_GERENCIA_DIR, 'ontrack_publicado.json')
_ONTRACK_CLI_FILE = os.path.join(_GERENCIA_DIR, 'ontrack_clientes_publicado.json')
_ONTRACK_META_DIR = os.path.join(_GERENCIA_DIR, 'ontrack_metas')
_ONTRACK_CLI_DIR  = os.path.join(_GERENCIA_DIR, 'ontrack_clientes')
_QUEBRA_DIR       = os.path.join(_GERENCIA_DIR, 'quebra')
_MARGEM_REAL_DIR  = os.path.join(_GERENCIA_DIR, 'margem_real')
_PREVPERDAS_DIR   = os.path.join(_GERENCIA_DIR, 'prevencao_perdas')
_PERDAS_DIR       = os.path.join(_GERENCIA_DIR, 'perdas_realizadas')
_MESES_QBR     = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']
_SENHA_FALLBACK = 'othil2024'


# ── Cores por status de On Track — FONTE ÚNICA ────────────────────────────────
# Antes existiam DUAS tabelas independentes de cor para os MESMOS 4 estados de
# on_track.py (_GER_STATUS_COR, hex sólido usado nas pílulas/legendas, e
# _GER_STATUS_LABEL_COR, pares pastel bg/fg usados nos cartões de Metas
# Gerais) -- duas tabelas para o mesmo enum significavam manter cor em dois
# lugares e deixá-las divergir. Agora há um único mapa por status, com tudo
# que a tela precisa:
#   cor         -> hex sólido (texto/legenda/barra de progresso)
#   bg / fg     -> par pastel (fundo/texto) para qualquer bloco colorido
#   delta_color -> valor aceito por st.metric(delta_color=...)
#   md          -> nome de cor do markdown do Streamlit (:green[...] etc.),
#                  usado nas legendas de status abaixo dos st.metric
_GER_STATUS_CORES = {
    on_track.STATUS_VERDE: {
        'cor': '#2D6A4F', 'bg': '#D8EFE3', 'fg': '#1B4332',
        'delta_color': 'normal', 'md': 'green',
    },
    on_track.STATUS_ATENCAO: {
        'cor': '#B8860B', 'bg': '#FEF9C3', 'fg': '#7D6608',
        'delta_color': 'off', 'md': 'orange',
    },
    on_track.STATUS_FORA: {
        'cor': '#C00000', 'bg': '#FADADD', 'fg': '#7A1F2B',
        'delta_color': 'inverse', 'md': 'red',
    },
    on_track.STATUS_SEM_META: {
        'cor': '#6c757d', 'bg': '#EDEDED', 'fg': '#555555',
        'delta_color': 'off', 'md': 'gray',
    },
}

# Alias mantido para os pontos que só precisam do hex sólido — deriva do mapa
# único acima, nunca mais uma segunda tabela mantida à mão.
_GER_STATUS_COR = {_s: _v['cor'] for _s, _v in _GER_STATUS_CORES.items()}


def _ger_legenda_status(ot):
    """Legenda curta e colorida de status (🟢 On Track / 🟡 Atenção / ...),
    exibida logo abaixo de um st.metric. Usa a cor de markdown nativa do
    Streamlit vinda do mapa único _GER_STATUS_CORES."""
    md = _GER_STATUS_CORES[ot['status']]['md']
    st.caption(f":{md}[{ot['emoji']} {ot['label']}]")


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


# ── Navegação de período por DATA (mesma lógica/arquitetura da página
# Relatório Diário — periodo.py + data_store.py — reaproveitada aqui em vez
# de duplicar uma estrutura paralela). Corrige o mesmo bug de raiz que
# afetava as setas do Relatório Diário: o código antigo desta seção usava
# um índice dentro da lista de dashboards SALVOS, combinado com
# st.selectbox(..., index=...) — o Streamlit ignora esse index= a partir do
# segundo rerun (o valor persistido no session_state da própria selectbox
# manda), então o clique nas setas era desfeito na linha seguinte. Além
# disso, por navegar sobre a LISTA de salvos (não sobre datas), não dava
# pra "andar" até um período sem dado nenhum — violava a mesma regra do
# item 2 do pedido original (navegação não pode depender de já existir
# registro salvo).
def _diario_data(ref):
    return datetime.datetime.strptime(ref, '%Y-%m-%d').date()


def _periodo_atual_ref(tipo):
    if tipo == 'diario':
        return datetime.date.today().strftime('%Y-%m-%d')
    return periodo_mod.periodo_atual(tipo)


def _periodo_anterior(tipo, ref):
    if tipo == 'diario':
        return (_diario_data(ref) - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    return periodo_mod.periodo_anterior(tipo, ref)


def _periodo_posterior(tipo, ref):
    if tipo == 'diario':
        return (_diario_data(ref) + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    return periodo_mod.periodo_posterior(tipo, ref)


def _intervalo_periodo(tipo, ref):
    if tipo == 'diario':
        d = _diario_data(ref)
        return d, d
    return periodo_mod.intervalo_datas(tipo, ref)


def _rotulo_periodo(tipo, ref):
    if tipo == 'diario':
        return _diario_data(ref).strftime('%d/%m/%Y')
    return periodo_mod.rotulo(tipo, ref)


def _nav_periodo_row(tipo, state_key, sufixo_key, itens_salvos):
    """Linha ÚNICA de navegação de período: ◀ | seletor | ▶.

    Padrão visual/interação único do app (mesmo bloco já adotado em
    pages/1_Relatorio_Diario_OTHIL.py e pages/4_Quebra_OTHIL.py), no lugar
    da antiga linha de setas + um expander SEPARADO de "🔎 Períodos salvos"
    logo abaixo. A MECÂNICA de navegação continua exatamente a mesma: as
    setas andam por DATA (periodo.py), então seguem funcionando para
    QUALQUER período, com ou sem dado salvo; o seletor lista os períodos
    salvos e sempre exibe também o período navegado no momento, marcado
    "(sem dado)" quando não houver registro.

    Devolve (ref_sel, ini, fim, tem_dado) -- os mesmos valores que os dois
    chamadores (_render_secao_dash e _render_secao_margem_real, antes
    duplicados linha a linha) calculavam por conta própria.
    """
    if state_key not in st.session_state:
        st.session_state[state_key] = _periodo_atual_ref(tipo)

    def _ir_anterior():
        st.session_state[state_key] = _periodo_anterior(tipo, st.session_state[state_key])

    def _ir_posterior():
        st.session_state[state_key] = _periodo_posterior(tipo, st.session_state[state_key])

    labels_salvos = {}
    for _s, _m in itens_salvos:
        if tipo == 'diario':
            labels_salvos[_s] = f"{_m.get('emissao', _s)}  —  {_m.get('periodo','-')}"
        else:
            labels_salvos[_s] = _label_slug(_s, tipo) + f"  ({_m.get('periodo','-')})"

    ref_sel = st.session_state[state_key]
    opcoes = sorted(set(labels_salvos) | {ref_sel}, reverse=True)

    def _fmt_opcao(r):
        if r in labels_salvos:
            return labels_salvos[r]
        try:
            return _rotulo_periodo(tipo, r) + ' (sem dado)'
        except Exception:
            return f'{r} (sem dado)'

    col_prev, col_sel, col_next = st.columns([1, 6, 1], vertical_alignment='bottom')
    with col_prev:
        st.button('◀', key=f'ger_prev{sufixo_key}_{tipo}', help='Período anterior',
                   on_click=_ir_anterior, use_container_width=True)
    with col_next:
        st.button('▶', key=f'ger_next{sufixo_key}_{tipo}', help='Próximo período',
                   on_click=_ir_posterior, use_container_width=True)
    with col_sel:
        # Chave escopada por ref_sel (mesma técnica de
        # pages/1_Relatorio_Diario_OTHIL.py): garante que o `index=` volte a
        # ser aplicado sempre que o período mudar por clique nas setas, em
        # vez de ficar preso ao valor anterior guardado pelo próprio widget.
        escolha = st.selectbox(
            f'Período ({len(labels_salvos)} salvo(s))', opcoes,
            format_func=_fmt_opcao,
            index=opcoes.index(ref_sel),
            key=f'ger_quick_sel{sufixo_key}_{tipo}_{ref_sel}',
        )
    if escolha != ref_sel:
        st.session_state[state_key] = escolha
        st.rerun()

    ini, fim = _intervalo_periodo(tipo, ref_sel)
    tem_dado = ds.has_data(MOD_RELATORIO_DIARIO, tipo, ref_sel)

    if tipo == 'diario':
        st.markdown(f'**{_rotulo_periodo(tipo, ref_sel)}**')
    else:
        st.markdown(f'**{ini.strftime("%d/%m/%Y")} – {fim.strftime("%d/%m/%Y")}**  ·  '
                    f'{_rotulo_periodo(tipo, ref_sel)}')
    st.caption('🟢 Período salvo ✓' if tem_dado else '⚪ Nenhum dado cadastrado para este período.')

    return ref_sel, ini, fim, tem_dado


def _render_secao_dash(tipo, titulo_secao, emoji):
    st.header(f'{emoji} {titulo_secao}')

    ref_sel, ini, fim, tem_dado = _nav_periodo_row(
        tipo, f'_ger_periodo_sel_{tipo}', '', _listar_dashboards(tipo))

    st.divider()

    if not tem_dado:
        tipo_label = {'diario': 'Relatório Diário', 'semanal': 'aba Semanal', 'mensal': 'aba Mensal'}
        st.info(f'Nenhum dado cadastrado para o período de {ini.strftime("%d/%m/%Y")} a '
                f'{fim.strftime("%d/%m/%Y")}. Gere ou importe esse período na página '
                f'**{tipo_label.get(tipo, tipo)}** (seção "Histórico" → "Importar dados históricos").')
        return

    registro = ds.load_current(MOD_RELATORIO_DIARIO, tipo, ref_sel)
    valores = registro.get('valores', {}) or {}
    gerado  = (registro.get('atualizado_em') or '')[:16].replace('T', ' ')
    st.caption(f'Período: {valores.get("periodo","-")}  |  Salvo em: {gerado}')

    html_path = os.path.join(_dir_tipo(tipo), f'{ref_sel}.html')
    if not os.path.exists(html_path):
        st.warning('Este dashboard não pôde ser regenerado automaticamente '
                    '(dado antigo, salvo antes da persistência com histórico de itens, ou período '
                    'importado sem PDF). Gere novamente (ou reenvie o PDF) na página de origem.')
        return
    with open(html_path, 'r', encoding='utf-8') as f:
        html_text = f.read()

    components.html(html_text, height=1400, scrolling=True)
    st.download_button(
        f'⬇️ Baixar {_label_slug(ref_sel, tipo) if tipo != "diario" else ref_sel}',
        data=html_text.encode('utf-8'),
        file_name=f'dashboard_{tipo}_{ref_sel}_OTHIL.html',
        mime='text/html',
        key=f'ger_dl_{tipo}',
    )


# ── Margem Real (custo real por produto, sem despesa administrativa) ──────────
# Reaproveita os MESMOS itens já salvos no histórico do Relatório Diário
# (MOD_RELATORIO_DIARIO) -- sem nenhuma publicação própria -- e o cadastro
# de percentuais por produto (margem_produto.py, editável na página
# "Cadastro de Marcas"). Ao contrário de _listar_dashboards/_render_secao_dash
# acima, o HTML aqui é SEMPRE regenerado na hora (nunca fica em cache no
# disco) -- decisão explícita da Ingrid: a Margem Real de um dia antigo tem
# que usar o percentual MAIS ATUAL do cadastro, não o que valia na época.

def _dir_tipo_margem_real(tipo):
    d = os.path.join(_MARGEM_REAL_DIR, tipo)
    os.makedirs(d, exist_ok=True)
    return d


def _listar_periodos_margem_real(tipo):
    """Períodos que têm itens salvos no Relatório Diário/Semanal/Mensal
    (mesma fonte de dados do Dashboard Gerencial) -- usado só pro atalho de
    seleção rápida, igual ao _listar_dashboards acima."""
    try:
        out = []
        for slug in ds.list_periodos(MOD_RELATORIO_DIARIO, tipo):
            registro = ds.load_current(MOD_RELATORIO_DIARIO, tipo, slug)
            if registro and registro.get('valores', {}).get('itens'):
                out.append((slug, registro['valores']))
        return out
    except Exception:
        return []


def _render_secao_margem_real(tipo, titulo_secao, emoji):
    st.header(f'{emoji} {titulo_secao}')

    # Mesma linha ◀ | seletor | ▶ do Dashboard Gerencial -- as duas seções
    # eram cópias quase idênticas uma da outra; agora compartilham
    # _nav_periodo_row (a única diferença real, a lista de períodos com dado,
    # continua vindo da fonte específica de cada uma).
    ref_sel, ini, fim, tem_dado = _nav_periodo_row(
        tipo, f'_ger_periodo_sel_mr_{tipo}', '_mr', _listar_periodos_margem_real(tipo))

    st.divider()

    if not tem_dado:
        tipo_label = {'diario': 'Relatório Diário', 'semanal': 'aba Semanal', 'mensal': 'aba Mensal'}
        st.info(f'Nenhum dado cadastrado para o período de {ini.strftime("%d/%m/%Y")} a '
                f'{fim.strftime("%d/%m/%Y")}. Gere ou importe esse período na página '
                f'**{tipo_label.get(tipo, tipo)}** (seção "Histórico" → "Importar dados históricos").')
        return

    registro = ds.load_current(MOD_RELATORIO_DIARIO, tipo, ref_sel)
    valores = registro.get('valores', {}) or {}
    if not valores.get('itens'):
        st.warning('Este período foi salvo antes da persistência com histórico de itens, ou foi '
                   'importado sem PDF — não dá pra calcular a Margem Real sem os itens originais. '
                   'Gere novamente (ou reenvie o PDF) na página de origem.')
        return

    gerado = (registro.get('atualizado_em') or '')[:16].replace('T', ' ')
    st.caption(f'Período: {valores.get("periodo","-")}  |  Dado original salvo em: {gerado}')

    tabela = mp.carregar_marcas()
    n_sem_cadastro = sum(1 for it in valores['itens'] if not mp.pct_admin(it.get('produto'), tabela)[1])
    if n_sem_cadastro:
        st.caption(
            f'⚠️ {n_sem_cadastro} linha(s) deste período usam produtos sem marca cadastrada — '
            f'veja a lista no dashboard abaixo e cadastre em **Cadastro de Marcas**.'
        )

    html_path = os.path.join(_dir_tipo_margem_real(tipo), f'{ref_sel}.html')
    try:
        gerar_dashboard_custo_real(
            {'itens': valores['itens'], 'periodo': valores.get('periodo'),
             'data_emissao': valores.get('emissao')},
            tabela, html_path, tipo=tipo,
        )
    except Exception as e:
        st.error(f'Não foi possível calcular a Margem Real deste período: {e}')
        return

    with open(html_path, 'r', encoding='utf-8') as f:
        html_text = f.read()

    components.html(html_text, height=1400, scrolling=True)
    st.download_button(
        f'⬇️ Baixar Margem Real — {_label_slug(ref_sel, tipo) if tipo != "diario" else ref_sel}',
        data=html_text.encode('utf-8'),
        file_name=f'margem_real_{tipo}_{ref_sel}_OTHIL.html',
        mime='text/html',
        key=f'ger_dl_mr_{tipo}',
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
    c1.metric(f'Total CX — {label_a}', f"{_num_vc(total_a, 0)} cx")
    c2.metric(f'Total CX — {label_b}', f"{_num_vc(total_b, 0)} cx")
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
    df_cat_tbl[label_a]     = df_cat_tbl[label_a].map(lambda x: f"{_num_vc(x, 0)}")
    df_cat_tbl[label_b]     = df_cat_tbl[label_b].map(lambda x: f"{_num_vc(x, 0)}")
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
        df_grp[label_a]     = df_grp[label_a].map(lambda x: f"{_num_vc(x, 0)}")
        df_grp[label_b]     = df_grp[label_b].map(lambda x: f"{_num_vc(x, 0)}")
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

    # Mesma linha única ◀ | seletor | ▶ das demais seções (alinhamento pela
    # base em vez dos antigos st.write('') vazios usados como espaçador).
    # A mecânica aqui continua sendo por ÍNDICE na lista de salvos, como
    # sempre foi -- só o layout foi padronizado.
    col_prev, col_sel, col_next = st.columns([1, 6, 1], vertical_alignment='bottom')
    with col_prev:
        if st.button('◀', key=f'ger_qbr_prev_{tipo}', help='Período anterior',
                      use_container_width=True):
            st.session_state[idx_key] = min(st.session_state[idx_key] + 1, len(slugs) - 1)
    with col_next:
        if st.button('▶', key=f'ger_qbr_next_{tipo}', help='Próximo período',
                      use_container_width=True):
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
    col1.metric('Total CX Quebradas', f"{_num_vc(total, 0)} cx")
    if categorias:
        top = categorias[0]
        col2.metric(f'Maior: {top["categoria"]}', f"{_num_vc(top['cx'], 0)} cx")

    # ── Comparativo automático vs período anterior salvo (menor é melhor)
    if idx + 1 < len(historico):
        dados_ant = historico[idx + 1][1]
        total_ant = dados_ant.get('total_cx', 0)
        comp_auto = comparativo.calcular(total, total_ant, menor_e_melhor=True)
        st.metric(
            f'📊 vs período anterior ({_qbr_label(slugs[idx + 1], tipo)})',
            f"{_num_vc(total, 0)} cx",
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


def _on_track_status_ger(atingido: float, dia: int, total_dias: int = 6):
    """(emoji, label, hex_color) — via lógica central de On Track
    (on_track.py), tempo decorrido em dias de venda da semana comercial
    sábado a sexta (1..6, sem domingo -- ver calc.dia_semana_atual), MESMA
    convenção usada em Metas Semanais (calc.py é a fonte única). Corrige
    inconsistência: esta função usava a convenção ANTIGA segunda-sexta
    (1..5, dia/5) mesmo depois da semana comercial de Metas Semanais já
    ter virado sexta-sexta -- exatamente o tipo de divergência que a
    Ingrid pediu pra eliminar ("não criar uma segunda lógica de
    semana")."""
    pct_tempo = (dia / total_dias) if total_dias else 0.0
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
    return sorted(items.items(), key=lambda kv: _sort_key_semana_slug(kv[0]), reverse=True)


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

    # Mensagem da correção de semana (ver "🔧 Corrigir a semana desta
    # publicação" abaixo) -- precisa ficar guardada no session_state e
    # exibida SÓ no rerun seguinte: st.success() chamado bem antes de um
    # st.rerun() nunca chega a aparecer na tela (o rerun já troca a página
    # antes da pessoa ver), dando a falsa impressão de que o botão não fez
    # nada (bug real reportado pela Ingrid, 31/08/2026 -- ela clicou,
    # "nada aconteceu", mas o registro novo tinha sido salvo mesmo assim).
    _msg_corr_ot = st.session_state.pop('_ger_ot_corrigir_msg', None)
    if _msg_corr_ot:
        (st.success if _msg_corr_ot[0] == 'success' else st.warning)(_msg_corr_ot[1])

    historico_ot = _listar_ontrack_metas_hist()
    slug_ot = None

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
        # Linha única ◀ | seletor | ▶, mesmo padrão das demais seções (antes
        # era só a lista suspensa, sem setas). A lista em si e a leitura do
        # snapshot continuam iguais -- o índice apenas passou a ficar no
        # session_state pra as setas poderem andar nele.
        idx_key_ot = '_ger_ot_meta_idx'
        if idx_key_ot not in st.session_state:
            st.session_state[idx_key_ot] = 0

        col_prev_ot, col_sel_ot, col_next_ot = st.columns([1, 6, 1], vertical_alignment='bottom')
        with col_prev_ot:
            if st.button('◀', key='ger_ot_meta_prev', help='Semana anterior',
                          use_container_width=True):
                st.session_state[idx_key_ot] = min(st.session_state[idx_key_ot] + 1,
                                                    len(labels_ot) - 1)
        with col_next_ot:
            if st.button('▶', key='ger_ot_meta_next', help='Próxima semana',
                          use_container_width=True):
                st.session_state[idx_key_ot] = max(st.session_state[idx_key_ot] - 1, 0)
        with col_sel_ot:
            escolha_ot = st.selectbox(
                f'{len(historico_ot)} semana(s) disponível(is):',
                labels_ot,
                index=min(st.session_state[idx_key_ot], len(labels_ot) - 1),
                key='ger_ot_meta_sel',
            )
        idx_ot = labels_ot.index(escolha_ot)
        st.session_state[idx_key_ot] = idx_ot
        slug_ot = historico_ot[idx_ot][0]
        snap = historico_ot[idx_ot][1]

    pub_em     = snap.get('publicado_em', '')[:16].replace('T', ' ')
    periodo    = snap.get('periodo', '—')
    resultados = snap.get('resultados', [])
    totais_rs  = snap.get('totais_rs', {})

    st.caption(f"Período: **{periodo}**  |  Publicado em: **{pub_em}**")

    # Corrigir semana errada (31/08/2026, pedido da Ingrid) -- mesma
    # ferramenta e mesmo motivo da que existe em "Fechamentos Semanais"
    # (ver _render_fechamentos_semanais acima): uma publicação feita ANTES
    # da migração pra semana comercial sábado-a-sexta pode ter sido salva
    # sob a semana errada, pela mesma ambiguidade da sexta que motivou a
    # migração (publicar "hoje" numa sexta lia aquela sexta como abertura
    # da semana NOVA, não fechamento da que estava terminando -- ver
    # calc.py). Não recalcula nada -- só re-salva o MESMO snapshot já
    # publicado sob o periodo_ref certo. Só aparece quando há uma semana
    # selecionada (slug_ot) -- não no fallback do arquivo único legado.
    if slug_ot:
        with st.expander('🔧 Corrigir a semana desta publicação'):
            st.caption(
                f'Semana atual desta publicação: **{_label_fech(slug_ot)}**. '
                'Escolha uma data dentro da semana comercial CORRETA e '
                'confirme abaixo -- o snapshot publicado (resultados, '
                'totais) continua exatamente o mesmo, só a semana em que '
                'fica arquivado muda.'
            )
            nova_data_ot = st.date_input(
                'Data dentro da semana correta', value=datetime.date.today(),
                format='DD/MM/YYYY', key=f'ger_ot_corrigir_data_{slug_ot}',
            )
            novo_slug_ot = calc.slug_semana(nova_data_ot)
            if novo_slug_ot == slug_ot:
                st.caption('Essa data cai na mesma semana já usada -- nada a corrigir.')
            else:
                st.caption(f'Nova semana: **{calc.label_semana(novo_slug_ot)}**')
                if st.button('✅ Corrigir e salvar sob essa semana', key=f'ger_ot_corrigir_btn_{slug_ot}'):
                    try:
                        _reg_corr_ot = ds.save_record(
                            modulo=MOD_ONTRACK_METAS, tipo_periodo='semanal', periodo_ref=novo_slug_ot,
                            valores=snap, usuario=st.session_state.get('usuario_nome'),
                        )
                        _erro_corr_ot = _reg_corr_ot.get('_erro_persistencia_remota') if _reg_corr_ot else None
                        # Reseleciona automaticamente o registro CORRIGIDO.
                        # BUG REAL encontrado em 31/08/2026 (Ingrid: "dá
                        # sucesso, porém não altera a data"): só ajustar
                        # st.session_state[idx_key_ot] não bastava -- o
                        # st.selectbox abaixo tem seu PRÓPRIO key
                        # ('ger_ot_meta_sel'), que guarda o rótulo (texto)
                        # já escolhido. Depois que um widget com key já
                        # rodou uma vez, o Streamlit ignora o argumento
                        # index= em reruns seguintes e mantém o valor que
                        # já está em session_state[key] -- por isso a
                        # semana continuava exibindo a mesma antiga. A
                        # correção real é apagar esse key do session_state
                        # também, pra o widget nascer de novo no próximo
                        # rerun usando o index= (que aí sim reflete a
                        # semana recém-corrigida).
                        _hist_novo_ot = _listar_ontrack_metas_hist()
                        _slugs_novo_ot = [s for s, _ in _hist_novo_ot]
                        if novo_slug_ot in _slugs_novo_ot:
                            st.session_state[idx_key_ot] = _slugs_novo_ot.index(novo_slug_ot)
                            st.session_state.pop('ger_ot_meta_sel', None)
                        if _erro_corr_ot:
                            st.session_state['_ger_ot_corrigir_msg'] = (
                                'warning',
                                f'Salvo, mas houve um problema ao persistir de forma permanente: {_erro_corr_ot}',
                            )
                        else:
                            st.session_state['_ger_ot_corrigir_msg'] = (
                                'success',
                                f'✅ Salvo como {calc.label_semana(novo_slug_ot)}. A publicação antiga '
                                '(sob a semana errada) continua no histórico, sem uso.',
                            )
                        st.rerun()
                    except Exception as e:
                        st.error(f'Erro ao corrigir: {e}')

    # Dia calculado em relação à semana SELECIONADA acima (slug_ot), não à
    # que o calendário de hoje sugeriria por conta própria -- útil quando a
    # tela está mostrando uma semana diferente da atual (histórico), já que
    # calc.dia_semana_atual() sozinho sempre se refere à semana de hoje.
    _dia_default = (calc.dia_semana_no_periodo(slug_ot) if slug_ot
                     else calc.dia_semana_atual())
    # Chave inclui a semana selecionada -- sem isso, o slider ficaria
    # "preso" no valor da última semana visitada ao trocar de período
    # (mesmo bug de fundo: mistura o estado de duas semanas diferentes).
    dia = st.slider(
        'Dia da semana (para status On Track)', 1, 6,
        value=_dia_default,
        format='Dia %d de 6', key=f'ger_ot_dia_{slug_ot or "legado"}',
        help='Semana comercial sábado a sexta (sem domingo, que não tem '
             'venda): Sábado=1  Segunda=2  Terça=3  Quarta=4  Quinta=5  '
             'Sexta (fecha a semana)=6 -- mesma convenção da aba Metas '
             'Semanais. Calculado em relação à semana selecionada acima, '
             'não à data de hoje sozinha.',
    )

    st.divider()

    # KPIs gerais / Faturamento Geral removidos daqui a pedido explícito da
    # Ingrid (28/08/2026) -- ela quis a tela mais enxuta, indo direto pro
    # detalhamento Por Produto / Por Vendedor abaixo, sem repetir o resumo
    # geral aqui.

    # Por produto -- mesmo padrão visual/estrutural do "Por Vendedor" logo
    # abaixo (tabela via st.dataframe, não mais uma lista de accordions).
    # Meta/Vendido seguem em CAIXAS (cx): não existe Faturamento/MC calculado
    # por PRODUTO no app (só por vendedor, vindo do PDF de Lucratividade).
    st.subheader('Por Produto')
    prow = []
    for r in resultados:
        # Meta do produto = 'estoque_total' real, não a soma das metas
        # individuais por vendedor (ver nota nos KPIs gerais acima).
        p_meta = r.get('estoque_total', 0)
        p_vend = sum(l['vendido'] for l in r.get('linhas', []))
        p_atg  = p_vend / p_meta if p_meta else 0
        p_em, p_lb, _ = _on_track_status_ger(p_atg, dia)
        prow.append({
            'Produto':      r.get('produto', ''),
            'Prioridade':   r.get('prioridade', 'Normal'),
            'Meta (cx)':    p_meta,
            'Vendido (cx)': p_vend,
            '% Atingido':   p_atg,
            'Status':       f'{p_em} {p_lb}',
        })
    df_prod = pd.DataFrame(prow)
    if not df_prod.empty:
        df_prod['Meta (cx)']    = df_prod['Meta (cx)'].map(lambda x: f'{_num_vc(x, 0)}')
        df_prod['Vendido (cx)'] = df_prod['Vendido (cx)'].map(lambda x: f'{_num_vc(x, 0)}')
        df_prod['% Atingido']   = df_prod['% Atingido'].map(lambda x: f'{x*100:.1f}%')
    st.dataframe(df_prod, use_container_width=True, hide_index=True)

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
            'Meta (cx)':   f"{_num_vc(ag['meta'], 0)}",
            'Vendido (cx)': f"{_num_vc(ag['vendido'], 0)}",
            '% Atingido':  f"{v_atg*100:.1f}%",
            'Status':      f'{v_em} {v_lb}',
            'Fat R$':      f"R$ {_num_vc(rs['fat'], 2)}"   if rs.get('fat')    is not None else '—',
            'MC R$':       f"R$ {_num_vc(rs['mc_rs'], 2)}" if rs.get('mc_rs') is not None else '—',
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

    return sorted(items.items(), key=lambda kv: _sort_key_semana_slug(kv[0]), reverse=True)


def _label_fech(slug: str) -> str:
    """Rótulo em português do fechamento `slug`.

    BUG REAL encontrado em 31/08/2026 (reportado pela Ingrid: rótulo
    'Semana 28/08 a 04/09' sem sentido pra um fechamento cujo período era
    21/08 a 28/08): esta função reimplementava sua PRÓPRIA conta de data
    de fim (+7 dias corridos, sem pular domingo) em vez de usar
    calc.label_semana() -- exatamente o tipo de "segunda lógica de
    semana divergente" que a Ingrid pediu pra nunca existir (26/08/2026).
    Além de duplicada, essa conta local nunca foi atualizada quando a
    semana comercial virou sábado-a-sexta (31/08/2026, ver calc.py), então
    seguia calculando como se ainda fosse a definição antiga.

    FONTE ÚNICA agora: calc.label_semana(), a mesma usada em Metas
    Semanais e nas demais seções desta página. Formato antigo "AAAA-Www"
    (slugs arquivados de antes da migração pra semana comercial em
    18/08/2026) continua caindo em periodo_mod.rotulo()."""
    if '-W' in slug:
        try:
            return periodo_mod.rotulo('semanal', slug)
        except Exception:
            return slug
    return calc.label_semana(slug)


def _sort_key_semana_slug(slug: str) -> str:
    """Chave de ordenação cronológica pros slugs de semana de Metas
    Semanais (MOD_FECHAMENTO / MOD_ONTRACK_METAS), que durante a transição
    pra semana sexta-a-sexta podem estar em dois formatos: o antigo ISO
    "AAAA-Www" e o novo "AAAA-MM-DD". Ordenar a string pura intercala os
    dois formatos errado ('W' > dígito no ASCII) -- aqui os dois convergem
    pra uma data real comparável (a segunda-feira ISO da semana, no
    formato antigo)."""
    try:
        ano_s, semana_s = slug.split('-W')
        return datetime.date.fromisocalendar(int(ano_s), int(semana_s), 1).isoformat()
    except (ValueError, IndexError):
        return slug


def _render_fechamentos_semanais():
    st.header('🏁 Fechamentos Semanais')

    # Mensagem da correção de semana (ver "🔧 Corrigir a semana deste
    # fechamento" abaixo) -- mesmo motivo do comentário equivalente em
    # _render_ontrack_publicado() acima: st.success() logo antes de um
    # st.rerun() nunca chega a aparecer (bug real reportado pela Ingrid,
    # 31/08/2026 -- "não está dando certo" / "nada acontece", quando na
    # real o registro novo tinha sido salvo).
    _msg_corr_fech = st.session_state.pop('_ger_fech_corrigir_msg', None)
    if _msg_corr_fech:
        (st.success if _msg_corr_fech[0] == 'success' else st.warning)(_msg_corr_fech[1])

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

    # Linha única ◀ | seletor | ▶ padronizada com as demais seções.
    col_prev, col_sel, col_next = st.columns([1, 6, 1], vertical_alignment='bottom')
    with col_prev:
        if st.button('◀', key='ger_fech_prev', help='Semana anterior', use_container_width=True):
            st.session_state[idx_key] = min(st.session_state[idx_key] + 1, len(slugs) - 1)
    with col_next:
        if st.button('▶', key='ger_fech_next', help='Próxima semana', use_container_width=True):
            st.session_state[idx_key] = max(st.session_state[idx_key] - 1, 0)
    with col_sel:
        escolha = st.selectbox(
            f'{len(historico)} fechamento(s) salvo(s):',
            labels,
            index=min(st.session_state[idx_key], len(labels) - 1),
            key='ger_fech_sel',
        )
        st.session_state[idx_key] = labels.index(escolha)

    idx        = st.session_state[idx_key]
    slug_atual = slugs[idx]
    dados      = historico[idx][1]

    gerado = dados.get('gerado_em', '')[:16].replace('T', ' ')
    st.caption(f"Período: {dados.get('periodo', '-')}  |  Salvo em: {gerado}")

    # Corrigir semana errada (31/08/2026, pedido da Ingrid): um fechamento
    # feito ANTES da migração pra semana comercial sábado-a-sexta podia ter
    # sido salvo sob a semana errada por causa da própria ambiguidade da
    # sexta que motivou essa migração (fechar "hoje" numa sexta lia aquela
    # sexta como abertura da semana NOVA, não fechamento da que estava
    # terminando -- ver calc.py). A Ingrid não quer recalcular/refechar do
    # zero pra corrigir isso -- só re-salva os MESMOS dados já calculados
    # sob o periodo_ref certo. O fechamento antigo (sob a semana errada)
    # não é apagado (não existe uma função de apagar em data_store.py, e
    # não é o caso de criar uma só pra isso) -- fica órfão no histórico,
    # sem efeito prático, exatamente como já foi explicado pra ela.
    with st.expander('🔧 Corrigir a semana deste fechamento'):
        st.caption(
            f'Semana atual deste fechamento: **{_label_fech(slug_atual)}**. '
            'Escolha uma data dentro da semana comercial CORRETA (qualquer '
            'dia entre a abertura e o fechamento dela) e confirme abaixo -- '
            'os dados calculados (metas, vendido, matriz produto × '
            'vendedor) continuam exatamente os mesmos, só a semana em que '
            'ficam arquivados muda.'
        )
        nova_data_fech = st.date_input(
            'Data dentro da semana correta', value=datetime.date.today(),
            format='DD/MM/YYYY', key=f'ger_fech_corrigir_data_{slug_atual}',
        )
        novo_slug_fech = calc.slug_semana(nova_data_fech)
        if novo_slug_fech == slug_atual:
            st.caption('Essa data cai na mesma semana já usada -- nada a corrigir.')
        else:
            st.caption(f'Nova semana: **{calc.label_semana(novo_slug_fech)}**')
            if st.button('✅ Corrigir e salvar sob essa semana', key=f'ger_fech_corrigir_btn_{slug_atual}'):
                try:
                    _reg_corr = ds.save_record(
                        modulo=MOD_FECHAMENTO, tipo_periodo='semanal', periodo_ref=novo_slug_fech,
                        valores=dados, usuario=st.session_state.get('usuario_nome'),
                    )
                    _erro_corr = _reg_corr.get('_erro_persistencia_remota') if _reg_corr else None
                    # Reseleciona automaticamente o registro CORRIGIDO --
                    # mesmo bug e mesma correção do comentário equivalente
                    # na correção de On Track acima ("dá sucesso, porém não
                    # altera a data"): o st.selectbox tem seu PRÓPRIO key
                    # ('ger_fech_sel'), que precisa ser apagado do
                    # session_state também -- só ajustar idx_key não é
                    # suficiente, porque o Streamlit ignora index= num
                    # widget com key que já rodou antes.
                    _hist_novo_fech = _listar_fechamentos()
                    _slugs_novo_fech = [s for s, _ in _hist_novo_fech]
                    if novo_slug_fech in _slugs_novo_fech:
                        st.session_state[idx_key] = _slugs_novo_fech.index(novo_slug_fech)
                        st.session_state.pop('ger_fech_sel', None)
                    if _erro_corr:
                        st.session_state['_ger_fech_corrigir_msg'] = (
                            'warning',
                            f'Salvo, mas houve um problema ao persistir de forma permanente: {_erro_corr}',
                        )
                    else:
                        st.session_state['_ger_fech_corrigir_msg'] = (
                            'success',
                            f'✅ Salvo como {calc.label_semana(novo_slug_fech)}. O fechamento antigo '
                            '(sob a semana errada) continua no histórico, sem uso.',
                        )
                    st.rerun()
                except Exception as e:
                    st.error(f'Erro ao corrigir: {e}')

    prods = dados.get('produtos', [])

    # KPIs gerais / Faturamento Geral removidos daqui a pedido explícito da
    # Ingrid (28/08/2026), mesmo ajuste feito em "On Track Atual" -- tela
    # mais enxuta, indo direto pra matriz Produto × Vendedor abaixo.

    st.divider()

    # Matriz Produto × Vendedor agrupada por prioridade -- igual ao Resumo
    # Geral (mesma implementação usada na prévia de Metas Semanais, ver
    # resumo_matriz.py, pra nunca ficar diferente daqui pra lá)
    resumo_matriz.render_matriz_produto_vendedor(prods)

    # Comparativo de Semanas removido daqui a pedido explícito da Ingrid
    # (28/08/2026) -- tela mais enxuta, encerrando na matriz Produto ×
    # Vendedor acima.


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
        # Linha única ◀ | seletor | ▶, mesmo padrão das demais seções (antes
        # era só a lista suspensa, sem setas). A lista e a leitura do
        # snapshot continuam iguais.
        idx_key_cli = '_ger_ot_cli_idx'
        if idx_key_cli not in st.session_state:
            st.session_state[idx_key_cli] = 0

        col_prev_cli, col_sel_cli, col_next_cli = st.columns([1, 6, 1], vertical_alignment='bottom')
        with col_prev_cli:
            if st.button('◀', key='ger_ot_cli_prev', help='Mês anterior',
                          use_container_width=True):
                st.session_state[idx_key_cli] = min(st.session_state[idx_key_cli] + 1,
                                                     len(labels_cli) - 1)
        with col_next_cli:
            if st.button('▶', key='ger_ot_cli_next', help='Próximo mês',
                          use_container_width=True):
                st.session_state[idx_key_cli] = max(st.session_state[idx_key_cli] - 1, 0)
        with col_sel_cli:
            escolha_cli = st.selectbox(
                f'{len(historico_cli)} mês(es) disponível(is):',
                labels_cli,
                index=min(st.session_state[idx_key_cli], len(labels_cli) - 1),
                key='ger_ot_cli_sel',
            )
        idx_cli = labels_cli.index(escolha_cli)
        st.session_state[idx_key_cli] = idx_cli
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

    # Cards de resumo em st.metric NATIVO (antes: grid de 6 divs cinza com
    # borda esquerda colorida montadas à mão). Mesmos 6 indicadores, mesma
    # ordem e mesmos valores -- o emoji de status segue no "% Atingido" e a
    # seta ▲/▼ segue na "Diferença Proj.".
    cm1, cm2, cm3, cm4, cm5, cm6 = st.columns(6)
    cm1.metric('Meta Mensal',     _brl(tot_meta))
    cm2.metric('Faturamento',     _brl(tot_fat))
    cm3.metric('% Atingido',      f'{tot_pct*100:.1f}% {g_em}')
    cm3.caption(f'{g_em} {g_lb}')
    cm4.metric('Valor Restante',  _brl(tot_rest))
    cm5.metric('Projeção Mês',    _brl(tot_proj))
    cm6.metric('Diferença Proj.', f"{'▲' if tot_dif >= 0 else '▼'} {_brl(abs(tot_dif))}")

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


def _brl_vc(v):
    v = v or 0.0
    s = f"{abs(v):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"R$ {'-' if v < 0 else ''}{s}"


def _num_vc(v, casas=0):
    v = v or 0.0
    return f"{v:,.{casas}f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def _get_meta_fat_vc(historico_data: dict, vend: str, cli_key: str):
    """Busca meta de faturamento do cliente no histórico salvo -- mesma
    lógica de pages/3_Vendedor_Cliente_OTHIL.py (não duplica o cálculo,
    só a leitura, já que a Gerência lê o mesmo registro salvo)."""
    if not historico_data:
        return None
    tab = VENDOR_TAB.get(vend, vend.upper())
    meta_vend = historico_data.get('meta', {}).get(tab, {})
    if not meta_vend:
        return None
    if cli_key in meta_vend:
        m = meta_vend[cli_key]
        return m.get('fat') if m else None
    cli_norm = _normalize(cli_key)
    for k, v in meta_vend.items():
        if _normalize(k) == cli_norm:
            return v.get('fat') if v else None
    return None


def _meses_vc_disponiveis():
    """Meses com relatório Vendedor-Cliente salvo (gerado na página
    Vendedor-Cliente, aba 'Relatório Semanal' -- o registro fica salvo
    automaticamente a cada geração de Excel, sem precisar de um passo de
    publicação separado). Mais recente primeiro."""
    try:
        return sorted(ds.list_periodos(MOD_VENDEDOR_CLIENTE, 'mensal'), reverse=True)
    except Exception:
        return []


def _render_top50_clientes_ger():
    st.header('🏆 Top 50 Clientes')
    st.caption('Lê o mesmo relatório salvo automaticamente quando você gera o Excel Vendedor-Cliente '
               '(aba "📋 Relatório Semanal") -- não precisa de nenhuma publicação extra.')
    try:
        st.page_link('pages/3_Vendedor_Cliente_OTHIL.py',
                      label='Abrir módulo completo →', icon='📋')
    except Exception:
        pass

    meses_vc = _meses_vc_disponiveis()
    if not meses_vc:
        st.info('Nenhum relatório Vendedor-Cliente salvo ainda. Gere o Excel na página '
                '**Vendedor-Cliente** primeiro.')
        return

    ref_50 = st.selectbox('Mês', meses_vc, format_func=lambda r: periodo_mod.rotulo('mensal', r),
                           key='ger_vc_top50_mes')
    registro_50 = ds.load_current(MOD_VENDEDOR_CLIENTE, 'mensal', ref_50)
    if not registro_50:
        st.info('Sem dados para este mês.')
        return
    clientes_data_50 = registro_50['valores'].get('clientes_data', {})
    historico_data_50 = registro_50['valores'].get('historico', {})
    if not clientes_data_50:
        st.info('Registro salvo, mas sem dados de clientes.')
        return

    ordenar_por = st.selectbox(
        'Ordenar por',
        ['Faturamento', 'Volume', 'Margem (MC R$)', 'Rentabilidade (MC %)', 'Atingimento da meta'],
        key='ger_vc_top50_sort',
    )

    ref_ant_50 = periodo_mod.periodo_anterior('mensal', ref_50)
    reg_ant_50 = ds.load_current(MOD_VENDEDOR_CLIENTE, 'mensal', ref_ant_50)
    clientes_ant_50 = reg_ant_50['valores'].get('clientes_data', {}) if reg_ant_50 else {}

    linhas_50 = []
    for vendedor, clientes in clientes_data_50.items():
        for cliente, dados in clientes.items():
            fat = dados.get('fat', 0)
            vol = dados.get('vol', 0)
            mc_rs = dados.get('mc_rs', 0)
            mc_pct = dados.get('mc_pct', 0)
            meta = _get_meta_fat_vc(historico_data_50, vendedor, cliente) or 0

            fat_ant = None
            cli_ant = (clientes_ant_50.get(vendedor) or {})
            if cliente in cli_ant:
                fat_ant = cli_ant[cliente].get('fat')
            else:
                cli_norm = _normalize(cliente)
                for k, v in cli_ant.items():
                    if _normalize(k) == cli_norm:
                        fat_ant = v.get('fat')
                        break
            comp = comparativo.calcular(fat, fat_ant)

            if meta:
                pct_atg = fat / meta
                r_ot = on_track.calcular(meta, fat, 'mensal', ref_50)
                status_txt = f"{r_ot['emoji']} {r_ot['label']}"
            else:
                pct_atg = None
                status_txt = '—'

            linhas_50.append({
                'Vendedor': vendedor, 'Cliente': cliente,
                '_fat': fat, '_vol': vol, '_mc_rs': mc_rs, '_mc_pct': mc_pct,
                '_pct_atg': pct_atg or 0, 'Faturamento': _brl_vc(fat),
                'Volume (cx)': f'{_num_vc(vol, 0)}', 'Margem (MC R$)': _brl_vc(mc_rs),
                'Rentabilidade': f'{mc_pct:.1f}%',
                'Comparativo': comparativo.formatar_variacao(comp),
                '% Atingido': f'{pct_atg*100:.1f}%' if pct_atg is not None else '—',
                'On Track': status_txt,
            })

    if not linhas_50:
        st.info('Nenhum cliente neste mês.')
        return

    sort_key_map = {
        'Faturamento': '_fat', 'Volume': '_vol', 'Margem (MC R$)': '_mc_rs',
        'Rentabilidade (MC %)': '_mc_pct', 'Atingimento da meta': '_pct_atg',
    }
    linhas_50.sort(key=lambda r: r[sort_key_map[ordenar_por]], reverse=True)
    top50 = linhas_50[:50]
    for i, r in enumerate(top50, start=1):
        r['Ranking'] = i

    st.caption(f'{len(linhas_50)} cliente(s) no total — mostrando os {len(top50)} principais '
               f'por {ordenar_por.lower()}.')

    df_top50 = pd.DataFrame(top50)[[
        'Ranking', 'Vendedor', 'Cliente', 'Faturamento', 'Volume (cx)',
        'Margem (MC R$)', 'Rentabilidade', 'Comparativo', '% Atingido', 'On Track',
    ]]
    st.dataframe(df_top50, use_container_width=True, hide_index=True)

    csv_top50 = df_top50.to_csv(index=False, sep=';').encode('utf-8-sig')
    st.download_button(
        '⬇️ Exportar Top 50 (CSV)', data=csv_top50,
        file_name=f'top50_clientes_ger_{ref_50}.csv', mime='text/csv', key='ger_vc_top50_csv',
    )


def _render_clientes_por_vendedor_ger():
    st.header('👤 Clientes por Vendedor')
    st.caption('Lê o mesmo relatório salvo automaticamente quando você gera o Excel Vendedor-Cliente '
               '(aba "📋 Relatório Semanal") -- não precisa de nenhuma publicação extra.')

    meses_vc = _meses_vc_disponiveis()
    if not meses_vc:
        st.info('Nenhum relatório Vendedor-Cliente salvo ainda. Gere o Excel na página '
                '**Vendedor-Cliente** primeiro.')
        return

    ref_pv = st.selectbox('Mês', meses_vc, format_func=lambda r: periodo_mod.rotulo('mensal', r),
                           key='ger_vc_pv_mes')
    registro_pv = ds.load_current(MOD_VENDEDOR_CLIENTE, 'mensal', ref_pv)
    if not registro_pv:
        st.info('Sem dados para este mês.')
        return
    clientes_data_pv = registro_pv['valores'].get('clientes_data', {})
    historico_data_pv = registro_pv['valores'].get('historico', {})
    if not clientes_data_pv:
        st.info('Registro salvo, mas sem dados de clientes.')
        return

    vendedor_sel_pv = st.selectbox('Selecionar vendedor', sorted(clientes_data_pv.keys()),
                                    key='ger_vc_pv_vendedor')

    ref_ant_pv = periodo_mod.periodo_anterior('mensal', ref_pv)
    reg_ant_pv = ds.load_current(MOD_VENDEDOR_CLIENTE, 'mensal', ref_ant_pv)
    clientes_ant_pv_vend = ((reg_ant_pv['valores'].get('clientes_data', {}) if reg_ant_pv else {})
                             .get(vendedor_sel_pv, {}))

    clientes_vendedor = clientes_data_pv.get(vendedor_sel_pv, {})
    fat_total_vendedor = sum(d.get('fat', 0) for d in clientes_vendedor.values()) or 1e-9

    linhas_pv = []
    for cliente, dados in clientes_vendedor.items():
        fat = dados.get('fat', 0)
        vol = dados.get('vol', 0)
        mc_rs = dados.get('mc_rs', 0)
        mc_pct = dados.get('mc_pct', 0)
        meta = _get_meta_fat_vc(historico_data_pv, vendedor_sel_pv, cliente) or 0
        participacao = fat / fat_total_vendedor

        fat_ant = None
        if cliente in clientes_ant_pv_vend:
            fat_ant = clientes_ant_pv_vend[cliente].get('fat')
        else:
            cli_norm = _normalize(cliente)
            for k, v in clientes_ant_pv_vend.items():
                if _normalize(k) == cli_norm:
                    fat_ant = v.get('fat')
                    break
        comp = comparativo.calcular(fat, fat_ant)

        if meta:
            r_ot = on_track.calcular(meta, fat, 'mensal', ref_pv)
            status_txt = f"{r_ot['emoji']} {r_ot['label']}"
        else:
            status_txt = '—'

        linhas_pv.append({
            '_fat': fat,
            'Cliente': cliente, 'Faturamento': _brl_vc(fat), 'Volume (cx)': f'{_num_vc(vol, 0)}',
            'Margem (MC R$)': _brl_vc(mc_rs), 'Rentabilidade': f'{mc_pct:.1f}%',
            'Comparativo': comparativo.formatar_variacao(comp),
            'Participação no vendedor': f'{participacao*100:.1f}%',
            'On Track': status_txt,
        })

    if not linhas_pv:
        st.info(f'Nenhum cliente de {vendedor_sel_pv} neste mês.')
        return

    linhas_pv.sort(key=lambda r: r['_fat'], reverse=True)

    st.caption(f'{len(linhas_pv)} cliente(s) de **{vendedor_sel_pv}** em '
               f'{periodo_mod.rotulo("mensal", ref_pv)} — faturamento total: {_brl_vc(fat_total_vendedor)}')

    df_pv = pd.DataFrame(linhas_pv)[[
        'Cliente', 'Faturamento', 'Volume (cx)', 'Margem (MC R$)', 'Rentabilidade',
        'Comparativo', 'Participação no vendedor', 'On Track',
    ]]
    st.dataframe(df_pv, use_container_width=True, hide_index=True)

    csv_pv = df_pv.to_csv(index=False, sep=';').encode('utf-8-sig')
    st.download_button(
        f'⬇️ Exportar clientes de {vendedor_sel_pv} (CSV)', data=csv_pv,
        file_name=f'clientes_{vendedor_sel_pv}_ger_{ref_pv}.csv', mime='text/csv', key='ger_vc_pv_csv',
    )


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

def _barra_horizontal_meta(titulo, realizado, meta, status, unidade_fmt, subtitulo=None):
    """Barra horizontal de progresso (realizado vs meta), preenchendo da
    esquerda pra direita conforme o % atingido -- pedido explícito da
    Ingrid, 28/08/2026: "um gráfico na horizontal em que vai enchendo à
    medida que vamos faturando de acordo com a meta". Cor igual ao status
    on-track (mesmo mapa único _GER_STATUS_CORES usado no resto da tela --
    nunca uma segunda paleta). O preenchimento visual nunca passa de 100%
    da largura (fisicamente não cabe no container), mas o texto do %
    sempre mostra o valor real mesmo acima de 100% -- nunca esconde o
    número (mesma filosofia de mg.quebra_semanal_meta: passar de 100% não
    é limitado nem escondido)."""
    cor = _GER_STATUS_CORES[status]['cor']
    pct = (realizado / meta * 100) if (meta and realizado is not None) else None
    largura = min(pct, 100) if pct is not None else 0.0
    pct_txt = f'{pct:.0f}%' if pct is not None else '—'
    val_txt = unidade_fmt(realizado) if realizado is not None else '—'
    meta_txt = unidade_fmt(meta) if meta else '—'
    st.markdown(
        f'<div style="margin-bottom:0.2rem;">'
        f'<div style="display:flex; justify-content:space-between; font-size:0.95rem; '
        f'margin-bottom:4px;"><span style="font-weight:600;">{titulo}</span>'
        f'<span>{val_txt} <span style="color:#888;">/ {meta_txt}</span></span></div>'
        f'<div style="background:#EDEDED; border-radius:8px; height:30px; '
        f'overflow:hidden; position:relative;">'
        f'<div style="background:{cor}; width:{largura:.1f}%; height:100%; '
        f'border-radius:8px;"></div>'
        f'<div style="position:absolute; top:0; left:0; width:100%; height:100%; '
        f'display:flex; align-items:center; justify-content:center; font-weight:700; '
        f'font-size:0.9rem; color:#1a1a1a;">{pct_txt}</div></div></div>',
        unsafe_allow_html=True,
    )
    if subtitulo:
        st.caption(subtitulo)


def _badge_indicador_simples(status, titulo, valor_txt, detalhe=None):
    """Indicador simplificado (badge colorido, 1 número em destaque) --
    pedido explícito da Ingrid, 28/08/2026: "algum indicador simplificado
    que acompanhe o track de margem" / "algum indicador que vá indicando a
    relação quebra vs faturamento". Mesmas cores de status do resto da
    tela (_GER_STATUS_CORES bg/fg), sem os detalhes extras (projeção,
    histórico etc.) que os cards anteriores tinham -- só o essencial."""
    cores = _GER_STATUS_CORES[status]
    st.markdown(
        f'<div style="background:{cores["bg"]}; color:{cores["fg"]}; border-radius:8px; '
        f'padding:10px 14px; margin-bottom:0.2rem;">'
        f'<div style="font-size:0.8rem; font-weight:600; opacity:0.85;">{titulo}</div>'
        f'<div style="font-size:1.35rem; font-weight:700;">{valor_txt}</div></div>',
        unsafe_allow_html=True,
    )
    if detalhe:
        st.caption(detalhe)


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
    # Os blocos "Comparativo vs período anterior" (Empresa e Vendedor) foram
    # removidos a pedido explícito da Ingrid em 26/08/2026 ("remover
    # completamente"), junto com o cálculo de período/realizado anterior
    # que só existia pra alimentá-los.

    tab_empresa, tab_vendedor = st.tabs(['🏢 Empresa', '👤 Vendedor'])

    # =========================================================================
    # ABA EMPRESA — consolidado (equivalente à aba "GERAL" do Vendedor-Cliente)
    # =========================================================================
    with tab_empresa:
        meta_atual = mg.carregar_meta(tipo_mg, ref_mg) or {}

        # ── Indicadores primeiro ─────────────────────────────────────────────
        # Ordem de leitura invertida em relação à versão anterior (que abria
        # com o formulário de meta e o histórico de alterações, empurrando os
        # KPIs pra baixo): quem abre a aba quer ver PRIMEIRO como a empresa
        # está no período. As ferramentas de edição/auditoria da meta
        # (formulário "🎯 Definir/editar meta" e "🕘 Histórico de alterações")
        # continuam idênticas, só passaram para logo abaixo dos indicadores.
        pct_tempo_mg = periodo_mod.pct_tempo_decorrido(tipo_mg, ref_mg)
        _completude_msgs = {
            'sem_dado': f'⚪ Sem dado publicado ainda para {periodo_mod.rotulo(tipo_mg, ref_mg)} (fonte: {rv.get("origem","-")}).',
            'parcial':  f'🟡 Dado parcial: {len(rv.get("meses_com_dado", []))}/{len(rv.get("meses_total", []))} mês(es) do período têm publicação.',
            # Distinto de 'sem_dado': aqui o Vendedor-Cliente PODE já estar
            # publicado, só não deu pra confirmar agora porque a consulta ao
            # GitHub falhou (rede/token/rate-limit) -- ver
            # ds.load_current_com_erro(). Antes esse caso ficava idêntico a
            # "sem dado publicado", escondendo uma falha real de leitura.
            'erro_leitura': (f'🔴 Não deu pra confirmar o dado de {periodo_mod.rotulo(tipo_mg, ref_mg)} agora '
                              f'-- a consulta ao GitHub falhou (pode já estar publicado, mas não foi possível '
                              f'verificar). Tente recarregar a página em alguns instantes. '
                              f'Detalhe técnico: {rv.get("erro_leitura", "-")}'),
            'completo': None,
        }

        # 3 indicadores simplificados -- substituem os 4 cards detalhados
        # anteriores (Faturamento/Volume/Margem/Quebra, cada um com
        # meta/realizado/%/status/projeção), a pedido explícito da Ingrid
        # (28/08/2026): "Track da meta geral: um gráfico na horizontal que
        # vai enchendo + indicador simplificado de margem + indicador de
        # quebra vs faturamento. Apenas isso nos dá o que precisamos... e
        # gera um baita engajamento." Os CÁLCULOS continuam os mesmos de
        # sempre (mg.realizado_vendas / on_track.calcular / mg.status_quebra
        # / mg.quebra_pct_faturamento) -- só a apresentação foi trocada por
        # algo mais visual e direto. Volume (CX) deixou de ter indicador
        # dedicado aqui (continua no gráfico de Evolução logo abaixo e no
        # ranking da aba Vendedor).
        st.subheader('Indicadores da Empresa')

        # NÃO usar `or 0` no realizado: rv.get(...) retorna None quando
        # ainda não há dado publicado (diferente de "publicado e deu
        # zero"), e on_track.calcular já trata None corretamente (status
        # ⚪ Sem meta/dado). Convertendo para 0 aqui, o cálculo interpretava
        # como "0% atingido" e mostrava 🔴 Fora do Track incorretamente
        # assim que o período começava, mesmo sem nenhum dado publicado.
        ot_fat = on_track.calcular(meta_atual.get('faturamento') or 0, rv.get('faturamento'),
                                    tipo_mg, ref_mg, pct_tempo_decorrido=pct_tempo_mg)
        _barra_horizontal_meta(
            '💰 Faturamento', rv.get('faturamento'), meta_atual.get('faturamento'),
            ot_fat['status'], lambda x: f'R$ {_num_vc(x, 0)}',
            subtitulo=_completude_msgs.get(rv['completude']),
        )

        st.markdown('<div style="height:0.6rem;"></div>', unsafe_allow_html=True)
        _col_marg, _col_qbr = st.columns(2)
        with _col_marg:
            ot_marg = on_track.calcular(meta_atual.get('margem_pct') or 0, rv.get('margem_pct'),
                                         tipo_mg, ref_mg, pct_tempo_decorrido=pct_tempo_mg)
            _marg_realizado = rv.get('margem_pct')
            _marg_txt = f"{_marg_realizado:.1f}%" if _marg_realizado is not None else '—'
            _marg_det = (f"Meta: {meta_atual['margem_pct']:.1f}%" if meta_atual.get('margem_pct')
                         else 'Meta de margem não definida')
            _badge_indicador_simples(ot_marg['status'], '📊 Margem', _marg_txt, _marg_det)
        with _col_qbr:
            # Mesma prioridade R$ > cx da versão anterior do card de Quebra:
            # usa custo real (R$) quando já extraído do PDF e o Teto em R$
            # já foi definido; senão cai pra cx.
            _qbr_meta_rs = meta_atual.get('quebra_max_rs')
            _qbr_realizado_rs = rq.get('total_custo')
            _usa_rs_qbr = bool(_qbr_meta_rs) and _qbr_realizado_rs is not None
            if _usa_rs_qbr:
                _ot_qbr = mg.status_quebra(_qbr_meta_rs, _qbr_realizado_rs, tipo_mg, ref_mg)
            else:
                _ot_qbr = mg.status_quebra(meta_atual.get('quebra_max_cx'), rq.get('total_cx'),
                                            tipo_mg, ref_mg)
            # A "relação quebra vs faturamento" pedida pela Ingrid -- REALIZADO
            # sobre REALIZADO (não meta sobre meta): quanto da quebra de
            # verdade já representa do faturamento de verdade até agora.
            _qbr_pct_real = mg.quebra_pct_faturamento(_qbr_realizado_rs, rv.get('faturamento'))
            if _qbr_pct_real is not None:
                _qbr_txt = f"{_qbr_pct_real:.2f}% do fat."
                _qbr_txt_em_rs = True
            elif rq.get('total_cx') is not None:
                _qbr_txt = f"{_num_vc(rq.get('total_cx'), 0)} cx"
                _qbr_txt_em_rs = False
            else:
                _qbr_txt = '—'
                _qbr_txt_em_rs = _usa_rs_qbr  # sem valor nenhum -- tanto faz, não há unidade pra casar
            # O Teto mostrado precisa estar na MESMA unidade do valor acima
            # (_qbr_txt_em_rs), senão compara cx com R$ sem relação nenhuma
            # entre si (bug real: com custo real ainda não extraído do PDF de
            # quebra -- ou faturamento ainda não publicado pra calcular o %
            # -- o valor cai pra cx mas o Teto continuava priorizando R$
            # sempre que ele estivesse definido, mostrando ex. "831 cx" ao
            # lado de "Teto: R$ 80.000,00"). Usa o que efetivamente formou
            # _qbr_txt acima (_qbr_txt_em_rs), não _usa_rs_qbr sozinho --
            # _usa_rs_qbr fica True mesmo quando o % não deu pra calcular
            # por falta de faturamento, e nesse caso _qbr_txt já caiu pra cx.
            if _qbr_txt_em_rs and _qbr_meta_rs:
                _qbr_det = f"Teto: R$ {_num_vc(_qbr_meta_rs, 2)}"
            elif meta_atual.get('quebra_max_cx'):
                _qbr_det = f"Teto: {_num_vc(meta_atual['quebra_max_cx'], 0)} cx"
            elif _qbr_meta_rs:
                _qbr_det = (f"Teto em R$ definido ({_num_vc(_qbr_meta_rs, 2)}), mas ainda falta "
                            f"custo real de quebra e/ou faturamento publicado pra comparar -- "
                            f"defina também um Teto de Quebra (CX) pra ter um indicador aqui.")
            else:
                _qbr_det = 'Teto de quebra não definido'
            # Mesma distinção "sem dado" vs "falha ao consultar" já aplicada
            # no Faturamento (ver _completude_msgs['erro_leitura']) -- sem
            # isso, uma falha de leitura no GitHub ficava idêntica a "nunca
            # publicou quebra nenhuma" aqui também.
            if _qbr_txt == '—' and rq.get('erro_leitura'):
                _qbr_det = (f'🔴 Não deu pra confirmar -- consulta ao GitHub falhou. '
                            f'Detalhe técnico: {rq["erro_leitura"]}')
            _badge_indicador_simples(_ot_qbr['status'], '📦 Quebra vs Faturamento', _qbr_txt, _qbr_det)

        st.divider()

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
                    meta_qbr_rs = st.number_input(
                        'Teto de Quebra (R$)', min_value=0.0,
                        value=float(meta_atual.get('quebra_max_rs') or 0.0), step=1000.0,
                        help='Opcional -- independente do Teto em CX acima (não converte um no outro). '
                             'Usado só pra calcular quanto isso representa em % da Meta de Faturamento, '
                             'exibido no indicador de Quebra acima.')
                if st.form_submit_button('💾 Salvar meta', type='primary'):
                    _reg_meta = mg.salvar_meta(tipo_mg, ref_mg, meta_fat, meta_vol, meta_marg, meta_qbr,
                                                quebra_max_rs=meta_qbr_rs or None,
                                                usuario=st.session_state.get('usuario_nome'))
                    # data_store.save_record devolve '_erro_persistencia_remota' quando
                    # a gravação no GitHub falha (token expirado, instabilidade da API,
                    # etc.) -- nesse caso o dado só fica no cache local efêmero e é
                    # perdido no próximo restart/redeploy do Streamlit Cloud. Antes esse
                    # retorno era descartado e a tela sempre mostrava "Meta salva." como
                    # se tivesse persistido de verdade, mesmo quando não persistiu.
                    _erro_meta = _reg_meta.get('_erro_persistencia_remota') if _reg_meta else None
                    if _erro_meta:
                        st.warning(f'Meta salva localmente, mas houve um problema ao salvar de forma '
                                   f'permanente: {_erro_meta}. Tente salvar de novo em alguns instantes.')
                    else:
                        st.success('Meta salva.')
                    st.rerun()

        _hist_meta = mg.historico_meta(tipo_mg, ref_mg)
        with st.expander(f'🕘 Histórico de alterações da meta — {periodo_mod.rotulo(tipo_mg, ref_mg)} '
                          f'({len(_hist_meta)} versão(ões) anterior(es))'):
            if not _hist_meta:
                st.caption('Nenhuma alteração anterior registrada para este período — a meta atual '
                           'acima é a primeira versão salva.')
            else:
                # Mais recente primeiro (load_history devolve da mais antiga pra mais nova).
                _linhas_hist = []
                for _v in reversed(_hist_meta):
                    _vals = _v.get('valores', {}) or {}
                    _linhas_hist.append({
                        'Versão': _v.get('versao'),
                        'Salvo em': (_v.get('atualizado_em') or '')[:16].replace('T', ' '),
                        'Por': _v.get('usuario', 'não identificado'),
                        'Faturamento': f"R$ {_num_vc(_vals.get('faturamento', 0), 0)}",
                        'Volume (CX)': f"{_num_vc(_vals.get('volume', 0), 0)}",
                        'Margem (%)': f"{_vals.get('margem_pct', 0):.2f}%",
                        'Teto Quebra (CX)': f"{_num_vc(_vals.get('quebra_max_cx', 0), 0)}",
                        'Teto Quebra (R$)': (f"R$ {_num_vc(_vals.get('quebra_max_rs'), 2)}"
                                              if _vals.get('quebra_max_rs') else '—'),
                    })
                st.dataframe(pd.DataFrame(_linhas_hist), hide_index=True, use_container_width=True)

        # Comparativo vs período anterior removido a pedido explícito da
        # Ingrid em 26/08/2026 ("remover completamente"), pra deixar a tela
        # mais compacta.

        # ── Publicar Realizado do Período (PDF) ──────────────────────────────
        # Pedido explícito da Ingrid, 29/08/2026: "não quero que seja a soma a
        # partir do módulo vendedor cliente, quero que tenha espaço pra eu
        # adicionar os PDFs e ele calcular -- o mesmo para a quebra". Publica
        # DIRETO aqui (mg.MOD_MG_VENDAS / mg.MOD_MG_QUEBRA), independente do
        # que estiver ou não publicado em Vendedor-Cliente/Quebra -- só
        # reaproveita os mesmos parsers que aquelas páginas já usam
        # (parsers_vendedor.parse_totais_vendedor / parser_quebra.parse_quebra).
        # Só faz sentido por mês (cada PDF é de um período fechado
        # específico), por isso só fica ativo com Tipo de período = Mensal --
        # mesmo padrão já usado no OnTrack Semanal logo abaixo.
        with st.expander(f'📤 Publicar Realizado — {periodo_mod.rotulo(tipo_mg, ref_mg)}'):
            if tipo_mg != 'mensal':
                st.caption('Publicação é sempre por mês -- mude "Tipo de período" acima pra '
                           '**Mensal** e selecione o mês do PDF pra publicar.')
            else:
                st.caption('Sobe o PDF do relatório e o app calcula sozinho -- não depende do '
                           'que foi (ou não) publicado nas páginas Vendedor-Cliente / Quebra.')
                col_pub_v, col_pub_q = st.columns(2)
                with col_pub_v:
                    st.markdown('**💰 Faturamento / Volume / Margem**')
                    pdf_vendas_mg = st.file_uploader(
                        'PDF Lucratividade por Vendedor', type='pdf', key='mg_pdf_vendas')
                    if pdf_vendas_mg is not None and st.button(
                            '📊 Processar e publicar Vendas', key='mg_btn_pub_vendas'):
                        with st.spinner('Lendo PDF...'):
                            try:
                                _reg_v = mg.publicar_vendas_pdf(
                                    ref_mg, pdf_vendas_mg,
                                    usuario=st.session_state.get('usuario_nome'))
                                _erro_v = _reg_v.get('_erro_persistencia_remota') if _reg_v else None
                                _tg = (_reg_v.get('valores') or {}).get('total_geral') or {}
                                if _erro_v:
                                    st.warning(f'Processado, mas houve um problema ao salvar de '
                                               f'forma permanente: {_erro_v}')
                                else:
                                    st.success(
                                        f"✅ Publicado: R$ {_num_vc(_tg.get('fat', 0), 2)} de "
                                        f"faturamento, {_num_vc(_tg.get('vol', 0), 0)} cx, "
                                        f"{_tg.get('resultado_real', 0):.2f}% de margem."
                                    )
                                st.rerun()
                            except Exception as _e_pub_v:
                                st.error(f'Erro ao processar o PDF: {_e_pub_v}')
                with col_pub_q:
                    st.markdown('**📦 Quebra**')
                    pdf_quebra_mg = st.file_uploader(
                        'PDF Resumo do Estoque (Quebra)', type='pdf', key='mg_pdf_quebra')
                    if pdf_quebra_mg is not None and st.button(
                            '📊 Processar e publicar Quebra', key='mg_btn_pub_quebra'):
                        with st.spinner('Lendo PDF...'):
                            try:
                                _reg_q = mg.publicar_quebra_pdf(
                                    ref_mg, pdf_quebra_mg,
                                    usuario=st.session_state.get('usuario_nome'))
                                _erro_q = _reg_q.get('_erro_persistencia_remota') if _reg_q else None
                                _vq = (_reg_q.get('valores') or {}) if _reg_q else {}
                                if _erro_q:
                                    st.warning(f'Processado, mas houve um problema ao salvar de '
                                               f'forma permanente: {_erro_q}')
                                else:
                                    _custo_txt = (f", R$ {_num_vc(_vq.get('total_custo'), 2)}"
                                                  if _vq.get('total_custo') is not None else '')
                                    st.success(
                                        f"✅ Publicado: {_num_vc(_vq.get('total_cx', 0), 0)} cx "
                                        f"quebradas{_custo_txt}."
                                    )
                                st.rerun()
                            except Exception as _e_pub_q:
                                st.error(f'Erro ao processar o PDF: {_e_pub_q}')

        # ── Evolução ──────────────────────────────────────────────────────────
        # Faturamento, Volume e Margem já existiam (Quebra tinha sido removida
        # DESSE MESMO gráfico combinado a pedido da Ingrid em 25/08/2026:
        # "gráfico de quebra não é necessário" -- ela se referia a não misturar
        # Quebra no mesmo gráfico/eixo de Faturamento/Volume/Margem).
        # Gráfico de Quebra (R$) adicionado em 26/08/2026 a pedido explícito
        # (item 5 do pedido "AJUSTES NO APP": "adicionar também um gráfico de
        # quebra na aba Evolução" -- ela esclareceu que é o indicador de
        # Quebra de verdade, não uma quebra/breakdown por dimensão). Fica
        # como card SEPARADO dos outros 3, mesmos filtros/período, sem alterar
        # os 3 gráficos existentes.
        st.subheader('📈 Evolução')
        hist_refs = list(reversed(periodo_mod.listar_periodos(tipo_mg, n=8, ate=ref_mg)))
        evol_rows = []
        for r in hist_refs:
            rv_h = mg.realizado_vendas(tipo_mg, r)
            rq_h = mg.realizado_quebra(tipo_mg, r)
            evol_rows.append({
                'Período': periodo_mod.rotulo(tipo_mg, r),
                'Faturamento': rv_h.get('faturamento') or 0,
                'Volume (CX)': rv_h.get('volume') or 0,
                'Margem (%)': rv_h.get('margem_pct') or 0,
                # Mesma prioridade R$ > cx do indicador de Quebra acima:
                # custo real quando já extraído do PDF, senão cx como fallback.
                'Quebra (R$)': (rq_h.get('total_custo') if rq_h.get('total_custo') is not None
                                 else (rq_h.get('total_cx') or 0)),
            })
        if evol_rows:
            import pandas as _pd
            df_evol = _pd.DataFrame(evol_rows).set_index('Período')
            # sort=False em todos: por padrão o st.bar_chart ordena o eixo
            # categórico em ordem alfabética (comportamento do Altair/Vega-Lite
            # pra colunas de texto), o que embaralhava os meses (Abril, Agosto,
            # Fevereiro, Janeiro...) mesmo com df_evol já montado na ordem
            # cronológica certa (via hist_refs acima). sort=False desliga essa
            # ordenação automática e preserva a ordem das linhas do DataFrame.
            ev1, ev2, ev3 = st.columns(3)
            with ev1:
                st.caption('Faturamento (R$)')
                st.bar_chart(df_evol[['Faturamento']], color='#2D6A4F', sort=False)
            with ev2:
                st.caption('Volume (CX)')
                st.bar_chart(df_evol[['Volume (CX)']], color='#7C6FAD', sort=False)
            with ev3:
                st.caption('Margem (%)')
                st.bar_chart(df_evol[['Margem (%)']], color='#2A6F97', sort=False)
            st.caption('Quebra (R$ — ou cx, quando o custo real ainda não foi extraído do PDF)')
            st.bar_chart(df_evol[['Quebra (R$)']], color='#BC4749', sort=False)

        # ── OnTrack Semanal — quebra da meta MENSAL fixa (Faturamento) ──────
        # Só faz sentido pra 'mensal' (não dá pra quebrar um trimestre/ano em
        # "semana 1 a 4"). A meta em si (meta_atual['faturamento'], já
        # definida acima) NUNCA muda aqui -- só a expectativa acumulada por
        # semana, calculada a partir dos percentuais configuráveis abaixo.
        if tipo_mg == 'mensal':
            st.divider()
            st.subheader('📅 OnTrack Semanal — Quebra da Meta Mensal (Faturamento)')
            st.caption(
                'A Meta de Faturamento definida acima nunca muda. Aqui se acompanha, semana '
                'a semana, quanto dela já era esperado ter sido vendido (percentuais '
                'incrementais -- podem somar mais ou menos que 100%, isso é normal) e o '
                '**Atingimento**, que é sempre o vendido acumulado sobre a META TOTAL do mês '
                '(não sobre o esperado daquela semana).'
            )
            with st.expander('⚙️ Configurar percentuais semanais'):
                st.caption(
                    f'Percentuais específicos de {periodo_mod.rotulo(tipo_mg, ref_mg)} -- cada '
                    f'mês tem o seu próprio conjunto. As "semanas" aqui são 4 blocos '
                    f'sequenciais de dias corridos a partir do dia 1 do mês (dias 1-7, 8-14, '
                    f'15-21 e 22-fim) -- não são semanas ISO do calendário, por isso todo mês '
                    f'sempre tem a mesma quantidade de semanas (4).'
                )
                _pcts_atuais = mg.carregar_pcts_semanais(ref_mg)
                with st.form(key='mg_form_pcts_semanais'):
                    _n_sem_cfg = st.number_input(
                        'Quantidade de semanas configuradas', min_value=1, max_value=8,
                        value=len(_pcts_atuais), step=1, key='mg_pcts_n',
                    )
                    _pcts_inputs = []
                    _cols_pct = st.columns(int(_n_sem_cfg))
                    for _i in range(int(_n_sem_cfg)):
                        _valor_padrao = _pcts_atuais[_i] if _i < len(_pcts_atuais) else 0.0
                        with _cols_pct[_i]:
                            _pcts_inputs.append(st.number_input(
                                f'Semana {_i + 1:02d} do mês (%)', min_value=0.0,
                                value=float(_valor_padrao), step=1.0, key=f'mg_pct_sem_{_i}',
                            ))
                    _soma_pcts = sum(_pcts_inputs)
                    st.caption(f'Soma dos percentuais: {_soma_pcts:.0f}% — pode ser diferente '
                               f'de 100% (maior ou menor), isso é permitido de propósito.')
                    if st.form_submit_button('💾 Salvar percentuais', type='primary'):
                        mg.salvar_pcts_semanais(ref_mg, _pcts_inputs, usuario=st.session_state.get('usuario_nome'))
                        st.success(f'Percentuais semanais de {periodo_mod.rotulo(tipo_mg, ref_mg)} salvos.')
                        st.rerun()

            _meta_fat_mg = meta_atual.get('faturamento')
            if not _meta_fat_mg:
                st.info('Defina a Meta de Faturamento acima pra ver a quebra semanal.')
            else:
                _quebra_emp = mg.quebra_semanal_meta(ref_mg, _meta_fat_mg)
                _rows_quebra = [{
                    'Semana':             l['label'],
                    'Meta fixa (R$)':     f"R$ {_num_vc(_meta_fat_mg, 2)}",
                    '% semanal':          f"{l['pct_semana']:.0f}%",
                    'Esperado acumulado': f"R$ {_num_vc(l['esperado_acumulado'], 2)}",
                    'Vendido acumulado':  f"R$ {_num_vc(l['vendido_acumulado'], 2)}" if l['vendido_acumulado'] is not None else '—',
                    'Atingimento':        f"{l['atingimento']:.0f}%" if l['atingimento'] is not None else '—',
                } for l in _quebra_emp]
                st.dataframe(pd.DataFrame(_rows_quebra), use_container_width=True, hide_index=True)

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
                'Faturamento': lambda v: f"R$ {_num_vc(v, 2)}", 'Volume (CX)': lambda v: _num_vc(v, 3),
                'Margem %': '{:.2f}%', 'Participação': '{:.1f}%',
            })
            st.dataframe(styled_rank, use_container_width=True, hide_index=True)

            # Drill-down individual
            st.divider()
            st.subheader('🔎 Detalhe por vendedor')
            vend_sel_mg = st.selectbox('Selecionar vendedor', sorted(vendedores_mg.keys()), key='mg_vend_sel')
            v_sel = vendedores_mg.get(vend_sel_mg, {})
            dc1, dc2, dc3, dc4 = st.columns(4)
            dc1.metric('Faturamento', f"R$ {_num_vc(v_sel.get('fat', 0), 2)}")
            dc2.metric('Volume (CX)', f"{_num_vc(v_sel.get('vol', 0), 3)}")
            dc3.metric('Margem %', f"{v_sel.get('mc_pct', 0):.2f}%")
            dc4.metric('Participação na empresa',
                       f"{(v_sel.get('fat', 0) / fat_total_emp * 100) if fat_total_emp else 0:.1f}%")
            # Comparativo vs período anterior removido a pedido explícito da
            # Ingrid em 26/08/2026 ("remover completamente").

        # ── OnTrack Semanal por Vendedor — quebra da meta MENSAL fixa dele ──
        # Fica FORA do if/else acima de propósito: precisa estar disponível
        # mesmo sem nenhum dado de vendas ainda (início do mês), já que a
        # meta é digitada aqui, não vem de realizado_vendas.
        if tipo_mg == 'mensal':
            st.divider()
            st.subheader('📅 OnTrack Semanal por Vendedor')
            st.caption(
                'Meta fixa individual de Faturamento por vendedor (independente da meta '
                'da empresa) -- nunca é calculada como fatia da meta geral nem como soma '
                'de outra coisa, você digita direto aqui.'
            )
            _metas_vend_atuais = mg.carregar_metas_vendedores(tipo_mg, ref_mg)
            with st.expander('🎯 Definir/editar meta fixa de Faturamento por vendedor'):
                with st.form(key='mg_form_metas_vendedores'):
                    _novas_metas_vend = {}
                    _nomes_vend_cfg = list(calc.VENDEDORES_PADRAO.keys())
                    _cols_mv = st.columns(4)
                    for _i, _nome_v in enumerate(_nomes_vend_cfg):
                        with _cols_mv[_i % 4]:
                            _novas_metas_vend[_nome_v] = st.number_input(
                                f'{_nome_v} (R$)', min_value=0.0,
                                value=float(_metas_vend_atuais.get(_nome_v) or 0.0), step=1000.0,
                                key=f'mg_meta_vend_{_nome_v}',
                            )
                    if st.form_submit_button('💾 Salvar metas dos vendedores', type='primary'):
                        mg.salvar_metas_vendedores(tipo_mg, ref_mg, _novas_metas_vend,
                                                    usuario=st.session_state.get('usuario_nome'))
                        st.success('Metas dos vendedores salvas.')
                        st.rerun()

            _vend_com_meta = {k: v for k, v in _metas_vend_atuais.items() if v}
            if not _vend_com_meta:
                st.info('Defina a meta fixa de pelo menos um vendedor acima pra ver a quebra semanal.')
            else:
                _vend_sel_sem = st.selectbox('Vendedor', sorted(_vend_com_meta.keys()),
                                              key='mg_ot_semanal_vend_sel')
                _meta_fixa_v = _vend_com_meta[_vend_sel_sem]
                _quebra_v = mg.quebra_semanal_meta(ref_mg, _meta_fixa_v, vendedor=_vend_sel_sem)
                _rows_quebra_v = [{
                    'Semana':             l['label'],
                    'Meta fixa (R$)':     f"R$ {_num_vc(_meta_fixa_v, 2)}",
                    '% semanal':          f"{l['pct_semana']:.0f}%",
                    'Esperado acumulado': f"R$ {_num_vc(l['esperado_acumulado'], 2)}",
                    'Vendido acumulado':  f"R$ {_num_vc(l['vendido_acumulado'], 2)}" if l['vendido_acumulado'] is not None else '—',
                    'Atingimento':        f"{l['atingimento']:.0f}%" if l['atingimento'] is not None else '—',
                } for l in _quebra_v]
                st.dataframe(pd.DataFrame(_rows_quebra_v), use_container_width=True, hide_index=True)


# ── Auth ──────────────────────────────────────────────────────────────────────
if not _check_auth():
    st.stop()

# Mesmo padrão usado em todas as outras páginas (ex.: pages/metas_semanais.py,
# pages/4_Quebra_OTHIL.py) -- sem isso, qualquer gravação feita a partir desta
# página (ex.: "Salvar meta" em Metas Gerais) ficava com usuario="não
# identificado" no histórico versionado sempre que a Gerência era a primeira
# página aberta na sessão (não passando antes por nenhuma outra página que já
# define este valor).
st.session_state.setdefault('usuario_nome', 'Ingrid')


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
    c1.metric('Faturamento', f"R$ {_num_vc(kpi['faturamento'], 2)}",
              delta=comparativo.formatar_variacao(_c('faturamento')) if kpi_ant else None)
    c2.metric('Margem R$', f"R$ {_num_vc(kpi['margem_rs'], 2)}",
              delta=comparativo.formatar_variacao(_c('margem_rs')) if kpi_ant else None)
    c3.metric('Margem %', f"{kpi['margem_pct']:.2f}%",
              delta=comparativo.formatar_variacao(_c('margem_pct')) if kpi_ant else None)
    c4.metric('Ticket Médio', f"R$ {_num_vc(kpi['ticket_medio'], 2)}",
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


def _render_produtos_resumo():
    st.header('📦 Relatórios de Produtos — Resumo')
    st.caption('Visão consolidada para a Gerência (reaproveita o mesmo motor de cálculo do módulo '
               'completo -- nenhuma lógica de faturamento/volume foi duplicada aqui).')
    try:
        st.page_link('pages/7_Relatorios_Produtos_OTHIL.py',
                      label='Abrir módulo completo (filtros, rankings, matrizes, histórico) →', icon='📦')
    except Exception:
        pass

    itens_base, avisos = prod.carregar_base_consolidada()
    if not itens_base:
        st.info('Ainda não há dados suficientes. Faça upload de pelo menos um Relatório Diário, '
                'Semanal ou Mensal.')
        return
    if avisos:
        st.caption(f'ℹ️ {len(avisos)} registro(s) não incluído(s) no histórico consolidado (evita duplicidade).')

    col_tipo, col_periodo = st.columns([1, 2])
    with col_tipo:
        tipo_p = st.selectbox('Período', periodo_mod.TIPOS_PERIODO, format_func=periodo_mod.rotulo_tipo,
                               index=1, key='ger_prod_tipo')
    opcoes_p = prod.periodos_disponiveis(itens_base, tipo_p)
    if not opcoes_p:
        st.warning('Nenhum dado disponível para esse tipo de período.')
        return
    with col_periodo:
        ref_p = st.selectbox('Referência', opcoes_p, format_func=lambda r: periodo_mod.rotulo(tipo_p, r),
                              key='ger_prod_periodo')

    itens_p = prod.filtrar_periodo(itens_base, tipo_p, ref_p)
    if not itens_p:
        st.info('Sem dados para este período.')
        return
    kpi = prod.kpis_produto(itens_p)
    ref_ant = periodo_mod.periodo_anterior(tipo_p, ref_p)
    itens_ant = prod.filtrar_periodo(itens_base, tipo_p, ref_ant)
    kpi_ant = prod.kpis_produto(itens_ant) if itens_ant else None

    def _c(chave):
        return comparativo.calcular(kpi.get(chave), kpi_ant.get(chave)) if kpi_ant else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric('Produtos Trabalhados', kpi.get('skus', 0),
              delta=comparativo.formatar_variacao(_c('skus')) if kpi_ant else None)
    c2.metric('Faturamento', f"R$ {_num_vc(kpi['faturamento'], 2)}",
              delta=comparativo.formatar_variacao(_c('faturamento')) if kpi_ant else None)
    c3.metric('Volume (cx)', f"{_num_vc(kpi['volume'], 3)}",
              delta=comparativo.formatar_variacao(_c('volume')) if kpi_ant else None)
    c4.metric('Margem de Contribuição', f"R$ {_num_vc(kpi['margem_rs'], 2)}",
              delta=comparativo.formatar_variacao(_c('margem_rs')) if kpi_ant else None)

    c5, c6, c7 = st.columns(3)
    margem_pp_ger = (kpi['margem_pct'] - kpi_ant['margem_pct']) if kpi_ant else None
    c5.metric('Margem %', f"{kpi['margem_pct']:.2f}%",
              delta=(f"{'+' if margem_pp_ger >= 0 else ''}{margem_pp_ger:.2f} p.p."
                     if margem_pp_ger is not None else None))
    c6.metric('Grupo Líder', kpi.get('grupo_lider') or '-')
    c7.metric('Produto Líder', kpi.get('produto_lider') or '-')

    ranking_ger = prod.ranking_com_crescimento(itens_p, itens_ant or None)
    contagem_ger = prod.contagem_crescimento_queda(ranking_ger)
    dest = prod.destaques(itens_p, itens_ant)
    if dest:
        rcol1, rcol2 = st.columns(2)
        with rcol1:
            if dest.get('maior_crescimento'):
                mc = dest['maior_crescimento']
                st.markdown(f"**📈 Maior crescimento:** {mc['chave']} ({mc['crescimento_pct']:.2f}%) "
                            f"— {contagem_ger['crescimento']} produto(s) em crescimento no total.")
            else:
                st.markdown('**📈 Maior crescimento:** nenhum produto cresceu neste recorte.')
        with rcol2:
            if dest.get('maior_queda'):
                mq = dest['maior_queda']
                st.markdown(f"**📉 Maior queda:** {mq['chave']} ({mq['crescimento_pct']:.2f}%) "
                            f"— {contagem_ger['queda']} produto(s) em queda no total.")
            else:
                st.markdown('**📉 Maior queda:** nenhum produto caiu neste recorte.')

    st.markdown('**🏆 Top 5 Produtos (Faturamento)**')
    top_p = sorted(prod.por_produto(itens_p), key=lambda l: l['faturamento'], reverse=True)[:5]
    st.dataframe(pd.DataFrame([{'Produto': p['chave'], 'Faturamento R$': p['faturamento'],
                                 'Margem R$': p['margem_rs'], 'Volume (cx)': p['volume']} for p in top_p]),
                 use_container_width=True, hide_index=True)

    alertas = prod.alertas_produtos(itens_p, itens_ant or None)
    st.markdown('**🚨 Pontos de Atenção**')
    if not alertas:
        st.success('Nenhum ponto de atenção identificado.')
    else:
        for a in alertas[:5]:
            icone = '🔴' if a['severidade'] == 'critico' else '🟡'
            st.markdown(f"{icone} **{a['tipo']}** — {a['detalhe']}")
        if len(alertas) > 5:
            st.caption(f'+ {len(alertas) - 5} outro(s) ponto(s) de atenção. Veja o módulo completo para a lista inteira.')


def _render_recorrencia_resumo():
    st.header('🔄 Recorrência de Vendas — Resumo')
    st.caption('Publicações salvas na página **Recorrência**, organizadas por período '
               '(semanal/mensal/trimestral/semestral/anual) -- igual Rentabilidade e Produtos.')
    try:
        st.page_link('pages/2_Recorrencia_OTHIL.py',
                      label='Abrir módulo completo (upload de PDF, matriz cliente x produto) →', icon='🔄')
    except Exception:
        pass

    col_tipo, col_periodo = st.columns([1, 2])
    with col_tipo:
        tipo_rc = st.selectbox('Período', periodo_mod.TIPOS_PERIODO, format_func=periodo_mod.rotulo_tipo,
                                index=0, key='ger_rec_tipo')
    try:
        refs_rc = sorted(ds.list_periodos(MOD_RECORRENCIA, tipo_rc), reverse=True)
    except Exception:
        refs_rc = []
    if not refs_rc:
        st.info(f'Nenhuma recorrência publicada ainda como {periodo_mod.rotulo_tipo(tipo_rc)}. '
                'Publique um PDF na página **Recorrência**.')
    else:
        with col_periodo:
            ref_rc = st.selectbox('Referência', refs_rc,
                                   format_func=lambda r: periodo_mod.rotulo(tipo_rc, r),
                                   key='ger_rec_periodo')

        registro_rc = ds.load_current(MOD_RECORRENCIA, tipo_rc, ref_rc)
        if not registro_rc:
            st.info('Sem dados para este período.')
        else:
            val_rc = registro_rc['valores']
            totais_rc = val_rc.get('totais', {})
            st.caption(f"Período (texto do PDF): {val_rc.get('periodo','-')}  |  "
                       f"Emissão: {val_rc.get('emissao','-')}")

            ref_ant_rc = periodo_mod.periodo_anterior(tipo_rc, ref_rc)
            try:
                registro_ant_rc = ds.load_current(MOD_RECORRENCIA, tipo_rc, ref_ant_rc)
            except Exception:
                registro_ant_rc = None
            tot_ant_rc = registro_ant_rc['valores'].get('totais', {}) if registro_ant_rc else None

            def _c_rc(chave):
                return comparativo.calcular(totais_rc.get(chave), tot_ant_rc.get(chave)) if tot_ant_rc else None

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric('Faturamento', f"R$ {_num_vc(totais_rc.get('faturamento', 0), 2)}",
                      delta=comparativo.formatar_variacao(_c_rc('faturamento')) if tot_ant_rc else None)
            c2.metric('MC R$', f"R$ {_num_vc(totais_rc.get('mc_rs', 0), 2)}",
                      delta=comparativo.formatar_variacao(_c_rc('mc_rs')) if tot_ant_rc else None)
            c3.metric('MC %', f"{totais_rc.get('mc_pct', 0):.2f}%")
            c4.metric('Total CX', f"{_num_vc(totais_rc.get('caixas', 0), 3)}",
                      delta=comparativo.formatar_variacao(_c_rc('caixas')) if tot_ant_rc else None)
            c5.metric('Clientes', totais_rc.get('n_clientes', '-'),
                      delta=comparativo.formatar_variacao(_c_rc('n_clientes')) if tot_ant_rc else None)
            if tot_ant_rc:
                st.caption(f'Base de comparação: {periodo_mod.rotulo(tipo_rc, ref_ant_rc)}')

            clientes_rc = val_rc.get('clientes', [])
            if clientes_rc:
                df_rc = pd.DataFrame(clientes_rc)
                top30_rc = df_rc.head(30).set_index('Cliente')[['Faturamento R$']]
                st.markdown('**Top 30 clientes — Faturamento (R$)**')
                st.bar_chart(top30_rc, color='#2D6A4F')
                with st.expander(f'Todos os clientes ({len(df_rc)})'):
                    styled_rc = df_rc.style.format({
                        'Faturamento R$': lambda v: f"R$ {_num_vc(v, 2)}",
                        'Caixas': lambda v: _num_vc(v, 3),
                        'MC R$': lambda v: f"R$ {_num_vc(v, 2)}",
                        'MC %': '{:.2f}%',
                    })
                    st.dataframe(styled_rc, use_container_width=True, hide_index=True)

    _hist_legado_rc = _listar_recorrencias_ger()
    if _hist_legado_rc:
        with st.expander(f'📜 Histórico antigo ({len(_hist_legado_rc)} publicação(ões) salvas '
                          'antes do sistema de período estruturado)'):
            for _slug_lrc, _val_lrc, _ts_lrc in _hist_legado_rc:
                _tot_lrc = _val_lrc.get('totais', {})
                st.caption(
                    f"{_val_lrc.get('periodo','-')} — emissão {_val_lrc.get('emissao','-')} "
                    f"— Faturamento R$ {_num_vc(_tot_lrc.get('faturamento', 0), 2)}"
                )


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
# As mesmas 10 seções de sempre, agora agrupadas por assunto em 5 abas-pai com
# st.tabs aninhado (mesma técnica de pages/7_Relatorios_Produtos_OTHIL.py) --
# 10 abas lado a lado no topo já não cabiam na tela sem rolagem horizontal.
# Nenhuma seção foi removida, renomeada ou teve conteúdo alterado: cada bloco
# `with ...:` abaixo é exatamente o que já existia, só reposicionado sob a aba
# de grupo correspondente.
grp_top_metas, grp_top_dashboards, grp_top_resultados, grp_top_operacao, grp_top_clientes = st.tabs([
    '🎯 Metas',
    '📊 Dashboards',
    '💰 Resultados',
    '📦 Operação',
    '👥 Clientes',
])

# ══ GRUPO: METAS ══════════════════════════════════════════════════════════════
with grp_top_metas:
    grp_metas, grp_metas_gerais = st.tabs([
        '🎯 Metas Semanais',
        '🌐 Metas Gerais',
    ])

    # ── METAS SEMANAIS ────────────────────────────────────────────────────────
    with grp_metas:
        tab_ot, tab_fech = st.tabs([
            '📊 On Track',
            '🏁 Fechamentos Semanais',
        ])
        with tab_ot:
            _render_ontrack_publicado()
        with tab_fech:
            _render_fechamentos_semanais()

    # ── METAS GERAIS ──────────────────────────────────────────────────────────
    with grp_metas_gerais:
        _render_metas_gerais()

# ══ GRUPO: DASHBOARDS ═════════════════════════════════════════════════════════
with grp_top_dashboards:
    grp_vendas, grp_margem_real = st.tabs([
        '📊 Dashboards',
        '💵 Margem Real',
    ])

    # ── VENDAS ────────────────────────────────────────────────────────────────
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

    # ── MARGEM REAL ───────────────────────────────────────────────────────────
    with grp_margem_real:
        st.caption(
            'Custo real = Custo do relatório ÷ (1 + % administrativo do produto) — retira do Custo '
            'a despesa administrativa que já vem embutida nele (variável por produto, cadastrada em '
            '**Cadastro de Marcas**). MC % real = MC R$ real ÷ Custo real × 100, sem o +15pp '
            'operacional usado nos outros indicadores. Sempre recalculada com o percentual mais atual '
            'do cadastro, mesmo para períodos antigos.'
        )
        tab_mr_d, tab_mr_s, tab_mr_m = st.tabs([
            '📅 Diário',
            '📆 Semanal',
            '🗓️ Mensal',
        ])
        with tab_mr_d:
            _render_secao_margem_real('diario', 'Margem Real — Diário', '📅')
        with tab_mr_s:
            _render_secao_margem_real('semanal', 'Margem Real — Semanal', '📆')
        with tab_mr_m:
            _render_secao_margem_real('mensal', 'Margem Real — Mensal', '🗓️')

# ══ GRUPO: RESULTADOS ═════════════════════════════════════════════════════════
with grp_top_resultados:
    grp_rentabilidade, grp_produtos, grp_recorrencia = st.tabs([
        '💰 Rentabilidade',
        '📦 Produtos',
        '🔄 Recorrência',
    ])

    # ── RENTABILIDADE ─────────────────────────────────────────────────────────
    with grp_rentabilidade:
        _render_rentabilidade_resumo()

    # ── PRODUTOS ──────────────────────────────────────────────────────────────
    with grp_produtos:
        _render_produtos_resumo()

    # ── RECORRÊNCIA ───────────────────────────────────────────────────────────
    with grp_recorrencia:
        _render_recorrencia_resumo()

# ══ GRUPO: OPERAÇÃO ═══════════════════════════════════════════════════════════
with grp_top_operacao:
    grp_quebras, grp_prevperdas = st.tabs([
        '📦 Quebras',
        '🚨 Prevenção de Perdas',
    ])

    # ── QUEBRAS ───────────────────────────────────────────────────────────────
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

    # ── PREVENÇÃO DE PERDAS ───────────────────────────────────────────────────
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

# ══ GRUPO: CLIENTES ═══════════════════════════════════════════════════════════
# Único grupo com uma seção só -- as 3 sub-abas de Clientes ficam direto sob a
# aba-pai, sem um nível intermediário que não separaria nada.
with grp_top_clientes:
    tab_cli_ot, tab_cli_top50, tab_cli_pv = st.tabs([
        '📊 On Track por Cliente', '🏆 Top 50 Clientes', '👤 Clientes por Vendedor',
    ])
    with tab_cli_ot:
        _render_ontrack_clientes()
    with tab_cli_top50:
        _render_top50_clientes_ger()
    with tab_cli_pv:
        _render_clientes_por_vendedor_ger()
    # Ranking de Recorrência mudou para a aba própria '🔄 Recorrência' (mais fácil de
    # achar, e junto ali agora tem os 5 tipos de período + histórico versionado).
