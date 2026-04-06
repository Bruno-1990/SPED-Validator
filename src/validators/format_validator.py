"""Validador de formatos específicos: CNPJ, CPF, datas, CEP, CFOP, NCM, chave NFe, código município."""

from __future__ import annotations

import re
from datetime import datetime

from ..services.reference_loader import ReferenceLoader

_reference_loader: ReferenceLoader | None = None


def _get_reference_loader() -> ReferenceLoader:
    """Retorna instância singleton do ReferenceLoader."""
    global _reference_loader  # noqa: PLW0603
    if _reference_loader is None:
        _reference_loader = ReferenceLoader()
    return _reference_loader

# ──────────────────────────────────────────────
# CNPJ (14 dígitos + módulo 11)
# ──────────────────────────────────────────────

def validate_cnpj(cnpj: str) -> bool:
    """Valida CNPJ com dígitos verificadores (módulo 11).

    Aceita apenas 14 dígitos numéricos (sem pontuação).
    """
    cnpj = cnpj.strip()
    if not re.fullmatch(r"\d{14}", cnpj):
        return False

    # Rejeitar CNPJs com todos os dígitos iguais
    if len(set(cnpj)) == 1:
        return False

    # Cálculo do primeiro dígito verificador
    weights_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    total = sum(int(cnpj[i]) * weights_1[i] for i in range(12))
    remainder = total % 11
    digit_1 = 0 if remainder < 2 else 11 - remainder

    if int(cnpj[12]) != digit_1:
        return False

    # Cálculo do segundo dígito verificador
    weights_2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    total = sum(int(cnpj[i]) * weights_2[i] for i in range(13))
    remainder = total % 11
    digit_2 = 0 if remainder < 2 else 11 - remainder

    return int(cnpj[13]) == digit_2


# ──────────────────────────────────────────────
# CPF (11 dígitos + módulo 11)
# ──────────────────────────────────────────────

def validate_cpf(cpf: str) -> bool:
    """Valida CPF com dígitos verificadores (módulo 11).

    Aceita apenas 11 dígitos numéricos (sem pontuação).
    """
    cpf = cpf.strip()
    if not re.fullmatch(r"\d{11}", cpf):
        return False

    if len(set(cpf)) == 1:
        return False

    # Primeiro dígito
    total = sum(int(cpf[i]) * (10 - i) for i in range(9))
    remainder = total % 11
    digit_1 = 0 if remainder < 2 else 11 - remainder

    if int(cpf[9]) != digit_1:
        return False

    # Segundo dígito
    total = sum(int(cpf[i]) * (11 - i) for i in range(10))
    remainder = total % 11
    digit_2 = 0 if remainder < 2 else 11 - remainder

    return int(cpf[10]) == digit_2


# ──────────────────────────────────────────────
# Data DDMMAAAA
# ──────────────────────────────────────────────

def validate_date(date_str: str) -> bool:
    """Valida data no formato DDMMAAAA (padrão SPED).

    Verifica se dia/mês/ano formam uma data válida.
    """
    date_str = date_str.strip()
    if not re.fullmatch(r"\d{8}", date_str):
        return False

    day = int(date_str[0:2])
    month = int(date_str[2:4])
    year = int(date_str[4:8])

    if year < 1900 or year > 2100:
        return False

    try:
        datetime(year, month, day)
        return True
    except ValueError:
        return False


def date_in_period(date_str: str, dt_ini: str, dt_fin: str) -> bool:
    """Verifica se uma data está dentro do período DT_INI..DT_FIN."""
    try:
        date = _parse_date(date_str)
        start = _parse_date(dt_ini)
        end = _parse_date(dt_fin)
        return start <= date <= end
    except (ValueError, IndexError):
        return False


def _parse_date(date_str: str) -> datetime:
    """Converte DDMMAAAA para datetime."""
    return datetime(int(date_str[4:8]), int(date_str[2:4]), int(date_str[0:2]))


# ──────────────────────────────────────────────
# CEP (8 dígitos)
# ──────────────────────────────────────────────

def validate_cep(cep: str) -> bool:
    """Valida CEP: 8 dígitos numéricos, não pode ser 00000000."""
    cep = cep.strip()
    return bool(re.fullmatch(r"\d{8}", cep)) and cep != "00000000"


# ──────────────────────────────────────────────
# CFOP (4 dígitos, primeiro 1-7)
# ──────────────────────────────────────────────

def validate_cfop(cfop: str) -> bool:
    """Valida CFOP: 4 dígitos, primeiro dígito entre 1 e 7."""
    cfop = cfop.strip()
    return bool(re.fullmatch(r"[1-7]\d{3}", cfop))


def cfop_matches_operation(cfop: str, ind_oper: str) -> bool:
    """Verifica se CFOP é coerente com IND_OPER.

    IND_OPER=0 (entrada): CFOP começa com 1, 2 ou 3
    IND_OPER=1 (saída): CFOP começa com 5, 6 ou 7
    """
    cfop = cfop.strip()
    if not cfop or len(cfop) < 1:
        return True  # Não é possível validar

    first = cfop[0]
    if ind_oper == "0":
        return first in ("1", "2", "3")
    elif ind_oper == "1":
        return first in ("5", "6", "7")
    return True  # IND_OPER desconhecido


# ──────────────────────────────────────────────
# NCM (8 dígitos)
# ──────────────────────────────────────────────

def validate_ncm(ncm: str) -> bool:
    """Valida NCM: 8 dígitos numéricos."""
    ncm = ncm.strip()
    return bool(re.fullmatch(r"\d{8}", ncm))


# ──────────────────────────────────────────────
# Chave NFe (44 dígitos + dígito verificador)
# ──────────────────────────────────────────────

def validate_chave_nfe(chave: str) -> bool:
    """Valida chave de acesso da NFe: 44 dígitos com dígito verificador.

    Estrutura: UF(2) + AAMM(4) + CNPJ(14) + MOD(2) + SERIE(3) + NUM(9) + TIPO_EMIS(1) + NUM_ALEATORIO(8) + DV(1)
    """
    chave = chave.strip()
    if not re.fullmatch(r"\d{44}", chave):
        return False

    # Dígito verificador (módulo 11, pesos 2-9 da direita para esquerda)
    digits = [int(c) for c in chave[:43]]
    weights = [2, 3, 4, 5, 6, 7, 8, 9]
    total = 0
    for i, d in enumerate(reversed(digits)):
        total += d * weights[i % 8]

    remainder = total % 11
    dv_calc = 0 if remainder < 2 else 11 - remainder

    return int(chave[43]) == dv_calc


# ──────────────────────────────────────────────
# Código Município IBGE (7 dígitos)
# ──────────────────────────────────────────────

# Primeiro dígito do código IBGE por região
_UF_FIRST_DIGITS = {"1", "2", "3", "4", "5"}

def validate_cod_municipio(cod: str) -> bool:
    """Valida código de município IBGE: 7 dígitos, validado contra tabela IBGE.

    Se a tabela ibge_municipios.yaml estiver disponível, valida contra a lista
    completa de municípios. Caso contrário, usa fallback de primeiro dígito 1-5.
    """
    cod = cod.strip()
    if not re.fullmatch(r"\d{7}", cod):
        return False
    if cod[0] not in _UF_FIRST_DIGITS:
        return False
    loader = _get_reference_loader()
    if loader.has_municipios_table():
        return loader.is_municipio_valido(cod)
    return True
