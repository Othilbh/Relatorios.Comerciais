"""Motor de cálculo das Metas Semanais.

Regras de negócio (validadas contra os relatórios reais da Ingrid):
  Meta(vendedor, produto)    = round_up(% vendedor × Estoque(produto))
                                (se não for número inteiro, arredonda sempre
                                para cima, ex.: 20,3 -> 21)
  Vendido(vendedor, produto) = soma de Qtd Vendida no relatório de vendas
                                (Lucratividade por Vendedor), agrupada pela
                                SEÇÃO DE VENDEDOR em que a linha aparece
                                (quem efetivamente vendeu) — não pelo
                                "Complemento" (vendedor responsável) do
                                relatório de Estoque.
  Falta(vendedor, produto)   = max(Meta − Vendido, 0)
                                (nunca negativo -- quando já ultrapassou a
                                meta não "falta" nada; ver soma_falta() para
                                agregações que não deixam produtos/vendedores
                                que bateram a meta abaterem o que falta em
                                outros)
  % Atingido                 = Vendido / Meta

'Estoque(produto)' é digitado manualmente pela Ingrid no app (não é mais
extraído automaticamente do PDF de Estoque Físico), pois o snapshot do PDF
pode não refletir o estoque conferido na segunda-feira na hora de bater a
meta.
"""
import datetime
import math
import re
import unicodedata
from parsers import normalize_codigo
# map_vendedor()/VENDOR_ALIASES vêm de parsers_diario -- fonte única. Havia
# uma segunda cópia (divergente) aqui em calc.py que nunca foi atualizada
# quando o Luca foi cadastrado como vendedor, então TODAS as vendas dele
# ficavam silenciosamente de fora do cálculo de Vendido (Meta continuava
# aparecendo normal, só o Vendido zerava) -- consolidado num só lugar para
# não poder mais desalinhar.
from parsers_diario import map_vendedor

# Percentuais fixos (mas editáveis na UI) de cada vendedor sobre o estoque
# atual de cada produto. Não somam 100% — cada vendedor tem uma meta
# independente sobre o estoque total do produto.
VENDEDORES_PADRAO = {
    'Farley': 17,
    'Dora': 17,
    'Afanais': 25,
    'Roni': 25,
    'Reginaldo': 22,
    'Luciano': 7,
    'Juliana': 7,
    'Claudia': 7,
}

# map_vendedor()/VENDOR_ALIASES agora vêm de parsers_diario (import no topo
# do arquivo) -- nomes que não casam com nenhum alias lá são ignorados
# (não fazem parte das metas rastreadas).


def round_up(x: float) -> int:
    """Arredonda sempre para cima quando o resultado não é inteiro
    (ex.: 20,3 -> 21; 20,0 permanece 20)."""
    return math.ceil(x)


# ---------------------------------------------------------------------------
# Semana comercial de Metas Semanais: SÁBADO A SEXTA (redefinido a pedido
# explícito da Ingrid, 31/08/2026: "Precisaremos voltar atrás naquela
# questão da semana terminar e iniciar na sexta feira. A semana terminará
# na sexta. Na sexta mesmo eu coloco os produtos da nova semana, mas só
# começará a contar as vendas de sábado. Então a semana será de sexta a
# sábado" -- ou seja: a sexta continua sendo o dia em que ela fecha a
# semana e já configura os produtos da semana seguinte, mas as VENDAS da
# semana nova só passam a contar a partir do sábado seguinte).
#
# Definição ANTERIOR (sexta a sexta, 18/08/2026 a 30/08/2026): a mesma
# sexta-feira era ao mesmo tempo o dia 7 (fechamento) de uma semana E o
# dia 1 (abertura) da próxima -- essa ambiguidade exigia um band-aid
# (`dia_semana_no_periodo`, ver abaixo) sempre que a tela precisava saber
# a que semana uma sexta-feira específica pertencia. Na definição NOVA, a
# sexta-feira pertence só à semana que abriu no sábado anterior (como seu
# último dia de venda) -- nunca à semana seguinte, que só começa a contar
# no sábado. Isso elimina a ambiguidade na raiz, em vez de contorná-la.
#
# FONTE ÚNICA dessa definição -- tanto pages/metas_semanais.py quanto a
# tela "On Track Atual" de pages/gerencia.py (que exibe snapshots
# publicados de Metas Semanais) importam daqui, pra nunca haver uma
# segunda lógica de semana divergente (reafirmado pela Ingrid em
# 26/08/2026: "não criar uma segunda lógica de semana").
#
# ISSO É ESPECÍFICO DE METAS SEMANAIS -- não usa nem altera periodo.py
# (que continua semana ISO segunda-domingo, usado por Quebra, Vendedor-
# Cliente e outros módulos independentes; escopo confirmado com a
# Ingrid: "Só Metas Semanais").
# ---------------------------------------------------------------------------

