"""Página Streamlit — Relatório Diário, Semanal e Mensal OTHIL.

Três abas: Diário / Semanal / Mensal.
Todas usam o mesmo parse + gerar_dashboard — só muda o período do PDF.
"""
import datetime
import json
import os
import re
import tempfile

import streamlit as st
import streamlit.components.v1 as components

from parsers_diario import parse_relatorio_diario, ValidationError
from xlsx_diario import gerar_xlsx
from dashboard_diario import gerar_dashboard

try:
    from gsheets_upload import upload_xlsx_as_sheet
    _GSHEETS_OK = True
except Exception:
    _GSHEETS_OK = False

_GERENCIA_DIR = os.path.join(os.path.dirname(__file__), '..', 'gerencia_data')


# ── Helpers de storage ───────────────────────────────────────────────────────

def _dir_tipo(tipo):
    d = os.path.join(_GERENCIA_DIR, tipo)
    os.makedirs(d, exist_ok=True)
    return d


def _salvar_dashboard(html_text, tipo, slug, periodo, emissao):
    try:
        d = _dir_tipo(tipo)
        with open(os.path.join(d, f'{slug}.html'), 'w', encoding='utf-8') as f:
            f.write(html_text)
        with open(os.path.join(d, f'{slug}.json'), 'w', encoding='utf-8') as f:
            json.dump({
                'slug': slug, 'tipo': tipo,
                'periodo': periodo, 'emissao': emissao,
                'gerado_em': datetime.datetime.now().isoformat(),
            }, f, ensure_ascii=False)
    except Exception:
        pass


