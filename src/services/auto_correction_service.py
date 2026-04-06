"""Motor de auto-correção determinística para erros SPED.

MOD-10: Apenas correções determinísticas (formato de data, CNPJ, numérico) são
aplicadas automaticamente. Correções de CST, CFOP, alíquota e campos fiscais
sensíveis são retornadas como sugestões (suggested=True), nunca aplicadas.
"""

from __future__ import annotations

import sqlite3

from .correction_service import apply_correction

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


def auto_correct_errors(
    db: sqlite3.Connection,
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
    rows = db.execute(
        """SELECT ve.id, ve.record_id, ve.register, ve.field_no, ve.field_name,
                  ve.value, ve.error_type, ve.expected_value
           FROM validation_errors ve
           WHERE ve.file_id = ? AND ve.status = 'open' AND ve.auto_correctable = 1
           ORDER BY ve.line_number""",
        (file_id,),
    ).fetchall()

    for row in rows:
        error_id = row[0]
        record_id = row[1]
        register = row[2]
        field_no = row[3]
        field_name = row[4] or ""
        current_value = row[5] or ""
        error_type = row[6]
        expected_value = row[7]

        if not expected_value or not record_id or not field_no:
            continue

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
