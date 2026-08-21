"""Parser do relatório Resumo do Estoque filtrado por QUEBRA (OTHIL).

O PDF contém blocos por grupo de produto. Cada bloco termina com uma linha
"Sub-Total" cujo 3º valor numérico é a quantidade de CX descartadas (Saída).
"""
import re
import pdfplumber
from categorias import map_categoria

_VENDEDORES = {
    'AFANAIS', 'DORA', 'FARLEY', 'LUCA', 'LUCIANO', 'REGINALDO',
    'RONI', 'RONISTONIS', 'JULIANA', 'CLAUDIA',
}


def _parse_num(s: str) -> float:
    """Converte número BR (1.234,56) → float."""
    return float(s.replace('.', '').replace(',', '.'))


def _limpar_nome_grupo(nome_raw: str) -> str:
    """Remove vendedor do final do nome do grupo."""
    parts = nome_raw.strip().split()
    if parts and parts[-1].upper() in _VENDEDORES:
        parts = parts[:-1]
    return ' '.join(parts)


def parse_quebra(pdf_file) -> dict:
    """
    Parseia PDF Resumo do Estoque (classificação QUEBRA).

    Retorna dict:
      periodo   – str  ex: "01/07/2026 a 31/07/2026"
      emissao   – str  ex: "04/08/2026"
      total_cx  – float
      grupos    – list[dict]  cada item: {grupo, codigo, categoria, cx}
      categorias – list[dict] cada item: {categoria, cx}  (ordenado desc)
    """
    linhas = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            txt = page.extract_text()
            if txt:
                linhas.extend(txt.splitlines())

    # ── Período ───────────────────────────────────────────────────────────
    periodo = ''
    for linha in linhas:
        m = re.search(
            r'Per[íi]odo de (\d{2}/\d{2}/\d{4}).*?at[eé] (\d{2}/\d{2}/\d{4})',
            linha
        )
        if m:
            periodo = f"{m.group(1)} a {m.group(2)}"
            break

    # ── Emissão ───────────────────────────────────────────────────────────
    emissao = ''
    for linha in linhas:
        m = re.search(r'Emiss[aã]o[:\s]+(\d{2}/\d{2}/\d{4})', linha)
        if m:
            emissao = m.group(1)
            break

    # ── Grupos e quebras ──────────────────────────────────────────────────
    grupos: list[dict] = []
    grupo_codigo = None
    grupo_nome = None

    for linha in linhas:
        s = linha.strip()

        # Cabeçalho de grupo: "Grupo: 1.1.01.01.001.001.015 WILLAMS MENIS RONISTONIS"
        m_g = re.match(r'Grupo:\s+([\d.]+)\s+(.+)', s)
        if m_g:
            grupo_codigo = m_g.group(1)
            grupo_nome = _limpar_nome_grupo(m_g.group(2))
            continue

        # Sub-Total: "Sub-Total 815,000 0,000 2,000 0,000 992,000 138.414,94
        # 2,000 0,00 0,00 314,72 157,36 -314,72 -100,00" -- 13 números, na
        # mesma ordem das colunas do cabeçalho ("Saldo Inicial Entrada
        # Saída Avar. Saí Saldo Final Custo Total Saída Valor Saí. Méd.Saí.
        # Custo Saída Méd.Cto. Resultado %"):
        #   [2]=Saída (cx quebrada, já que este relatório é filtrado por
        #       classificação QUEBRA -- confirmado batendo com o Total
        #       Geral em PDFs reais)
        #   [9]=Custo Saída (valor em R$ do custo daquela quebra -- NÃO
        #       confundir com [5]="Custo", que é o custo médio unitário do
        #       SALDO que sobrou, outra coisa. Confirmado somando o [9] de
        #       cada grupo e batendo exatamente com o Total Geral de um
        #       PDF real de 07/08/2026: R$ 25.394,78.)
        # O regex não captura o sinal de "-" -- não é problema pra [9]
        # (custo de uma saída nunca é negativo na prática), mas por
        # segurança nunca use este parser pra ler [7]/[11]/[12], que podem
        # vir negativos e perderiam o sinal.
        if s.startswith('Sub-Total') and grupo_nome:
            nums = re.findall(r'[\d]+(?:[.,][\d]+)*', s)
            if len(nums) >= 3:
                try:
                    cx = _parse_num(nums[2])
                    if cx > 0:
                        custo = _parse_num(nums[9]) if len(nums) >= 10 else None
                        grupos.append({
                            'grupo': grupo_nome,
                            'codigo': grupo_codigo or '',
                            'categoria': map_categoria(grupo_nome),
                            'cx': cx,
                            'custo': custo,
                        })
                except (ValueError, IndexError):
                    pass
            grupo_codigo = None
            grupo_nome = None

    # ── Agrega por categoria ──────────────────────────────────────────────
    cat_dict: dict[str, dict] = {}
    for g in grupos:
        c = cat_dict.setdefault(g['categoria'], {'cx': 0.0, 'custo': 0.0})
        c['cx'] += g['cx']
        if g['custo'] is not None:
            c['custo'] += g['custo']

    categorias = sorted(
        [{'categoria': k, 'cx': v['cx'], 'custo': v['custo']} for k, v in cat_dict.items()],
        key=lambda x: -x['cx'],
    )

    total_cx = sum(g['cx'] for g in grupos)
    # total_custo: soma só o que foi lido com sucesso -- None (não 0) se
    # NENHUM grupo tinha a coluna Custo Saída legível, pra não mostrar um
    # "R$ 0,00" enganoso quando na real não conseguimos ler nada.
    custos_lidos = [g['custo'] for g in grupos if g['custo'] is not None]
    total_custo = sum(custos_lidos) if custos_lidos else None
    grupos.sort(key=lambda x: -x['cx'])

    return {
        'periodo': periodo,
        'emissao': emissao,
        'total_cx': total_cx,
        'total_custo': total_custo,
        'grupos': grupos,
        'categorias': categorias,
    }
