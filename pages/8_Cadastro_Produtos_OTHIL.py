"""OTHIL — Cadastro de Marcas/Fornecedores (% de despesa administrativa)

Tela pra Ingrid manter, sozinha e sem precisar de alteração de código, o
percentual de despesa administrativa POR MARCA/FORNECEDOR/EMBALAGEM usado
pelo dashboard "Margem Real" (aba dentro da Gerência) pra retirar essa
despesa do Custo do relatório e achar o custo real do produto:

    Custo real = Custo do relatório ÷ (1 + % da marca do produto / 100)

Até 25/08/2026 esse cadastro era por PRODUTO EXATO (185+ linhas). Análise
da planilha real confirmou com a Ingrid que o percentual varia pela
MARCA/FORNECEDOR/EMBALAGEM (ex.: VALENTINO, FRUTIMAR, POMERANA...), não
pela fruta ou calibre — então agora o cadastro é por marca (bem mais
enxuto), e um produto novo da mesma marca já sai certo sozinho: o sistema
procura, no nome do produto, qual marca cadastrada aparece.

Persistência central versionada (data_store.py — mesma usada em todo o
app): toda vez que o cadastro é salvo, fica registrado quem mudou o quê e
quando, e nada se perde (histórico completo disponível abaixo).
"""
import pandas as pd
import streamlit as st

import margem_produto as mp

st.title('🏷️ Cadastro de Marcas')
st.caption(
    'Percentual de despesa administrativa por marca/fornecedor/embalagem, usado pelo '
    'dashboard **Margem Real** (aba dentro da Gerência) pra calcular o custo real: '
    '**Custo real = Custo do relatório ÷ (1 + % da marca)**. Um produto é associado à marca '
    'quando o nome dela aparece dentro do nome do produto — ex.: a marca **VALENTINO** vale '
    'pra "GALA 165 PRETA VALENTINO", "FUJI 100 PRETA VALENTINO" etc., sem precisar cadastrar '
    'cada um.'
)

# ---------------------------------------------------------------------------
# Estado inicial: carrega o cadastro salvo (ou a semente, se nunca foi salvo)
# ---------------------------------------------------------------------------
if 'marcas_df' not in st.session_state:
    marcas_iniciais = mp.carregar_marcas()
    st.session_state['marcas_df'] = pd.DataFrame(
        sorted(marcas_iniciais.items()), columns=['Marca', 'Porcentagem']
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
        'tabela semente, montada automaticamente a partir da planilha de produtos que você '
        'mandou (produto → marca detectada pelo nome). **Vale conferir** essa lista antes de '
        'salvar pela primeira vez, principalmente as marcas mais curtas/genéricas (ex. "GI", '
        '"Z", "TP") — se alguma não fizer sentido como marca, é só apagar a linha ou corrigir '
        'o percentual. Depois de revisar, clique em **💾 Salvar cadastro** na seção 2.'
    )

st.divider()

# ---------------------------------------------------------------------------
# 1. Importar planilha (opcional) — atualiza/adiciona, nunca remove sozinho
# ---------------------------------------------------------------------------
st.header('1. Importar planilha (opcional)')
st.caption(
    'Envie uma planilha (.xls, .xlsx ou .csv) com uma coluna de nome da marca e uma coluna de '
    'porcentagem. A importação só ATUALIZA percentuais de marcas já existentes e ADICIONA '
    'marcas novas — nunca remove uma marca sozinha, mesmo que ela não apareça na planilha '
    'enviada. Nada é salvo de verdade até você clicar em **💾 Salvar cadastro** na seção 2.'
)

up = st.file_uploader('Planilha de percentuais', type=['xls', 'xlsx', 'csv'], key='cad_upload')

