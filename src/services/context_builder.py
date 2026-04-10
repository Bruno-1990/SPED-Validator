"""MOD-01: Identificacao de Regime Tributario e construcao do ValidationContext.

Determina o regime tributario (Normal, Simples Nacional, MEI) a partir do
registro 0000 do arquivo SPED EFD e popula caches de participantes, produtos
e naturezas de operacao para uso durante a validacao.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

logger = logging.getLogger(__name__)

from ..validators.helpers import fields_to_dict
from .client_service import ClienteInfo, buscar_cliente
from .reference_loader import BeneficioProfile, ReferenceLoader


class TaxRegime(Enum):
    """Regime tributario identificado a partir do IND_PERFIL do registro 0000."""

    NORMAL = "normal"
    SIMPLES_NACIONAL = "simples_nacional"
    MEI = "mei"
    UNKNOWN = "unknown"


# CSTs validos por regime (atualizado conforme Tabela_CST_Vigente.json)
CST_TABELA_A = {
    "00", "02", "10", "12", "13", "15", "20", "30", "40", "41",
    "50", "51", "52", "53", "60", "61", "70", "72", "74", "90",
}
CST_TABELA_B = {"101", "102", "103", "201", "202", "203", "300", "400", "500", "900"}


@dataclass
class ValidationContext:
    """Contexto de validacao construido antes da execucao do pipeline."""

    file_id: int
    regime: TaxRegime = TaxRegime.UNKNOWN
    uf_contribuinte: str = ""
    periodo_ini: date | None = None
    periodo_fim: date | None = None
    ind_perfil: str = ""
    cod_ver: str = ""
    cnpj: str = ""
    company_name: str = ""
    available_tables: list[str] = field(default_factory=list)
    participantes: dict[str, dict] = field(default_factory=dict)  # cod_part -> dados
    produtos: dict[str, dict] = field(default_factory=dict)       # cod_item -> dados
    naturezas: dict[str, str] = field(default_factory=dict)       # cod_nat -> descr
    reference_loader: ReferenceLoader | None = None
    active_rules: list[str] = field(default_factory=list)
    rule_index: object | None = None  # RuleIndex (import circular evitado)
    found_errors: list[str] = field(default_factory=list)
    # Dados do cliente (MySQL DCTF_WEB)
    cliente: ClienteInfo | None = None
    # Benefícios fiscais resolvidos (JSON x MySQL)
    beneficios_ativos: list[BeneficioProfile] = field(default_factory=list)


def _parse_date(dt_str: str) -> date | None:
    """Converte string DDMMAAAA para date."""
    if not dt_str or len(dt_str) != 8:
        return None
    try:
        return date(int(dt_str[4:8]), int(dt_str[2:4]), int(dt_str[0:2]))
    except (ValueError, IndexError):
        return None


def _determine_regime(ind_perfil: str) -> TaxRegime:
    """Determina regime tributario a partir do IND_PERFIL.

    IND_PERFIL:
      A = Perfil A (completo) -> Regime Normal
      B = Perfil B (simplificado) -> Regime Normal
      C = Perfil C (Simples Nacional / ME/EPP) -> Simples Nacional
    """
    ind = ind_perfil.strip().upper()
    if ind == "C":
        return TaxRegime.SIMPLES_NACIONAL
    if ind in ("A", "B"):
        return TaxRegime.NORMAL
    return TaxRegime.UNKNOWN


def _load_fields(row: tuple | sqlite3.Row, register: str) -> dict[str, str]:
    """Carrega fields_json suportando formato dict (novo) e list (legado)."""
    raw = row[0]
    parsed = json.loads(raw)
    if isinstance(parsed, list):
        return fields_to_dict(register, parsed)
    return dict(parsed)


def build_context(file_id: int, db: sqlite3.Connection) -> ValidationContext:
    """Constroi ValidationContext a partir dos registros ja persistidos no banco.

    Le o registro 0000 para determinar regime, UF, periodo e CNPJ.
    Popula caches de participantes (0150), produtos (0200) e naturezas (0400).
    """
    ctx = ValidationContext(file_id=file_id)

    # -- Reference loader --
    loader = ReferenceLoader()
    ctx.reference_loader = loader
    ctx.available_tables = loader.available_tables()

    # -- Registro 0000 --
    row_0000 = db.execute(
        "SELECT fields_json FROM sped_records WHERE file_id = ? AND register = '0000' LIMIT 1",
        (file_id,),
    ).fetchone()

    if row_0000:
        f = _load_fields(row_0000, "0000")
        ctx.cod_ver = f.get("COD_VER", "")
        ctx.periodo_ini = _parse_date(f.get("DT_INI", ""))
        ctx.periodo_fim = _parse_date(f.get("DT_FIN", ""))
        ctx.company_name = f.get("NOME", "")
        ctx.cnpj = f.get("CNPJ", "")
        ctx.uf_contribuinte = f.get("UF", "")
        ctx.ind_perfil = f.get("IND_PERFIL", "")
        ctx.regime = _determine_regime(ctx.ind_perfil)

    # -- Consultar cliente no MySQL (DCTF_WEB) pelo CNPJ --
    if ctx.cnpj:
        cliente = buscar_cliente(ctx.cnpj)
        ctx.cliente = cliente if cliente.encontrado else None

        # Se o MySQL tem regime_tributario, prevalece sobre o IND_PERFIL
        if cliente.encontrado and cliente.regime_tributario:
            regime_mysql = cliente.regime_tributario.strip().lower()
            if "simples" in regime_mysql:
                ctx.regime = TaxRegime.SIMPLES_NACIONAL
            elif regime_mysql in ("mei", "microempreendedor"):
                ctx.regime = TaxRegime.MEI
            elif regime_mysql in ("normal", "lucro real", "lucro presumido"):
                ctx.regime = TaxRegime.NORMAL

    # -- Resolver benefícios fiscais (JSON x MySQL) --
    if ctx.cliente and ctx.cliente.beneficios_fiscais and loader:
        resolvidos = loader.get_beneficios_do_cliente(ctx.cliente.beneficios_fiscais)
        ctx.beneficios_ativos = resolvidos
        # Verificar códigos não resolvidos (match normalizado)
        codigos_resolvidos = {
            loader._normalizar_codigo_beneficio(b.codigo) for b in resolvidos
        }
        for cod in ctx.cliente.beneficios_fiscais:
            if loader._normalizar_codigo_beneficio(cod) not in codigos_resolvidos:
                logger.warning(
                    "Beneficio '%s' declarado no MySQL sem JSON correspondente", cod
                )

    # Verificar se o usuario informou regime_override no upload
    row_override = db.execute(
        "SELECT regime_override FROM sped_files WHERE id = ?",
        (file_id,),
    ).fetchone()
    if row_override:
        override = row_override[0] if isinstance(row_override, tuple) else row_override["regime_override"]
        if override == "simples_nacional":
            ctx.regime = TaxRegime.SIMPLES_NACIONAL
        elif override == "normal":
            ctx.regime = TaxRegime.NORMAL

    # -- Participantes (0150) --
    rows_0150 = db.execute(
        "SELECT fields_json FROM sped_records WHERE file_id = ? AND register = '0150'",
        (file_id,),
    ).fetchall()
    for row in rows_0150:
        f = _load_fields(row, "0150")
        cod_part = f.get("COD_PART", "")
        if cod_part:
            ctx.participantes[cod_part] = {
                "nome": f.get("NOME", ""),
                "cnpj": f.get("CNPJ", ""),
                "ie": f.get("IE", ""),
                "uf": f.get("UF", ""),
                "cod_mun": f.get("COD_MUN", ""),
            }

    # -- Produtos (0200) --
    rows_0200 = db.execute(
        "SELECT fields_json FROM sped_records WHERE file_id = ? AND register = '0200'",
        (file_id,),
    ).fetchall()
    for row in rows_0200:
        f = _load_fields(row, "0200")
        cod_item = f.get("COD_ITEM", "")
        if cod_item:
            ctx.produtos[cod_item] = {
                "descr": f.get("DESCR_ITEM", ""),
                "ncm": f.get("COD_NCM", ""),
            }

    # -- Naturezas de operacao (0400) --
    rows_0400 = db.execute(
        "SELECT fields_json FROM sped_records WHERE file_id = ? AND register = '0400'",
        (file_id,),
    ).fetchall()
    for row in rows_0400:
        f = _load_fields(row, "0400")
        cod_nat = f.get("COD_NAT", "")
        descr = f.get("DESCR_NAT", "")
        if cod_nat:
            ctx.naturezas[cod_nat] = descr

    return ctx
