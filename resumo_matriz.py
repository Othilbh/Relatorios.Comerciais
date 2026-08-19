"""Matriz Produto × Vendedor agrupada por prioridade -- a mesma visão do
'Resumo Geral' (PDF gerado em pdfgen.generate_resumo_geral). Extraído para
cá para ter UMA SÓ implementação usada tanto na prévia de Metas Semanais
(antes de fechar a semana) quanto na tela de Fechamentos Semanais da
Gerência (depois de fechada) -- duas cópias divergentes foi exatamente o
tipo de bug que já mordeu esse app antes (ver calc.map_vendedor), então
aqui fica centralizado.

`resultados` é a lista no formato de calc.compute_metas() / salvo em
'produtos' pelo fechamento: [{'produto', 'estoque_total', 'prioridade',
'linhas': [{'vendedor', 'meta', 'vendido', 'atingido', ...}, ...]}, ...]
"""
import pandas as pd
import streamlit as st

_PRIO_KEYS = ['🚨 Grande Urgência', '🔥 Alta Prioridade', 'Normal']


def _vendedores_de(resultados: list) -> list:
    """Lista de vendedores na ordem em que aparecem no primeiro produto
    (mesma ordem configurada em Percentuais dos Vendedores); usa a união
    de todos os produtos como fallback caso o primeiro esteja incompleto."""
    for r in resultados:
        linhas = r.get('linhas') or []
        if linhas:
            return [l['vendedor'] for l in linhas]
    return sorted({l['vendedor'] for r in resultados for l in r.get('linhas', [])})


def render_matriz_produto_vendedor(resultados: list, titulo: str = 'Resumo Geral — Matriz Produto × Vendedor'):
    """Renderiza a matriz Produto × Vendedor, agrupada por prioridade com
    linha de SUBTOTAL por grupo -- igual ao PDF Resumo Geral.

    Cada célula de vendedor mostra SÓ o vendido (pedido explícito da
    Ingrid: célula com vendido/meta/% junto ficava poluída). A meta de cada
    linha/subtotal fica na coluna 'Qtde', o vendido total na coluna
    'Vendido Total' e o percentual na coluna '% Atingido' -- SEM combinar
    vendido/meta no mesmo campo (ex.: "275/618"), também por pedido
    explícito da Ingrid. 'Qtde' sempre usa a meta REAL do produto
    ('estoque_total'), nunca a soma das metas individuais dos vendedores
    (ver correção de meta geral)."""
    if not resultados:
        st.info('Sem dados para montar o Resumo Geral.')
        return

    vendedores = _vendedores_de(resultados)
    if not vendedores:
        st.info('Sem dados para montar o Resumo Geral.')
        return

    st.markdown(f'**{titulo}**')

    grupos_prio: dict = {}
    for r in resultados:
        prio = r.get('prioridade', 'Normal')
        grupos_prio.setdefault(prio, []).append(r)

    for prio_key in _PRIO_KEYS:
        grupo = grupos_prio.get(prio_key)
        if not grupo:
            continue
        prio_label = prio_key.replace('🚨 ', '').replace('🔥 ', '')
        st.markdown(f'*{prio_label}*')

        rows_m = []
        for r in grupo:
            # Meta do produto (coluna TOTAL da linha) = 'estoque_total' real,
            # igual à coluna 'Qtde' -- NUNCA a soma das metas individuais dos
            # vendedores (essa soma é inflada pelo arredondamento pra cima
            # de cada meta individual, e antes ficava divergente da 'Qtde'
            # na mesma linha, o que não faz sentido: as duas são a mesma
            # meta do produto).
            p_meta = r.get('estoque_total', 0)
            row = {'Produto': r['produto'], 'Qtde': f"{p_meta:.0f}"}
            p_vend = 0.0
            linhas_por_vend = {l['vendedor']: l for l in r.get('linhas', [])}
            for v in vendedores:
                l = linhas_por_vend.get(v)
                if l:
                    row[v] = f"{l['vendido']:.0f}"
                    p_vend += l['vendido']
                else:
                    row[v] = '-'
            row['Vendido Total'] = f"{p_vend:.0f}"
            row['% Atingido'] = f"{p_vend/p_meta*100:.0f}%" if p_meta else '—'
            rows_m.append(row)

        # Linha de subtotal -- mesma regra: a meta do grupo (coluna TOTAL)
        # usa a soma do 'estoque_total' real dos produtos do grupo (igual à
        # 'Qtde' do subtotal), não a soma das metas individuais. Já a meta
        # de CADA vendedor (sm) continua sendo a soma das metas dele mesmo
        # nos produtos do grupo -- isso é o total individual dele, correto.
        gm = sum(r.get('estoque_total', 0) for r in grupo)
        sub = {'Produto': 'SUBTOTAL', 'Qtde': f"{gm:.0f}"}
        for v in vendedores:
            sv = sum(l['vendido'] for r in grupo for l in r.get('linhas', []) if l['vendedor'] == v)
            sub[v] = f"{sv:.0f}"
        gv = sum(l['vendido'] for r in grupo for l in r.get('linhas', []))
        sub['Vendido Total'] = f"{gv:.0f}"
        sub['% Atingido'] = f"{gv/gm*100:.0f}%" if gm else '—'
        rows_m.append(sub)

        st.dataframe(pd.DataFrame(rows_m), use_container_width=True, hide_index=True)

    # Total Geral -- soma de todos os grupos de prioridade juntos. Mesma
    # regra: meta geral = soma do 'estoque_total' real de todos os produtos,
    # não a soma das metas individuais dos vendedores.
    gm_all = sum(r.get('estoque_total', 0) for r in resultados)
    tot = {'Produto': 'TOTAL GERAL', 'Qtde': f"{gm_all:.0f}"}
    for v in vendedores:
        tv = sum(l['vendido'] for r in resultados for l in r.get('linhas', []) if l['vendedor'] == v)
        tot[v] = f"{tv:.0f}"
    gv_all = sum(l['vendido'] for r in resultados for l in r.get('linhas', []))
    tot['Vendido Total'] = f"{gv_all:.0f}"
    tot['% Atingido'] = f"{gv_all/gm_all*100:.0f}%" if gm_all else '—'
    st.dataframe(pd.DataFrame([tot]), use_container_width=True, hide_index=True)
