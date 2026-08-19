"""Faz upload de um arquivo XLSX para o Google Drive e converte para
Google Sheets automaticamente. Usa as credenciais da conta de serviço
armazenadas nos Secrets do Streamlit Cloud.

Configuração necessária em st.secrets (secrets.toml):
  [gcp_service_account]
  type = "service_account"
  project_id = "..."
  private_key_id = "..."
  private_key = "-----BEGIN RSA PRIVATE KEY-----\\n..."
  client_email = "othil-sheets@relatorios-othil-d15ada4a1f71.iam.gserviceaccount.com"
  ... (demais campos do JSON baixado do Google Cloud)

  gsheets_folder_id = "ID_DA_PASTA_NO_GOOGLE_DRIVE"
"""
import io

import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets',
]


def _get_drive_service():
    creds_info = dict(st.secrets['gcp_service_account'])
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)


def upload_xlsx_as_sheet(xlsx_bytes: bytes, nome_arquivo: str) -> str:
    """Faz upload de xlsx_bytes para o Google Drive, convertendo para
    Google Sheets. Retorna o link público do arquivo criado.

    Args:
        xlsx_bytes: conteúdo do arquivo .xlsx em bytes.
        nome_arquivo: nome do arquivo sem extensão (ex: 'Relatorio_30-06-2026').

    Returns:
        URL do Google Sheets criado (webViewLink).
    """
    service = _get_drive_service()
    folder_id = st.secrets.get('gsheets_folder_id', '')

    file_metadata = {
        'name': nome_arquivo,
        # mimeType de Google Sheets faz o Drive converter o XLSX automaticamente
        'mimeType': 'application/vnd.google-apps.spreadsheet',
    }
    if folder_id:
        file_metadata['parents'] = [folder_id]

    media = MediaIoBaseUpload(
        io.BytesIO(xlsx_bytes),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        resumable=False,
    )

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id,webViewLink',
    ).execute()

    # Qualquer pessoa com o link pode visualizar (sem precisar de login)
    service.permissions().create(
        fileId=file['id'],
        body={'type': 'anyone', 'role': 'reader'},
    ).execute()

    return file['webViewLink']
