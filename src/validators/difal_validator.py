"""Validador de DIFAL (Diferencial de Aliquota Interestadual).

Regras implementadas:
- DIFAL_001: DIFAL faltante em operacao de consumo final interestadual
- DIFAL_002: DIFAL indevido em revenda/industrializacao
- DIFAL_003: UF destino inconsistente no DIFAL
- DIFAL_004: Aliquota interna destino incorreta no DIFAL
- DIFAL_005: Base DIFAL inconsistente com operacao
- DIFAL_006: FCP ausente ou incoerente
- DIFAL_007: Perfil destinatario incompativel com DIFAL
- DIFAL_008: Consumo final sem marcadores consistentes
- DIFAL_009: Partilha DIFAL incorreta (EC 87/2015, transicao 2016-2018)

Tabelas de referencia (via ReferenceLoader / sped.db):
- aliquotas_internas_uf.yaml
- fcp_por_uf.yaml
- difal_vigente (sped.db)
"""

from __future__ import annotations

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import ValidationContext
from .helpers import (
    ALIQ_INTERESTADUAIS,
    CFOP_REMESSA_RETORNO,
    CST_TRIBUTADO,
    cst_origem,
    get_field,
    make_error,
    make_generic_error,
    to_float,
    trib,
)
from .tolerance import get_tolerance


# ──────────────────────────────────────────────
# Constantes locais
# ──────────────────────────────────────────────

# CFOPs de venda/transferencia interestadual para consumidor final
_CFOP_INTERESTADUAL_CONSUMO_FINAL = {
    "6107", "6108",  # venda a nao contribuinte
    "6401", "6402", "6403", "6404",  # venda por ST a consumidor final
    "6501", "6502",  # remessa p/ industrializacao por encomenda (uso/consumo)
}

# CFOPs de venda interestadual para revenda/industrializacao
_CFOP_INTERESTADUAL_REVENDA_INDUSTRIA = {
    "6101", "6102", "6103", "6104", "6105", "6106",  # venda
    "6109", "6110", "6111", "6112", "6113", "6116",  # venda
    "6117", "6118", "6119", "6120", "6122", "6123",  # venda
    "6151", "6152", "6153",  # transferencia
    "6201", "6202",  # devolucao
}

# CSTs que indicam operacao com DIFAL (tributado com diferencial)
# Usa CST_TRIBUTADO do helpers.py (alimentado por Tabela_CST_Vigente.json)
# que inclui 00,02,10,12,13,15,20,70,72,74 (exclui 90 residual)
_CST_COM_DIFAL = CST_TRIBUTADO

# CSTs de origem que indicam produto importado sujeito a aliquota 4%
# (Resolucao Senado 13/2012)
# Origem 1 = importacao direta, 2 = importacao mercado interno,
# 3 = nacional conteudo importacao > 40%, 8 = nacional importacao > 70%
# Excecoes (seguem 7/12%): 4 = PPB, 6/7 = sem similar nacional CAMEX
_CST_ORIGEM_IMPORTADA_4PCT = {"1", "2", "3", "8"}


# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def validate_difal(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Executa validacoes de DIFAL nos registros SPED."""
    from datetime import date as _date

    # Vigencia: DIFAL so se aplica a partir de 01/01/2016 (EC 87/2015)
    if context and context.periodo_ini and context.periodo_ini < _date(2016, 1, 1):
        return []

    groups = group_by_register(records)
    errors: list[ValidationError] = []

    # Resolver loader de referencia
    loader = context.reference_loader if context else None

    # Verificar disponibilidade de tabelas externas
    if not loader or loader.get_aliquota_interna("SP") is None:
        errors.append(make_generic_error(
            "DIFAL_VERIFICACAO_INCOMPLETA",
            "Tabela de aliquotas internas por UF nao disponivel. "
            "Verificacoes DIFAL_001 e DIFAL_004 serao parciais. "
            "Disponibilize data/reference/aliquotas_internas_uf.yaml.",
            register="E300",
            value="aliquotas_internas_uf.yaml",
        ))

    # UF do declarante (0000, campo 8)
    uf_declarante = ""
    for r in groups.get("0000", []):
        uf_declarante = get_field(r, "UF").upper()
        break

    if not uf_declarante:
        return errors

    # Regime para consulta DIFAL
    regime = ""
    if context:
        from ..services.context_builder import TaxRegime
        if context.regime == TaxRegime.SIMPLES_NACIONAL:
            regime = "simples_nacional"
        elif context.regime == TaxRegime.NORMAL:
            regime = "normal"

    # Mapa COD_PART -> (UF, IND_IE)
    part_info: dict[str, dict[str, str]] = {}
    for r in groups.get("0150", []):
        cod = get_field(r, "COD_PART")
        uf = get_field(r, "UF").upper()
        ind_ie = get_field(r, "CPF")
        if cod:
            part_info[cod] = {"uf": uf, "ind_ie": ind_ie}

    # Mapa C170.line -> C100 pai
    c170_parent = _build_parent_map(groups)

    # Per-item (C170) — operacoes interestaduais
    for rec in groups.get("C170", []):
        parent = c170_parent.get(rec.line_number)
        if not parent:
            continue

        cod_part = get_field(parent, "COD_PART")
        info = part_info.get(cod_part, {})
        uf_dest = info.get("uf", "")
        ind_ie = info.get("ind_ie", "")

        # So valida interestaduais (CFOP 6xxx)
        cfop = get_field(rec, "CFOP")
        if not cfop or cfop[0] != "6":
            continue
        if cfop in CFOP_REMESSA_RETORNO:
            continue

        # Determinar tipo destinatario e situacao DIFAL
        dest_tipo = "nao_contribuinte" if ind_ie == "9" else "contribuinte"
        situacao = None
        if loader and loader.has_difal_vigente_table():
            situacao = loader.get_difal_situacao(regime, dest_tipo)

        # Nota de controversia para todas as regras
        controverso = situacao.get("status_juridico") == "controverso" if situacao else False

        errors.extend(_check_difal_001(rec, cfop, uf_declarante, uf_dest, ind_ie, loader, situacao))
        errors.extend(_check_difal_002(rec, cfop, ind_ie, situacao))
        errors.extend(_check_difal_003(rec, cfop, uf_declarante, uf_dest))
        errors.extend(_check_difal_004(rec, cfop, uf_dest, uf_declarante, loader))
        errors.extend(_check_difal_005(rec, cfop, uf_dest, uf_declarante, loader))
        errors.extend(_check_difal_006(rec, cfop, uf_dest, loader))
        errors.extend(_check_difal_007(rec, cfop, ind_ie, uf_dest))
        errors.extend(_check_difal_008(rec, cfop, ind_ie))
        errors.extend(_check_difal_010(rec, cfop, uf_declarante, uf_dest, loader))

    # DIFAL_009: validacao de partilha (nivel arquivo)
    if context and context.periodo_ini and loader:
        errors.extend(_check_difal_009(context.periodo_ini.year, loader))

    return errors


# ──────────────────────────────────────────────
# Contexto
# ──────────────────────────────────────────────

def _build_parent_map(
    groups: dict[str, list[SpedRecord]],
) -> dict[int, SpedRecord]:
    """Mapa C170.line_number -> C100 pai."""
    all_recs = []
    for reg_type in ("C100", "C170"):
        for r in groups.get(reg_type, []):
            all_recs.append(r)
    all_recs.sort(key=lambda r: r.line_number)

    parent_map: dict[int, SpedRecord] = {}
    current_c100: SpedRecord | None = None
    for r in all_recs:
        if r.register == "C100":
            current_c100 = r
        elif r.register == "C170" and current_c100 is not None:
            parent_map[r.line_number] = current_c100
    return parent_map


def _aliq_interestadual_esperada(uf_origem: str, uf_dest: str, loader=None) -> float:
    """Retorna aliquota interestadual esperada com base nas UFs."""
    if loader:
        result = loader.get_matriz_aliquota(uf_origem, uf_dest)
        if result is not None:
            return result
    # Fallback: regra geral Resolucao Senado 13/2012
    return 12.0


def _aliq_interna_destino(uf_dest: str, loader=None) -> float:
    """Retorna aliquota interna padrao da UF de destino."""
    if loader:
        result = loader.get_aliquota_interna(uf_dest)
        if result is not None:
            return result
    return 0.0


def _fcp_destino(uf_dest: str, loader=None) -> float:
    """Retorna percentual de FCP da UF de destino."""
    if loader:
        return loader.get_fcp(uf_dest)
    return 0.0


