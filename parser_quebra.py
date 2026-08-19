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

        # Sub-Total: "Sub-Total 96 0 36 0 167 21.551,80 36"
        if s.startswith('Sub-Total') and grupo_nome:
            nums = re.findall(r'[\d]+(?:[.,][\d]+)*', s)
            if len(nums) >= 3:
                try:
                    cx = _parse_num(nums[2])
                    if cx > 0:
                        grupos.append({
                            'grupo': grupo_nome,
                            'codigo': grupo_codigo or '',
                            'categoria': map_categoria(grupo_nome),
                            'cx': cx,
                        })
                except (ValueError, IndexError):
                    pass
            grupo_codigo = None
            grupo_nome = None

    # ── Agrega por categoria ──────────────────────────────────────────────
    cat_dict: dict[str, float] = {}
    for g in grupos:
        cat_dict[g['categoria']] = cat_dict.get(g['categoria'], 0.0) + g['cx']

    categorias = sorted(
        [{'categoria': k, 'cx': v} for k, v in cat_dict.items()],
        key=lambda x: -x['cx'],
    )

    total_cx = sum(g['cx'] for g in grupos)
    grupos.sort(key=lambda x: -x['cx'])

    return {
        'periodo': periodo,
        'emissao': emissao,
        'total_cx': total_cx,
        'grupos': grupos,
        'categorias': categorias,
    }
