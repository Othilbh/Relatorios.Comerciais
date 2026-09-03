"""OTHIL — Resultado por Marca/Fornecedor.

Relatório mensal pra reunião comercial da 1ª sábado do mês, pra discutir
fornecedores (pedido da Ingrid, 02/09/2026: "Todo 1º sábado do mês tem
uma reunião com o comercial a fim de discutir sobre os fornecedores...
eu mandaria esses PDFs todo mês" -- dois PDFs "Resumo do Estoque" do
Plus, um filtrado Vendas+Bonificação, outro filtrado Quebra).

Reaproveita 100% o parser já existente e validado em produção
(parsers_estoque.parse_resumo_estoque() -- NÃO duplicado aqui; ver aquele
módulo pro formato de cada item). Este módulo só adiciona o que é
específico deste relatório: classificação por marca/fornecedor e
persistência dos dois uploads mensais.

Persistência: dois módulos de data_store INDEPENDENTES (MOD_VENDAS e
MOD_QUEBRA), mesma técnica já usada em metas_gerais.publicar_vendas_pdf()/
publicar_quebra_pdf() -- assim enviar o PDF de Quebra num mês nunca
apaga o de Vendas do mesmo mês (e vice-versa). Isso é diferente do
upload único de produtos.salvar_resumo_estoque(), que substitui o mês
inteiro a cada envio (não serve pro fluxo de 2 PDFs por mês da Ingrid).

Classificação por marca: reaproveita 100% margem_produto.marcas_no_produto()
(cadastro editável em "Cadastro de Marcas"), com um pequeno conjunto de
regras manuais por cima -- pedidos explícitos da Ingrid em 02/09/2026 pra
unificar variedades/frutas que hoje aparecem picadas em vários nomes de
produto sem fornecedor claro no nome (ex.: "MELAO CEPI", "MELAO GAIA",
"MELAO DINO" viram todos "ITAUEIRA"). Essas regras têm PRIORIDADE sobre
o cadastro -- ver UNIFICACOES_MANUAIS abaixo, e classificar_marca().

Ajuste "Resultado Real" (+15pp): mesmo ajuste usado no resto do app
(parsers_vendedor._agg, metas_gerais.realizado_vendas) -- pedido da
Ingrid, 02/09/2026: "é para ter o ajuste de 15pp". Este é um mecanismo
DIFERENTE do "% administrativo" por marca de margem_produto.py (usado só
no dashboard Margem Real, que explicitamente NÃO soma o +15pp -- ver
docstring de margem_produto.py); aqui resultado_real_pct = (faturamento -
custo)/custo × 100 + 15.
"""
import datetime as _dt
import re as _re

import data_store as ds
import periodo as periodo_mod
import margem_produto as mp

MOD_VENDAS = 'marca_fornecedor_vendas'
MOD_QUEBRA = 'marca_fornecedor_quebra'

AJUSTE_RESULTADO_REAL_PP = 15.0

# Regras manuais da Ingrid (02/09/2026, ao ver a prévia do relatório) --
# lista ordenada: a 1ª regra cujo termo aparece (substring, maiúsculas)
# no nome do produto vence, com PRIORIDADE sobre o cadastro de marcas.
# Ela pediu essas 4 unificações primeiro (melão/melancia, vitória,
# thompson, mamão) e depois mais 5, olhando o que sobrou "sem marca"
# (kiwi, pimentão, tâmara, red globe, mirtilo). Se pedir mais no futuro,
# é só acrescentar aqui.
UNIFICACOES_MANUAIS = [
    (('MELAO', 'MELÃO', 'MELANCIA'), 'ITAUEIRA'),
    (('VITORIA', 'VITÓRIA'), 'VITORIA'),
    (('THOMPSON',), 'THOMPSON'),
    (('MAMAO', 'MAMÃO'), 'MAMAO'),
    (('KIWI',), 'KIWI IMPORTADO'),
    (('PIMENTAO', 'PIMENTÃO'), 'PIMENTAO'),
    (('TAMARA', 'TÂMARA'), 'TAMARA'),
    (('RED GLOBE',), 'RED GLOBE'),
    (('MIRTILO',), 'MIRTILO'),
]


def classificar_marca(produto_nome, marcas_cadastro=None):
    """Marca/fornecedor de um produto: 1ª regra de UNIFICACOES_MANUAIS que
    bater, senão cai pro cadastro (margem_produto.marcas_no_produto(), com
    o mesmo desempate por especificidade de margem_produto.pct_admin() --
    marcas aninhadas usa a mais específica, ambíguas de verdade não
    reconhece). Retorna None quando não reconhece nenhuma marca (produto
    entra em "sem marca reconhecida")."""
    nome_up = (produto_nome or '').upper()
    for termos, marca in UNIFICACOES_MANUAIS:
        if any(t in nome_up for t in termos):
            return marca
    achadas = mp.marcas_no_produto(produto_nome, marcas_cadastro)
    if not achadas:
        return None
    if len(achadas) == 1:
        return achadas[0]
    mais_especifica = max(achadas, key=lambda a: len(str(a).strip()))
    outras = [a for a in achadas if a != mais_especifica]
    alvo = str(mais_especifica).strip().upper()
    if all(_re.search(r'(?<!\w)' + _re.escape(str(a).strip().upper()) + r'(?!\w)', alvo)
           for a in outras):
        return mais_especifica
    return None