def slug_semana(data: datetime.date) -> str:
    """periodo_ref da semana COMERCIAL de Metas Semanais: sábado a sexta (7
    dias corridos). O identificador é a data (ISO, "AAAA-MM-DD") do
    sábado em que as VENDAS da semana começam a contar (mesmo que os
    produtos já tenham sido configurados na sexta anterior, ao fechar a
    semana passada). Se `data` cair num sábado, ela é tratada como o
    sábado de abertura da semana que começa NAQUELA data -- e uma
    sexta-feira pertence sempre à semana que abriu no sábado anterior
    (seu dia de fechamento), nunca à que abre no sábado seguinte."""
    dias_desde_sabado = (data.weekday() - 5) % 7  # segunda=0 ... sábado=5 -> 0
    sabado_abertura = data - datetime.timedelta(days=dias_desde_sabado)
    return sabado_abertura.isoformat()


def intervalo_semana(slug: str):
    """(sabado_abertura, sexta_fechamento) da semana `slug` -- 7 dias
    corridos (sábado a sexta, ambos incluídos)."""
    inicio = datetime.date.fromisoformat(slug)
    fim = inicio + datetime.timedelta(days=6)
    return inicio, fim


def label_semana(slug: str) -> str:
    try:
        inicio, fim = intervalo_semana(slug)
        return f"Semana {inicio.strftime('%d/%m')} a {fim.strftime('%d/%m')}"
    except Exception:
        return slug


def semana_anterior(slug: str) -> str:
    """periodo_ref da semana comercial imediatamente anterior."""
    inicio, _ = intervalo_semana(slug)
    return (inicio - datetime.timedelta(days=7)).isoformat()


def semana_ano_anterior(slug: str) -> str:
    """periodo_ref da mesma semana comercial um ano antes -- aproximação
    por 364 dias (52 semanas exatas) em vez de 365/366, pra preservar a
    sexta-feira como dia da semana (mesma lógica de aproximação que
    periodo.periodo_ano_anterior já usa pro tipo 'semanal')."""
    inicio, _ = intervalo_semana(slug)
    return (inicio - datetime.timedelta(days=364)).isoformat()


def dia_semana_atual(data: datetime.date = None) -> int:
    """Dia de venda (1..6) dentro da semana sábado-a-sexta que contém
    `data` (hoje, por padrão) -- pula domingo, que não tem venda.

    Desde a redefinição de 31/08/2026 (sábado a sexta) não existe mais a
    ambiguidade que a definição anterior (sexta a sexta) tinha numa
    sexta-feira -- cada dia do calendário pertence a exatamente uma
    semana comercial. `dia_semana_no_periodo(slug, ...)` abaixo continua
    disponível para quando já existe uma semana especificamente
    selecionada na tela (histórico/publicação) diferente da semana
    corrente do calendário."""
    if data is None:
        data = datetime.date.today()
    inicio, _ = intervalo_semana(slug_semana(data))
    dia = 0
    d = inicio
    while d <= data:
        if d.weekday() != 6:  # domingo
            dia += 1
        d += datetime.timedelta(days=1)
    return max(1, min(dia, 6))


def dia_semana_no_periodo(slug: str, hoje: datetime.date = None) -> int:
    """Dia de venda (1..6) já decorrido dentro da semana comercial `slug`
    especificamente, até hoje -- ou a semana inteira (6) se `slug` já
    tiver fechado antes de hoje. Sob a definição sábado-a-sexta (a partir
    de 31/08/2026) não há mais a ambiguidade de sexta-feira que motivou a
    criação desta função -- mas ela continua útil quando a tela já tem
    uma semana selecionada (histórico, publicação) diferente da semana
    corrente do calendário, calculando o dia em relação a ESSA semana."""
    if hoje is None:
        hoje = datetime.date.today()
    inicio, fim = intervalo_semana(slug)
    ref = min(hoje, fim)
    if ref < inicio:
        return 1
    dia = 0
    d = inicio
    while d <= ref:
        if d.weekday() != 6:  # domingo
            dia += 1
        d += datetime.timedelta(days=1)
    return max(1, min(dia, 6))


