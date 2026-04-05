"""Loader e validador do arquivo rules.yaml.

Uso:
    python -m src.rules              # Resumo das regras
    python -m src.rules --check      # Verifica implementacao vs definicao
    python -m src.rules --pending    # Lista apenas regras pendentes
    python -m src.rules --block SEU_BLOCO  # Filtra por bloco
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

RULES_PATH = Path(__file__).parent.parent / "rules.yaml"

# Mapeia module → error_types implementados (extraidos do codigo)
_KNOWN_ERROR_TYPES: set[str] = {
    # format_validator.py
    "FORMATO_INVALIDO", "INVALID_DATE", "DATE_OUT_OF_PERIOD",
    # validator.py
    "MISSING_REQUIRED", "WRONG_TYPE", "WRONG_SIZE", "INVALID_VALUE",
    # intra_register_validator.py
    "MISSING_CONDITIONAL", "INCONSISTENCY", "DATE_ORDER",
    "CFOP_MISMATCH", "SOMA_DIVERGENTE", "CALCULO_DIVERGENTE",
    # cross_block_validator.py
    "REF_INEXISTENTE", "CRUZAMENTO_DIVERGENTE", "CONTAGEM_DIVERGENTE",
    # cst_validator.py
    "CST_INVALIDO", "ISENCAO_INCONSISTENTE", "TRIBUTACAO_INCONSISTENTE",
    "VALOR_NEGATIVO",
    # fiscal_semantics.py
    "CST_ALIQ_ZERO_FORTE", "CST_ALIQ_ZERO_MODERADO", "CST_ALIQ_ZERO_INFO",
    "IPI_CST_ALIQ_ZERO", "PIS_CST_ALIQ_ZERO", "COFINS_CST_ALIQ_ZERO",
    "CST_CFOP_INCOMPATIVEL",
    "MONOFASICO_ALIQ_INVALIDA", "MONOFASICO_VALOR_INDEVIDO",
    "MONOFASICO_NCM_INCOMPATIVEL", "MONOFASICO_CST_INCORRETO",
    "MONOFASICO_ENTRADA_CST04",
    # audit_rules.py
    "CFOP_INTERESTADUAL_DESTINO_INTERNO", "DIFERIMENTO_COM_DEBITO",
    "IPI_REFLEXO_INCORRETO", "BENEFICIO_CARGA_REDUZIDA_DOCUMENTO",
    "VOLUME_ISENTO_ATIPICO", "REMESSA_SEM_RETORNO",
    "INVENTARIO_ITEM_PARADO", "PARAMETRIZACAO_SISTEMICA_INCORRETA",
    "CREDITO_USO_CONSUMO_INDEVIDO", "CREDITO_FORMA_SEM_SUBSTANCIA",
    "OPERACAO_ESPECIAL_CONTAMINANDO", "REGISTROS_ESSENCIAIS_AUSENTES",
    "CHECKLIST_AUDITORIA_INCOMPLETO", "CFOP_CORRETO_CST_INCORRETO",
    # Fase 1 — aliquota_validator.py
    "ALIQ_INTERESTADUAL_INVALIDA", "ALIQ_INTERNA_EM_INTERESTADUAL",
    "ALIQ_INTERESTADUAL_EM_INTERNA", "ALIQ_MEDIA_INDEVIDA",
    # Fase 1 — c190_validator.py
    "C190_DIVERGE_C170", "C190_COMBINACAO_INCOMPATIVEL",
    # Fase 1 — cst_validator.py (expandido)
    "CST_020_SEM_REDUCAO", "IPI_CST_INCOMPATIVEL",
    # beneficio_audit_validator.py
    "BENEFICIO_DEBITO_NAO_INTEGRAL", "AJUSTE_SEM_LASTRO_DOCUMENTAL",
    "AJUSTE_SOMA_DIVERGENTE", "DEVOLUCAO_BENEFICIO_NAO_REVERTIDO",
    "SALDO_CREDOR_RECORRENTE", "SOBREPOSICAO_BENEFICIOS",
    "BENEFICIO_VALOR_DESPROPORCIONAL", "ST_APURACAO_INCONSISTENTE",
    "AJUSTE_CODIGO_GENERICO", "ESCRITURACAO_DIVERGE_DOCUMENTO",
    "CHECKLIST_INCOMPLETO", "TRILHA_BENEFICIO_INCOMPLETA",
    "ICMS_EFETIVO_SEM_TRILHA", "BENEFICIO_FORA_ESCOPO",
    "DIVERGENCIA_DOCUMENTO_ESCRITURACAO",
    "C190_CONSOLIDACAO_INDEVIDA", "CREDITO_ENTRADA_SEM_SAIDA",
    "INVENTARIO_INCONSISTENTE_TRIBUTARIO", "BENEFICIO_SEM_GOVERNANCA",
    "TOTALIZACAO_BENEFICIO_DIVERGENTE", "MISTURA_INSTITUTOS_TRIBUTARIOS",
    "BENEFICIO_PERFIL_INCOMPATIVEL", "BENEFICIO_EXECUCAO_INCORRETA",
    "BENEFICIO_SEM_SEGREGACAO_DESTINATARIO", "BASE_BENEFICIO_INFLADA",
    "SPED_CONTRIBUICOES_DIVERGENTE", "AJUSTE_NUMERICO_SEM_VALIDADE_JURIDICA",
    "CODIGO_AJUSTE_INCOMPATIVEL", "TRILHA_BENEFICIO_AUSENTE",
    "CLASSIFICACAO_TIPO_ERRO", "ACHADO_LIMITADO_AO_SPED",
    # pendentes_validator.py
    "BENEFICIO_NAO_VINCULADO", "DESONERACAO_SEM_MOTIVO",
    "DEVOLUCAO_INCONSISTENTE", "ANOMALIA_HISTORICA",
    "IPI_ALIQ_NCM_DIVERGENTE",
    # correction_hypothesis.py
    "ALIQ_ICMS_AUSENTE",
}


@dataclass
class Rule:
    """Uma regra de validacao carregada do YAML."""
    id: str
    block: str
    register: str
    fields: list[str]
    error_type: str
    severity: str
    description: str
    condition: str
    implemented: bool
    module: str
    legislation: str | None = None


def load_rules(path: Path | None = None) -> list[Rule]:
    """Carrega todas as regras do arquivo YAML."""
    path = path or RULES_PATH
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    rules: list[Rule] = []
    skip_keys = {"version", "tolerance"}

    for block_name, block_rules in data.items():
        if block_name in skip_keys:
            continue
        if not isinstance(block_rules, list):
            continue
        for entry in block_rules:
            rules.append(Rule(
                id=entry["id"],
                block=block_name,
                register=entry.get("register", "*"),
                fields=entry.get("fields", []),
                error_type=entry.get("error_type", ""),
                severity=entry.get("severity", "error"),
                description=entry.get("description", ""),
                condition=entry.get("condition", ""),
                implemented=entry.get("implemented", False),
                module=entry.get("module", ""),
                legislation=entry.get("legislation"),
            ))

    return rules


def check_rules(rules: list[Rule]) -> dict:
    """Verifica regras implementadas vs pendentes e error_types conhecidos."""
    implemented = [r for r in rules if r.implemented]
    pending = [r for r in rules if not r.implemented]

    # Verificar se error_types das regras implementadas existem no codigo
    missing_types: list[Rule] = []
    for r in implemented:
        if r.error_type and r.error_type not in _KNOWN_ERROR_TYPES:
            missing_types.append(r)

    return {
        "total": len(rules),
        "implemented": len(implemented),
        "pending": len(pending),
        "missing_error_types": missing_types,
        "pending_rules": pending,
        "by_block": _count_by_block(rules),
        "by_severity": _count_by_severity(rules),
    }


def _count_by_block(rules: list[Rule]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for r in rules:
        if r.block not in result:
            result[r.block] = {"total": 0, "implemented": 0, "pending": 0}
        result[r.block]["total"] += 1
        if r.implemented:
            result[r.block]["implemented"] += 1
        else:
            result[r.block]["pending"] += 1
    return result


def _count_by_severity(rules: list[Rule]) -> dict[str, int]:
    result: dict[str, int] = {}
    for r in rules:
        result[r.severity] = result.get(r.severity, 0) + 1
    return result


def print_summary(rules: list[Rule]) -> None:
    """Imprime resumo das regras."""
    report = check_rules(rules)
    print(f"\n{'='*70}")
    print("  SPED EFD - Regras de Validacao")
    print(f"{'='*70}")
    print(f"  Total: {report['total']} regras")
    print(f"  Implementadas: {report['implemented']}")
    print(f"  Pendentes: {report['pending']}")
    print()

    print("  Por bloco:")
    for block, counts in report["by_block"].items():
        status = "OK" if counts["pending"] == 0 else f"{counts['pending']} pendente(s)"
        print(f"    {block:<30s} {counts['implemented']:>3}/{counts['total']:<3} [{status}]")

    print()
    print("  Por severidade:")
    for sev, count in sorted(report["by_severity"].items()):
        print(f"    {sev:<12s} {count:>3}")

    if report["missing_error_types"]:
        print(f"\n  ATENCAO: {len(report['missing_error_types'])} regra(s) com error_type nao encontrado no codigo:")
        for r in report["missing_error_types"]:
            print(f"    - {r.id}: {r.error_type}")

    print(f"{'='*70}\n")


def print_pending(rules: list[Rule]) -> None:
    """Imprime regras pendentes de implementacao."""
    pending = [r for r in rules if not r.implemented]
    if not pending:
        print("\nNenhuma regra pendente. Todas implementadas!")
        return

    print(f"\n{'='*70}")
    print(f"  REGRAS PENDENTES DE IMPLEMENTACAO ({len(pending)})")
    print(f"{'='*70}")
    for r in pending:
        print(f"\n  [{r.id}] {r.description}")
        print(f"    Bloco:     {r.block}")
        print(f"    Registro:  {r.register}")
        print(f"    Campos:    {', '.join(r.fields)}")
        print(f"    Tipo erro: {r.error_type}")
        print(f"    Severidade: {r.severity}")
        print(f"    Condicao:  {r.condition}")
        print(f"    Modulo:    {r.module}")
        if r.legislation:
            print(f"    Legislacao: {r.legislation}")
    print(f"\n{'='*70}\n")


def print_block(rules: list[Rule], block: str) -> None:
    """Imprime regras de um bloco especifico."""
    filtered = [r for r in rules if r.block == block]
    if not filtered:
        blocks = sorted({r.block for r in rules})
        print(f"\nBloco '{block}' nao encontrado. Blocos disponiveis:")
        for b in blocks:
            print(f"  - {b}")
        return

    print(f"\n{'='*70}")
    print(f"  BLOCO: {block} ({len(filtered)} regras)")
    print(f"{'='*70}")
    for r in filtered:
        status = "OK" if r.implemented else "PENDENTE"
        print(f"\n  [{r.id}] [{status}] {r.description}")
        print(f"    Registro: {r.register} | Campos: {', '.join(r.fields)}")
        print(f"    Tipo: {r.error_type} | Severidade: {r.severity}")
        print(f"    Condicao: {r.condition}")
        if r.legislation:
            print(f"    Legislacao: {r.legislation}")
    print(f"\n{'='*70}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerenciador de regras SPED")
    parser.add_argument("--check", action="store_true", help="Verifica implementacao")
    parser.add_argument("--pending", action="store_true", help="Lista regras pendentes")
    parser.add_argument("--block", type=str, help="Filtra por bloco")
    parser.add_argument("--rules-file", type=str, help="Caminho do rules.yaml")
    args = parser.parse_args()

    path = Path(args.rules_file) if args.rules_file else None
    rules = load_rules(path)

    if args.block:
        print_block(rules, args.block)
    elif args.pending:
        print_pending(rules)
    elif args.check:
        print_summary(rules)
        report = check_rules(rules)
        if report["pending"] > 0:
            print_pending(rules)
        sys.exit(1 if report["missing_error_types"] else 0)
    else:
        print_summary(rules)


if __name__ == "__main__":
    main()
