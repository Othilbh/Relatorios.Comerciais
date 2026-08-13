"""Metas Gerais — painel consolidado da EMPRESA (Faturamento / Volume /
Margem / Quebra), com Meta / Realizado / % Atingimento / On Track /
Comparativo / Evolução / Projeção, mais ranking de vendedores com
drill-down individual.

O "Realizado" NÃO é digitado nesta tela — é agregado automaticamente dos
módulos que já publicam esses números (evita divergência entre painéis e
trabalho duplicado de digitação):

  Faturamento / Volume (CX) / Margem %:
    - semanal:                    Metas Semanais (metas_semanais_fechamento)
                                   -> totais_rs.total_geral / totais_rs.vendedores
    - mensal/trimestral/semestral/anual:
                                   Vendedor-Cliente (vendedor_cliente, mensal)
                                   -> totais_dict (por vendedor), somado mês a
                                   mês quando o período cobre mais de um mês

  Quebra (CX quebradas):
    - semanal / mensal:           Quebra (quebra) -> total_cx
    - trimestral/semestral/anual: soma dos registros mensais de Quebra que
                                   caem dentro do período

Somente a "Meta" (alvo) de cada indicador é configurada nesta tela — fica
salva com histórico versionado via data_store (mudar a meta no meio do
período não apaga o valor anterior).
"""
import periodo
import on_track
import data_store as ds

MODULO_META = 'metas_gerais_config'

MOD_METAS_SEMANAIS = 'metas_semanais_fechamento'
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
    completude: 'completo'|'parcial'|'sem_dado', origem}."""
    if tipo_periodo == 'semanal':
        reg = ds.load_current(MOD_METAS_SEMANAIS, 'semanal', periodo_ref)
        if not reg:
            return {'faturamento': None, 'volume': None, 'margem_pct': None,
                     'vendedores': {}, 'completude': 'sem_dado', 'origem': 'Metas Semanais'}
        totais_rs = reg['valores'].get('totais_rs', {}) or {}
        tg = totais_rs.get('total_geral', {}) or {}
        vend = totais_rs.get('vendedores', {}) or {}
        return {
            'faturamento': tg.get('fat'), 'volume': tg.get('vol'), 'margem_pct': tg.get('mc_pct'),
            'vendedores': vend, 'completude': 'completo' if tg else 'sem_dado',
            'origem': 'Metas Semanais (semana fechada)',
        }

    # mensal / trimestral / semestral / anual -> agrega por mês via Vendedor-Cliente
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


def realizado_quebra(tipo_periodo: str, periodo_ref: str) -> dict:
    """{total_cx, completude, meses_com_dado?, meses_total?}."""
    if tipo_periodo in ('semanal', 'mensal'):
        reg = ds.load_current(MOD_QUEBRA, tipo_periodo, periodo_ref)
        if reg and reg['valores'].get('total_cx') is not None:
            return {'total_cx': reg['valores'].get('total_cx', 0), 'completude': 'completo'}
        return {'total_cx': None, 'completude': 'sem_dado'}

    meses = _meses_do_periodo(tipo_periodo, periodo_ref)
    total = 0.0
    meses_com_dado = []
    for mes in meses:
        reg = ds.load_current(MOD_QUEBRA, 'mensal', mes)
        if reg and reg['valores'].get('total_cx') is not None:
            meses_com_dado.append(mes)
            total += reg['valores'].get('total_cx', 0) or 0
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
