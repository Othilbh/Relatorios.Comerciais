"""Componente central de PERÍODO — padrão único para todo o app.

Define os 5 tipos de período exigidos (semanal, mensal, trimestral,
semestral, anual), a representação textual estável de cada período
(`periodo_ref`, usada como chave de persistência e como parte do nome de
arquivo salvo pelo data_store), rótulos legíveis em português, cálculo do
período anterior e do mesmo período no ano anterior (para os
comparativos), e o percentual de tempo decorrido dentro do período (usado
pelo componente On Track).

Formato de periodo_ref por tipo:
  semanal:     "2026-W33"   (semana ISO)
  mensal:      "2026-08"
  trimestral:  "2026-Q3"    (Q1=jan-mar, Q2=abr-jun, Q3=jul-set, Q4=out-dez)
  semestral:   "2026-S2"    (S1=jan-jun, S2=jul-dez)
  anual:       "2026"
"""
from datetime import date, timedelta

TIPOS_PERIODO = ['semanal', 'mensal', 'trimestral', 'semestral', 'anual']

_MESES_PT = [
    'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
    'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
]


def _hoje(hoje=None) -> date:
    return hoje if hoje else date.today()


# ---------------------------------------------------------------------------
# periodo_ref <-> data
# ---------------------------------------------------------------------------

def periodo_ref(tipo: str, referencia: date) -> str:
    """Calcula o periodo_ref (chave estável) que contém a data `referencia`."""
    if tipo == 'semanal':
        ano_iso, semana_iso, _ = referencia.isocalendar()
        return f"{ano_iso}-W{semana_iso:02d}"
    if tipo == 'mensal':
        return f"{referencia.year}-{referencia.month:02d}"
    if tipo == 'trimestral':
        trimestre = (referencia.month - 1) // 3 + 1
        return f"{referencia.year}-Q{trimestre}"
    if tipo == 'semestral':
        semestre = 1 if referencia.month <= 6 else 2
        return f"{referencia.year}-S{semestre}"
    if tipo == 'anual':
        return f"{referencia.year}"
    raise ValueError(f"tipo de período inválido: {tipo}")


def periodo_atual(tipo: str, hoje=None) -> str:
    return periodo_ref(tipo, _hoje(hoje))


def intervalo_datas(tipo: str, ref: str) -> tuple[date, date]:
    """Retorna (data_inicio, data_fim) do período representado por `ref`."""
    if tipo == 'semanal':
        ano_s, semana_s = ref.split('-W')
        ano, semana = int(ano_s), int(semana_s)
        inicio = date.fromisocalendar(ano, semana, 1)
        fim = date.fromisocalendar(ano, semana, 7)
        return inicio, fim
    if tipo == 'mensal':
        ano_s, mes_s = ref.split('-')
        ano, mes = int(ano_s), int(mes_s)
        inicio = date(ano, mes, 1)
        fim = date(ano + (1 if mes == 12 else 0), (mes % 12) + 1, 1) - timedelta(days=1)
        return inicio, fim
    if tipo == 'trimestral':
        ano_s, q_s = ref.split('-Q')
        ano, q = int(ano_s), int(q_s)
        mes_ini = (q - 1) * 3 + 1
        inicio = date(ano, mes_ini, 1)
        mes_fim = mes_ini + 2
        fim = date(ano + (1 if mes_fim > 12 else 0), ((mes_fim - 1) % 12) + 1, 1)
        # avança pro último dia do mes_fim
        prox_mes = mes_fim + 1
        fim = date(ano + (1 if prox_mes > 12 else 0), ((prox_mes - 1) % 12) + 1, 1) - timedelta(days=1)
        return inicio, fim
    if tipo == 'semestral':
        ano_s, s_s = ref.split('-S')
        ano, s = int(ano_s), int(s_s)
        if s == 1:
            return date(ano, 1, 1), date(ano, 6, 30)
        return date(ano, 7, 1), date(ano, 12, 31)
    if tipo == 'anual':
        ano = int(ref)
        return date(ano, 1, 1), date(ano, 12, 31)
    raise ValueError(f"tipo de período inválido: {tipo}")


