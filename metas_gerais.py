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
de 100%, isso é esperado e nunca é limitado -- decisão explícita da Ingrid,
reafirmada em 25/08/2026: "deixa dar mais que 100%, não tem problema").
O "vendido acumulado" real
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

# Realizado da Meta Geral -- PUBLICADO DIRETO AQUI (PDF), independente dos
# módulos Vendedor-Cliente/Quebra usados por outras páginas (pedido
# explícito da Ingrid, 29/08/2026: "não quero que seja a soma a partir do
# módulo vendedor cliente, quero que tenha espaço pra eu adicionar os PDFs
# e ele calcular -- o mesmo para a quebra"). As funções publicar_*_pdf()
# abaixo reaproveitam os MESMOS parsers que Vendedor-Cliente/Quebra já
# usam (parsers_vendedor.parse_totais_vendedor / parser_quebra.parse_quebra)
# -- só a persistência é um módulo à parte, pra publicar aqui nunca
# depender nem sobrescrever o que foi (ou não) publicado naquelas páginas.
MOD_MG_VENDAS = 'metas_gerais_vendas'
MOD_MG_QUEBRA = 'metas_gerais_quebra'


# ---------------------------------------------------------------------------
# Meta (configuração) — a única coisa digitada manualmente nesta tela
# ---------------------------------------------------------------------------

