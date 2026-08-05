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
from datetime import datetime

import streamlit as st
import pandas as pd

from xlsx_vendedor_cliente import (
    salvar_historico, carregar_historico, gerar_xlsx, ler_xlsx_historico,
    parse_e_agregar,
)
from parsers_vendedor import parse_totais_vendedor

st.title('Relatorio Vendedor-Cliente')

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

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_rel, tab_ontrack = st.tabs(['📋 Relatório Semanal', '📊 On Track por Cliente'])

# =============================================================================
# TAB 1 — Relatório Semanal (conteúdo original)
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

    col_j, col_a, col_b = st.columns(3)
    with col_j:
        hist_file = st.file_uploader(
            f'Historico ({fname_json})',
            type='json', key='hist_json')
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
    if hist_file is None:
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
                    historico   = carregar_historico(hist_file.read())
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

                    # Salva dados de clientes para a aba On Track
                    try:
                        clientes_data = parse_e_agregar(
                            [io.BytesIO(b) for b in clientes_bytes]
                        )
                        st.session_state['clientes_on_track'] = clientes_data
                        st.session_state['totais_on_track']   = totais_dict
                    except Exception:
                        pass

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

    clientes_data = st.session_state.get('clientes_on_track')
    totais_dict   = st.session_state.get('totais_on_track', {})

    if not clientes_data:
        st.info(
            'Gere o relatório semanal na aba **📋 Relatório Semanal** primeiro. '
            'Os dados de cliente aparecerão aqui automaticamente.'
        )
    else:
        # ── Filtros ──────────────────────────────────────────────────────
        col_busca, col_vend, col_sort = st.columns([3, 2, 2])
        with col_busca:
            busca = st.text_input('🔍 Pesquisar cliente', placeholder='Digite parte do nome...', key='ot_busca')
        with col_vend:
            vendedores_disp = ['Todos'] + sorted(clientes_data.keys())
            vend_filtro = st.selectbox('Filtrar por vendedor', vendedores_disp, key='ot_vend')
        with col_sort:
            sort_cli = st.selectbox(
                'Ordenar por',
                ['Maior faturamento', 'Maior MC R$', 'Maior MC %', 'Alfabético'],
                key='ot_sort',
            )

        st.divider()

        # ── Montar tabela de clientes ─────────────────────────────────────
        rows = []
        for vendedor, clientes in clientes_data.items():
            if vend_filtro != 'Todos' and vendedor != vend_filtro:
                continue
            for cliente, dados in clientes.items():
                if busca and busca.lower() not in cliente.lower():
                    continue
                rows.append({
                    'Vendedor':   vendedor,
                    'Cliente':    cliente,
                    'CX':         dados.get('vol', 0),
                    'Fat R$':     dados.get('fat', 0),
                    'MC R$':      dados.get('mc_rs', 0),
                    'MC %':       dados.get('mc_pct', 0),
                    'Margem %':   dados.get('resultado_real', 0),
                })

        if not rows:
            st.info('Nenhum cliente encontrado com os filtros selecionados.')
        else:
            # Sort
            if sort_cli == 'Maior faturamento':
                rows.sort(key=lambda r: r['Fat R$'], reverse=True)
            elif sort_cli == 'Maior MC R$':
                rows.sort(key=lambda r: r['MC R$'], reverse=True)
            elif sort_cli == 'Maior MC %':
                rows.sort(key=lambda r: r['MC %'], reverse=True)
            else:
                rows.sort(key=lambda r: r['Cliente'])

            # KPIs rápidos do filtro atual
            tot_fat = sum(r['Fat R$'] for r in rows)
            tot_mc  = sum(r['MC R$']  for r in rows)
            tot_cx  = sum(r['CX']     for r in rows)
            mc_pct_medio = (tot_mc / (tot_fat - tot_mc) * 100) if (tot_fat - tot_mc) else 0

            k1, k2, k3, k4 = st.columns(4)
            k1.metric('Clientes', len(rows))
            k2.metric('Faturamento', f'R$ {tot_fat:,.2f}')
            k3.metric('MC R$', f'R$ {tot_mc:,.2f}')
            k4.metric('Volume', f'{tot_cx:,.0f} cx')

            st.divider()

            # Tabela formatada
            df_cli = pd.DataFrame(rows)
            df_cli_fmt = df_cli.copy()
            df_cli_fmt['CX']       = df_cli_fmt['CX'].map(lambda x: f'{x:,.0f}')
            df_cli_fmt['Fat R$']   = df_cli_fmt['Fat R$'].map(lambda x: f'R$ {x:,.2f}')
            df_cli_fmt['MC R$']    = df_cli_fmt['MC R$'].map(lambda x: f'R$ {x:,.2f}')
            df_cli_fmt['MC %']     = df_cli_fmt['MC %'].map(lambda x: f'{x:.2f}%')
            df_cli_fmt['Margem %'] = df_cli_fmt['Margem %'].map(lambda x: f'{x:.2f}%')

            st.dataframe(df_cli_fmt, use_container_width=True, hide_index=True)

            # Download CSV
            csv = df_cli.to_csv(index=False).encode('utf-8')
            st.download_button(
                '⬇️ Exportar CSV',
                data=csv,
                file_name=f'clientes_on_track_{lbl_atual.replace("/","")}.csv',
                mime='text/csv',
            )