# ──────────────────────────────────────────────
# DIFAL_001: DIFAL faltante em consumo final
# ──────────────────────────────────────────────

def _check_difal_001(
    record: SpedRecord,
    cfop: str,
    uf_declarante: str,
    uf_dest: str,
    ind_ie: str,
    loader=None,
    situacao: dict | None = None,
) -> list[ValidationError]:
    """Operacao interestadual para consumidor final sem DIFAL."""
    if not uf_dest or uf_dest == uf_declarante:
        return []

    eh_consumo_final = (
        ind_ie == "9"
        or cfop in _CFOP_INTERESTADUAL_CONSUMO_FINAL
    )
    if not eh_consumo_final:
        return []

    cst = get_field(record, "CST_ICMS")
    if not cst:
        return []
    t = trib(cst)
    if t not in _CST_COM_DIFAL:
        return []

    aliq = to_float(get_field(record, "ALIQ_ICMS"))
    aliq_interna = _aliq_interna_destino(uf_dest, loader)
    aliq_inter = _aliq_interestadual_esperada(uf_declarante, uf_dest, loader)

    if aliq_interna <= 0:
        return []

    difal_esperado = aliq_interna - aliq_inter
    if difal_esperado <= 0:
        return []

    # Determinar severity: controverso -> warning, vigente -> error
    severity_hint = ""
    if situacao and situacao.get("status_juridico") == "controverso":
        severity_hint = " (NOTA: situacao juridica controversa — STF ADI 5469)"

    if abs(aliq - aliq_inter) < get_tolerance("item_icms"):
        return [make_error(
            record, "DIFAL", "DIFAL_FALTANTE_CONSUMO_FINAL",
            (
                f"Operacao interestadual (CFOP {cfop}) para consumidor final "
                f"em {uf_dest} com aliquota {aliq:.2f}% (interestadual). "
                f"Esperado DIFAL de {difal_esperado:.2f}pp "
                f"(aliq interna {uf_dest}={aliq_interna:.2f}% - "
                f"interestadual={aliq_inter:.2f}%). "
                f"Verifique se o DIFAL esta sendo recolhido por GNRE ou ajuste E300."
                f"{severity_hint}"
            ),
            field_no=14,
            value=f"CFOP={cfop} ALIQ={aliq:.2f}% UF_DEST={uf_dest}",
            expected_value=f"DIFAL={difal_esperado:.2f}pp",
        )]

    return []


# ──────────────────────────────────────────────
# DIFAL_002: DIFAL indevido em revenda/industrializacao
# ──────────────────────────────────────────────

def _check_difal_002(
    record: SpedRecord,
    cfop: str,
    ind_ie: str,
    situacao: dict | None = None,
) -> list[ValidationError]:
    """DIFAL aplicado indevidamente em operacao de revenda ou industrializacao."""
    if ind_ie != "1":
        return []

    if cfop not in _CFOP_INTERESTADUAL_REVENDA_INDUSTRIA:
        return []

    cst = get_field(record, "CST_ICMS")
    if not cst:
        return []
    t = trib(cst)
    if t not in _CST_COM_DIFAL:
        return []

    aliq = to_float(get_field(record, "ALIQ_ICMS"))
    if aliq <= 12.0:
        return []

    if aliq not in ALIQ_INTERESTADUAIS:
        return [make_error(
            record, "DIFAL", "DIFAL_INDEVIDO_REVENDA",
            (
                f"Operacao interestadual (CFOP {cfop}) para contribuinte "
                f"(IND_IE=1, revenda/industrializacao) com aliquota {aliq:.2f}%. "
                f"Nao cabe DIFAL em operacao para revenda ou industrializacao. "
                f"Aliquota esperada: 4%, 7% ou 12% conforme UF de origem/destino."
            ),
            field_no=14,
            value=f"CFOP={cfop} ALIQ={aliq:.2f}% IND_IE={ind_ie}",
        )]

    return []


# ──────────────────────────────────────────────
# DIFAL_003: UF destino inconsistente no DIFAL
# ──────────────────────────────────────────────

