"""Pagina Streamlit - Relatorio Vendedor-Cliente OTHIL.

Workflow:
  (1) Inicio do mes (uma vez):
      Secao 'Configurar Historico':
      - OPCAO A: Sobe o xlsx do mes anterior (mesmo formato gerado aqui)
        -> le clientes, historico e metas automaticamente
      - OPCAO B: Sobe dois PDFs Lucratividade por Vendedor-Cliente
        (ant_ano e ant_mes)
      - Clica 'Salvar Historico' -> baixa historico_JUL2026.json

  (2) Toda sexta-feira:
      Secao 'Gerar Relatorio Semanal':
      - Sobe historico_JUL2026.json (salvo acima)
      - Sobe PDFs Vendedor-Cliente atual (1 por vendedor, ate 8 arquivos)
      - Sobe PDF Lucratividade por Vendedor (totais reais)
      - Clica 'Gerar Excel' -> baixa o .xlsx
"""
import io
import json
import os
import calendar as _cal
from datetime import datetime

import streamlit as st
import pandas as pd

_ONTRACK_CLI_FILE = os.path.join(
    os.path.dirname(__file__), '..', 'gerencia_data', 'ontrack_clientes_publicado.json'
)
_ONTRACK_CLI_DIR = os.path.join(
    os.path.dirname(__file__), '..', 'gerencia_data', 'ontrack_clientes'
)

from xlsx_vendedor_cliente import (
    salvar_historico, carregar_historico, gerar_xlsx, ler_xlsx_historico,
    parse_e_agregar, agregar_produtos_por_cliente, VENDOR_TAB, _normalize,
)
from parsers_vendedor import parse_totais_vendedor
import acesso
import periodo
import comparativo
import on_track
import data_store as ds
import metas_gerais as mg
import metas_clientes as mc_cli
import calc

MODULO = 'vendedor_cliente'
MODULO_ONTRACK = 'vendedor_cliente_ontrack'
MODULO_HIST = 'vendedor_cliente_historico'

st.title('Relatorio Vendedor-Cliente')

st.session_state.setdefault('usuario_nome', 'Ingrid')

MESES = ['Janeiro','Fevereiro','Marco','Abril','Maio','Junho',
         'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']
MESES_ABR = ['jan','fev','mar','abr','mai','jun',
              'jul','ago','set','out','nov','dez']

# --- Seletor de mes / ano ---
with st.expander('Periodo de Referencia', expanded=True):
    c1, c2 = st.columns(2)
    with c1:
        mes = st.selectbox('Mes', range(1, 13),
                           index=datetime.today().month - 1,
                           format_func=lambda m: MESES[m - 1])
    with c2:
        ano = st.number_input('Ano', min_value=2020, max_value=2035,
                              value=datetime.today().year)

ref_date   = datetime(int(ano), int(mes), 1)
m_ant      = mes - 1 if mes > 1 else 12
y_ant      = ano if mes > 1 else ano - 1
lbl_atual  = f"{MESES_ABR[mes-1].upper()}/{ano}"
lbl_ant_m  = f"{MESES_ABR[m_ant-1]}./{y_ant}"
lbl_ant_a  = f"{MESES_ABR[mes-1]}./{ano-1}"
fname_json = f"historico_{lbl_atual.replace('/','')}.json"
PERIODO_REF = periodo.periodo_ref('mensal', ref_date.date())

# ── Persistência real: se os dados deste mês já foram gerados antes (nesta
# sessão ou em qualquer sessão anterior, mesmo depois de um restart do app),
# recupera automaticamente — sem precisar reprocessar os PDFs de novo só
# porque a página foi recarregada.
if st.session_state.get('_vc_periodo_carregado') != PERIODO_REF:
    _registro_vc = ds.load_current(MODULO, 'mensal', PERIODO_REF)
    if _registro_vc:
        st.session_state['clientes_on_track'] = _registro_vc['valores'].get('clientes_data')
        st.session_state['totais_on_track']   = _registro_vc['valores'].get('totais_dict')
        st.session_state['historico_vc']      = _registro_vc['valores'].get('historico')
        st.session_state['produtos_por_cliente_vc'] = _registro_vc['valores'].get('produtos_por_cliente')
        st.session_state['ref_date_vc']       = ref_date
    st.session_state['_vc_periodo_carregado'] = PERIODO_REF

# ── Histórico (Seção 1) também recuperado automaticamente após restart —
# mesma lógica: se já foi gerado e salvo antes para este mês (em qualquer
# sessão), fica disponível sem precisar reenviar o xlsx/PDFs de novo.
if st.session_state.get('_vc_hist_periodo_carregado') != PERIODO_REF:
    _registro_hist = ds.load_current(MODULO_HIST, 'mensal', PERIODO_REF)
    st.session_state['historico_vc_salvo'] = (
        _registro_hist['valores'].get('historico') if _registro_hist else None
    )
    st.session_state['_vc_hist_periodo_carregado'] = PERIODO_REF

st.divider()

# ── Helpers de formatação ─────────────────────────────────────────────────────

def _brl(v: float) -> str:
    """Formata valor monetário no padrão brasileiro: R$ 1.234,56"""
    s = f"{abs(v):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"R$ {'-' if v < 0 else ''}{s}"

def _num(v, casas: int = 0) -> str:
    """Formata número (não monetário) no padrão brasileiro: 1.234"""
    return f"{v:,.{casas}f}".replace(',', 'X').replace('.', ',').replace('X', '.')

def _fmt_brl_or_dash(v) -> str:
    """Como _brl, mas retorna '—' quando o valor está ausente (ex.: sem meta) —
    usado em colunas de tabela com st.dataframe(...).style.format(...)."""
    if v is None or pd.isna(v):
        return '—'
    return _brl(v)

def _fmt_pct1(v, casas: int = 1) -> str:
    """Formata percentual (valor já em unidade %, ex.: 23.5) com 1 casa —
    mesmo padrão usado hoje nas colunas de percentual desta página."""
    return f"{v:.{casas}f}%"

def _fmt_pct1_or_dash(v, casas: int = 1) -> str:
    """Como _fmt_pct1, mas retorna '—' quando o valor está ausente (ex.: sem meta)."""
    if v is None or pd.isna(v):
        return '—'
    return f"{v:.{casas}f}%"

def _fmt_dif_or_dash(v) -> str:
    """Formata diferença de projeção com sinal explícito '+'/'-' (padrão
    brasileiro), ou '—' quando não há meta para calcular a diferença."""
    if v is None or pd.isna(v):
        return '—'
    return ('+' if v >= 0 else '') + _brl(v)

def _ot_status(atual_pct: float, elapsed_pct: float):
    """Retorna (emoji, label, ratio) para status On Track — via lógica
    central (on_track.py), mesmos limiares 0,85/0,55 usados em todo o app."""
    r = on_track.calcular(
        meta=1.0, realizado=atual_pct, tipo_periodo='mensal',
        periodo_ref='(pct)', pct_tempo_decorrido=elapsed_pct,
    )
    ratio = r['ratio'] if r['ratio'] is not None else 1.0
    return r['emoji'], r['label'], ratio

