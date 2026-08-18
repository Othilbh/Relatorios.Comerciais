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
 
 
def compute_metas(vendas_rows, produtos_config, vendedor_pcts):
    """
    produtos_config: list of {'nome': str, 'codigos': list[str], 'estoque': float}
      'estoque' é a quantidade atual em estoque do produto (em caixas),
      digitada manualmente pela Ingrid no app.
    'codigos' continua sendo usado apenas para casar as vendas (Vendido)
      no relatório de Lucratividade por Vendedor.
    vendedor_pcts: dict {nome_vendedor: percentual (0-100)}
 
    Retorna lista de dicts:
      {
        'produto': str, 'estoque_total': float,
        'linhas': [
          {'vendedor', 'pct', 'meta', 'vendido', 'falta', 'atingido'}, ...
        ]
      }
    """
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
 
        linhas = []
        for vend, pct in vendedor_pcts.items():
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
                'vendido': vendido,
                'falta': falta,
                'atingido': atingido,
            })
 
        results.append({
            'produto': nome,
            'estoque_total': estoque_total,
            'linhas': linhas,
        })
    return results
