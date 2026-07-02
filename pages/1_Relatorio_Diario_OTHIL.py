"""Página Streamlit do módulo Relatório Diário de Vendas OTHIL.

Faz upload do PDF diário "Lucratividade por Vendedor-Cliente no Previsão"
(Mercatus), faz o parsing/validação (parsers_diario.py) e gera os dois
arquivos de saída do dia:
  - Excel: Relatorio_Diario_DD-MM-AAAA_OTHIL.xlsx (xlsx_diario.py)
  - Dashboard HTML: dashboard_gerencial_othil_DDMMAAAA.html (dashboard_diario.py)
"""
import datetime
import io
import json
import os
import tempfile

import streamlit as st

_GERENCIA_DIR = os.path.join(os.path.dirname(__file__), '..', 'gerencia_data')


def _salvar_dashboard_gerencia(html_text: str, periodo: str, emissao: str):
    try:
        os.makedirs(_GERENCIA_DIR, exist_ok=True)
        # Usa a data de emissão do PDF como nome do arquivo (formato YYYY-MM-DD)
        try:
            d, m, a = emissao.split('/')
            slug = f'{a}-{m}-{d}'
        except Exception:
            slug = datetime.datetime.now().strftime('%Y-%m-%d')
        html_path = os.path.join(_GERENCIA_DIR, f'dashboard_{slug}.html')
        meta_path = os.path.join(_GERENCIA_DIR, f'dashboard_{slug}.json')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_text)
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump({
                'slug': slug,
                'periodo': periodo,
                'emissao': emissao,
                'gerado_em': datetime.datetime.now().isoformat(),
            }, f, ensure_ascii=False)
    except Exception:
        pass

from parsers_diario import parse_relatorio_diario, ValidationError
from xlsx_diario import gerar_xlsx
from dashboard_diario import gerar_dashboard
try:
    from gsheets_upload import upload_xlsx_as_sheet
    _GSHEETS_OK = True
except Exception:
    _GSHEETS_OK = False


st.title('OTHIL — Relatórios Comerciais')
st.caption('Módulo: Relatório Diário de Vendas (Lucratividade por Vendedor-Cliente)')

st.header('1. Upload do PDF do dia')
pdf_file = st.file_uploader(
    'Lucratividade por Vendedor-Cliente no Previsão (PDF, Mercatus) — obrigatório',
    type='pdf', key='pdf_diario',
)

if pdf_file is not None:
    with st.spinner('Lendo e validando o PDF...'):
        try:
            resultado = parse_relatorio_diario(pdf_file)
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
    custo_real = custo / 1.15 if custo else 0.0
    mc_rs  = faturamento - custo_real
    mc_pct = mc_rs / custo_real * 100 if custo_real else 0.0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric('Faturamento', f'R$ {faturamento:,.2f}')
    c2.metric('MC R$', f'R$ {mc_rs:,.2f}')
    c3.metric('MC %', f'{mc_pct:.2f}%')
    c4.metric('Caixas', f'{caixas:,.3f}')
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
            if _GSHEETS_OK and 'gcp_service_account' in st.secrets:
                if st.button('🔗 Abrir no Google Sheets', key='btn_gsheets'):
                    with st.spinner('Enviando para o Google Sheets...'):
                        try:
                            link = upload_xlsx_as_sheet(
                                st.session_state['xlsx_bytes'],
                                nome.replace('.xlsx', ''),
                            )
                            st.session_state['gsheets_link'] = link
                        except Exception as e:
                            st.error(f'Erro ao enviar para o Google Sheets: {e}')
            if 'gsheets_link' in st.session_state:
                st.success('Planilha criada no Google Sheets!')
                st.markdown(f'[📄 Abrir planilha]({st.session_state["gsheets_link"]})')

    with col_html:
        if st.button('📈 Gerar Dashboard HTML', type='primary', key='btn_html'):
            with st.spinner('Gerando dashboard...'):
                with tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w', encoding='utf-8') as tmp:
                    pass
                gerar_dashboard(resultado, tmp.name)
                html_text = open(tmp.name, 'r', encoding='utf-8').read()
            st.session_state['html_text'] = html_text
            st.session_state['html_nome'] = f'dashboard_gerencial_othil_{data_fmt_html}.html'
            _salvar_dashboard_gerencia(
                html_text,
                resultado.get('periodo') or '-',
                resultado.get('data_emissao') or '-',
            )
        if 'html_text' in st.session_state:
            st.download_button(
                '⬇️ Baixar ' + st.session_state['html_nome'],
                data=st.session_state['html_text'].encode('utf-8'),
                file_name=st.session_state['html_nome'],
                mime='text/html',
            )

    if 'html_text' in st.session_state:
        with st.expander('Pré-visualizar dashboard'):
            st.components.v1.html(st.session_state['html_text'], height=1400, scrolling=True)
else:
    st.info('Envie o PDF do dia para começar.')