def _publicar(modulo, pdf_parsed, usuario):
    data_ref = pdf_parsed.get('emissao_date') or _dt.date.today()
    periodo_ref_str = periodo_mod.periodo_ref('mensal', data_ref)
    valores = {
        'itens': pdf_parsed.get('itens') or [],
        'avisos': pdf_parsed.get('avisos') or [],
        'emissao': pdf_parsed.get('emissao'),
        'n_itens': len(pdf_parsed.get('itens') or []),
    }
    registro = ds.save_record(modulo=modulo, tipo_periodo='mensal',
                               periodo_ref=periodo_ref_str, valores=valores, usuario=usuario)
    return periodo_ref_str, registro


def publicar_vendas(pdf_parsed, usuario=None):
    """Salva um upload do Resumo do Estoque filtrado Vendas+Bonificação.
    periodo_ref sempre mensal, pela data de Emissão do próprio PDF (mesma
    convenção de produtos.salvar_resumo_estoque). Independente do upload
    de Quebra do mesmo mês -- ver docstring do módulo."""
    return _publicar(MOD_VENDAS, pdf_parsed, usuario)


def publicar_quebra(pdf_parsed, usuario=None):
    """Salva um upload do Resumo do Estoque filtrado Quebra. Ver
    publicar_vendas()."""
    return _publicar(MOD_QUEBRA, pdf_parsed, usuario)


def meses_disponiveis():
    """União dos meses com Vendas OU Quebra publicados (mais recente
    primeiro) -- um mês pode ter só um dos dois, se o outro PDF ainda não
    foi enviado."""
    meses = set(ds.list_periodos(MOD_VENDAS, 'mensal')) | set(ds.list_periodos(MOD_QUEBRA, 'mensal'))
    return sorted(meses, reverse=True)


def carregar_mes(mes_ref):
    """Itens brutos publicados nesse mês: (itens_vendas, itens_quebra),
    cada um uma lista vazia se aquele PDF ainda não foi enviado no mês."""
    reg_v = ds.load_current(MOD_VENDAS, 'mensal', mes_ref)
    reg_q = ds.load_current(MOD_QUEBRA, 'mensal', mes_ref)
    itens_v = ((reg_v or {}).get('valores') or {}).get('itens') or []
    itens_q = ((reg_q or {}).get('valores') or {}).get('itens') or []
    return itens_v, itens_q


def _novo_agg():
    return {'cx': 0.0, 'faturamento': 0.0, 'custo': 0.0, 'quebra_cx': 0.0,
            'quebra_rs': 0.0, 'produtos': {}}


def _novo_agg_produto():
    return {'cx': 0.0, 'faturamento': 0.0, 'custo': 0.0, 'quebra_cx': 0.0, 'quebra_rs': 0.0}


def _fechar_agg(d):
    d['mc_rs'] = d['faturamento'] - d['custo']
    d['mc_pct_bruto'] = (d['mc_rs'] / d['custo'] * 100) if d['custo'] else 0.0
    d['resultado_real_pct'] = round(d['mc_pct_bruto'] + AJUSTE_RESULTADO_REAL_PP, 2)


def agregar_por_marca(itens_vendas, itens_quebra, marcas_cadastro=None):
    """Agrega itens (formato de parsers_estoque.parse_resumo_estoque()) por
    marca/fornecedor -- ver classificar_marca(). Retorna dict:

      marcas -- {marca: {cx, faturamento, custo, mc_rs, mc_pct_bruto,
                 resultado_real_pct, quebra_cx, quebra_rs,
                 produtos: {produto: {mesmos campos, por produto}}}}
      sem_marca_vendas -- {produto: {cx, valor, custo}}
      sem_marca_quebra -- {produto: {cx, custo}}

    (produtos que não bateram com nenhuma marca, pra sinalizar na tela --
    nunca descartados em silêncio, mesma filosofia de margem_produto.py).

    resultado_real_pct = mc_pct_bruto + 15pp (AJUSTE_RESULTADO_REAL_PP) --
    ver docstring do módulo sobre a diferença pro % administrativo de
    margem_produto.py."""
    if marcas_cadastro is None:
        marcas_cadastro = mp.carregar_marcas()

    marcas = {}
    sem_marca_vendas = {}
    sem_marca_quebra = {}

    for it in itens_vendas:
        marca = classificar_marca(it['produto'], marcas_cadastro)
        if marca:
            ma = marcas.setdefault(marca, _novo_agg())
            ma['cx'] += it['saida']
            ma['faturamento'] += it['valor_saida']
            ma['custo'] += it['custo_saida']
            p = ma['produtos'].setdefault(it['produto'], _novo_agg_produto())
            p['cx'] += it['saida']
            p['faturamento'] += it['valor_saida']
            p['custo'] += it['custo_saida']
        else:
            d = sem_marca_vendas.setdefault(it['produto'], {'cx': 0.0, 'valor': 0.0, 'custo': 0.0})
            d['cx'] += it['saida']
            d['valor'] += it['valor_saida']
            d['custo'] += it['custo_saida']

    for it in itens_quebra:
        marca = classificar_marca(it['produto'], marcas_cadastro)
        if marca:
            ma = marcas.setdefault(marca, _novo_agg())
            ma['quebra_cx'] += it['saida']
            ma['quebra_rs'] += it['custo_saida']
            p = ma['produtos'].setdefault(it['produto'], _novo_agg_produto())
            p['quebra_cx'] += it['saida']
            p['quebra_rs'] += it['custo_saida']
        else:
            d = sem_marca_quebra.setdefault(it['produto'], {'cx': 0.0, 'custo': 0.0})
            d['cx'] += it['saida']
            d['custo'] += it['custo_saida']

    for ma in marcas.values():
        _fechar_agg(ma)
        for p in ma['produtos'].values():
            _fechar_agg(p)

    return {'marcas': marcas, 'sem_marca_vendas': sem_marca_vendas, 'sem_marca_quebra': sem_marca_quebra}
