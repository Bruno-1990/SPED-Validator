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
from .beneficio_engine import BeneficioEngine
from .client_service import ClienteInfo, buscar_cliente
from .reference_loader import BeneficioProfile, ReferenceLoader


class TaxRegime(Enum):
    """Regime tributario detectado pelos CSTs reais do arquivo SPED (BUG-001 fix)."""

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
    """Contexto de validacao v2 — Context-First (Fase 2).

    Montado integralmente no Stage 0, ANTES de qualquer validacao.
    Imutavel apos montagem — nenhum validador altera o contexto.
    """

    # Identificacao
    file_id: int
    run_id: int = 0
    mode: str = "sped_only"  # "sped_only" | "sped_xml"

    # Regime (detectado por CSTs, NAO por IND_PERFIL — BUG-001)
    regime: TaxRegime = TaxRegime.UNKNOWN
    regime_source: str = "CST"  # "CST" | "CST+MYSQL" | "CONFLITO" | "MYSQL"

    # Metadados do arquivo (registro 0000)
    uf_contribuinte: str = ""
    periodo_ini: date | None = None
    periodo_fim: date | None = None
    ind_perfil: str = ""       # Armazenado mas NAO usado para regime
    ind_ativ: str = ""         # 0=industrial/equiparado, 1=outros
    cod_ver: str = ""
    cnpj: str = ""
    company_name: str = ""

    # Dados mestres do cliente (SQLite clientes ou MySQL DCTF_WEB)
    cliente: ClienteInfo | None = None
    cliente_id: int | None = None  # ID na tabela local clientes (se existir)

    # Beneficios fiscais resolvidos
    beneficios_ativos: list[BeneficioProfile] = field(default_factory=list)
    beneficio_engine: BeneficioEngine | None = None

    # Caches do Bloco 0 (imutaveis durante validacao)
    participantes: dict[str, dict] = field(default_factory=dict)  # cod_part -> dados
    produtos: dict[str, dict] = field(default_factory=dict)       # cod_item -> dados
    naturezas: dict[str, str] = field(default_factory=dict)       # cod_nat -> descr

    # Tabelas fiscais de referencia
    available_tables: list[str] = field(default_factory=list)
    tabelas_ausentes: list[str] = field(default_factory=list)
    reference_loader: ReferenceLoader | None = None

    # Emitentes SN (CRTs do historico de XMLs)
    emitentes_sn: set = field(default_factory=set)  # CNPJs com CRT=1

    # Regras vigentes
    active_rules: list[str] = field(default_factory=list)
    rule_index: object | None = None  # RuleIndex (import circular evitado)

    # XML (apenas no modo sped_xml)
    has_xmls: bool = False
    xml_by_chave: dict = field(default_factory=dict)
    xml_cobertura_pct: float = 0.0

    # Controle de qualidade do contexto
    context_hash: str = ""
    context_warnings: list[str] = field(default_factory=list)

    # Retrocompatibilidade
    found_errors: list[str] = field(default_factory=list)


def _parse_date(dt_str: str) -> date | None:
    """Converte string DDMMAAAA para date."""
    if not dt_str or len(dt_str) != 8:
        return None
    try:
        return date(int(dt_str[4:8]), int(dt_str[2:4]), int(dt_str[0:2]))
    except (ValueError, IndexError):
        return None


def _determine_regime_by_cst(db: sqlite3.Connection, file_id: int) -> tuple[TaxRegime, str]:
    """Detecta regime tributario pelos CSTs reais do arquivo (BUG-001 fix).

    CORRECAO CRITICA: IND_PERFIL indica nivel de escrituracao, NAO regime.
    A deteccao usa exclusivamente CSTs encontrados em C170/C190.

    Returns:
        (regime, source): regime detectado e fonte da deteccao ("CST")
    """
    row = db.execute(
        """SELECT DISTINCT
            CASE
                WHEN CAST(json_extract(fields_json, '$.CST_ICMS') AS TEXT)
                    IN ('101','102','103','201','202','203','300','400','500','900')
                THEN 'SN'
                WHEN CAST(json_extract(fields_json, '$.CST_ICMS') AS INTEGER) BETWEEN 101 AND 900
                THEN 'SN'
                ELSE 'NORMAL'
            END as regime_type
        FROM sped_records
        WHERE file_id = ? AND register IN ('C170', 'C190')
              AND json_extract(fields_json, '$.CST_ICMS') IS NOT NULL
              AND json_extract(fields_json, '$.CST_ICMS') != ''
        LIMIT 500""",
        (file_id,),
    ).fetchall()

    regimes_found = {r[0] if isinstance(r, tuple) else r["regime_type"] for r in row}

    if "SN" in regimes_found:
        return TaxRegime.SIMPLES_NACIONAL, "CST"
    if "NORMAL" in regimes_found:
        return TaxRegime.NORMAL, "CST"
    return TaxRegime.UNKNOWN, "CST"