# ---------------------------------------------------------------------------
# navegação entre períodos
# ---------------------------------------------------------------------------

def periodo_anterior(tipo: str, ref: str) -> str:
    """periodo_ref do período imediatamente anterior ao mesmo tipo."""
    inicio, _ = intervalo_datas(tipo, ref)
    dia_anterior = inicio - timedelta(days=1)
    return periodo_ref(tipo, dia_anterior)


def periodo_posterior(tipo: str, ref: str) -> str:
    """periodo_ref do período imediatamente seguinte ao mesmo tipo."""
    _, fim = intervalo_datas(tipo, ref)
    dia_seguinte = fim + timedelta(days=1)
    return periodo_ref(tipo, dia_seguinte)


def periodo_ano_anterior(tipo: str, ref: str) -> str:
    """periodo_ref do mesmo período (semana/mês/trimestre/semestre), um ano
    antes — usado para comparação tipo 'Agosto/2026 x Agosto/2025'.
    Para semanal, usa a mesma semana ISO no ano anterior (aproximação —
    calendários ISO podem ter 52 ou 53 semanas)."""
    if tipo == 'anual':
        return str(int(ref) - 1)
    if tipo == 'semanal':
        ano_s, semana_s = ref.split('-W')
        ano, semana = int(ano_s), int(semana_s)
        semana = min(semana, 52)
        return f"{ano - 1}-W{semana:02d}"
    prefixo, resto = ref.split('-', 1)
    return f"{int(prefixo) - 1}-{resto}"


def listar_periodos(tipo: str, n: int = 12, ate: str = None) -> list[str]:
    """Lista os `n` periodo_ref mais recentes (mais recente primeiro),
    terminando no período `ate` (ou no período atual, se omitido)."""
    ref = ate or periodo_atual(tipo)
    out = [ref]
    for _ in range(n - 1):
        ref = periodo_anterior(tipo, ref)
        out.append(ref)
    return out


# ---------------------------------------------------------------------------
# rótulos legíveis
# ---------------------------------------------------------------------------

def rotulo(tipo: str, ref: str) -> str:
    """Rótulo em português para exibição (ex.: 'Agosto/2026',
    '3º trimestre/2026', 'Semana 33/2026', '2º semestre/2026', '2026')."""
    if tipo == 'semanal':
        ano_s, semana_s = ref.split('-W')
        return f"Semana {int(semana_s)}/{ano_s}"
    if tipo == 'mensal':
        ano_s, mes_s = ref.split('-')
        return f"{_MESES_PT[int(mes_s) - 1]}/{ano_s}"
    if tipo == 'trimestral':
        ano_s, q_s = ref.split('-Q')
        return f"{q_s}º trimestre/{ano_s}"
    if tipo == 'semestral':
        ano_s, s_s = ref.split('-S')
        return f"{s_s}º semestre/{ano_s}"
    if tipo == 'anual':
        return ref
    raise ValueError(f"tipo de período inválido: {tipo}")


def rotulo_tipo(tipo: str) -> str:
    return {
        'semanal': 'Semanal', 'mensal': 'Mensal', 'trimestral': 'Trimestral',
        'semestral': 'Semestral', 'anual': 'Anual',
    }[tipo]


# ---------------------------------------------------------------------------
# tempo decorrido (para On Track)
# ---------------------------------------------------------------------------

def pct_tempo_decorrido(tipo: str, ref: str, hoje=None) -> float:
    """Fração (0..1) do período já transcorrida até `hoje`. Se o período já
    terminou, retorna 1.0; se ainda não começou, retorna 0.0."""
    inicio, fim = intervalo_datas(tipo, ref)
    hoje = _hoje(hoje)
    total_dias = (fim - inicio).days + 1
    if hoje < inicio:
        return 0.0
    if hoje > fim:
        return 1.0
    decorridos = (hoje - inicio).days + 1
    return max(0.0, min(1.0, decorridos / total_dias))


def periodo_esta_atual(tipo: str, ref: str, hoje=None) -> bool:
    inicio, fim = intervalo_datas(tipo, ref)
    hoje = _hoje(hoje)
    return inicio <= hoje <= fim
