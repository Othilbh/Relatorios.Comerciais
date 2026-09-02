"""OTHIL — Cadastro de Marcas/Fornecedores (% de despesa administrativa)

Até 25/08/2026 esse cadastro era por PRODUTO EXATO (185+ linhas, uma pra
cada combinação de fruta/calibre/embalagem). Analisando a planilha real
que a Ingrid mandou, ficou claro que o percentual NÃO varia pela fruta ou
pelo calibre — varia pela MARCA/FORNECEDOR/EMBALAGEM que aparece no nome
do produto (ex.: VALENTINO, FRUTIMAR, POMERANA, SANJO...). Agrupando os
185 produtos reais por essa marca, 100% dos grupos tiveram um percentual
único e consistente (nenhuma mistura) — confirmado com a Ingrid em
25/08/2026 ("Faz muito sentido, é exatamente isso").

Por isso o cadastro passou a ser por MARCA (hoje ~80, bem mais enxuto que
185+), e um produto NOVO da mesma marca já cai certo sozinho, sem precisar
cadastrar cada SKU um por um:

  Custo real = Custo do relatório ÷ (1 + % da marca do produto / 100)

Como acha a marca de um produto: procura, dentro do nome do produto
(comparação por palavra inteira, não por trecho solto), qual marca
cadastrada aparece.
  - Encontrou exatamente 1 marca cadastrada -> usa o % dela.
  - Não encontrou nenhuma, ou encontrou mais de uma (nome ambíguo) -> usa
    PADRAO_PCT e sinaliza como não encontrado, pra aparecer visível no
    dashboard "Margem Real" (nunca adivinha um % por conta própria —
    decisão explícita da Ingrid: risco de errar em dado financeiro).

Persistência central versionada (data_store.py, com histórico) — editável
pela própria Ingrid na página "Cadastro de Marcas"
(pages/8_Cadastro_Produtos_OTHIL.py), sem precisar de alteração de código.
`_MARCAS_SEED` abaixo é só o valor SEMENTE: ponto de partida derivado
automaticamente da planilha real de 185 produtos (marca = a palavra, do
fim do nome pro início, que não é um código de calibre/tamanho/caixa NEM
uma palavra genérica de cor/embalagem -- "AZUL", "VERDE", "BRANCA",
"ISOPOR", "PVC", "TP" etc. foram deixadas de fora de propósito, porque
descrevem a caixa/cor, não o fornecedor, e bater com elas causaria
percentual ambíguo/errado em produtos de fornecedores diferentes que
usam a mesma cor de caixa) -- usado a primeira vez que a página de
cadastro é aberta (antes de qualquer 'Salvar'), e como fallback se a
persistência central não puder ser lida.

Por causa desse filtro, ~35 dos 185 produtos originais (a maioria já no
padrão de 15%) ficam sem marca detectada na semente -- aparecem
sinalizados em "sem % cadastrado" no dashboard Margem Real até a Ingrid
adicionar a marca certa (ex.: os produtos "ROSADA ... ISOPOR ..." são
17%, mas não têm um nome de fornecedor claro no texto -- precisa da
Ingrid pra saber qual é). Isso é intencional: preferível sinalizar um
produto sem marca do que arriscar aplicar um percentual errado por
adivinhação de texto.
"""
import re

import data_store as ds

MODULO = 'cadastro_marcas_margem'
TIPO_PERIODO = 'global'
PERIODO_REF = 'percentuais'

PADRAO_PCT = 15.0

_MARCAS_SEED = {
    'AGROEX': 15,
    'ALESSANDRINI': 15,
    'ARGO': 15,
    'AZALEIA': 15,
    'BELLA': 15,
    'CAPELLARO': 15,
    'CAROL': 15,
    'COMPOSOL': 15,
    'CRUNCH': 15,
    'DADIVA': 18,
    'DELICAT': 15,
    'DELICIA': 15,
    'DOLE': 15,
    'EXPORT': 15,
    'EXPRESSA': 15,
    'FAENZA': 15,
    'FRUITS': 15,
    'FRUTIBRAS': 15,
    'FRUTIMAR': 15,
    'GAUCHO': 15,
    'GOLD': 15,
    'GRANDGRAPE': 15,
    'GRANDVALLE': 15,
    'GRANGRAPE': 15,
    'GURUVA': 15,
    'HOSHI': 15,
    'HOTH': 17,
    'IBACEM/GOOD': 15,
    'IGARASHI': 15,
    'KETTERFRUTTI': 15,
    'LADY': 15,
    'LINA': 15,
    'MANAIRA': 15,
    'MEDJOUL': 15,
    'MORESCO': 15,
    'MOUGHRABI': 15,
    'NECTA': 15,
    'NORTE': 15,
    'OPAL': 15,
    'PILGER': 15,
    'POLAR': 15,
    'POMERANA': 18,
    'POMICA': 15,
    'PREMIUM': 15,
    'QUALITY': 15,
    'REI': 15,
    'SABOR': 15,
    'SANJO': 18,
    'SPECIALE': 15,
    'TANY': 15,
    'TOFRUT': 15,
    'TORREON': 15,
    'URUGOLD': 15,
    'VALE': 15,
    'VALENTINO': 15,
    'VALLE': 15,
    'VERFRUT': 15,
    'VILA': 15,
    'VILLA': 15,
}


