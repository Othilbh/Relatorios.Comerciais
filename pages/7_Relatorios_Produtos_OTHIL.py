"""OTHIL — Resultado de Produtos (antes "Relatórios de Produtos" / Projeto 2).

Upload mensal do "Resumo do Estoque" (PDF do Plus), base do relatório de
Resultado por Marca/Fornecedor -- ver marcas_fornecedor.py e a aba
"🏷️ Marca/Fornecedor" na Gerência, onde o resultado é exibido. Pedido da
Ingrid, 02/09/2026: reunião comercial do 1º sábado do mês pra discutir
fornecedores, com base em 2 PDFs mensais do Resumo do Estoque -- um
filtrado Vendas+Bonificação, outro filtrado Quebra (independentes: enviar
um não apaga o outro do mesmo mês -- ver marcas_fornecedor.py).

Reaproveita 100% o parser já usado nesta página desde o Projeto 2
(parsers_estoque.parse_resumo_estoque(), não duplicado) e a mesma técnica
de extração de texto de PDF (pdftotext -layout) já usada em Prevenção de
Perdas.

Renomeada e simplificada em 02/09/2026 -- pedido da Ingrid ("gostaria que
o nome ficasse Resultado de produtos. E se não for aproveitar a aba de
produtos para nada, pode excluí-la"): a antiga análise genérica de
produtos desta página (rankings, evolução, produto x cliente/vendedor,
matrizes, alertas, ~900 linhas) foi removida -- nunca chegou a ficar
visível de verdade (ficava atrás de acesso.parar_se_upload(), que sempre
interrompe a página inteira, política de upload de 27/08/2026), e a base
por trás dela (produtos.carregar_base_estoque()/salvar_resumo_estoque())
não é mais chamada por ninguém. Não foi apagada de produtos.py -- é um
módulo compartilhado e essas funções não atrapalham ficando paradas lá;
só não são mais usadas aqui. O "📦 Produtos" que já existe dentro da
Gerência (_render_produtos_resumo(), baseado na base consolidada de
Relatório Diário/Semanal/Mensal) é uma funcionalidade DIFERENTE e
continua exatamente como estava -- não tem nenhuma relação com esta
página nem com o Resumo do Estoque.

Upload e visualização continuam separados (upload aqui no módulo,
resultado só na Gerência) -- mesma política de acesso de 27/08/2026, ver
acesso.py. Usa deve_esconder_apos_upload() (não parar_se_upload()) porque
esta página tem DUAS seções de upload -- mesmo bug real de 29/08/2026
documentado em acesso.py (parar_se_upload()/st.stop() interromperia a
segunda seção se chamado depois da primeira)."""
import os
import subprocess
import tempfile

import streamlit as st

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import acesso
import data_store as ds
import periodo as periodo_mod
import parsers_estoque
import marcas_fornecedor as mf


def _pdf_to_text(uploaded_file):
    """Mesma técnica usada em Prevenção de Perdas (pdftotext -layout via
    subprocess) -- reaproveitada aqui, não reimplementada."""
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
        tmp.write(uploaded_file.read())
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            ['pdftotext', '-layout', tmp_path, '-'],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout if result.returncode == 0 else None
    except Exception:
        return None
    finally:
        os.unlink(tmp_path)


