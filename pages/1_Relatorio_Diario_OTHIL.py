"""Página Streamlit — Relatório Diário, Semanal e Mensal OTHIL.

Três abas: Diário / Semanal / Mensal.
Todas usam o mesmo parse + gerar_dashboard — só muda o período do PDF.
"""
import datetime
import json
import os
import re
import tempfile

import streamlit as st
import streamlit.components.v1 as components
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from parsers_diario import parse_relatorio_diario, ValidationError
from xlsx_diario import gerar_xlsx
from dashboard_diario import gerar_dashboard
import acesso
import comparativo
import data_store as ds
import periodo as periodo_mod

try:
    from gsheets_upload import upload_xlsx_as_sheet
    _GSHEETS_OK = True
except Exception:
    _GSHEETS_OK = False

_GERENCIA_DIR = os.path.join(os.path.dirname(__file__), '..', 'gerencia_data')
MODULO = 'relatorio_diario'


# ── Formatação numérica em padrão brasileiro ────────────────────────────────
# Mesmo idioma já usado em pdfgen.py, pages/3_Vendedor_Cliente_OTHIL.py,
# pages/6_Rentabilidade_Margens_OTHIL.py, pages/7_Relatorios_Produtos_OTHIL.py
# e pages/gerencia.py -- só esta página ainda usava o formato padrão do
# Python (separador de milhar ',' e decimal '.', ex.: "R$ 12,345.67"), que
# fica invertido em relação ao padrão brasileiro usado no resto do app e no
# dashboard HTML embutido logo abaixo (que usa toLocaleString('pt-BR'),
# ex.: "R$ 12.345,67") -- o mesmo número aparecia em dois formatos
# diferentes na mesma tela.
def _fmt_num(v, casas=0):
    return f"{v:,.{casas}f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def _fmt_moeda(v):
    return f"R$ {_fmt_num(v, 2)}"


# ── Helpers de storage ───────────────────────────────────────────────────────

def _dir_tipo(tipo):
    d = os.path.join(_GERENCIA_DIR, tipo)
    os.makedirs(d, exist_ok=True)
    return d


def _salvar_dashboard(html_text, tipo, slug, periodo, emissao, resumo=None,
                       itens_fonte=None, usuario=None):
    try:
        d = _dir_tipo(tipo)
        with open(os.path.join(d, f'{slug}.html'), 'w', encoding='utf-8') as f:
            f.write(html_text)
        with open(os.path.join(d, f'{slug}.json'), 'w', encoding='utf-8') as f:
            json.dump({
                'slug': slug, 'tipo': tipo,
                'periodo': periodo, 'emissao': emissao,
                'gerado_em': datetime.datetime.now().isoformat(),
            }, f, ensure_ascii=False)
    except Exception:
        pass
    # Persistência real (data_store) — sobrevive a reinício do app. Guarda o
    # resumo (para histórico/comparativo) e os itens de origem (para
    # regenerar o dashboard visual mesmo que o cache local em disco tenha
    # sido perdido, ex.: após redeploy/hibernação no Streamlit Cloud).
    try:
        ds.save_record(
            modulo=MODULO, tipo_periodo=tipo, periodo_ref=slug,
            valores={
                'periodo': periodo, 'emissao': emissao,
                'resumo': resumo or {}, 'itens': itens_fonte or [],
            },
            usuario=usuario,
        )
    except Exception:
        pass


def _listar_dashboards(tipo):
    """Retorna lista de (slug, meta) ordenada do mais recente para o mais
    antigo. Mescla a persistência real (data_store) com o cache local em
    disco: quando o HTML local não existir mais (reinício do app), o
    dashboard é regenerado a partir dos itens salvos no data_store."""
    d = _dir_tipo(tipo)
    items = {}

    try:
        for slug in ds.list_periodos(MODULO, tipo):
            registro = ds.load_current(MODULO, tipo, slug)
            if not registro:
                continue
            valores = registro['valores']
            meta = {
                'slug': slug, 'tipo': tipo,
                'periodo': valores.get('periodo'), 'emissao': valores.get('emissao'),
                'gerado_em': registro.get('atualizado_em', ''),
                'resumo': valores.get('resumo', {}),
            }
            html_path = os.path.join(d, f'{slug}.html')
            if not os.path.exists(html_path) and valores.get('itens'):
                # Self-healing: regenera o HTML localmente a partir dos itens
                # persistidos, para que o dashboard volte a ficar disponível
                # sem precisar reenviar o PDF.
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


def _slug_diario(resultado):
    emissao = resultado.get('data_emissao') or ''
    try:
        d, m, a = emissao.split('/')
        return f'{a}-{m}-{d}'
    except Exception:
        return datetime.date.today().strftime('%Y-%m-%d')


def _slug_periodo(resultado, tipo):
    """Gera slug baseado no início do período: semana ISO ou mês."""
    periodo = resultado.get('periodo') or resultado.get('data_emissao') or ''
    m = re.search(r'(\d{2})/(\d{2})/(\d{4})', periodo)
    if m:
        day, mon, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        dt = datetime.date(year, mon, day)
        if tipo == 'semanal':
            iso = dt.isocalendar()
            return f'{iso[0]}-W{iso[1]:02d}'
        else:  # mensal
            return f'{year}-{mon:02d}'
    if tipo == 'semanal':
        return datetime.date.today().strftime('%Y-W%V')
    return datetime.date.today().strftime('%Y-%m')