def codigo_matches(codigo_norm: str, entry: str) -> bool:
    """Casa um código normalizado contra uma entrada digitada pela Ingrid.

    Uma entrada terminando em '*' é tratada como prefixo
    (ex.: '3102006*' casa com '3102006', '31020060', '31020071' etc.).
    Sem '*', a entrada precisa casar exatamente (após normalização)."""
    entry = entry.strip()
    if not entry:
        return False
    if entry.endswith('*'):
        prefix = normalize_codigo(entry[:-1])
        return bool(prefix) and codigo_norm.startswith(prefix)
    return codigo_norm == normalize_codigo(entry)


def _normaliza_nome(s: str) -> set:
    """Maiúsculas, sem acento, só letras/números, dividido em palavras --
    para comparar nome de produto configurado contra descrição extraída do
    PDF sem depender de acento/pontuação/ordem exata das palavras."""
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r'[^A-Za-z0-9 ]', ' ', s.upper())
    # Palavras puramente numéricas são mantidas mesmo curtas (ex.: "50",
    # "55", "65", "70") -- são justamente o que distingue variantes de
    # tamanho do mesmo produto (ex.: "AMEIXA 50-55 TANY" vs. "AMEIXA 65/70
    # TANY"); descartá-las faria as duas colapsarem no mesmo conjunto
    # {AMEIXA, TANY} e uma sugerir o código da outra.
    return {w for w in s.split() if len(w) >= 3 or w.isdigit()}


def sugestao_codigo_por_nome(nome_produto: str, vendas_rows) -> list[dict]:
    """Quando o CÓDIGO configurado de um produto não bate com nada nas
    vendas, procura no PDF alguma linha cuja DESCRIÇÃO pareça ser o mesmo
    produto pelo NOME -- para pegar erro de digitação no código.

    A Ingrid digita nome E código de propósito, exatamente para evitar esse
    tipo de erro; se o nome bate com uma linha do PDF mas o código
    configurado não é o código daquela linha, é sinal forte de erro de
    digitação no código (não de o produto realmente não ter vendido nada),
    e por isso vale avisar -- ao contrário de um produto sem nenhuma venda
    e sem nenhum nome parecido no PDF, que é simplesmente uma semana sem
    movimento (não deve gerar aviso nenhum, pra não virar ruído).

    Retorna lista de {'codigo', 'descricao', 'qtde'} (candidatos, por
    volume decrescente) -- lista vazia se não achar nenhum nome parecido.
    """
    alvo = _normaliza_nome(nome_produto)
    if not alvo:
        return []
    candidatos = {}
    for row in vendas_rows:
        desc = row.get('descricao')
        if not desc:
            continue
        palavras_desc = _normaliza_nome(desc)
        if not palavras_desc:
            continue
        # "bate" só se TODAS as palavras significativas do nome configurado
        # aparecem na descrição da linha do PDF (subconjunto completo, não
        # limiar parcial) -- ex.: "PESSEGO FRUITS PONENT" digitado é
        # subconjunto de "PESSEGO FRUITS PONENT BRANCO" no PDF, então bate.
        # Um limiar parcial (ex.: 60% de overlap) já causou falso positivo:
        # "PESSEGO FRUITS PONENT" batendo 2/3 com uma descrição de
        # NECTARINA só porque "FRUITS"/"PONENT" também aparecem lá, sem
        # nenhuma palavra de "PESSEGO" em comum. Exigir o subconjunto
        # completo elimina esse tipo de coincidência parcial.
        if alvo <= palavras_desc:
            cod = row['codigo']
            c = candidatos.setdefault(cod, {'codigo': cod, 'descricao': desc, 'qtde': 0.0})
            c['qtde'] += row['qtde_vendida']
    return sorted(candidatos.values(), key=lambda x: -x['qtde'])


