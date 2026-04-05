"""Pipeline estagiado de validação SPED com progresso em tempo real."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from ..models import SpedRecord, ValidationError
from ..validator import load_field_definitions, validate_records
from ..validators.aliquota_validator import validate_aliquotas
from ..validators.correction_hypothesis import validate_with_hypotheses
from ..validators.cst_hypothesis import validate_cst_hypotheses
from ..validators.audit_rules import validate_audit_rules
from ..validators.beneficio_audit_validator import validate_beneficio_audit
from ..validators.c190_validator import validate_c190
from ..validators.cross_block_validator import validate_cross_blocks
from ..validators.cst_validator import validate_cst_and_exemptions
from ..validators.fiscal_semantics import validate_fiscal_semantics
from ..validators.intra_register_validator import validate_intra_register
from ..validators.pendentes_validator import validate_pendentes
from ..validators.tax_recalc import recalculate_taxes
from .error_messages import format_friendly_message, get_guidance
from .validation_service import _load_records, _severity_for


# ──────────────────────────────────────────────
# Progress tracking
# ──────────────────────────────────────────────

@dataclass
class PipelineProgress:
    """Estado do pipeline de validação em tempo real."""
    file_id: int
    stage: str = "pending"
    stage_progress: int = 0
    detail: str = ""
    total_errors: int = 0
    errors_by_stage: dict[str, int] = field(default_factory=dict)
    auto_corrected: int = 0
    done: bool = False

    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "stage": self.stage,
            "stage_progress": self.stage_progress,
            "detail": self.detail,
            "total_errors": self.total_errors,
            "errors_by_stage": self.errors_by_stage,
            "auto_corrected": self.auto_corrected,
            "done": self.done,
        }


# Pipelines ativos — seguro para SQLite single-process
_active_pipelines: dict[int, PipelineProgress] = {}


def get_pipeline_progress(file_id: int) -> PipelineProgress | None:
    return _active_pipelines.get(file_id)


# ──────────────────────────────────────────────
# Pipeline principal
# ──────────────────────────────────────────────

def run_pipeline(
    db: sqlite3.Connection,
    file_id: int,
    doc_db_path: str | None = None,
) -> PipelineProgress:
    """Executa o pipeline completo de validação em 4 estágios.

    Estágios:
    1. estrutural — campo-a-campo + formatos + intra-registro
    2. cruzamento — cross-block + recálculo tributário + CST
    3. enriquecimento — mensagens amigáveis + base legal
    4. auto_correcao — correções determinísticas
    """
    progress = PipelineProgress(file_id=file_id)
    _active_pipelines[file_id] = progress

    try:
        db.execute(
            "UPDATE sped_files SET status = 'validating', validation_stage = 'estrutural' WHERE id = ?",
            (file_id,),
        )
        db.commit()

        # Limpar correções e erros anteriores (corrections referencia validation_errors)
        db.execute("DELETE FROM corrections WHERE file_id = ?", (file_id,))
        db.execute("DELETE FROM validation_errors WHERE file_id = ?", (file_id,))
        db.commit()

        records = _load_records(db, file_id)

        # ── Estágio 1: Estrutural ──
        progress.stage = "estrutural"
        progress.stage_progress = 0

        structural_errors: list[ValidationError] = []
        if doc_db_path:
            progress.detail = "Validando campos: tipo, tamanho, obrigatoriedade"
            field_defs = load_field_definitions(doc_db_path)
            structural_errors.extend(validate_records(records, field_defs))
        progress.stage_progress = 50

        progress.detail = "Validando formatos: CNPJ, datas, CFOP, C100, C170"
        structural_errors.extend(validate_intra_register(records))
        progress.stage_progress = 100

        _persist_stage_errors(db, file_id, structural_errors)
        progress.errors_by_stage["estrutural"] = len(structural_errors)
        progress.total_errors = len(structural_errors)

        db.execute(
            "UPDATE sped_files SET validation_stage = 'cruzamento' WHERE id = ?",
            (file_id,),
        )
        db.commit()

        # ── Estágio 2: Cruzamento ──
        progress.stage = "cruzamento"
        progress.stage_progress = 0

        cross_errors: list[ValidationError] = []
        progress.detail = "Cruzando C100 x C170 x C190, referencias 0150/0200, E110"
        cross_errors.extend(validate_cross_blocks(records))
        progress.stage_progress = 20

        progress.detail = "Recalculando ICMS, ICMS-ST, IPI, PIS/COFINS nos C170"
        cross_errors.extend(recalculate_taxes(records))
        progress.stage_progress = 45

        progress.detail = "Validando CST ICMS, isencoes e Bloco H"
        cross_errors.extend(validate_cst_and_exemptions(records))
        progress.stage_progress = 65

        progress.detail = "Analise semantica: CST x CFOP, aliquota zero, monofasicos"
        cross_errors.extend(validate_fiscal_semantics(records))
        progress.stage_progress = 85

        progress.detail = "Auditoria fiscal: CFOP x UF, parametrizacao, remessas, inventario"
        cross_errors.extend(validate_audit_rules(records))
        progress.stage_progress = 90

        progress.detail = "Validando aliquotas e consolidacao C190"
        cross_errors.extend(validate_aliquotas(records))
        cross_errors.extend(validate_c190(records))
        progress.stage_progress = 93

        progress.detail = "Auditoria de beneficios fiscais e regras pendentes"
        cross_errors.extend(validate_beneficio_audit(records))
        cross_errors.extend(validate_pendentes(records))
        progress.stage_progress = 97

        progress.detail = "Hipoteses de correcao inteligente (aliquota e CST)"
        cross_errors.extend(validate_with_hypotheses(records))
        cross_errors.extend(validate_cst_hypotheses(records))
        progress.stage_progress = 100

        # Deduplicar: hipoteses inteligentes supersede erros genericos
        cross_errors = _deduplicate_errors(cross_errors)

        _persist_stage_errors(db, file_id, cross_errors)
        progress.errors_by_stage["cruzamento"] = len(cross_errors)
        progress.total_errors += len(cross_errors)

        db.execute(
            "UPDATE sped_files SET validation_stage = 'enriquecimento' WHERE id = ?",
            (file_id,),
        )
        db.commit()

        # ── Estágio 3: Enriquecimento ──
        progress.stage = "enriquecimento"
        progress.stage_progress = 0
        progress.detail = "Gerando mensagens amigaveis e buscando base legal"

        _enrich_errors(db, file_id, doc_db_path, progress)
        progress.stage_progress = 100

        # Finalizar
        db.execute(
            """UPDATE sped_files
               SET status = 'validated',
                   total_errors = ?,
                   validation_stage = 'concluido'
               WHERE id = ?""",
            (progress.total_errors, file_id),
        )
        db.commit()

        db.execute(
            "INSERT INTO audit_log (file_id, action, details) VALUES (?, ?, ?)",
            (
                file_id,
                "validate",
                f"Pipeline completo: {progress.total_errors} erros encontrados.",
            ),
        )
        db.commit()

        progress.stage = "concluido"
        progress.done = True

    except Exception:
        progress.done = True
        progress.stage = "erro"
        db.execute(
            "UPDATE sped_files SET status = 'error' WHERE id = ?",
            (file_id,),
        )
        db.commit()
        raise
    finally:
        # Limpar após conclusão (com delay para SSE ler o estado final)
        pass

    return progress


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _deduplicate_errors(errors: list[ValidationError]) -> list[ValidationError]:
    """Remove erros duplicados e genericos quando outro erro ja cobre o mesmo item.

    Duas estrategias:
    1. Hipoteses inteligentes supersede erros genericos (mesma linha)
    2. Mesma linha + mesmo campo: manter apenas o mais especifico
       (com expected_value ou maior prioridade)
    """
    # ── Estrategia 1: hipoteses supersede genericos ──
    lines_aliq_hyp: set[int] = set()
    lines_cst_hyp: set[int] = set()

    for err in errors:
        if err.error_type == "ALIQ_ICMS_AUSENTE":
            lines_aliq_hyp.add(err.line_number)
        elif err.error_type == "CST_HIPOTESE":
            lines_cst_hyp.add(err.line_number)

    _SUPRIMIDOS_POR_ALIQ = {"CST_ALIQ_ZERO_FORTE"}
    _SUPRIMIDOS_POR_CST = {
        "CST_ALIQ_ZERO_FORTE",
        "CST_ALIQ_ZERO_MODERADO",
        "ISENCAO_INCONSISTENTE",
    }

    after_hyp = []
    for err in errors:
        ln = err.line_number
        et = err.error_type

        if ln in lines_aliq_hyp and et in _SUPRIMIDOS_POR_ALIQ:
            continue
        if ln in lines_cst_hyp and et in _SUPRIMIDOS_POR_CST:
            continue

        after_hyp.append(err)

    # ── Estrategia 2: mesma linha + mesmo campo = manter o melhor ──
    # Quando dois erros apontam para o mesmo (linha, campo), manter
    # o que tem expected_value (acionavel) ou o mais especifico.
    seen: dict[tuple[int, str], ValidationError] = {}
    result = []

    for err in after_hyp:
        key = (err.line_number, err.field_name or "")

        # Erros sem field_name (genericos) nao deduplicam por campo
        if not err.field_name:
            result.append(err)
            continue

        if key not in seen:
            seen[key] = err
            result.append(err)
        else:
            existing = seen[key]
            # Preferir o que tem expected_value (acionavel pelo usuario)
            if err.expected_value and not existing.expected_value:
                result.remove(existing)
                seen[key] = err
                result.append(err)
            # Se ambos tem expected_value, preferir o mais especifico
            # (CALCULO_DIVERGENTE > CRUZAMENTO_DIVERGENTE)
            elif err.expected_value and existing.expected_value:
                # Manter o existente (primeiro encontrado)
                pass

    return result


def _persist_stage_errors(
    db: sqlite3.Connection,
    file_id: int,
    errors: list[ValidationError],
) -> None:
    """Persiste erros de um estágio (append, não limpa anteriores)."""
    # Cache line_number -> record_id
    line_to_record: dict[int, int] = {}
    rows = db.execute(
        "SELECT id, line_number FROM sped_records WHERE file_id = ?",
        (file_id,),
    ).fetchall()
    for r in rows:
        ln = r[1] if isinstance(r, (tuple, list)) else r["line_number"]
        rid = r[0] if isinstance(r, (tuple, list)) else r["id"]
        line_to_record[ln] = rid

    for err in errors:
        record_id = line_to_record.get(err.line_number) if err.line_number > 0 else None
        db.execute(
            """INSERT INTO validation_errors
               (file_id, record_id, line_number, register, field_no, field_name, value,
                error_type, severity, message, expected_value)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                file_id, record_id, err.line_number, err.register, err.field_no,
                err.field_name, err.value, err.error_type,
                _severity_for(err.error_type), err.message,
                err.expected_value,
            ),
        )
    db.commit()