def _label_slug(slug, tipo):
    """Transforma slug em label legível."""
    try:
        if tipo == 'semanal':
            year, week = slug.split('-W')
            return f'Semana {int(week):02d} / {year}'
        else:  # mensal
            year, mon = slug.split('-')
            meses = ['Jan','Fev','Mar','Abr','Mai','Jun',
                     'Jul','Ago','Set','Out','Nov','Dez']
            return f'{meses[int(mon)-1]} / {year}'
    except Exception:
        return slug


# ── Navegação de período por DATA (não por índice de registro salvo) ───────
#
# Correção da causa raiz do bug relatado: as setas ◀/▶ antigas incrementavam
# um índice dentro da lista de dashboards SALVOS (session_state[idx_key]),
# e por causa disso (a) só era possível navegar entre períodos que já
# tinham dado, e (b) o valor do índice entrava em conflito com o estado
# interno do st.selectbox (que tem sua própria key), fazendo a seleção
# "voltar" sozinha depois de um clique -- daí "as setas não funcionam".
#
# A correção: o período selecionado é uma referência de DATA
# (periodo_ref, ex.: '2026-W33'), calculada com periodo.py (mesmo padrão
# usado em Rentabilidade/Produtos) -- nunca um índice de lista. 'diario'
# não é um dos 5 tipos de período de periodo.py (representa 1 upload de
# 1 dia, não um período de relatório), por isso tem seu próprio cálculo
# local por aritmética de data, com a mesma interface.

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


def _obter_html_periodo(tipo, ref, valores):
    """HTML do dashboard salvo para (tipo, ref): usa o cache local se
    existir; se não existir mas houver itens salvos, regenera (self-
    healing, mesma lógica que já existia em _listar_dashboards). None se
    não houver itens (ex.: período importado manualmente, sem PDF)."""
    html_path = os.path.join(_dir_tipo(tipo), f'{ref}.html')
    if os.path.exists(html_path):
        with open(html_path, 'r', encoding='utf-8') as f:
            return f.read()
    if not valores.get('itens'):
        return None
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
        return html_regen
    except Exception:
        return None


def _exibir_metricas_resumo(resumo, tipo):
    if tipo == 'diario':
        r1, r2, r3, r4, r5, r6 = st.columns(6)
        cols_vals = [
            (r1, 'Faturamento', _fmt_moeda(resumo.get('faturamento', 0))),
            (r2, 'MC R$', _fmt_moeda(resumo.get('mc_rs', 0))),
            (r3, 'MC %', f"{resumo.get('mc_pct', 0):.2f}%".replace('.', ',')),
            (r4, 'Caixas', _fmt_num(resumo.get('caixas', 0), 3)),
            (r5, 'Clientes', resumo.get('clientes', '-')),
            (r6, 'Vendedores', resumo.get('vendedores', '-')),
        ]
    else:
        r1, r2, r3, r4, r5 = st.columns(5)
        cols_vals = [
            (r1, 'Faturamento', _fmt_moeda(resumo.get('faturamento', 0))),
            (r2, 'MC R$', _fmt_moeda(resumo.get('mc_rs', 0))),
            (r3, 'MC %', f"{resumo.get('mc_pct', 0):.2f}%".replace('.', ',')),
            (r4, 'Caixas', _fmt_num(resumo.get('caixas', 0), 3)),
            (r5, 'Clientes', resumo.get('clientes', '-')),
        ]
    for col, lab, val in cols_vals:
        col.metric(lab, val)