def _salvar_historico_permanente(json_bytes: bytes, periodo_ref: str):
    """Persiste o histórico gerado na Seção 1 de forma real (data_store,
    GitHub-backed), para não depender só do download manual do JSON — se
    o app reiniciar ou ela abrir em outro computador, o histórico deste
    mês continua disponível e não precisa reenviar o xlsx/PDFs de novo."""
    try:
        historico_dict = json.loads(json_bytes.decode('utf-8'))
        ds.save_record(
            modulo=MODULO_HIST, tipo_periodo='mensal', periodo_ref=periodo_ref,
            valores={'historico': historico_dict},
            usuario=st.session_state.get('usuario_nome'),
        )
        st.session_state['historico_vc_salvo'] = historico_dict
        st.session_state['_vc_hist_periodo_carregado'] = periodo_ref
        st.caption(
            '✅ Histórico também salvo permanentemente no servidor — na Seção 2 '
            'não é mais obrigatório reenviar este JSON (mas o download acima '
            'continua disponível se quiser guardar uma cópia).'
        )
    except Exception as _e_persist_hist:
        st.warning(
            f'Histórico gerado e disponível para download, mas houve um '
            f'problema ao salvar de forma permanente no servidor: {_e_persist_hist}. '
            f'Guarde bem o arquivo baixado, pois pode ser necessário reenviá-lo.'
        )


def _get_meta_fat(historico_data: dict, vend: str, cli_key: str):
    """Busca meta de faturamento do cliente -- PRIMEIRO na meta definida
    manualmente no app (metas_clientes, 28/08/2026, pedido explícito da
    Ingrid: "construir edição no app" em vez de depender só da planilha),
    e só se não houver nada definido ali, cai pro valor antigo vindo da
    coluna 'META' do Excel de histórico (nunca apagado -- as duas fontes
    convivem, evita quebrar quem ainda não preencheu tudo pelo app novo)."""
    meta_app = mc_cli.get_meta_cliente('mensal', PERIODO_REF, vend, cli_key)
    if meta_app is not None:
        return meta_app

    if not historico_data:
        return None
    tab = VENDOR_TAB.get(vend, vend.upper())
    meta_vend = historico_data.get('meta', {}).get(tab, {})
    if not meta_vend:
        return None
    cli_norm = _normalize(cli_key)
    # match exato
    if cli_key in meta_vend:
        m = meta_vend[cli_key]
        return m.get('fat') if m else None
    # match normalizado
    for k, v in meta_vend.items():
        if _normalize(k) == cli_norm:
            return v.get('fat') if v else None
    return None

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_rel, tab_ontrack, tab_top50, tab_por_vend, tab_meta_vend = st.tabs([
    '📋 Relatório Semanal', '📊 On Track por Cliente',
    '🏆 Top 50 Clientes', '👤 Clientes por Vendedor', '🎯 Meta do Vendedor',
])

