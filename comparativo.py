"""Componente central de COMPARATIVO — padrão único para todo o app.

Compara um valor "atual" com um valor "anterior" (período anterior, ou
mesmo período do ano anterior) e devolve diferença absoluta, variação
percentual, tendência e indicação de melhora/piora — sempre no mesmo
formato, para uso em cards, tabelas e exportações de qualquer módulo.
"""


def calcular(atual: float, anterior: float | None, menor_e_melhor: bool = False) -> dict:
    """
    atual / anterior: valores numéricos do indicador no período atual e no
      período de comparação (pode ser None se não houver dado anterior
      disponível — nesse caso o comparativo é retornado como indefinido).
    menor_e_melhor: True para indicadores onde reduzir é bom (ex.: Quebra,
      Custo) — inverte a interpretação de "melhora" sem inverter o sinal
      da variação percentual exibida.
    """
    if anterior is None or atual is None:
        return {
            'atual': atual,
            'anterior': anterior,
            'diferenca_absoluta': None,
            'variacao_pct': None,
            'tendencia': 'indisponivel',
            'melhora': None,
            'menor_e_melhor': menor_e_melhor,
        }

    diferenca = atual - anterior
    variacao_pct = (diferenca / anterior * 100) if anterior else None

    if diferenca > 1e-9:
        tendencia = 'alta'
    elif diferenca < -1e-9:
        tendencia = 'baixa'
    else:
        tendencia = 'estavel'

    if tendencia == 'estavel':
        melhora = None
    elif menor_e_melhor:
        melhora = tendencia == 'baixa'
    else:
        melhora = tendencia == 'alta'

    return {
        'atual': atual,
        'anterior': anterior,
        'diferenca_absoluta': diferenca,
        'variacao_pct': variacao_pct,
        'tendencia': tendencia,
        'melhora': melhora,
        'menor_e_melhor': menor_e_melhor,
    }


def formatar_variacao(comp: dict, casas: int = 2) -> str:
    """'+6,25%' / '-3,10%' / 'n/d'."""
    v = comp.get('variacao_pct')
    if v is None:
        return 'n/d'
    sinal = '+' if v >= 0 else ''
    texto = f"{v:.{casas}f}".replace('.', ',')
    return f"{sinal}{texto}%"


def emoji_tendencia(comp: dict) -> str:
    if comp.get('melhora') is None:
        return '➖'
    return '📈' if comp['melhora'] else '📉'
