"""Validador de CST para Simples Nacional — MOD-12.

Regras implementadas:
- SN_001: CST Tabela A usado em contribuinte Simples Nacional (deve usar CSOSN)
- SN_002: CSOSN invalido (fora da tabela B)
- SN_003: CSOSN 101/201 com credito ICMS zerado ou acima de 3.95% (teto LC 155/2016)
- SN_004: CSOSN 201/202/203 sem ST preenchida
- SN_005: CSOSN 300 (imune) com BC ou ICMS preenchido
- SN_006: CSOSN 400 (nao tributada) com BC ou ICMS preenchido
- SN_007: CSOSN 500 (ST retida) sem preenchimento de BC_ICMS_ST anterior
- SN_008: CSOSN 900 (outros) sem justificativa aparente
- SN_009: PIS/COFINS com CST incompativel para SN
- SN_010: Arquivo Simples com perfil diferente de C
- SN_011: CST PIS/COFINS 04 (monofasico) em produto cujo NCM nao e monofasico
- SN_012: Aliquota de credito ICMS inconsistente entre itens do mesmo arquivo
"""

from __future__ import annotations

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import TaxRegime, ValidationContext
from ..services.reference_loader import ReferenceLoader
from .fiscal_semantics import _ncm_is_monofasico
from .helpers import (
    CST_TRIBUTADO,
    CST_ISENTO_NT,
    CST_DIFERIMENTO,
    CST_RESIDUAL,
    CSOSN_COM_CREDITO,
    CSOSN_COM_ST,
    CSOSN_SEM_DEBITO,
    CSOSN_VALIDOS,
    F_C170_ALIQ_ICMS,
    F_C170_COD_ITEM,
    F_C170_CST_ICMS,
    F_C170_CST_PIS,
    F_C170_CST_COFINS,
    F_C170_VL_BC_ICMS,
    F_C170_VL_BC_ICMS_ST,
    F_C170_VL_ICMS,
    F_C170_VL_ICMS_ST,
    get_field,
    make_error,
    to_float,
)

# CSTs Tabela A (Regime Normal) — nao devem aparecer em Simples
# Construido da uniao de todos os CSTs ICMS do JSON
_CST_TABELA_A = CST_TRIBUTADO | CST_ISENTO_NT | CST_DIFERIMENTO | CST_RESIDUAL

# CSOSN isentos/imunes/nao tributados — nao devem ter BC/ICMS
_CSOSN_ZERO = {"300", "400"}

# CSTs PIS/COFINS compativeis com Simples Nacional (fallback)
_CST_PIS_COFINS_SN_FALLBACK = frozenset({
    "04", "06", "07", "08", "09", "49",  # saidas
    "50", "70", "98",                      # entradas
    "99",                                  # ambos
})

# CSTs PIS/COFINS PROIBIDOS para SN (regime cumulativo/nao-cumulativo)
_CST_PIS_COFINS_PROIBIDOS_FALLBACK: dict[str, str] = {
    "01": "Exclusivo do regime de lucro real nao-cumulativo",
    "02": "Exclusivo do regime de lucro real nao-cumulativo",
    "03": "Exclusivo do regime de lucro real nao-cumulativo",
    "05": "Reservado para substitutos tributarios, nao aplicavel ao SN",
}

# Descricoes para mensagens de erro (fallback se YAML indisponivel)
_CST_PIS_COFINS_SN_DESC: dict[str, str] = {
    "04": "Monofasica - revenda a aliquota zero",
    "06": "Aliquota zero",
    "07": "Isenta da contribuicao",
    "08": "Sem incidencia da contribuicao",
    "09": "Com suspensao da contribuicao",
    "49": "Outras saidas (SN - receita tributada no regime)",
    "50": "Credito vinculado a receitas tributadas (entrada)",
    "70": "Aquisicao sem direito a credito (entrada)",
    "98": "Outras operacoes de entrada",
    "99": "Outras operacoes",
}

