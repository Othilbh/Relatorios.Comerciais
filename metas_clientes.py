"""Meta de Faturamento por Cliente -- definida diretamente no app (28/08/2026,
pedido explícito da Ingrid: as metas por cliente hoje só existiam na coluna
'META' de uma planilha Excel mantida à mão e reenviada todo mês, sem jeito
de editar dentro do próprio app como já existe para Meta Geral -- "Construir
edição no app").

Independente de:
  - metas_gerais.py (Meta Geral da EMPRESA inteira)
  - metas_gerais.salvar_metas_vendedores (meta própria de cada VENDEDOR,
    independente da Meta Geral -- "uma meta própria, definida à parte")

Este módulo é especificamente por CLIENTE, dentro de cada vendedor. Mesma
mecânica dos dois acima: digitada manualmente, versionada via data_store
(salvar uma meta nova nunca apaga a anterior -- fica no histórico).

Uma vez definida aqui, esta meta passa a ser a fonte PREFERIDA em toda a
página Vendedor-Cliente (tabs On Track por Cliente / Top 50 / Clientes por
Vendedor), na frente da meta antiga vinda da coluna 'META' do Excel de
histórico -- ver xlsx_vendedor_cliente/pages 3_Vendedor_Cliente_OTHIL.py
`_get_meta_fat`, que agora consulta primeiro `get_meta_cliente` daqui e só
cai no Excel quando não há nada definido manualmente. As duas fontes
convivem (o Excel nunca é apagado), evitando quebrar quem ainda depende
só do Excel enquanto a Ingrid não tiver preenchido tudo por aqui.
"""
import data_store as ds

MODULO = 'vendedor_cliente_metas_clientes'


def carregar_todas_metas_clientes(tipo_periodo: str, periodo_ref: str) -> dict:
    """{vendedor: {cliente: valor_R$}} -- de TODOS os vendedores que já têm
    alguma meta de cliente salva neste período."""
    reg = ds.load_current(MODULO, tipo_periodo, periodo_ref)
    return dict(reg['valores'].get('metas', {})) if reg else {}


def carregar_metas_cliente_vendedor(tipo_periodo: str, periodo_ref: str, vendedor: str) -> dict:
    """{cliente: valor_R$} -- só as metas de clientes DESTE vendedor."""
    return carregar_todas_metas_clientes(tipo_periodo, periodo_ref).get(vendedor, {})


def salvar_metas_clientes(tipo_periodo: str, periodo_ref: str, vendedor: str,
                           metas: dict, usuario: str = None) -> dict:
    """Salva/atualiza as metas de cliente DESTE vendedor (metas: {cliente:
    valor_R$}). Lê o registro atual (todos os vendedores), substitui só a
    chave `vendedor` e regrava tudo junto -- pra não apagar as metas de
    outros vendedores já salvas neste mesmo período (o registro no
    data_store é um único bloco por período, não um registro por
    vendedor)."""
    atuais = carregar_todas_metas_clientes(tipo_periodo, periodo_ref)
    atuais[vendedor] = metas
    return ds.save_record(
        modulo=MODULO, tipo_periodo=tipo_periodo, periodo_ref=periodo_ref,
        valores={'metas': atuais}, usuario=usuario,
    )


def get_meta_cliente(tipo_periodo: str, periodo_ref: str, vendedor: str, cliente: str):
    """Meta de faturamento (R$) de um cliente específico deste vendedor, ou
    None se não configurada. Faz match exato primeiro e, se não achar,
    tenta por nome normalizado (mesmo padrão de xlsx_vendedor_cliente
    ._normalize -- acentos/maiúsculas não deveriam impedir o match, já que
    o nome do cliente que chega aqui vem sempre normalizado pelo parser)."""
    from xlsx_vendedor_cliente import _normalize
    metas_v = carregar_metas_cliente_vendedor(tipo_periodo, periodo_ref, vendedor)
    if not metas_v:
        return None
    if cliente in metas_v:
        return metas_v[cliente] or None
    cli_norm = _normalize(cliente)
    for k, v in metas_v.items():
        if _normalize(k) == cli_norm:
            return v or None
    return None
