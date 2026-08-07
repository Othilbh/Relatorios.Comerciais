"""Página Prevenção de Perdas — Estoque Parado."""
import datetime
import subprocess
import tempfile
import os
import streamlit as st
import pandas as pd

from parsers_estoque import parse_estoque_fisico

st.set_page_config(page_title="Prevenção de Perdas", layout="wide")

st.title("🚨 Prevenção de Perdas — Estoque Parado")
st.caption(
    "Identifica produtos parados antes que virem prejuízo. "
    "Envie o PDF do Estoque Físico gerado no Mercatus."
)

# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def _pdf_to_text(uploaded_file):
    """Converte PDF enviado pelo usuário em texto usando pdftotext -layout."""
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
        tmp.write(uploaded_file.read())
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            ['pdftotext', '-layout', tmp_path, '-'],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            st.error(f"Erro ao processar PDF: {result.stderr}")
            return None
        return result.stdout
    except FileNotFoundError:
        st.error("pdftotext não encontrado. Instale poppler-utils no servidor.")
        return None
    except subprocess.TimeoutExpired:
        st.error("Timeout ao processar PDF.")
        return None
    finally:
        os.unlink(tmp_path)


def _fmt_float(v):
    """Formata número com vírgula decimal, ex: 1.234,56."""
    return f"{v:,.3f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def _fmt_moeda(v):
    return f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def _render_metricas(df, label_saldo='Saldo (cx)', saldo_col='Saldo (cx)', valor_col='Valor Estoque'):
    c1, c2, c3 = st.columns(3)
    c1.metric("Produtos encontrados", len(df))
    total_saldo = df[saldo_col].sum()
    c2.metric(label_saldo, _fmt_float(total_saldo))
    total_valor = df[valor_col].sum()
    c3.metric("Valor em estoque", _fmt_moeda(total_valor))


def _df_sem_venda(produtos):
    """Filtra: Saldo Atual > 0 E Qtde Vendida = 0."""
    filtrado = [
        p for p in produtos
        if p['saldo_atual'] > 0 and p['qtd_vendida'] == 0
    ]
    if not filtrado:
        return pd.DataFrame()
    df = pd.DataFrame(filtrado)
    df = df[['codigo', 'produto', 'complemento', 'saldo_atual',
             'custo_unit', 'valor_estoque', 'data_entrada_str']].copy()
    df.columns = ['Código', 'Produto', 'Depto', 'Saldo (cx)',
                  'Custo Unit.', 'Valor Estoque', 'Data Entrada']
    df = df.sort_values('Valor Estoque', ascending=False).reset_index(drop=True)
    return df


def _df_mes_estoque(produtos, emissao_date, dias=30):
    """Filtra: Saldo Atual > 0 E Data Entrada < emissao_date - dias."""
    cutoff = emissao_date - datetime.timedelta(days=dias)
    filtrado = [
        p for p in produtos
        if p['saldo_atual'] > 0 and p['data_entrada'] < cutoff
    ]
    if not filtrado:
        return pd.DataFrame(), cutoff

    df = pd.DataFrame(filtrado)
    df['dias_estoque'] = df['data_entrada'].apply(lambda d: (emissao_date - d).days)
    df = df[['codigo', 'produto', 'complemento', 'data_entrada_str',
             'dias_estoque', 'saldo_atual', 'custo_unit', 'valor_estoque']].copy()
    df.columns = ['Código', 'Produto', 'Depto', 'Data Entrada',
                  'Dias em Estoque', 'Saldo (cx)', 'Custo Unit.', 'Valor Estoque']
    df = df.sort_values('Dias em Estoque', ascending=False).reset_index(drop=True)
    return df, cutoff


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab1, tab2 = st.tabs(["🕐 1 Semana Sem Venda", "📦 1 Mês em Estoque"])

