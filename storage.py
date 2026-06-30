"""Persistência da configuração semanal (produtos + percentuais) num arquivo
dentro do próprio repositório GitHub, usando a API de Contents.

Por quê: o app roda no Streamlit Community Cloud, cujo disco é efêmero —
qualquer arquivo gravado localmente (ex.: config_semanal.json) é perdido
sempre que o app reinicia (inatividade, novo deploy, etc.). Por isso a
configuração da semana precisa ficar salva em algum lugar fora do container,
e o lugar mais simples (sem precisar criar conta em outro serviço) é o
próprio repositório do app no GitHub.

Configuração necessária (Streamlit Cloud → app → Settings → Secrets):
    GITHUB_TOKEN = "ghp_..."   # Personal Access Token com permissão de
                                 escrita no conteúdo deste repositório
                                 (classic: scope "repo"; fine-grained:
                                 Contents: Read and write)

Opcionalmente, para apontar para outro repositório/arquivo/branch:
    GITHUB_REPO = "Othilbh/Relatorios.Comerciais"
    GITHUB_CONFIG_PATH = "config_semanal.json"
    GITHUB_BRANCH = "main"

Se o token não estiver configurado, as funções abaixo retornam None / False
e o app.py cai de volta no arquivo local (que funciona normalmente quando
roda na sua máquina, mas não persiste no Streamlit Cloud).
"""
import base64
import json
import os

import requests
import streamlit as st

DEFAULT_REPO = "Othilbh/Relatorios.Comerciais"
DEFAULT_PATH = "config_semanal.json"
DEFAULT_BRANCH = "main"


def _secret(name, default=None):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name, default)


def _config_target():
    repo = _secret("GITHUB_REPO", DEFAULT_REPO)
    path = _secret("GITHUB_CONFIG_PATH", DEFAULT_PATH)
    branch = _secret("GITHUB_BRANCH", DEFAULT_BRANCH)
    return repo, path, branch


def _headers():
    token = _secret("GITHUB_TOKEN")
    if not token:
        return None
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }


def is_configured() -> bool:
    """True se houver um GITHUB_TOKEN configurado nos Secrets."""
    return _headers() is not None


def load_config_remote():
    """Lê a configuração salva no repositório. Retorna o dict, ou None se
    não houver token configurado, o arquivo ainda não existir, ou der erro
    de rede (nesses casos o app.py decide o fallback)."""
    headers = _headers()
    if not headers:
        return None
    repo, path, branch = _config_target()
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    try:
        resp = requests.get(url, headers=headers, params={"ref": branch}, timeout=10)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return json.loads(content)
    except Exception:
        return None


def save_config_remote(cfg: dict):
    """Grava a configuração no repositório (cria ou atualiza o arquivo via
    commit). Retorna (True, None) em caso de sucesso, ou (False, motivo) em
    caso de falha — o motivo é mostrado na tela para a Ingrid entender o que
    falta configurar."""
    headers = _headers()
    if not headers:
        return False, ("GITHUB_TOKEN não configurado nos Secrets do Streamlit "
                        "Cloud — a configuração não pode ser salva de forma "
                        "permanente. Veja as instruções de configuração.")
    repo, path, branch = _config_target()
    url = f"https://api.github.com/repos/{repo}/contents/{path}"

    sha = None
    try:
        get_resp = requests.get(url, headers=headers, params={"ref": branch}, timeout=10)
        if get_resp.status_code == 200:
            sha = get_resp.json().get("sha")
    except requests.RequestException as e:
        return False, f"Falha ao consultar o GitHub: {e}"

    content_str = json.dumps(cfg, ensure_ascii=False, indent=2)
    payload = {
        "message": f"Atualiza configuração semanal ({cfg.get('periodo', '')})".strip(),
        "content": base64.b64encode(content_str.encode("utf-8")).decode("utf-8"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    try:
        put_resp = requests.put(url, headers=headers, json=payload, timeout=10)
    except requests.RequestException as e:
        return False, f"Falha ao salvar no GitHub: {e}"

    if put_resp.status_code in (200, 201):
        return True, None
    return False, f"GitHub respondeu {put_resp.status_code}: {put_resp.text[:200]}"
