"""Pagina Streamlit - Relatorio Vendedor-Cliente OTHIL.

Workflow:
  (1) Inicio do mes (uma vez):
      Secao 'Configurar Historico':
      - Sobe PDF Vendedor-Cliente de jul./ANO-1 e jun./ANO
      - Clica 'Salvar Historico' -> baixa historico_JUL2026.json

  (2) Toda sexta-feira:
      Secao 'Gerar Relatorio Semanal':
      - Sobe historico_JUL2026.json (salvo acima)
      - Sobe PDF Vendedor-Cliente atual (clientes do periodo)
      - Sobe PDF Lucratividade por Vendedor (totais reais)
      - Clica 'Gerar Excel' -> baixa o .xlsx
"""
from datetime import datetime

import streamlit as st

from xlsx_vendedor_cliente import salvar_historico, carregar_historico, gerar_xlsx
from parsers_vendedor import parse_totais_vendedor

st.set_page_config(page_title='Vendedor-Cliente OTHIL', layout='wide')
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

# =============================================================================
# SECAO 1 - Configurar Historico (uma vez por mes)
# =============================================================================
with st.expander(f'(1) Configurar Historico - faca uma vez no inicio de {MESES[mes-1]}',
                 expanded=False):
    st.info(
        'Envie os PDFs Lucratividade por Vendedor-Cliente dos dois periodos '
        'anteriores. O app vai parsear e gerar um arquivo JSON que substitui '
        f'os PDFs nas gerações semanais. Guarde o arquivo {fname_json}.'
    )
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
        if st.button('Salvar Historico', type='secondary'):
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

# =============================================================================
# SECAO 2 - Gerar Relatorio Semanal
# =============================================================================
st.subheader(f'(2) Gerar Relatorio Semanal - {lbl_atual}')
st.caption(
    'Envie o JSON de historico (gerado acima uma vez por mes) e os '
    'dois PDFs da semana. O Excel gerado tem uma aba por vendedor + GERAL.'
)

col_j, col_a, col_b = st.columns(3)
with col_j:
    hist_file = st.file_uploader(
        f'Historico ({fname_json})',
        type='json', key='hist_json')
with col_a:
    pdf_clientes = st.file_uploader(
        'PDF Vendedor-Cliente (clientes do periodo atual)',
        type='pdf', key='pdf_clientes')
with col_b:
    pdf_totais = st.file_uploader(
        'PDF Lucratividade por Vendedor (totais reais)',
        type='pdf', key='pdf_totais')

meta_file = st.file_uploader(
    'Planilha de metas anterior (opcional - importa coluna META)',
    type=['xlsx', 'xls'], key='meta_xlsx')

faltando = []
if hist_file is None:
    faltando.append('Historico JSON')
if pdf_clientes is None:
    faltando.append('PDF Vendedor-Cliente')
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
                meta_bytes  = meta_file.read() if meta_file else None

                xlsx_bytes = gerar_xlsx(
                    historico=historico,
                    pdf_clientes_atual=pdf_clientes,
                    totais_atual=totais_dict,
                    meta_xlsx_bytes=meta_bytes,
                    ref_date=ref_date,
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