def _secao_upload(titulo, ajuda, modulo, publicar_fn, key_prefix):
    """Uma seção de upload (Vendas+Bonificação OU Quebra) -- mesmo fluxo de
    validação/preview/salvar já usado no resto do app (ver histórico deste
    arquivo), parametrizado pra não duplicar entre as duas seções desta
    página."""
    with st.expander(titulo, expanded=not ds.list_periodos(modulo, 'mensal')):
        st.caption(ajuda)
        arquivo = st.file_uploader('Resumo do Estoque (PDF)', type='pdf', key=f'{key_prefix}_upload')
        if arquivo is None:
            return
        texto_pdf = _pdf_to_text(arquivo)
        if not texto_pdf:
            st.error('Não foi possível ler o texto deste PDF (pdftotext falhou). Confirme que é o '
                     'relatório "Resumo do Estoque" exportado em PDF pelo Plus.')
            return
        parsed = parsers_estoque.parse_resumo_estoque(texto_pdf)
        if not parsed['itens']:
            st.error('Não foi possível reconhecer nenhum produto neste PDF. Confirme que é o '
                     'relatório "Resumo do Estoque" (com seções "Grupo: ..." e coluna "Resultado").')
            return
        uc1, uc2 = st.columns(2)
        uc1.metric('Produtos reconhecidos', len(parsed['itens']))
        uc2.metric('Grupos oficiais', len(parsed['grupos']))
        if parsed['avisos']:
            with st.expander(f"⚠️ {len(parsed['avisos'])} observação(ões) na leitura deste PDF "
                              f"(nenhum dado foi inventado ou descartado)"):
                for a in parsed['avisos']:
                    st.caption('• ' + a)

        # Mês de referência: sugerido pela data de Emissão do PDF, mas
        # editável (03/09/2026, pedido da Ingrid: enviou PDFs de agosto
        # emitidos já em setembro, e o app publicou como setembro -- a
        # Emissão sozinha não distingue "dados de agosto, impressos em
        # setembro" de "dados de setembro"). Ver mf.mes_detectado().
        periodo_ref_detectado = mf.mes_detectado(parsed)
        opcoes_mes = periodo_mod.listar_periodos('mensal', n=15)
        if periodo_ref_detectado not in opcoes_mes:
            opcoes_mes = sorted(set(opcoes_mes) | {periodo_ref_detectado}, reverse=True)
        periodo_ref_escolhido = st.selectbox(
            'Mês de referência', opcoes_mes, index=opcoes_mes.index(periodo_ref_detectado),
            format_func=lambda r: periodo_mod.rotulo('mensal', r), key=f'{key_prefix}_mes_sel',
            help=f"Detectado pela data de Emissão do PDF ({parsed.get('emissao') or '?'}). Corrija "
                 "aqui se o relatório foi emitido só nos primeiros dias do mês seguinte."
        )
        if periodo_ref_escolhido != periodo_ref_detectado:
            st.caption(f"⚠️ Mês detectado pela Emissão do PDF: "
                       f"{periodo_mod.rotulo('mensal', periodo_ref_detectado)} -- "
                       f"salvando como {periodo_mod.rotulo('mensal', periodo_ref_escolhido)}.")

        if ds.has_data(modulo, 'mensal', periodo_ref_escolhido):
            st.warning(f"Já existe um envio salvo para {periodo_mod.rotulo('mensal', periodo_ref_escolhido)}. "
                       f"Salvar de novo cria uma nova versão no histórico (a versão anterior NÃO é apagada).")
        if st.button('💾 Salvar', key=f'{key_prefix}_salvar'):
            periodo_ref_salvo, registro = publicar_fn(
                parsed, periodo_ref=periodo_ref_escolhido,
                usuario=st.session_state.get('usuario_nome', 'Ingrid'))
            if registro.get('_erro_persistencia_remota'):
                st.warning('Salvo localmente, mas houve um problema ao salvar de forma permanente: '
                           f"{registro['_erro_persistencia_remota']}")
            else:
                st.success(f"Salvo -- {periodo_mod.rotulo('mensal', periodo_ref_salvo)} "
                           f"(versão {registro['versao']}).")
            acesso.redirecionar_pos_upload()


# ── Page ─────────────────────────────────────────────────────────────────

st.title('📦 Resultado de Produtos')
st.caption('Upload mensal do Resumo do Estoque -- base do Resultado por Marca/Fornecedor '
           '(reunião comercial do 1º sábado do mês). Resultado disponível na Gerência.')

st.session_state.setdefault('usuario_nome', 'Ingrid')

_secao_upload(
    '📤 Vendas + Bonificação (PDF)',
    'Relatório do Plus: Estoque → Resumo do Estoque, filtrado por classificação BONIFICAÇÃO e '
    'VENDA. Cada envio cobre 1 mês (identificado pela data de Emissão do próprio relatório).',
    mf.MOD_VENDAS, mf.publicar_vendas, 'mf_vendas',
)

_secao_upload(
    '📤 Quebra (PDF)',
    'Relatório do Plus: Estoque → Resumo do Estoque, filtrado por classificação QUEBRA. Cada envio '
    'cobre 1 mês (identificado pela data de Emissão do próprio relatório) e é independente do envio '
    'de Vendas + Bonificação -- enviar um não apaga o outro do mesmo mês.',
    mf.MOD_QUEBRA, mf.publicar_quebra, 'mf_quebra',
)

# Perfil de upload (27/08/2026, pedido da Ingrid) -- ver docstring do
# módulo. Nada além das duas seções de upload acima é mostrado nesta
# página (o resultado fica só na Gerência) -- não há nenhum conteúdo de
# dashboard/histórico aqui pra gatear com deve_esconder_apos_upload(),
# ao contrário de páginas como 4_Quebra_OTHIL.py.
