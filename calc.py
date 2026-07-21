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
  Falta(vendedor, produto)   = Meta − Vendido
  % Atingido                 = Vendido / Meta

'Estoque(produto)' é digitado manualmente pela Ingrid no app (não é mais
extraído automaticamente do PDF de Estoque Físico), pois o snapshot do PDF
pode não refletir o estoque conferido na segunda-feira na hora de bater a
meta.
"""
import math
from parsers import normalize_codigo

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
    'Luca': 7,
}

# Aliases para reconciliar os nomes "crus" que aparecem nos PDFs de
# estoque/vendas com os 8 nomes de exibição usados nas Metas Semanais.
# Nomes que não casam com nenhum alias (ex.: "JEAN CARLOS", "NAYARA")
# são ignorados (não fazem parte das 8 metas).
# O match usa o alias mais longo para "LUCIANO" não cair em "LUCA".
VENDOR_ALIASES = {
    'Reginaldo': ['REGINALDO'],
    'Roni': ['RONI'],
    'Afanais': ['AFANAIS'],
    'Dora': ['DORA'],
    'Farley': ['FARLEY'],
    'Luciano': ['LUCIANO'],
    'Juliana': ['JULIANA'],
    'Luca': ['LUCA - VENDEDOR', 'LUCA'],
}


def map_vendedor(raw: str):
    """Casa nome bruto do PDF com o nome de exibição.
    Prefere o alias mais longo (ex.: LUCIANO vence LUCA)."""
    raw_u = (raw or '').upper()
    best = None
    best_len = -1
    for display, aliases in VENDOR_ALIASES.items():
        for a in aliases:
            if a in raw_u and len(a) > best_len:
                best = display
                best_len = len(a)
    return best


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
            falta = meta - vendido
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
