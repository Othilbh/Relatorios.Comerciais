"""Meta Geral — painel consolidado da EMPRESA (Faturamento / Volume /
Margem / Quebra), com Meta / Realizado / % Atingimento / On Track /
Comparativo / Evolução / Projeção, mais ranking de vendedores com
drill-down individual.

Meta Geral é um conceito INDEPENDENTE de Metas Semanais (metas semanais são
metas operacionais por produto; Meta Geral é o alvo financeiro da empresa
em mensal/trimestral/semestral/anual — não existe versão semanal aqui, e
nada deste módulo lê dado de metas_semanais_fechamento).

O "Realizado" NÃO é digitado nesta tela — é agregado automaticamente dos
módulos que já publicam esses números (evita divergência entre painéis e
trabalho duplicado de digitação):

  Faturamento / Volume (CX) / Margem %:
    Vendedor-Cliente (vendedor_cliente, mensal) -> totais_dict (por
    vendedor), somado mês a mês quando o período cobre mais de um mês.

  Quebra (CX quebradas):
    - mensal:                     Quebra (quebra) -> total_cx
    - trimestral/semestral/anual: soma dos registros mensais de Quebra que
                                   caem dentro do período

Somente a "Meta" (alvo) de cada indicador é configurada nesta tela — fica
salva com histórico versionado via data_store (mudar a meta no meio do
período não apaga o valor anterior).
"""
from datetime import timedelta

import periodo
import on_track
import data_store as ds

MODULO_META = 'metas_gerais_config'

MOD_VENDEDOR_CLIENTE = 'vendedor_cliente'
MOD_QUEBRA = 'quebra'


# ---------------------------------------------------------------------------
# Meta (configuração) — a única coisa digitada manualmente nesta tela
# ---------------------------------------------------------------------------

def salvar_meta(tipo_periodo: str, periodo_ref: str, faturamento: float, volume: float,
                 margem_pct: float, quebra_max_cx: float, usuario: str = None) -> dict:
    return ds.save_record(
        modulo=MODULO_META, tipo_periodo=tipo_periodo, periodo_ref=periodo_ref,
        valores={
            'faturamento': faturamento, 'volume': volume,
            'margem_pct': margem_pct, 'quebra_max_cx': quebra_max_cx,
        },
        usuario=usuario,
    )


def carregar_meta(tipo_periodo: str, periodo_ref: str):
    reg = ds.load_current(MODULO_META, tipo_periodo, periodo_ref)
    return reg['valores'] if reg else None


def historico_meta(tipo_periodo: str, periodo_ref: str) -> list:
    """Versões ANTERIORES da meta deste período (mais antiga -> mais
    recente; não inclui a versão atual, que já vem de carregar_meta). Usa
    o histórico versionado do data_store -- salvar uma meta nova nunca
    apaga a anterior, ela só passa a aparecer aqui."""
    return ds.load_history(MODULO_META, tipo_periodo, periodo_ref)


# ---------------------------------------------------------------------------
# Realizado — agregação a partir dos módulos que já existem
# ---------------------------------------------------------------------------

def _meses_do_periodo(tipo_periodo: str, periodo_ref: str) -> list:
    """Lista de periodo_ref 'mensal' (YYYY-MM) cobertos pelo período dado."""
    if tipo_periodo == 'mensal':
        return [periodo_ref]
    ini, fim = periodo.intervalo_datas(tipo_periodo, periodo_ref)
    meses = []
    d = ini.replace(day=1)
    while d <= fim:
        meses.append(periodo.periodo_ref('mensal', d))
        d = d.replace(year=d.year + 1, month=1) if d.month == 12 else d.replace(month=d.month + 1)
    return meses


def realizado_vendas(tipo_periodo: str, periodo_ref: str) -> dict:
    """{faturamento, volume, margem_pct, vendedores: {nome: {fat,vol,custo,mc_rs,mc_pct}},
    completude: 'completo'|'parcial'|'sem_dado', origem}.

    Meta Geral é independente de Metas Semanais — cobre apenas mensal,
    trimestral, semestral e anual, agregando por mês via Vendedor-Cliente."""
    meses = _meses_do_periodo(tipo_periodo, periodo_ref)
    fat = vol = custo = 0.0
    vend_agg = {}
    meses_com_dado = []
    for mes in meses:
        reg = ds.load_current(MOD_VENDEDOR_CLIENTE, 'mensal', mes)
        if not reg:
            continue
        totais_dict = reg['valores'].get('totais_dict', {}) or {}
        if not totais_dict:
            continue
        meses_com_dado.append(mes)
        for nome, v in totais_dict.items():
            a = vend_agg.setdefault(nome, {'fat': 0.0, 'vol': 0.0, 'custo': 0.0})
            a['fat']   += v.get('fat', 0) or 0
            a['vol']   += v.get('vol', 0) or 0
            a['custo'] += v.get('custo', 0) or 0
            fat   += v.get('fat', 0) or 0
            vol   += v.get('vol', 0) or 0
            custo += v.get('custo', 0) or 0
    for a in vend_agg.values():
        a['mc_rs']  = a['fat'] - a['custo']
        a['mc_pct'] = (a['mc_rs'] / a['custo'] * 100) if a['custo'] else 0.0

    if not meses_com_dado:
        completude = 'sem_dado'
    elif len(meses_com_dado) < len(meses):
        completude = 'parcial'
    else:
        completude = 'completo'

    margem_pct = ((fat - custo) / custo * 100) if (custo and meses_com_dado) else None
    return {
        'faturamento': fat if meses_com_dado else None,
        'volume': vol if meses_com_dado else None,
        'margem_pct': margem_pct,
        'vendedores': vend_agg,
        'completude': completude,
        'meses_com_dado': meses_com_dado,
        'meses_total': meses,
        'origem': 'Vendedor-Cliente (agregado por mês)',
    }