# ── Tab 1: 1 Semana Sem Venda ────────────────────────────────────────────────
with tab1:
    st.subheader("1 Semana Sem Venda")
    st.info(
        "Envie o relatório de Estoque Físico **com período de 1 semana** "
        "(ex: 31/07 a 07/08). O app filtra automaticamente os produtos com "
        "**Saldo Atual > 0 e Qtde Vendida = 0**."
    )

    uploaded1 = st.file_uploader(
        "Estoque Físico — Período de 1 semana (PDF)",
        type='pdf',
        key='upload_sem_venda',
    )

    if uploaded1:
        with st.spinner("Processando PDF..."):
            texto = _pdf_to_text(uploaded1)

        if texto:
            dados = parse_estoque_fisico(texto)
            emissao = dados['emissao']
            periodo = dados['periodo']
            produtos = dados['produtos']

            st.success(
                f"PDF lido com sucesso · Emissão: **{emissao}** · "
                f"Período desde: **{periodo}** · "
                f"Total no relatório: **{len(produtos)} produtos**"
            )

            df = _df_sem_venda(produtos)

            if df.empty:
                st.success("✅ Nenhum produto com saldo > 0 e venda zero no período.")
            else:
                st.warning(
                    f"⚠️ **{len(df)} produto(s)** com saldo em estoque e **zero vendas** na semana."
                )
                _render_metricas(df, label_saldo='Total cx paradas')

                # Formatar para exibição
                df_show = df.copy()
                df_show['Saldo (cx)']     = df_show['Saldo (cx)'].apply(_fmt_float)
                df_show['Custo Unit.']    = df_show['Custo Unit.'].apply(_fmt_moeda)
                df_show['Valor Estoque']  = df_show['Valor Estoque'].apply(_fmt_moeda)
                st.dataframe(df_show, use_container_width=True, hide_index=True)

                # Download CSV
                csv = df.to_csv(index=False, sep=';', decimal=',').encode('utf-8-sig')
                st.download_button(
                    "⬇️ Baixar CSV",
                    data=csv,
                    file_name=f"sem_venda_{emissao.replace('/', '-')}.csv",
                    mime='text/csv',
                )

# ── Tab 2: 1 Mês em Estoque ──────────────────────────────────────────────────
with tab2:
    st.subheader("1 Mês em Estoque")
    st.info(
        "Envie o relatório de Estoque Físico **do dia atual**. "
        "O app filtra os produtos com **Saldo Atual > 0 e Data de Entrada há mais de 30 dias**."
    )

    uploaded2 = st.file_uploader(
        "Estoque Físico — Do dia atual (PDF)",
        type='pdf',
        key='upload_mes_estoque',
    )

    if uploaded2:
        with st.spinner("Processando PDF..."):
            texto2 = _pdf_to_text(uploaded2)

        if texto2:
            dados2 = parse_estoque_fisico(texto2)
            emissao2     = dados2['emissao']
            emissao_date = dados2['emissao_date']
            produtos2    = dados2['produtos']

            st.success(
                f"PDF lido com sucesso · Emissão: **{emissao2}** · "
                f"Total no relatório: **{len(produtos2)} produtos**"
            )

            df2, cutoff = _df_mes_estoque(produtos2, emissao_date, dias=30)

            if df2.empty:
                st.success("✅ Nenhum produto com mais de 30 dias em estoque e saldo > 0.")
            else:
                st.warning(
                    f"⚠️ **{len(df2)} produto(s)** com **mais de 30 dias em estoque** "
                    f"(entrada antes de {cutoff.strftime('%d/%m/%Y')})."
                )
                _render_metricas(df2, label_saldo='Total cx paradas')

                # Formatar para exibição
                df_show2 = df2.copy()
                df_show2['Saldo (cx)']    = df_show2['Saldo (cx)'].apply(_fmt_float)
                df_show2['Custo Unit.']   = df_show2['Custo Unit.'].apply(_fmt_moeda)
                df_show2['Valor Estoque'] = df_show2['Valor Estoque'].apply(_fmt_moeda)
                st.dataframe(df_show2, use_container_width=True, hide_index=True)

                # Download CSV
                csv2 = df2.to_csv(index=False, sep=';', decimal=',').encode('utf-8-sig')
                st.download_button(
                    "⬇️ Baixar CSV",
                    data=csv2,
                    file_name=f"mes_estoque_{emissao2.replace('/', '-')}.csv",
                    mime='text/csv',
                )
