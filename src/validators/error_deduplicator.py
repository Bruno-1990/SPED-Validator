"""Deduplicação de apontamentos de validação.

Quando múltiplos validadores detectam o mesmo problema na mesma linha/campo,
mantém apenas o de maior severidade e referencia os demais.
"""

from __future__ import annotations

from ..models import ValidationError

# Ordem de severidade para desempate (maior = mais importante)
IMPACTO_ORDER = {
    "critico": 3,
    "relevante": 2,
    "informativo": 1,
}

# Grupos de error_type semanticamente equivalentes
EQUIVALENT_ERROR_GROUPS: list[frozenset[str]] = [
    frozenset({"ISENCAO_INCONSISTENTE", "TRIBUTACAO_INCONSISTENTE", "CST_ALIQ_ZERO_FORTE"}),
    frozenset({"CST_CFOP_INCOMPATIVEL", "CFOP_MISMATCH", "CFOP_INTERESTADUAL_MESMA_UF"}),
    frozenset({"SOMA_DIVERGENTE", "CALCULO_DIVERGENTE", "CRUZAMENTO_DIVERGENTE"}),
    frozenset({"REF_INEXISTENTE", "D_REF_INEXISTENTE"}),
    frozenset({"CONTAGEM_DIVERGENTE"}),
]


def _same_group(error_type_a: str, error_type_b: str) -> bool:
    """Retorna True se os dois error_types pertencem ao mesmo grupo semântico."""
    for group in EQUIVALENT_ERROR_GROUPS:
        if error_type_a in group and error_type_b in group:
            return True
    return False


class ErrorDeduplicator:
    """Deduplica erros de validação mantendo o de maior severidade por linha+campo.

    Preserva referências às detecções duplicadas para rastreabilidade.
    """

    @staticmethod
    def deduplicate(errors: list[ValidationError]) -> list[ValidationError]:
        """Recebe lista de erros (possivelmente com duplicatas) e retorna lista
        deduplicada. Erros são considerados duplicados se:
        1. Mesma line_number
        2. Mesmo field_name (ou ambos vazios)
        3. error_type pertence ao mesmo grupo semântico

        O erro mantido é o de maior impacto (critico > relevante > informativo).
        """
        if not errors:
            return []

        # Agrupa por (line_number, field_name)
        groups: dict[tuple, list[ValidationError]] = {}
        for err in errors:
            key = (err.line_number, err.field_name or "")
            groups.setdefault(key, []).append(err)

        result: list[ValidationError] = []
        for _key, group_errors in groups.items():
            if len(group_errors) == 1:
                result.append(group_errors[0])
                continue

            # Dentro do grupo, identificar clusters de error_types equivalentes
            processed: set[int] = set()
            for i, err_i in enumerate(group_errors):
                if i in processed:
                    continue
                cluster = [err_i]
                for j, err_j in enumerate(group_errors):
                    if j == i or j in processed:
                        continue
                    if _same_group(err_i.error_type, err_j.error_type):
                        cluster.append(err_j)
                        processed.add(j)
                processed.add(i)

                # Mantém o de maior impacto no cluster
                winner = max(
                    cluster,
                    key=lambda e: IMPACTO_ORDER.get(e.impacto, 0),
                )
                # Adiciona referência às duplicatas no message
                duplicates = [e.error_type for e in cluster if e is not winner]
                if duplicates:
                    dup_str = ", ".join(duplicates)
                    winner = ValidationError(
                        line_number=winner.line_number,
                        register=winner.register,
                        field_no=winner.field_no,
                        field_name=winner.field_name,
                        value=winner.value,
                        error_type=winner.error_type,
                        message=winner.message + f" [também detectado como: {dup_str}]",
                        expected_value=winner.expected_value,
                        categoria=winner.categoria,
                        certeza=winner.certeza,
                        impacto=winner.impacto,
                    )
                result.append(winner)

        # Ordena por line_number para output consistente
        result.sort(key=lambda e: (e.line_number or 0, e.field_name or ""))
        return result
