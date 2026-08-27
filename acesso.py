"""Fluxo Upload de PDFs -> Gerência.

Pedido explícito da Ingrid (26-27/08/2026, "AJUSTE DE ACESSO E FLUXO DE
UPLOAD DOS PDFs", ajustado em 27/08): depois que um PDF é enviado e o
dashboard daquele período é salvo, a página NÃO mostra o dashboard ali na
hora -- só uma mensagem de sucesso com um link pra Gerência, que é onde o
resultado passa a aparecer (a senha da própria Gerência, que já existia
antes desta funcionalidade, continua sendo o único jeito de ver os dados).
Isso vale pra QUALQUER pessoa que use essas páginas, sem exceção e sem
senha nova -- por isso, ao contrário da primeira versão desta
funcionalidade, não existe mais aqui nenhum conceito de "perfil" ou login
separado. É sempre assim, pra todo mundo.

FONTE ÚNICA desse redirecionamento -- toda página com upload de PDF importa
daqui em vez de reimplementar a mesma lógica.
"""
import streamlit as st


def redirecionar_pos_upload():
    """Chamar logo após uma ação de salvar/publicar um upload ser
    concluída com sucesso -- em vez de continuar mostrando o dashboard
    nessa página, mostra uma mensagem de sucesso com um link pra Gerência
    (onde o resultado passa a ficar disponível, atrás da senha que já
    existe lá) e interrompe o resto da página."""
    st.success('✅ Upload concluído e salvo. Veja o resultado na Gerência.')
    st.page_link('pages/gerencia.py', label='Ir para a Gerência', icon='🔐')
    st.stop()


def parar_se_upload():
    """Chamar dentro de uma aba/seção que mistura upload com
    dashboard/histórico/relatório, IMEDIATAMENTE ANTES do conteúdo que não
    é upload -- a parte de upload já foi mostrada normalmente antes desta
    chamada; daqui em diante (preview de dashboard, histórico) fica de fora,
    disponível só na Gerência."""
    st.stop()
