"""Motor de hipotese de correcao: sugestao inteligente baseada em evidencias.

Camada 2 do motor de validacao — apos detectar o erro, tenta responder:
"qual e a correcao mais provavel?"

Classificacao de confianca:
- >= 80: sugestao forte (auto-correcao segura)
- 60-79: sugestao provavel (auto-correcao com revisao)
- 40-59: indicio (apenas informativo)
- < 40: sem sugestao automatica

Regras implementadas:
- Aliquota implicita (VL_ICMS / VL_BC_ICMS)
- Plausibilidade (comparacao com aliquotas conhecidas)
- Padrao do documento (itens irmaos no mesmo C100)
- Totalizacao (cruzamento com C190)
- Classificacao do tipo de erro (aliquota, valor, base, enquadramento)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from .helpers import (
    CST_TRIBUTADO,
    F_C170_ALIQ_ICMS,
    F_C170_CFOP,
    F_C170_CST_ICMS,
    F_C170_VL_BC_ICMS,
    F_C170_VL_ICMS,
    F_C190_ALIQ,
    F_C190_CFOP,
    F_C190_CST,
    F_C190_VL_ICMS,
    TOLERANCE,
    get_field,
    make_error,
    to_float,
    trib,
)

# ──────────────────────────────────────────────
# Aliquotas plausíveis (nacional + interestaduais)
# ──────────────────────────────────────────────

_ALIQ_PLAUSIVEIS = {
    0.0, 4.0, 7.0, 12.0, 17.0, 17.5, 18.0, 19.0, 19.5,
    20.0, 20.5, 21.0, 25.0, 27.0, 29.0, 30.0, 33.0, 35.0, 37.0,
}

_ALIQ_TOLERANCIA = 0.05  # pontos percentuais


# ──────────────────────────────────────────────
# Estrutura de hipotese
# ──────────────────────────────────────────────

@dataclass
class CorrectionHypothesis:
    """Hipotese de correcao com score de confianca."""
    field_name: str
    current_value: str
    suggested_value: str
    score: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> str:
        if self.score >= 80:
            return "alta"
        if self.score >= 60:
            return "provavel"
        if self.score >= 40:
            return "indicio"
        return "baixa"

    @property
    def auto_correctable(self) -> bool:
        return self.score >= 60


# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def validate_with_hypotheses(records: list[SpedRecord]) -> list[ValidationError]:
    """Executa validacao com hipoteses de correcao inteligentes.

    Foco em casos onde ALIQ_ICMS=0 mas VL_ICMS>0 (aliquota faltante).
    """
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    # Construir mapa C170 -> C100 pai
    all_recs = []
    for reg_type in ("C100", "C170", "C190"):
        for r in groups.get(reg_type, []):
            all_recs.append(r)
    all_recs.sort(key=lambda r: r.line_number)

    current_c100: SpedRecord | None = None
    doc_c170: dict[int, list[SpedRecord]] = defaultdict(list)
    doc_c190: dict[int, list[SpedRecord]] = defaultdict(list)
    c170_to_c100: dict[int, int] = {}

    for r in all_recs:
        if r.register == "C100":
            current_c100 = r
        elif r.register == "C170" and current_c100 is not None:
            doc_c170[current_c100.line_number].append(r)
            c170_to_c100[r.line_number] = current_c100.line_number
        elif r.register == "C190" and current_c100 is not None:
            doc_c190[current_c100.line_number].append(r)

    # Analisar cada C170 com ALIQ=0 e VL_ICMS>0
    for c100_line, items in doc_c170.items():
        c190_recs = doc_c190.get(c100_line, [])

        for item in items:
            vl_bc = to_float(get_field(item, F_C170_VL_BC_ICMS))
            aliq = to_float(get_field(item, F_C170_ALIQ_ICMS))
            vl_icms = to_float(get_field(item, F_C170_VL_ICMS))

            if not (aliq == 0 and vl_icms > 0 and vl_bc > 0):
                continue

            # Gerar hipotese
            hypothesis = _build_hypothesis(item, items, c190_recs)
            if hypothesis:
                errors.append(_hypothesis_to_error(item, hypothesis))

    return errors


# ──────────────────────────────────────────────
# Construcao da hipotese
# ──────────────────────────────────────────────

def _build_hypothesis(
    item: SpedRecord,
    siblings: list[SpedRecord],
    c190_recs: list[SpedRecord],
) -> CorrectionHypothesis | None:
    """Constroi hipotese de correcao para item com ALIQ=0."""
    vl_bc = to_float(get_field(item, F_C170_VL_BC_ICMS))
    vl_icms = to_float(get_field(item, F_C170_VL_ICMS))

    if vl_bc <= 0:
        return None

    # Etapa 1: Calcular aliquota implicita
    aliq_implicita = round(vl_icms / vl_bc * 100, 2)

    # Etapa 2: Verificar plausibilidade
    aliq_plausivel = _find_plausible_rate(aliq_implicita)
    if aliq_plausivel is None:
        return None

    hypothesis = CorrectionHypothesis(
        field_name="ALIQ_ICMS",
        current_value="0",
        suggested_value=f"{aliq_plausivel:.2f}",
    )

    # Score: aliquota implicita bate com percentual conhecido
    icms_check = round(vl_bc * aliq_plausivel / 100, 2)
    if abs(icms_check - vl_icms) <= TOLERANCE:
        hypothesis.score += 40
        hypothesis.reasons.append(
            f"Aliquota implicita {aliq_plausivel:.2f}% reproduz exatamente "
            f"o VL_ICMS ({vl_bc:.2f} x {aliq_plausivel:.2f}% = {icms_check:.2f})"
        )
    else:
        hypothesis.score += 20
        hypothesis.reasons.append(
            f"Aliquota implicita {aliq_implicita:.2f}% aproxima-se de "
            f"{aliq_plausivel:.2f}% (diferenca de arredondamento)"
        )

    # Score: campo zerado (erro de preenchimento, nao de conceito)
    hypothesis.score += 10
    hypothesis.reasons.append("Divergencia decorre de campo ALIQ_ICMS zerado")

    # Etapa 3: Cruzar com itens irmaos do mesmo documento
    cst_item = get_field(item, F_C170_CST_ICMS)
    cfop_item = get_field(item, F_C170_CFOP)
    siblings_same_rate = 0
    siblings_checked = 0

    for sib in siblings:
        if sib.line_number == item.line_number:
            continue
        sib_cst = get_field(sib, F_C170_CST_ICMS)
        sib_cfop = get_field(sib, F_C170_CFOP)
        sib_bc = to_float(get_field(sib, F_C170_VL_BC_ICMS))
        sib_icms = to_float(get_field(sib, F_C170_VL_ICMS))
        sib_aliq = to_float(get_field(sib, F_C170_ALIQ_ICMS))

        # Mesmo perfil fiscal
        if sib_cst != cst_item or sib_cfop != cfop_item:
            continue
        if sib_bc <= 0 or sib_icms <= 0:
            continue

        siblings_checked += 1
        sib_aliq_impl = round(sib_icms / sib_bc * 100, 2)
        sib_plausivel = _find_plausible_rate(sib_aliq_impl)

        if sib_plausivel == aliq_plausivel:
            siblings_same_rate += 1

    if siblings_checked > 0 and siblings_same_rate == siblings_checked:
        hypothesis.score += 20
        hypothesis.reasons.append(
            f"Todos os {siblings_checked} itens irmaos do documento "
            f"confirmam aliquota de {aliq_plausivel:.2f}%"
        )
    elif siblings_same_rate > 0:
        hypothesis.score += 10
        hypothesis.reasons.append(
            f"{siblings_same_rate} de {siblings_checked} itens irmaos "
            f"confirmam aliquota de {aliq_plausivel:.2f}%"
        )

    # Etapa 4: Cruzar com C190
    cst_trib = trib(cst_item)
    for c190 in c190_recs:
        c190_cst = trib(get_field(c190, F_C190_CST))
        c190_cfop = get_field(c190, F_C190_CFOP)
        c190_aliq = to_float(get_field(c190, F_C190_ALIQ))

        if c190_cst == cst_trib and c190_cfop == cfop_item:
            # C190 tem aliquota preenchida?
            if c190_aliq == aliq_plausivel:
                hypothesis.score += 20
                hypothesis.reasons.append(
                    f"C190 (CST={c190_cst} CFOP={c190_cfop}) confirma "
                    f"aliquota de {aliq_plausivel:.2f}%"
                )
                break
            elif c190_aliq > 0:
                # C190 tem outra aliquota
                hypothesis.score += 5
                hypothesis.reasons.append(
                    f"C190 indica aliquota {c190_aliq:.2f}% para esta combinacao"
                )
                break

    # Etapa 5: CST/CFOP compativeis com tributacao
    if cst_trib in CST_TRIBUTADO:
        hypothesis.score += 10
        hypothesis.reasons.append(
            f"CST {cst_item} indica tributacao (compativel com ICMS destacado)"
        )

    return hypothesis


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _find_plausible_rate(aliq_implicita: float) -> float | None:
    """Encontra aliquota plausivel mais proxima, dentro da tolerancia."""
    best = None
    best_diff = float("inf")
    for known in _ALIQ_PLAUSIVEIS:
        diff = abs(aliq_implicita - known)
        if diff <= _ALIQ_TOLERANCIA and diff < best_diff:
            best = known
            best_diff = diff
    return best


def _hypothesis_to_error(
    record: SpedRecord,
    hyp: CorrectionHypothesis,
) -> ValidationError:
    """Converte hipotese em ValidationError com mensagem detalhada."""
    vl_bc = to_float(get_field(record, F_C170_VL_BC_ICMS))
    vl_icms = to_float(get_field(record, F_C170_VL_ICMS))

    # Construir mensagem com evidencias
    parts = [
        f"ALIQ_ICMS=0 mas VL_ICMS={vl_icms:.2f} com BC={vl_bc:.2f}.",
        f"Aliquota sugerida: {hyp.suggested_value}%.",
    ]

    # Adicionar evidencias
    parts.append(f"Confianca: {hyp.confidence} ({hyp.score} pontos).")
    for reason in hyp.reasons:
        parts.append(f"- {reason}")

    suggested = hyp.suggested_value if hyp.auto_correctable else None

    return make_error(
        record,
        "ALIQ_ICMS",
        "ALIQ_ICMS_AUSENTE",
        " ".join(parts[:3]) + "\n" + "\n".join(parts[3:]),
        field_no=14,
        value="0",
        expected_value=suggested,
    )