# =============================================================================
# TAB 1 — Relatório Semanal
# =============================================================================
with tab_rel:

    # ─ Seção 1: Configurar Histórico ─────────────────────────────────────
    with st.expander(
        f'(1) Configurar Historico - faca uma vez no inicio de {MESES[mes-1]}',
        expanded=False,
    ):
        st.info(
            f'Envie o Excel do mes anterior **ou** os dois PDFs historicos. '
            f'O app vai gerar o arquivo {fname_json} para ser usado nas gerações semanais.'
        )

        modo = st.radio(
            'Como voce quer enviar o historico?',
            options=['xlsx (Excel do mes anterior)', 'PDFs (Lucratividade por Vendedor-Cliente)'],
            horizontal=True,
            key='modo_historico',
        )

        json_bytes = None

        if modo.startswith('xlsx'):
            xlsx_hist = st.file_uploader(
                'Excel do mes anterior (mesmo formato gerado aqui)',
                type=['xlsx', 'xls'],
                key='hist_xlsx',
            )
            if xlsx_hist is None:
                st.warning('Envie o arquivo Excel do mes anterior para continuar.')
            else:
                if st.button('Salvar Historico (via xlsx)', type='secondary'):
                    with st.spinner('Lendo Excel historico...'):
                        try:
                            json_bytes = ler_xlsx_historico(
                                xlsx_bytes=xlsx_hist.read(),
                                ref_date=ref_date,
                            )
                            st.success(f'Historico gerado: {fname_json}')
                            st.download_button(
                                label=f'Baixar {fname_json}',
                                data=json_bytes,
                                file_name=fname_json,
                                mime='application/json',
                                type='secondary',
                            )
                            _salvar_historico_permanente(json_bytes, PERIODO_REF)
                        except Exception as exc:
                            st.error(f'Erro ao processar xlsx: {exc}')
                            import traceback
                            st.code(traceback.format_exc())
        else:
            h1, h2 = st.columns(2)
            with h1:
                pdf_hist_ant_ano = st.file_uploader(
                    f'PDF Mesmo Mes / Ano Anterior ({lbl_ant_a})',
                    type='pdf', key='hist_ant_ano')
            with h2:
                pdf_hist_ant_mes = st.file_uploader(
                    f'PDF Mes Anterior ({lbl_ant_m})',
                    type='pdf', key='hist_ant_mes')

            if pdf_hist_ant_ano is None or pdf_hist_ant_mes is None:
                st.warning('Envie os dois PDFs historicos para gerar o arquivo de configuracao.')
            else:
                if st.button('Salvar Historico (via PDFs)', type='secondary'):
                    with st.spinner('Parseando PDFs historicos...'):
                        try:
                            json_bytes = salvar_historico(
                                pdf_ant_ano=pdf_hist_ant_ano,
                                pdf_ant_mes=pdf_hist_ant_mes,
                                ref_date=ref_date,
                            )
                            st.success(f'Historico gerado: {fname_json}')
                            st.download_button(
                                label=f'Baixar {fname_json}',
                                data=json_bytes,
                                file_name=fname_json,
                                mime='application/json',
                                type='secondary',
                            )
                            _salvar_historico_permanente(json_bytes, PERIODO_REF)
                        except Exception as exc:
                            st.error(f'Erro ao processar PDFs historicos: {exc}')
                            import traceback
                            st.code(traceback.format_exc())

    st.divider()

    # ─ Seção 2: Gerar Relatório Semanal ──────────────────────────────────
    st.subheader(f'(2) Gerar Relatorio Semanal - {lbl_atual}')
    st.caption(
        'Envie o JSON de historico (gerado acima uma vez por mes) e os '
        'arquivos da semana. O Excel gerado tem uma aba por vendedor + GERAL.'
    )

    historico_salvo = st.session_state.get('historico_vc_salvo')

    col_j, col_a, col_b = st.columns(3)
    with col_j:
        hist_file = st.file_uploader(
            f'Historico ({fname_json})',
            type='json', key='hist_json')
        if hist_file is None and historico_salvo:
            st.caption(
                '✅ Histórico deste mês já está salvo no servidor — não '
                'precisa reenviar o JSON (pode enviar de novo se quiser '
                'substituir por outra versão).'
            )
    with col_a:
        pdf_clientes = st.file_uploader(
            'PDFs Vendedor-Cliente (1 por vendedor, ate 8 arquivos)',
            type='pdf', key='pdf_clientes',
            accept_multiple_files=True)
    with col_b:
        pdf_totais = st.file_uploader(
            'PDF Lucratividade por Vendedor (totais reais)',
            type='pdf', key='pdf_totais')

    # Comparativo com Set./Ago. (mesmo mês do ano anterior + mês anterior)
    # -- pedido explícito da Ingrid, 04/09/2026: "hoje o modelo é esse
    # [com Set./Ago.]... preciso que se torne [só Meta e Atual]... o
    # primeiro modelo só preciso no começo do mês, quando for definir as
    # metas, que aí preciso ver o comparativo." Ou seja: o padrão da
    # geração SEMANAL passa a ser só Meta+Atual (desmarcado); ela marca
    # esta caixa só quando estiver no início do mês definindo as metas e
    # quiser ver o histórico ao lado pra decidir os números. Ver
    # `incluir_comparativo` em xlsx_vendedor_cliente.gerar_xlsx.
    incluir_comparativo_vc = st.checkbox(
        '📊 Incluir comparativo com Set./Ago. (mesmo mês do ano anterior e mês anterior)',
        value=False, key='vc_incluir_comparativo',
        help='Deixe desmarcado nas gerações semanais normais (Excel só com Meta e Atual). '
             'Marque só no início do mês, quando for definir as metas com base no histórico '
             '-- aí o Excel sai com 4 grupos de colunas (Set./Ago., Meta e Atual).',
    )

    faltando = []
    if hist_file is None and not historico_salvo:
        faltando.append('Historico JSON')
    if not pdf_clientes:
        faltando.append('PDFs Vendedor-Cliente')
    if pdf_totais is None:
        faltando.append('PDF Lucratividade por Vendedor')

    if faltando:
        st.warning(f"Faltando: {', '.join(faltando)}")
    else:
        if st.button('Gerar Excel Vendedor-Cliente', type='primary', use_container_width=True):
            # BUG REAL corrigido 03/09/2026, reportado pela Ingrid ("Vendedor
            # cliente, não carrega", print mostrando o spinner "Processando e
            # montando planilha..." preso na tela junto com o resultado já
            # pronto embaixo dele). Causa raiz: acesso.redirecionar_pos_upload()
            # (que faz st.stop()) era chamado AINDA DENTRO do `with
            # st.spinner(...)`. Reproduzido isolado com Playwright antes de
            # corrigir: st.stop() disparado de dentro de um st.spinner() ainda
            # aberto interrompe o script sem o `with` chegar a fechar
            # normalmente -- e é só ao fechar normalmente que o Streamlit
            # remove o ícone/texto do spinner da tela. Resultado: o spinner
            # fica preso pra sempre, mesmo com o resto do conteúdo (sucesso,
            # botão de baixar, link pra Gerência) já renderizado embaixo dele.
            # Fix: `with st.spinner(...)` passa a envolver SÓ o processamento
            # (nada que possa disparar st.stop()) -- sucesso/botão de baixar/
            # redirecionamento só são montados DEPOIS que o spinner já fechou
            # normalmente, mesmo padrão já usado em 1_Relatorio_Diario_OTHIL.py.
            erro_geracao = None
            erro_traceback = None
            resultado_geracao = None
            with st.spinner('Processando e montando planilha...'):
                try:
                    historico   = (
                        carregar_historico(hist_file.read())
                        if hist_file is not None else historico_salvo
                    )
                    totais_res  = parse_totais_vendedor(pdf_totais)
                    totais_dict = totais_res['vendedores']

                    # Lê bytes dos PDFs de clientes para reusar no On Track
                    clientes_bytes = [f.read() for f in pdf_clientes]

                    xlsx_bytes = gerar_xlsx(
                        historico=historico,
                        pdf_clientes_atual=[io.BytesIO(b) for b in clientes_bytes],
                        totais_atual=totais_dict,
                        ref_date=ref_date,
                        incluir_comparativo=incluir_comparativo_vc,
                    )

                    # Salva dados para a aba On Track — e persiste de forma
                    # real (data_store), com histórico versionado: gerar de
                    # novo na mesma semana/mês não apaga a versão anterior,
                    # e os dados continuam disponíveis mesmo depois de um
                    # restart do app (antes só existiam em session_state).
                    aviso_persistencia = None
                    try:
                        clientes_data = parse_e_agregar(
                            [io.BytesIO(b) for b in clientes_bytes]
                        )
                        # Mesma fonte (clientes_bytes) reaproveitada pra também
                        # reter quais PRODUTOS foram vendidos a cada cliente --
                        # parse_e_agregar acima descarta o produto (só soma
                        # fat/vol/custo agregados); esta função paralela não
                        # descarta, alimentando a aba "Produtos por Cliente".
                        produtos_por_cliente = agregar_produtos_por_cliente(
                            [io.BytesIO(b) for b in clientes_bytes]
                        )
                        st.session_state['clientes_on_track'] = clientes_data
                        st.session_state['totais_on_track']   = totais_dict
                        st.session_state['historico_vc']      = historico
                        st.session_state['produtos_por_cliente_vc'] = produtos_por_cliente
                        st.session_state['ref_date_vc']       = ref_date
                        st.session_state['_vc_periodo_carregado'] = PERIODO_REF
                        ds.save_record(
                            modulo=MODULO, tipo_periodo='mensal', periodo_ref=PERIODO_REF,
                            valores={
                                'clientes_data': clientes_data,
                                'totais_dict': totais_dict,
                                'historico': historico,
                                'produtos_por_cliente': produtos_por_cliente,
                            },
                            usuario=st.session_state.get('usuario_nome'),
                        )
                    except Exception as _e_persist:
                        aviso_persistencia = (
                            f'Relatório gerado, mas houve um problema ao salvar de forma '
                            f'permanente para a aba On Track: {_e_persist}'
                        )

                    fname = f"Vendedor_Cliente_{MESES_ABR[mes-1]}{ano}_OTHIL.xlsx"
                    resultado_geracao = {
                        'xlsx_bytes': xlsx_bytes,
                        'fname': fname,
                        'periodo_totais': totais_res.get('periodo'),
                        'aviso_persistencia': aviso_persistencia,
                    }
                except Exception as exc:
                    import traceback
                    erro_geracao = exc
                    erro_traceback = traceback.format_exc()

            if erro_geracao is not None:
                st.error(f'Erro ao gerar Excel: {erro_geracao}')
                st.code(erro_traceback)
            else:
                if resultado_geracao['aviso_persistencia']:
                    st.warning(resultado_geracao['aviso_persistencia'])
                st.success(f"Planilha gerada: {resultado_geracao['fname']}")
                st.download_button(
                    label='Baixar Excel',
                    data=resultado_geracao['xlsx_bytes'],
                    file_name=resultado_geracao['fname'],
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    use_container_width=True,
                    type='secondary',
                )
                if resultado_geracao['periodo_totais']:
                    st.caption(f"Periodo do PDF de totais: {resultado_geracao['periodo_totais']}")
                # Fluxo Upload -> Gerência (pedido da Ingrid, 27/08/2026):
                # nunca fica numa tela de Dashboard depois de enviar o PDF
                # (o botão de baixar o Excel acima continua disponível).
                acesso.redirecionar_pos_upload()

    st.divider()

    # ── Meta Geral — Realizado (Faturamento/Volume/Margem) ──────────────────
    # Publica DIRETO no painel "🌐 Meta Geral" da Gerência -- pedido explícito
    # da Ingrid, 29/08/2026 ("não quero que seja a soma a partir do módulo
    # vendedor cliente, quero que tenha espaço pra eu adicionar os PDFs e ele
    # calcular"): mesmo tipo de PDF do relatório acima, mas publicação
    # INDEPENDENTE (metas_gerais.MOD_MG_VENDAS -- não depende de ter gerado o
    # Excel nem de nada mais nesta página, e o envio acima não alimenta isto).
    # Movido pra cá em 03/09/2026, pedido da Ingrid: "na gerência não é para
    # ficar upload de nada, apenas os resultados -- upload são todos nos
    # módulos" (antes ficava dentro da própria Gerência). O resultado
    # publicado aqui só aparece na aba "🌐 Meta Geral" da Gerência, nunca
    # nesta página -- mesma política de acesso de 27/08/2026 (ver acesso.py).
    with st.expander('📤 Publicar Realizado da Meta Geral (Faturamento/Volume/Margem)'):
        st.caption(
            'Sobe o mesmo tipo de PDF "Lucratividade por Vendedor" de cima, mas publica '
            'DIRETO na Meta Geral (Gerência) -- independente do relatório semanal acima.'
        )
        pdf_mg_v = st.file_uploader('PDF Lucratividade por Vendedor', type='pdf', key='mg_v_upload')
        if pdf_mg_v is not None:
            _raw_mg_v = pdf_mg_v.getvalue()
            try:
                _prev_mg_v = parse_totais_vendedor(io.BytesIO(_raw_mg_v))
            except Exception as _e_prev_v:
                st.error(f'Não foi possível ler este PDF: {_e_prev_v}')
                _prev_mg_v = None
            if _prev_mg_v is not None:
                _tg_prev_v = _prev_mg_v.get('total_geral') or {}
                puc1, puc2 = st.columns(2)
                puc1.metric('Faturamento no PDF', _brl(_tg_prev_v.get('fat', 0)))
                puc2.metric('Vendedores reconhecidos', len(_prev_mg_v.get('vendedores') or {}))

                _mes_detect_v = mg.mes_do_periodo_pdf(
                    _prev_mg_v.get('periodo'), _prev_mg_v.get('data_emissao'))
                _opcoes_mes_v = periodo.listar_periodos('mensal', n=15)
                if _mes_detect_v not in _opcoes_mes_v:
                    _opcoes_mes_v = sorted(set(_opcoes_mes_v) | {_mes_detect_v}, reverse=True)
                _mes_escolhido_v = st.selectbox(
                    'Mês de referência (Meta Geral)', _opcoes_mes_v,
                    index=_opcoes_mes_v.index(_mes_detect_v),
                    format_func=lambda r: periodo.rotulo('mensal', r), key='mg_v_mes_sel',
                    help=f"Detectado pelo período do PDF "
                         f"({_prev_mg_v.get('periodo') or _prev_mg_v.get('data_emissao') or '?'}). "
                         f"Corrija aqui se necessário.",
                )
                if st.button('📊 Processar e publicar na Meta Geral', key='mg_v_btn'):
                    # Mesma correção de 03/09/2026 aplicada acima em "Gerar
                    # Excel Vendedor-Cliente" (ver comentário lá): o spinner
                    # não pode conter a chamada de redirecionar_pos_upload()
                    # (st.stop()) -- senão fica preso na tela.
                    _erro_pub_v = None
                    _sucesso_pub_v = None
                    with st.spinner('Publicando...'):
                        try:
                            _reg_mg_v = mg.publicar_vendas_pdf(
                                _mes_escolhido_v, io.BytesIO(_raw_mg_v),
                                usuario=st.session_state.get('usuario_nome'))
                            _erro_persist_v = _reg_mg_v.get('_erro_persistencia_remota') if _reg_mg_v else None
                            if _erro_persist_v:
                                _sucesso_pub_v = (
                                    'warning',
                                    f'Publicado localmente, mas houve um problema ao salvar de '
                                    f'forma permanente: {_erro_persist_v}')
                            else:
                                _sucesso_pub_v = (
                                    'success',
                                    f"✅ Publicado na Meta Geral -- "
                                    f"{periodo.rotulo('mensal', _mes_escolhido_v)}.")
                        except Exception as _e_pub_v:
                            _erro_pub_v = _e_pub_v
                    if _erro_pub_v is not None:
                        st.error(f'Erro ao publicar: {_erro_pub_v}')
                    else:
                        (st.success if _sucesso_pub_v[0] == 'success' else st.warning)(_sucesso_pub_v[1])
                        acesso.redirecionar_pos_upload()