def carregar_marcas() -> dict:
    """Carrega o cadastro atual (marca normalizada em MAIÚSCULO -> %) da
    persistência central. Se ainda não existir nenhum registro salvo
    (página de cadastro nunca foi aberta/salva), devolve a tabela semente
    (_MARCAS_SEED) como ponto de partida -- não grava nada sozinho, quem
    decide salvar é sempre uma ação explícita da Ingrid na tela."""
    try:
        registro = ds.load_current(MODULO, TIPO_PERIODO, PERIODO_REF)
    except Exception:
        registro = None
    if registro and registro.get('valores', {}).get('marcas'):
        return {str(k).strip().upper(): float(v)
                for k, v in registro['valores']['marcas'].items()}
    return dict(_MARCAS_SEED)


def salvar_marcas(marcas: dict, usuario: str = None):
    """Salva o cadastro completo (substitui o anterior, mas o histórico de
    versões antigas continua disponível via ds.load_history). `marcas` é
    um dict {marca: pct} -- normaliza nome (strip+upper) e pct (float)
    antes de gravar, e descarta linhas com marca vazia."""
    limpo = {
        str(k).strip().upper(): float(v)
        for k, v in marcas.items() if str(k).strip()
    }
    return ds.save_record(
        modulo=MODULO, tipo_periodo=TIPO_PERIODO, periodo_ref=PERIODO_REF,
        valores={'marcas': limpo}, usuario=usuario,
    )


def historico_marcas() -> list:
    """Versões anteriores do cadastro (mais recente primeiro), pra tela de
    auditoria -- quem mudou o quê e quando."""
    try:
        return list(reversed(ds.load_history(MODULO, TIPO_PERIODO, PERIODO_REF)))
    except Exception:
        return []


def marcas_no_produto(produto_nome: str, marcas: dict = None):
    """Lista as marcas cadastradas que aparecem como palavra (ou sequência
    de palavras) inteira dentro do nome do produto -- comparação por
    limite de palavra, não substring solta, pra 'PP' não bater sozinho
    dentro de outra palavra maior por acidente.

    Usa (?<!\\w)...(?!\\w) em vez de \\b...\\b nas duas pontas -- \\b só marca
    posição numa TRANSIÇÃO entre caractere de palavra e não-palavra, então
    quando a marca cadastrada começa ou termina com um caractere que não é
    letra/número (ex.: 'VIDA +', pedido real da Ingrid -- 02/09/2026: 'estão
    cadastrados, porém constam como sem % administrativo cadastrado') o \\b
    logo depois do '+' nunca fecha (não há transição de não-palavra pra
    não-palavra), e a marca NUNCA é encontrada, mesmo digitada certinha no
    cadastro. (?<!\\w)/(?!\\w) resolve isso -- exige só que o caractere
    imediatamente antes/depois não seja letra/número (ou não exista, início/
    fim da string), sem depender de uma transição específica -- continua
    tendo exatamente o mesmo comportamento de antes pra marcas comuns
    (só letras/números nas pontas, a grande maioria)."""
    if marcas is None:
        marcas = carregar_marcas()
    nome = (produto_nome or '').strip().upper()
    if not nome:
        return []
    achadas = []
    for m in marcas:
        m_norm = str(m).strip().upper()
        if not m_norm:
            continue
        if re.search(r'(?<!\w)' + re.escape(m_norm) + r'(?!\w)', nome):
            achadas.append(m)
    return achadas


def pct_admin(produto_nome: str, marcas: dict = None):
    """Retorna (pct, encontrado). `encontrado=True` quando exatamente UMA
    marca cadastrada aparece no nome do produto, OU quando mais de uma
    aparece mas todas as outras são sub-frase inteira da mais ESPECÍFICA
    (mais longa) -- ex.: 'PILGER' e 'TANGERINA PILGER' cadastradas juntas
    (caso real, 02/09/2026): um produto 'TANGERINA PILGER GRAUDA' bate com
    as duas, mas não é ambiguidade de verdade -- é a Ingrid tendo cadastrado
    a mesma marca em dois níveis de detalhe (genérico + específico), e o
    específico é o que soa mais correto. Nesse caso usa o % da mais longa.
    Nome sem nenhuma marca reconhecida, ou com 2+ marcas que NÃO são
    aninhadas entre si (marcas de verdade diferentes, não relacionadas),
    usa PADRAO_PCT e volta encontrado=False, pra ficar sinalizado no
    dashboard Margem Real (nunca adivinha nesse caso -- decisão explícita
    da Ingrid). `marcas` é opcional -- passe o cadastro já carregado
    (carregar_marcas()) quando for chamar isso muitas vezes em loop, pra
    não ler a persistência central a cada item; se omitido, carrega uma vez
    internamente."""
    if marcas is None:
        marcas = carregar_marcas()
    achadas = marcas_no_produto(produto_nome, marcas)
    if len(achadas) == 1:
        return float(marcas[achadas[0]]), True
    if len(achadas) > 1:
        mais_especifica = max(achadas, key=lambda a: len(str(a).strip()))
        outras = [a for a in achadas if a != mais_especifica]
        alvo = str(mais_especifica).strip().upper()
        if all(re.search(r'(?<!\w)' + re.escape(str(a).strip().upper()) + r'(?!\w)', alvo)
               for a in outras):
            return float(marcas[mais_especifica]), True
    return PADRAO_PCT, False
