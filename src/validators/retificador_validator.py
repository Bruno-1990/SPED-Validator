"""Validador de retificadores SPED (MOD-16).

Regras implementadas:
- RET_001: Retificador com periodo diferente da original (error)
- RET_002: Retificador sem original no sistema (warning informativo)
"""

from __future__ import annotations

from ..models import SpedRecord, ValidationError
from ..services.db_types import AuditConnection
from ..parser import group_by_register
from .helpers import make_error


def validate_retificador(
    records: list[SpedRecord],
    db: AuditConnection | None = None,
    file_id: int | None = None,
) -> list[ValidationError]:
    """Valida consistencia de retificadores SPED."""
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    rec_0000_list = groups.get("0000", [])
    if not rec_0000_list:
        return errors

    rec_0000 = rec_0000_list[0]
    cod_fin_raw = rec_0000.fields.get("COD_FIN", "0")
    try:
        cod_ver = int(cod_fin_raw)
    except (ValueError, TypeError):
        cod_ver = 0

    if cod_ver == 0:
        return errors

    # E um retificador — precisa do DB para validar
    if db is None or file_id is None:
        return errors

    cnpj = rec_0000.fields.get("CNPJ", "")
    dt_ini = rec_0000.fields.get("DT_INI", "")
    dt_fin = rec_0000.fields.get("DT_FIN", "")

    if not cnpj or not dt_ini or not dt_fin:
        return errors

    # Buscar original (COD_VER=0, mesmo CNPJ+periodo)
    row = db.execute(
        """SELECT id, period_start, period_end FROM sped_files
           WHERE cnpj = ? AND cod_ver = 0 AND id != ?
           ORDER BY id LIMIT 1""",
        (cnpj, file_id),
    ).fetchone()

    if row is None:
        # RET_002: retificador sem original no sistema
        errors.append(make_error(
            record=rec_0000,
            field_name="COD_VER",
            error_type="RET_002",
            message=(
                f"Retificador (COD_VER={cod_ver}) sem arquivo original no sistema "
                f"para CNPJ {cnpj}, periodo {dt_ini}-{dt_fin}. "
                "A original pode estar em outro sistema."
            ),
            field_no=2,
            value=str(cod_ver),
        ))
        return errors

    # Original encontrada — verificar periodo
    orig_start = row[1] if isinstance(row, tuple) else row["period_start"]
    orig_end = row[2] if isinstance(row, tuple) else row["period_end"]

    if orig_start != dt_ini or orig_end != dt_fin:
        errors.append(make_error(
            record=rec_0000,
            field_name="DT_INI",
            error_type="RET_001",
            message=(
                f"Retificador (COD_VER={cod_ver}) com periodo {dt_ini}-{dt_fin} "
                f"diferente da original ({orig_start}-{orig_end}). "
                "Retificacao deve manter o mesmo periodo da escrituracao original."
            ),
            field_no=4,
            value=f"{dt_ini}-{dt_fin}",
            expected_value=f"{orig_start}-{orig_end}",
        ))

    return errors