def _resolve_regime_with_mysql(
    regime_cst: TaxRegime, regime_mysql_str: str | None
) -> tuple[TaxRegime, str]:
    """Confirma regime CST com dados do MySQL. Se conflito, CST prevalece.

    Returns:
        (regime, source): "CST", "CST+MYSQL", ou "CONFLITO"
    """
    if not regime_mysql_str:
        return regime_cst, "CST"

    regime_mysql_str = regime_mysql_str.strip().lower()
    if "simples" in regime_mysql_str:
        regime_mysql = TaxRegime.SIMPLES_NACIONAL
    elif regime_mysql_str in ("mei", "microempreendedor"):
        regime_mysql = TaxRegime.MEI
    elif regime_mysql_str in ("normal", "lucro real", "lucro presumido"):
        regime_mysql = TaxRegime.NORMAL
    else:
        return regime_cst, "CST"

    if regime_cst == TaxRegime.UNKNOWN:
        return regime_mysql, "MYSQL"
    if regime_cst == regime_mysql or (
        regime_cst == TaxRegime.NORMAL and regime_mysql in (TaxRegime.NORMAL, TaxRegime.MEI)
    ):
        return regime_cst, "CST+MYSQL"

    # Conflito: CST prevalece como evidencia primaria
    logger.warning(
        "CONFLITO de regime: CST=%s vs MySQL=%s. CST prevalece. Requer revisao manual.",
        regime_cst.value, regime_mysql.value,
    )
    return regime_cst, "CONFLITO"


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
        # BUG-001 fix: IND_PERFIL armazenado mas NAO usado para regime

    # -- Detectar regime pelos CSTs reais do arquivo (BUG-001) --
    regime_cst, regime_source = _determine_regime_by_cst(db, file_id)
    ctx.regime = regime_cst
    ctx.regime_source = regime_source

    # -- Consultar cliente no MySQL (DCTF_WEB) pelo CNPJ --
    if ctx.cnpj:
        cliente = buscar_cliente(ctx.cnpj)
        ctx.cliente = cliente if cliente.encontrado else None

        # Confirmar regime CST com MySQL (se disponivel); CST prevalece em conflito
        if cliente.encontrado and cliente.regime_tributario:
            ctx.regime, ctx.regime_source = _resolve_regime_with_mysql(
                regime_cst, cliente.regime_tributario
            )

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

    # -- Instanciar BeneficioEngine (Fase 3) --
    ctx.beneficio_engine = BeneficioEngine(
        beneficios=ctx.beneficios_ativos,
        uf=ctx.uf_contribuinte or "ES",
        periodo_ini=ctx.periodo_ini,
    )
    # Detectar conflitos entre beneficios
    conflitos = ctx.beneficio_engine.get_conflitos_beneficios()
    for c in conflitos:
        ctx.context_warnings.append(f"CONFLITO de beneficios: {c}. Auditor deve revisar.")

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

    # -- IND_ATIV do 0000 --
    if row_0000:
        f0 = _load_fields(row_0000, "0000")
        ctx.ind_ativ = f0.get("IND_ATIV", "")

    # -- Emitentes SN (CRT=1) do historico de XMLs --
    ctx.emitentes_sn = _load_emitentes_sn(db)

    # -- Carregar cliente local (tabela clientes SQLite) --
    if ctx.cnpj:
        ctx.cliente_id = _get_cliente_local_id(db, ctx.cnpj)

    # -- Tabelas ausentes --
    ctx.tabelas_ausentes = _detect_missing_tables(loader)

    # -- Context hash (para invalidar cache IA) --
    ctx.context_hash = _compute_context_hash(ctx)

    # -- Context warnings --
    if ctx.regime_source == "CONFLITO":
        ctx.context_warnings.append(
            f"CONFLITO de regime: CST detectou {ctx.regime.value} mas cadastro diverge. Requer revisao."
        )
    if ctx.tabelas_ausentes:
        ctx.context_warnings.append(
            f"Tabelas ausentes: {', '.join(ctx.tabelas_ausentes)}. Cobertura da auditoria reduzida."
        )

    return ctx


