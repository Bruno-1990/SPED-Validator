"""Pipeline estagiado de validação SPED com progresso em tempo real."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

from .db_types import AuditConnection
from ..models import ValidationError
from ..validator import load_field_definitions, validate_records
from ..validators.apuracao_validator import validate_apuracao
from ..validators.aliquota_validator import validate_aliquotas
from ..validators.audit_rules import validate_audit_rules
from ..validators.base_calculo_validator import validate_base_calculo
from ..validators.beneficio_audit_validator import validate_beneficio_audit
from ..validators.beneficio_cross_validator import validate_beneficio_cross
from ..validators.beneficio_validator import validate_beneficio, validate_beneficio_engine
from ..validators.bloco_c_servicos_validator import validate_bloco_c_servicos
from ..validators.encadeamento_validator import validate_encadeamento
from ..validators.bloco_d_validator import validate_bloco_d
from ..validators.bloco_k_validator import validate_bloco_k
from ..validators.retificador_validator import validate_retificador
from ..validators.c190_validator import validate_c190
from ..validators.cfop_validator import validate_cfop
from ..validators.correction_hypothesis import validate_with_hypotheses
from ..validators.cross_block_validator import validate_cross_blocks
from ..validators.cst_hypothesis import validate_cst_hypotheses
from ..validators.cst_validator import validate_cst_and_exemptions
from ..validators.destinatario_validator import validate_destinatario
from ..validators.devolucao_validator import validate_devolucao
from ..validators.difal_validator import validate_difal
from ..validators.fiscal_semantics import validate_fiscal_semantics
from ..validators.intra_register_validator import validate_intra_register
from ..validators.ipi_validator import validate_ipi
from ..validators.ncm_validator import validate_ncm
from ..validators.parametrizacao_validator import validate_parametrizacao
from ..validators.pis_cofins_validator import validate_pis_cofins
from ..validators.pendentes_validator import validate_pendentes
from ..validators.simples_validator import validate_simples
from ..validators.st_validator import validate_st, validate_st_mva
from ..validators.tax_recalc import recalculate_taxes
from .context_builder import build_context
from .error_messages import format_friendly_message, get_guidance
from .rule_loader import RuleLoader
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
    risk_score: float = 0.0
    coverage_score: float = 0.0

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
            "risk_score": self.risk_score,
            "coverage_score": self.coverage_score,
        }


# Pipelines ativos — seguro para SQLite single-process
_active_pipelines: dict[int, PipelineProgress] = {}


def get_pipeline_progress(file_id: int) -> PipelineProgress | None:
    return _active_pipelines.get(file_id)


# ──────────────────────────────────────────────
# Pipeline principal
# ──────────────────────────────────────────────

def run_pipeline(
    db: AuditConnection,
    file_id: int,
    doc_db_path: str | None = None,
    validation_mode: str = "sped_only",
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

        # BUG-006 fix: NAO deletar erros agora.
        # Erros serao acumulados em memoria e trocados atomicamente ao final.

        # ── Stage 0: Montagem de Contexto (Context-First) ──
        context = build_context(file_id, db, validation_mode=validation_mode)

        # Registrar execucao e salvar snapshot (Migration 14)
        from .context_builder import create_validation_run, save_context_snapshot
        context.run_id = create_validation_run(db, context)
        save_context_snapshot(db, context)

        # Carregar apenas regras vigentes para o período do arquivo
        from .rule_loader import RuleIndex
        active_error_types: set[str] | None = None
        rule_index: RuleIndex | None = None
        if context.periodo_ini and context.periodo_fim:
            loader = RuleLoader()
            active_rules = loader.load_rules_for_period(
                context.periodo_ini, context.periodo_fim
            )
            all_rules = loader.load_all_rules()
            context.active_rules = [r["id"] for r in active_rules]
            rule_index = RuleIndex(active_rules, all_rules)
            context.rule_index = rule_index
            active_error_types = rule_index._active_error_types

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
        structural_errors.extend(validate_intra_register(records, context=context))
        progress.stage_progress = 100

        structural_errors = _filter_by_vigencia(structural_errors, active_error_types)
        _persist_stage_errors(db, file_id, structural_errors, rule_index=rule_index)
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
        cross_errors.extend(validate_cross_blocks(records, context=context))
        progress.stage_progress = 15

        if context.mode == "sped_xml" and context.has_xmls:
            progress.detail = "Conferencia declarativa SPED x XML (field_map C100)..."
            from ..validators.field_map_validator import validate_field_map_c100

            cross_errors.extend(validate_field_map_c100(db, file_id, records, context))

        progress.stage_progress = 20

        progress.detail = "Recalculando ICMS, ICMS-ST, IPI, PIS/COFINS nos C170"
        cross_errors.extend(recalculate_taxes(records, context=context))
        progress.stage_progress = 45

        if context.mode == "sped_xml" and context.has_xmls:
            progress.detail = (
                "Conferencia declarativa SPED x XML (field_map C170 itens, pos-recalculo interno)..."
            )
            from ..validators.field_map_validator import (
                validate_field_map_c170,
                validate_field_map_c190,
            )

            cross_errors.extend(validate_field_map_c170(db, file_id, records, context))
            progress.detail = (
                "Conferencia declarativa SPED x XML (field_map C190 agregado x XML)..."
            )
            cross_errors.extend(validate_field_map_c190(db, file_id, records, context))

        progress.detail = "Validando CST ICMS, isencoes e Bloco H"
        cross_errors.extend(validate_cst_and_exemptions(records, context=context))
        progress.stage_progress = 65

        progress.detail = "Analise semantica: CST x CFOP, aliquota zero, monofasicos"
        cross_errors.extend(validate_fiscal_semantics(records, context=context))
        progress.stage_progress = 83

        progress.detail = "PIS/COFINS: direcao, consistencia CST x campos"
        cross_errors.extend(validate_pis_cofins(records, context=context))
        progress.stage_progress = 85

        progress.detail = "Auditoria fiscal: CFOP x UF, parametrizacao, remessas, inventario"
        cross_errors.extend(validate_audit_rules(records, context=context))
        progress.stage_progress = 88

        progress.detail = "Parametrizacao sistematica: erros por item, UF e data"
        cross_errors.extend(validate_parametrizacao(records, context=context))
        progress.stage_progress = 89

        progress.detail = "NCM: tratamento tributario e NCM generico"
        cross_errors.extend(validate_ncm(records, context=context))
        progress.stage_progress = 90

        progress.detail = "Validando aliquotas e consolidacao C190"
        cross_errors.extend(validate_aliquotas(records, context=context))
        cross_errors.extend(validate_c190(records, context=context))
        cross_errors.extend(validate_bloco_d(records, context=context))
        progress.stage_progress = 93

        progress.detail = "Auditoria de beneficios fiscais e regras pendentes"
        cross_errors.extend(validate_beneficio_audit(records, context=context))
        cross_errors.extend(validate_pendentes(records, context=context))
        progress.stage_progress = 97

        progress.detail = "Base de calculo ICMS (BASE_001 a BASE_006)"
        cross_errors.extend(validate_base_calculo(records, context=context))
        progress.stage_progress = 97

        progress.detail = "DIFAL (Diferencial de Aliquota Interestadual)"
        cross_errors.extend(validate_difal(records, context=context))
        progress.stage_progress = 97

        progress.detail = "Beneficios fiscais (BENE_001 a BENE_003)"
        cross_errors.extend(validate_beneficio(records, context=context))

        progress.detail = "Cruzamento beneficios fiscais x regras JSON"
        cross_errors.extend(validate_beneficio_cross(records, context=context))

        progress.detail = "Beneficios via BeneficioEngine (CST, aliquota, E111)"
        cross_errors.extend(validate_beneficio_engine(records, context=context))

        progress.detail = "Devolucoes (DEV_001 a DEV_003)"
        cross_errors.extend(validate_devolucao(records, context=context))

        progress.detail = "IPI: reflexo BC, CST monetario"
        cross_errors.extend(validate_ipi(records, context=context))

        progress.detail = "Destinatario: IE, UF, CEP"
        cross_errors.extend(validate_destinatario(records, context=context))

        progress.detail = "CFOP: interestadual x interno, DIFAL"
        cross_errors.extend(validate_cfop(records, context=context))
        progress.stage_progress = 95

        progress.detail = "ICMS-ST: apuracao, CST 60, MVA"
        cross_errors.extend(validate_st(records, context=context))
        cross_errors.extend(validate_st_mva(records, context=context))
        progress.stage_progress = 97

        progress.detail = "Simples Nacional: CSOSN, credito, PIS/COFINS"
        cross_errors.extend(validate_simples(records, context=context))
        progress.stage_progress = 98

        progress.detail = "Apuracao ICMS: reconciliacao C190 x E110 x E111 x E116"
        cross_errors.extend(validate_apuracao(records, context=context))

        progress.detail = "Bloco C Servicos (C400/C490/C500/C590), Bloco K e Retificadores"
        cross_errors.extend(validate_bloco_c_servicos(records, context=context))
        cross_errors.extend(validate_bloco_k(records, context=context))
        cross_errors.extend(validate_retificador(records, db=db, file_id=file_id))

        progress.detail = "Encadeamento fiscal: C100→C170, ST apuracao, IPI apuracao"
        cross_errors.extend(validate_encadeamento(records, context=context))

        progress.detail = "Hipoteses de correcao inteligente (aliquota e CST)"
        cross_errors.extend(validate_with_hypotheses(records, context=context))
        cross_errors.extend(validate_cst_hypotheses(records, context=context))
        progress.stage_progress = 100

        # Deduplicar: hipoteses inteligentes supersede erros genericos
        cross_errors = _deduplicate_errors(cross_errors)
        cross_errors = _filter_by_vigencia(cross_errors, active_error_types)

        _persist_stage_errors(db, file_id, cross_errors, rule_index=rule_index)
        progress.errors_by_stage["cruzamento"] = len(cross_errors)
        progress.total_errors += len(cross_errors)

        # ── Estágio 2.5: Motor de Cruzamento XC (XML x SPED) ──
        if context.mode == "sped_xml" and context.has_xmls:
            progress.detail = "Motor de Cruzamento XC: construindo escopos e executando regras XC001-XC095"
            try:
                from .cross_engine import CrossValidationEngine
                xc_engine = CrossValidationEngine(
                    db, file_id,
                    regime=context.regime.value if hasattr(context.regime, 'value') else str(context.regime),
                    cod_ver=context.cod_ver,
                    benefit_context=",".join(b.codigo for b in context.beneficios_ativos) if context.beneficios_ativos else "",
                )
                xc_findings = xc_engine.run()
                xc_engine.persist_findings()
                xc_engine.persist_to_legacy_table()
                xc_summary = xc_engine.get_summary()
                progress.errors_by_stage["cruzamento_xc"] = xc_summary.get("total_errors", 0)
                progress.total_errors += xc_summary.get("total_errors", 0)
                logger.info(
                    "Motor XC: %d findings (%d erros, %d escopos)",
                    xc_summary.get("total_findings", 0),
                    xc_summary.get("total_errors", 0),
                    xc_summary.get("total_scopes", 0),
                )
            except Exception as e:
                logger.error("Erro no Motor de Cruzamento XC: %s", e, exc_info=True)

        db.execute(
            "UPDATE sped_files SET validation_stage = 'enriquecimento' WHERE id = ?",
            (file_id,),
        )
        db.commit()

        # ── Estágio 3: Enriquecimento ──
        progress.stage = "enriquecimento"
        progress.stage_progress = 0
        progress.detail = "Gerando mensagens amigaveis e buscando base legal"

        _enrich_errors(db, file_id, doc_db_path, progress, rule_index=rule_index, context=context)
        progress.stage_progress = 100

        # ── Calculo de Scores (Fase 6) ──
        from .risk_score import (
            calculate_coverage_score,
            calculate_risk_score,
            persist_scores,
        )
        risk_score = calculate_risk_score(db, file_id)
        coverage_score = calculate_coverage_score(db, file_id, context.run_id)
        persist_scores(db, file_id, context.run_id, risk_score, coverage_score)
        progress.risk_score = risk_score
        progress.coverage_score = coverage_score

        # BUG-006 fix: Troca atomica — deletar erros antigos e atualizar status
        # numa unica transacao. Erros antigos ficam visiveis ate este ponto.
        try:
            db.execute("DELETE FROM corrections WHERE file_id = ?", (file_id,))
            # Nota: erros novos ja foram inseridos por _persist_stage_errors durante o pipeline.
            # Erros de cruzamento XML sao preservados pelo filtro de categoria.
            db.execute(
                """UPDATE sped_files
                   SET status = 'validated',
                       total_errors = ?,
                       validation_stage = 'concluido'
                   WHERE id = ?""",
                (progress.total_errors, file_id),
            )
            db.execute(
                "INSERT INTO audit_log (file_id, action, details) VALUES (?, ?, ?)",
                (
                    file_id,
                    "validate",
                    f"Pipeline completo: {progress.total_errors} erros encontrados.",
                ),
            )
            db.commit()
        except Exception:
            db.rollback()
            raise

        progress.stage = "concluido"
        progress.done = True

    except Exception:
        progress.done = True
        progress.stage = "erro"
        try:
            db.rollback()
            db.execute(
                "UPDATE sped_files SET status = 'error' WHERE id = ?",
                (file_id,),
            )
            db.commit()
        except Exception:
            pass
        raise
    finally:
        # Limpar após conclusão (com delay para SSE ler o estado final)
        pass

    return progress


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _filter_by_vigencia(
    errors: list[ValidationError],
    active_error_types: set[str] | None,
) -> list[ValidationError]:
    """Remove erros de regras fora da vigencia do periodo do arquivo."""
    if active_error_types is None:
        return errors
    _keep = frozenset({"field_map_xml"})
    return [
        e
        for e in errors
        if e.error_type in active_error_types or e.categoria in _keep
    ]


def _deduplicate_errors(errors: list[ValidationError]) -> list[ValidationError]:
    """Remove erros duplicados e genericos quando outro erro ja cobre o mesmo item.

    Tres estrategias:
    1. Hipoteses inteligentes supersede erros genericos (mesma linha)
    2. Erros de mesma causa raiz: manter o mais especifico (mesma linha)
    3. Mesma linha + mesmo campo: manter apenas o mais acionavel
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

    # ── Estrategia 2: mesma causa raiz na mesma linha ──
    # CST_ALIQ_ZERO_MODERADO ja diz "CST errado" — BENEFICIO_NAO_VINCULADO
    # e CST_CFOP_INCOMPATIVEL sao sintomas da mesma causa
    lines_cst_zero: set[int] = set()
    for err in errors:
        if err.error_type == "CST_ALIQ_ZERO_MODERADO":
            lines_cst_zero.add(err.line_number)

    _SUPRIMIDOS_POR_CST_ZERO = {"BENEFICIO_NAO_VINCULADO", "CST_CFOP_INCOMPATIVEL"}

    after_hyp = []
    for err in errors:
        ln = err.line_number
        et = err.error_type

        if ln in lines_aliq_hyp and et in _SUPRIMIDOS_POR_ALIQ:
            continue
        if ln in lines_cst_hyp and et in _SUPRIMIDOS_POR_CST:
            continue
        if ln in lines_cst_zero and et in _SUPRIMIDOS_POR_CST_ZERO:
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
    db: AuditConnection,
    file_id: int,
    errors: list[ValidationError],
    rule_index=None,
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
        # Filtrar por vigência: error_type no YAML mas fora da vigência → descartar
        if rule_index and not rule_index.is_error_type_active(err.error_type):
            if rule_index.error_type_exists_in_yaml(err.error_type):
                continue

        record_id = line_to_record.get(err.line_number) if err.line_number > 0 else None

        # Certeza/impacto: YAML é fonte primária
        certeza = err.certeza
        impacto = err.impacto
        if rule_index:
            ci = rule_index.get_certeza_impacto(err.error_type)
            if ci:
                certeza, impacto = ci
        if err.certeza != "objetivo":
            certeza = err.certeza
        if err.impacto != "relevante":
            impacto = err.impacto

        try:
            db.execute(
                """INSERT INTO validation_errors
                   (file_id, record_id, line_number, register, field_no, field_name, value,
                    error_type, severity, message, expected_value, categoria, certeza, impacto,
                    error_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    file_id, record_id, err.line_number, err.register, err.field_no,
                    err.field_name, err.value, err.error_type,
                    _severity_for(err.error_type, rule_index), err.message,
                    err.expected_value, err.categoria, certeza, impacto,
                    err.error_hash,
                ),
            )
        except Exception:
            pass  # Duplicata por hash — ignorar silenciosamente
    db.commit()


def _enrich_errors(
    db: AuditConnection,
    file_id: int,
    doc_db_path: str | None,
    progress: PipelineProgress,
    rule_index=None,
    context=None,
) -> None:
    """Enriquece erros com mensagens amigáveis, base legal e explicacao IA.

    Agrupa erros por (error_type, register, field_name) para evitar buscas
    redundantes — ex: 500 erros iguais fazem apenas 1 busca.

    Se OPENAI_API_KEY configurada, gera doc_suggestion via IA com contexto
    fiscal (regime, UF, beneficio). Resultado cacheado em ai_error_cache.
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

    for processed, ((error_type, register, field_name), entries) in enumerate(groups.items(), 1):
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

        # Determinar se auto-corrigível
        # Fonte primária: campo 'corrigivel' do rules.yaml
        # Fallback: lógica hardcoded para error_types sem entrada no YAML
        auto_correctable = 0
        if rule_index:
            corrigivel = rule_index.get_corrigivel(error_type)
            if corrigivel == "automatico" and sample.get("expected_value"):
                auto_correctable = 1
            elif corrigivel == "proposta" and sample.get("expected_value"):
                auto_correctable = 1  # proposta: mostra botao, usuario confirma
        if not auto_correctable:
            # Fallback hardcoded (error_types sem entrada no YAML)
            if (
                error_type in ("CALCULO_DIVERGENTE", "SOMA_DIVERGENTE", "CRUZAMENTO_DIVERGENTE",
                               "C190_DIVERGE_C170") and sample["expected_value"]
                or error_type == "CONTAGEM_DIVERGENTE" and sample["expected_value"]
            ):
                auto_correctable = 1
            elif error_type == "ALIQ_ICMS_AUSENTE" and sample["expected_value"]:
                auto_correctable = 1
            elif error_type == "CST_HIPOTESE" and sample["expected_value"]:
                auto_correctable = 1
            elif error_type == "CALCULO_ARREDONDAMENTO" and sample["expected_value"]:
                auto_correctable = 1
            elif error_type.startswith("FM_") and sample.get("expected_value"):
                auto_correctable = 1

        # Gerar doc_suggestion via IA (1 por grupo, cacheado)
        ai_doc_suggestion = None
        if _has_openai_key():
            regime_str = ""
            uf_str = ""
            beneficio_str = ""
            if context:
                regime_str = context.regime.value if hasattr(context.regime, 'value') else str(context.regime or "")
                uf_str = context.uf_contribuinte or ""
                beneficio_str = ", ".join(b.codigo if hasattr(b, 'codigo') else str(b) for b in context.beneficios_ativos) if context.beneficios_ativos else ""

            ai_doc_suggestion = _generate_ai_doc_suggestion(
                db, error_type, sample["message"], register, field_name,
                sample["value"], sample["expected_value"],
                regime_str, uf_str, beneficio_str,
                guidance,
            )

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

            # doc_suggestion: IA quando disponivel, senao fallback
            if ai_doc_suggestion:
                # Personalizar com valores especificos deste erro
                doc_suggestion = ai_doc_suggestion
                if entry["value"] and entry["value"] != sample["value"]:
                    doc_suggestion = doc_suggestion.replace(
                        sample["value"], entry["value"]
                    )
                if entry["expected_value"] and entry["expected_value"] != sample["expected_value"]:
                    doc_suggestion = doc_suggestion.replace(
                        sample["expected_value"], entry["expected_value"]
                    )
            else:
                doc_suggestion = f"{entry_friendly}\n\n**Como corrigir:** {entry['message']}"

            db.execute(
                """UPDATE validation_errors
                   SET friendly_message = ?,
                       legal_basis = ?,
                       doc_suggestion = ?,
                       auto_correctable = ?
                   WHERE id = ?""",
                (entry_friendly, legal_basis_json, doc_suggestion, entry_auto, entry["id"]),
            )

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


_ai_key_checked = False
_ai_key_available = False


def _has_openai_key() -> bool:
    """Verifica se alguma chave de IA esta configurada (Claude ou OpenAI)."""
    global _ai_key_checked, _ai_key_available
    if not _ai_key_checked:
        import os
        _ai_key_available = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY"))
        _ai_key_checked = True
    return _ai_key_available


_AI_SYSTEM_PROMPT = """Voce e um auditor fiscal especializado em SPED EFD ICMS/IPI.
Gere uma explicacao estruturada para um erro de validacao.

FORMATO OBRIGATORIO (use exatamente esses marcadores):

**O que foi encontrado:**
[Descreva o erro em 1-2 frases claras, citando valores e campos]

**Por que isso importa:**
[Explique o impacto fiscal em 1-2 frases — credito indevido, omissao, risco de autuacao]

**Como corrigir:**
[Instrucoes objetivas de correcao, citando campos e registros especificos]

**Base legal:**
[Cite a legislacao aplicavel — LC 87/96, Guia Pratico EFD, RICMS, etc.]

REGRAS:
- Portugues brasileiro, linguagem acessivel ao contador
- Seja direto e especifico — cite campos, valores e registros
- Use **negrito** para destacar campos, valores e termos importantes
- Nunca afirme categoricamente — use "possivelmente", "verificar se"
- Maximo 200 palavras total"""


def _generate_ai_doc_suggestion(
    db: AuditConnection,
    error_type: str,
    message: str,
    register: str,
    field_name: str,
    value: str,
    expected_value: str,
    regime: str,
    uf: str,
    beneficio: str,
    guidance: str,
) -> str | None:
    """Gera doc_suggestion via IA (Claude prioritario, OpenAI fallback) com cache."""
    import os

    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    if not anthropic_key and not openai_key:
        return None

    # Tentar cache primeiro
    from .ai_service import get_cached_explanation, PROMPT_VERSION
    cached = get_cached_explanation(
        db, error_type, regime, uf,
        campo_principal=field_name,
        rule_id=error_type,
        value=value,
        expected_value=expected_value,
    )
    if cached and cached.get("explicacao"):
        return cached["explicacao"]

    # Montar prompt com contexto rico
    parts = [
        f"Tipo de erro: {error_type}",
        f"Registro SPED: {register}",
        f"Campo: {field_name}" if field_name else "",
        f"Mensagem tecnica: {message}",
        f"Valor no SPED: {value}" if value else "",
        f"Valor esperado/XML: {expected_value}" if expected_value else "",
        f"Regime tributario: {regime}" if regime else "",
        f"UF do contribuinte: {uf}" if uf else "",
        f"Beneficio fiscal: {beneficio}" if beneficio else "",
        f"Orientacao base: {guidance}" if guidance else "",
    ]
    user_prompt = "\n".join(p for p in parts if p)

    content = ""
    model_used = ""

    # Tentar Claude primeiro
    if anthropic_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=anthropic_key)
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=600,
                system=_AI_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            content = response.content[0].text if response.content else ""
            model_used = "claude-sonnet-4"
        except Exception as e:
            logger.warning("Falha Claude doc_suggestion, tentando OpenAI: %s", e)

    # Fallback OpenAI
    if not content and openai_key:
        try:
            import openai
            client = openai.OpenAI(api_key=openai_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": _AI_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=600,
            )
            content = response.choices[0].message.content or ""
            model_used = "gpt-4o-mini"
        except Exception as e:
            logger.warning("Falha OpenAI doc_suggestion: %s", e)
            return None

    if not content.strip():
        return None

    # Salvar no cache
    from .ai_service import _build_cache_key
    from datetime import datetime
    chave_hash = _build_cache_key(
        error_type, error_type, regime, uf,
        campo_principal=field_name,
        valor_encontrado=value,
        valor_esperado=expected_value,
    )
    try:
        db.execute(
            """INSERT INTO ai_error_cache
               (chave_hash, rule_id, error_type, regime, uf, beneficio_codigo,
                ind_oper, campo_principal, explicacao_texto, sugestao_texto,
                modelo_usado, prompt_version, rule_version, gerado_em, hits)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
               ON CONFLICT (chave_hash) DO UPDATE SET
                explicacao_texto = EXCLUDED.explicacao_texto,
                modelo_usado = EXCLUDED.modelo_usado,
                gerado_em = EXCLUDED.gerado_em,
                hits = 0""",
            (
                chave_hash, error_type, error_type, regime, uf, beneficio,
                "", field_name, content, "",
                "gpt-4o-mini", PROMPT_VERSION, 1, datetime.now().isoformat(),
            ),
        )
        db.commit()
    except Exception:
        logger.warning("Falha ao salvar cache IA", exc_info=True)

    return content


def cleanup_pipeline(file_id: int) -> None:
    """Remove pipeline do rastreamento após SSE encerrar."""
    _active_pipelines.pop(file_id, None)