def _bloco_importar_historico(tipo, label_tipo, state_key, ref_sugerido=None, expanded=None):
    """Cadastro de dados de um período retroativo (item 4 do pedido) --
    mesma estrutura de dados dos registros normais (ds.save_record no
    módulo 'relatorio_diario'), identificado pelo período de referência
    informado, NÃO pela data de hoje. Duas formas: reenviar o PDF original
    daquele período (reaproveita 100% o parser existente, preserva os
    itens/detalhe) ou, se o PDF não existir mais, informar os totais
    manualmente (sem detalhe por item -- ver aviso na tela)."""
    aberto_por_sugestao = expanded if expanded is not None else (ref_sugerido is not None)
    # Todas as chaves de widget deste bloco são "escopadas" pelo período
    # sugerido (ctx). Isso é ESSENCIAL: sem isso, um st.date_input(key=...,
    # value=...) só aceita o `value=` na primeira vez que é criado -- em
    # reruns seguintes o valor persistido no session_state manda, mesmo que
    # `value=` mude (mesma classe de bug já corrigida na navegação por
    # setas). Como este bloco é renderizado tanto no caminho "sem dado"
    # (ref_sugerido = período navegado) quanto no caminho "com dado"
    # (ref_sugerido = None, formulário genérico no fim da página), usar uma
    # chave fixa fazia TODO import cair sempre no primeiro período em que o
    # formulário apareceu (tipicamente a semana atual), ignorando para qual
    # período o usuário havia navegado. Ao trocar de período, o contexto
    # muda e os widgets são recriados do zero, já com o valor correto.
    ctx = ref_sugerido or 'geral'
    with st.expander('➕ Importar dados históricos', expanded=aberto_por_sugestao):
        st.caption(
            'Cadastre dados de um período que aconteceu antes de o aplicativo passar a ser usado '
            '(ou que você não tenha mais o PDF). Fica salvo com a MESMA estrutura dos dados normais, '
            'identificado pelo período informado abaixo -- não pela data de hoje.'
        )

        if tipo == 'diario':
            data_escolhida = st.date_input(
                'Data do relatório', value=_diario_data(ref_sugerido) if ref_sugerido else datetime.date.today(),
                key=f'imp_data_{tipo}_{ctx}', format='DD/MM/YYYY')
            ref_calc = data_escolhida.strftime('%Y-%m-%d')
            ini_calc, fim_calc = data_escolhida, data_escolhida
        else:
            rotulo_tipo_lower = periodo_mod.rotulo_tipo(tipo).lower()
            valor_padrao = (periodo_mod.intervalo_datas(tipo, ref_sugerido)[0] if ref_sugerido
                             else datetime.date.today())
            data_escolhida = st.date_input(
                f'Uma data dentro d{"o" if tipo == "mensal" else "a"} {rotulo_tipo_lower} desejad'
                f'{"o" if tipo == "mensal" else "a"}',
                value=valor_padrao, key=f'imp_data_{tipo}_{ctx}', format='DD/MM/YYYY')
            ref_calc = periodo_mod.periodo_ref(tipo, data_escolhida)
            ini_calc, fim_calc = periodo_mod.intervalo_datas(tipo, ref_calc)

        aviso_regra = ' (regra segunda a domingo aplicada automaticamente)' if tipo == 'semanal' else ''
        st.info(f'Período identificado: **{ini_calc.strftime("%d/%m/%Y")} a {fim_calc.strftime("%d/%m/%Y")}** '
                f'— {_rotulo_periodo(tipo, ref_calc)}{aviso_regra}.')

        ja_existe = ds.has_data(MODULO, tipo, ref_calc)
        confirmar_dup = True
        if ja_existe:
            st.warning('Já existe um dado salvo para este período. Importar de novo cria uma NOVA VERSÃO '
                       'no histórico (a versão anterior fica preservada, nada é apagado ou perdido).')
            confirmar_dup = st.checkbox('Sim, quero substituir (criar nova versão) para este período',
                                         key=f'imp_conf_{tipo}_{ctx}')

        modo = st.radio('Como você quer informar os dados?',
                         ['Tenho o PDF original desse período',
                          'Não tenho o PDF — informar os números manualmente'],
                         key=f'imp_modo_{tipo}_{ctx}')

        if modo.startswith('Tenho'):
            if ja_existe and not confirmar_dup:
                st.caption('Marque a confirmação acima para habilitar o envio.')
            pdf_hist = st.file_uploader(f'PDF {label_tipo} do período histórico', type='pdf',
                                         key=f'imp_pdf_{tipo}_{ctx}', disabled=(ja_existe and not confirmar_dup))
            if pdf_hist is not None:
                try:
                    resultado_h = parse_relatorio_diario(pdf_hist)
                except Exception as e:
                    st.error(f'Não foi possível ler o PDF: {e}')
                    resultado_h = None
                if resultado_h is not None and not resultado_h.get('itens'):
                    st.error('Nenhum item foi encontrado neste PDF -- confira se é o relatório '
                             '"Lucratividade por Vendedor-Cliente no Previsão" correto para este período.')
                elif resultado_h is not None:
                    itens_h = resultado_h['itens']
                    fat_h = sum(it['faturamento'] for it in itens_h)
                    custo_h = sum(it['custo_total'] for it in itens_h)
                    caixas_h = sum(it['qtd'] for it in itens_h)
                    clientes_h = len(set(it['cliente_codigo'] for it in itens_h))
                    mc_rs_h = fat_h - custo_h
                    mc_pct_h = mc_rs_h / custo_h * 100 if custo_h else 0.0
                    st.caption(f"PDF lido: Faturamento {_fmt_moeda(fat_h)} · MC {_fmt_moeda(mc_rs_h)} · "
                               f"Caixas {_fmt_num(caixas_h, 3)} · Clientes {clientes_h}")
                    if st.button('💾 Salvar este período histórico', key=f'imp_salvar_pdf_{tipo}_{ctx}',
                                  type='primary', disabled=(ja_existe and not confirmar_dup)):
                        resumo_h = {'faturamento': round(fat_h, 2), 'mc_rs': round(mc_rs_h, 2),
                                    'mc_pct': round(mc_pct_h, 2), 'caixas': round(caixas_h, 3),
                                    'clientes': clientes_h}
                        if tipo == 'diario':
                            resumo_h['vendedores'] = len({(it.get('vendedor') or it.get('vendedor_raw'))
                                                           for it in itens_h})
                        periodo_txt = (ini_calc.strftime('%d/%m/%Y') if tipo == 'diario'
                                       else f'{ini_calc:%d/%m/%Y} a {fim_calc:%d/%m/%Y}')
                        ds.save_record(
                            modulo=MODULO, tipo_periodo=tipo, periodo_ref=ref_calc,
                            valores={'periodo': periodo_txt,
                                     'emissao': resultado_h.get('data_emissao') or periodo_txt,
                                     'resumo': resumo_h, 'itens': itens_h,
                                     'origem': 'importacao_historica_pdf'},
                            usuario=st.session_state.get('usuario_nome', 'Ingrid'),
                            data_referencia=ini_calc.isoformat())
                        st.session_state[state_key] = ref_calc
                        st.session_state[f'_flash_{tipo}'] = (
                            f'Período {_rotulo_periodo(tipo, ref_calc)} importado com sucesso.')
                        st.rerun()
        else:
            st.caption('⚠️ Sem o PDF, só é possível informar os totais -- não haverá detalhamento por '
                       'produto/cliente/vendedor para este período em Rentabilidade/Relatórios de Produtos '
                       '(que dependem do item a item), mas o Dashboard, o histórico, os comparativos e os '
                       'Períodos Salvos passam a considerar este período normalmente.')
            with st.form(key=f'imp_form_manual_{tipo}_{ctx}'):
                mf1, mf2 = st.columns(2)
                faturamento_m = mf1.number_input('Faturamento (R$)', min_value=0.0, step=100.0,
                                                  key=f'imp_fat_{tipo}_{ctx}')
                custo_m = mf2.number_input('Custo Total (R$)', min_value=0.0, step=100.0,
                                            key=f'imp_custo_{tipo}_{ctx}')
                mf3, mf4 = st.columns(2)
                caixas_m = mf3.number_input('Caixas', min_value=0.0, step=1.0, key=f'imp_cx_{tipo}_{ctx}')
                clientes_m = mf4.number_input('Clientes', min_value=0, step=1, key=f'imp_cli_{tipo}_{ctx}')
                vendedores_m = 0
                if tipo == 'diario':
                    vendedores_m = st.number_input('Vendedores Ativos', min_value=0, step=1,
                                                     key=f'imp_vend_{tipo}_{ctx}')
                enviado = st.form_submit_button('💾 Salvar este período histórico', type='primary',
                                                 disabled=(ja_existe and not confirmar_dup))
            if enviado:
                if faturamento_m <= 0 and custo_m <= 0 and caixas_m <= 0 and clientes_m <= 0:
                    st.error('Informe ao menos um valor maior que zero antes de salvar.')
                else:
                    mc_rs_m = faturamento_m - custo_m
                    mc_pct_m = mc_rs_m / custo_m * 100 if custo_m else 0.0
                    resumo_m = {'faturamento': round(faturamento_m, 2), 'mc_rs': round(mc_rs_m, 2),
                                'mc_pct': round(mc_pct_m, 2), 'caixas': round(caixas_m, 3),
                                'clientes': int(clientes_m)}
                    if tipo == 'diario':
                        resumo_m['vendedores'] = int(vendedores_m or 0)
                    periodo_txt = (ini_calc.strftime('%d/%m/%Y') if tipo == 'diario'
                                   else f'{ini_calc:%d/%m/%Y} a {fim_calc:%d/%m/%Y}')
                    ds.save_record(
                        modulo=MODULO, tipo_periodo=tipo, periodo_ref=ref_calc,
                        valores={'periodo': periodo_txt, 'emissao': periodo_txt,
                                 'resumo': resumo_m, 'itens': [],
                                 'origem': 'importacao_historica_manual'},
                        usuario=st.session_state.get('usuario_nome', 'Ingrid'),
                        data_referencia=ini_calc.isoformat())
                    st.session_state[state_key] = ref_calc
                    st.session_state[f'_flash_{tipo}'] = (
                        f'Período {_rotulo_periodo(tipo, ref_calc)} importado com sucesso '
                        f'(dados agregados, sem detalhamento por item).')
                    st.rerun()


