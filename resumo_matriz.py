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
    """Renderiza a matriz Produto × Vendedor (Vendido/Meta/%), agrupada por
    prioridade com linha de SUBTOTAL por grupo -- igual ao PDF Resumo Geral."""
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
            row = {'Produto': r['produto'], 'Qtde': f"{r.get('estoque_total', 0):.0f}"}
            p_meta = 0.0
            p_vend = 0.0
            linhas_por_vend = {l['vendedor']: l for l in r.get('linhas', [])}
            for v in vendedores:
                l = linhas_por_vend.get(v)
                if l:
                    row[v] = f"{l['vendido']:.0f}/{l['meta']:.0f} ({l['atingido']*100:.0f}%)"
                    p_meta += l['meta']
                    p_vend += l['vendido']
                else:
                    row[v] = '-'
            row['TOTAL'] = f"{p_vend:.0f}/{p_meta:.0f} ({p_vend/p_meta*100:.0f}%)" if p_meta else '—'
            rows_m.append(row)

        # Linha de subtotal
        sub = {'Produto': 'SUBTOTAL', 'Qtde': f"{sum(r.get('estoque_total', 0) for r in grupo):.0f}"}
        for v in vendedores:
            sv = sum(l['vendido'] for r in grupo for l in r.get('linhas', []) if l['vendedor'] == v)
            sm = sum(l['meta']    for r in grupo for l in r.get('linhas', []) if l['vendedor'] == v)
            sub[v] = f"{sv:.0f}/{sm:.0f} ({sv/sm*100:.0f}%)" if sm else '—'
        gv = sum(l['vendido'] for r in grupo for l in r.get('linhas', []))
        gm = sum(l['meta']    for r in grupo for l in r.get('linhas', []))
        sub['TOTAL'] = f"{gv:.0f}/{gm:.0f} ({gv/gm*100:.0f}%)" if gm else '—'
        rows_m.append(sub)

        st.dataframe(pd.DataFrame(rows_m), use_container_width=True, hide_index=True)

    # Total Geral -- soma de todos os grupos de prioridade juntos
    tot = {'Produto': 'TOTAL GERAL', 'Qtde': f"{sum(r.get('estoque_total', 0) for r in resultados):.0f}"}
    for v in vendedores:
        tv = sum(l['vendido'] for r in resultados for l in r.get('linhas', []) if l['vendedor'] == v)
        tm = sum(l['meta']    for r in resultados for l in r.get('linhas', []) if l['vendedor'] == v)
        tot[v] = f"{tv:.0f}/{tm:.0f} ({tv/tm*100:.0f}%)" if tm else '—'
    gv_all = sum(l['vendido'] for r in resultados for l in r.get('linhas', []))
    gm_all = sum(l['meta']    for r in resultados for l in r.get('linhas', []))
    tot['TOTAL'] = f"{gv_all:.0f}/{gm_all:.0f} ({gv_all/gm_all*100:.0f}%)" if gm_all else '—'
    st.dataframe(pd.DataFrame([tot]), use_container_width=True, hide_index=True)