def salvar_meta(tipo_periodo: str, periodo_ref: str, faturamento: float, volume: float,
                 margem_pct: float, quebra_max_cx: float, quebra_max_rs: float = None,
                 quebra_max_pct: float = None, usuario: str = None) -> dict:
    """quebra_max_rs (opcional): teto de Quebra também expresso em R$ (pedido
    Ingrid, 19/08/2026) -- ela pensa/define esse teto em valor, não em
    caixas. É um campo INDEPENDENTE de quebra_max_cx: não converte um no
    outro (não há preço médio por caixa confiável pra isso) -- os dois
    convivem. Quando há Teto em R$ (calculado ou digitado) E realizado de
    Quebra em R$ publicado, o status On Track usa o R$ (não o CX) -- ver
    gerencia.py; quebra_max_cx continua sendo o único usado quando falta
    um dos dois lados em R$.

    quebra_max_pct (opcional, pedido Ingrid 31/08/2026: "o teto de quebra
    é para ser em porcentagem... 0,6% sobre o faturamento"): o teto
    ACEITÁVEL como percentual do Faturamento -- ex.: 0,6. Quando
    preenchido, é a FONTE do quebra_max_rs (gerencia.py calcula
    quebra_max_rs = quebra_max_pct/100 * faturamento META antes de chamar
    esta função, então quebra_max_rs guardado aqui já vem pronto em R$ --
    é a "meta" fixa do período, calculada uma vez sobre o faturamento
    META, sem depender do que acontecer depois). Guardado separado (não só
    o R$ já calculado) pra reabrir o formulário depois mostrando o %
    original digitado, não um % re-derivado. Períodos antigos sem
    quebra_max_pct continuam funcionando normalmente com o quebra_max_rs
    digitado manualmente (não migra dado antigo sozinho)."""
    return ds.save_record(
        modulo=MODULO_META, tipo_periodo=tipo_periodo, periodo_ref=periodo_ref,
        valores={
            'faturamento': faturamento, 'volume': volume,
            'margem_pct': margem_pct, 'quebra_max_cx': quebra_max_cx,
            'quebra_max_rs': quebra_max_rs, 'quebra_max_pct': quebra_max_pct,
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
    """vendedores (por vendedor: fat/vol/custo) do Realizado de Vendas
    publicado direto na Meta Geral (MOD_MG_VENDAS) pra esse mês, na versão
    mais recente cujo timestamp seja <= data_limite -- ou seja, 'o que já
    estava vendido' até aquele momento, reconstruído a partir dos PDFs
    realmente publicados aqui (cada publicação via publicar_vendas_pdf()
    gera uma versão nova via data_store). Não inventa nem interpola nenhum
    número; se não houver nenhuma versão até essa data, devolve {} (sem
    dado ainda naquele momento)."""
    versoes = ds.load_all_versions(MOD_MG_VENDAS, 'mensal', mes_ref)
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
    return (melhor[1].get('valores') or {}).get('vendedores', {}) or {}


def _blocos_semanais_do_mes(mes_ref: str, n_semanas: int = 4) -> list:
    """Divide o mês em `n_semanas` blocos SEQUENCIAIS de dias corridos a
    partir do dia 1 (NÃO são semanas ISO -- não dependem de qual dia da
    semana cai o dia 1). Os primeiros n_semanas-1 blocos têm 7 dias cada;
    o último absorve os dias restantes até o fim do mês (pode ter mais ou
    menos que 7 dias, dependendo do tamanho do mês).

    Isso é de propósito diferente de `_semanas_do_mes` (que usa semanas
    ISO reais e é usado por `_quebra_mes` pra somar relatórios semanais
    publicados por semana ISO -- não pode mudar). Aqui o objetivo é outro:
    dividir o mês em N pedaços de acompanhamento simples e sempre com a
    MESMA quantidade (4, por padrão) independente de como o calendário se
    alinha -- ex.: agosto/2026 tem 4 semanas "completas" nesse sentido
    (dias 1-7, 8-14, 15-21, 22-31), não 6 como semanas ISO reais dariam
    (a semana ISO 31 começa em julho e a 36 termina em setembro)."""
    ini, fim = periodo.intervalo_datas('mensal', mes_ref)
    blocos = []
    inicio_bloco = ini
    for i in range(n_semanas):
        if i == n_semanas - 1:
            fim_bloco = fim  # último bloco absorve o resto do mês
        else:
            fim_bloco = min(inicio_bloco + timedelta(days=6), fim)
        blocos.append((inicio_bloco, fim_bloco))
        inicio_bloco = fim_bloco + timedelta(days=1)
        if inicio_bloco > fim:
            break
    return blocos


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
    'atingimento' = vendido_acumulado ÷ meta_fixa (a meta TOTAL do mês, não
    o esperado daquela semana) -- ex.: meta 18.000.000, vendido acumulado
    12.963.383,34 -> 72%. É simplesmente "quanto da meta já foi batido até
    agora", sem ajustar pelo ritmo esperado da semana.

    O 'label' é a posição da semana DENTRO do mês (ex.: "Semana 01 do mês
    08"). As semanas em si NÃO são semanas ISO -- são blocos sequenciais
    de 7 dias a partir do dia 1 do mês (ver `_blocos_semanais_do_mes`),
    então todo mês sempre tem a mesma quantidade de semanas (4 por
    padrão), em vez de variar conforme o alinhamento do calendário.
    """
    if pcts_semanais is None:
        pcts_semanais = carregar_pcts_semanais(mes_ref)
    meta_fixa = meta_fixa or 0
    hoje = hoje or date.today()
    n_semanas = len(pcts_semanais) or 4
    blocos = _blocos_semanais_do_mes(mes_ref, n_semanas)
    mes_num = int(mes_ref.split('-')[1])

    linhas = []
    pct_acum = 0.0
    for i, (inicio_sem, fim_sem) in enumerate(blocos):
        pct_sem = pcts_semanais[i] if i < len(pcts_semanais) else 0.0
        pct_acum += pct_sem
        esperado = meta_fixa * pct_acum / 100

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

        # Atingimento = % da META TOTAL do mês (não da expectativa daquela
        # semana) -- decisão explícita da Ingrid em 25/08/2026: "a
        # porcentagem de atingido seja em cima da meta total" (ex.: meta
        # 18.000.000, vendido acumulado 12.963.383,34 -> 72%, não a
        # comparação com o esperado daquele ponto do mês).
        atingimento = (vendido / meta_fixa * 100) if (vendido is not None and meta_fixa) else None

        linhas.append({
            'semana': i + 1,
            'periodo_ref': f'{mes_ref}-s{i + 1}',
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


def publicar_vendas_pdf(mes_ref: str, pdf_file, usuario: str = None) -> dict:
    """Lê o PDF 'Lucratividade por Vendedor' e publica como o Realizado
    (Faturamento/Volume/Margem) da Meta Geral pro mês `mes_ref` --
    INDEPENDENTE do módulo Vendedor-Cliente (ver comentário de MOD_MG_VENDAS
    acima). Reaproveita o mesmo parser que a página Vendedor-Cliente já usa
    pros totais (parsers_vendedor.parse_totais_vendedor); só não precisa
    dos PDFs por cliente nem do histórico JSON que aquela página também
    pede, porque a Meta Geral só precisa do total agregado da empresa, não
    do detalhe por cliente."""
    from parsers_vendedor import parse_totais_vendedor
    res = parse_totais_vendedor(pdf_file)
    vendedores = res.get('vendedores') or {}
    total_geral = res.get('total_geral')
    if not total_geral:
        # PDF sem a linha "Total Geral:" reconhecida (ou ilegível nessa
        # linha) -- soma os vendedores manualmente em vez de falhar, mesma
        # agregação que o resto do app já faz a partir de totais por
        # vendedor (ver _agg() em parsers_vendedor.py).
        vol_s   = sum(v.get('vol', 0) or 0 for v in vendedores.values())
        fat_s   = sum(v.get('fat', 0) or 0 for v in vendedores.values())
        custo_s = sum(v.get('custo', 0) or 0 for v in vendedores.values())
        mc_rs_s  = fat_s - custo_s
        mc_pct_s = (mc_rs_s / custo_s * 100) if custo_s else 0.0
        total_geral = {
            'vol': round(vol_s), 'fat': round(fat_s, 2), 'custo': round(custo_s, 2),
            'mc_rs': round(mc_rs_s, 2), 'mc_pct': round(mc_pct_s, 2),
            'resultado_real': round(mc_pct_s + 15, 2),
        }
    return ds.save_record(
        modulo=MOD_MG_VENDAS, tipo_periodo='mensal', periodo_ref=mes_ref,
        valores={
            'total_geral': total_geral,
            'vendedores': vendedores,
            'periodo_pdf': res.get('periodo'),
            'data_emissao_pdf': res.get('data_emissao'),
        },
        usuario=usuario,
    )


def publicar_quebra_pdf(mes_ref: str, pdf_file, usuario: str = None) -> dict:
    """Lê o PDF 'Resumo do Estoque (Quebra)' e publica como o Realizado de
    Quebra da Meta Geral pro mês `mes_ref` -- INDEPENDENTE do módulo Quebra
    usado por pages/4_Quebra_OTHIL.py. Reaproveita o mesmo parser que
    aquela página já usa (parser_quebra.parse_quebra)."""
    from parser_quebra import parse_quebra
    dados = parse_quebra(pdf_file)
    return ds.save_record(
        modulo=MOD_MG_QUEBRA, tipo_periodo='mensal', periodo_ref=mes_ref,
        valores=dados, usuario=usuario,
    )


def realizado_vendas(tipo_periodo: str, periodo_ref: str) -> dict:
    """{faturamento, volume, margem_pct, vendedores: {nome: {fat,vol,custo,mc_rs,mc_pct}},
    completude: 'completo'|'parcial'|'sem_dado'|'erro_leitura', erro_leitura, origem}.

    Meta Geral é independente de Metas Semanais E de Vendedor-Cliente —
    cobre apenas mensal, trimestral, semestral e anual, agregando por mês
    a partir do que foi publicado direto aqui via publicar_vendas_pdf()."""
    meses = _meses_do_periodo(tipo_periodo, periodo_ref)
    fat = vol = custo = 0.0
    vend_agg = {}
    meses_com_dado = []
    # Guarda o 1º erro de leitura AMBÍGUO (rede/token/rate-limit no GitHub)
    # encontrado entre os meses do período -- ver load_current_com_erro().
    # Antes disso usávamos ds.load_current() puro, que descarta erro em
    # silêncio: uma falha transitória de leitura virava "Sem dado publicado
    # ainda" na tela, indistinguível de realmente não ter publicado nada.
    erro_leitura = None
    for mes in meses:
        reg, erro = ds.load_current_com_erro(MOD_MG_VENDAS, 'mensal', mes)
        if erro and erro_leitura is None:
            erro_leitura = erro
        if not reg:
            continue
        tg = reg['valores'].get('total_geral') or {}
        if not tg:
            continue
        meses_com_dado.append(mes)
        fat   += tg.get('fat', 0) or 0
        vol   += tg.get('vol', 0) or 0
        custo += tg.get('custo', 0) or 0
        for nome, v in (reg['valores'].get('vendedores') or {}).items():
            a = vend_agg.setdefault(nome, {'fat': 0.0, 'vol': 0.0, 'custo': 0.0})
            a['fat']   += v.get('fat', 0) or 0
            a['vol']   += v.get('vol', 0) or 0
            a['custo'] += v.get('custo', 0) or 0
    for a in vend_agg.values():
        a['mc_rs']  = a['fat'] - a['custo']
        a['mc_pct'] = (a['mc_rs'] / a['custo'] * 100) if a['custo'] else 0.0

    if not meses_com_dado:
        # Só chama de "sem dado" quando a leitura foi CONCLUSIVA (confirmou
        # que não existe). Se houve erro de leitura ambíguo, não sabemos --
        # não inventa a ausência do dado.
        completude = 'erro_leitura' if erro_leitura else 'sem_dado'
    elif len(meses_com_dado) < len(meses):
        completude = 'parcial'
    else:
        completude = 'completo'

    # +15pp: mesmo ajuste "Resultado Real" aplicado em todo o resto do app
    # (parsers_vendedor._agg, dashboard_diario, xlsx_diario) -- a MC bruta
    # (faturamento - custo) subestima a margem real porque já cobre parte
    # das despesas administrativas/frete/seguro que não aparecem no custo
    # do produto. Sem isso, esta era a única tela mostrando a margem "crua"
    # (ex.: -0,63%) enquanto o resto do app já mostra a versão +15pp.
    margem_pct = ((fat - custo) / custo * 100 + 15) if (custo and meses_com_dado) else None
    return {
        'faturamento': fat if meses_com_dado else None,
        'volume': vol if meses_com_dado else None,
        'margem_pct': margem_pct,
        'vendedores': vend_agg,
        'completude': completude,
        'erro_leitura': erro_leitura,
        'meses_com_dado': meses_com_dado,
        'meses_total': meses,
        'origem': 'PDF Lucratividade por Vendedor (publicado direto na Meta Geral)',
    }


def realizado_quebra(tipo_periodo: str, periodo_ref: str) -> dict:
    """{total_cx, total_custo, completude, erro_leitura, meses_com_dado?, meses_total?}.

    total_custo é None se nenhum mês do período tinha a coluna de custo
    extraída ainda -- nunca inventa um valor parcial silenciosamente.
    Fonte: Realizado de Quebra publicado direto na Meta Geral (PDF), via
    publicar_quebra_pdf() -- independente da página de Quebra."""
    meses = _meses_do_periodo(tipo_periodo, periodo_ref)
    total_cx = 0.0
    total_custo = 0.0
    algum_custo_lido = False
    meses_com_dado = []
    erro_leitura = None
    for mes in meses:
        reg, erro = ds.load_current_com_erro(MOD_MG_QUEBRA, 'mensal', mes)
        if erro and erro_leitura is None:
            erro_leitura = erro
        if not reg:
            continue
        v = reg['valores']
        if v.get('total_cx') is None:
            continue
        meses_com_dado.append(mes)
        total_cx += v.get('total_cx', 0) or 0
        if v.get('total_custo') is not None:
            algum_custo_lido = True
            total_custo += v.get('total_custo')
    if not meses_com_dado:
        completude = 'erro_leitura' if erro_leitura else 'sem_dado'
    elif len(meses_com_dado) < len(meses):
        completude = 'parcial'
    else:
        completude = 'completo'
    return {'total_cx': total_cx if meses_com_dado else None,
            'total_custo': total_custo if (meses_com_dado and algum_custo_lido) else None,
            'completude': completude,
            'erro_leitura': erro_leitura,
            'meses_com_dado': meses_com_dado, 'meses_total': meses}


# ---------------------------------------------------------------------------
# On Track de Quebra — invertido (menor é melhor): a "meta" aqui é um TETO
# máximo aceitável para o período inteiro, não um alvo a alcançar.
# ---------------------------------------------------------------------------

def status_quebra(quebra_max_cx, quebra_realizada_cx, tipo_periodo: str, periodo_ref: str,
                   hoje=None, limiar_verde: float = on_track.LIMIAR_VERDE_PADRAO,
                   limiar_amarelo: float = on_track.LIMIAR_AMARELO_PADRAO,
                   orcamento_ate_agora: float = None) -> dict:
    """`orcamento_ate_agora` (opcional): pedido explícito da Ingrid,
    31/08/2026 -- quando o Teto de Quebra é definido em % do Faturamento
    (ver quebra_max_pct em salvar_meta), o "quanto já podia ter quebrado
    até agora" NÃO deve ser o teto total do período pro-rateado pelo TEMPO
    decorrido (o cálculo padrão abaixo) -- deve ser o percentual aplicado
    sobre o FATURAMENTO REALIZADO até agora ("Mas no ontrack vai sendo
    calculado conforme o faturamento realizado"), porque quebra é
    proporcional a quanto se vendeu, não a quantos dias já passaram no
    calendário. Quem chama (gerencia.py) calcula esse valor
    (quebra_max_pct/100 * faturamento_realizado) e passa aqui pronto; se
    não for passado (None), cai no cálculo por tempo decorrido de sempre
    (teto CX, ou teto R$ sem % definido -- comportamento inalterado)."""
    if not quebra_max_cx:
        return {
            'meta': quebra_max_cx, 'realizado': quebra_realizada_cx,
            'pct_atingido': None, 'status': on_track.STATUS_SEM_META,
            'emoji': on_track.EMOJI[on_track.STATUS_SEM_META],
            'label': on_track.LABEL[on_track.STATUS_SEM_META],
            'projecao_fechamento': None,
        }
    pct_tempo = periodo.pct_tempo_decorrido(tipo_periodo, periodo_ref, hoje=hoje)
    if orcamento_ate_agora is None:
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