def _exibir_comparativo(tipo, ref_sel, resumo):
    """Comparativo vs período anterior (por DATA, não pelo registro salvo
    mais próximo). Fatorado para ser reutilizável tanto no Histórico quanto
    logo após uma geração nova (mesma lógica, sem duplicar código)."""
    ref_ant = _periodo_anterior(tipo, ref_sel)
    reg_ant = ds.load_current(MODULO, tipo, ref_ant)
    if not reg_ant:
        st.caption(f'Sem dados para comparação no período anterior ({_rotulo_periodo(tipo, ref_ant)}).')
        return
    resumo_ant = reg_ant.get('valores', {}).get('resumo') or {}
    campos_cmp = [('Faturamento', 'faturamento', _fmt_moeda),
                  ('MC R$', 'mc_rs', _fmt_moeda),
                  ('MC %', 'mc_pct', lambda x: f'{x:.2f}%'.replace('.', ',')),
                  ('Caixas', 'caixas', lambda x: _fmt_num(x, 3)),
                  ('Clientes', 'clientes', lambda x: _fmt_num(x, 0))]
    # MC % e Vendedores ficavam de fora deste comparativo, mesmo sendo
    # mostrados nos cartões acima (_exibir_metricas_resumo) -- MC % é a
    # métrica mais citada do negócio (margem de contribuição) e não
    # tinha variação % nenhuma aqui. Vendedores só existe no resumo do
    # Diário (não no Semanal/Mensal), por isso só entra quando presente.
    if 'vendedores' in resumo and 'vendedores' in resumo_ant:
        campos_cmp.append(('Vendedores', 'vendedores', lambda x: _fmt_num(x, 0)))
    cols_cmp = st.columns(len(campos_cmp))
    for col, (lab, chave, fmt) in zip(cols_cmp, campos_cmp):
        comp = comparativo.calcular(resumo.get(chave, 0), resumo_ant.get(chave))
        col.metric(lab, fmt(resumo.get(chave, 0)), delta=comparativo.formatar_variacao(comp))
    st.caption(f'Base de comparação: {_rotulo_periodo(tipo, ref_ant)}.')