def _check_difal_003(
    record: SpedRecord,
    cfop: str,
    uf_declarante: str,
    uf_dest: str,
) -> list[ValidationError]:
    """UF do destinatario inconsistente com a operacao interestadual."""
    if not uf_dest:
        return []

    if cfop[0] == "6" and uf_dest == uf_declarante:
        return [make_error(
            record, "UF_DESTINO", "DIFAL_UF_DESTINO_INCONSISTENTE",
            (
                f"CFOP {cfop} (interestadual) mas destinatario cadastrado "
                f"na mesma UF do declarante ({uf_declarante}). "
                f"Se a operacao e interna, o CFOP deveria iniciar com 5. "
                f"Isso impacta diretamente o calculo do DIFAL."
            ),
            field_no=11,
            value=f"CFOP={cfop} UF_DECL={uf_declarante} UF_DEST={uf_dest}",
        )]

    return []


# ──────────────────────────────────────────────
# DIFAL_004: Aliquota interna destino incorreta
# ──────────────────────────────────────────────

def _check_difal_004(
    record: SpedRecord,
    cfop: str,
    uf_dest: str,
    uf_declarante: str,
    loader=None,
) -> list[ValidationError]:
    """Aliquota interna do destino incorreta no calculo do DIFAL."""
    if not uf_dest or uf_dest == uf_declarante:
        return []

    cst = get_field(record, "CST_ICMS")
    if not cst:
        return []
    t = trib(cst)
    if t not in _CST_COM_DIFAL:
        return []

    aliq = to_float(get_field(record, "ALIQ_ICMS"))
    aliq_interna = _aliq_interna_destino(uf_dest, loader)

    if aliq_interna <= 0:
        return []

    aliq_inter = _aliq_interestadual_esperada(uf_declarante, uf_dest, loader)

    if aliq <= aliq_inter + get_tolerance("item_icms"):
        return []

    if abs(aliq - aliq_interna) > get_tolerance("item_icms") and aliq > aliq_inter:
        return [make_error(
            record, "ALIQ_ICMS", "DIFAL_ALIQ_INTERNA_INCORRETA",
            (
                f"Operacao interestadual (CFOP {cfop}) para {uf_dest} com "
                f"aliquota {aliq:.2f}%, que difere da aliquota interna "
                f"oficial de {uf_dest} ({aliq_interna:.2f}%). "
                f"Para DIFAL, a aliquota interna de referencia deve ser "
                f"{aliq_interna:.2f}% conforme legislacao vigente."
            ),
            field_no=14,
            value=f"CFOP={cfop} ALIQ={aliq:.2f}% UF_DEST={uf_dest}",
            expected_value=f"{aliq_interna:.2f}%",
        )]

    return []


# ──────────────────────────────────────────────
# DIFAL_005: Base DIFAL inconsistente
# ──────────────────────────────────────────────

def _check_difal_005(
    record: SpedRecord,
    cfop: str,
    uf_dest: str,
    uf_declarante: str,
    loader=None,
) -> list[ValidationError]:
    """Base de calculo do DIFAL inconsistente com a operacao."""
    if not uf_dest or uf_dest == uf_declarante:
        return []

    cst = get_field(record, "CST_ICMS")
    if not cst:
        return []
    t = trib(cst)
    if t not in _CST_COM_DIFAL:
        return []

    vl_item = to_float(get_field(record, "VL_ITEM"))
    vl_bc = to_float(get_field(record, "VL_BC_ICMS"))
    aliq = to_float(get_field(record, "ALIQ_ICMS"))
    vl_icms = to_float(get_field(record, "VL_ICMS"))

    if vl_item <= 0 or vl_bc <= 0:
        return []

    aliq_interna = _aliq_interna_destino(uf_dest, loader)
    if aliq_interna <= 0:
        return []

    icms_esperado = vl_bc * aliq / 100.0
    if vl_icms > 0 and abs(vl_icms - icms_esperado) > max(get_tolerance("item_icms"), vl_bc * 0.005):
        return [make_error(
            record, "VL_BC_ICMS", "DIFAL_BASE_INCONSISTENTE",
            (
                f"Base ICMS (R$ {vl_bc:.2f}) x aliquota ({aliq:.2f}%) = "
                f"R$ {icms_esperado:.2f}, mas VL_ICMS informado e "
                f"R$ {vl_icms:.2f} (diferenca de R$ {abs(vl_icms - icms_esperado):.2f}). "
                f"A base de calculo do DIFAL deve refletir corretamente "
                f"a operacao interestadual para {uf_dest}."
            ),
            field_no=13,
            value=f"BC={vl_bc:.2f} ALIQ={aliq:.2f}% ICMS={vl_icms:.2f}",
            expected_value=f"ICMS={icms_esperado:.2f}",
        )]

    return []