def soma_falta(linhas) -> float:
    """Soma 'Falta' (Meta − Vendido, travado em 0 por linha) de uma lista de
    linhas com chaves 'meta'/'vendido' -- usada para agregar totais (por
    vendedor, por produto, geral). Importante somar já travado em 0 por
    linha, e não travar só o total: senão um produto/vendedor que já
    ultrapassou a meta (que sozinho teria Falta negativa) abateria o que
    ainda falta em outro produto/vendedor, subestimando o total real."""
    return sum(max(l['meta'] - l['vendido'], 0.0) for l in linhas)


def parse_codigos_input(text: str) -> list[str]:
    """Converte o texto digitado (separado por vírgula e/ou linha) em uma
    lista de entradas de código."""
    if not text:
        return []
    parts = []
    for chunk in text.replace('\n', ',').split(','):
        c = chunk.strip()
        if c:
            parts.append(c)
    return parts


def compute_metas(vendas_rows, produtos_config, vendedor_pcts, estoque_rows=None):
    """
    produtos_config: list of {'nome': str, 'codigos': list[str], 'estoque': float}
      'estoque' é a quantidade atual em estoque do produto (em caixas),
      digitada manualmente pela Ingrid no app.
    'codigos' continua sendo usado apenas para casar as vendas (Vendido)
      no relatório de Lucratividade por Vendedor.
    'metas_fixas_ativo' (bool, opcional) + 'metas_fixas' (dict opcional,
      {nome_vendedor: quantidade}): pedido da Ingrid (04/09/2026) --
      "Hoje a meta semanal é definida por porcentagens fixas. Preciso que eu
      consiga momentaneamente definir quantidades por alguns produtos" --
      quando 'metas_fixas_ativo' é True, a Meta de um vendedor QUE TENHA
      entrada em 'metas_fixas' nesse produto usa esse número diretamente, em
      vez de calcular por percentual sobre o estoque; vendedores sem entrada
      em 'metas_fixas' (ou quando 'metas_fixas_ativo' é False/ausente)
      continuam pelo cálculo por percentual de sempre, produto por produto,
      sem afetar os demais. Guardar os dois campos separados (valores vs.
      "ligado") permite desligar e religar sem perder os números já digitados
      -- por isso "momentâneo": reversível a qualquer momento, sem apagar nada.
    vendedor_pcts: dict {nome_vendedor: percentual (0-100)}
    estoque_rows: lista OPCIONAL de linhas do PDF "Estoque Físico"
      (parsers.parse_estoque), cada uma com pelo menos 'codigo', 'qtde_vendida',
      'md_venda' (R$ médio de venda por caixa, já calculado pelo sistema de
      origem -- Mercatus/Previsão, coluna "Md Venda" do relatório -- pedido
      explícito da Ingrid por ser "mais acertivo" que calcular por conta
      própria a partir do PDF de vendas) e 'custo_unitario' (coluna "Custo"
      do mesmo relatório). Casada pelo MESMO código usado pra achar Vendido.
      Se omitida/vazia (PDF de Estoque Físico não enviado -- é opcional
      nesta tela), 'media_rs_cx' e 'media_custo_cx' ficam None em todos os
      produtos.

    Retorna lista de dicts:
      {
        'produto': str, 'estoque_total': float,
        'linhas': [
          {'vendedor', 'pct', 'meta', 'vendido', 'falta', 'atingido'}, ...
        ],
        'media_rs_cx': float | None,
        'media_custo_cx': float | None,
      }
    'media_rs_cx' = média do "Md Venda" (R$/cx, vindo pronto do Estoque
    Físico) das linhas de estoque que casam com os códigos configurados
    desse produto, PONDERADA pela Qtde Vendida de cada linha (um código com
    mais volume pesa mais que um com pouco volume no resultado do produto
    como um todo -- nunca uma média simples entre códigos/SKUs, que
    distorceria quando eles têm volumes bem diferentes). Vem None quando
    nenhuma linha de estoque que bate com esse produto tem Qtde Vendida > 0
    (nada pra ponderar -- nunca inventa um valor), inclusive quando o PDF de
    Estoque Físico simplesmente não foi enviado.
    'media_custo_cx' = mesma lógica acima, mas para 'custo_unitario' (coluna
    "Custo" do Estoque Físico) em vez de "Md Venda".
    """
    estoque_rows = estoque_rows or []
    results = []
    for produto in produtos_config:
        nome = produto['nome']
        entries = produto['codigos']
        estoque_total = float(produto.get('estoque', 0) or 0)

        vendido_por_vendedor = {v: 0.0 for v in vendedor_pcts}
        for row in vendas_rows:
            cn = normalize_codigo(row['codigo'])
            if any(codigo_matches(cn, e) for e in entries):
                disp = map_vendedor(row['vendedor'])
                if disp in vendido_por_vendedor:
                    vendido_por_vendedor[disp] += row['qtde_vendida']

        soma_rs_ponderada = 0.0
        soma_peso = 0.0
        soma_custo_ponderada = 0.0
        soma_peso_custo = 0.0
        for er in estoque_rows:
            cn_er = normalize_codigo(er.get('codigo', ''))
            if not any(codigo_matches(cn_er, e) for e in entries):
                continue
            peso = er.get('qtde_vendida') or 0.0
            md = er.get('md_venda')
            if peso > 0 and md is not None:
                soma_rs_ponderada += md * peso
                soma_peso += peso
            custo_unit = er.get('custo_unitario')
            if peso > 0 and custo_unit is not None:
                soma_custo_ponderada += custo_unit * peso
                soma_peso_custo += peso
        media_rs_cx = (soma_rs_ponderada / soma_peso) if soma_peso else None
        media_custo_cx = (soma_custo_ponderada / soma_peso_custo) if soma_peso_custo else None

        metas_fixas = produto.get('metas_fixas') or {}
        metas_fixas_ativo = bool(produto.get('metas_fixas_ativo'))

        linhas = []
        for vend, pct in vendedor_pcts.items():
            # Meta fixa por vendedor (ver docstring acima) -- só entra em
            # vigor pra quem TEM um número digitado nesse produto E com o
            # botão ligado; os demais vendedores desse mesmo produto (e todo
            # produto sem meta fixa nenhuma) seguem 100% pelo percentual, sem
            # nenhuma mudança de comportamento.
            usa_meta_fixa = metas_fixas_ativo and vend in metas_fixas
            if usa_meta_fixa:
                meta = int(metas_fixas[vend])
            else:
                meta = round_up(pct / 100 * estoque_total)
            vendido = vendido_por_vendedor.get(vend, 0.0)
            # 'Falta' nunca é negativo -- quando o vendido já ultrapassou a
            # meta não "falta" nada, então trava em 0 em vez de mostrar um
            # número negativo (que passa a impressão de meta não batida).
            falta = max(meta - vendido, 0.0)
            atingido = (vendido / meta) if meta else 0.0
            linhas.append({
                'vendedor': vend,
                'pct': pct,
                'meta': meta,
                'meta_fixa': usa_meta_fixa,
                'vendido': vendido,
                'falta': falta,
                'atingido': atingido,
            })

        results.append({
            'produto': nome,
            'estoque_total': estoque_total,
            'linhas': linhas,
            'media_rs_cx': media_rs_cx,
            # Somas brutas (não só a razão pronta) -- pra quem agrupa vários
            # produtos (ex.: subtotal por prioridade no PDF/Resumo Geral)
            # poder calcular a média ponderada certa (soma dos R$ ponderados
            # ÷ soma dos pesos), em vez de fazer média simples das médias de
            # cada produto (que distorceria o resultado quando os produtos
            # têm volumes bem diferentes entre si).
            'media_rs_cx_soma_ponderada': soma_rs_ponderada,
            'media_rs_cx_peso': soma_peso,
            # Mesma lógica acima, mas para o custo unitário ('Custo' do
            # Estoque Físico) em vez do "Md Venda" -- pedido explícito da
            # Ingrid (28/08/2026) pra mostrar média de custo ao lado da
            # média de venda no Resumo Geral. None quando nenhuma linha de
            # estoque que bate com esse produto tem Qtde Vendida > 0 e
            # Custo (mesma regra de 'media_rs_cx' -- nunca inventa valor).
            'media_custo_cx': media_custo_cx,
            'media_custo_cx_soma_ponderada': soma_custo_ponderada,
            'media_custo_cx_peso': soma_peso_custo,
        })
    return results
