"""OTHIL — Relatórios Comerciais — Módulo Metas Semanais

App Streamlit: faz upload dos PDFs de Estoque Físico e de Lucratividade por
Vendedor, permite configurar os produtos da semana (nome + códigos/SKU) e os
percentuais de cada vendedor, calcula Meta/Vendido/Falta/% e gera os 3 PDFs
de saída (relatório por vendedor, dashboard e resumo geral).
"""
import json
import datetime
import streamlit as st

from parsers import parse_estoque, parse_vendas
from calc import compute_metas, VENDEDORES_PADRAO, parse_codigos_input, map_vendedor
from pdfgen import generate_relatorio_vendedor, generate_dashboard, generate_resumo_geral
import storage

CONFIG_PATH = 'config_semanal.json'

st.set_page_config(page_title='OTHIL — Metas Semanais', layout='wide')


# ---------------------------------------------------------------------------
# Persistência da configuração da semana (produtos + percentuais).
#
# O app roda no Streamlit Cloud, cujo disco é apagado a cada reinício —
# por isso um arquivo local sozinho NÃO basta (era esse o motivo de tudo
# salvo "ontem" desaparecer "hoje"). A configuração agora é salva também no
# próprio repositório do GitHub via storage.py (precisa de um GITHUB_TOKEN
# nos Secrets do Streamlit Cloud — ver instruções no topo de storage.py).
# Sem esse token, o app cai de volta no arquivo local (só persiste se o app
# rodar na sua própria máquina, sem reiniciar).
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    'produtos': [
        {'nome': 'Melão Gaia', 'codigos_texto': '3102006*', 'estoque': 0},
        {'nome': 'Goiaba', 'codigos_texto': '300200208,300200203', 'estoque': 0},
    ],
    'vendedor_pcts': dict(VENDEDORES_PADRAO),
}


def load_config():
    remote = storage.load_config_remote()
    if remote is not None:
        return remote
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg, show_feedback=True):
    ok, motivo = storage.save_config_remote(cfg)
    if show_feedback:
        if ok:
            st.success('Configuração salva — vai continuar disponível a semana toda.')
        else:
            st.warning(f'Não foi possível salvar de forma permanente: {motivo}')
    # Cópia local como cache de melhor esforço (útil rodando localmente; no
    # Streamlit Cloud é apagada no próximo reinício, por isso não é a fonte
    # principal de persistência).
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return ok


if 'config' not in st.session_state:
    st.session_state.config = load_config()

cfg = st.session_state.config

if not storage.is_configured():
    st.info(
        '⚠️ Persistência permanente ainda não configurada: a configuração desta '
        'semana só fica salva enquanto o app não reiniciar/dormir. Para manter os '
        'dados disponíveis a semana toda, configure o GITHUB_TOKEN nos Secrets do '
        'Streamlit Cloud (instruções no topo do arquivo storage.py).'
    )

st.title('OTHIL — Relatórios Comerciais')
st.caption('Módulo: Metas Semanais')

# ---------------------------------------------------------------------------
# 1) Upload dos PDFs de origem
# ---------------------------------------------------------------------------
st.header('1. Upload dos relatórios da semana')
col1, col2 = st.columns(2)
with col1:
    estoque_file = st.file_uploader('Estoque Físico (PDF) — opcional, usado só para detalhar '
                                     'o estoque completo no relatório individual de cada vendedor',
                                     type='pdf', key='estoque')
with col2:
    vendas_file = st.file_uploader('Lucratividade por Vendedor / Vendas Acumuladas (PDF) — obrigatório',
                                    type='pdf', key='vendas')

