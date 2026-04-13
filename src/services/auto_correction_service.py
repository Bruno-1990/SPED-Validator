"""Motor de auto-correção determinística para erros SPED.

MOD-10: Apenas correções determinísticas (formato de data, CNPJ, numérico) são
aplicadas automaticamente. Correções de CST, CFOP, alíquota e campos fiscais
sensíveis são retornadas como sugestões (suggested=True), nunca aplicadas.
"""

from __future__ import annotations

from .db_types import AuditConnection
from .correction_service import CorrectionBlockedError, apply_correction

_SQL_AUTO_ROWS = """SELECT ve.id, ve.record_id, ve.register, ve.field_no, ve.field_name,
                  ve.value, ve.error_type, ve.expected_value, ve.categoria
           FROM validation_errors ve
           WHERE ve.file_id = ? AND ve.status = 'open' AND ve.auto_correctable = 1
           ORDER BY ve.line_number"""

_SQL_AUTO_ROWS_LEGACY = """SELECT ve.id, ve.record_id, ve.register, ve.field_no, ve.field_name,
                  ve.value, ve.error_type, ve.expected_value, 'fiscal' AS categoria
           FROM validation_errors ve
           WHERE ve.file_id = ? AND ve.status = 'open' AND ve.auto_correctable = 1
           ORDER BY ve.line_number"""

# Campos que NUNCA devem ser auto-corrigidos (exigem aprovação humana)
_PROHIBITED_AUTO_FIELDS = frozenset({
    "CST_ICMS", "CFOP", "ALIQ_ICMS", "CST_IPI", "COD_AJ_APUR", "VL_AJ_APUR",
    "CST_PIS", "CST_COFINS",
})

# Tipos de erro que envolvem campos fiscais sensíveis (nunca auto-corrigir)
_PROHIBITED_ERROR_TYPES = frozenset({
    "CST_HIPOTESE", "ALIQ_ICMS_AUSENTE", "CALCULO_ARREDONDAMENTO",
    "CST_INVALIDO", "CFOP_INVALIDO",
})

# Tipos determinísticos seguros para auto-correção
_DETERMINISTIC_TYPES = frozenset({
    "CALCULO_DIVERGENTE", "SOMA_DIVERGENTE", "CONTAGEM_DIVERGENTE",
})

# Divergências field_map (referência XML) — auto-aplicar só valores monetários/qtd/data
# (NUM_DOC/SER/CST/CFOP etc. ficam como sugestão — governança em correction_service.)
_FIELD_MAP_AUTO_SAFE = frozenset({
    "VL_DOC", "VL_ICMS", "VL_ICMS_ST", "VL_IPI", "VL_BC_ICMS",
    "DT_DOC", "COD_SIT",
    "VL_ITEM", "QTD",
})


def auto_correct_errors(
    db: AuditConnection,
    file_id: int,
    doc_db_path: str | None = None,
) -> list[dict]:
    """Aplica correções automáticas apenas para erros determinísticos seguros.

    Correções de CST, CFOP, alíquota e campos sensíveis são retornadas como
    sugestões (suggested=True) e nunca aplicadas automaticamente.

    Retorna lista de correções aplicadas e sugestões.
    """
    results: list[dict] = []

    # Buscar erros auto-corrigíveis
    try:
        rows = db.execute(_SQL_AUTO_ROWS, (file_id,)).fetchall()
    except Exception:
        rows = db.execute(_SQL_AUTO_ROWS_LEGACY, (file_id,)).fetchall()

    for row in rows:
        error_id = row[0]
        record_id = row[1]
        register = row[2]
        field_no = row[3]
        field_name = row[4] or ""
        current_value = row[5] or ""
        error_type = row[6]
        expected_value = row[7]
        try:
            categoria = row[8]  # type: ignore[index]
        except (IndexError, KeyError):
            try:
                categoria = row["categoria"]  # type: ignore[index]
            except (KeyError, TypeError):
                categoria = ""

        if not expected_value or not record_id or not field_no:
            continue

        is_fm = (error_type or "").startswith("FM_")
        xml_field_map = categoria == "field_map_xml" and is_fm and field_name in _FIELD_MAP_AUTO_SAFE

        # Campos proibidos → sugestão apenas
        if field_name in _PROHIBITED_AUTO_FIELDS or error_type in _PROHIBITED_ERROR_TYPES:
            results.append({
                "error_id": error_id,
                "record_id": record_id,
                "register": register,
                "field_no": field_no,
                "field_name": field_name,
                "old_value": current_value,
                "suggested_value": expected_value,
                "error_type": error_type,
                "suggested": True,
                "applied": False,
            })
            continue

        # Divergência SPED x XML (field_map) com campo seguro — aplicar como determinística
        if xml_field_map:
            try:
                success = apply_correction(
                    db=db,
                    file_id=file_id,
                    record_id=record_id,
                    field_no=field_no,
                    field_name=field_name,
                    new_value=expected_value,
                    error_id=error_id,
                    justificativa="Correcao automatica alinhada ao valor de referencia da NF-e (XML).",
                    correction_type="deterministic",
                    rule_id=error_type,
                )
            except CorrectionBlockedError:
                success = False
            if success:
                results.append({
                    "error_id": error_id,
                    "record_id": record_id,
                    "register": register,
                    "field_no": field_no,
                    "field_name": field_name,
                    "old_value": current_value,
                    "new_value": expected_value,
                    "error_type": error_type,
                    "suggested": False,
                    "applied": True,
                })
            else:
                results.append({
                    "error_id": error_id,
                    "record_id": record_id,
                    "register": register,
                    "field_no": field_no,
                    "field_name": field_name,
                    "old_value": current_value,
                    "suggested_value": expected_value,
                    "error_type": error_type,
                    "suggested": True,
                    "applied": False,
                })
            continue

        # Apenas tipos determinísticos são auto-aplicados
        if error_type not in _DETERMINISTIC_TYPES:
            results.append({
                "error_id": error_id,
                "record_id": record_id,
                "register": register,
                "field_no": field_no,
                "field_name": field_name,
                "old_value": current_value,
                "suggested_value": expected_value,
                "error_type": error_type,
                "suggested": True,
                "applied": False,
            })
            continue

        # Aplicar correção determinística
        try:
            success = apply_correction(
                db=db,
                file_id=file_id,
                record_id=record_id,
                field_no=field_no,
                field_name=field_name,
                new_value=expected_value,
                error_id=error_id,
                justificativa="Correção determinística automática — valor calculado sem ambiguidade",
                correction_type="deterministic",
                rule_id=error_type,
            )
        except CorrectionBlockedError:
            success = False

        if success:
            db.execute(
                """UPDATE corrections
                   SET applied_by = 'auto'
                   WHERE id = (
                       SELECT id FROM corrections
                       WHERE file_id = ? AND record_id = ? AND field_no = ?
                       ORDER BY applied_at DESC LIMIT 1
                   )""",
                (file_id, record_id, field_no),
            )
            db.commit()

            results.append({
                "error_id": error_id,
                "record_id": record_id,
                "register": register,
                "field_no": field_no,
                "field_name": field_name,
                "old_value": current_value,
                "new_value": expected_value,
                "error_type": error_type,
                "suggested": False,
                "applied": True,
            })

    return results
