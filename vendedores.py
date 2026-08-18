"""Cadastro único de vendedores da Othil.

Consolida num só lugar os nomes canônicos de vendedor e as variações
"cruas" conhecidas como aparecem nos diferentes relatórios em PDF. Antes
desta consolidação existiam 5 dicionários de alias independentes e
levemente divergentes entre si: calc.py:VENDEDORES_PADRAO/VENDOR_ALIASES,
parsers.py:KNOWN_VENDOR_NAMES, parsers_diario.py:VENDOR_ALIASES,
xlsx_vendedor_cliente.py:VENDOR_TAB/VENDOR_ORDER e
parser_quebra.py:_VENDEDORES.

IMPORTANTE: este módulo é aditivo — os parsers existentes (parsers.py,
parsers_diario.py, parser_quebra.py, calc.py, xlsx_vendedor_cliente.py)
continuam com sua lógica própria de reconhecimento de nome (cada PDF tem
peculiaridades diferentes de extração), e não foram alterados para
importar daqui ainda. A migração de cada um para usar este cadastro único
deve ser feita módulo a módulo, testando contra PDFs reais, para não
quebrar o reconhecimento de vendedor que já funciona hoje.
"""

# Nome de exibição canônico -> percentual padrão de meta semanal
# (mesmos valores de calc.py:VENDEDORES_PADRAO).
VENDEDORES_METAS = {
    'Farley': 17,
    'Dora': 17,
    'Afanais': 25,
    'Roni': 25,
    'Reginaldo': 22,
    'Luciano': 7,
    'Juliana': 7,
    'Claudia': 7,
}

# Todos os vendedores conhecidos no sistema, incluindo os que não têm meta
# semanal própria (ex.: Luca), na ordem de exibição preferida.
VENDEDORES_TODOS = list(VENDEDORES_METAS.keys()) + ['Luca']

# Variantes "cruas" conhecidas de cada nome, como aparecem nos diferentes
# relatórios em PDF (maiúsculas, com/sem sobrenome, grafias alternativas
# já mapeadas manualmente ao longo do tempo nos módulos originais).
ALIASES = {
    'Farley':    ['FARLEY'],
    'Dora':      ['DORA', 'ADILSON-DORA', 'ADILSON'],
    'Afanais':   ['AFANAIS'],
    'Roni':      ['RONI', 'RONISTONIS'],
    'Reginaldo': ['REGINALDO'],
    'Luciano':   ['LUCIANO'],
    'Juliana':   ['JULIANA', 'JULIANA AUGUSTA'],
    'Claudia':   ['CLAUDIA'],
    'Luca':      ['LUCA', 'LUCA-VENDEDOR', 'LUCA VENDEDOR'],
}

# Nomes brutos conhecidos, ordenados do mais longo pro mais curto — útil
# para casar o alias mais específico primeiro quando houver ambiguidade
# (ex.: "RONISTONIS" contém "RONI").
NOMES_BRUTOS_POR_TAMANHO = sorted(
    {alias for aliases in ALIASES.values() for alias in aliases},
    key=len, reverse=True,
)


def map_vendedor(raw: str):
    """Casa um nome bruto (como aparece em qualquer um dos relatórios) com
    o nome de exibição canônico. Retorna None se não reconhecer.

    Estratégia: 1) igualdade exata contra os aliases conhecidos；
    2) fallback por substring (do alias mais longo/específico pro mais
    curto), para cobrir nomes que vêm colados com outro texto."""
    if not raw:
        return None
    raw_u = raw.strip().upper()
    for nome, aliases in ALIASES.items():
        if raw_u in aliases:
            return nome
    for alias in NOMES_BRUTOS_POR_TAMANHO:
        if alias in raw_u:
            for nome, aliases in ALIASES.items():
                if alias in aliases:
                    return nome
    return None