# =============================================================================
# TAB 2 — On Track por Cliente
# =============================================================================
with tab_ontrack:
    st.header('📊 On Track por Cliente')
    st.caption(f'Período de referência selecionado: **{lbl_atual}**')

    clientes_data  = st.session_state.get('clientes_on_track')
    historico_data = st.session_state.get('historico_vc')
    totais_dict_ot = st.session_state.get('totais_on_track', {})
    ref_date_ot    = st.session_state.get('ref_date_vc', ref_date)

    if not clientes_data:
        st.info(
            'Gere o relatório semanal na aba **📋 Relatório Semanal** primeiro. '
            'Os dados aparecerão aqui automaticamente.'
        )
    else:
        # Contexto de datas do mês de referência
        today          = datetime.today()
        ano_ref        = ref_date_ot.year
        mes_ref        = ref_date_ot.month
        days_in_month  = _cal.monthrange(ano_ref, mes_ref)[1]
        # Dias decorridos: se o mês de referência é o mês atual, usa hoje; senão usa fim do mês
        if ano_ref == today.year and mes_ref == today.month:
            days_elapsed = max(today.day, 1)
        else:
            days_elapsed = days_in_month
        days_remaining = max(days_in_month - days_elapsed, 0)
        elapsed_pct    = days_elapsed / days_in_month

        # ── Filtros ──────────────────────────────────────────────────────
        f1, f2, f3 = st.columns([3, 2, 2])
        with f1:
            busca = st.text_input('🔍 Pesquisar cliente', placeholder='Digite parte do nome...', key='ot_busca')
        with f2:
            vendedores_disp = ['Todos'] + sorted(clientes_data.keys())
            vend_filtro = st.selectbox('Filtrar por vendedor', vendedores_disp, key='ot_vend')
        with f3:
            sort_cli = st.selectbox('Ordenar por', [
                'Maior faturamento', 'Maior % atingido', 'Maior MC R$',
                'Maior margem', 'Maior valor restante', 'Alfabético',
            ], key='ot_sort')

        st.divider()

        # ── Construir linhas com todos os indicadores ─────────────────────
        rows = []
        for vendedor, clientes in clientes_data.items():
            if vend_filtro != 'Todos' and vendedor != vend_filtro:
                continue
            for cliente, dados in clientes.items():
                if busca and busca.lower() not in cliente.lower():
                    continue

                fat    = dados.get('fat', 0)
                mc_rs  = dados.get('mc_rs', 0)
                mc_pct = dados.get('mc_pct', 0)
                res    = dados.get('resultado_real', 0)

                meta = _get_meta_fat(historico_data, vendedor, cliente) or 0
                tem_meta = meta > 0

                pct_atg      = fat / meta if tem_meta else 0.0
                restante     = max(meta - fat, 0) if tem_meta else 0.0
                avg_diaria   = fat / days_elapsed if days_elapsed > 0 else 0.0
                projecao     = fat + avg_diaria * days_remaining
                diferenca    = projecao - meta if tem_meta else 0.0
                media_nec    = restante / days_remaining if (tem_meta and days_remaining > 0) else 0.0

                if tem_meta:
                    em, lb, ratio = _ot_status(pct_atg, elapsed_pct)
                else:
                    em, lb, ratio = '—', 'Sem meta', 1.0

                rows.append({
                    'Vendedor':  vendedor,
                    'Cliente':   cliente,
                    '_fat':      fat,
                    '_meta':     meta,
                    '_mc_rs':    mc_rs,
                    '_mc_pct':   mc_pct,
                    '_res':      res,
                    '_pct_atg':  pct_atg,
                    '_restante': restante,
                    '_projecao': projecao,
                    '_diferenca':diferenca,
                    '_ratio':    ratio,
                    '_avg':      avg_diaria,
                    '_media_nec':media_nec,
                    '_em':       em,
                    '_lb':       lb,
                    '_tem_meta': tem_meta,
                })

        # Ordenação
        sort_map = {
            'Maior faturamento':   ('_fat',      True),
            'Maior % atingido':    ('_pct_atg',  True),
            'Maior MC R$':         ('_mc_rs',    True),
            'Maior margem':        ('_res',      True),
            'Maior valor restante':('_restante', True),
            'Alfabético':          ('Cliente',   False),
        }
        sk, sr = sort_map[sort_cli]
        rows.sort(key=lambda r: r[sk], reverse=sr)

        if not rows:
            st.info('Nenhum cliente encontrado com os filtros selecionados.')
            st.stop()

        # ── Totais para cards ─────────────────────────────────────────────
        tot_fat  = sum(r['_fat']      for r in rows)
        tot_meta = sum(r['_meta']     for r in rows)
        tot_mc   = sum(r['_mc_rs']    for r in rows)
        tot_pct  = tot_fat / tot_meta if tot_meta > 0 else 0.0
        tot_rest = max(tot_meta - tot_fat, 0)
        avg_d    = tot_fat / days_elapsed if days_elapsed > 0 else 0.0
        tot_proj = tot_fat + avg_d * days_remaining
        tot_dif  = tot_proj - tot_meta

        g_em, g_lb, g_ratio = _ot_status(tot_pct, elapsed_pct)

        # ── Cards de resumo (st.metric nativo) ──────────────────────────────
        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric('Meta Mensal', _brl(tot_meta))
        k2.metric('Faturamento', _brl(tot_fat))
        k3.metric('% Atingido', f"{tot_pct*100:.1f}% {g_em}")
        k4.metric('Valor Restante', _brl(tot_rest))
        k5.metric('Projeção Mês', _brl(tot_proj))
        _dif_sinal = '+' if tot_dif >= 0 else '-'
        k6.metric('Diferença Proj.', _brl(tot_dif), delta=f"{_dif_sinal}{_brl(abs(tot_dif))}")

        # Barra de progresso geral (nativa) + ritmo esperado em texto
        prog_w = min(tot_pct, 1.0)
        exp_w  = elapsed_pct * 100
        st.progress(
            prog_w,
            text=(f"Progresso da Meta — Dia {days_elapsed} de {days_in_month} "
                  f"({elapsed_pct*100:.0f}% do mês) — {prog_w*100:.1f}% atingido"),
        )
        st.caption(
            f"▲ Ritmo esperado: {exp_w:.0f}%  |  Dia {days_elapsed}/{days_in_month}  |  "
            f"{days_remaining} dias restantes"
        )

        st.divider()

        # ── Comparativo (componente central comparativo.py) ────────────────
        with st.expander('📊 Comparativo', expanded=True):
            periodo_ref_ot = periodo.periodo_ref('mensal', ref_date_ot.date())
            slug_ant_ot = periodo.periodo_anterior('mensal', periodo_ref_ot)
            slug_ano_ant_ot = periodo.periodo_ano_anterior('mensal', periodo_ref_ot)

            def _fat_total_periodo(pref):
                reg = ds.load_current(MODULO, 'mensal', pref)
                if not reg:
                    return None
                cdata = reg['valores'].get('clientes_data', {})
                return sum(c.get('fat', 0) for cli in cdata.values() for c in cli.values())

            fat_ant_ot = _fat_total_periodo(slug_ant_ot)
            fat_ano_ant_ot = _fat_total_periodo(slug_ano_ant_ot)

            cc1, cc2 = st.columns(2)
            with cc1:
                st.markdown(f'**{lbl_atual} × {periodo.rotulo("mensal", slug_ant_ot)}**')
                if fat_ant_ot is None:
                    st.caption('Sem dado salvo do mês anterior para comparar.')
                else:
                    comp_m = comparativo.calcular(tot_fat, fat_ant_ot)
                    st.metric('Faturamento', _brl(tot_fat), delta=comparativo.formatar_variacao(comp_m))
            with cc2:
                st.markdown(f'**{lbl_atual} × {periodo.rotulo("mensal", slug_ano_ant_ot)} (ano anterior)**')
                if fat_ano_ant_ot is None:
                    st.caption('Sem dado salvo da mesma época no ano anterior para comparar.')
                else:
                    comp_a = comparativo.calcular(tot_fat, fat_ano_ant_ot)
                    st.metric('Faturamento', _brl(tot_fat), delta=comparativo.formatar_variacao(comp_a))

        st.divider()

        # ── Ranking de Vendedores ─────────────────────────────────────────
        if vend_filtro == 'Todos':
            with st.expander('🏆 Ranking de Vendedores', expanded=True):
                vend_rank: dict = {}
                for r in rows:
                    v = r['Vendedor']
                    if v not in vend_rank:
                        vend_rank[v] = {'fat': 0.0, 'meta': 0.0, 'mc_rs': 0.0}
                    vend_rank[v]['fat']   += r['_fat']
                    vend_rank[v]['meta']  += r['_meta']
                    vend_rank[v]['mc_rs'] += r['_mc_rs']

                rank_rows = []
                for v, d in vend_rank.items():
                    pct = d['fat'] / d['meta'] if d['meta'] > 0 else 0.0
                    em, lb, ratio = _ot_status(pct, elapsed_pct)
                    tend = '↑ Acima' if ratio >= 1.0 else ('→ No ritmo' if ratio >= 0.85 else '↓ Abaixo')
                    rank_rows.append({'v': v, 'fat': d['fat'], 'meta': d['meta'],
                                      'mc_rs': d['mc_rs'], 'pct': pct,
                                      'em': em, 'lb': lb, 'ratio': ratio, 'tend': tend})
                rank_rows.sort(key=lambda x: x['pct'], reverse=True)

                medals = ['🥇', '🥈', '🥉']
                df_rank_rows = []
                for i, rv in enumerate(rank_rows):
                    df_rank_rows.append({
                        'Colocação':   medals[i] if i < 3 else f'#{i+1}',
                        'Vendedor':    rv['v'],
                        'Faturamento': rv['fat'],
                        'Meta':        rv['meta'],
                        '% Atingido':  rv['pct'] * 100,
                        'Status':      f"{rv['em']} {rv['lb']}",
                        'Tendência':   rv['tend'],
                    })
                df_rank = pd.DataFrame(df_rank_rows)
                st.dataframe(
                    df_rank.style.format({
                        'Faturamento': _brl,
                        'Meta':        _brl,
                        '% Atingido':  _fmt_pct1,
                    }),
                    use_container_width=True, hide_index=True,
                )

        st.divider()

        # ── Tabela detalhada ──────────────────────────────────────────────
        st.subheader(f'Detalhamento por Cliente — {len(rows)} cliente(s)')

        df_rows = []
        for r in rows:
            df_rows.append({
                'Vendedor':      r['Vendedor'],
                'Cliente':       r['Cliente'],
                'Meta':          r['_meta'] if r['_tem_meta'] else float('nan'),
                'Faturamento':   r['_fat'],
                '% Atingido':    (r['_pct_atg'] * 100) if r['_tem_meta'] else float('nan'),
                'Restante':      r['_restante'] if r['_tem_meta'] else float('nan'),
                'Méd. Diária':   r['_avg'],
                'Méd. Nec/dia':  r['_media_nec'] if r['_tem_meta'] else float('nan'),
                'Projeção':      r['_projecao'],
                'Dif. Projeção': r['_diferenca'] if r['_tem_meta'] else float('nan'),
                'MC R$':         r['_mc_rs'],
                'MC %':          r['_mc_pct'],
                'Status':        f"{r['_em']} {r['_lb']}",
            })

        df_detalhe = pd.DataFrame(df_rows)
        st.dataframe(
            df_detalhe.style.format({
                'Meta':          _fmt_brl_or_dash,
                'Faturamento':   _brl,
                '% Atingido':    _fmt_pct1_or_dash,
                'Restante':      _fmt_brl_or_dash,
                'Méd. Diária':   _brl,
                'Méd. Nec/dia':  _fmt_brl_or_dash,
                'Projeção':      _brl,
                'Dif. Projeção': _fmt_dif_or_dash,
                'MC R$':         _brl,
                'MC %':          _fmt_pct1,
            }),
            use_container_width=True, hide_index=True,
        )

        st.divider()

        # ── Exportar CSV ──────────────────────────────────────────────────
        csv_rows = []
        for r in rows:
            csv_rows.append({
                'Vendedor':                  r['Vendedor'],
                'Cliente':                   r['Cliente'],
                'Meta (R$)':                 round(r['_meta'], 2),
                'Faturamento (R$)':           round(r['_fat'], 2),
                '% Atingido':                f"{r['_pct_atg']*100:.1f}%" if r['_tem_meta'] else '—',
                'Valor Restante (R$)':        round(r['_restante'], 2),
                'Média Diária Atual (R$)':    round(r['_avg'], 2),
                'Média Necessária/dia (R$)':  round(r['_media_nec'], 2),
                'Projeção Fechamento (R$)':   round(r['_projecao'], 2),
                'Dif. Projeção vs Meta (R$)': round(r['_diferenca'], 2),
                'MC R$':                     round(r['_mc_rs'], 2),
                'MC %':                      f"{r['_mc_pct']:.1f}%",
                'Margem %':                  f"{r['_res']:.1f}%",
                'Status On Track':            f"{r['_em']} {r['_lb']}",
            })

        c_csv, c_pub = st.columns(2)
        with c_csv:
            csv = pd.DataFrame(csv_rows).to_csv(index=False, sep=';').encode('utf-8-sig')
            st.download_button(
                '⬇️ Exportar CSV completo',
                data=csv,
                file_name=f'ontrack_cliente_{lbl_atual.replace("/","")}.csv',
                mime='text/csv',
                use_container_width=True,
                type='secondary',
            )
        with c_pub:
            if st.button('📤 Publicar On Track para Gerência', use_container_width=True, type='primary'):
                try:
                    os.makedirs(os.path.dirname(_ONTRACK_CLI_FILE), exist_ok=True)
                    snapshot = {
                        'publicado_em':  datetime.now().isoformat(timespec='seconds'),
                        'periodo':       lbl_atual,
                        'days_elapsed':  days_elapsed,
                        'days_in_month': days_in_month,
                        'days_remaining':days_remaining,
                        'elapsed_pct':   elapsed_pct,
                        'totais': {
                            'fat':  tot_fat,  'meta': tot_meta,
                            'mc':   tot_mc,   'pct':  tot_pct,
                            'rest': tot_rest, 'proj': tot_proj,
                            'dif':  tot_dif,
                        },
                        'rows': [{
                            'Vendedor':  r['Vendedor'],
                            'Cliente':   r['Cliente'],
                            'fat':       r['_fat'],
                            'meta':      r['_meta'],
                            'mc_rs':     r['_mc_rs'],
                            'mc_pct':    r['_mc_pct'],
                            'res':       r['_res'],
                            'pct_atg':   r['_pct_atg'],
                            'restante':  r['_restante'],
                            'projecao':  r['_projecao'],
                            'diferenca': r['_diferenca'],
                            'ratio':     r['_ratio'],
                            'avg':       r['_avg'],
                            'media_nec': r['_media_nec'],
                            'em':        r['_em'],
                            'lb':        r['_lb'],
                            'tem_meta':  r['_tem_meta'],
                        } for r in rows],
                    }
                    # Arquivo atual (compatibilidade)
                    with open(_ONTRACK_CLI_FILE, 'w', encoding='utf-8') as f:
                        json.dump(snapshot, f, ensure_ascii=False, indent=2)
                    # Histórico por mês (usa ref_date_vc se disponível)
                    os.makedirs(_ONTRACK_CLI_DIR, exist_ok=True)
                    ref = st.session_state.get('ref_date_vc', datetime.today())
                    slug_mes = ref.strftime('%Y-%m')
                    hist_cli_path = os.path.join(_ONTRACK_CLI_DIR, f'{slug_mes}.json')
                    with open(hist_cli_path, 'w', encoding='utf-8') as f:
                        json.dump(snapshot, f, ensure_ascii=False, indent=2)
                    # Persistência real e versionada (sobrevive a restart do app)
                    try:
                        ds.save_record(
                            modulo=MODULO_ONTRACK, tipo_periodo='mensal', periodo_ref=slug_mes,
                            valores=snapshot, usuario=st.session_state.get('usuario_nome'),
                        )
                    except Exception as e2:
                        st.warning(f'Publicado localmente, mas houve um problema ao salvar de forma permanente: {e2}')
                    st.success('✅ On Track de Clientes publicado na Gerência.')
                except Exception as e:
                    st.error(f'Erro ao publicar: {e}')