# CSTs que exigem NCM monofasico para serem validos
_CST_EXIGE_MONOFASICO = {"04"}

# CSOSN sets unificados (helpers.py carrega do JSON, com fallback)
_CSOSN_VALIDOS_FALLBACK = CSOSN_VALIDOS
_CSOSN_CREDITO_FALLBACK = CSOSN_COM_CREDITO
_CSOSN_ST_FALLBACK = CSOSN_COM_ST


def _get_cst_pis_cofins_sn(context: ValidationContext | None) -> frozenset[str]:
    """Retorna CSTs PIS/COFINS válidos para SN do reference_loader ou fallback."""
    loader = context.reference_loader if context else None
    if loader and hasattr(loader, "get_cst_pis_cofins_sn_validos"):
        result = loader.get_cst_pis_cofins_sn_validos()
        if result:
            return frozenset(result)
    return _CST_PIS_COFINS_SN_FALLBACK


def _get_cst_proibido_motivo(context: ValidationContext | None, cst: str) -> str | None:
    """Retorna motivo de proibição do CST para SN, ou None se não proibido."""
    loader = context.reference_loader if context else None
    if loader and hasattr(loader, "get_cst_pis_cofins_sn_proibidos"):
        proibidos = loader.get_cst_pis_cofins_sn_proibidos()
        if cst in proibidos:
            return proibidos[cst].get("motivo", "CST proibido para SN")
    return _CST_PIS_COFINS_PROIBIDOS_FALLBACK.get(cst)


def _get_cst_pis_desc(context: ValidationContext | None, cst: str) -> str:
    """Retorna descrição do CST PIS/COFINS via loader ou fallback."""
    loader = context.reference_loader if context else None
    if loader and hasattr(loader, "get_cst_pis_cofins_sn_descricao"):
        return loader.get_cst_pis_cofins_sn_descricao(cst)
    return _CST_PIS_COFINS_SN_DESC.get(cst, cst)


def _cst_exige_monofasico(context: ValidationContext | None, cst: str) -> bool:
    """Verifica se CST exige NCM monofásico via loader ou fallback."""
    loader = context.reference_loader if context else None
    if loader and hasattr(loader, "cst_pis_cofins_exige_monofasico"):
        return loader.cst_pis_cofins_exige_monofasico(cst)
    return cst in _CST_EXIGE_MONOFASICO


def _get_csosn_sets(context: ValidationContext | None) -> tuple[set[str], set[str], set[str]]:
    """Retorna (validos, credito, st) do reference_loader ou fallback."""
    loader = context.reference_loader if context else None
    if loader and hasattr(loader, "get_csosn_validos"):
        return (
            loader.get_csosn_validos() or _CSOSN_VALIDOS_FALLBACK,
            loader.get_csosn_com_credito() or _CSOSN_CREDITO_FALLBACK,
            loader.get_csosn_com_st() or _CSOSN_ST_FALLBACK,
        )
    return _CSOSN_VALIDOS_FALLBACK, _CSOSN_CREDITO_FALLBACK, _CSOSN_ST_FALLBACK


def _get_csosn_descricao(context: ValidationContext | None, csosn: str) -> str:
    """Retorna descrição do CSOSN via loader ou código cru."""
    loader = context.reference_loader if context else None
    if loader and hasattr(loader, "get_csosn_descricao"):
        return loader.get_csosn_descricao(csosn)
    return csosn