def _listar_dashboards(tipo):
    """Retorna lista de (slug, meta) ordenada do mais recente para o mais antigo."""
    d = _dir_tipo(tipo)
    items = []
    for fname in os.listdir(d):
        if fname.endswith('.json'):
            try:
                with open(os.path.join(d, fname), 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                slug = meta.get('slug') or fname.replace('.json', '')
                if os.path.exists(os.path.join(d, f'{slug}.html')):
                    items.append((slug, meta))
            except Exception:
                pass
    items.sort(key=lambda x: x[0], reverse=True)
    return items


def _slug_diario(resultado):
    emissao = resultado.get('data_emissao') or ''
    try:
        d, m, a = emissao.split('/')
        return f'{a}-{m}-{d}'
    except Exception:
        return datetime.date.today().strftime('%Y-%m-%d')


def _slug_periodo(resultado, tipo):
    """Gera slug baseado no início do período: semana ISO ou mês."""
    periodo = resultado.get('periodo') or resultado.get('data_emissao') or ''
    m = re.search(r'(\d{2})/(\d{2})/(\d{4})', periodo)
    if m:
        day, mon, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        dt = datetime.date(year, mon, day)
        if tipo == 'semanal':
            iso = dt.isocalendar()
            return f'{iso[0]}-W{iso[1]:02d}'
        else:  # mensal
            return f'{year}-{mon:02d}'
    if tipo == 'semanal':
        return datetime.date.today().strftime('%Y-W%V')
    return datetime.date.today().strftime('%Y-%m')


def _label_slug(slug, tipo):
    """Transforma slug em label legível."""
    try:
        if tipo == 'semanal':
            year, week = slug.split('-W')
            return f'Semana {int(week):02d} / {year}'
        else:  # mensal
            year, mon = slug.split('-')
            meses = ['Jan','Fev','Mar','Abr','Mai','Jun',
                     'Jul','Ago','Set','Out','Nov','Dez']
            return f'{meses[int(mon)-1]} / {year}'
    except Exception:
        return slug


# ── Bloco reutilizável: upload + gerar + histórico ────────────────────────────

def _render_tab(tipo, label_tipo):
    """Renderiza uma aba de dashboard (semanal ou mensal)."""
    key = tipo  # prefixo para session_state e widget keys

    st.header(f'1. Upload do PDF {label_tipo}')
    st.caption(
        f'Envie o PDF "Lucratividade por Vendedor-Cliente no Previsão" '
        f'cobrindo o período {label_tipo.lower()} desejado.'
    )
    pdf_file = st.file_uploader(
        f'PDF {label_tipo} (Mercatus)',
        type='pdf', key=f'pdf_{key}',
    )

    if pdf_file is not None:
        with st.spinner(f'Lendo PDF {label_tipo.lower()}...'):
            try:
                resultado = parse_relatorio_diario(pdf_file)
                st.session_state[f'resultado_{key}'] = resultado
            except Exception as e:
                st.error(f'Não foi possível ler o PDF: {e}')

    if f'resultado_{key}' in st.session_state:
        resultado = st.session_state[f'resultado_{key}']
        itens = resultado['itens']

        if resultado.get('divergencias'):
            st.warning(
                f"⚠️ {len(resultado['divergencias'])} divergência(s) detectadas. "
                "O dashboard é gerado mesmo assim."
            )
        else:
            st.success('PDF lido com sucesso.')

        periodo  = resultado.get('periodo') or '-'
        emissao  = resultado.get('data_emissao') or '-'
        fat_total  = sum(it['faturamento'] for it in itens)
        custo_tot  = sum(it['custo_total']  for it in itens)
        caixas_tot = sum(it['qtd']          for it in itens)
        clientes   = len(set(it['cliente_codigo'] for it in itens))
        mc_rs      = fat_total - custo_tot
        mc_pct     = mc_rs / custo_tot * 100 if custo_tot else 0.0

        st.caption(f'Período: {periodo}  |  Emissão: {emissao}')
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric('Faturamento', f'R$ {fat_total:,.2f}')
        c2.metric('MC R$',       f'R$ {mc_rs:,.2f}')
        c3.metric('MC %',        f'{mc_pct:.2f}%')
        c4.metric('Caixas',      f'{caixas_tot:,.3f}')
        c5.metric('Clientes',    clientes)

        st.header(f'2. Gerar Dashboard {label_tipo}')
        if st.button(f'📈 Gerar Dashboard {label_tipo}', type='primary', key=f'btn_dash_{key}'):
            with st.spinner('Gerando dashboard...'):
                with tempfile.NamedTemporaryFile(suffix='.html', delete=False,
                                                 mode='w', encoding='utf-8') as tmp:
                    pass
                gerar_dashboard(resultado, tmp.name, tipo=tipo)
                html_text = open(tmp.name, 'r', encoding='utf-8').read()
            slug = _slug_periodo(resultado, tipo)
            _salvar_dashboard(html_text, tipo, slug, periodo, emissao)
            st.session_state[f'html_{key}']   = html_text
            st.session_state[f'slug_{key}']   = slug
            st.success(f'Dashboard salvo — {_label_slug(slug, tipo)}')

        if f'html_{key}' in st.session_state:
            slug = st.session_state[f'slug_{key}']
            st.download_button(
                f'⬇️ Baixar dashboard {_label_slug(slug, tipo)}',
                data=st.session_state[f'html_{key}'].encode('utf-8'),
                file_name=f'dashboard_{tipo}_{slug}_OTHIL.html',
                mime='text/html',
                key=f'dl_{key}',
            )
            with st.expander('Pré-visualizar dashboard'):
                components.html(st.session_state[f'html_{key}'], height=1400, scrolling=True)

    # ── Histórico ────────────────────────────────────────────────────────────
    st.divider()
    st.header(f'3. Histórico {label_tipo}')

    dashboards = _listar_dashboards(tipo)
    if dashboards:
        # Navegação prev / selectbox / next
        slugs  = [s for s, _ in dashboards]
        labels = [_label_slug(s, tipo) + f"  ({m.get('periodo','-')})"
                  for s, m in dashboards]

        idx_key = f'_hist_idx_{key}'
        if idx_key not in st.session_state:
            st.session_state[idx_key] = 0

        col_prev, col_sel, col_next = st.columns([1, 6, 1])
        with col_prev:
            st.write('')
            if st.button('◀', key=f'prev_{key}', help='Período anterior'):
                st.session_state[idx_key] = min(
                    st.session_state[idx_key] + 1, len(slugs) - 1)
        with col_next:
            st.write('')
            if st.button('▶', key=f'next_{key}', help='Próximo período'):
                st.session_state[idx_key] = max(
                    st.session_state[idx_key] - 1, 0)
        with col_sel:
            escolha = st.selectbox(
                f'{len(dashboards)} período(s) salvo(s):',
                labels,
                index=st.session_state[idx_key],
                key=f'sel_{key}',
            )
            st.session_state[idx_key] = labels.index(escolha)

        idx     = st.session_state[idx_key]
        slug_h  = slugs[idx]
        meta_h  = dashboards[idx][1]
        gerado  = meta_h.get('gerado_em', '')[:16].replace('T', ' ')
        st.caption(f'Período: {meta_h.get("periodo","-")}  |  Gerado em: {gerado}')

        html_path = os.path.join(_dir_tipo(tipo), f'{slug_h}.html')
        with open(html_path, 'r', encoding='utf-8') as f:
            html_hist = f.read()

        components.html(html_hist, height=1400, scrolling=True)
        st.download_button(
            f'⬇️ Baixar {_label_slug(slug_h, tipo)}',
            data=html_hist.encode('utf-8'),
            file_name=f'dashboard_{tipo}_{slug_h}_OTHIL.html',
            mime='text/html',
            key=f'dl_hist_{key}',
        )
    else:
        st.info(f'Nenhum dashboard {label_tipo.lower()} salvo ainda. '
                f'Gere o primeiro acima.')


# ── Página principal ─────────────────────────────────────────────────────────

st.title('OTHIL — Dashboard de Vendas')

tab_d, tab_s, tab_m = st.tabs(['📅 Diário', '📆 Semanal', '🗓️ Mensal'])

# ── ABA DIÁRIO ───────────────────────────────────────────────────────────────
with tab_d:
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
        mc_rs  = faturamento - custo
        mc_pct = mc_rs / custo * 100 if custo else 0.0

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

        with col_html:
            if st.button('📈 Gerar Dashboard HTML', type='primary', key='btn_html'):
                with st.spinner('Gerando dashboard...'):
                    with tempfile.NamedTemporaryFile(suffix='.html', delete=False,
                                                     mode='w', encoding='utf-8') as tmp:
                        pass
                    gerar_dashboard(resultado, tmp.name, tipo='diario')
                    html_text = open(tmp.name, 'r', encoding='utf-8').read()
                slug_d = _slug_diario(resultado)
                _salvar_dashboard(
                    html_text, 'diario', slug_d,
                    resultado.get('periodo') or '-',
                    resultado.get('data_emissao') or '-',
                )
                st.session_state['html_text'] = html_text
                st.session_state['html_nome'] = f'dashboard_gerencial_othil_{data_fmt_html}.html'
            if 'html_text' in st.session_state:
                st.download_button(
                    '⬇️ Baixar ' + st.session_state['html_nome'],
                    data=st.session_state['html_text'].encode('utf-8'),
                    file_name=st.session_state['html_nome'],
                    mime='text/html',
                )

        if 'html_text' in st.session_state:
            with st.expander('Pré-visualizar dashboard'):
                components.html(st.session_state['html_text'], height=1400, scrolling=True)

        # Histórico diário
        st.divider()
        st.header('4. Histórico Diário')
        dashboards_d = _listar_dashboards('diario')
        if dashboards_d:
            opcoes = {
                f"{m.get('emissao', s)}  —  {m.get('periodo','-')}": s
                for s, m in dashboards_d
            }
            escolha = st.selectbox(
                f'{len(dashboards_d)} dashboard(s) diário(s) salvo(s):',
                list(opcoes.keys()),
                key='sel_hist_diario',
            )
            slug_sel = opcoes[escolha]
            meta_sel = next(m for ss, m in dashboards_d if ss == slug_sel)
            gerado = meta_sel.get('gerado_em', '')[:16].replace('T', ' ')
            st.caption(f'Gerado em: {gerado}')
            html_path = os.path.join(_dir_tipo('diario'), f'{slug_sel}.html')
            with open(html_path, 'r', encoding='utf-8') as f:
                html_hist = f.read()
            components.html(html_hist, height=1400, scrolling=True)
            st.download_button(
                f'⬇️ Baixar dashboard {slug_sel}',
                data=html_hist.encode('utf-8'),
                file_name=f'dashboard_diario_{slug_sel}_OTHIL.html',
                mime='text/html',
                key='dl_hist_diario',
            )
        else:
            st.info('Nenhum dashboard diário salvo ainda.')
    else:
        st.info('Envie o PDF do dia para começar.')

# ── ABA SEMANAL ──────────────────────────────────────────────────────────────
with tab_s:
    _render_tab('semanal', 'Semanal')

# ── ABA MENSAL ───────────────────────────────────────────────────────────────
with tab_m:
    _render_tab('mensal', 'Mensal')