# =============================================================================
# TAB 3 — Top 50 Clientes
# =============================================================================
with tab_top50:
    st.header('🏆 Top 50 Clientes')
    st.caption(f'Período de referência selecionado: **{lbl_atual}**')

    clientes_data_50 = st.session_state.get('clientes_on_track')
    historico_data_50 = st.session_state.get('historico_vc')

    if not clientes_data_50:
        st.info(
            'Gere o relatório do mês na aba **📋 Relatório Semanal** primeiro '
            '(ou selecione um período de referência que já tenha relatório gerado).'
        )
    else:
        periodo_ref_50 = periodo.periodo_ref('mensal', ref_date.date())
        slug_ant_50 = periodo.periodo_anterior('mensal', periodo_ref_50)

        ordenar_por = st.selectbox(
            'Ordenar por',
            ['Faturamento', 'Volume', 'Margem (MC R$)', 'Rentabilidade (MC %)', 'Atingimento da meta'],
            key='top50_sort',
        )

        reg_ant_50 = ds.load_current(MODULO, 'mensal', slug_ant_50)
        clientes_ant_50 = reg_ant_50['valores'].get('clientes_data', {}) if reg_ant_50 else {}

        linhas_50 = []
        for vendedor, clientes in clientes_data_50.items():
            for cliente, dados in clientes.items():
                fat = dados.get('fat', 0)
                vol = dados.get('vol', 0)
                mc_rs = dados.get('mc_rs', 0)
                mc_pct = dados.get('mc_pct', 0)
                meta = _get_meta_fat(historico_data_50, vendedor, cliente) or 0

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
                    r_ot = on_track.calcular(meta, fat, 'mensal', periodo_ref_50)
                    status_txt = f"{r_ot['emoji']} {r_ot['label']}"
                else:
                    pct_atg = None
                    status_txt = '—'

                linhas_50.append({
                    'Vendedor': vendedor, 'Cliente': cliente,
                    '_fat': fat, '_vol': vol, '_mc_rs': mc_rs, '_mc_pct': mc_pct,
                    '_pct_atg': pct_atg or 0, 'Faturamento': fat,
                    'Volume (cx)': vol, 'Margem (MC R$)': mc_rs,
                    'Rentabilidade': mc_pct,
                    'Comparativo': comparativo.formatar_variacao(comp),
                    '% Atingido': (pct_atg * 100) if pct_atg is not None else float('nan'),
                    'On Track': status_txt,
                })

        sort_key_map = {
            'Faturamento': '_fat', 'Volume': '_vol', 'Margem (MC R$)': '_mc_rs',
            'Rentabilidade (MC %)': '_mc_pct', 'Atingimento da meta': '_pct_atg',
        }
        linhas_50.sort(key=lambda r: r[sort_key_map[ordenar_por]], reverse=True)
        top50 = linhas_50[:50]
        for i, r in enumerate(top50, start=1):
            r['Ranking'] = i

        st.caption(f'{len(linhas_50)} cliente(s) no total — mostrando os {len(top50)} principais por {ordenar_por.lower()}.')

        df_top50 = pd.DataFrame(top50)[[
            'Ranking', 'Vendedor', 'Cliente', 'Faturamento', 'Volume (cx)',
            'Margem (MC R$)', 'Rentabilidade', 'Comparativo', '% Atingido', 'On Track',
        ]]
        st.dataframe(
            df_top50.style.format({
                'Faturamento':     _brl,
                'Volume (cx)':     _num,
                'Margem (MC R$)':  _brl,
                'Rentabilidade':   _fmt_pct1,
                '% Atingido':      _fmt_pct1_or_dash,
            }),
            use_container_width=True, hide_index=True,
        )

        # CSV mantém o mesmo texto formatado exibido anteriormente na tabela
        df_top50_csv = df_top50.copy()
        df_top50_csv['Faturamento']    = df_top50_csv['Faturamento'].map(_brl)
        df_top50_csv['Volume (cx)']    = df_top50_csv['Volume (cx)'].map(_num)
        df_top50_csv['Margem (MC R$)'] = df_top50_csv['Margem (MC R$)'].map(_brl)
        df_top50_csv['Rentabilidade']  = df_top50_csv['Rentabilidade'].map(_fmt_pct1)
        df_top50_csv['% Atingido']     = df_top50_csv['% Atingido'].map(_fmt_pct1_or_dash)

        csv_top50 = df_top50_csv.to_csv(index=False, sep=';').encode('utf-8-sig')
        st.download_button(
            '⬇️ Exportar Top 50 (CSV)', data=csv_top50,
            file_name=f'top50_clientes_{lbl_atual.replace("/","")}.csv',
            mime='text/csv',
            type='secondary',
        )


