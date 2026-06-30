"""Categorização ampla de produto, usada SÓ nos gráficos de categoria do
dashboard gerencial (aba/seção 'Categorias de produto'). Não altera o nome
do produto em nenhuma outra aba/seção — ali ele continua exatamente como
extraído do PDF, item a item, conforme pedido pela Ingrid.

Regra padrão (ajustável): casamento por palavra-chave no nome do produto
(maiúsculo). É uma aproximação por nome — não há uma lista oficial de
código→categoria ainda. Se alguma categorização sair errada, é só pedir
o ajuste e a lista de palavras-chave abaixo é atualizada.
"""
import re

# Ordem importa: a primeira palavra-chave que casar decide a categoria.
# Termos mais específicos vêm antes dos mais genéricos.
_REGRAS = [
    ('Maçã Fuji', [r'\bFUJI\b']),
    ('Maçã Gala', [r'\bGALA\b']),
    ('Maçã Importada', [r'\bCHILENA\b', r'\bARGENTINA\b', r'\bPINK LADY\b',
                         r'\bGRAN ?SMITH\b', r'\bGRANNY\b']),
    ('Pera Forelle/Ercoline', [r'\bFORELLE\b', r'\bERCOLINE\b']),
    ('Pera Williams', [r'\bWILL(IAM|IAN|AM)?S?\b', r'\bPACKHAMS?\b', r'\bABATE\b']),
    ('Uva', [r'\bCUMB\b', r'\bTHOMPSON\b', r'\bVITORIA\b', r'\bITALIA\b',
             r'\bBENITAKA\b', r'\bCR[ÍI]NS?ON\b', r'\bNUBIA\b', r'\bJUBILLE\b',
             r'\bISIS\b', r'\bUVA\b', r'\bPORTUGUESA\b', r'\bRED ?GLOBE\b']),
    ('Melão', [r'\bMEL[ÃA]O\b']),
    ('Melancia', [r'\bMELANCIA\b']),
    ('Kiwi', [r'\bKIWI\b']),
    ('Caroço', [r'\bAMEIXA\b', r'\bP[ÊE]SSEGO\b', r'\bNECTARINA\b', r'\bDAMASCO\b']),
    ('Caqui', [r'\bCAQUI\b']),
    ('Mamão', [r'\bMAM[ÃA]O\b']),
    ('Rosada', [r'\bROSADA\b']),
    ('Roma/Mirtilo', [r'\bROMA\b', r'\bMIRTILO\b']),
    ('Citros', [r'\bLARANJA\b', r'\bTANGERINA\b', r'\bLIM[ÃA]O\b', r'\bBERGAMOTA\b']),
    ('Goiaba', [r'\bGOIABA\b']),
    ('Tâmara', [r'\bT[ÂA]MARA\b']),
    ('Hortaliças', [r'\bPIMENT[ÃA]O\b']),
]

_COMPILED = [(nome, [re.compile(p) for p in pats]) for nome, pats in _REGRAS]


def map_categoria(produto_nome: str) -> str:
    nome_u = (produto_nome or '').upper()
    for categoria, patterns in _COMPILED:
        if any(p.search(nome_u) for p in patterns):
            return categoria
    return 'Outros'
