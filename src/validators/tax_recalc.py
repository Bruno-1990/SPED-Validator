"""Recalculo tributario: ICMS, ICMS-ST, IPI, PIS/COFINS e totalizacao E110."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import ValidationContext
from .helpers import (
    get_field,
    make_error,
    to_float,
)
from .tolerance import get_tolerance

# ──────────────────────────────────────────────
# Helpers locais
# ──────────────────────────────────────────────

def _float_opt(value: str) -> float | None:
    """Converte string para float, retornando None se vazio."""
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _check_calc(
    record: SpedRecord,
    field_name: str,
    field_no: int,
    vl_bc: float,
    aliq: float,
    vl_declarado: float,
    tributo_label: str,
    tolerance_type: str = "item_icms",
) -> list[ValidationError]:
    """Verifica calculo imposto = BC * ALIQ / 100 com deteccao de arredondamento.

    Se a divergencia decorre de arredondamento ou truncamento (ERP usa
    precisao diferente), gera CALCULO_ARREDONDAMENTO com explicacao.
    Caso contrario, gera CALCULO_DIVERGENTE.

    Deteccao de arredondamento/truncamento:
    - R$ 0.01: sempre arredondamento (1 centavo)
    - Taxa efetiva arredondada bate com aliquota
    - Declarado == truncamento do calculo exato (int(calc*100)/100)
    """
    calc = vl_bc * aliq / 100
    diff = abs(calc - vl_declarado)

    tol = get_tolerance(tolerance_type)
    if diff <= tol:
        return []

    # Verificar se e arredondamento/truncamento
    is_rounding = False
    motivo_arredondamento = ""

    if vl_bc > 0 and vl_declarado > 0:
        # Caso 1: diferenca de exatamente 1 centavo (arredondamento classico)
        if round(diff, 2) == 0.01:
            is_rounding = True
            motivo_arredondamento = "diferenca de 1 centavo por arredondamento"

        # Caso 2: taxa efetiva arredondada bate com aliquota
        if not is_rounding:
            taxa_efetiva = vl_declarado / vl_bc * 100
            if round(taxa_efetiva, 2) == round(aliq, 2):
                is_rounding = True
                motivo_arredondamento = (
                    f"taxa efetiva ({taxa_efetiva:.4f}%) coincide com aliquota ({aliq:.2f}%)"
                )

        # Caso 3: declarado == truncamento do calculo exato
        if not is_rounding:
            truncado = int(calc * 100) / 100
            if abs(vl_declarado - truncado) < 0.005:
                is_rounding = True
                motivo_arredondamento = (
                    f"ERP truncou {calc:.4f} para {truncado:.2f} em vez de arredondar para {round(calc, 2):.2f}"
                )

        # Caso 4: diferenca <= 0.02 (2 centavos) com aliquota inteira
        if not is_rounding and diff <= 0.02 and aliq == round(aliq):
            is_rounding = True
            motivo_arredondamento = f"diferenca de R$ {diff:.2f} com aliquota inteira ({aliq:.0f}%)"

    if is_rounding:
        return [make_error(
            record, field_name, "CALCULO_ARREDONDAMENTO",
            f"{tributo_label}: calculado={calc:.2f} (BC {vl_bc:.2f} x {aliq:.2f}%) "
            f"vs declarado={vl_declarado:.2f} (dif=R$ {diff:.2f}). "
            f"Causa provavel: {motivo_arredondamento}. "
            f"Confianca: alta (95 pontos).",
            field_no=field_no,
            expected_value=f"{calc:.2f}",
            value=f"{vl_declarado:.2f}",
        )]

    # Calculo divergente: confianca baseada na certeza matematica
    score = 100  # Recalculo deterministico = certeza maxima
    return [make_error(
        record, field_name, "CALCULO_DIVERGENTE",
        f"{tributo_label}: calculado={calc:.2f} (BC {vl_bc:.2f} x {aliq:.2f}%) "
        f"vs declarado={vl_declarado:.2f} (dif={diff:.2f}). "
        f"Confianca: alta ({score} pontos).",
        field_no=field_no,
        expected_value=f"{calc:.2f}",
        value=f"{vl_declarado:.2f}",
    )]


# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def recalculate_taxes(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Executa todos os recalculos tributarios.

    Retorna lista de erros onde valor declarado diverge do recalculado.
    """
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    # Recalculo por item (C170)
    for rec in groups.get("C170", []):
        errors.extend(recalc_icms_item(rec))
        errors.extend(recalc_icms_st_item(rec))
        errors.extend(recalc_ipi_item(rec))
        errors.extend(recalc_pis_cofins_item(rec))

    # Totalizacao E110
    errors.extend(recalc_e110_totals(groups))

    return errors


# ──────────────────────────────────────────────
# ICMS por item (C170)
# ──────────────────────────────────────────────