# =============================================================================
# TAB 4 — Clientes por Vendedor
# =============================================================================
with tab_por_vend:
    st.header('👤 Clientes por Vendedor')
    st.caption(f'Período de referência selecionado: **{lbl_atual}**')

    clientes_data_pv = st.session_state.get('clientes_on_track')
    historico_data_pv = st.session_state.get('historico_vc')

    if not clientes_data_pv:
        st.info(
            'Gere o relatório do mês na aba **📋 Relatório Semanal** primeiro '
            '(ou selecione um período de referência que já tenha relatório gerado).'
        )
    else:
        vendedor_sel_pv = st.selectbox(
            'Selecionar vendedor', sorted(clientes_data_pv.keys()), key='pv_vendedor_sel',
        )

        periodo_ref_pv = periodo.periodo_ref('mensal', ref_date.date())
        slug_ant_pv = periodo.periodo_anterior('mensal', periodo_ref_pv)
        reg_ant_pv = ds.load_current(MODULO, 'mensal', slug_ant_pv)
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
            meta = _get_meta_fat(historico_data_pv, vendedor_sel_pv, cliente) or 0
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
                r_ot = on_track.calcular(meta, fat, 'mensal', periodo_ref_pv)
                status_txt = f"{r_ot['emoji']} {r_ot['label']}"
            else:
                status_txt = '—'

            linhas_pv.append({
                '_fat': fat,
                'Cliente': cliente, 'Faturamento': fat, 'Volume (cx)': vol,
                'Margem (MC R$)': mc_rs, 'Rentabilidade': mc_pct,
                'Comparativo': comparativo.formatar_variacao(comp),
                'Participação no vendedor': participacao * 100,
                'On Track': status_txt,
            })

        linhas_pv.sort(key=lambda r: r['_fat'], reverse=True)

        st.caption(f'{len(linhas_pv)} cliente(s) de **{vendedor_sel_pv}** em {lbl_atual} — '
                   f'faturamento total: {_brl(fat_total_vendedor)}')

        df_pv = pd.DataFrame(linhas_pv)[[
            'Cliente', 'Faturamento', 'Volume (cx)', 'Margem (MC R$)', 'Rentabilidade',
            'Comparativo', 'Participação no vendedor', 'On Track',
        ]]
        st.dataframe(
            df_pv.style.format({
                'Faturamento':               _brl,
                'Volume (cx)':               _num,
                'Margem (MC R$)':            _brl,
                'Rentabilidade':             _fmt_pct1,
                'Participação no vendedor':  _fmt_pct1,
            }),
            use_container_width=True, hide_index=True,
        )

        # CSV mantém o mesmo texto formatado exibido anteriormente na tabela
        df_pv_csv = df_pv.copy()
        df_pv_csv['Faturamento']              = df_pv_csv['Faturamento'].map(_brl)
        df_pv_csv['Volume (cx)']              = df_pv_csv['Volume (cx)'].map(_num)
        df_pv_csv['Margem (MC R$)']           = df_pv_csv['Margem (MC R$)'].map(_brl)
        df_pv_csv['Rentabilidade']            = df_pv_csv['Rentabilidade'].map(_fmt_pct1)
        df_pv_csv['Participação no vendedor'] = df_pv_csv['Participação no vendedor'].map(_fmt_pct1)

        csv_pv = df_pv_csv.to_csv(index=False, sep=';').encode('utf-8-sig')
        st.download_button(
            f'⬇️ Exportar clientes de {vendedor_sel_pv} (CSV)', data=csv_pv,
            file_name=f'clientes_{vendedor_sel_pv}_{lbl_atual.replace("/","")}.csv',
            mime='text/csv',
            type='secondary',
        )


