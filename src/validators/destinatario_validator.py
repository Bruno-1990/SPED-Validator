"""Validador de Destinatario: IE, UF e CEP.

Regras:
- DEST_001: IE inconsistente com tratamento fiscal
- DEST_002: UF incompativel com IE (prefixo IE vs UF)
- DEST_003: UF incompativel com CEP (faixa CEP vs UF)
"""

from __future__ import annotations

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import ValidationContext
from .helpers import get_field, make_error, trib

# ──────────────────────────────────────────────
# Tabela: faixa de CEP por UF
# ──────────────────────────────────────────────

_FAIXA_CEP_UF: list[tuple[int, int, str]] = [
    (1000000, 19999999, "SP"),
    (20000000, 28999999, "RJ"),
    (29000000, 29999999, "ES"),
    (30000000, 39999999, "MG"),
    (40000000, 48999999, "BA"),
    (49000000, 49999999, "SE"),
    (50000000, 56999999, "PE"),
    (57000000, 57999999, "AL"),
    (58000000, 58999999, "PB"),
    (59000000, 59999999, "RN"),
    (60000000, 63999999, "CE"),
    (64000000, 64999999, "PI"),
    (65000000, 65999999, "MA"),
    (66000000, 68899999, "PA"),
    (68900000, 68999999, "AP"),
    (69000000, 69299999, "AM"),
    (69300000, 69399999, "RR"),
    (69400000, 69899999, "AM"),
    (69900000, 69999999, "AC"),
    (70000000, 72799999, "DF"),
    (72800000, 72999999, "GO"),
    (73000000, 73699999, "GO"),
    (73700000, 76799999, "GO"),
    (76800000, 76999999, "RO"),
    (77000000, 77999999, "TO"),
    (78000000, 78899999, "MT"),
    (78900000, 78999999, "MT"),
    (79000000, 79999999, "MS"),
    (80000000, 87999999, "PR"),
    (88000000, 89999999, "SC"),
    (90000000, 99999999, "RS"),
]


def _uf_from_cep(cep: str) -> str | None:
    """Retorna UF esperada a partir do CEP, ou None se invalido."""
    cep_clean = cep.strip().replace("-", "").replace(".", "")
    if len(cep_clean) != 8 or not cep_clean.isdigit():
        return None
    cep_num = int(cep_clean)
    for ini, fim, uf in _FAIXA_CEP_UF:
        if ini <= cep_num <= fim:
            return uf
    return None


# ──────────────────────────────────────────────
# Tabela: prefixo IE por UF (primeiros digitos)
# Fonte: SINTEGRA / layouts de IE por estado
# ──────────────────────────────────────────────

_PREFIXO_IE_UF: dict[str, list[str]] = {
    "AC": ["01"],
    "AL": ["24"],
    "AM": ["04"],
    "AP": ["03"],
    "BA": ["05", "06"],
    "CE": ["06"],
    "DF": ["07"],
    "ES": ["08"],
    "GO": ["10", "11", "15"],
    "MA": ["12"],
    "MG": ["062", "002"],
    "MS": ["28"],
    "MT": ["13"],
    "PA": ["15"],
    "PB": ["16"],
    "PE": ["18"],
    "PI": ["19"],
    "PR": ["90", "10"],
    "RJ": ["77", "78", "79", "80", "81", "82", "83", "84", "85"],
    "RN": ["20"],
    "RO": ["00"],
    "RR": ["24"],
    "RS": ["0"],
    "SC": ["25"],
    "SE": ["27"],
    "SP": ["1"],
    "TO": ["29"],
}


def _ie_matches_uf(ie: str, uf: str) -> bool | None:
    """Verifica se prefixo da IE e compativel com a UF.

    Retorna None se nao ha dados para validar.
    """
    ie_clean = ie.strip().replace(".", "").replace("-", "").replace("/", "")
    if not ie_clean or not ie_clean[0].isdigit():
        return None

    prefixos = _PREFIXO_IE_UF.get(uf.upper())
    if not prefixos:
        return None

    return any(ie_clean.startswith(pfx) for pfx in prefixos)


