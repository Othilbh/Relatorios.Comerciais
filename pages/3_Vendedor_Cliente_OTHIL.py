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
    parse_e_agregar, VENDOR_TAB, _normalize,
)
from parsers_vendedor import parse_totais_vendedor
import periodo
import comparativo
import on_track
import data_store as ds

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
    """Busca meta de faturamento do cliente no histórico."""
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
tab_rel, tab_ontrack, tab_top50, tab_por_vend = st.tabs([
    '📋 Relatório Semanal', '📊 On Track por Cliente',
    '🏆 Top 50 Clientes', '👤 Clientes por Vendedor',
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
                    )

                    # Salva dados para a aba On Track — e persiste de forma
                    # real (data_store), com histórico versionado: gerar de
                    # novo na mesma semana/mês não apaga a versão anterior,
                    # e os dados continuam disponíveis mesmo depois de um
                    # restart do app (antes só existiam em session_state).
                    try:
                        clientes_data = parse_e_agregar(
                            [io.BytesIO(b) for b in clientes_bytes]
                        )
                        st.session_state['clientes_on_track'] = clientes_data
                        st.session_state['totais_on_track']   = totais_dict
                        st.session_state['historico_vc']      = historico
                        st.session_state['ref_date_vc']       = ref_date
                        st.session_state['_vc_periodo_carregado'] = PERIODO_REF
                        ds.save_record(
                            modulo=MODULO, tipo_periodo='mensal', periodo_ref=PERIODO_REF,
                            valores={
                                'clientes_data': clientes_data,
                                'totais_dict': totais_dict,
                                'historico': historico,
                            },
                            usuario=st.session_state.get('usuario_nome'),
                        )
                    except Exception as _e_persist:
                        st.warning(
                            f'Relatório gerado, mas houve um problema ao salvar de forma '
                            f'permanente para a aba On Track: {_e_persist}'
                        )

                    fname = f"Vendedor_Cliente_{MESES_ABR[mes-1]}{ano}_OTHIL.xlsx"
                    st.success(f'Planilha gerada: {fname}')
                    st.download_button(
                        label='Baixar Excel',
                        data=xlsx_bytes,
                        file_name=fname,
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        use_container_width=True,
                    )
                    if totais_res.get('periodo'):
                        st.caption(f"Periodo do PDF de totais: {totais_res['periodo']}")

                except Exception as exc:
                    st.error(f'Erro ao gerar Excel: {exc}')
                    import traceback
                    st.code(traceback.format_exc())


# =============================================================================
# TAB 2 — On Track por Cliente
# =============================================================================
with tab_ontrack:
    st.header('📊 On Track por Cliente')

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
        _COR = {'🟢': '#2D6A4F', '🟡': '#B8860B', '🔴': '#C00000', '—': '#888'}
        cor_status = _COR.get(g_em, '#888')
        cor_dif    = '#2D6A4F' if tot_dif >= 0 else '#C00000'

        # ── Cards de resumo ───────────────────────────────────────────────
        st.markdown(f"""
        <div style="display:grid; grid-template-columns:repeat(6,1fr); gap:10px; margin-bottom:14px;">
          <div style="background:#f8f9fa; border-left:4px solid #2D6A4F; border-radius:8px; padding:12px 10px;">
            <div style="font-size:10px; color:#666; font-weight:700; letter-spacing:.05em;">META MENSAL</div>
            <div style="font-size:16px; font-weight:700; color:#1B4332; margin-top:4px;">{_brl(tot_meta)}</div>
          </div>
          <div style="background:#f8f9fa; border-left:4px solid #4472C4; border-radius:8px; padding:12px 10px;">
            <div style="font-size:10px; color:#666; font-weight:700; letter-spacing:.05em;">FATURAMENTO</div>
            <div style="font-size:16px; font-weight:700; color:#1F4E79; margin-top:4px;">{_brl(tot_fat)}</div>
          </div>
          <div style="background:#f8f9fa; border-left:4px solid {cor_status}; border-radius:8px; padding:12px 10px;">
            <div style="font-size:10px; color:#666; font-weight:700; letter-spacing:.05em;">% ATINGIDO</div>
            <div style="font-size:16px; font-weight:700; color:{cor_status}; margin-top:4px;">{tot_pct*100:.1f}% {g_em}</div>
          </div>
          <div style="background:#f8f9fa; border-left:4px solid #C00000; border-radius:8px; padding:12px 10px;">
            <div style="font-size:10px; color:#666; font-weight:700; letter-spacing:.05em;">VALOR RESTANTE</div>
            <div style="font-size:16px; font-weight:700; color:#C00000; margin-top:4px;">{_brl(tot_rest)}</div>
          </div>
          <div style="background:#f8f9fa; border-left:4px solid #375623; border-radius:8px; padding:12px 10px;">
            <div style="font-size:10px; color:#666; font-weight:700; letter-spacing:.05em;">PROJEÇÃO MÊS</div>
            <div style="font-size:16px; font-weight:700; color:#375623; margin-top:4px;">{_brl(tot_proj)}</div>
          </div>
          <div style="background:#f8f9fa; border-left:4px solid {cor_dif}; border-radius:8px; padding:12px 10px;">
            <div style="font-size:10px; color:#666; font-weight:700; letter-spacing:.05em;">DIFERENÇA PROJ.</div>
            <div style="font-size:16px; font-weight:700; color:{cor_dif}; margin-top:4px;">{'▲' if tot_dif >= 0 else '▼'} {_brl(abs(tot_dif))}</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        # Barra de progresso geral com marcador de ritmo esperado
        prog_w  = min(tot_pct, 1.0) * 100
        exp_w   = elapsed_pct * 100
        cor_bar = cor_status
        st.markdown(f"""
        <div style="margin-bottom:16px;">
          <div style="font-size:11px; color:#666; margin-bottom:4px;">
            Progresso da Meta — Dia {days_elapsed} de {days_in_month} ({elapsed_pct*100:.0f}% do mês)
          </div>
          <div style="background:#e0e0e0; border-radius:6px; height:20px; position:relative;">
            <div style="background:{cor_bar}; width:{prog_w:.1f}%; height:20px; border-radius:6px;
                        display:flex; align-items:center; justify-content:flex-end; padding-right:6px;">
              <span style="color:white; font-weight:700; font-size:11px;">{prog_w:.1f}%</span>
            </div>
            <div style="position:absolute; top:0; left:{exp_w:.1f}%; width:2px; height:20px;
                        background:#333; opacity:0.4;" title="Ritmo esperado"></div>
          </div>
          <div style="font-size:10px; color:#999; margin-top:2px;">▲ Ritmo esperado: {exp_w:.0f}%  |  Dia {days_elapsed}/{days_in_month}  |  {days_remaining} dias restantes</div>
        </div>
        """, unsafe_allow_html=True)

        st.divider()

        # ── Comparativo (componente central comparativo.py) ────────────────
        st.subheader('📊 Comparativo')
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
            st.subheader('🏆 Ranking de Vendedores')

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
                tend_cor = '#2D6A4F' if ratio >= 1.0 else ('#B8860B' if ratio >= 0.85 else '#C00000')
                rank_rows.append({'v': v, 'fat': d['fat'], 'meta': d['meta'],
                                  'mc_rs': d['mc_rs'], 'pct': pct,
                                  'em': em, 'lb': lb, 'ratio': ratio,
                                  'tend': tend, 'tend_cor': tend_cor})
            rank_rows.sort(key=lambda x: x['pct'], reverse=True)

            cards = '<div style="display:grid; grid-template-columns:repeat(auto-fill,minmax(270px,1fr)); gap:12px; margin-bottom:16px;">'
            medals = ['🥇', '🥈', '🥉']
            for i, rv in enumerate(rank_rows):
                medal  = medals[i] if i < 3 else f'#{i+1}'
                cor    = _COR.get(rv['em'], '#888')
                prog   = min(rv['pct'], 1.0) * 100
                exp_p  = elapsed_pct * 100
                cards += f"""
                <div style="background:white; border:1px solid #e0e0e0; border-radius:10px; padding:14px;
                            box-shadow:0 1px 4px rgba(0,0,0,.07);">
                  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <span style="font-size:15px; font-weight:700;">{medal} {rv['v']}</span>
                    <span style="background:{cor}; color:white; padding:2px 9px; border-radius:12px;
                                 font-size:10px; font-weight:700;">{rv['em']} {rv['lb']}</span>
                  </div>
                  <div style="font-size:12px; color:#444; margin-bottom:6px;">
                    Fat: <b>{_brl(rv['fat'])}</b>&nbsp;&nbsp;/&nbsp;&nbsp;Meta: {_brl(rv['meta'])}
                  </div>
                  <div style="background:#e0e0e0; border-radius:4px; height:12px; position:relative; margin-bottom:4px;">
                    <div style="background:{cor}; width:{prog:.1f}%; height:12px; border-radius:4px;"></div>
                    <div style="position:absolute; top:0; left:{exp_p:.1f}%; width:2px; height:12px; background:#333; opacity:.4;"></div>
                  </div>
                  <div style="display:flex; justify-content:space-between; font-size:11px; color:#666;">
                    <span>{rv['pct']*100:.1f}% atingido</span>
                    <span style="color:{rv['tend_cor']}; font-weight:700;">{rv['tend']}</span>
                  </div>
                </div>"""
            cards += '</div>'
            st.markdown(cards, unsafe_allow_html=True)
            st.divider()

        # ── Tabela detalhada ──────────────────────────────────────────────
        st.subheader(f'Detalhamento por Cliente — {len(rows)} cliente(s)')

        df_rows = []
        for r in rows:
            df_rows.append({
                'Vendedor':      r['Vendedor'],
                'Cliente':       r['Cliente'],
                'Meta':          _brl(r['_meta']) if r['_tem_meta'] else '—',
                'Faturamento':   _brl(r['_fat']),
                '% Atingido':    f"{r['_pct_atg']*100:.1f}%" if r['_tem_meta'] else '—',
                'Restante':      _brl(r['_restante']) if r['_tem_meta'] else '—',
                'Méd. Diária':   _brl(r['_avg']),
                'Méd. Nec/dia':  _brl(r['_media_nec']) if r['_tem_meta'] else '—',
                'Projeção':      _brl(r['_projecao']),
                'Dif. Projeção': ('+' if r['_diferenca'] >= 0 else '') + _brl(r['_diferenca']) if r['_tem_meta'] else '—',
                'MC R$':         _brl(r['_mc_rs']),
                'MC %':          f"{r['_mc_pct']:.1f}%",
                'Status':        f"{r['_em']} {r['_lb']}",
            })

        st.dataframe(pd.DataFrame(df_rows), use_container_width=True, hide_index=True)

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
            )
        with c_pub:
            if st.button('📤 Publicar On Track para Gerência', use_container_width=True):
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
                    '_pct_atg': pct_atg or 0, 'Faturamento': _brl(fat),
                    'Volume (cx)': f'{vol:,.0f}', 'Margem (MC R$)': _brl(mc_rs),
                    'Rentabilidade': f'{mc_pct:.1f}%',
                    'Comparativo': comparativo.formatar_variacao(comp),
                    '% Atingido': f'{pct_atg*100:.1f}%' if pct_atg is not None else '—',
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
        st.dataframe(df_top50, use_container_width=True, hide_index=True)

        csv_top50 = df_top50.to_csv(index=False, sep=';').encode('utf-8-sig')
        st.download_button(
            '⬇️ Exportar Top 50 (CSV)', data=csv_top50,
            file_name=f'top50_clientes_{lbl_atual.replace("/","")}.csv',
            mime='text/csv',
        )


# =============================================================================
# TAB 4 — Clientes por Vendedor
# =============================================================================
with tab_por_vend:
    st.header('👤 Clientes por Vendedor')

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
                'Cliente': cliente, 'Faturamento': _brl(fat), 'Volume (cx)': f'{vol:,.0f}',
                'Margem (MC R$)': _brl(mc_rs), 'Rentabilidade': f'{mc_pct:.1f}%',
                'Comparativo': comparativo.formatar_variacao(comp),
                'Participação no vendedor': f'{participacao*100:.1f}%',
                'On Track': status_txt,
            })

        linhas_pv.sort(key=lambda r: r['_fat'], reverse=True)

        st.caption(f'{len(linhas_pv)} cliente(s) de **{vendedor_sel_pv}** em {lbl_atual} — '
                   f'faturamento total: {_brl(fat_total_vendedor)}')

        df_pv = pd.DataFrame(linhas_pv)[[
            'Cliente', 'Faturamento', 'Volume (cx)', 'Margem (MC R$)', 'Rentabilidade',
            'Comparativo', 'Participação no vendedor', 'On Track',
        ]]
        st.dataframe(df_pv, use_container_width=True, hide_index=True)

        csv_pv = df_pv.to_csv(index=False, sep=';').encode('utf-8-sig')
        st.download_button(
            f'⬇️ Exportar clientes de {vendedor_sel_pv} (CSV)', data=csv_pv,
            file_name=f'clientes_{vendedor_sel_pv}_{lbl_atual.replace("/","")}.csv',
            mime='text/csv',
        )