def _semanas_do_mes(mes_ref: str) -> list:
    """Lista (sem repetição, em ordem) das semanas ISO ('YYYY-Www') que
    tocam o mês `mes_ref` ('YYYY-MM'). Uma semana ISO pode começar num mês
    e terminar no seguinte -- nesse caso ela conta para os dois meses (não
    há como fatiar uma semana ao meio sem dado diário, que este app não
    guarda; é a mesma aproximação usada em periodo_ano_anterior)."""
    ini, fim = periodo.intervalo_datas('mensal', mes_ref)
    semanas = []
    d = ini
    while d <= fim:
        s = periodo.periodo_ref('semanal', d)
        if s not in semanas:
            semanas.append(s)
        d += timedelta(days=1)
    return semanas


def _quebra_mes(mes_ref: str):
    """Total de Quebra (CX) de um mês, ou None se não houver nenhum dado.

    O módulo de Quebra (pages/4_Quebra_OTHIL.py) permite publicar tanto em
    modo Semanal quanto Mensal (a Ingrid escolhe a aba na hora do upload).
    Na prática, o uso real tem sido sempre pela aba Semanal -- então exigir
    um registro 'mensal' aqui (como este módulo fazia antes) deixava o
    indicador de Quebra sempre "Sem dado" no painel de Meta Geral,
    mesmo com quebra publicada normalmente todo período. Por isso: usa o
    registro mensal direto se existir (compatível com quem publica em modo
    Mensal); senão, soma as semanas ISO que tocam o mês."""
    reg = ds.load_current(MOD_QUEBRA, 'mensal', mes_ref)
    if reg and reg['valores'].get('total_cx') is not None:
        return reg['valores'].get('total_cx', 0) or 0

    total = 0.0
    alguma_semana_com_dado = False
    for semana in _semanas_do_mes(mes_ref):
        reg_sem = ds.load_current(MOD_QUEBRA, 'semanal', semana)
        if reg_sem and reg_sem['valores'].get('total_cx') is not None:
            alguma_semana_com_dado = True
            total += reg_sem['valores'].get('total_cx', 0) or 0
    return total if alguma_semana_com_dado else None


def realizado_quebra(tipo_periodo: str, periodo_ref: str) -> dict:
    """{total_cx, completude, meses_com_dado?, meses_total?}."""
    meses = _meses_do_periodo(tipo_periodo, periodo_ref)
    total = 0.0
    meses_com_dado = []
    for mes in meses:
        total_mes = _quebra_mes(mes)
        if total_mes is not None:
            meses_com_dado.append(mes)
            total += total_mes
    if not meses_com_dado:
        completude = 'sem_dado'
    elif len(meses_com_dado) < len(meses):
        completude = 'parcial'
    else:
        completude = 'completo'
    return {'total_cx': total if meses_com_dado else None, 'completude': completude,
            'meses_com_dado': meses_com_dado, 'meses_total': meses}


# ---------------------------------------------------------------------------
# On Track de Quebra — invertido (menor é melhor): a "meta" aqui é um TETO
# máximo aceitável para o período inteiro, não um alvo a alcançar.
# ---------------------------------------------------------------------------

def status_quebra(quebra_max_cx, quebra_realizada_cx, tipo_periodo: str, periodo_ref: str,
                   hoje=None, limiar_verde: float = on_track.LIMIAR_VERDE_PADRAO,
                   limiar_amarelo: float = on_track.LIMIAR_AMARELO_PADRAO) -> dict:
    if not quebra_max_cx:
        return {
            'meta': quebra_max_cx, 'realizado': quebra_realizada_cx,
            'pct_atingido': None, 'status': on_track.STATUS_SEM_META,
            'emoji': on_track.EMOJI[on_track.STATUS_SEM_META],
            'label': on_track.LABEL[on_track.STATUS_SEM_META],
            'projecao_fechamento': None,
        }
    pct_tempo = periodo.pct_tempo_decorrido(tipo_periodo, periodo_ref, hoje=hoje)
    orcamento_ate_agora = quebra_max_cx * pct_tempo

    if quebra_realizada_cx is None:
        ratio = None
    elif quebra_realizada_cx <= 0:
        ratio = 2.0  # nenhuma quebra ainda = ótimo
    elif orcamento_ate_agora > 0:
        ratio = orcamento_ate_agora / quebra_realizada_cx
    else:
        ratio = None  # período ainda não começou e já há quebra registrada (raro)

    if ratio is None:
        status = on_track.STATUS_SEM_META
    elif ratio >= limiar_verde:
        status = on_track.STATUS_VERDE
    elif ratio >= limiar_amarelo:
        status = on_track.STATUS_ATENCAO
    else:
        status = on_track.STATUS_FORA

    projecao = (quebra_realizada_cx / pct_tempo) if (pct_tempo and pct_tempo > 0
                                                       and quebra_realizada_cx is not None) else None
    return {
        'meta': quebra_max_cx, 'realizado': quebra_realizada_cx,
        'pct_atingido': (quebra_realizada_cx / quebra_max_cx) if quebra_realizada_cx is not None else None,
        'status': status, 'emoji': on_track.EMOJI[status], 'label': on_track.LABEL[status],
        'projecao_fechamento': projecao,
    }
