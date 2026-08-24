"""OTHIL — Cadastro de Produtos (% de despesa administrativa)

Tela pra Ingrid manter, sozinha e sem precisar de alteração de código, o
percentual de despesa administrativa POR PRODUTO usado pelo dashboard
"Margem Real" (aba dentro da Gerência) pra retirar essa despesa do Custo
do relatório e achar o custo real do produto:

    Custo real = Custo do relatório ÷ (1 + % do produto / 100)

Persistência central versionada (data_store.py — mesma usada em todo o
app): toda vez que o cadastro é salvo, fica registrado quem mudou o quê e
quando, e nada se perde (histórico completo disponível abaixo).
"""
import pandas as pd
import streamlit as st

import margem_produto as mp

st.title('📦 Cadastro de Produtos')
st.caption(
    'Percentual de despesa administrativa por produto, usado pelo dashboard '
    '**Margem Real** (aba dentro da Gerência) pra calcular o custo real: '
    '**Custo real = Custo do relatório ÷ (1 + % do produto)**.'
)

# ---------------------------------------------------------------------------
# Estado inicial: carrega o cadastro salvo (ou a semente, se nunca foi salvo)
# ---------------------------------------------------------------------------
if 'cadastro_df' not in st.session_state:
    tabela_inicial = mp.carregar_tabela()
    st.session_state['cadastro_df'] = pd.DataFrame(
        sorted(tabela_inicial.items()), columns=['Produto', 'Porcentagem']
    )

registro_atual = None
try:
    import data_store as ds
    registro_atual = ds.load_current(mp.MODULO, mp.TIPO_PERIODO, mp.PERIODO_REF)
except Exception:
    pass

if registro_atual:
    _gerado = (registro_atual.get('atualizado_em') or '')[:16].replace('T', ' ')
    _usuario = registro_atual.get('usuario') or 'não identificado'
    _versao = registro_atual.get('versao')
    st.caption(f'Última alteração salva: {_gerado} por {_usuario} (versão {_versao}).')
else:
    st.info(
        '⚠️ Este cadastro ainda não foi salvo na persistência central — está mostrando a '
        'tabela padrão (a última que estava fixa no código). Revise/ajuste abaixo e clique '
        'em **💾 Salvar cadastro** pra ele passar a valer de verdade.'
    )

st.divider()

# ---------------------------------------------------------------------------
# 1. Importar planilha (opcional) — atualiza/adiciona, nunca remove sozinho
# ---------------------------------------------------------------------------
st.header('1. Importar planilha (opcional)')
st.caption(
    'Envie uma planilha (.xls, .xlsx ou .csv) com uma coluna de nome do produto e uma '
    'coluna de porcentagem. A importação só ATUALIZA percentuais de produtos já existentes '
    'e ADICIONA produtos novos — nunca remove um produto sozinha, mesmo que ele não apareça '
    'na planilha enviada. Nada é salvo de verdade até você clicar em **💾 Salvar cadastro** '
    'na seção 2.'
)

up = st.file_uploader('Planilha de percentuais', type=['xls', 'xlsx', 'csv'], key='cad_upload')

if up is not None and st.session_state.get('_cad_upload_processado') != up.file_id:
    try:
        if up.name.lower().endswith('.csv'):
            df_novo = pd.read_csv(up)
        else:
            df_novo = pd.read_excel(up)

        cols_norm = {str(c).strip().upper(): c for c in df_novo.columns}
        col_prod = next((orig for norm, orig in cols_norm.items() if 'PRODUTO' in norm), None)
        col_pct = next(
            (orig for norm, orig in cols_norm.items()
             if 'PORCENT' in norm or 'PERCENT' in norm or norm.strip() == '%'),
            None,
        )
        if not col_prod or not col_pct:
            raise ValueError(
                'não encontrei colunas de produto e porcentagem nessa planilha — '
                'esperado algo como "PRODUTO" e "PORCENTAGEM" no cabeçalho'
            )

        df_novo = df_novo[[col_prod, col_pct]].copy()
        df_novo.columns = ['Produto', 'Porcentagem']
        df_novo['Produto'] = df_novo['Produto'].astype(str).str.strip()
        df_novo = df_novo[df_novo['Produto'] != '']
        df_novo['Porcentagem'] = pd.to_numeric(df_novo['Porcentagem'], errors='coerce')

        invalidas = df_novo[df_novo['Porcentagem'].isna()]
        if not invalidas.empty:
            st.warning(
                f"{len(invalidas)} linha(s) com porcentagem não numérica foram ignoradas: "
                + ', '.join(invalidas['Produto'].tolist())
            )
            df_novo = df_novo.dropna(subset=['Porcentagem'])

        df_novo['_norm'] = df_novo['Produto'].str.upper()
        dup_upload = df_novo[df_novo.duplicated('_norm', keep=False)]
        if not dup_upload.empty:
            st.warning(
                f"{dup_upload['_norm'].nunique()} produto(s) aparecem mais de uma vez NA "
                f"PRÓPRIA planilha enviada — usando a última linha de cada um."
            )
        df_novo = df_novo.drop_duplicates('_norm', keep='last')

        atual_map = {
            str(r['Produto']).strip().upper(): float(r['Porcentagem'])
            for _, r in st.session_state['cadastro_df'].iterrows()
        }

        mudou, novos = [], []
        for _, r in df_novo.iterrows():
            chave = r['_norm']
            pct_novo = float(r['Porcentagem'])
            if chave in atual_map:
                if atual_map[chave] != pct_novo:
                    mudou.append({'Produto': r['Produto'], '% Atual': atual_map[chave], '% Novo': pct_novo})
            else:
                novos.append({'Produto': r['Produto'], '% Novo': pct_novo})

        if not mudou and not novos:
            st.success('✅ Planilha lida — nenhuma mudança em relação ao cadastro atual (tudo já está igual).')
        else:
            if mudou:
                st.warning(f'{len(mudou)} produto(s) terão o percentual ATUALIZADO:')
                st.dataframe(pd.DataFrame(mudou), use_container_width=True, hide_index=True)
            if novos:
                st.info(f'{len(novos)} produto(s) NOVO(s) serão adicionados ao cadastro:')
                st.dataframe(pd.DataFrame(novos), use_container_width=True, hide_index=True)

            # Aplica ao estado em memória (ainda não salvo de forma
            # permanente -- só a tabela editável abaixo é atualizada)
            df_atual = st.session_state['cadastro_df'].copy()
            df_atual['_norm'] = df_atual['Produto'].astype(str).str.strip().str.upper()
            novo_map_completo = {r['_norm']: (r['Produto'], float(r['Porcentagem'])) for _, r in df_novo.iterrows()}

            linhas_finais = []
            vistos = set()
            for _, r in df_atual.iterrows():
                if r['_norm'] in novo_map_completo:
                    prod, pct = novo_map_completo[r['_norm']]
                    linhas_finais.append({'Produto': prod, 'Porcentagem': pct})
                    vistos.add(r['_norm'])
                else:
                    linhas_finais.append({'Produto': r['Produto'], 'Porcentagem': r['Porcentagem']})
            for chave, (prod, pct) in novo_map_completo.items():
                if chave not in vistos:
                    linhas_finais.append({'Produto': prod, 'Porcentagem': pct})

            st.session_state['cadastro_df'] = pd.DataFrame(linhas_finais).sort_values('Produto').reset_index(drop=True)
            st.success(
                'Planilha aplicada à tabela abaixo (ainda em memória). Revise e clique em '
                '**💾 Salvar cadastro** na seção 2 pra confirmar de verdade.'
            )

        st.session_state['_cad_upload_processado'] = up.file_id
    except Exception as e:
        st.error(f'Não foi possível importar essa planilha: {e}')