def _navegar_e_exibir_historico(tipo, label_tipo):
    """Navegação ◀ seletor ▶ por DATA (uma única linha, seletor já cobre a
    seleção rápida entre períodos salvos) + comparativo vs período anterior
    (calculado por data, não pelo registro salvo mais próximo) +
    importação de dados históricos, sempre no mesmo lugar (expandida
    quando o período não tem dado, recolhida quando já tem)."""
    state_key = f'_periodo_sel_{tipo}'
    if state_key not in st.session_state:
        st.session_state[state_key] = _periodo_atual_ref(tipo)

    flash_key = f'_flash_{tipo}'
    if flash_key in st.session_state:
        st.success(st.session_state.pop(flash_key))

    def _ir_anterior():
        st.session_state[state_key] = _periodo_anterior(tipo, st.session_state[state_key])

    def _ir_posterior():
        st.session_state[state_key] = _periodo_posterior(tipo, st.session_state[state_key])

    ref_sel = st.session_state[state_key]
    dashboards_meta = dict(_listar_dashboards(tipo))
    # Opções do seletor: todos os períodos com dado salvo + o período
    # atualmente navegado (mesmo sem dado), pra ele sempre aparecer
    # selecionado -- sem index de lista, sem perder a navegação por
    # QUALQUER período (com ou sem dado) que as setas ◀ ▶ já garantiam.
    opcoes_periodo = sorted(set(dashboards_meta.keys()) | {ref_sel}, reverse=True)

    # Uma única linha ◀ | seletor | ▶ (mesmo padrão visual de
    # pages/4_Quebra_OTHIL.py), substituindo a antiga linha de setas +
    # expander separado de "seleção rápida" mais abaixo -- a lógica de
    # navegação por DATA (funções acima) continua exatamente a mesma, só
    # muda o layout.
    col_prev, col_sel, col_next = st.columns([1, 5, 1])
    with col_prev:
        st.button('◀', key=f'nav_prev_{tipo}', help='Período anterior', on_click=_ir_anterior,
                   use_container_width=True)
    with col_next:
        st.button('▶', key=f'nav_next_{tipo}', help='Próximo período', on_click=_ir_posterior,
                   use_container_width=True)
    with col_sel:
        # Chave escopada por ref_sel (mesma técnica já usada em
        # _bloco_importar_historico): garante que `index=` seja reaplicado
        # sempre que o período mudar (por clique nas setas, por exemplo),
        # em vez de ficar preso ao valor anterior do widget.
        escolha = st.selectbox(
            'Período', opcoes_periodo,
            format_func=lambda r: _rotulo_periodo(tipo, r) + ('' if r in dashboards_meta else ' (sem dado)'),
            index=opcoes_periodo.index(ref_sel),
            key=f'nav_sel_{tipo}_{ref_sel}',
        )
    if escolha != ref_sel:
        st.session_state[state_key] = escolha
        st.rerun()

    ini, fim = _intervalo_periodo(tipo, ref_sel)
    tem_dado = ds.has_data(MODULO, tipo, ref_sel)

    # Rótulo do período em destaque (badge), em vez de texto em markdown
    # simples -- fica mais visível qual período está sendo exibido.
    if tipo == 'diario':
        rotulo_atual = _rotulo_periodo(tipo, ref_sel)
    else:
        rotulo_atual = (f'{ini.strftime("%d/%m/%Y")} – {fim.strftime("%d/%m/%Y")}  ·  '
                        f'{_rotulo_periodo(tipo, ref_sel)}')
    if tem_dado:
        st.info(f'🟢 **{rotulo_atual}** — período salvo ✓')
    else:
        st.info(f'⚪ **{rotulo_atual}** — nenhum dado cadastrado para este período.')

    st.divider()

    # Ponto único de entrada do "Importar dados históricos" (antes existia
    # duas vezes: uma auto-expandida quando não havia dado, outra recolhida
    # mais abaixo depois de todo o detalhe do período já com dado) --
    # mesmo lugar sempre, só o estado expandido/recolhido muda.
    _bloco_importar_historico(tipo, label_tipo, state_key, ref_sugerido=ref_sel, expanded=not tem_dado)

    if not tem_dado:
        return

    st.divider()

    registro = ds.load_current(MODULO, tipo, ref_sel)
    valores = registro.get('valores', {}) or {}
    resumo = valores.get('resumo') or {}
    gerado = (registro.get('atualizado_em') or '')[:16].replace('T', ' ')
    origem = valores.get('origem')
    st.caption(f'Período: {valores.get("periodo", "-")}  |  Salvo em: {gerado}' +
               (' · importado manualmente (sem PDF)' if origem == 'importacao_historica_manual' else ''))

    _hist_versoes = ds.load_history(MODULO, tipo, ref_sel)
    if _hist_versoes:
        # data_store guarda TODAS as versões salvas para este período (ex.:
        # o mesmo dia foi reenviado/corrigido mais de uma vez) -- antes isso
        # ficava só no JSON do repositório, sem nenhum jeito de ver pela
        # tela; aqui mostra ao menos quando cada versão anterior foi salva e
        # por quem, para não ficar "invisível".
        with st.expander(f'🕘 Versões anteriores deste período ({len(_hist_versoes)})'):
            for _v in reversed(_hist_versoes):
                _vres = (_v.get('valores', {}) or {}).get('resumo') or {}
                _vquando = (_v.get('atualizado_em') or '')[:16].replace('T', ' ')
                st.caption(
                    f"Versão {_v.get('versao')} — salvo em {_vquando} por "
                    f"{_v.get('usuario', 'não identificado')} — "
                    f"Faturamento: {_fmt_moeda(_vres.get('faturamento', 0))}  |  "
                    f"Caixas: {_fmt_num(_vres.get('caixas', 0), 3)}"
                )

    _exibir_metricas_resumo(resumo, tipo)

    st.subheader('📊 Comparativo vs período anterior')
    _exibir_comparativo(tipo, ref_sel, resumo)

    html_periodo = _obter_html_periodo(tipo, ref_sel, valores)
    if html_periodo:
        components.html(html_periodo, height=1400, scrolling=True)
        st.download_button(
            f'⬇️ Baixar {_rotulo_periodo(tipo, ref_sel)}',
            data=html_periodo.encode('utf-8'),
            file_name=f'dashboard_{tipo}_{ref_sel}_OTHIL.html',
            mime='text/html', key=f'dl_hist_{tipo}',
        )
    else:
        st.info('Visual do dashboard não disponível para reexibir agora -- os números acima ficaram salvos. '
                'Reenvie o PDF desse período (via "Importar dados históricos" acima) para gerar o visual.')