# ──────────────────────────────────────────────
# DIFAL_006: FCP ausente ou incoerente
# ──────────────────────────────────────────────

def _check_difal_006(
    record: SpedRecord,
    cfop: str,
    uf_dest: str,
    loader=None,
) -> list[ValidationError]:
    """FCP ausente ou incoerente em operacao com DIFAL."""
    if not uf_dest:
        return []

    fcp_percentual = _fcp_destino(uf_dest, loader)

    if fcp_percentual <= 0:
        return []

    if cfop not in _CFOP_INTERESTADUAL_CONSUMO_FINAL:
        return []

    cst = get_field(record, "CST_ICMS")
    if not cst:
        return []
    t = trib(cst)
    if t not in _CST_COM_DIFAL:
        return []

    return [make_error(
        record, "FCP", "DIFAL_FCP_AUSENTE",
        (
            f"Operacao interestadual (CFOP {cfop}) para consumidor final "
            f"em {uf_dest}, que cobra FCP de {fcp_percentual:.1f}%. "
            f"Verifique se o FCP esta sendo destacado e recolhido."
        ),
        field_no=14,
        value=f"CFOP={cfop} UF_DEST={uf_dest} FCP_ESPERADO={fcp_percentual:.1f}%",
    )]


# ──────────────────────────────────────────────
# DIFAL_007: Perfil destinatario incompativel
# ──────────────────────────────────────────────

def _check_difal_007(
    record: SpedRecord,
    cfop: str,
    ind_ie: str,
    uf_dest: str,
) -> list[ValidationError]:
    """Perfil do destinatario incompativel com tratamento DIFAL."""
    if not ind_ie or not uf_dest:
        return []

    if ind_ie == "1" and cfop in _CFOP_INTERESTADUAL_CONSUMO_FINAL:
        return [make_error(
            record, "IND_IE", "DIFAL_PERFIL_INCOMPATIVEL",
            (
                f"Destinatario e contribuinte (IND_IE=1) mas CFOP {cfop} "
                f"indica operacao para consumidor final. Revise o cadastro "
                f"do participante ou o CFOP. Isso afeta diretamente "
                f"a responsabilidade pelo recolhimento do DIFAL."
            ),
            field_no=11,
            value=f"IND_IE={ind_ie} CFOP={cfop}",
        )]

    if ind_ie == "9" and cfop in _CFOP_INTERESTADUAL_REVENDA_INDUSTRIA:
        return [make_error(
            record, "IND_IE", "DIFAL_PERFIL_INCOMPATIVEL",
            (
                f"Destinatario nao-contribuinte (IND_IE=9) mas CFOP {cfop} "
                f"indica revenda/industrializacao. Nao-contribuinte nao "
                f"revende nem industrializa. Revise cadastro do participante "
                f"ou reclassifique a operacao."
            ),
            field_no=11,
            value=f"IND_IE={ind_ie} CFOP={cfop}",
        )]

    return []


# ──────────────────────────────────────────────
# DIFAL_008: Consumo final sem marcadores
# ──────────────────────────────────────────────

def _check_difal_008(
    record: SpedRecord,
    cfop: str,
    ind_ie: str,
) -> list[ValidationError]:
    """Consumo final sem marcadores consistentes."""
    if ind_ie != "9":
        return []

    if cfop in _CFOP_INTERESTADUAL_CONSUMO_FINAL:
        return []

    cst = get_field(record, "CST_ICMS")
    if not cst:
        return []
    t = trib(cst)
    if t not in _CST_COM_DIFAL:
        return []

    return [make_error(
        record, "CFOP", "DIFAL_CONSUMO_FINAL_SEM_MARCADOR",
        (
            f"Destinatario nao-contribuinte (IND_IE=9) com CFOP {cfop} "
            f"que nao e especifico de consumo final. Operacoes para "
            f"consumidor final interestadual devem usar CFOPs adequados "
            f"(6107, 6108, etc.) para correto tratamento do DIFAL. "
            f"Risco de extravio na apuracao do diferencial."
        ),
        field_no=11,
        value=f"IND_IE={ind_ie} CFOP={cfop}",
    )]


