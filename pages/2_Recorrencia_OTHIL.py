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
import periodo

try:
    from gsheets_upload import upload_xlsx_as_sheet
    _GSHEETS_OK = True
except Exception:
    _GSHEETS_OK = False

_GERENCIA_DIR = os.path.join(os.path.dirname(__file__), '..', 'gerencia_data')
MODULO = 'recorrencia'
TIPO_PERIODO_LEGADO = 'livre'  # período de texto livre usado antes desta versão -- mantido só
                               # pra continuar enxergando o histórico salvo daquele jeito


def _salvar_gerencia(data: dict, tipo_periodo: str, periodo_ref: str, usuario: str = None):
    """Salva com a MESMA chave estruturada (tipo_periodo, periodo_ref) usada
    em Rentabilidade/Produtos -- reenviar o PDF do mesmo período gera nova
    versão no histórico (não sobrescreve nem duplica)."""
    try:
        os.makedirs(_GERENCIA_DIR, exist_ok=True)
        path = os.path.join(_GERENCIA_DIR, 'recorrencia_latest.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    try:
        ds.save_record(
            modulo=MODULO, tipo_periodo=tipo_periodo, periodo_ref=periodo_ref,
            valores=data, usuario=usuario,
        )
    except Exception:
        pass


def _listar_recorrencias(tipo_periodo: str):
    """Histórico de publicações de Recorrência para um tipo de período
    (semanal/mensal/trimestral/semestral/anual), mais recente primeiro."""
    itens = []
    try:
        for ref in ds.list_periodos(MODULO, tipo_periodo):
            registro = ds.load_current(MODULO, tipo_periodo, ref)
            if registro:
                itens.append((ref, registro['valores'], registro.get('atualizado_em', '')))
    except Exception:
        pass
    itens.sort(key=lambda t: t[0], reverse=True)
    return itens


def _listar_recorrencias_legado():
    """Publicações salvas ANTES desta versão (chave de texto livre extraída
    do PDF, sem tipo de período estruturado) -- mantidas visíveis aqui pra
    não perder o histórico já salvo, mas não recebem novas entradas."""
    itens = []
    try:
        for slug in ds.list_periodos(MODULO, TIPO_PERIODO_LEGADO):
            registro = ds.load_current(MODULO, TIPO_PERIODO_LEGADO, slug)
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

st.session_state.setdefault('usuario_nome', 'Ingrid')

st.header('1. Período de Referência')
st.caption(
    'A que período este PDF pertence? Isso é o que organiza o histórico na '
    'Gerência (igual em Rentabilidade e Produtos) -- o texto de período que '
    'vem dentro do próprio PDF continua sendo mostrado como informação, mas '
    'quem decide onde fica salvo é a seleção abaixo.'
)
c_tipo, c_data = st.columns(2)
with c_tipo:
    tipo_periodo_rec = st.selectbox(
        'Tipo de período', periodo.TIPOS_PERIODO, format_func=periodo.rotulo_tipo,
        index=0, key='rec_tipo_periodo',
    )
with c_data:
    data_ref_rec = st.date_input(
        'Data dentro do período coberto pelo PDF', value=datetime.date.today(),
        format='DD/MM/YYYY', key='rec_data_ref',
    )
periodo_ref_rec = periodo.periodo_ref(tipo_periodo_rec, data_ref_rec)
st.caption(f'Vai ser salvo como: **{periodo.rotulo(tipo_periodo_rec, periodo_ref_rec)}**')

st.header('2. Upload do PDF')
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

    # Resumo (texto de período como extraído do próprio PDF -- informativo;
    # quem decide onde fica salvo é a seleção da seção 1, em periodo_ref_rec)
    periodo_pdf_texto = resultado.get('periodo') or '-'
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

    st.header('3. Resumo do periodo')
    st.caption(f'Periodo (texto do PDF): {periodo_pdf_texto}  |  Emissao: {emissao}  |  '
               f'{len(itens_validos)} itens (excluindo Luca)')
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
    st.header('4. Dashboard de Clientes')

    rows = _agregar_clientes(itens_validos)

    if rows:
        import pandas as pd

        df = pd.DataFrame(rows)

        # Salva para a página de Gerência (histórico versionado — sobrevive a
        # reinício do app; período repetido = nova versão, não sobrescreve)
        _salvar_gerencia({
            'periodo': periodo_pdf_texto,
            'emissao': emissao,
            'tipo_periodo': tipo_periodo_rec,
            'periodo_ref': periodo_ref_rec,
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
        }, tipo_periodo_rec, periodo_ref_rec, usuario=st.session_state.get('usuario_nome', 'Ingrid'))
        st.caption(f'✅ Salvo na Gerência como **{periodo.rotulo(tipo_periodo_rec, periodo_ref_rec)}** '
                   f'({periodo.rotulo_tipo(tipo_periodo_rec)}).')

        # ---- Comparativo vs período anterior publicado (mesmo tipo) --------
        _ref_ant = periodo.periodo_anterior(tipo_periodo_rec, periodo_ref_rec)
        _registro_ant = None
        try:
            _registro_ant = ds.load_current(MODULO, tipo_periodo_rec, _ref_ant)
        except Exception:
            _registro_ant = None
        if _registro_ant:
            st.subheader('📊 Comparativo vs período anterior publicado')
            _val_ant = _registro_ant['valores']
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
            st.caption(f'Base de comparação: {periodo.rotulo(tipo_periodo_rec, _ref_ant)} '
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
    st.header('5. Gerar Recorrencia Excel')

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
    st.header('6. Histórico de Recorrências Salvas')

    _tipo_h = st.selectbox(
        'Tipo de período', periodo.TIPOS_PERIODO, format_func=periodo.rotulo_tipo,
        index=0, key='rec_tipo_hist',
    )
    _hist_todos = _listar_recorrencias(_tipo_h)
    if not _hist_todos:
        st.info(f'Nenhuma recorrência salva ainda como {periodo.rotulo_tipo(_tipo_h)}.')
    else:
        _labels_h = [f"{periodo.rotulo(_tipo_h, ref)}  —  {v.get('periodo','-')}  "
                     f"({(ts or '')[:16].replace('T',' ')})" for ref, v, ts in _hist_todos]
        _escolha_h = st.selectbox(f'{len(_hist_todos)} publicação(ões):', _labels_h,
                                   index=0, key='sel_hist_rec')
        _idx_h = _labels_h.index(_escolha_h)
        _ref_h, _val_h, _ts_h = _hist_todos[_idx_h]
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
            _versoes = ds.load_history(MODULO, _tipo_h, _ref_h)
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

    _hist_legado = _listar_recorrencias_legado()
    if _hist_legado:
        with st.expander(f'📜 Histórico antigo ({len(_hist_legado)} publicação(ões) salvas '
                          'antes desta atualização, por texto de período livre)'):
            st.caption(
                'Estas publicações foram salvas antes de existir a seleção de tipo de '
                'período acima. Ficam aqui só para consulta -- novas publicações não '
                'são mais salvas neste formato.'
            )
            for _slug_l, _val_l, _ts_l in _hist_legado:
                _tot_l = _val_l.get('totais', {})
                _quando_l = (_ts_l or '')[:16].replace('T', ' ')
                st.caption(
                    f"{_val_l.get('periodo','-')} — emissão {_val_l.get('emissao','-')} "
                    f"({_quando_l}) — Faturamento R$ {_tot_l.get('faturamento', 0):,.2f}"
                )

else:
    st.info('Envie o PDF do periodo desejado para comecar.')
