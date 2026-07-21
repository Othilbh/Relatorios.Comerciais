"""Parser do relatório 'Lucratividade por Vendedor no Previsão' (OTHIL).

Formato (uma linha de dados por vendedor):
  Vendedor: <código>                  <NOME>
                                           Saídas Devoluções  Valor Total  Val.Unit.  Custo Total  Cust.Unit  Desc.Fin.Prev  Lucro Liq.  Lucro Unit.  Lucro %
                                          1.324,000  0,000    87.718,15               101.668,05               0,00         -13.949,90                -13,72
  ...
  Total Geral:                            6.899,000  0,000   480.149,92               521.848,01               0,00         -41.698,09                 -7,99

Colunas extraídas (pela posição na sequência de números):
  [0] Saídas   → volume (CX)
  [1] Devoluções (ignorado)
  [2] Valor Total → faturamento
  [3] Custo Total → custo
  os demais (Desc, Lucro Liq., Lucro %) são ignorados — recalculamos.

Regra de negócio:
  MC_RS          = fat - custo
  MC_PCT         = MC_RS / custo × 100
  Resultado Real = MC_PCT + 15 pp
"""
import os
import re
import subprocess
import tempfile

from parsers_diario import VENDOR_ALIASES, _norm_vendor_key, _to_float

# ─── Padrões ─────────────────────────────────────────────────────────────────
_VENDOR_RE  = re.compile(r'Vendedor:\s*\d+\s+(.+)')
_TOTAL_RE   = re.compile(r'Total Geral:')
_NUMBER_RE  = re.compile(r'-?\d{1,3}(?:\.\d{3})*,\d{2,3}')
_EMISSAO_RE = re.compile(r'Emissão:\s*(\d{2}/\d{2}/\d{4})')
_PERIODO_RE = re.compile(
    r'Período\s*:\s*(\d{2}/\d{2}/\d{4}[^N]*?\d{2}/\d{2}/\d{4})'
)


# ─── Helpers ─────────────────────────────────────────────────────────────────
def _extract_text(file_obj) -> str:
    data = file_obj.read() if hasattr(file_obj, 'read') else file_obj
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(data)
        tmp = f.name
    try:
        r = subprocess.run(
            ['pdftotext', '-layout', tmp, '-'],
            capture_output=True, timeout=30,
        )
        return r.stdout.decode('utf-8', errors='replace')
    finally:
        os.unlink(tmp)


def _lookup(raw: str):
    """Mapeia nome bruto do PDF para nome normalizado (VENDOR_ALIASES)."""
    key = _norm_vendor_key(raw)          # ex.: "ADILSON-DORA", "JULIANA AUGUSTA"
    return VENDOR_ALIASES.get(key)


def _agg(vol: float, fat: float, custo: float) -> dict:
    mc_rs  = fat - custo
    mc_pct = mc_rs / custo * 100 if custo else 0.0
    return {
        'vol':            round(vol),
        'fat':            round(fat, 2),
        'custo':          round(custo, 2),
        'mc_rs':          round(mc_rs, 2),
        'mc_pct':         round(mc_pct, 2),
        'resultado_real': round(mc_pct + 15, 2),
    }


# ─── Parser principal ─────────────────────────────────────────────────────────
def parse_totais_vendedor(file_obj) -> dict:
    """Parse do relatório 'Lucratividade por Vendedor no Previsão'.

    Returns
    -------
    {
      'data_emissao': str | None,
      'periodo':      str | None,
      'vendedores': {
          nome: {vol, fat, custo, mc_rs, mc_pct, resultado_real},
          ...
      },
      'total_geral': {vol, fat, custo, mc_rs, mc_pct, resultado_real} | None,
    }
    nome = valor de VENDOR_ALIASES (ex.: 'Roni', 'Afanais').
    Luca - Vendedor é incluído caso apareça — o chamador decide se exclui.
    """
    text  = _extract_text(file_obj)
    lines = text.split('\n')

    data_emissao: str | None  = None
    periodo:      str | None  = None
    vendedores:   dict        = {}
    total_geral:  dict | None = None
    cur_vendor:   str | None  = None   # nome normalizado ou None (não mapeado)

    for line in lines:
        # ── Metadados ─────────────────────────────────────────────────────
        if data_emissao is None:
            m = _EMISSAO_RE.search(line)
            if m:
                data_emissao = m.group(1)
        if periodo is None:
            m = _PERIODO_RE.search(line)
            if m:
                periodo = m.group(1).strip()

        # ── Cabeçalho de vendedor ─────────────────────────────────────────
        m = _VENDOR_RE.search(line)
        if m:
            cur_vendor = _lookup(m.group(1).strip())
            continue

        # ── Total Geral ────────────────────────────────────────────────────
        if _TOTAL_RE.search(line):
            nums = _NUMBER_RE.findall(line)
            if len(nums) >= 4:
                total_geral = _agg(
                    _to_float(nums[0]),   # Saídas
                    _to_float(nums[2]),   # Valor Total
                    _to_float(nums[3]),   # Custo Total
                )
            cur_vendor = None
            continue

        # ── Linha de dados do vendedor ─────────────────────────────────────
        if cur_vendor is not None:
            nums = _NUMBER_RE.findall(line)
            if len(nums) >= 4:
                vendedores[cur_vendor] = _agg(
                    _to_float(nums[0]),   # Saídas
                    _to_float(nums[2]),   # Valor Total
                    _to_float(nums[3]),   # Custo Total
                )
                cur_vendor = None   # cada vendedor tem só uma linha de dados

    return {
        'data_emissao': data_emissao,
        'periodo':      periodo,
        'vendedores':   vendedores,
        'total_geral':  total_geral,
    }