if up is not None and st.session_state.get('_cad_upload_processado') != up.file_id:
    try:
        if up.name.lower().endswith('.csv'):
            df_novo = pd.read_csv(up)
        else:
            df_novo = pd.read_excel(up)

        cols_norm = {str(c).strip().upper(): c for c in df_novo.columns}
        col_marca = next(
            (orig for norm, orig in cols_norm.items() if 'MARCA' in norm or 'PRODUTO' in norm or 'FORNECEDOR' in norm),
            None,
        )
        col_pct = next(
            (orig for norm, orig in cols_norm.items()
             if 'PORCENT' in norm or 'PERCENT' in norm or norm.strip() == '%'),
            None,
        )
        if not col_marca or not col_pct:
            raise ValueError(
                'não encontrei colunas de marca e porcentagem nessa planilha — '
                'esperado algo como "MARCA" e "PORCENTAGEM" no cabeçalho'
            )

        df_novo = df_novo[[col_marca, col_pct]].copy()
        df_novo.columns = ['Marca', 'Porcentagem']
        df_novo['Marca'] = df_novo['Marca'].astype(str).str.strip()
        df_novo = df_novo[df_novo['Marca'] != '']
        df_novo['Porcentagem'] = pd.to_numeric(df_novo['Porcentagem'], errors='coerce')

        invalidas = df_novo[df_novo['Porcentagem'].isna()]
        if not invalidas.empty:
            st.warning(
                f"{len(invalidas)} linha(s) com porcentagem não numérica foram ignoradas: "
                + ', '.join(invalidas['Marca'].tolist())
            )
            df_novo = df_novo.dropna(subset=['Porcentagem'])

        df_novo['_norm'] = df_novo['Marca'].str.upper()
        dup_upload = df_novo[df_novo.duplicated('_norm', keep=False)]
        if not dup_upload.empty:
            st.warning(
                f"{dup_upload['_norm'].nunique()} marca(s) aparecem mais de uma vez NA "
                f"PRÓPRIA planilha enviada — usando a última linha de cada uma."
            )
        df_novo = df_novo.drop_duplicates('_norm', keep='last')

        atual_map = {
            str(r['Marca']).strip().upper(): float(r['Porcentagem'])
            for _, r in st.session_state['marcas_df'].iterrows()
        }

        mudou, novos = [], []
        for _, r in df_novo.iterrows():
            chave = r['_norm']
            pct_novo = float(r['Porcentagem'])
            if chave in atual_map:
                if atual_map[chave] != pct_novo:
                    mudou.append({'Marca': r['Marca'], '% Atual': atual_map[chave], '% Novo': pct_novo})
            else:
                novos.append({'Marca': r['Marca'], '% Novo': pct_novo})

        if not mudou and not novos:
            st.success('✅ Planilha lida — nenhuma mudança em relação ao cadastro atual (tudo já está igual).')
        else:
            if mudou:
                st.warning(f'{len(mudou)} marca(s) terão o percentual ATUALIZADO:')
                st.dataframe(pd.DataFrame(mudou), use_container_width=True, hide_index=True)
            if novos:
                st.info(f'{len(novos)} marca(s) NOVA(s) serão adicionadas ao cadastro:')
                st.dataframe(pd.DataFrame(novos), use_container_width=True, hide_index=True)

            # Aplica ao estado em memória (ainda não salvo de forma
            # permanente -- só a tabela editável abaixo é atualizada)
            df_atual = st.session_state['marcas_df'].copy()
            df_atual['_norm'] = df_atual['Marca'].astype(str).str.strip().str.upper()
            novo_map_completo = {r['_norm']: (r['Marca'], float(r['Porcentagem'])) for _, r in df_novo.iterrows()}

            linhas_finais = []
            vistos = set()
            for _, r in df_atual.iterrows():
                if r['_norm'] in novo_map_completo:
                    marca, pct = novo_map_completo[r['_norm']]
                    linhas_finais.append({'Marca': marca, 'Porcentagem': pct})
                    vistos.add(r['_norm'])
                else:
                    linhas_finais.append({'Marca': r['Marca'], 'Porcentagem': r['Porcentagem']})
            for chave, (marca, pct) in novo_map_completo.items():
                if chave not in vistos:
                    linhas_finais.append({'Marca': marca, 'Porcentagem': pct})

            st.session_state['marcas_df'] = pd.DataFrame(linhas_finais).sort_values('Marca').reset_index(drop=True)
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
st.header('2. Marcas cadastradas')
st.caption(
    'Edite direto na tabela: clique numa célula pra alterar, use o "+" no fim da tabela pra '
    'adicionar uma marca nova, ou clique na linha pra selecioná-la (fica destacada) e aperte '
    'Delete ou Backspace no teclado pra remover -- não existe ícone de lixeira, a tabela usa o '
    'teclado pra apagar linha. '
    f'Produto que não bater com nenhuma marca cadastrada usa {mp.PADRAO_PCT:g}% (padrão) no '
    'dashboard Margem Real, e fica sinalizado lá até você adicionar a marca aqui.'
)

df_editado = st.data_editor(
    st.session_state['marcas_df'],
    num_rows='dynamic',
    use_container_width=True,
    hide_index=True,
    column_config={
        'Marca': st.column_config.TextColumn('Marca', required=True, width='large'),
        'Porcentagem': st.column_config.NumberColumn(
            'Porcentagem (%)', required=True, min_value=0, max_value=100, step=0.5, format='%.1f%%',
        ),
    },
    key='cad_editor',
)

st.session_state['marcas_df'] = df_editado

col_save, col_count = st.columns([2, 2])
with col_count:
    st.caption(f'{len(df_editado)} marca(s) na tabela.')
with col_save:
    if st.button('💾 Salvar cadastro', type='primary', use_container_width=True):
        df_valido = df_editado.dropna(subset=['Marca', 'Porcentagem'])
        df_valido = df_valido[df_valido['Marca'].astype(str).str.strip() != '']

        # Detecta duplicados (mesma marca normalizada aparecendo 2x na
        # tabela) ANTES de salvar -- sem isso, uma delas seria descartada
        # silenciosamente ao virar dict, e a Ingrid não saberia qual valeu.
        norm = df_valido['Marca'].astype(str).str.strip().str.upper()
        dup_mask = norm.duplicated(keep=False)
        if dup_mask.any():
            dups = sorted(set(norm[dup_mask]))
            st.error(
                f"Não salvei: {len(dups)} marca(s) aparecem mais de uma vez na tabela "
                f"(mesmo nome, ignorando maiúsculas/espaços): {', '.join(dups)}. "
                f"Remova a linha duplicada e tente salvar de novo."
            )
        else:
            marcas_novas = {
                str(r['Marca']).strip(): float(r['Porcentagem'])
                for _, r in df_valido.iterrows()
            }
            ok = mp.salvar_marcas(marcas_novas, usuario=st.session_state.get('usuario_nome', 'Ingrid'))
            if ok:
                st.success(f'✅ Cadastro salvo — {len(marcas_novas)} marca(s). Já vale pro dashboard Margem Real.')
                st.rerun()
            else:
                st.error('Não foi possível salvar de forma permanente — veja o aviso acima sobre persistência.')

st.divider()

# ---------------------------------------------------------------------------
# Histórico de versões
# ---------------------------------------------------------------------------
historico = mp.historico_marcas()
if historico:
    with st.expander(f'3. 🕓 Histórico de versões ({len(historico)} anterior(es))'):
        for v in historico:
            v_quando = (v.get('atualizado_em') or '')[:16].replace('T', ' ')
            v_qtd = len(v.get('valores', {}).get('marcas', {}))
            st.markdown(
                f"- **v{v.get('versao')}** — {v_quando} por {v.get('usuario', 'não identificado')} "
                f"— {v_qtd} marca(s)"
            )
