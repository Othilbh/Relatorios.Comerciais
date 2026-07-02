"""Pagina Streamlit — Recorrencia de Vendas OTHIL.

Upload do PDF 'Lucratividade por Vendedor-Cliente no Previsao' (Mercatus)
cobrindo o periodo desejado (dia, quinzena, mes, etc.) e geracao do Excel
Recorrencia_<Periodo>_OTHIL.xlsx com a matriz cliente x produto.
"""
import datetime
import io
import json
import os
import tempfile
from collections import defaultdict

import streamlit as st

from parsers_diario import parse_relatorio_diario
from xlsx_recorrencia import gerar_xlsx

try:
    from gsheets_upload import upload_xlsx_as_sheet
    _GSHEETS_OK = True
except Exception:
    _GSHEETS_OK = False

_GERENCIA_DIR = os.path.join(os.path.dirname(__file__), '..', 'gerencia_data')


def _salvar_gerencia(data: dict):
    try:
        os.makedirs(_GERENCIA_DIR, exist_ok=True)
        path = os.path.join(_GERENCIA_DIR, 'recorrencia_latest.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _agregar_clientes(itens):
    """Agrega itens por cliente, calcula faturamento, CX, MC R$ e MC %."""
    agg = defaultdict(lambda: {'faturamento': 0.0, 'qtd': 0.0, 'custo': 0.0})
    for it in itens:
        nome = it['cliente_nome'] or '(sem nome)'
        agg[nome]['faturamento'] += it['faturamento']
        agg[nome]['qtd'] += it['qtd']
        agg[nome]['custo'] += it['custo_total']

    rows = []
    for nome, v in sorted(agg.items(), key=lambda x: x[1]['faturamento'], reverse=True):
        mc_rs = v['faturamento'] - v['custo']
        mc_pct = (mc_rs / v['custo'] * 100) if v['custo'] != 0 else 0.0
        rows.append({
            'Cliente': nome,
            'Faturamento R$': round(v['faturamento'], 2),
            'Caixas': round(v['qtd'], 3),
            'MC R$': round(mc_rs, 2),
            'MC %': round(mc_pct, 2),
        })
    return rows


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
    itens_validos = [it for it in itens if it.get('vendedor') != 'Luca']
    fat_total = sum(it['faturamento'] for it in itens_validos)
    cx_total  = sum(it['qtd']         for it in itens_validos)
    custo_total = sum(it['custo_total'] for it in itens_validos)
    mc_rs_total = fat_total - custo_total
    mc_pct_total = (mc_rs_total / custo_total * 100) if custo_total else 0.0
    clientes  = len(set(it['cliente_codigo'] for it in itens_validos))
    vendedores = len(set(
        (it.get('vendedor') or it.get('vendedor_raw', ''))
        for it in itens_validos
    ))

    st.header('2. Resumo do periodo')
    st.caption(f'Periodo: {periodo}  |  Emissao: {emissao}  |  {len(itens_validos)} itens (excluindo Luca)')
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric('Faturamento', f'R$ {fat_total:,.2f}')
    c2.metric('MC R$', f'R$ {mc_rs_total:,.2f}')
    c3.metric('MC %', f'{mc_pct_total:.2f}%')
    c4.metric('Total CX', f'{cx_total:,.3f}')
    c5.metric('Clientes', clientes)
    c6.metric('Vendedores', vendedores)

    # ------------------------------------------------------------------
    # Dashboard de clientes
    # ------------------------------------------------------------------
    st.header('3. Dashboard de Clientes')

    rows = _agregar_clientes(itens_validos)

    if rows:
        import pandas as pd

        df = pd.DataFrame(rows)

        # Salva para a página de Gerência
        _salvar_gerencia({
            'periodo': periodo,
            'emissao': emissao,
            'gerado_em': datetime.datetime.now().isoformat(),
            'clientes': rows,
            'totais': {
                'faturamento': round(fat_total, 2),
                'caixas': round(cx_total, 3),
                'mc_rs': round(mc_rs_total, 2),
                'mc_pct': round(mc_pct_total, 2),
                'n_clientes': clientes,
                'n_vendedores': vendedores,
            }
        })

        # Gráfico — top 30 por faturamento (evita gráfico ilegível)
        top30 = df.head(30).set_index('Cliente')[['Faturamento R$']]
        st.subheader('Top 30 clientes — Faturamento (R$)')
        st.bar_chart(top30, color='#2D6A4F')

        # Tabela completa
        st.subheader(f'Todos os clientes ({len(df)})')

        # Formatação visual
        styled = df.style.format({
            'Faturamento R$': 'R$ {:,.2f}',
            'Caixas': '{:,.3f}',
            'MC R$': 'R$ {:,.2f}',
            'MC %': '{:.2f}%',
        }).background_gradient(
            subset=['Faturamento R$'], cmap='Greens'
        ).background_gradient(
            subset=['MC %'], cmap='RdYlGn', vmin=-30, vmax=30
        )

        st.dataframe(styled, use_container_width=True, hide_index=True)
    else:
        st.info('Nenhum cliente encontrado nos dados.')

    # ------------------------------------------------------------------
    # Gerar Excel
    # ------------------------------------------------------------------
    st.header('4. Gerar Recorrencia Excel')

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
