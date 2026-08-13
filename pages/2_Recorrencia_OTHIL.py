"""Pagina Streamlit — Recorrencia de Vendas OTHIL.

Upload do PDF 'Lucratividade por Vendedor-Cliente no Previsao' (Mercatus)
cobrindo o periodo desejado (dia, quinzena, mes, etc.) e geracao do Excel
Recorrencia_<Periodo>_OTHIL.xlsx com a matriz cliente x produto.
"""
import datetime
import io
import json
import os
import re
import tempfile
from collections import defaultdict

import streamlit as st
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from parsers_diario import parse_relatorio_diario
from xlsx_recorrencia import gerar_xlsx
import comparativo
import data_store as ds

try:
    from gsheets_upload import upload_xlsx_as_sheet
    _GSHEETS_OK = True
except Exception:
    _GSHEETS_OK = False

_GERENCIA_DIR = os.path.join(os.path.dirname(__file__), '..', 'gerencia_data')
MODULO = 'recorrencia'
TIPO_PERIODO = 'livre'  # período de duração variável (dia, quinzena, mês, etc.) — não é um dos 5 tipos padrão


def _slug_recorrencia(periodo_str: str, emissao_str: str) -> str:
    """Slug estável a partir do texto do período (mesmo período reenviado =
    mesma chave = nova versão no histórico, não uma entrada nova)."""
    base = (periodo_str or '').strip() or (emissao_str or '').strip()
    slug = re.sub(r'[^0-9A-Za-z]+', '-', base).strip('-')
    return slug or datetime.date.today().strftime('%Y-%m-%d')


def _salvar_gerencia(data: dict, periodo_str: str = '', emissao_str: str = '', usuario: str = None):
    try:
        os.makedirs(_GERENCIA_DIR, exist_ok=True)
        path = os.path.join(_GERENCIA_DIR, 'recorrencia_latest.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    try:
        slug = _slug_recorrencia(periodo_str, emissao_str)
        ds.save_record(
            modulo=MODULO, tipo_periodo=TIPO_PERIODO, periodo_ref=slug,
            valores=data, usuario=usuario,
        )
    except Exception:
        pass


def _listar_recorrencias():
    """Histórico de publicações de Recorrência, mais recente primeiro
    (ordenado pelo horário real de gravação, já que o período é de texto
    livre e não segue uma ordenação cronológica lexical confiável)."""
    itens = []
    try:
        for slug in ds.list_periodos(MODULO, TIPO_PERIODO):
            registro = ds.load_current(MODULO, TIPO_PERIODO, slug)
            if registro:
                itens.append((slug, registro['valores'], registro.get('atualizado_em', '')))
    except Exception:
        pass
    itens.sort(key=lambda t: t[2], reverse=True)
    return itens


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

with st.expander('👤 Seu nome (fica registrado no histórico de publicações)'):
    st.session_state['usuario_nome'] = st.text_input(
        'Seu nome', value=st.session_state.get('usuario_nome', 'Ingrid'), key='usuario_nome_input_rec',
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

        # Salva para a página de Gerência (histórico versionado — sobrevive a
        # reinício do app; período repetido = nova versão, não sobrescreve)
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
        }, periodo_str=periodo, emissao_str=emissao, usuario=st.session_state.get('usuario_nome'))

        # ---- Comparativo vs período anterior publicado ---------------------
        _hist_rec = _listar_recorrencias()
        _slug_atual = _slug_recorrencia(periodo, emissao)
        _anteriores = [(s, v) for s, v, _ in _hist_rec if s != _slug_atual]
        if _anteriores:
            st.subheader('📊 Comparativo vs período anterior publicado')
            _slug_ant, _val_ant = _anteriores[0]
            _tot_ant = _val_ant.get('totais', {})
            cc1, cc2, cc3, cc4 = st.columns(4)
            for _col, _label, _atual_v, _chave in [
                (cc1, 'Faturamento', fat_total, 'faturamento'),
                (cc2, 'MC R$', mc_rs_total, 'mc_rs'),
                (cc3, 'Total CX', cx_total, 'caixas'),
                (cc4, 'Clientes', clientes, 'n_clientes'),
            ]:
                _comp = comparativo.calcular(_atual_v, _tot_ant.get(_chave))
                _fmt = (lambda x: f'R$ {x:,.2f}') if _chave in ('faturamento', 'mc_rs') else \
                       (lambda x: f'{x:,.3f}') if _chave == 'caixas' else (lambda x: f'{x:,.0f}')
                _col.metric(_label, _fmt(_atual_v), delta=comparativo.formatar_variacao(_comp))
            st.caption(f'Base de comparação: {_val_ant.get("periodo","-")} '
                       f'(emissão {_val_ant.get("emissao","-")})')

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
        })

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

    # ------------------------------------------------------------------
    # Histórico de Recorrências salvas
    # ------------------------------------------------------------------
    st.divider()
    st.header('5. Histórico de Recorrências Salvas')

    _hist_todos = _listar_recorrencias()
    if not _hist_todos:
        st.info('Nenhuma recorrência salva ainda.')
    else:
        _labels_h = [f"{v.get('periodo','-')}  —  emissão {v.get('emissao','-')}  "
                     f"({(ts or '')[:16].replace('T',' ')})" for _, v, ts in _hist_todos]
        _escolha_h = st.selectbox(f'{len(_hist_todos)} publicação(ões):', _labels_h,
                                   index=0, key='sel_hist_rec')
        _idx_h = _labels_h.index(_escolha_h)
        _slug_h, _val_h, _ts_h = _hist_todos[_idx_h]
        _tot_h = _val_h.get('totais', {})
        hc1, hc2, hc3, hc4, hc5 = st.columns(5)
        hc1.metric('Faturamento', f"R$ {_tot_h.get('faturamento', 0):,.2f}")
        hc2.metric('MC R$', f"R$ {_tot_h.get('mc_rs', 0):,.2f}")
        hc3.metric('MC %', f"{_tot_h.get('mc_pct', 0):.2f}%")
        hc4.metric('Total CX', f"{_tot_h.get('caixas', 0):,.3f}")
        hc5.metric('Clientes', _tot_h.get('n_clientes', '-'))

        _clientes_h = _val_h.get('clientes', [])
        if _clientes_h:
            import pandas as pd
            df_h = pd.DataFrame(_clientes_h)
            styled_h = df_h.style.format({
                'Faturamento R$': 'R$ {:,.2f}',
                'Caixas': '{:,.3f}',
                'MC R$': 'R$ {:,.2f}',
                'MC %': '{:.2f}%',
            })
            st.dataframe(styled_h, use_container_width=True, hide_index=True)

        # Versões anteriores desse mesmo período (se o período foi reenviado)
        try:
            _versoes = ds.load_history(MODULO, TIPO_PERIODO, _slug_h)
        except Exception:
            _versoes = []
        if _versoes:
            with st.expander(f'🕓 {len(_versoes)} versão(ões) anterior(es) deste período'):
                for _v in reversed(_versoes):
                    _quando = (_v.get('atualizado_em') or '')[:16].replace('T', ' ')
                    _quem = _v.get('usuario', 'não identificado')
                    _t = _v.get('valores', {}).get('totais', {})
                    st.caption(f"v{_v.get('versao','?')} — {_quando} — por {_quem} — "
                               f"Faturamento R$ {_t.get('faturamento', 0):,.2f}")

else:
    st.info('Envie o PDF do periodo desejado para comecar.')
