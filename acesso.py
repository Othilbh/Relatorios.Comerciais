"""Controle de acesso do perfil "Upload de PDFs".

Pedido explícito da Ingrid, 26/08/2026 ("AJUSTE DE ACESSO E FLUXO DE UPLOAD
DOS PDFs"): a pessoa responsável por fazer upload dos PDFs não deve ter
acesso aos Dashboards do sistema -- nem pelo menu, nem por URL direta.
Fluxo esperado pra esse perfil: Login -> Upload dos PDFs -> Gerência,
nunca redirecionado pra nenhum Dashboard.

FONTE ÚNICA desse controle -- toda página que precisa saber se a sessão
atual é o perfil restrito, ou aplicar o bloqueio/redirecionamento, importa
daqui. Não criar uma segunda lógica de perfil em nenhum outro arquivo.

Importante: isso NÃO mexe em nada da Gerência (pages/gerencia.py) -- ela
continua com a própria senha de acesso, exatamente como já era antes
("só é permitida a visualização na gerência, com senha" -- confirmado pela
Ingrid). O perfil de upload também precisa dessa senha da Gerência pra
efetivamente ver o conteúdo de lá; este módulo só garante que ele chegue
até a TELA da Gerência (post-upload), não que ele veja o conteúdo sem
senha.
"""
import streamlit as st

_SENHA_FALLBACK = 'othil_upload_2026'


def _get_senha() -> str:
    try:
        return st.secrets['upload_senha']
    except Exception:
        return _SENHA_FALLBACK


def is_upload() -> bool:
    """True se a sessão atual está autenticada como o perfil restrito de
    upload (sem acesso a Dashboards)."""
    return st.session_state.get('perfil') == 'upload'


def tentar_login(senha: str) -> bool:
    """Tenta autenticar como perfil de upload. Não mexe no estado se a
    senha estiver errada (deixa o perfil atual como estava)."""
    if senha and senha == _get_senha():
        st.session_state['perfil'] = 'upload'
        return True
    return False


def sair():
    """Volta pro acesso normal (sem restrição), como era antes desta
    funcionalidade -- não afeta nenhum outro usuário/sessão."""
    st.session_state.pop('perfil', None)


def bloquear_dashboard():
    """Chamar logo no topo (após st.set_page_config, se houver) de
    qualquer página que seja Dashboard/relatório sem nenhuma função de
    upload de PDF pro perfil restrito -- bloqueia de vez o acesso direto
    por URL, mesmo que a página já não apareça no menu lateral pra esse
    perfil (defesa em profundidade: não depender só da lista do
    st.navigation)."""
    if is_upload():
        st.error(
            '🔒 Acesso restrito. Este perfil tem acesso apenas ao envio de '
            'PDFs e, após concluído, à Gerência.'
        )
        st.stop()


def redirecionar_pos_upload():
    """Chamar logo após uma ação de salvar/publicar um upload ser
    concluída com sucesso, quando o perfil atual é o de upload -- pedido
    explícito da Ingrid: fluxo Login -> Upload -> Gerência, o perfil de
    upload nunca deve permanecer numa tela de Dashboard depois de enviar o
    PDF. `st.switch_page` já interrompe a execução do script (equivalente
    a um st.stop() logo em seguida)."""
    if is_upload():
        st.success('Upload concluído. Redirecionando para a Gerência...')
        st.switch_page('pages/gerencia.py')


def parar_se_upload():
    """Chamar dentro de uma aba/seção que mistura upload com
    dashboard/histórico/relatório, IMEDIATAMENTE ANTES do conteúdo que não
    é upload -- pro perfil restrito, interrompe a renderização ali (sem
    afetar o restante da página pros demais perfis). Diferente de
    `bloquear_dashboard`, que bloqueia a página inteira: aqui a parte de
    upload já foi mostrada normalmente antes desta chamada."""
    if is_upload():
        st.stop()
