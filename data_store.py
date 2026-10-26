"""Camada central de PERSISTÊNCIA e HISTÓRICO — usada por todos os módulos.

Por quê: o app roda no Streamlit Community Cloud, cujo disco é efêmero —
qualquer arquivo gravado localmente (inclusive tudo que hoje é salvo em
gerencia_data/) é apagado a cada restart/redeploy/hibernação por
inatividade. Hoje só a configuração semanal (storage.py) sobrevive a isso,
porque é salva no repositório GitHub via API em vez de em disco local.

Este módulo estende exatamente esse mesmo padrão (já comprovado, já
configurado via GITHUB_TOKEN, sem custo/conta nova) para QUALQUER dado
salvo por qualquer módulo do app, com histórico versionado: salvar um novo
valor NÃO apaga o anterior — o valor anterior fica preservado em
'history', consultável depois.

Se GITHUB_TOKEN não estiver configurado (ex.: rodando localmente na
máquina da Ingrid, fora do Streamlit Cloud), cai automaticamente para
arquivo local em gerencia_data/data/ — funciona normalmente localmente,
só não persiste entre deploys no Cloud (mesmo fallback que storage.py já
tem hoje para a config semanal).

Uso típico:
    import data_store as ds

    registro = ds.save_record(
        modulo='metas_semanais', tipo_periodo='semanal', periodo_ref='2026-W33',
        valores={'meta': 1_000_000, 'realizado': 600_000},
        usuario='Ingrid',
    )
    atual = ds.load_current('metas_semanais', 'semanal', '2026-W33')
    versoes_antigas = ds.load_history('metas_semanais', 'semanal', '2026-W33')
    periodos_com_dado = ds.list_periodos('metas_semanais', 'semanal')
"""
import base64
import json
import os
import uuid
from datetime import datetime, timezone

import requests
import streamlit as st

DEFAULT_REPO = "Othilbh/Relatorios.Comerciais"
DEFAULT_BRANCH = "main"
DATA_ROOT = "data"            # pasta no repositório GitHub onde tudo é salvo
LOCAL_ROOT = os.path.join("gerencia_data", "data")  # fallback local


# ---------------------------------------------------------------------------
# Configuração / secrets (mesmo padrão de storage.py)
# ---------------------------------------------------------------------------

def _secret(name, default=None):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name, default)


def _repo_branch():
    return _secret("GITHUB_REPO", DEFAULT_REPO), _secret("GITHUB_BRANCH", DEFAULT_BRANCH)


def _headers():
    token = _secret("GITHUB_TOKEN")
    if not token:
        return None
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}


def is_remoto() -> bool:
    """True se houver GITHUB_TOKEN configurado (persistência sobrevive ao
    Streamlit Cloud). Se False, os dados só ficam garantidos localmente."""
    return _headers() is not None


def _path_for(modulo: str, tipo_periodo: str, periodo_ref: str) -> str:
    return f"{modulo}/{tipo_periodo}/{periodo_ref}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# ---------------------------------------------------------------------------
# I/O remoto (GitHub Contents API)
# ---------------------------------------------------------------------------

def _github_get(rel_path: str):
    """Retorna (obj, sha, erro).

    erro é None quando a leitura foi conclusiva -- seja porque encontrou o
    arquivo (obj preenchido), seja porque o GitHub confirmou (404) que ele
    ainda não existe (obj=None, erro=None: "não existe" é uma resposta
    válida, não uma falha).

    erro é preenchido (string) quando a leitura foi AMBÍGUA -- falha de
    rede, timeout, token sem permissão (401/403), rate limit (429), erro
    do lado do GitHub (5xx) ou conteúdo que veio mas não pôde ser
    decodificado. Nesses casos NÃO dá pra saber se o arquivo existe ou
    não -- quem chama não deve tratar isso como "não existe ainda".
    """
    headers = _headers()
    if not headers:
        return None, None, None
    repo, branch = _repo_branch()
    url = f"https://api.github.com/repos/{repo}/contents/{DATA_ROOT}/{rel_path}"
    try:
        resp = requests.get(url, headers=headers, params={"ref": branch}, timeout=10)
    except requests.RequestException as e:
        return None, None, f"falha de rede ao consultar o GitHub: {e}"
    if resp.status_code == 404:
        return None, None, None
    if resp.status_code != 200:
        return None, None, f"GitHub respondeu {resp.status_code} ao consultar {rel_path}"
    data = resp.json()
    try:
        content = base64.b64decode(data["content"]).decode("utf-8")
        return json.loads(content), data.get("sha"), None
    except Exception as e:
        return None, data.get("sha"), f"conteúdo remoto ilegível em {rel_path}: {e}"