def validate_destinatario(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Executa validacoes DEST_001, DEST_002 e DEST_003."""
    if not context:
        return []

    errors: list[ValidationError] = []
    groups = group_by_register(records)

    # Mapear C100 -> COD_PART para vincular ao C170
    current_c100_part = ""
    c170_to_part: dict[int, str] = {}
    for rec in records:
        if rec.register == "C100":
            current_c100_part = get_field(rec, "COD_PART")
        elif rec.register == "C170":
            c170_to_part[rec.line_number] = current_c100_part

    # DEST_001: IE inconsistente com tratamento fiscal
    # Participante com IE ativa escriturado como consumidor final (CST indicando isencao)
    for rec in groups.get("C170", []):
        cod_part = c170_to_part.get(rec.line_number, "")
        part = context.participantes.get(cod_part, {})
        ie = part.get("ie", "")
        if not ie or ie.strip().upper() in ("ISENTO", "ISENTA", ""):
            continue

        cst = get_field(rec, "CST_ICMS")
        cfop = get_field(rec, "CFOP")
        if not cst or not cfop:
            continue

        cst_trib = trib(cst)
        # IE ativa + CST isento/NT em operacao interestadual de saida = inconsistente
        if cfop.startswith("6") and cst_trib in ("40", "41"):
            errors.append(make_error(
                rec, "CST_ICMS", "DEST_IE_INCONSISTENTE",
                f"Participante {cod_part} possui IE ativa ({ie}) mas "
                f"CST {cst} indica isencao/NT em operacao interestadual "
                f"(CFOP {cfop}). Verificar se o tratamento fiscal esta correto.",
                field_no=9,
                value=cst,
            ))

    # DEST_002 e DEST_003: validar no nivel do participante (0150)
    for rec in groups.get("0150", []):
        cod_part = get_field(rec, "COD_PART")
        uf_part = get_field(rec, "UF")
        ie = get_field(rec, "IE")

        if uf_part and ie and ie.strip().upper() not in ("ISENTO", "ISENTA", ""):
            match = _ie_matches_uf(ie, uf_part)
            if match is False:
                errors.append(make_error(
                    rec, "IE", "DEST_UF_IE_INCOMPATIVEL",
                    f"Participante {cod_part}: IE '{ie}' nao corresponde "
                    f"ao prefixo esperado para UF={uf_part}. "
                    f"Verificar cadastro do participante.",
                    field_no=6,
                    value=ie,
                ))

        # DEST_003: UF vs CEP
        cod_mun = get_field(rec, "COD_MUN")
        # 0150 nao tem CEP diretamente, mas cod_mun pode servir
        # Buscar CEP do 0005 se contribuinte, ou usar dados do context
        # Para participantes, verificamos via cod_mun + UF
        # O CEP esta no 0005 (para o contribuinte) e no 0150 nao tem CEP direto
        # Portanto, DEST_003 valida no 0005 da empresa principal
        pass

    # DEST_003: Validar CEP vs UF no registro 0005 (dados da empresa)
    # Nota: 0005 nao tem campo UF — a UF do contribuinte esta no 0000
    uf_contribuinte = ""
    if context:
        uf_contribuinte = context.uf_contribuinte
    if not uf_contribuinte:
        for rec_0000 in groups.get("0000", []):
            uf_contribuinte = get_field(rec_0000, "UF").upper()
            break

    for rec in groups.get("0005", []):
        cep = get_field(rec, "CEP")
        if not cep or not uf_contribuinte:
            continue

        uf_esperada = _uf_from_cep(cep)
        if uf_esperada and uf_esperada != uf_contribuinte.upper():
            errors.append(make_error(
                rec, "CEP", "DEST_UF_CEP_INCOMPATIVEL",
                f"CEP {cep} pertence a faixa de {uf_esperada}, "
                f"mas UF do contribuinte (0000) e {uf_contribuinte}. "
                f"Verificar endereco.",
                field_no=2,
                value=cep,
            ))

    # DEST_003 tambem para participantes via cod_mun -> UF implicita
    # cod_mun do IBGE: primeiros 2 digitos = codigo UF
    _COD_UF_IBGE = {
        "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA",
        "16": "AP", "17": "TO", "21": "MA", "22": "PI", "23": "CE",
        "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE",
        "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP",
        "41": "PR", "42": "SC", "43": "RS", "50": "MS", "51": "MT",
        "52": "GO", "53": "DF",
    }
    for rec in groups.get("0150", []):
        cod_part = get_field(rec, "COD_PART")
        uf_part = get_field(rec, "UF")
        cod_mun = get_field(rec, "COD_MUN")
        if not uf_part or not cod_mun or len(cod_mun) < 2:
            continue
        uf_mun = _COD_UF_IBGE.get(cod_mun[:2])
        if uf_mun and uf_mun != uf_part.upper():
            errors.append(make_error(
                rec, "COD_MUN", "DEST_UF_CEP_INCOMPATIVEL",
                f"Participante {cod_part}: COD_MUN {cod_mun} pertence a "
                f"{uf_mun}, mas UF informada e {uf_part}.",
                field_no=7,
                value=cod_mun,
            ))

    return errors