# =============================================================================
# TAB 5 — Meta do Vendedor (meta própria + metas por cliente + produtos)
# =============================================================================
# Pedido explícito da Ingrid (28/08/2026): "ter uma planilha ou um quadro
# que abranja a meta geral deste vendedor + as metas por cliente em uma sub
# aba com a meta geral... + uma aba que pode até ser a mesma que permita
# que o vendedor veja todos os seus clientes e quais produtos estão sendo
# vendidos para estes clientes."
with tab_meta_vend:
    st.header('🎯 Meta do Vendedor')
    st.caption(f'Período de referência selecionado: **{lbl_atual}**')
    st.caption(
        'Meta própria de faturamento deste vendedor — independente da Meta '
        'Geral da empresa ("uma meta própria, definida à parte"). Mesma '
        'persistência usada na Gerência → Metas Gerais → aba Vendedor → '
        'OnTrack Semanal por Vendedor: editar aqui ou lá atualiza o mesmo valor.'
    )

    clientes_data_mv = st.session_state.get('clientes_on_track')
    produtos_pc_mv    = st.session_state.get('produtos_por_cliente_vc')
    historico_data_mv = st.session_state.get('historico_vc')

    _nomes_vend_cfg_mv = list(calc.VENDEDORES_PADRAO.keys())
    vendedor_sel_mv = st.selectbox('Selecionar vendedor', sorted(_nomes_vend_cfg_mv), key='mv_vendedor_sel')

    # ── Meta própria do vendedor ─────────────────────────────────────────
    _metas_vend_atuais_mv = mg.carregar_metas_vendedores('mensal', PERIODO_REF)
    _meta_vend_sel = _metas_vend_atuais_mv.get(vendedor_sel_mv) or 0.0

    with st.expander(f'🎯 Definir/editar meta de {vendedor_sel_mv}', expanded=not bool(_meta_vend_sel)):
        with st.form(key='mv_form_meta_vendedor'):
            _nova_meta_vend = st.number_input(
                f'Meta de Faturamento (R$) — {vendedor_sel_mv}', min_value=0.0,
                value=float(_meta_vend_sel), step=1000.0, key='mv_meta_input',
            )
            if st.form_submit_button('💾 Salvar meta do vendedor', type='primary'):
                _novas_todas_mv = dict(_metas_vend_atuais_mv)
                _novas_todas_mv[vendedor_sel_mv] = _nova_meta_vend
                mg.salvar_metas_vendedores('mensal', PERIODO_REF, _novas_todas_mv,
                                            usuario=st.session_state.get('usuario_nome'))
                st.success('Meta do vendedor salva.')
                st.rerun()

    # ── Realizado (mesma fonte de fat usada em Clientes por Vendedor) ────
    if not clientes_data_mv:
        st.info('Gere o relatório do mês na aba **📋 Relatório Semanal** primeiro pra ver o realizado.')
        clientes_vendedor_mv = {}
    else:
        clientes_vendedor_mv = clientes_data_mv.get(vendedor_sel_mv, {})
        fat_realizado_mv = sum(d.get('fat', 0) for d in clientes_vendedor_mv.values())
        if _meta_vend_sel:
            r_ot_mv = on_track.calcular(_meta_vend_sel, fat_realizado_mv, 'mensal', PERIODO_REF)
            mv1, mv2, mv3 = st.columns(3)
            mv1.metric('Meta', _brl(_meta_vend_sel))
            mv2.metric('Faturamento', _brl(fat_realizado_mv))
            mv3.metric('% Atingido', f"{fat_realizado_mv / _meta_vend_sel * 100:.1f}%")
            st.progress(min(fat_realizado_mv / _meta_vend_sel, 1.0),
                        text=f"{r_ot_mv['emoji']} {r_ot_mv['label']}")
        else:
            st.metric('Faturamento', _brl(fat_realizado_mv))
            st.caption('Defina a meta acima pra ver % atingido e status.')

    st.divider()

    sub_metas_cli, sub_prod_cli = st.tabs(['💰 Metas por Cliente', '📦 Produtos por Cliente'])

    # ── Sub-aba: Metas por Cliente ───────────────────────────────────────
    with sub_metas_cli:
        if not clientes_vendedor_mv:
            st.info(f'Nenhum cliente encontrado para {vendedor_sel_mv} em {lbl_atual} ainda.')
        else:
            _linhas_mc = []
            for _cli, _dados_cli in clientes_vendedor_mv.items():
                _fat_cli = _dados_cli.get('fat', 0)
                _meta_cli = _get_meta_fat(historico_data_mv, vendedor_sel_mv, _cli) or 0
                if _meta_cli:
                    _r_ot_cli = on_track.calcular(_meta_cli, _fat_cli, 'mensal', PERIODO_REF)
                    _status_txt_cli = f"{_r_ot_cli['emoji']} {_r_ot_cli['label']}"
                    _pct_cli = _fat_cli / _meta_cli * 100
                else:
                    _status_txt_cli = '—'
                    _pct_cli = float('nan')
                _linhas_mc.append({
                    'Cliente': _cli,
                    'Meta': _meta_cli if _meta_cli else float('nan'),
                    'Faturamento': _fat_cli,
                    '% Atingido': _pct_cli,
                    'Status': _status_txt_cli,
                })
            _linhas_mc.sort(key=lambda r: r['Faturamento'], reverse=True)
            st.dataframe(
                pd.DataFrame(_linhas_mc).style.format({
                    'Meta':        _fmt_brl_or_dash,
                    'Faturamento': _brl,
                    '% Atingido':  _fmt_pct1_or_dash,
                }),
                use_container_width=True, hide_index=True,
            )

            with st.expander('✏️ Definir/editar meta por cliente'):
                st.caption(
                    'Meta de faturamento (R$) por cliente, definida diretamente aqui — fica '
                    'salva e passa a valer nas outras abas também (On Track por Cliente, '
                    'Top 50, Clientes por Vendedor). Deixe em 0 pra continuar usando a meta '
                    'antiga da planilha Excel de histórico, se houver uma.'
                )
                _metas_cli_atuais = mc_cli.carregar_metas_cliente_vendedor(
                    'mensal', PERIODO_REF, vendedor_sel_mv)
                with st.form(key='mv_form_metas_clientes'):
                    _novas_metas_cli = {}
                    for _cli in sorted(clientes_vendedor_mv.keys()):
                        _novas_metas_cli[_cli] = st.number_input(
                            _cli, min_value=0.0,
                            value=float(_metas_cli_atuais.get(_cli) or 0.0), step=500.0,
                            key=f'mv_meta_cli_{vendedor_sel_mv}_{_cli}',
                        )
                    if st.form_submit_button('💾 Salvar metas por cliente', type='primary'):
                        mc_cli.salvar_metas_clientes(
                            'mensal', PERIODO_REF, vendedor_sel_mv, _novas_metas_cli,
                            usuario=st.session_state.get('usuario_nome'))
                        st.success('Metas por cliente salvas.')
                        st.rerun()

    # ── Sub-aba: Produtos por Cliente (relatório mais recente) ──────────
    with sub_prod_cli:
        if not produtos_pc_mv:
            st.info(
                'Sem dado de produtos por cliente para este período ainda — gere o '
                'relatório novamente na aba **📋 Relatório Semanal** (esta aba passou a '
                'existir em 28/08/2026; relatórios gerados antes disso não têm esse dado '
                'salvo, é preciso reenviar os PDFs Vendedor-Cliente uma vez).'
            )
        else:
            produtos_vendedor_mv = produtos_pc_mv.get(vendedor_sel_mv, {})
            if not produtos_vendedor_mv:
                st.info(f'Nenhum produto encontrado para {vendedor_sel_mv} em {lbl_atual}.')
            else:
                st.caption(f'Relatório mais recente gerado — {lbl_atual}.')
                _cli_prod_sel = st.selectbox(
                    'Ver produtos de um cliente específico',
                    sorted(produtos_vendedor_mv.keys()), key='mv_cliente_produtos_sel',
                )
                _produtos_cli_sel = produtos_vendedor_mv.get(_cli_prod_sel, {})
                _linhas_prod_sel = sorted(
                    [{'Produto': p, 'Volume (cx)': d['vol'], 'Faturamento': d['fat']}
                     for p, d in _produtos_cli_sel.items()],
                    key=lambda r: r['Faturamento'], reverse=True,
                )
                st.dataframe(
                    pd.DataFrame(_linhas_prod_sel).style.format({
                        'Volume (cx)': _num, 'Faturamento': _brl,
                    }),
                    use_container_width=True, hide_index=True,
                )

                st.divider()
                st.caption(f'Todos os clientes de {vendedor_sel_mv} — produtos vendidos ({lbl_atual})')
                _linhas_prod_todos = []
                for _cli_p, _prods_p in produtos_vendedor_mv.items():
                    for _p_nome, _p_dados in _prods_p.items():
                        _linhas_prod_todos.append({
                            'Cliente': _cli_p, 'Produto': _p_nome,
                            'Volume (cx)': _p_dados['vol'], 'Faturamento': _p_dados['fat'],
                        })
                _linhas_prod_todos.sort(key=lambda r: (r['Cliente'], -r['Faturamento']))
                st.dataframe(
                    pd.DataFrame(_linhas_prod_todos).style.format({
                        'Volume (cx)': _num, 'Faturamento': _brl,
                    }),
                    use_container_width=True, hide_index=True,
                )