# ── Bloco reutilizável: upload + gerar + histórico ────────────────────────────

def _render_tab(tipo, label_tipo):
    """Renderiza uma aba de dashboard (semanal ou mensal)."""
    key = tipo  # prefixo para session_state e widget keys

    st.header(f'1. Upload do PDF {label_tipo}')
    st.caption(
        f'Envie o PDF "Lucratividade por Vendedor-Cliente no Previsão" '
        f'cobrindo o período {label_tipo.lower()} desejado.'
    )
    pdf_file = st.file_uploader(
        f'PDF {label_tipo} (Mercatus)',
        type='pdf', key=f'pdf_{key}',
    )

    if pdf_file is not None:
        with st.spinner(f'Lendo PDF {label_tipo.lower()}...'):
            try:
                resultado = parse_relatorio_diario(pdf_file)
                if not resultado.get('itens'):
                    st.error(
                        'Nenhum item foi encontrado neste PDF — o dashboard não foi gerado. '
                        'Confira se o arquivo enviado é o relatório '
                        '**"Lucratividade por Vendedor-Cliente no Previsão"** (ele precisa ter '
                        'as linhas "Cliente:" para cada cliente). Outros relatórios parecidos, '
                        'como "Vendedor-Faturamento no Previsão" ou "Vendedor no Previsão", têm '
                        'layout diferente e não são reconhecidos aqui.'
                    )
                else:
                    st.session_state[f'resultado_{key}'] = resultado
            except Exception as e:
                st.error(f'Não foi possível ler o PDF: {e}')

    if f'resultado_{key}' in st.session_state:
        resultado = st.session_state[f'resultado_{key}']
        itens = resultado['itens']

        if resultado.get('divergencias'):
            st.warning(
                f"⚠️ {len(resultado['divergencias'])} divergência(s) detectadas. "
                "O dashboard é gerado mesmo assim."
            )
            with st.expander('Ver divergências'):
                st.dataframe(resultado['divergencias'], use_container_width=True, hide_index=True)
        else:
            st.success('PDF lido com sucesso.')

        periodo  = resultado.get('periodo') or '-'
        emissao  = resultado.get('data_emissao') or '-'
        fat_total  = sum(it['faturamento'] for it in itens)
        custo_tot  = sum(it['custo_total']  for it in itens)
        caixas_tot = sum(it['qtd']          for it in itens)
        clientes   = len(set(it['cliente_codigo'] for it in itens))
        mc_rs      = fat_total - custo_tot
        mc_pct     = mc_rs / custo_tot * 100 if custo_tot else 0.0

        st.header('2. Resumo do período')
        st.caption(f'Período: {periodo}  |  Emissão: {emissao}')
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric('Faturamento', _fmt_moeda(fat_total))
        c2.metric('MC R$',       _fmt_moeda(mc_rs))
        c3.metric('MC %',        f'{mc_pct:.2f}%'.replace('.', ','))
        c4.metric('Caixas',      _fmt_num(caixas_tot, 3))
        c5.metric('Clientes',    clientes)

        st.header(f'3. Gerar Dashboard {label_tipo}')
        if st.button(f'📈 Gerar Dashboard {label_tipo}', type='primary', key=f'btn_dash_{key}'):
            with st.spinner('Gerando dashboard...'):
                with tempfile.NamedTemporaryFile(suffix='.html', delete=False,
                                                 mode='w', encoding='utf-8') as tmp:
                    pass
                gerar_dashboard(resultado, tmp.name, tipo=tipo)
                html_text = open(tmp.name, 'r', encoding='utf-8').read()
            slug = _slug_periodo(resultado, tipo)
            resumo_tab = {
                'faturamento': round(fat_total, 2), 'mc_rs': round(mc_rs, 2),
                'mc_pct': round(mc_pct, 2), 'caixas': round(caixas_tot, 3),
                'clientes': clientes,
            }
            _salvar_dashboard(html_text, tipo, slug, periodo, emissao,
                               resumo=resumo_tab, itens_fonte=itens,
                               usuario=st.session_state.get('usuario_nome'))
            st.session_state[f'html_{key}']   = html_text
            st.session_state[f'slug_{key}']   = slug
            st.success(f'Dashboard salvo — {_label_slug(slug, tipo)}')
            st.caption('📊 vs período anterior')
            _exibir_comparativo(tipo, slug, resumo_tab)
            # Perfil de upload (26/08/2026, pedido da Ingrid): fluxo
            # Login -> Upload -> Gerência, nunca fica numa tela de Dashboard.
            acesso.redirecionar_pos_upload()

        # BUG REAL corrigido 03/09/2026, pedido da Ingrid: "quando gera o
        # relatório diário não é para aparecer o dashboard na geração,
        # somente na gerência". O acesso.redirecionar_pos_upload() logo
        # acima já interrompe (st.stop()) o rerun EM QUE o botão foi
        # clicado -- por isso, no instante da geração, ela só via a
        # mensagem de sucesso. Mas html_{key}/slug_{key} ficam salvos no
        # session_state, e este bloco (download + preview) não tinha
        # NENHUMA verificação de política -- só checava se esses valores
        # existiam na sessão. Resultado: em qualquer rerun seguinte desta
        # MESMA página (ex.: voltar do link "Ir para a Gerência", trocar
        # de página e voltar, ou qualquer outra interação que faça o
        # script rodar de novo com o PDF ainda "preso" no uploader), o
        # dashboard reaparecia aqui, sem o st.stop() pra impedir. Mesma
        # verificação já usada pra esconder a seção "4. Histórico" logo
        # abaixo (deve_esconder_apos_upload()) resolve, porque ela não
        # depende de o script ter parado no meio -- é reavaliada em TODO
        # rerun.
        if f'html_{key}' in st.session_state and not acesso.deve_esconder_apos_upload():
            slug = st.session_state[f'slug_{key}']
            st.download_button(
                f'⬇️ Baixar dashboard {_label_slug(slug, tipo)}',
                data=st.session_state[f'html_{key}'].encode('utf-8'),
                file_name=f'dashboard_{tipo}_{slug}_OTHIL.html',
                mime='text/html',
                key=f'dl_{key}',
            )
            with st.expander('Pré-visualizar dashboard', expanded=True):
                components.html(st.session_state[f'html_{key}'], height=1400, scrolling=True)

    # Perfil de upload (26/08/2026, pedido da Ingrid): nunca vê o
    # download/preview do dashboard nem o histórico abaixo -- SEMPRE
    # bloqueado aqui, independente de já ter lido um PDF ou não nesta
    # sessão (por isso fica fora do "if resultado_{key}..." acima, e não
    # só dentro dele).
    #
    # Usa deve_esconder_apos_upload() em vez de parar_se_upload() aqui --
    # bug real encontrado em 29/08/2026: esta função é chamada de dentro
    # de _render_tab(), compartilhada pelas abas Semanal e Mensal desta
    # MESMA página (que tem 3 abas: Diário/Semanal/Mensal). parar_se_upload()
    # usa st.stop(), que mata o script INTEIRO -- ao rodar a aba Semanal
    # (que vem antes da Mensal no código), o st.stop() impedia a aba Mensal
    # de sequer aparecer (nem o uploader dela). Sintoma reportado pela
    # Ingrid: "no dashboard semanal e mensal, não está com a opção de
    # colocar upload do PDF" -- as abas ficavam totalmente em branco.
    if not acesso.deve_esconder_apos_upload():
        st.divider()
        st.header(f'4. Histórico {label_tipo}')
        _navegar_e_exibir_historico(tipo, label_tipo)