# ──────────────────────────────────────────────
# DIFAL_009: Partilha DIFAL (EC 87/2015)
# ──────────────────────────────────────────────

def _check_difal_009(ano: int, loader) -> list[ValidationError]:
    """DIFAL_009: Informa sobre a regra de partilha aplicavel ao periodo.

    2016: 60% origem / 40% destino
    2017: 40% origem / 60% destino
    2018: 20% origem / 80% destino
    2019+: 0% origem / 100% destino
    """
    if ano < 2016 or ano >= 2019:
        return []

    if not loader.has_difal_vigente_table():
        return []

    partilha = loader.get_difal_partilha(ano)
    if not partilha:
        return []

    return [make_generic_error(
        "DIFAL_PARTILHA_PERIODO_TRANSICAO",
        (
            f"Periodo {ano} esta na fase de transicao da partilha DIFAL "
            f"(EC 87/2015). {partilha.get('descricao', '')}. "
            f"Verifique se a apuracao E300/E310 reflete corretamente "
            f"a partilha entre UF origem e UF destino."
        ),
        register="E300",
        value=f"ANO={ano}",
    )]


# ──────────────────────────────────────────────
# DIFAL_010: Aliquota interestadual incompativel com origem do CST
# ──────────────────────────────────────────────

def _check_difal_010(
    record: SpedRecord,
    cfop: str,
    uf_declarante: str,
    uf_dest: str,
    loader=None,
) -> list[ValidationError]:
    """Aliquota interestadual incompativel com o digito de origem do CST.

    Resolucao Senado 13/2012:
    - Origens 1,2,3,8 (importados ou CI>40%) → aliquota 4%
    - Origens 4 (PPB), 6,7 (sem similar CAMEX) → seguem 7% ou 12% conforme UF
    - Origem 0,5 (nacionais normais) → seguem 7% ou 12% conforme UF

    Regra: se CST tem origem importada (1/2/3/8) e aliquota != 4%, erro.
    Se CST tem origem nacional/PPB/CAMEX (0/4/5/6/7) e aliquota = 4%, erro.
    """
    cst = get_field(record, "CST_ICMS")
    origem = cst_origem(cst)
    if not origem:
        return []  # CST sem 3 digitos — nao verificar

    t = trib(cst)
    if t not in _CST_COM_DIFAL:
        return []

    aliq = to_float(get_field(record, "ALIQ_ICMS"))
    if aliq <= 0:
        return []

    # Origem importada (1/2/3/8) deveria usar aliquota 4%
    if origem in _CST_ORIGEM_IMPORTADA_4PCT and abs(aliq - 4.0) > 0.01:
        aliq_esperada = _aliq_interestadual_esperada(uf_declarante, uf_dest, loader)
        # Se a aliquota nao e 4% e tambem nao e a esperada pela matriz UF,
        # pode ser que o CST de origem esteja errado ou a aliquota esteja errada
        return [make_error(
            record, "ALIQ_ICMS", "DIFAL_ALIQ_ORIGEM_INCOMPATIVEL",
            (
                f"CST {cst} indica origem importada (digito {origem}) — "
                f"aliquota interestadual esperada: 4% (Res. Senado 13/2012). "
                f"Encontrada: {aliq:.2f}%. "
                f"Verifique se a origem da mercadoria esta correta ou se "
                f"o produto se enquadra nas excecoes (PPB, sem similar CAMEX)."
            ),
            field_no=14,
            value=f"CST={cst} ALIQ={aliq:.2f}% CFOP={cfop}",
            expected_value="4.00",
        )]

    # Origem nacional/PPB/CAMEX (0/4/5/6/7) usando aliquota 4% indevidamente
    if origem not in _CST_ORIGEM_IMPORTADA_4PCT and abs(aliq - 4.0) < 0.01:
        return [make_error(
            record, "ALIQ_ICMS", "DIFAL_ALIQ_ORIGEM_INCOMPATIVEL",
            (
                f"CST {cst} indica origem nacional (digito {origem}), "
                f"mas aliquota interestadual e de 4% (exclusiva para importados). "
                f"Para mercadoria nacional, a aliquota interestadual deve ser "
                f"7% ou 12% conforme UF de origem/destino."
            ),
            field_no=14,
            value=f"CST={cst} ALIQ={aliq:.2f}% CFOP={cfop}",
        )]

    return []
