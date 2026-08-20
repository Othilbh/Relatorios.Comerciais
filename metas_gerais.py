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

OnTrack Semanal (quebra da meta MENSAL): a meta mensal de Faturamento
(empresa e, opcionalmente, de cada vendedor) pode ser acompanhada semana a
semana sem nunca mudar de valor -- só a EXPECTATIVA de quanto dela já
deveria ter sido vendida em cada semana muda, via percentuais incrementais
configuráveis (padrão 30/28/25/25, acumulados: 30/58/83/108 -- pode passar
de 100%, isso é esperado e nunca é limitado). O "vendido acumulado" real
usa o histórico versionado do Vendedor-Cliente daquele mês (cada upload
durante o mês vira uma versão datada) -- pega a versão mais recente até o
fim de cada semana, sem inventar número. Só existe pra tipo_periodo
'mensal' (não faz sentido quebrar um trimestre/ano em "semanas 1-4").
"""
from datetime import timedelta, date

import periodo
import on_track
import data_store as ds

MODULO_META = 'metas_gerais_config'
MODULO_META_VENDEDORES = 'metas_gerais_config_vendedores'
MODULO_PCTS_SEMANAIS = 'metas_gerais_pcts_semanais'
PCTS_SEMANAIS_PADRAO = [30.0, 28.0, 25.0, 25.0]

MOD_VENDEDOR_CLIENTE = 'vendedor_cliente'
MOD_QUEBRA = 'quebra'


# ---------------------------------------------------------------------------
# Meta (configuração) — a única coisa digitada manualmente nesta tela
# ---------------------------------------------------------------------------

def salvar_meta(tipo_periodo: str, periodo_ref: str, faturamento: float, volume: float,
                 margem_pct: float, quebra_max_cx: float, quebra_max_rs: float = None,
                 usuario: str = None) -> dict:
    """quebra_max_rs (opcional): teto de Quebra também expresso em R$ (pedido
    Ingrid, 19/08/2026) -- ela pensa/define esse teto em valor, não em
    caixas. É um campo INDEPENDENTE de quebra_max_cx: não converte um no
    outro (não há preço médio por caixa confiável pra isso) -- os dois
    convivem. quebra_max_cx continua sendo o único usado no status On
    Track de Quebra (compara com o realizado, que só vem em CX dos
    relatórios de Quebra); quebra_max_rs só alimenta o cálculo de
    'quanto isso representa em % do faturamento' (ver
    quebra_pct_faturamento abaixo)."""
    return ds.save_record(
        modulo=MODULO_META, tipo_periodo=tipo_periodo, periodo_ref=periodo_ref,
        valores={
            'faturamento': faturamento, 'volume': volume,
            'margem_pct': margem_pct, 'quebra_max_cx': quebra_max_cx,
            'quebra_max_rs': quebra_max_rs,
        },
        usuario=usuario,
    )


def quebra_pct_faturamento(quebra_rs, faturamento_rs):
    """Quanto um valor de Quebra (R$) representa em % do Faturamento (R$).
    Ex.: quebra R$ 80.000,00 sobre meta de faturamento R$ 18.000.000,00 =
    0,44%. None se faltar faturamento ou quebra (evita divisão por zero e
    não inventa um percentual sem as duas pontas)."""
    if not faturamento_rs or quebra_rs is None:
        return None
    return quebra_rs / faturamento_rs * 100


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
# Meta fixa individual de cada vendedor (Faturamento, R$) -- independente da
# meta da empresa (módulo separado), mas mesma mecânica: digitada uma vez
# por período, versionada, nunca é a soma/fatia calculada de outra coisa.
# ---------------------------------------------------------------------------

def salvar_metas_vendedores(tipo_periodo: str, periodo_ref: str, metas: dict,
                             usuario: str = None) -> dict:
    """metas: {nome_vendedor: valor_faturamento_R$}."""
    return ds.save_record(
        modulo=MODULO_META_VENDEDORES, tipo_periodo=tipo_periodo, periodo_ref=periodo_ref,
        valores={'metas': metas}, usuario=usuario,
    )


def carregar_metas_vendedores(tipo_periodo: str, periodo_ref: str) -> dict:
    reg = ds.load_current(MODULO_META_VENDEDORES, tipo_periodo, periodo_ref)
    return (reg['valores'].get('metas') if reg else None) or {}


# ---------------------------------------------------------------------------
# Percentuais semanais (quebra da meta mensal) -- configuração global,
# reaproveitada em todos os meses até a Ingrid decidir mudar.
# ---------------------------------------------------------------------------

def carregar_pcts_semanais(mes_ref: str) -> list:
    """Percentuais semanais configurados para ESSE mês especificamente
    (cada mês tem seu próprio conjunto -- meses diferentes tocam
    quantidades diferentes de semanas ISO, então não faz sentido usar um
    único conjunto global pra todos). Se a Ingrid ainda não configurou
    nada pra esse mês, cai no padrão de 4 semanas (30/28/25/25)."""
    reg = ds.load_current(MODULO_PCTS_SEMANAIS, 'mensal', mes_ref)
    valores = reg['valores'].get('percentuais') if reg else None
    return list(valores) if valores else list(PCTS_SEMANAIS_PADRAO)


def salvar_pcts_semanais(mes_ref: str, percentuais: list, usuario: str = None) -> dict:
    return ds.save_record(
        modulo=MODULO_PCTS_SEMANAIS, tipo_periodo='mensal', periodo_ref=mes_ref,
        valores={'percentuais': percentuais}, usuario=usuario,
    )


# ---------------------------------------------------------------------------
# OnTrack Semanal — quebra da meta MENSAL fixa (Faturamento) por semana
# ---------------------------------------------------------------------------

def _vendido_acumulado_ate(mes_ref: str, data_limite: date) -> dict:
    """totais_dict (por vendedor: fat/vol/custo) do Vendedor-Cliente daquele
    mês, na versão mais recente cujo timestamp seja <= data_limite -- ou
    seja, 'o que já estava vendido' até aquele momento, reconstruído a
    partir dos uploads reais já feitos (cada upload durante o mês gera uma
    versão nova via data_store). Não inventa nem interpola nenhum número;
    se não houver nenhuma versão até essa data, devolve {} (sem dado ainda
    naquele momento)."""
    versoes = ds.load_all_versions(MOD_VENDEDOR_CLIENTE, 'mensal', mes_ref)
    melhor = None
    for v in versoes:
        ts = (v.get('atualizado_em') or v.get('criado_em') or '')[:10]
        if not ts:
            continue
        try:
            data_v = date.fromisoformat(ts)
        except ValueError:
            continue
        if data_v <= data_limite and (melhor is None or data_v >= melhor[0]):
            melhor = (data_v, v)
    if melhor is None:
        return {}
    return (melhor[1].get('valores') or {}).get('totais_dict', {}) or {}


def quebra_semanal_meta(mes_ref: str, meta_fixa, pcts_semanais: list = None,
                         hoje: date = None, vendedor: str = None) -> list:
    """Quebra a meta MENSAL fixa (Faturamento, R$) em checkpoints semanais.

    A meta fixa NUNCA muda -- é sempre a referência de 100%. Os percentuais
    semanais são incrementais e são ACUMULADOS pra saber quanto da meta fixa
    já era esperado até cada semana (podem somar mais ou menos que 100%; o
    acumulado e o atingimento NUNCA são limitados a 100%).

    vendedor=None -> total da empresa (soma de todos os vendedores no
    Vendedor-Cliente). vendedor='Nome' -> só aquele vendedor -- nesse caso
    `meta_fixa` deve ser a meta fixa DELE (não a da empresa).

    Retorna uma linha por semana do mês:
      {'semana', 'periodo_ref', 'label', 'pct_semana', 'pct_acumulado',
       'esperado_acumulado', 'vendido_acumulado' (None se a semana ainda
       não começou), 'atingimento' (None se não dá pra calcular)}.

    O 'label' é a posição da semana DENTRO do mês (ex.: "Semana 01 do mês
    08"), não o número da semana ISO (ex.: "Semana 31/2026") -- uma semana
    ISO pode pertencer a dois meses (começar num, terminar no outro), e
    numerar pela semana ISO ficava confuso pra acompanhar mês a mês.
    """
    if pcts_semanais is None:
        pcts_semanais = carregar_pcts_semanais(mes_ref)
    meta_fixa = meta_fixa or 0
    hoje = hoje or date.today()
    semanas = _semanas_do_mes(mes_ref)
    mes_num = int(mes_ref.split('-')[1])

    linhas = []
    pct_acum = 0.0
    for i, slug in enumerate(semanas):
        pct_sem = pcts_semanais[i] if i < len(pcts_semanais) else 0.0
        pct_acum += pct_sem
        esperado = meta_fixa * pct_acum / 100

        inicio_sem, fim_sem = periodo.intervalo_datas('semanal', slug)
        if hoje < inicio_sem:
            vendido = None  # semana ainda não começou -- não há como ter dado
        else:
            totais = _vendido_acumulado_ate(mes_ref, min(fim_sem, hoje))
            # totais vazio cobre tanto "nenhuma publicação ainda" quanto
            # "publicação existe mas sem vendedores" -- não dá pra distinguir
            # dos dois "vendeu 0", então trata como sem dado (None) em vez de
            # mostrar um 0 enganoso.
            if not totais:
                vendido = None
            elif vendedor is None:
                vendido = sum(v.get('fat', 0) or 0 for v in totais.values())
            else:
                vendido = (totais.get(vendedor) or {}).get('fat')

        atingimento = (vendido / esperado * 100) if (vendido is not None and esperado) else None

        linhas.append({
            'semana': i + 1,
            'periodo_ref': slug,
            'label': f'Semana {i + 1:02d} do mês {mes_num:02d}',
            'pct_semana': pct_sem,
            'pct_acumulado': pct_acum,
            'esperado_acumulado': esperado,
            'vendido_acumulado': vendido,
            'atingimento': atingimento,
        })
    return linhas


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
