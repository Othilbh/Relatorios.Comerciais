"""Pagina Streamlit — Recorrencia de Vendas OTHIL.

Upload do PDF 'Lucratividade por Vendedor-Cliente no Previsao' (Mercatus)
cobrindo o periodo desejado (dia, quinzena, mes, etc.) e geracao do Excel
Recorrencia_<Periodo>_OTHIL.xlsx com a matriz cliente x produto.
"""
import datetime
import io
import tempfile

import streamlit as st

from parsers_diario import parse_relatorio_diario
from xlsx_recorrencia import gerar_xlsx

try:
    from gsheets_upload import upload_xlsx_as_sheet
    _GSHEETS_OK = True
except Exception:
    _GSHEETS_OK = False

st.set_page_config(page_title='OTHIL — Recorrencia de Vendas', layout='wide')

st.title('OTHIL — Recorrencia de Vendas')
st.caption(
    'Gera a matriz cliente x produto em caixas (CX) a partir do PDF '
    '"Lucratividade por Vendedor-Cliente no Previsao" (Mercatus). '
    'Verde = comprou | Laranja = disponivel no mix mas nao comprou.'
)

st.header('1. Upload do PDF')
pdf_file = st.file_uploader(
    'Lucratividade por Vendedor-Cliente no Previsao — qualquer periodo (PDF, Mercatus)',
    type='pdf', key='pdf_recorrencia',
)

if pdf_file is not None:
    with st.spinner('Lendo e validando o PDF...'):
        try:
            resultado = parse_relatorio_diario(pdf_file)
        except Exception as e:
            st.error(f'Nao foi possivel ler o PDF: {e}')
            resultado = None

    if resultado is not None:
        st.session_state['resultado_rec'] = resultado

if 'resultado_rec' in st.session_state:
    resultado = st.session_state['resultado_rec']
    itens = resultado['itens']

    if resultado['divergencias']:
        st.warning(
            f"Atencao: {len(resultado['divergencias'])} divergencia(s) entre os "
            "itens extraidos e os Totais oficiais do PDF (tolerancia R$ 1). "
            "O arquivo e gerado mesmo assim, mas pode estar incompleto."
        )
        with st.expander('Ver divergencias'):
            st.dataframe(resultado['divergencias'], use_container_width=True, hide_index=True)
    else:
        st.success('PDF lido com sucesso — todos os totais conferidos.')

    # Resumo
    periodo = resultado.get('periodo') or '-'
    emissao = resultado.get('data_emissao') or '-'
    itens_validos = [it for it in itens if it.get('vendedor') != 'Luca - Vendedor']
    fat_total = sum(it['faturamento'] for it in itens_validos)
    cx_total  = sum(it['qtd']         for it in itens_validos)
    clientes  = len(set(it['cliente_codigo'] for it in itens_validos))
    vendedores = len(set(
        (it.get('vendedor') or it.get('vendedor_raw', ''))
        for it in itens_validos
    ))

    st.header('2. Resumo do periodo')
    st.caption(f'Periodo: {periodo}  |  Emissao: {emissao}  |  {len(itens_validos)} itens (excluindo Luca - Vendedor)')
    c1, c2, c3, c4 = st.columns(4)
    c1.metric('Faturamento', f'R$ {fat_total:,.2f}')
    c2.metric('Total CX', f'{cx_total:,.3f}')
    c3.metric('Clientes', clientes)
    c4.metric('Vendedores', vendedores)

    st.header('3. Gerar Recorrencia')

    if st.button('Gerar Recorrencia Excel', type='primary', key='btn_rec'):
        with st.spinner('Montando a matriz...'):
            with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
                periodo_fn = gerar_xlsx(resultado, tmp.name)
                xlsx_bytes = open(tmp.name, 'rb').read()
        nome = f'Recorrencia_{periodo_fn}_OTHIL.xlsx'
        st.session_state['rec_bytes'] = xlsx_bytes
        st.session_state['rec_nome']  = nome

    if 'rec_bytes' in st.session_state:
        nome = st.session_state['rec_nome']

        st.download_button(
            label=f'Baixar {nome}',
            data=st.session_state['rec_bytes'],
            file_name=nome,
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

        if _GSHEETS_OK and 'gcp_service_account' in st.secrets:
            if st.button('Abrir no Google Sheets', key='btn_gsheets_rec'):
                with st.spinner('Enviando para o Google Sheets...'):
                    try:
                        link = upload_xlsx_as_sheet(
                            st.session_state['rec_bytes'],
                            nome.replace('.xlsx', ''),
                        )
                        st.session_state['rec_gsheets_link'] = link
                    except Exception as e:
                        st.error(f'Erro ao enviar para o Google Sheets: {e}')

        if 'rec_gsheets_link' in st.session_state:
            st.success('Planilha criada no Google Sheets!')
            st.markdown(f'[Abrir planilha]({st.session_state["rec_gsheets_link"]})')

else:
    st.info('Envie o PDF do periodo desejado para comecar.')