# ── Página principal ─────────────────────────────────────────────────────────

st.title('OTHIL — Dashboard de Vendas')

st.session_state.setdefault('usuario_nome', 'Ingrid')

tab_d, tab_s, tab_m = st.tabs(['📅 Diário', '📆 Semanal', '🗓️ Mensal'])

# ── ABA DIÁRIO ───────────────────────────────────────────────────────────────
with tab_d:
    st.header('1. Upload do PDF do dia')
    pdf_file = st.file_uploader(
        'Lucratividade por Vendedor-Cliente no Previsão (PDF, Mercatus) — obrigatório',
        type='pdf', key='pdf_diario',
    )

    if pdf_file is not None:
        with st.spinner('Lendo e validando o PDF...'):
            try:
                resultado = parse_relatorio_diario(pdf_file)
                if not resultado.get('itens'):
                    st.error(
                        'Nenhum item foi encontrado neste PDF — o dashboard não foi gerado. '
                        'Confira se o arquivo enviado é o relatório '
                        '**"Lucratividade por Vendedor-Cliente no Previsão"** (ele precisa ter '
                        'as linhas "Cliente:" para cada cliente). Outros relatórios parecidos, '
                        'como "Vendedor-Faturamento no Previsão" ou "Vendedor no Previsão", têm '
                        'layout diferente e não são reconhecidos aqui.'
                    )
                    resultado = None
            except Exception as e:
                st.error(f'Não foi possível ler o PDF enviado: {e}')
                resultado = None
        if resultado is not None:
            st.session_state['resultado_diario'] = resultado

    if 'resultado_diario' in st.session_state:
        resultado = st.session_state['resultado_diario']
        itens = resultado['itens']

        if resultado['divergencias']:
            st.warning(
                f"⚠️ {len(resultado['divergencias'])} divergência(s) entre os itens extraídos e os "
                "Totais do Vendedor/Cliente oficiais do PDF (tolerância R$ 1). Confira antes de "
                "usar os arquivos gerados — o relatório ainda é gerado, mas pode estar incompleto."
            )
            with st.expander('Ver divergências'):
                st.dataframe(resultado['divergencias'], use_container_width=True, hide_index=True)
        else:
            st.success('PDF lido com sucesso — todos os totais bateram exatamente com o PDF.')

        st.header('2. Resumo do dia')
        faturamento = sum(it['faturamento'] for it in itens)
        custo = sum(it['custo_total'] for it in itens)
        caixas = sum(it['qtd'] for it in itens)
        clientes = len(set(it['cliente_codigo'] for it in itens))
        vendedores = len(set((it['vendedor'] or it['vendedor_raw']) for it in itens))
        mc_rs  = faturamento - custo
        mc_pct = mc_rs / custo * 100 if custo else 0.0

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric('Faturamento', _fmt_moeda(faturamento))
        c2.metric('MC R$', _fmt_moeda(mc_rs))
        c3.metric('MC %', f'{mc_pct:.2f}%'.replace('.', ','))
        c4.metric('Caixas', _fmt_num(caixas, 3))
        c5.metric('Clientes', clientes)
        c6.metric('Vendedores Ativos', vendedores)

        st.caption(f"Dia: {resultado.get('data_emissao') or '-'} · Período: {resultado.get('periodo') or '-'} · "
                   f"{len(itens)} itens extraídos.")

        st.header('3. Gerar arquivos')
        data_ref = resultado.get('data_emissao')
        if data_ref:
            data_fmt_xlsx = data_ref.replace('/', '-')
            data_fmt_html = data_ref.replace('/', '')
        else:
            hoje = datetime.date.today()
            data_fmt_xlsx = hoje.strftime('%d-%m-%Y')
            data_fmt_html = hoje.strftime('%d%m%Y')

        col_xlsx, col_html = st.columns(2)

        with col_xlsx:
            if st.button('📊 Gerar Planilha', type='primary', key='btn_xlsx'):
                with st.spinner('Gerando planilha...'):
                    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
                        gerar_xlsx(resultado, tmp.name)
                        tmp.seek(0)
                        xlsx_bytes = open(tmp.name, 'rb').read()
                st.session_state['xlsx_bytes'] = xlsx_bytes
                st.session_state['xlsx_nome'] = f'Relatorio_Diario_{data_fmt_xlsx}_OTHIL.xlsx'
            if 'xlsx_bytes' in st.session_state:
                nome = st.session_state['xlsx_nome']
                st.download_button(
                    '⬇️ Baixar Excel — ' + nome,
                    data=st.session_state['xlsx_bytes'],
                    file_name=nome,
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                )

        with col_html:
            if st.button('📈 Gerar Dashboard HTML', type='primary', key='btn_html'):
                with st.spinner('Gerando dashboard...'):
                    with tempfile.NamedTemporaryFile(suffix='.html', delete=False,
                                                     mode='w', encoding='utf-8') as tmp:
                        pass
                    gerar_dashboard(resultado, tmp.name, tipo='diario')
                    html_text = open(tmp.name, 'r', encoding='utf-8').read()
                slug_d = _slug_diario(resultado)
                resumo_d = {
                    'faturamento': round(faturamento, 2), 'mc_rs': round(mc_rs, 2),
                    'mc_pct': round(mc_pct, 2), 'caixas': round(caixas, 3),
                    'clientes': clientes, 'vendedores': vendedores,
                }
                _salvar_dashboard(
                    html_text, 'diario', slug_d,
                    resultado.get('periodo') or '-',
                    resultado.get('data_emissao') or '-',
                    resumo=resumo_d, itens_fonte=itens,
                    usuario=st.session_state.get('usuario_nome'),
                )
                st.session_state['html_text'] = html_text
                st.session_state['html_nome'] = f'dashboard_gerencial_othil_{data_fmt_html}.html'
                st.success(f'Dashboard salvo — {_rotulo_periodo("diario", slug_d)}')
                st.caption('📊 vs período anterior')
                _exibir_comparativo('diario', slug_d, resumo_d)
                # Perfil de upload (26/08/2026, pedido da Ingrid): fluxo
                # Login -> Upload -> Gerência, nunca fica numa tela de Dashboard.
                acesso.redirecionar_pos_upload()
            # BUG REAL corrigido 03/09/2026, pedido da Ingrid: "quando gera
            # o relatório diário não é para aparecer o dashboard na
            # geração, somente na gerência" -- mesma causa e mesma correção
            # do bloco equivalente em _render_tab() (Semanal/Mensal, ver
            # comentário lá): html_text fica salvo no session_state e este
            # bloco não tinha nenhuma verificação de política, só olhava
            # se o valor existia na sessão -- em qualquer rerun desta
            # página DEPOIS do st.stop() do redirecionamento (ex.: voltar
            # pra cá vindo da Gerência), o dashboard reaparecia sem nada
            # pra impedir.
            if 'html_text' in st.session_state and not acesso.deve_esconder_apos_upload():
                st.download_button(
                    '⬇️ Baixar ' + st.session_state['html_nome'],
                    data=st.session_state['html_text'].encode('utf-8'),
                    file_name=st.session_state['html_nome'],
                    mime='text/html',
                )

        if 'html_text' in st.session_state and not acesso.deve_esconder_apos_upload():
            with st.expander('Pré-visualizar dashboard', expanded=True):
                components.html(st.session_state['html_text'], height=1400, scrolling=True)

    else:
        st.info('Envie o PDF do dia para começar.')

    # Perfil de upload (26/08/2026, pedido da Ingrid): nunca vê o preview do
    # dashboard nem o histórico abaixo -- SEMPRE bloqueado aqui, independente
    # de já ter lido um PDF ou não nesta sessão.
    #
    # Usa deve_esconder_apos_upload() em vez de parar_se_upload() aqui pelo
    # MESMO motivo do comentário equivalente em _render_tab() abaixo: esta
    # é a aba Diário, a PRIMEIRA das 3 abas desta página -- um st.stop()
    # aqui matava o script antes mesmo de chegar nas abas Semanal e Mensal,
    # deixando as duas completamente em branco (bug real reportado pela
    # Ingrid em 29/08/2026).
    if not acesso.deve_esconder_apos_upload():
        # Histórico diário -- sempre visível (não depende de ter subido um
        # PDF nesta sessão), com a mesma navegação por data usada em
        # Semanal/Mensal.
        st.divider()
        st.header('4. Histórico Diário')
        _navegar_e_exibir_historico('diario', 'Diário')

# ── ABA SEMANAL ──────────────────────────────────────────────────────────────
with tab_s:
    _render_tab('semanal', 'Semanal')

# ── ABA MENSAL ───────────────────────────────────────────────────────────────
with tab_m:
    _render_tab('mensal', 'Mensal')