def recalc_icms_item(record: SpedRecord) -> list[ValidationError]:
    """Recalcula ICMS de um item C170.

    Campos C170 relevantes (0-based):
    6:VL_ITEM, 7:VL_DESC, 12:VL_BC_ICMS, 13:ALIQ_ICMS, 14:VL_ICMS

    Regra: BC_ICMS = VL_ITEM - VL_DESC (quando tributado)
           ICMS = BC_ICMS * ALIQ / 100
    """
    errors: list[ValidationError] = []

    _vl_item = to_float(get_field(record, "VL_ITEM"))
    _vl_desc = to_float(get_field(record, "VL_DESC"))
    vl_bc_icms = _float_opt(get_field(record, "VL_BC_ICMS"))
    aliq_icms = _float_opt(get_field(record, "ALIQ_ICMS"))
    vl_icms = _float_opt(get_field(record, "VL_ICMS"))

    if vl_bc_icms is None or aliq_icms is None or vl_icms is None:
        return errors

    if vl_bc_icms == 0 and aliq_icms == 0:
        return errors  # Item nao tributado

    # Caso especial: ALIQ=0 mas VL_ICMS > 0 com BC > 0
    # Tratado pelo correction_hypothesis.py com analise de confianca.
    if aliq_icms == 0 and vl_icms > 0 and vl_bc_icms > 0:
        return errors

    errors.extend(_check_calc(
        record, "VL_ICMS", 15, vl_bc_icms, aliq_icms, vl_icms, "ICMS",
        tolerance_type="item_icms",
    ))
    return errors


# ──────────────────────────────────────────────
# ICMS-ST por item (C170)
# ──────────────────────────────────────────────

# CSTs que indicam substituicao tributaria
_CST_ST = {"10", "30", "60", "70", "201", "202", "203", "500"}


def recalc_icms_st_item(record: SpedRecord) -> list[ValidationError]:
    """Verifica consistencia do ICMS-ST de um item C170.

    Campos C170 relevantes (0-based):
    9:CST_ICMS (posicao pode variar), 15:VL_BC_ICMS_ST, 16:ALIQ_ST, 17:VL_ICMS_ST

    Para CSTs de ST, BC_ST e VL_ICMS_ST devem ser consistentes.
    """
    errors: list[ValidationError] = []

    # CST_ICMS na posicao 9 (campo 10 do C170)
    cst_icms = get_field(record, "CST_ICMS")

    # So valida se CST indica ST
    if cst_icms not in _CST_ST:
        return errors

    # Posicoes para ICMS-ST no C170 (podem variar por versao)
    # Tentamos posicoes comuns: 15, 16, 17
    vl_bc_st = _float_opt(get_field(record, "VL_BC_ICMS_ST"))
    aliq_st = _float_opt(get_field(record, "ALIQ_ST"))
    vl_icms_st = _float_opt(get_field(record, "VL_ICMS_ST"))

    if vl_bc_st is None or vl_icms_st is None:
        return errors

    # CST 10/30: verificar se BC_ICMS_ST existe quando VL_ICMS_ST > 0
    cst_trib = cst_icms[-2:] if len(cst_icms) >= 2 else cst_icms
    if cst_trib in ("10", "30") and vl_icms_st > 0 and vl_bc_st == 0:
        errors.append(make_error(
            record, "VL_BC_ICMS_ST", "CALCULO_DIVERGENTE",
            f"CST {cst_icms} indica ST com debito, VL_ICMS_ST={vl_icms_st:.2f} "
            f"mas BC_ICMS_ST esta zerada. A base de calculo da ST e obrigatoria.",
            field_no=16,
            expected_value=None,
            value="0.00",
        ))

    # Se tem BC_ST mas ICMS_ST e zero (ou vice-versa), pode ser inconsistencia
    if vl_bc_st > 0 and vl_icms_st == 0:
        expected_st = (vl_bc_st * aliq_st / 100) if aliq_st and aliq_st > 0 else None
        errors.append(make_error(
            record, "VL_ICMS_ST", "CALCULO_DIVERGENTE",
            f"CST {cst_icms} indica ST, BC_ST={vl_bc_st:.2f} mas VL_ICMS_ST=0.",
            field_no=18,
            expected_value=f"{expected_st:.2f}" if expected_st else None,
            value="0.00",
        ))

    # Se tem aliquota, recalcular
    if aliq_st is not None and aliq_st > 0 and vl_bc_st > 0:
        errors.extend(_check_calc(
            record, "VL_ICMS_ST", 18, vl_bc_st, aliq_st, vl_icms_st, "ICMS-ST",
            tolerance_type="item_icms",
        ))

    return errors


# ──────────────────────────────────────────────
# IPI por item (C170)
# ──────────────────────────────────────────────

