"""Componente central de ON TRACK — padrão único para todo o app.

Regra de negócio (centralizada — antes existiam 4 implementações
divergentes: metas_semanais.py:_on_track_status,
3_Vendedor_Cliente_OTHIL.py:_ot_status, e mais 2 cópias em gerencia.py):

  NÃO é apenas Realizado ÷ Meta. O status considera o quanto já deveria
  ter sido realizado até o momento do período (proporcional ao tempo
  decorrido, via periodo.pct_tempo_decorrido):

    pct_atingido = realizado / meta
    pct_esperado = fração do período já transcorrida
    ratio        = pct_atingido / pct_esperado

    🟢 On Track      se ratio >= LIMIAR_VERDE   (padrão 0.85)
    🟡 Atenção       se ratio >= LIMIAR_AMARELO (padrão 0.55)
    🔴 Fora do Track caso contrário

  Também calcula a projeção de fechamento por extrapolação linear da
  média realizada por dia decorrido até agora (mesma lógica que já existia
  em 3_Vendedor_Cliente_OTHIL.py, agora aplicada a todos os módulos).
"""
import periodo as _periodo

STATUS_VERDE = 'on_track'
STATUS_ATENCAO = 'atencao'
STATUS_FORA = 'fora'
STATUS_SEM_META = 'sem_meta'

EMOJI = {
    STATUS_VERDE: '🟢', STATUS_ATENCAO: '🟡', STATUS_FORA: '🔴',
    STATUS_SEM_META: '⚪',
}
LABEL = {
    STATUS_VERDE: 'On Track', STATUS_ATENCAO: 'Atenção', STATUS_FORA: 'Fora do Track',
    STATUS_SEM_META: 'Sem meta',
}

LIMIAR_VERDE_PADRAO = 0.85
LIMIAR_AMARELO_PADRAO = 0.55


def calcular(meta: float, realizado: float, tipo_periodo: str, periodo_ref: str,
             hoje=None, limiar_verde: float = LIMIAR_VERDE_PADRAO,
             limiar_amarelo: float = LIMIAR_AMARELO_PADRAO,
             pct_tempo_decorrido: float = None) -> dict:
    """
    pct_tempo_decorrido: opcional. Por padrão é calculado a partir do
    calendário (periodo.pct_tempo_decorrido — fração de dias corridos do
    período). Alguns módulos usam uma convenção de tempo diferente (ex.:
    Metas Semanais conta em dias ÚTEIS, 1..5, não dias corridos da semana
    ISO) — nesses casos o chamador pode calcular a própria fração e passar
    aqui, mantendo a mesma lógica central de status/projeção.
    """
    if not meta:
        return {
            'meta': meta, 'realizado': realizado,
            'pct_atingido': None, 'pct_tempo_decorrido': None, 'pct_esperado': None,
            'ratio': None, 'status': STATUS_SEM_META,
            'emoji': EMOJI[STATUS_SEM_META], 'label': LABEL[STATUS_SEM_META],
            'projecao_fechamento': None,
        }

    if pct_tempo_decorrido is not None:
        pct_tempo = max(0.0, min(1.0, pct_tempo_decorrido))
    else:
        pct_tempo = _periodo.pct_tempo_decorrido(tipo_periodo, periodo_ref, hoje=hoje)
    pct_atingido = realizado / meta
    pct_esperado = pct_tempo

    if pct_esperado > 0:
        ratio = pct_atingido / pct_esperado
    else:
        # período ainda não começou (ou começa hoje): não dá pra avaliar
        # ritmo ainda — considera on track se já bateu a meta, senão neutro.
        ratio = 1.0 if pct_atingido >= 1.0 else None

    if ratio is None:
        status = STATUS_SEM_META
    elif ratio >= limiar_verde:
        status = STATUS_VERDE
    elif ratio >= limiar_amarelo:
        status = STATUS_ATENCAO
    else:
        status = STATUS_FORA

    projecao = (realizado / pct_tempo) if pct_tempo and pct_tempo > 0 else None

    return {
        'meta': meta,
        'realizado': realizado,
        'pct_atingido': pct_atingido,
        'pct_tempo_decorrido': pct_tempo,
        'pct_esperado': pct_esperado,
        'ratio': ratio,
        'status': status,
        'emoji': EMOJI[status],
        'label': LABEL[status],
        'projecao_fechamento': projecao,
    }