# ──────────────────────────────────────────────
# Helpers Stage 0 (Context-First)
# ──────────────────────────────────────────────

def _load_emitentes_sn(db: sqlite3.Connection) -> set:
    """Carrega CNPJs de emitentes com CRT=1 (Simples Nacional) do historico."""
    try:
        rows = db.execute(
            "SELECT cnpj_emitente FROM emitentes_crt WHERE crt = 1"
        ).fetchall()
        return {r[0] if isinstance(r, tuple) else r["cnpj_emitente"] for r in rows}
    except sqlite3.OperationalError:
        # Tabela pode nao existir antes da Migration 14
        return set()


def _get_cliente_local_id(db: sqlite3.Connection, cnpj: str) -> int | None:
    """Busca ID do cliente na tabela local clientes (Migration 14)."""
    try:
        row = db.execute(
            "SELECT id FROM clientes WHERE cnpj = ? AND ativo = 1", (cnpj,)
        ).fetchone()
        if row:
            return row[0] if isinstance(row, tuple) else row["id"]
    except sqlite3.OperationalError:
        pass  # Tabela pode nao existir antes da Migration 14
    return None


def _detect_missing_tables(loader: ReferenceLoader | None) -> list[str]:
    """Detecta tabelas de referencia ausentes que reduzem cobertura."""
    ausentes = []
    if not loader:
        return ["reference_loader"]
    available = loader.available_tables()
    expected = ["aliquotas_internas_uf", "fcp_por_uf", "mva_por_ncm_uf",
                "codigos_ajuste_uf", "ibge_municipios"]
    for t in expected:
        if t not in available:
            ausentes.append(t)
    return ausentes


def _compute_context_hash(ctx: "ValidationContext") -> str:
    """Calcula hash do contexto para invalidar cache IA quando contexto muda."""
    import hashlib
    raw = (
        f"{ctx.regime.value}|{ctx.regime_source}|{ctx.uf_contribuinte}|"
        f"{ctx.periodo_ini}|{ctx.periodo_fim}|"
        f"{','.join(b.codigo for b in ctx.beneficios_ativos)}|"
        f"{len(ctx.active_rules)}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def create_validation_run(
    db: sqlite3.Connection, ctx: "ValidationContext"
) -> int:
    """Registra uma execucao de validacao na tabela validation_runs."""
    import json
    try:
        beneficios_json = json.dumps(
            [{"codigo": b.codigo, "tipo": getattr(b, "tipo", "")} for b in ctx.beneficios_ativos]
        )
        cursor = db.execute(
            """INSERT INTO validation_runs
               (file_id, mode, cliente_id, regime_usado, regime_source,
                beneficios_json, context_hash, rules_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (ctx.file_id, ctx.mode, ctx.cliente_id, ctx.regime.value,
             ctx.regime_source, beneficios_json, ctx.context_hash,
             ",".join(ctx.active_rules[:5])),
        )
        db.commit()
        return cursor.lastrowid
    except sqlite3.OperationalError:
        # Tabela pode nao existir antes da Migration 14
        return 0


def save_context_snapshot(
    db: sqlite3.Connection, ctx: "ValidationContext"
) -> None:
    """Salva snapshot do contexto fiscal para audit trail."""
    import json
    try:
        db.execute(
            """INSERT INTO fiscal_context_snapshots
               (run_id, cnpj, uf, periodo, regime, ind_perfil,
                beneficios_json, tables_available_json, context_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ctx.run_id, ctx.cnpj, ctx.uf_contribuinte,
             f"{ctx.periodo_ini}_{ctx.periodo_fim}",
             ctx.regime.value, ctx.ind_perfil,
             json.dumps([b.codigo for b in ctx.beneficios_ativos]),
             json.dumps(ctx.available_tables),
             ctx.context_hash),
        )
        db.commit()
    except sqlite3.OperationalError:
        pass  # Tabela pode nao existir antes da Migration 14
