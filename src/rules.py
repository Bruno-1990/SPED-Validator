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
    # validator.py / intra_register_validator.py
    "FORMATO_INVALIDO", "INVALID_DATE", "DATE_OUT_OF_PERIOD",
    "MISSING_REQUIRED", "MISSING_CONDITIONAL", "INCONSISTENCY",
    "DATE_ORDER", "CFOP_MISMATCH", "SOMA_DIVERGENTE", "CALCULO_DIVERGENTE",
    "CALCULO_ARREDONDAMENTO", "VALOR_NEGATIVO",
    # cross_block_validator.py
    "REF_INEXISTENTE", "CRUZAMENTO_DIVERGENTE", "CONTAGEM_DIVERGENTE",
    # cst_validator.py
    "CST_INVALIDO", "ISENCAO_INCONSISTENTE", "CST_020_SEM_REDUCAO",
    "CST_020_ALIQ_REDUZIDA", "CST_051_DIFERIMENTO_DEBITO",
    "CST_TRIBUTADO_ALIQ_ZERO", "CST_EFEITO_INCONSISTENTE",
    "CST_INCOMPATIVEL_COEXISTENTE", "CST_HIPOTESE",
    # fiscal_semantics.py
    "CST_ALIQ_ZERO_FORTE", "CST_ALIQ_ZERO_MODERADO",
    "IPI_CST_ALIQ_ZERO", "PIS_CST_ALIQ_ZERO", "COFINS_CST_ALIQ_ZERO",
    "CST_CFOP_INCOMPATIVEL", "VENDA_CST_ISENTO", "TRIBUTADO_ICMS_ZERO",
    "TRIBUTADO_SEM_BC",
    "MONOFASICO_ALIQ_INVALIDA", "MONOFASICO_VALOR_INDEVIDO",
    "MONOFASICO_NCM_INCOMPATIVEL", "MONOFASICO_CST_INCORRETO",
    "MONOFASICO_ENTRADA_CST04",
    # cfop_validator.py
    "CFOP_INVALIDO", "CFOP_INTERESTADUAL_MESMA_UF", "CFOP_INTERNO_OUTRA_UF",
    # audit_rules.py
    "CFOP_INTERESTADUAL_DESTINO_INTERNO", "DIFERIMENTO_COM_DEBITO",
    "IPI_REFLEXO_INCORRETO", "VOLUME_ISENTO_ATIPICO",
    "REMESSA_SEM_RETORNO", "INVENTARIO_ITEM_PARADO",
    "PARAMETRIZACAO_SISTEMICA_INCORRETA",
    "CREDITO_USO_CONSUMO_INDEVIDO", "REGISTROS_ESSENCIAIS_AUSENTES",
    "AMOSTRAGEM_MATERIALIDADE", "GRAU_CONFIANCA_ACHADOS",
    "CLASSIFICACAO_TIPO_ERRO", "ACHADO_LIMITADO_AO_SPED",
    # aliquota_validator.py
    "ALIQ_INTERESTADUAL_INVALIDA", "ALIQ_INTERNA_EM_INTERESTADUAL",
    "ALIQ_INTERESTADUAL_EM_INTERNA", "ALIQ_MEDIA_INDEVIDA",
    "ALIQ_4_SEM_IMPORTACAO", "ALIQ_DIVERGENTE_MESMO_ITEM",
    "ALIQ_UF_INCOMPATIVEL",
    # base_calculo_validator.py
    "BASE_MENOR_SEM_JUSTIFICATIVA", "BASE_SUPERIOR_RAZOAVEL",
    "DESPESAS_ACESSORIAS_FORA_BASE", "FRETE_CIF_FORA_BASE", "FRETE_FOB_NA_BASE",
    # c190_validator.py
    "C190_DIVERGE_C170", "C190_COMBINACAO_INCOMPATIVEL",
    "CS_C490_SOMA_DIVERGENTE", "CS_C590_DIVERGE_C510",
    # beneficio_validator.py
    "BENEFICIO_CONTAMINANDO_ALIQUOTA", "BENEFICIO_CONTAMINANDO_DIFAL",
    "BENEFICIO_BASE_NAO_ELEGIVEL",
    # beneficio_audit_validator.py
    "BENEFICIO_DEBITO_NAO_INTEGRAL", "AJUSTE_SOMA_DIVERGENTE",
    "DEVOLUCAO_BENEFICIO_NAO_REVERTIDO", "SALDO_CREDOR_RECORRENTE",
    "SOBREPOSICAO_BENEFICIOS", "BENEFICIO_VALOR_DESPROPORCIONAL",
    "ST_APURACAO_INCONSISTENTE", "CHECKLIST_INCOMPLETO",
    "ICMS_EFETIVO_SEM_TRILHA", "BENEFICIO_FORA_ESCOPO",
    "DIVERGENCIA_DOCUMENTO_ESCRITURACAO", "C190_CONSOLIDACAO_INDEVIDA",
    "INVENTARIO_INCONSISTENTE_TRIBUTARIO",
    "TOTALIZACAO_BENEFICIO_DIVERGENTE", "MISTURA_INSTITUTOS_TRIBUTARIOS",
    "BENEFICIO_PERFIL_INCOMPATIVEL", "BENEFICIO_EXECUCAO_INCORRETA",
    "BENEFICIO_SEM_SEGREGACAO_DESTINATARIO", "BASE_BENEFICIO_INFLADA",
    "SPED_CONTRIBUICOES_DIVERGENTE",
    # beneficio_cross_validator.py
    "BENE_CROSS_APURACAO_NAO_SEGREGADA", "BENE_CROSS_CODIGO_RECEITA_INCORRETO",
    "BENE_CROSS_ESTORNO_AUSENTE", "BENE_CROSS_CUMULACAO_VEDADA_DOCUMENTO",
    "BENE_CROSS_CUMULACAO_VEDADA_PERIODO", "BENE_CROSS_CREDITO_ENTRADA_ALERTA",
    "BENE_CROSS_CREDITO_PRESUMIDO_BASE_INCORRETA",
    "BENE_CROSS_DIFERIMENTO_CREDITADO", "BENE_CROSS_NCM_NAO_AUTORIZADA_DIFERIMENTO",
    # pendentes_validator.py
    "BENEFICIO_NAO_VINCULADO", "DESONERACAO_SEM_MOTIVO",
    "DEVOLUCAO_INCONSISTENTE", "ANOMALIA_HISTORICA", "IPI_ALIQ_NCM_DIVERGENTE",
    # correction_hypothesis.py
    "ALIQ_ICMS_AUSENTE",
    # difal_validator.py
    "DIFAL_FALTANTE_CONSUMO_FINAL", "DIFAL_INDEVIDO_REVENDA",
    "DIFAL_UF_DESTINO_INCONSISTENTE", "DIFAL_ALIQ_INTERNA_INCORRETA",
    "DIFAL_BASE_INCONSISTENTE", "DIFAL_FCP_AUSENTE",
    "DIFAL_PERFIL_INCOMPATIVEL", "DIFAL_CONSUMO_FINAL_SEM_MARCADOR",
    "DIFAL_ALIQ_ORIGEM_INCOMPATIVEL", "DIFAL_PARTILHA_PERIODO_TRANSICAO",
    "DIFAL_VERIFICACAO_INCOMPLETA", "CFOP_DIFAL_INCOMPATIVEL",
    # devolucao_validator.py
    "DEVOLUCAO_SEM_ESPELHAMENTO", "DEVOLUCAO_ALIQ_DIVERGENTE", "DEVOLUCAO_SEM_DIFAL",
    # destinatario_validator.py
    "DEST_UF_IE_INCOMPATIVEL", "DEST_UF_CEP_INCOMPATIVEL", "DEST_IE_INCONSISTENTE",
    # parametrizacao_validator.py
    "PARAM_ERRO_SISTEMATICO_ITEM", "PARAM_ERRO_SISTEMATICO_UF",
    "PARAM_ERRO_INICIADO_EM_DATA",
    # ncm_validator.py
    "NCM_INEXISTENTE", "NCM_FORA_VIGENCIA", "NCM_GENERICO_RELEVANTE",
    "NCM_TRIBUTACAO_INCOMPATIVEL", "NCM_MONOFASICO_CST_ICMS",
    "NCM_REFERENCIA_INDISPONIVEL",
    # ipi_validator.py
    "IPI_CST_INCOMPATIVEL", "IPI_REFLEXO_BC_ICMS", "IPI_CST_MONETARIO_INCOMPATIVEL",
    # st_validator.py
    "ST_MVA_BC_DIVERGENTE", "ST_MVA_ICMS_DIVERGENTE", "ST_MVA_NCM_SEM_ST",
    "ST_BC_MENOR_QUE_ITEM", "ST_CST60_DEBITO_INDEVIDO", "ST_MISTURA_DIFAL",
    # bloco_d_validator.py
    "D190_DIVERGE_D100", "D_CST_REGIME_INCOMPATIVEL", "D_CFOP_DIRECAO_INCOMPATIVEL",
    "D_CHAVE_CTE_INVALIDA", "D_REF_INEXISTENTE", "D_DEBITOS_EXCEDE_E110",
    # bloco_k_validator.py
    "K_QTD_NEGATIVA", "K_REF_ITEM_INEXISTENTE",
    "K_ORDEM_SEM_COMPONENTES", "K_BLOCO_SEM_MOVIMENTO_COM_REGISTROS",
    # simples_validator.py
    "SN_CST_TABELA_A", "SN_CSOSN_INVALIDO", "SN_CREDITO_ZERADO_OU_FORA_RANGE",
    "SN_ST_NAO_PREENCHIDA", "SN_500_SEM_BC_ST", "SN_PERFIL_INVALIDO",
    "SN_PIS_CST_INCOMPATIVEL", "SN_PIS_CST_PROIBIDO",
    "SN_CST_MONOFASICO_NCM_INVALIDO", "SN_CREDITO_INCONSISTENTE",
    # retificador
    "RET_001", "RET_002",
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
    vigencia_de: str | None = None
    vigencia_ate: str | None = None
    version: str | None = None
    last_updated: str | None = None
    corrigivel: str | None = None


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
                vigencia_de=entry.get("vigencia_de"),
                vigencia_ate=entry.get("vigencia_ate"),
                version=entry.get("version"),
                last_updated=entry.get("last_updated"),
                corrigivel=entry.get("corrigivel"),
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

    # Verificar campo corrigivel obrigatorio
    valid_corrigivel = {"automatico", "proposta", "investigar", "impossivel"}
    missing_corrigivel: list[Rule] = []
    invalid_corrigivel: list[Rule] = []
    for r in rules:
        if not r.corrigivel:
            missing_corrigivel.append(r)
        elif r.corrigivel not in valid_corrigivel:
            invalid_corrigivel.append(r)

    return {
        "total": len(rules),
        "implemented": len(implemented),
        "pending": len(pending),
        "missing_error_types": missing_types,
        "pending_rules": pending,
        "by_block": _count_by_block(rules),
        "by_severity": _count_by_severity(rules),
        "missing_corrigivel": missing_corrigivel,
        "invalid_corrigivel": invalid_corrigivel,
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

    # Governanca: corrigivel
    missing_c = report.get("missing_corrigivel", [])
    invalid_c = report.get("invalid_corrigivel", [])
    has_corrigivel = report["total"] - len(missing_c)
    print(f"\n  Governanca (corrigivel): {has_corrigivel}/{report['total']} regras com campo declarado")
    if missing_c:
        print(f"  ATENCAO: {len(missing_c)} regra(s) sem campo 'corrigivel':")
        for r in missing_c[:10]:
            print(f"    - {r.id}")
        if len(missing_c) > 10:
            print(f"    ... e mais {len(missing_c) - 10}")
    if invalid_c:
        print(f"  ERRO: {len(invalid_c)} regra(s) com valor invalido de 'corrigivel':")
        for r in invalid_c:
            print(f"    - {r.id}: '{r.corrigivel}'")

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


def print_vigentes(rules: list[Rule], periodo: str) -> None:
    """Imprime regras vigentes para um período YYYY-MM."""
    from datetime import date as _date

    from .services.rule_loader import RuleLoader

    parts = periodo.split("-")
    year, month = int(parts[0]), int(parts[1])
    period_start = _date(year, month, 1)
    # Último dia do mês
    if month == 12:
        period_end = _date(year, 12, 31)
    else:
        period_end = _date(year, month + 1, 1).replace(day=1)
        from datetime import timedelta
        period_end = period_end - timedelta(days=1)

    loader = RuleLoader()
    active_raw = loader.load_rules_for_period(period_start, period_end)
    active_ids = {r["id"] for r in active_raw}

    vigentes = [r for r in rules if r.id in active_ids]
    excluidas = [r for r in rules if r.id not in active_ids]

    print(f"\n{'='*70}")
    print(f"  REGRAS VIGENTES PARA {periodo}")
    print(f"{'='*70}")
    print(f"  Vigentes: {len(vigentes)} / {len(rules)}")
    print(f"  Excluidas por vigencia: {len(excluidas)}")

    if excluidas:
        print(f"\n  Regras NAO vigentes para {periodo}:")
        for r in excluidas:
            print(f"    - {r.id}: vigencia_de={r.vigencia_de} vigencia_ate={r.vigencia_ate}")

    print("\n  Regras vigentes:")
    for r in vigentes:
        print(f"    [{r.id}] {r.description[:60]}  (desde {r.vigencia_de})")
    print(f"{'='*70}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerenciador de regras SPED")
    parser.add_argument("--check", action="store_true", help="Verifica implementacao")
    parser.add_argument("--pending", action="store_true", help="Lista regras pendentes")
    parser.add_argument("--block", type=str, help="Filtra por bloco")
    parser.add_argument("--rules-file", type=str, help="Caminho do rules.yaml")
    parser.add_argument("--vigentes-para", type=str, help="Mostra regras vigentes para YYYY-MM")
    args = parser.parse_args()

    path = Path(args.rules_file) if args.rules_file else None
    rules = load_rules(path)

    if args.vigentes_para:
        print_vigentes(rules, args.vigentes_para)
    elif args.block:
        print_block(rules, args.block)
    elif args.pending:
        print_pending(rules)
    elif args.check:
        print_summary(rules)
        report = check_rules(rules)
        if report["pending"] > 0:
            print_pending(rules)
        has_errors = bool(
            report["missing_error_types"]
            or report.get("missing_corrigivel")
            or report.get("invalid_corrigivel")
        )
        sys.exit(1 if has_errors else 0)
    else:
        print_summary(rules)


if __name__ == "__main__":
    main()