st.divider()

# ---------------------------------------------------------------------------
# 2. Tabela editável + salvar
# ---------------------------------------------------------------------------
st.header('2. Produtos cadastrados')
st.caption(
    'Edite direto na tabela: clique numa célula pra alterar, use o "+" no fim da tabela pra '
    'adicionar um produto novo, ou selecione uma linha e aperte a lixeira pra remover. '
    f'Produto sem % cadastrado usa {mp.PADRAO_PCT:g}% (padrão) no dashboard Margem Real, e '
    'fica sinalizado lá até você adicioná-lo aqui.'
)

df_editado = st.data_editor(
    st.session_state['cadastro_df'],
    num_rows='dynamic',
    use_container_width=True,
    hide_index=True,
    column_config={
        'Produto': st.column_config.TextColumn('Produto', required=True, width='large'),
        'Porcentagem': st.column_config.NumberColumn(
            'Porcentagem (%)', required=True, min_value=0, max_value=100, step=0.5, format='%.1f%%',
        ),
    },
    key='cad_editor',
)

st.session_state['cadastro_df'] = df_editado

col_save, col_count = st.columns([1, 3])
with col_count:
    st.caption(f'{len(df_editado)} produto(s) na tabela.')
with col_save:
    if st.button('💾 Salvar cadastro', type='primary', use_container_width=True):
        df_valido = df_editado.dropna(subset=['Produto', 'Porcentagem'])
        df_valido = df_valido[df_valido['Produto'].astype(str).str.strip() != '']

        # Detecta duplicados (mesmo produto normalizado aparecendo 2x na
        # tabela) ANTES de salvar -- sem isso, um deles seria descartado
        # silenciosamente ao virar dict, e a Ingrid não saberia qual valeu.
        norm = df_valido['Produto'].astype(str).str.strip().str.upper()
        dup_mask = norm.duplicated(keep=False)
        if dup_mask.any():
            dups = sorted(set(norm[dup_mask]))
            st.error(
                f"Não salvei: {len(dups)} produto(s) aparecem mais de uma vez na tabela "
                f"(mesmo nome, ignorando maiúsculas/espaços): {', '.join(dups)}. "
                f"Remova a linha duplicada e tente salvar de novo."
            )
        else:
            tabela_nova = {
                str(r['Produto']).strip(): float(r['Porcentagem'])
                for _, r in df_valido.iterrows()
            }
            ok = mp.salvar_tabela(tabela_nova, usuario=st.session_state.get('usuario_nome', 'Ingrid'))
            if ok:
                st.success(f'✅ Cadastro salvo — {len(tabela_nova)} produto(s). Já vale pro dashboard Margem Real.')
                st.rerun()
            else:
                st.error('Não foi possível salvar de forma permanente — veja o aviso acima sobre persistência.')

st.divider()

# ---------------------------------------------------------------------------
# Histórico de versões
# ---------------------------------------------------------------------------
historico = mp.historico_tabela()
if historico:
    with st.expander(f'🕓 Histórico de versões ({len(historico)} anterior(es))'):
        for v in historico:
            v_quando = (v.get('atualizado_em') or '')[:16].replace('T', ' ')
            v_qtd = len(v.get('valores', {}).get('produtos', {}))
            st.markdown(
                f"- **v{v.get('versao')}** — {v_quando} por {v.get('usuario', 'não identificado')} "
                f"— {v_qtd} produto(s)"
            )