def _github_put(rel_path: str, obj: dict, sha, mensagem: str):
    headers = _headers()
    if not headers:
        return False, "GITHUB_TOKEN não configurado nos Secrets."
    repo, branch = _repo_branch()
    url = f"https://api.github.com/repos/{repo}/contents/{DATA_ROOT}/{rel_path}"
    content_str = json.dumps(obj, ensure_ascii=False, indent=2)
    payload = {
        "message": mensagem,
        "content": base64.b64encode(content_str.encode("utf-8")).decode("utf-8"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    try:
        resp = requests.put(url, headers=headers, json=payload, timeout=15)
    except requests.RequestException as e:
        return False, f"Falha ao salvar no GitHub: {e}"
    if resp.status_code in (200, 201):
        return True, None
    return False, f"GitHub respondeu {resp.status_code}: {resp.text[:200]}"


def _github_delete(rel_path: str, sha: str, mensagem: str):
    headers = _headers()
    if not headers:
        return False, "GITHUB_TOKEN não configurado nos Secrets."
    repo, branch = _repo_branch()
    url = f"https://api.github.com/repos/{repo}/contents/{DATA_ROOT}/{rel_path}"
    payload = {"message": mensagem, "sha": sha, "branch": branch}
    try:
        resp = requests.delete(url, headers=headers, json=payload, timeout=15)
    except requests.RequestException as e:
        return False, f"Falha ao apagar no GitHub: {e}"
    if resp.status_code in (200, 204):
        return True, None
    return False, f"GitHub respondeu {resp.status_code}: {resp.text[:200]}"


def _github_list_dir(rel_dir: str):
    headers = _headers()
    if not headers:
        return None
    repo, branch = _repo_branch()
    url = f"https://api.github.com/repos/{repo}/contents/{DATA_ROOT}/{rel_dir}"
    try:
        resp = requests.get(url, headers=headers, params={"ref": branch}, timeout=10)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        return [item['name'] for item in resp.json() if item.get('type') == 'file']
    except Exception:
        return None


# ---------------------------------------------------------------------------
# I/O local (fallback / cache de leitura)
# ---------------------------------------------------------------------------

def _local_full_path(rel_path: str) -> str:
    return os.path.join(LOCAL_ROOT, rel_path)


def _local_get(rel_path: str):
    full = _local_full_path(rel_path)
    if not os.path.exists(full):
        return None
    try:
        with open(full, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _local_put(rel_path: str, obj: dict):
    full = _local_full_path(rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _local_list_dir(rel_dir: str):
    full = _local_full_path(rel_dir)
    if not os.path.isdir(full):
        return []
    return [f for f in os.listdir(full) if f.endswith('.json')]


# ---------------------------------------------------------------------------
# Leitura/gravação combinadas (remoto é a fonte de verdade quando
# configurado; local funciona como cache de leitura + fallback completo
# quando não há GITHUB_TOKEN, ex.: desenvolvimento local da Ingrid)
# ---------------------------------------------------------------------------

def _read_file(rel_path: str):
    """Retorna (obj, erro) -- ver docstring de _github_get para o
    significado de erro (None = leitura conclusiva; string = ambígua)."""
    if is_remoto():
        obj, sha, erro = _github_get(rel_path)
        if obj is not None:
            _local_put(rel_path, obj)  # mantém cache local em dia
            return obj, None
        if erro is not None:
            # Leitura ambígua: não sabemos se existe ou não. Devolvemos o
            # cache local (se houver) só para exibição, mas propagamos o
            # erro -- quem grava não pode tratar isso como "arquivo novo".
            return _local_get(rel_path), erro
        # Confirmado (404): não existe remotamente ainda.
        return _local_get(rel_path), None
    return _local_get(rel_path), None


def _write_file(rel_path: str, obj: dict, mensagem: str):
    _local_put(rel_path, obj)  # grava local sempre (cache/dev)
    if is_remoto():
        _, sha, _erro = _github_get(rel_path)
        ok, err = _github_put(rel_path, obj, sha, mensagem)
        if not ok and err and err.startswith('GitHub respondeu 409'):
            # 409 = o sha que mandamos ficou desatualizado entre o GET e o
            # PUT acima -- outra gravação no MESMO arquivo aconteceu bem
            # no meio (ex.: duplo clique num botão de salvar, duas abas
            # abertas, dois cliques em sequência rápida enquanto a pessoa
            # não tinha certeza se o primeiro tinha funcionado -- caso
            # real da Ingrid em 31/08/2026, usando "Corrigir a semana"
            # duas vezes seguidas). Busca o sha ATUAL de novo e tenta
            # gravar mais uma vez antes de desistir -- sem isso, a
            # gravação ficava só no cache local (efêmero no Streamlit
            # Cloud), sem persistir de verdade, até a pessoa notar o aviso
            # e clicar de novo manualmente.
            _, sha2, _erro2 = _github_get(rel_path)
            ok, err = _github_put(rel_path, obj, sha2, mensagem)
        return ok, err
    return True, None


# ---------------------------------------------------------------------------
# Cache de leitura por execução do Streamlit (evita 1 chamada de API por
# rerun do script — o Streamlit reexecuta o arquivo inteiro a cada
# interação). Invalidado explicitamente após qualquer gravação.
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30, show_spinner=False)
def _load_current_cached(modulo: str, tipo_periodo: str, periodo_ref: str):
    """Devolve (registro, erro) -- ver load_current_com_erro() abaixo pro
    significado de cada um. Guardado como tupla numa cache só (em vez de
    duas caches separadas) pra não duplicar a chamada à API do GitHub."""
    rel_path = _path_for(modulo, tipo_periodo, periodo_ref)
    obj, erro = _read_file(rel_path)
    return (obj.get('current') if obj else None), erro


def _invalidate_cache():
    try:
        _load_current_cached.clear()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def save_record(modulo: str, tipo_periodo: str, periodo_ref: str, valores: dict,
                 usuario: str = None, data_referencia: str = None) -> dict:
    """Salva um novo valor para (modulo, tipo_periodo, periodo_ref).

    Não sobrescreve o histórico: se já existir um registro 'current' para
    essa combinação, ele é movido para 'history' antes de gravar o novo.
    Retorna o registro recém-salvo (com id, versao, criado_em, atualizado_em).
    """
    rel_path = _path_for(modulo, tipo_periodo, periodo_ref)
    existing, erro_leitura = _read_file(rel_path)

    agora = _now_iso()
    if existing and existing.get('current'):
        anterior = existing['current']
        history = list(existing.get('history', []))
        history.append(anterior)
        registro_id = anterior.get('id') or str(uuid.uuid4())
        criado_em = anterior.get('criado_em', agora)
        versao = int(anterior.get('versao', 0)) + 1
    else:
        history = []
        registro_id = str(uuid.uuid4())
        criado_em = agora
        versao = 1

    novo = {
        'id': registro_id,
        'modulo_origem': modulo,
        'tipo_periodo': tipo_periodo,
        'periodo_ref': periodo_ref,
        'data_referencia': data_referencia or agora[:10],
        'criado_em': criado_em,
        'atualizado_em': agora,
        'usuario': usuario or 'não identificado',
        'versao': versao,
        'valores': valores,
    }

    obj = {'current': novo, 'history': history}
    mensagem = f"{modulo}: atualiza {tipo_periodo} {periodo_ref} (v{versao})"

    if erro_leitura is not None:
        # Não conseguimos confirmar com certeza, antes de gravar, se já
        # existe um registro remoto para este período (leitura ambígua:
        # rede, GitHub fora do ar, token sem permissão, etc. -- ver
        # _github_get). 'existing' acima pode ter vindo do cache local
        # (possivelmente desatualizado ou vazio), então 'history'/'versao'
        # calculados a partir dele NÃO são confiáveis. Gravar no GitHub
        # nessa condição arriscaria apagar histórico real que não
        # conseguimos ler. Por segurança, guardamos apenas no cache local
        # (não perde o dado desta gravação) e NÃO tocamos no GitHub --
        # sinalizamos o erro para o chamador avisar a usuária e permitir
        # tentar de novo.
        _local_put(rel_path, obj)
        _invalidate_cache()
        novo = dict(novo)
        novo['_erro_persistencia_remota'] = (
            f"Não foi possível confirmar o histórico já salvo antes de gravar "
            f"({erro_leitura}). Para não arriscar apagar dados antigos, esta "
            f"gravação ficou só no cache local -- tente novamente em instantes."
        )
        return novo

    ok, err = _write_file(rel_path, obj, mensagem)
    _invalidate_cache()

    if not ok:
        # O registro sempre fica salvo localmente (cache); se a gravação
        # remota falhar, sinalizamos o erro para o chamador decidir como
        # avisar a usuária (ex.: st.warning), mas não perdemos o dado.
        novo = dict(novo)
        novo['_erro_persistencia_remota'] = err
    return novo


def delete_record(modulo: str, tipo_periodo: str, periodo_ref: str) -> tuple:
    """Apaga PERMANENTEMENTE o registro (modulo, tipo_periodo, periodo_ref)
    -- do GitHub (se configurado) e do cache local, junto com todo o
    histórico de versões dele. AÇÃO IRREVERSÍVEL -- diferente de
    save_record() (que nunca apaga, só versiona), esta função existe
    especificamente pra remover registros órfãos/duplicados (ex.: um
    fechamento salvo sob o periodo_ref errado por causa da ambiguidade da
    semana comercial -- ver "🔧 Corrigir a semana" em pages/gerencia.py).
    Só deve ser chamada com confirmação explícita da pessoa usuária na UI,
    nunca automaticamente. Devolve (ok: bool, erro: str|None)."""
    rel_path = _path_for(modulo, tipo_periodo, periodo_ref)
    full = _local_full_path(rel_path)
    if os.path.exists(full):
        try:
            os.remove(full)
        except Exception:
            pass  # segue tentando apagar do GitHub mesmo se o local falhar
    if not is_remoto():
        _invalidate_cache()
        return True, None
    _, sha, erro_leitura = _github_get(rel_path)
    if sha is None:
        _invalidate_cache()
        if erro_leitura:
            return False, f"Não foi possível confirmar o registro no GitHub antes de apagar: {erro_leitura}"
        return True, None  # já não existe remotamente -- nada a fazer
    ok, err = _github_delete(rel_path, sha, f"{modulo}: apaga {tipo_periodo} {periodo_ref}")
    _invalidate_cache()
    return ok, err


def load_current(modulo: str, tipo_periodo: str, periodo_ref: str):
    """Retorna o registro (versão) mais recente, ou None se não houver dado
    salvo para esse módulo/período. Não distingue "nunca foi publicado" de
    "falha ao consultar o GitHub agora" -- quem precisa dessa distinção
    (pra não mostrar "sem dado" quando na real é uma falha de leitura) usa
    load_current_com_erro() abaixo."""
    reg, _erro = _load_current_cached(modulo, tipo_periodo, periodo_ref)
    return reg


def load_current_com_erro(modulo: str, tipo_periodo: str, periodo_ref: str):
    """Como load_current(), mas devolve (registro, erro).

    erro vem preenchido (string) quando a consulta ao GitHub falhou de
    forma AMBÍGUA (rede, token inválido/sem permissão, rate limit, erro
    5xx do lado do GitHub) -- nesse caso NÃO dá pra saber se o dado existe
    ou não, e quem chama não deve tratar isso como "nunca foi publicado"
    (mesma distinção que _github_get já faz internamente, só que até aqui
    ela se perdia -- load_current descartava o erro em silêncio e todo
    "sem dado" na tela podia na real ser uma falha de leitura escondida).
    erro é None quando a consulta foi conclusiva (achou o registro, ou
    confirmou -- 404 -- que ele realmente não existe)."""
    return _load_current_cached(modulo, tipo_periodo, periodo_ref)


def load_history(modulo: str, tipo_periodo: str, periodo_ref: str) -> list:
    """Retorna as versões anteriores (mais antiga -> mais recente), sem
    incluir a versão atual."""
    rel_path = _path_for(modulo, tipo_periodo, periodo_ref)
    obj, _erro = _read_file(rel_path)
    return obj.get('history', []) if obj else []


def load_all_versions(modulo: str, tipo_periodo: str, periodo_ref: str) -> list:
    """Histórico completo incluindo a versão atual, em ordem cronológica
    (mais antiga -> mais recente)."""
    hist = load_history(modulo, tipo_periodo, periodo_ref)
    atual = load_current(modulo, tipo_periodo, periodo_ref)
    return hist + ([atual] if atual else [])


def list_periodos(modulo: str, tipo_periodo: str) -> list:
    """Lista os periodo_ref que têm dado salvo (mais recente primeiro)."""
    rel_dir = f"{modulo}/{tipo_periodo}"
    nomes = None
    if is_remoto():
        nomes = _github_list_dir(rel_dir)
    if nomes is None:
        nomes = _local_list_dir(rel_dir)
    return sorted((n[:-5] for n in nomes if n.endswith('.json')), reverse=True)


def has_data(modulo: str, tipo_periodo: str, periodo_ref: str) -> bool:
    return load_current(modulo, tipo_periodo, periodo_ref) is not None