# ---------------------------------------------------------------------------
# 2) Configuração semanal: produtos (nome + códigos) e percentuais
# ---------------------------------------------------------------------------
st.header('2. Produtos da semana')
st.caption(
    'Os produtos e seus códigos variam toda semana. Para cada produto, digite '
    'a quantidade atual em estoque (a Meta é calculada a partir dela) e cole os '
    'códigos usados para identificar as vendas desse produto no relatório de '
    'vendas, separados por vírgula ou quebra de linha. Use um "*" no final de '
    'um código para casar por prefixo (ex.: "3102006*" casa com qualquer código '
    'que comece com 3102006). Sem "*", o código precisa ser exato.'
)

if st.button('➕ Adicionar produto'):
    cfg['produtos'].append({'nome': '', 'codigos_texto': '', 'estoque': 0})

remover_idx = None
for i, p in enumerate(cfg['produtos']):
    p.setdefault('estoque', 0)
    with st.expander(f"Produto {i+1}: {p['nome'] or '(sem nome)'}", expanded=True):
        c1, c2, c3, c4 = st.columns([3, 4, 2, 1])
        with c1:
            p['nome'] = st.text_input('Nome do produto', value=p['nome'], key=f'nome_{i}')
        with c2:
            p['codigos_texto'] = st.text_area('Códigos (vírgula ou linha; use * para prefixo) '
                                               '— usados só para identificar as vendas',
                                               value=p['codigos_texto'], key=f'cod_{i}', height=80)
        with c3:
            p['estoque'] = st.number_input('Estoque atual (cx)', min_value=0, step=1,
                                            value=int(p['estoque']), key=f'est_{i}')
        with c4:
            st.write('')
            st.write('')
            if st.button('🗑️', key=f'del_{i}'):
                remover_idx = i

if remover_idx is not None:
    cfg['produtos'].pop(remover_idx)
    st.rerun()

st.subheader('Percentuais de meta por vendedor (% sobre o estoque digitado acima)')
st.caption('Já vêm preenchidos com os percentuais fixos de cada vendedor — normalmente não precisa alterar.')
pct_cols = st.columns(len(cfg['vendedor_pcts']))
for col, (vend, pct) in zip(pct_cols, list(cfg['vendedor_pcts'].items())):
    with col:
        cfg['vendedor_pcts'][vend] = st.number_input(vend, min_value=0, max_value=200,
                                                       value=int(pct), key=f'pct_{vend}')

cb1, cb2, cb3 = st.columns(3)
with cb1:
    if st.button('💾 Salvar configuração desta semana'):
        save_config(cfg)
with cb2:
    st.download_button('⬇️ Exportar configuração (JSON)',
                        data=json.dumps(cfg, ensure_ascii=False, indent=2),
                        file_name=f"config_metas_{datetime.date.today().isoformat()}.json",
                        mime='application/json')
with cb3:
    up_cfg = st.file_uploader('⬆️ Importar configuração (JSON)', type='json', key='cfg_upload')
    if up_cfg is not None:
        st.session_state.config = json.load(up_cfg)
        save_config(st.session_state.config, show_feedback=False)
        st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# 3) Cálculo e relatórios
# ---------------------------------------------------------------------------
st.header('3. Calcular metas e gerar relatórios')

periodo = st.text_input('Período (ex.: 22/06/2026 a 26/06/2026)',
                         value=cfg.get('periodo', ''))
data_emissao = st.text_input('Data de emissão (ex.: 29/06/2026)',
                              value=datetime.date.today().strftime('%d/%m/%Y'))
cfg['periodo'] = periodo

