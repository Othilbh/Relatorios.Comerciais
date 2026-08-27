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
import acesso
import data_store as ds
import periodo

try:
    from gsheets_upload import upload_xlsx_as_sheet
    _GSHEETS_OK = True
except Exception:
    _GSHEETS_OK = False

def _fmt_num(v, casas=0):
    return f"{v:,.{casas}f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def _fmt_moeda(v):
    return f"R$ {_fmt_num(v, 2)}"


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
st.caption(f'O resultado deste PDF vai ser salvo como: '
           f'**{periodo.rotulo(tipo_periodo_rec, periodo_ref_rec)}** '
           f'(definido na seção 1 acima).')
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
    st.caption(f'Período de referência selecionado: '
               f'**{periodo.rotulo(tipo_periodo_rec, periodo_ref_rec)}**')
    st.caption(f'Periodo (texto do PDF): {periodo_pdf_texto}  |  Emissao: {emissao}  |  '
               f'{len(itens_validos)} itens (excluindo Luca)')
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric('Faturamento', _fmt_moeda(fat_total))
    c2.metric('MC R$', _fmt_moeda(mc_rs_total))
    c3.metric('MC %', f'{mc_pct_total:.2f}%')
    c4.metric('Total CX', _fmt_num(cx_total, 3))
    c5.metric('Clientes', clientes)
    c6.metric('Vendedores', vendedores)

    # ------------------------------------------------------------------
    # Gerar Excel (movido pra antes do Dashboard de Clientes em 27/08/2026:
    # a geração/download do Excel não depende do Dashboard abaixo, e
    # precisa continuar acessível mesmo com o redirecionamento pra
    # Gerência logo após o Dashboard -- ver acesso.redirecionar_pos_upload
    # mais abaixo).
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
    # Dashboard de clientes
    # ------------------------------------------------------------------
    st.header('5. Dashboard de Clientes')
    st.caption(f'Período de referência selecionado: '
               f'**{periodo.rotulo(tipo_periodo_rec, periodo_ref_rec)}**')

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
        st.success(f'✅ Salvo na Gerência como **{periodo.rotulo(tipo_periodo_rec, periodo_ref_rec)}** '
                   f'({periodo.rotulo_tipo(tipo_periodo_rec)}).')

        # Fluxo Upload -> Gerência (pedido da Ingrid, 27/08/2026): o
        # salvamento acima já aconteceu -- a partir daqui era só
        # comparativo/gráfico/tabela (Dashboard), então redireciona pra
        # Gerência em vez de mostrar isso aqui.
        acesso.redirecionar_pos_upload()
    else:
        st.info('Nenhum cliente encontrado nos dados.')

    # Rede de segurança pro caso raro de `rows` vir vazio acima (nada foi
    # salvo nesse caso, então o redirect acima não disparou) -- garante que
    # o Histórico abaixo, que é Dashboard, também fique só na Gerência.
    acesso.parar_se_upload()

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
        _labels_h = [periodo.rotulo(_tipo_h, ref) for ref, v, ts in _hist_todos]

        _idx_key_h = f'rec_hist_idx_{_tipo_h}'
        if _idx_key_h not in st.session_state:
            st.session_state[_idx_key_h] = 0

        col_prev_h, col_sel_h, col_next_h = st.columns([1, 6, 1], vertical_alignment='bottom')
        with col_prev_h:
            if st.button('◀', key=f'rec_hist_prev_{_tipo_h}', help='Período anterior'):
                st.session_state[_idx_key_h] = min(
                    st.session_state[_idx_key_h] + 1, len(_labels_h) - 1)
        with col_next_h:
            if st.button('▶', key=f'rec_hist_next_{_tipo_h}', help='Próximo período'):
                st.session_state[_idx_key_h] = max(st.session_state[_idx_key_h] - 1, 0)
        with col_sel_h:
            _escolha_h = st.selectbox(
                f'{len(_hist_todos)} publicação(ões):', _labels_h,
                index=min(st.session_state[_idx_key_h], len(_labels_h) - 1),
                key='sel_hist_rec',
            )
        _idx_h = _labels_h.index(_escolha_h)
        st.session_state[_idx_key_h] = _idx_h
        _ref_h, _val_h, _ts_h = _hist_todos[_idx_h]
        st.caption(f"Período (texto do PDF): {_val_h.get('periodo','-')}  |  "
                   f"Salvo em: {(_ts_h or '')[:16].replace('T',' ')}")
        _tot_h = _val_h.get('totais', {})
        hc1, hc2, hc3, hc4, hc5 = st.columns(5)
        hc1.metric('Faturamento', _fmt_moeda(_tot_h.get('faturamento', 0)))
        hc2.metric('MC R$', _fmt_moeda(_tot_h.get('mc_rs', 0)))
        hc3.metric('MC %', f"{_tot_h.get('mc_pct', 0):.2f}%")
        hc4.metric('Total CX', _fmt_num(_tot_h.get('caixas', 0), 3))
        hc5.metric('Clientes', _tot_h.get('n_clientes', '-'))

        _clientes_h = _val_h.get('clientes', [])
        if _clientes_h:
            import pandas as pd
            df_h = pd.DataFrame(_clientes_h)
            styled_h = df_h.style.format({
                'Faturamento R$': lambda v: _fmt_moeda(v),
                'Caixas': lambda v: _fmt_num(v, 3),
                'MC R$': lambda v: _fmt_moeda(v),
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
                               f"Faturamento {_fmt_moeda(_t.get('faturamento', 0))}")

    _hist_legado = _listar_recorrencias_legado()
    if _hist_legado:
        with st.expander(f'📜 Histórico antigo ({len(_hist_legado)} publicação(ões) salvas '
                          'antes desta atualização, por texto de período livre)'):
            st.caption('Publicações de antes desta atualização -- só para consulta.')
            for _slug_l, _val_l, _ts_l in _hist_legado:
                _tot_l = _val_l.get('totais', {})
                _quando_l = (_ts_l or '')[:16].replace('T', ' ')
                st.caption(
                    f"{_val_l.get('periodo','-')} — emissão {_val_l.get('emissao','-')} "
                    f"({_quando_l}) — Faturamento {_fmt_moeda(_tot_l.get('faturamento', 0))}"
                )

else:
    st.info('Envie o PDF do periodo desejado para comecar.')
