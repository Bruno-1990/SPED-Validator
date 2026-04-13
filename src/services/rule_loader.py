"""MOD-04: Versionamento de Regras por Vigência Fiscal.

Carrega regras do rules.yaml e filtra por período de vigência,
garantindo que apenas regras aplicáveis ao período do arquivo
SPED sejam utilizadas na validação.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

RULES_PATH = Path(__file__).parent.parent.parent / "rules.yaml"


class RuleLoader:
    """Carrega e filtra regras por vigência fiscal."""

    def __init__(self, rules_path: Path | None = None) -> None:
        self._path = rules_path or RULES_PATH
        self._all_rules: list[dict] | None = None

    def _load_all(self) -> list[dict]:
        """Carrega todas as regras do YAML (com cache)."""
        if self._all_rules is not None:
            return self._all_rules

        with open(self._path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        rules: list[dict] = []
        skip_keys = {"version", "tolerance"}

        for block_name, block_rules in data.items():
            if block_name in skip_keys:
                continue
            if not isinstance(block_rules, list):
                continue
            for entry in block_rules:
                entry["_block"] = block_name
                rules.append(entry)

        self._all_rules = rules
        return rules

    def load_rules_for_period(
        self, period_start: date, period_end: date
    ) -> list[dict]:
        """Retorna apenas as regras vigentes para o período do arquivo.

        Uma regra é vigente se:
            rule.vigencia_de <= period_end AND
            (rule.vigencia_ate is None OR rule.vigencia_ate >= period_start)
        """
        all_rules = self._load_all()
        active: list[dict] = []

        for rule in all_rules:
            vigencia_de_str = rule.get("vigencia_de")
            vigencia_ate_str = rule.get("vigencia_ate")

            # Regras sem vigencia_de são tratadas como sempre vigentes
            if not vigencia_de_str:
                active.append(rule)
                continue

            vigencia_de = _parse_date(vigencia_de_str)

            if vigencia_de is not None and vigencia_de > period_end:
                continue

            if vigencia_ate_str is not None:
                vigencia_ate = _parse_date(vigencia_ate_str)
                if vigencia_ate is not None and vigencia_ate < period_start:
                    continue

            active.append(rule)

        return active

    def load_all_rules(self) -> list[dict]:
        """Retorna todas as regras sem filtro de vigência."""
        return list(self._load_all())


class RuleIndex:
    """Indice pre-computado de regras por error_type para enriquecimento rapido.

    Usado na camada de persistencia para aplicar severity, certeza, impacto e
    corrigivel do rules.yaml nos erros gerados pelos validators.
    """

    def __init__(self, active_rules: list[dict], all_rules: list[dict] | None = None) -> None:
        self._by_error_type: dict[str, dict] = {}
        self._active_error_types: set[str] = set()
        self._all_error_types: set[str] = set()

        for r in active_rules:
            et = r.get("error_type", "")
            if et:
                self._active_error_types.add(et)
                if et not in self._by_error_type:
                    self._by_error_type[et] = r

        # Se all_rules fornecido, mapeia todos os error_types conhecidos no YAML
        for r in (all_rules or active_rules):
            et = r.get("error_type", "")
            if et:
                self._all_error_types.add(et)

    def get_severity(self, error_type: str) -> str | None:
        """Retorna severity da regra, ou None se nao encontrada."""
        rule = self._by_error_type.get(error_type)
        if rule:
            return rule.get("severity")
        if error_type.startswith("FM_"):
            return "error"
        return None

    def get_corrigivel(self, error_type: str) -> str | None:
        """Retorna corrigivel (automatico/proposta/investigar/impossivel)."""
        rule = self._by_error_type.get(error_type)
        if rule:
            return rule.get("corrigivel")
        if error_type.startswith("FM_"):
            return "automatico"
        return None

    def get_certeza_impacto(self, error_type: str) -> tuple[str, str] | None:
        """Retorna (certeza, impacto) da regra, ou None."""
        rule = self._by_error_type.get(error_type)
        if rule:
            return (
                rule.get("certeza", "objetivo"),
                rule.get("impacto", "relevante"),
            )
        if error_type.startswith("FM_"):
            return ("objetivo", "relevante")
        return None

    def is_error_type_active(self, error_type: str) -> bool:
        """True se o error_type esta em alguma regra ativa (vigente)."""
        if error_type.startswith("FM_"):
            return True
        return error_type in self._active_error_types

    def error_type_exists_in_yaml(self, error_type: str) -> bool:
        """True se o error_type existe em qualquer regra do YAML (ativa ou nao)."""
        if error_type.startswith("FM_"):
            return True
        return error_type in self._all_error_types


def _parse_date(value: str | date) -> date | None:
    """Converte string YYYY-MM-DD para date."""
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        parts = value.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None