def validate_simples(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Valida CSTs para contribuintes do Simples Nacional."""
    if not context or context.regime != TaxRegime.SIMPLES_NACIONAL:
        return []

    csosn_validos, csosn_credito, csosn_st = _get_csosn_sets(context)
    cst_pis_cofins_validos = _get_cst_pis_cofins_sn(context)

    groups = group_by_register(records)
    errors: list[ValidationError] = []

    # Coletar aliquotas de credito ICMS para validacao de consistencia (SN_012)
    aliq_credito_valores: list[float] = []

    # Construir mapa COD_ITEM -> NCM a partir do cadastro 0200
    item_ncm: dict[str, str] = {}
    for r in groups.get("0200", []):
        cod_item = get_field(r, "COD_ITEM")
        ncm = get_field(r, "COD_NCM")
        if cod_item and ncm:
            item_ncm[cod_item] = ncm

    # SN_010: Perfil diferente de C
    if context.ind_perfil and context.ind_perfil.upper() != "C":
        errors.append(ValidationError(
            line_number=0,
            register="0000",
            field_no=13,
            field_name="IND_PERFIL",
            value=context.ind_perfil,
            error_type="SN_PERFIL_INVALIDO",
            message=(
                f"SN_010: Contribuinte identificado como Simples Nacional "
                f"mas IND_PERFIL='{context.ind_perfil}' (esperado 'C'). "
                f"Verifique se o regime tributario esta correto."
            ),
            expected_value="C",
        ))

    c170_records = groups.get("C170", [])

    for rec in c170_records:
        cst_raw = get_field(rec, F_C170_CST_ICMS)
        vl_bc = to_float(get_field(rec, F_C170_VL_BC_ICMS))
        vl_icms = to_float(get_field(rec, F_C170_VL_ICMS))
        aliq = to_float(get_field(rec, F_C170_ALIQ_ICMS))
        vl_bc_st = to_float(get_field(rec, F_C170_VL_BC_ICMS_ST))
        vl_icms_st = to_float(get_field(rec, F_C170_VL_ICMS_ST))
        cst_pis = get_field(rec, F_C170_CST_PIS)
        cst_cofins = get_field(rec, F_C170_CST_COFINS)

        # Extrair parte tributaria (2 ultimos digitos para Tabela A, 3 para CSOSN)
        cst_2d = cst_raw[-2:] if len(cst_raw) >= 2 else cst_raw

        # SN_001: CST Tabela A em Simples Nacional
        if cst_2d in _CST_TABELA_A and cst_raw not in csosn_validos:
            errors.append(make_error(
                rec, "CST_ICMS", "SN_CST_TABELA_A",
                f"SN_001: CST '{cst_raw}' pertence a Tabela A (Regime Normal). "
                f"Contribuinte do Simples Nacional deve usar CSOSN (Tabela B): "
                f"{', '.join(sorted(csosn_validos))}.",
                field_no=10,
                value=cst_raw,
            ))
            continue  # Sem sentido validar demais regras com CST errado

        # SN_002: CSOSN invalido
        if cst_raw and cst_raw not in csosn_validos and cst_2d not in _CST_TABELA_A:
            errors.append(make_error(
                rec, "CST_ICMS", "SN_CSOSN_INVALIDO",
                f"SN_002: CSOSN '{cst_raw}' nao e valido. "
                f"Valores aceitos: {', '.join(sorted(csosn_validos))}.",
                field_no=10,
                value=cst_raw,
            ))
            continue

        # SN_003: CSOSN 101/201 com credito — validacao por range (LC 155/2016)
        # Teto absoluto de qualquer Anexo/faixa: 3.95% (Anexo I faixa 6)
        # Sem RBT12 no SPED, sinaliza como indicio, nao erro objetivo.
        if cst_raw in csosn_credito:
            if aliq == 0 and (vl_icms != 0 or vl_bc > 0):
                # Aliquota zerada mas tem BC ou ICMS preenchido — erro provavel
                desc = _get_csosn_descricao(context, cst_raw)
                errors.append(make_error(
                    rec, "ALIQ_ICMS", "SN_CREDITO_ZERADO_OU_FORA_RANGE",
                    f"SN_003: CSOSN {cst_raw} ({desc}) com ALIQ_ICMS=0% mas "
                    f"VL_BC_ICMS={vl_bc:.2f} ou VL_ICMS={vl_icms:.2f} preenchido. "
                    f"Credito nao exercido ou empresa optou por nao segregar — "
                    f"requer confirmacao. Consultar DAS/PGDAS-D do periodo.",
                    field_no=14,
                    value="0",
                ))
            elif aliq == 0 and vl_icms == 0 and vl_bc == 0:
                # Tudo zerado — credito nao preenchido
                desc = _get_csosn_descricao(context, cst_raw)
                errors.append(make_error(
                    rec, "ALIQ_ICMS", "SN_CREDITO_ZERADO_OU_FORA_RANGE",
                    f"SN_003: CSOSN {cst_raw} ({desc}) permite aproveitamento de "
                    f"credito ICMS, mas ALIQ_ICMS, VL_BC_ICMS e VL_ICMS estao "
                    f"zerados. Preencher com a aliquota efetiva de ICMS do "
                    f"Simples (pCredSN conforme LC 155/2016). "
                    f"Faixa possivel: 0,40% a 3,95%.",
                    field_no=14,
                    value="0",
                ))
            elif aliq > 3.95:
                # Acima do teto maximo de qualquer Anexo/faixa (3.95%)
                desc = _get_csosn_descricao(context, cst_raw)
                errors.append(make_error(
                    rec, "ALIQ_ICMS", "SN_CREDITO_ZERADO_OU_FORA_RANGE",
                    f"SN_003: CSOSN {cst_raw} ({desc}) com ALIQ_ICMS={aliq:.2f}%, "
                    f"acima do teto maximo de 3,95% para credito ICMS no Simples "
                    f"Nacional (LC 155/2016, Anexos I-V, todas as faixas). "
                    f"Verificar faixa de RBT12 e Anexo aplicavel. "
                    f"Consultar DAS/PGDAS-D do periodo.",
                    field_no=14,
                    value=f"{aliq:.2f}",
                    expected_value="<= 3.95",
                ))
            elif aliq > 0:
                # Aliquota dentro do range valido — coletar para consistencia (SN_012)
                aliq_credito_valores.append(aliq)

        # SN_004: CSOSN com ST sem valores preenchidos
        if cst_raw in csosn_st and vl_bc_st == 0 and vl_icms_st == 0:
            desc = _get_csosn_descricao(context, cst_raw)
            errors.append(make_error(
                rec, "VL_BC_ICMS_ST", "SN_ST_NAO_PREENCHIDA",
                f"SN_004: CSOSN {cst_raw} ({desc}) indica ST, mas VL_BC_ICMS_ST e "
                f"VL_ICMS_ST estao zerados. Preencher base e valor da ST.",
                field_no=16,
                value="0",
            ))

        # SN_005/SN_006: CSOSN 300/400 com BC ou ICMS
        if cst_raw in _CSOSN_ZERO and (vl_bc > 0 or vl_icms > 0):
            desc = _get_csosn_descricao(context, cst_raw)
            rule = "SN_005" if cst_raw == "300" else "SN_006"
            errors.append(make_error(
                rec, "VL_BC_ICMS", f"SN_CSOSN_{cst_raw}_COM_ICMS",
                f"{rule}: CSOSN {cst_raw} ({desc}) nao deve ter "
                f"VL_BC_ICMS={vl_bc:.2f} ou VL_ICMS={vl_icms:.2f}. "
                f"Zerar campos de BC e ICMS.",
                field_no=13,
                value=f"{vl_bc:.2f}",
                expected_value="0.00",
            ))

        # SN_007: CSOSN 500 sem BC_ST anterior
        if cst_raw == "500" and vl_bc_st == 0:
            desc = _get_csosn_descricao(context, "500")
            errors.append(make_error(
                rec, "VL_BC_ICMS_ST", "SN_500_SEM_BC_ST",
                f"SN_007: CSOSN 500 ({desc}) mas "
                f"VL_BC_ICMS_ST esta zerado. Informar a base de calculo "
                f"da ST retida na operacao anterior.",
                field_no=16,
                value="0",
            ))

        # SN_009: PIS/COFINS com CST incompativel
        cst_pis_norm = cst_pis.strip().zfill(2) if cst_pis else ""
        if cst_pis_norm and cst_pis_norm not in cst_pis_cofins_validos:
            motivo = _get_cst_proibido_motivo(context, cst_pis_norm)
            if motivo:
                # CST explicitamente proibido para SN
                errors.append(make_error(
                    rec, "CST_PIS", "SN_PIS_CST_PROIBIDO",
                    f"SN_009: CST_PIS '{cst_pis_norm}' proibido para Simples Nacional. "
                    f"Motivo: {motivo}. "
                    f"Para saidas normais use CST 49; para entradas use CST 70.",
                    field_no=25,
                    value=cst_pis_norm,
                ))
            else:
                errors.append(make_error(
                    rec, "CST_PIS", "SN_PIS_CST_INCOMPATIVEL",
                    f"SN_009: CST_PIS '{cst_pis_norm}' nao permitido para Simples Nacional. "
                    f"CSTs permitidos: {', '.join(sorted(cst_pis_cofins_validos))}.",
                    field_no=25,
                    value=cst_pis_norm,
                ))

        # SN_011: CST PIS/COFINS 04 (monofasico) em NCM nao monofasico
        if cst_pis_norm and _cst_exige_monofasico(context, cst_pis_norm):
            cod_item = get_field(rec, F_C170_COD_ITEM)
            ncm = item_ncm.get(cod_item, "")
            if ncm and not _ncm_is_monofasico(ncm):
                desc = _get_cst_pis_desc(context, cst_pis_norm)
                errors.append(make_error(
                    rec, "CST_PIS", "SN_CST_MONOFASICO_NCM_INVALIDO",
                    f"SN_011: CST_PIS '{cst_pis_norm}' ({desc}) usado para "
                    f"item com NCM {ncm}, que nao consta na lista de produtos "
                    f"monofasicos da RFB. Verifique se o NCM esta correto ou "
                    f"se o CST deveria ser 49 (outras saidas tributadas no SN).",
                    field_no=25,
                    value=cst_pis_norm,
                ))

    # SN_012: Deteccao de anomalia em aliquotas de credito entre itens
    # Variacao > 1.0pp pode indicar: mistura de Anexos (correto mas raro),
    # mudanca de faixa RBT12 no periodo (improvavel), ou erro de ERP (provavel).
    # Threshold de 1.0pp evita falsos positivos por arredondamento.
    if len(aliq_credito_valores) >= 2:
        aliq_min = min(aliq_credito_valores)
        aliq_max = max(aliq_credito_valores)
        distinct_count = len(set(round(v, 4) for v in aliq_credito_valores))
        if distinct_count > 1 and (aliq_max - aliq_min) > 1.0:
            errors.append(ValidationError(
                line_number=0,
                register="C170",
                field_no=14,
                field_name="ALIQ_ICMS",
                value=f"min={aliq_min:.4f} max={aliq_max:.4f}",
                error_type="SN_CREDITO_INCONSISTENTE",
                message=(
                    f"SN_012: Aliquotas de credito ICMS variam significativamente "
                    f"entre itens (min={aliq_min:.4f}%, max={aliq_max:.4f}%, "
                    f"delta={aliq_max - aliq_min:.4f}pp, {distinct_count} valores "
                    f"distintos). Isso pode indicar: mistura de Anexos diferentes "
                    f"(correto mas raro), mudanca de faixa de RBT12 durante o "
                    f"periodo (improvavel), ou parametrizacao inconsistente no "
                    f"ERP (provavel erro). Verificar com DAS/PGDAS-D."
                ),
            ))

    return errors