def recalc_ipi_item(record: SpedRecord) -> list[ValidationError]:
    """Recalcula IPI de um item C170.

    Campos C170 relevantes (posicoes aproximadas):
    18 ou 19: VL_BC_IPI, 19 ou 20: ALIQ_IPI, 20 ou 21: VL_IPI

    Regra: IPI = VL_BC_IPI * ALIQ_IPI / 100
    """
    errors: list[ValidationError] = []

    # Posicoes do IPI no C170: campo 22=VL_BC_IPI, 23=ALIQ_IPI, 24=VL_IPI
    vl_bc_ipi = _float_opt(get_field(record, "VL_BC_IPI"))
    aliq_ipi = _float_opt(get_field(record, "ALIQ_IPI"))
    vl_ipi = _float_opt(get_field(record, "VL_IPI"))

    if vl_bc_ipi is None or aliq_ipi is None or vl_ipi is None:
        return errors

    if vl_bc_ipi == 0 and aliq_ipi == 0:
        return errors

    errors.extend(_check_calc(record, "VL_IPI", 22, vl_bc_ipi, aliq_ipi, vl_ipi, "IPI", tolerance_type="item_ipi"))
    return errors


# ──────────────────────────────────────────────
# PIS/COFINS por item (C170)
# ──────────────────────────────────────────────

def recalc_pis_cofins_item(record: SpedRecord) -> list[ValidationError]:
    """Recalcula PIS e COFINS de um item C170.

    Campos C170 (posicoes aproximadas):
    PIS: 22:VL_BC_PIS, 23:ALIQ_PIS, 24:VL_PIS
    COFINS: 25:VL_BC_COFINS, 26:ALIQ_COFINS, 27:VL_COFINS
    """
    errors: list[ValidationError] = []

    # PIS: campo 26=VL_BC_PIS, 27=ALIQ_PIS(%), 30=VL_PIS
    vl_bc_pis = _float_opt(get_field(record, "VL_BC_PIS"))
    aliq_pis = _float_opt(get_field(record, "ALIQ_PIS"))
    vl_pis = _float_opt(get_field(record, "VL_PIS"))

    if (vl_bc_pis is not None and aliq_pis is not None and vl_pis is not None
            and vl_bc_pis > 0 and aliq_pis > 0):
        errors.extend(_check_calc(record, "VL_PIS", 25, vl_bc_pis, aliq_pis, vl_pis, "PIS", tolerance_type="item_pis"))

    # COFINS: campo 32=VL_BC_COFINS, 33=ALIQ_COFINS(%), 36=VL_COFINS
    vl_bc_cofins = _float_opt(get_field(record, "VL_BC_COFINS"))
    aliq_cofins = _float_opt(get_field(record, "ALIQ_COFINS"))
    vl_cofins = _float_opt(get_field(record, "VL_COFINS"))

    if (vl_bc_cofins is not None and aliq_cofins is not None and vl_cofins is not None
            and vl_bc_cofins > 0 and aliq_cofins > 0):
        errors.extend(_check_calc(
            record, "VL_COFINS", 28, vl_bc_cofins, aliq_cofins, vl_cofins,
            "COFINS", tolerance_type="item_cofins",
        ))

    return errors


# ──────────────────────────────────────────────
# Totalizacao E110
# ──────────────────────────────────────────────

@dataclass
class E110Totals:
    """Totais recalculados para o E110."""
    debitos_c190: float = 0.0
    creditos_c190: float = 0.0
    debitos_d: float = 0.0
    creditos_d: float = 0.0
    debitos_c590: float = 0.0
    creditos_c590: float = 0.0

    @property
    def total_debitos(self) -> float:
        return self.debitos_c190 + self.debitos_d + self.debitos_c590

    @property
    def total_creditos(self) -> float:
        return self.creditos_c190 + self.creditos_d + self.creditos_c590