if st.button('▶️ Calcular metas', type='primary'):
    if not vendas_file:
        st.error('Envie o PDF de Vendas (Lucratividade por Vendedor) antes de calcular.')
    elif not any(p['nome'].strip() for p in cfg['produtos']):
        st.error('Cadastre ao menos um produto com nome, estoque e códigos.')
    else:
        with st.spinner('Lendo PDFs e calculando metas...'):
            estoque_rows = []
            if estoque_file:
                try:
                    estoque_rows = parse_estoque(estoque_file)
                except Exception:
                    st.warning(
                        'Não foi possível ler o PDF de Estoque Físico enviado '
                        '(arquivo corrompido, protegido ou em formato inesperado). '
                        'A Meta não depende desse PDF, então o cálculo vai continuar '
                        'sem a lista detalhada de estoque no relatório individual.'
                    )
            try:
                vendas_rows = parse_vendas(vendas_file)
            except Exception:
                st.error(
                    'Não foi possível ler o PDF de Vendas/Lucratividade enviado. '
                    'Verifique se o arquivo não está corrompido ou protegido por '
                    'senha e tente enviar novamente.'
                )
                vendas_rows = None

        if vendas_rows is not None:
            produtos_config = [
                {'nome': p['nome'], 'codigos': parse_codigos_input(p['codigos_texto']),
                 'estoque': p.get('estoque', 0)}
                for p in cfg['produtos'] if p['nome'].strip()
            ]
            resultados = compute_metas(vendas_rows, produtos_config, cfg['vendedor_pcts'])
            st.session_state['estoque_rows'] = estoque_rows
            st.session_state['vendas_rows'] = vendas_rows
            st.session_state['resultados'] = resultados
            # Salva a configuração usada automaticamente, como rede de
            # segurança extra além do botão "Salvar configuração desta semana".
            save_config(cfg, show_feedback=False)
            st.success('Cálculo concluído.')

if 'resultados' in st.session_state:
    resultados = st.session_state['resultados']
    estoque_rows = st.session_state['estoque_rows']

    st.subheader('Resultado: Meta / Vendido / Falta por produto e vendedor')
    for r in resultados:
        st.markdown(f"**{r['produto']}** — Estoque atual: {r['estoque_total']:.0f} cx")
        st.dataframe(
            [{'Vendedor': l['vendedor'], '% Meta': f"{l['pct']:.0f}%",
              'Meta (cx)': l['meta'], 'Vendido (cx)': l['vendido'],
              'Falta (cx)': l['falta'], '% Atingido': f"{l['atingido']*100:.1f}%"}
             for l in r['linhas']],
            use_container_width=True, hide_index=True,
        )

    st.divider()
    st.subheader('Gerar PDFs')

    vendedores_disponiveis = list(cfg['vendedor_pcts'].keys())
    vendedor_sel = st.selectbox('Relatório individual do vendedor', vendedores_disponiveis)

    pcol1, pcol2, pcol3 = st.columns(3)
    with pcol1:
        pdf_bytes = generate_relatorio_vendedor(vendedor_sel, data_emissao,
                                                  estoque_rows, resultados)
        st.download_button(f'⬇️ Relatório — {vendedor_sel}', data=pdf_bytes,
                            file_name=f'Relatorio_{vendedor_sel}_{datetime.date.today().strftime("%d%m%Y")}.pdf',
                            mime='application/pdf')
    with pcol2:
        pdf_bytes = generate_dashboard(periodo, resultados, cfg['vendedor_pcts'])
        st.download_button('⬇️ Dashboard', data=pdf_bytes,
                            file_name=f'Dashboard_{datetime.date.today().strftime("%d%m%Y")}.pdf',
                            mime='application/pdf')
    with pcol3:
        pdf_bytes = generate_resumo_geral(periodo, data_emissao, resultados, cfg['vendedor_pcts'])
        st.download_button('⬇️ Resumo Geral', data=pdf_bytes,
                            file_name=f'Resumo_Geral_{datetime.date.today().strftime("%d%m%Y")}.pdf',
                            mime='application/pdf')

    with st.expander('Gerar relatórios de TODOS os vendedores de uma vez'):
        if st.button('Gerar todos os PDFs individuais'):
            for v in vendedores_disponiveis:
                pdf_bytes = generate_relatorio_vendedor(v, data_emissao, estoque_rows, resultados)
                st.download_button(f'⬇️ {v}', data=pdf_bytes,
                                    file_name=f'Relatorio_{v}_{datetime.date.today().strftime("%d%m%Y")}.pdf',
                                    mime='application/pdf', key=f'all_{v}')