def _enrich_errors(
    db: sqlite3.Connection,
    file_id: int,
    doc_db_path: str | None,
    progress: PipelineProgress,
) -> None:
    """Enriquece erros com mensagens amigáveis e base legal.

    Agrupa erros por (error_type, register, field_name) para evitar buscas
    redundantes — ex: 500 erros iguais fazem apenas 1 busca.
    """
    rows = db.execute(
        """SELECT id, error_type, register, field_name, field_no, value,
                  line_number, expected_value, message
           FROM validation_errors
           WHERE file_id = ? AND status = 'open'""",
        (file_id,),
    ).fetchall()

    if not rows:
        return

    # Agrupar por chave única para busca de base legal
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        key = (row[1], row[2], row[3] or "")  # error_type, register, field_name
        entry = {
            "id": row[0],
            "error_type": row[1],
            "register": row[2],
            "field_name": row[3] or "",
            "field_no": row[4] or 0,
            "value": row[5] or "",
            "line_number": row[6],
            "expected_value": row[7] or "",
            "message": row[8],
        }
        groups.setdefault(key, []).append(entry)

    total_groups = len(groups)
    processed = 0

    for (error_type, register, field_name), entries in groups.items():
        # Gerar mensagem amigável (mesmo template para todos do grupo)
        sample = entries[0]
        friendly = format_friendly_message(
            error_type,
            field_name=field_name,
            register=register,
            line=sample["line_number"],
            value=sample["value"],
            expected=sample["expected_value"],
        )
        guidance = get_guidance(error_type)

        # Buscar base legal (1 busca por grupo)
        legal_basis_json = None
        if doc_db_path and field_name:
            legal_basis_json = _search_legal_basis(
                doc_db_path, register, field_name, sample["field_no"],
                sample["message"],
            )

        # Determinar se auto-corrigível (botao "Corrigir" no frontend)
        auto_correctable = 0
        if error_type in ("CALCULO_DIVERGENTE", "SOMA_DIVERGENTE") and sample["expected_value"]:
            auto_correctable = 1
        elif error_type == "CONTAGEM_DIVERGENTE" and sample["expected_value"]:
            auto_correctable = 1
        elif error_type == "ALIQ_ICMS_AUSENTE" and sample["expected_value"]:
            # Botao aparece, mas auto_correction_service pula (requer clique do usuario)
            auto_correctable = 1
        elif error_type == "CST_HIPOTESE" and sample["expected_value"]:
            # Hipotese de CST — sempre requer confirmacao manual
            auto_correctable = 1
        elif error_type == "CALCULO_ARREDONDAMENTO" and sample["expected_value"]:
            # Arredondamento — usuario decide se padroniza o valor
            auto_correctable = 1

        # Atualizar todos os erros do grupo
        for entry in entries:
            # Personalizar mensagem com dados específicos de cada erro
            entry_friendly = format_friendly_message(
                error_type,
                field_name=field_name,
                register=register,
                line=entry["line_number"],
                value=entry["value"],
                expected=entry["expected_value"],
            )

            entry_auto = auto_correctable
            if error_type in ("CALCULO_DIVERGENTE", "SOMA_DIVERGENTE") and not entry["expected_value"]:
                entry_auto = 0

            doc_suggestion = f"{friendly}\n\n**Como corrigir:** {guidance}"

            db.execute(
                """UPDATE validation_errors
                   SET friendly_message = ?,
                       legal_basis = ?,
                       doc_suggestion = ?,
                       auto_correctable = ?
                   WHERE id = ?""",
                (entry_friendly, legal_basis_json, doc_suggestion, entry_auto, entry["id"]),
            )

        processed += 1
        progress.stage_progress = int(processed / total_groups * 100)

    db.commit()


def _search_legal_basis(
    doc_db_path: str,
    register: str,
    field_name: str,
    field_no: int,
    error_message: str,
) -> str | None:
    """Busca base legal na documentação usando search_for_error.

    Retorna JSON string com fonte, artigo e trecho, ou None.
    """
    try:
        from ..searcher import search_for_error

        results = search_for_error(
            register=register,
            field_name=field_name,
            field_no=field_no,
            error_message=error_message,
            db_path=doc_db_path,
            top_k=2,
        )

        if not results:
            return None

        best = results[0]
        fonte = best.chunk.source_file
        if "/" in fonte:
            fonte = fonte.rsplit("/", 1)[-1]
        if fonte.endswith(".md"):
            fonte = fonte[:-3]
        fonte = fonte.replace("_", " ").replace("-", " ").title()

        legal = {
            "fonte": fonte,
            "artigo": best.chunk.heading or "",
            "trecho": (best.chunk.content or "")[:500],
            "score": round(best.score, 3),
        }
        return json.dumps(legal, ensure_ascii=False)

    except Exception:
        return None


def cleanup_pipeline(file_id: int) -> None:
    """Remove pipeline do rastreamento após SSE encerrar."""
    _active_pipelines.pop(file_id, None)