def recalc_e110_totals(groups: dict[str, list[SpedRecord]]) -> list[ValidationError]:
    """Recalcula totalizacao do E110 a partir dos C190, D690 e C590.

    Soma ICMS dos C190/D690/C590 com CFOP de saida -> debitos
    Soma ICMS dos C190/D690/C590 com CFOP de entrada -> creditos
    Compara com VL_TOT_DEBITOS e VL_TOT_CREDITOS do E110.

    IMPORTANTE: O E110 pode ter componentes nao cobertos pelo recalculo
    (D190, C390, ajustes E111, DIFAL E300+). O sistema informa
    o que foi considerado e o que pode justificar a diferenca.
    """
    errors: list[ValidationError] = []

    e110_records = groups.get("E110", [])
    if not e110_records:
        return errors

    totals = E110Totals()

    # C190: CFOP na posicao 2, VL_ICMS na posicao 6
    for rec in groups.get("C190", []):
        cfop = get_field(rec, "CFOP")
        vl_icms = to_float(get_field(rec, "VL_ICMS"))
        if cfop and cfop[0] in ("5", "6", "7"):
            totals.debitos_c190 += vl_icms
        elif cfop and cfop[0] in ("1", "2", "3"):
            totals.creditos_c190 += vl_icms

    # D690 (se existir): VL_OPR na posicao CFOP/VL_OPR
    for rec in groups.get("D690", []):
        cfop = get_field(rec, "CFOP")
        vl_icms = to_float(get_field(rec, "VL_OPR"))
        if cfop and cfop[0] in ("5", "6", "7"):
            totals.debitos_d += vl_icms
        elif cfop and cfop[0] in ("1", "2", "3"):
            totals.creditos_d += vl_icms

    # MOD-17: C590 (energia/gas) — VL_ICMS por CFOP
    for rec in groups.get("C590", []):
        cfop = get_field(rec, "CFOP")
        vl_icms = to_float(get_field(rec, "VL_ICMS"))
        if cfop and cfop[0] in ("5", "6", "7"):
            totals.debitos_c590 += vl_icms
        elif cfop and cfop[0] in ("1", "2", "3"):
            totals.creditos_c590 += vl_icms

    # Detectar presenca de componentes nao cobertos pelo recalculo
    has_e111 = len(groups.get("E111", [])) > 0
    has_d190 = len(groups.get("D190", [])) > 0
    has_c390 = len(groups.get("C390", [])) > 0
    has_e300 = len(groups.get("E300", [])) > 0

    nao_cobertos: list[str] = []
    if has_e111:
        nao_cobertos.append("E111 (ajustes de apuracao)")
    if has_d190:
        nao_cobertos.append("D190 (servicos)")
    if has_c390:
        nao_cobertos.append("C390 (cupons fiscais)")
    if has_e300:
        nao_cobertos.append("E300+ (DIFAL)")

    # Ajustar confianca: se ha componentes nao cobertos, a sugestao
    # de correcao pode estar incompleta
    tem_lacunas = len(nao_cobertos) > 0

    for e110 in e110_records:
        vl_tot_debitos = to_float(get_field(e110, "VL_TOT_DEBITOS"))
        vl_tot_creditos = to_float(get_field(e110, "VL_TOT_CREDITOS"))

        # Debitos
        tol_e110 = get_tolerance("apuracao_e110")
        diff_deb = abs(totals.total_debitos - vl_tot_debitos)
        if diff_deb > tol_e110:
            if tem_lacunas:
                score = 60
                aviso = (
                    f" ATENCAO: o recalculo considerou apenas C190+D690+C590. "
                    f"O arquivo tambem contem {', '.join(nao_cobertos)} que "
                    f"podem justificar a diferenca. Avalie antes de corrigir."
                )
            else:
                score = 100
                aviso = ""

            errors.append(make_error(
                e110, "VL_TOT_DEBITOS", "CALCULO_DIVERGENTE",
                f"Totalizacao E110: debitos recalculados={totals.total_debitos:.2f} "
                f"(C190={totals.debitos_c190:.2f} + D={totals.debitos_d:.2f} + C590={totals.debitos_c590:.2f}) "
                f"vs declarado={vl_tot_debitos:.2f} (dif={diff_deb:.2f}).{aviso} "
                f"Confianca: {'provavel' if tem_lacunas else 'alta'} ({score} pontos).",
                field_no=2,
                expected_value=f"{totals.total_debitos:.2f}",
                value=f"{vl_tot_debitos:.2f}",
            ))

        # Creditos
        diff_cred = abs(totals.total_creditos - vl_tot_creditos)
        if diff_cred > tol_e110:
            if tem_lacunas:
                score = 60
                aviso = (
                    f" ATENCAO: o recalculo considerou apenas C190+D690+C590. "
                    f"O arquivo tambem contem {', '.join(nao_cobertos)} que "
                    f"podem justificar a diferenca. Avalie antes de corrigir."
                )
            else:
                score = 100
                aviso = ""

            errors.append(make_error(
                e110, "VL_TOT_CREDITOS", "CALCULO_DIVERGENTE",
                f"Totalizacao E110: creditos recalculados={totals.total_creditos:.2f} "
                f"(C190={totals.creditos_c190:.2f} + D={totals.creditos_d:.2f} + C590={totals.creditos_c590:.2f}) "
                f"vs declarado={vl_tot_creditos:.2f} (dif={diff_cred:.2f}).{aviso} "
                f"Confianca: {'provavel' if tem_lacunas else 'alta'} ({score} pontos).",
                field_no=6,
                expected_value=f"{totals.total_creditos:.2f}",
                value=f"{vl_tot_creditos:.2f}",
            ))

    return errors
