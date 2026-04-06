"""Regras de auditoria fiscal: cruzamentos avancados entre registros SPED.

Camada 4 do motor de validacao -- regras de auditoria que analisam padroes
cross-record para detectar erros de parametrizacao, inconsistencias operacionais,
indicios de irregularidade e riscos fiscais.
"""

from __future__ import annotations

from collections import defaultdict

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import ValidationContext
from .helpers import (
    CFOP_REMESSA_SAIDA,
    CFOP_RETORNO_ENTRADA,
    CFOP_VENDA,
    CST_ISENTO_NT,
    F_0000_UF,
    F_0150_COD_PART,
    F_0150_UF,
    F_C100_COD_PART,
    F_C170_CFOP,
    F_C170_COD_ITEM,
    F_C170_CST_ICMS,
    F_C170_CST_IPI,
    F_C170_VL_BC_ICMS,
    F_C170_VL_ICMS,
    F_C170_VL_IPI,
    F_C170_VL_ITEM,
    F_C190_CST,
    F_C190_VL_OPR,
    F_H010_COD_ITEM,
    get_field,
    make_error,
    make_generic_error,
    to_float,
    trib,
)

# ──────────────────────────────────────────────
# Constantes locais
# ──────────────────────────────────────────────

# Registros essenciais para auditoria
_REGISTROS_ESSENCIAIS = {"0150", "0200", "C100", "C170", "C190", "E110", "H010"}

# CSTs de IPI nao recuperaveis (isento, NT, imune, suspenso)
_CST_IPI_NAO_RECUPERAVEL = {"02", "03", "04", "05", "52", "53", "54", "55"}


# ──────────────────────────────────────────────
# Contexto de auditoria
# ──────────────────────────────────────────────

class _AuditContext:
    """Dados pre-processados para as regras de auditoria."""

    def __init__(self, groups: dict[str, list[SpedRecord]]) -> None:
        # UF do declarante
        self.uf_declarante = ""
        for r in groups.get("0000", []):
            self.uf_declarante = get_field(r, F_0000_UF)
            break

        # Mapa COD_PART -> UF
        self.part_uf: dict[str, str] = {}
        for r in groups.get("0150", []):
            cod = get_field(r, F_0150_COD_PART)
            uf = get_field(r, F_0150_UF)
            if cod and uf:
                self.part_uf[cod] = uf

        # Mapa C170 -> C100 pai (para obter COD_PART)
        self.c170_parent: dict[int, SpedRecord] = {}
        self._build_parent_map(groups)

        # Items com saida (CFOP 5/6/7xxx)
        self.items_saida: set[str] = set()
        # Items com entrada creditada (CFOP 1102/2102)
        self.items_entrada_credito: set[str] = set()
        # Remessas: COD_ITEM -> [records]
        self.remessas: dict[str, list[SpedRecord]] = defaultdict(list)
        # Retornos: set de COD_ITEMs
        self.retorno_items: set[str] = set()

        for r in groups.get("C170", []):
            cfop = get_field(r, F_C170_CFOP)
            cod_item = get_field(r, F_C170_COD_ITEM)
            if cfop and cfop[0] in ("5", "6", "7"):
                self.items_saida.add(cod_item)
            if cfop in ("1102", "2102"):
                self.items_entrada_credito.add(cod_item)
            if cfop in CFOP_REMESSA_SAIDA:
                self.remessas[cod_item].append(r)
            if cfop in CFOP_RETORNO_ENTRADA:
                self.retorno_items.add(cod_item)

        # Items no inventario H010
        self.items_inventario: set[str] = set()
        for r in groups.get("H010", []):
            cod = get_field(r, F_H010_COD_ITEM)
            if cod:
                self.items_inventario.add(cod)

        # Items em qualquer C170
        self.items_c170: set[str] = set()
        for r in groups.get("C170", []):
            cod = get_field(r, F_C170_COD_ITEM)
            if cod:
                self.items_c170.add(cod)

        # Registros presentes
        self.registros_presentes: set[str] = set(groups.keys())

    def _build_parent_map(self, groups: dict[str, list[SpedRecord]]) -> None:
        """Constroi mapa C170.line -> C100 pai pela ordem dos registros."""
        # Registros C100 e C170 intercalados -- C170 pertence ao ultimo C100
        all_c_records = []
        for reg_type in ("C100", "C170"):
            for r in groups.get(reg_type, []):
                all_c_records.append(r)
        all_c_records.sort(key=lambda r: r.line_number)

        current_c100: SpedRecord | None = None
        for r in all_c_records:
            if r.register == "C100":
                current_c100 = r
            elif r.register == "C170" and current_c100 is not None:
                self.c170_parent[r.line_number] = current_c100

    def get_c170_participant_uf(self, c170: SpedRecord) -> str:
        """Obtem UF do participante via C100 pai -> COD_PART -> 0150."""
        parent = self.c170_parent.get(c170.line_number)
        if not parent:
            return ""
        cod_part = get_field(parent, F_C100_COD_PART)
        return self.part_uf.get(cod_part, "")


# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def validate_audit_rules(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Executa regras de auditoria fiscal nos registros SPED.

    Regras implementadas:
    - Per-item: CFOP interestadual x UF, CST 051, IPI BC
    - Aggregate: volume isentos, remessa/retorno, inventario, parametrizacao,
                 credito uso/consumo, operacao especial, registros essenciais
    """
    groups = group_by_register(records)
    if not groups:
        return []

    ctx = _AuditContext(groups)
    errors: list[ValidationError] = []

    # -- Per-item (C170) --
    for rec in groups.get("C170", []):
        errors.extend(_check_cfop_interestadual_uf(rec, ctx))
        errors.extend(_check_cst051_debito(rec))
        errors.extend(_check_ipi_reflexo_bc(rec))

    # -- Aggregate --
    errors.extend(_check_volume_isento(groups))
    errors.extend(_check_remessa_sem_retorno(ctx))
    errors.extend(_check_inventario_sem_movimento(ctx))
    errors.extend(_check_parametrizacao_sistemica(groups))
    errors.extend(_check_credito_uso_consumo(ctx, groups))
    errors.extend(_check_registros_essenciais(ctx))

    return errors


# ──────────────────────────────────────────────
# Per-item rules
# ──────────────────────────────────────────────

def _check_cfop_interestadual_uf(
    record: SpedRecord, ctx: _AuditContext,
) -> list[ValidationError]:
    """AUD_CFOP_INTERESTADUAL_UF_INTERNA: CFOP 6xxx para mesmo estado."""
    cfop = get_field(record, F_C170_CFOP)
    if not cfop or cfop[0] != "6":
        return []
    if cfop in CFOP_REMESSA_SAIDA:
        return []

    uf_dest = ctx.get_c170_participant_uf(record)
    if not uf_dest or not ctx.uf_declarante:
        return []

    if uf_dest.upper() == ctx.uf_declarante.upper():
        return [make_error(
            record, "CFOP", "CFOP_INTERESTADUAL_DESTINO_INTERNO",
            (
                f"CFOP {cfop} indica operacao interestadual, mas o "
                f"destinatario e da mesma UF do declarante ({uf_dest}). "
                f"Verifique se a operacao e realmente interestadual ou se "
                f"o CFOP deveria ser da serie 5xxx (interna)."
            ),
            field_no=11,
            value=f"CFOP={cfop} UF_DEST={uf_dest} UF_DECL={ctx.uf_declarante}",
        )]
    return []


def _check_cst051_debito(record: SpedRecord) -> list[ValidationError]:
    """AUD_CST051_DEBITO_INDEVIDO: CST 051 gerando debito."""
    cst = get_field(record, F_C170_CST_ICMS)
    if not cst:
        return []
    t = trib(cst)
    if t != "51":
        return []

    vl_icms = to_float(get_field(record, F_C170_VL_ICMS))
    if vl_icms > 0:
        return [make_error(
            record, "VL_ICMS", "DIFERIMENTO_COM_DEBITO",
            (
                f"CST {cst} indica diferimento, mas VL_ICMS={vl_icms:.2f}. "
                f"No diferimento, o imposto e adiado e nao deve gerar debito "
                f"no periodo. Verifique se o diferimento e total ou parcial "
                f"e se o debito esta correto."
            ),
            field_no=15,
            value=f"CST={cst} VL_ICMS={vl_icms:.2f}",
        )]
    return []


def _check_ipi_reflexo_bc(record: SpedRecord) -> list[ValidationError]:
    """AUD_IPI_REFLEXO_CUSTO_BC: IPI nao recuperavel deve integrar BC ICMS."""
    cst_ipi = get_field(record, F_C170_CST_IPI)
    if not cst_ipi or cst_ipi not in _CST_IPI_NAO_RECUPERAVEL:
        return []

    vl_ipi = to_float(get_field(record, F_C170_VL_IPI))
    if vl_ipi <= 0:
        return []

    vl_item = to_float(get_field(record, F_C170_VL_ITEM))
    vl_bc_icms = to_float(get_field(record, F_C170_VL_BC_ICMS))

    # Se IPI nao recuperavel e BC nao inclui IPI, alerta
    if vl_bc_icms > 0 and vl_bc_icms < vl_item + vl_ipi - 0.02:
        return [make_error(
            record, "VL_BC_ICMS", "IPI_REFLEXO_INCORRETO",
            (
                f"IPI nao recuperavel (CST_IPI={cst_ipi}, VL_IPI={vl_ipi:.2f}) "
                f"parece nao estar incluido na BC do ICMS "
                f"(VL_BC={vl_bc_icms:.2f}, VL_ITEM={vl_item:.2f}). "
                f"Para contribuintes que nao recuperam IPI, o valor do IPI "
                f"deve integrar a base de calculo do ICMS."
            ),
            field_no=13,
            value=f"CST_IPI={cst_ipi} VL_IPI={vl_ipi:.2f} BC={vl_bc_icms:.2f}",
        )]
    return []


# ──────────────────────────────────────────────
# Aggregate rules
# ──────────────────────────────────────────────

def _check_volume_isento(
    groups: dict[str, list[SpedRecord]],
) -> list[ValidationError]:
    """AUD_CST_VOLUME_ISENTO_ATIPICO: >50% de operacoes isentas/NT."""
    total_opr = 0.0
    isento_opr = 0.0

    for r in groups.get("C190", []):
        vl_opr = to_float(get_field(r, F_C190_VL_OPR))
        cst = get_field(r, F_C190_CST)
        total_opr += vl_opr
        if trib(cst) in CST_ISENTO_NT:
            isento_opr += vl_opr

    if total_opr <= 0:
        return []

    pct = isento_opr / total_opr * 100
    if pct > 50:
        return [make_generic_error(
            "VOLUME_ISENTO_ATIPICO",
            (
                f"O volume de operacoes com CST isento/NT/suspenso/ST "
                f"representa {pct:.1f}% do total (R$ {isento_opr:,.2f} de "
                f"R$ {total_opr:,.2f}). Percentual acima de 50% e atipico "
                f"e merece revisao da classificacao fiscal dos itens."
            ),
            register="C190",
            value=f"{pct:.1f}% isento/NT",
        )]
    return []


def _check_remessa_sem_retorno(ctx: _AuditContext) -> list[ValidationError]:
    """AUD_REMESSA_SEM_RETORNO: remessa sem retorno no periodo."""
    errors: list[ValidationError] = []

    for cod_item, recs in ctx.remessas.items():
        if cod_item not in ctx.retorno_items:
            first = recs[0]
            cfop = get_field(first, F_C170_CFOP)
            errors.append(make_error(
                first, "CFOP", "REMESSA_SEM_RETORNO",
                (
                    f"Item {cod_item} com remessa (CFOP {cfop}) sem retorno "
                    f"correspondente no periodo. Verifique se o retorno "
                    f"ocorreu, se esta em periodo posterior, ou se a "
                    f"operacao deveria ser classificada como venda."
                ),
                field_no=11,
                value=f"COD_ITEM={cod_item} CFOP={cfop}",
            ))

    return errors


def _check_inventario_sem_movimento(ctx: _AuditContext) -> list[ValidationError]:
    """AUD_INVENTARIO_ITEM_SEM_MOVIMENTO: item no H010 sem C170."""
    errors: list[ValidationError] = []

    sem_movimento = ctx.items_inventario - ctx.items_c170
    if len(sem_movimento) > 20:
        # Muitos itens -- emitir alerta consolidado
        return [make_generic_error(
            "INVENTARIO_ITEM_PARADO",
            (
                f"{len(sem_movimento)} itens no inventario (H010) nao "
                f"possuem nenhum movimento (C170) no periodo. Exemplos: "
                f"{', '.join(sorted(sem_movimento)[:5])}. Itens sem "
                f"movimentacao podem indicar estoque obsoleto."
            ),
            register="H010",
            value=f"{len(sem_movimento)} itens",
        )]

    for cod_item in sorted(sem_movimento):
        errors.append(make_generic_error(
            "INVENTARIO_ITEM_PARADO",
            (
                f"Item {cod_item} consta no inventario (H010) mas nao "
                f"possui nenhum movimento (C170) no periodo."
            ),
            register="H010",
            value=f"COD_ITEM={cod_item}",
        ))

    return errors


def _check_parametrizacao_sistemica(
    groups: dict[str, list[SpedRecord]],
) -> list[ValidationError]:
    """AUD_PARAMETRIZACAO_SISTEMICA: mesmo item com CST incompativel repetidamente."""
    errors: list[ValidationError] = []

    # Agrupar C170 por COD_ITEM
    item_records: dict[str, list[SpedRecord]] = defaultdict(list)
    for r in groups.get("C170", []):
        cod = get_field(r, F_C170_COD_ITEM)
        if cod:
            item_records[cod].append(r)

    for cod_item, recs in item_records.items():
        if len(recs) < 3:
            continue

        # Contar ocorrencias de CST incompativel com CFOP
        incomp_count = 0
        for r in recs:
            cfop = get_field(r, F_C170_CFOP)
            cst = get_field(r, F_C170_CST_ICMS)
            if not cfop or not cst:
                continue
            t = trib(cst)
            # Venda + isento = incompativel
            if cfop in CFOP_VENDA and t in CST_ISENTO_NT:
                incomp_count += 1

        ratio = incomp_count / len(recs)
        if ratio >= 0.8 and incomp_count >= 3:
            sample = recs[0]
            errors.append(make_error(
                sample, "CST_ICMS", "PARAMETRIZACAO_SISTEMICA_INCORRETA",
                (
                    f"Item {cod_item} apresenta CST incompativel com CFOP "
                    f"em {incomp_count} de {len(recs)} ocorrencias ({ratio:.0%}). "
                    f"Isso indica erro sistemico de parametrizacao no ERP. "
                    f"Revise o cadastro fiscal deste produto."
                ),
                field_no=10,
                value=f"COD_ITEM={cod_item} {incomp_count}/{len(recs)}",
            ))

    return errors


def _check_credito_uso_consumo(
    ctx: _AuditContext,
    groups: dict[str, list[SpedRecord]],
) -> list[ValidationError]:
    """AUD_CREDITO_ENTRADA_USO_CONSUMO: compra para revenda nunca vendida."""
    errors: list[ValidationError] = []

    # Itens com entrada para comercializacao mas sem saida
    suspeitos = ctx.items_entrada_credito - ctx.items_saida
    # Excluir itens no inventario (podem ser estoque legitimo)
    suspeitos = suspeitos - ctx.items_inventario

    if not suspeitos:
        return errors

    # Encontrar primeiro registro de cada item para vincular o erro
    item_first_rec: dict[str, SpedRecord] = {}
    for r in groups.get("C170", []):
        cod = get_field(r, F_C170_COD_ITEM)
        cfop = get_field(r, F_C170_CFOP)
        if cod in suspeitos and cfop in ("1102", "2102") and cod not in item_first_rec:
            item_first_rec[cod] = r

    for cod_item, rec in item_first_rec.items():
        errors.append(make_error(
            rec, "CFOP", "CREDITO_USO_CONSUMO_INDEVIDO",
            (
                f"Item {cod_item} escriturado como compra para "
                f"comercializacao (CFOP {get_field(rec, F_C170_CFOP)}) mas nao "
                f"possui nenhuma saida no periodo e nao consta no "
                f"inventario. Pode ser material de uso/consumo com "
                f"credito indevido de ICMS."
            ),
            field_no=11,
            value=f"COD_ITEM={cod_item}",
        ))

    return errors


def _check_registros_essenciais(ctx: _AuditContext) -> list[ValidationError]:
    """AUD_REGISTROS_ESSENCIAIS_AUSENTES: registros criticos faltando."""
    ausentes = _REGISTROS_ESSENCIAIS - ctx.registros_presentes

    if not ausentes:
        return []

    return [make_generic_error(
        "REGISTROS_ESSENCIAIS_AUSENTES",
        (
            f"O arquivo SPED nao contem os registros: "
            f"{', '.join(sorted(ausentes))}. A ausencia desses registros "
            f"compromete a capacidade de auditoria fiscal."
        ),
        register="SPED",
        value=f"Ausentes: {', '.join(sorted(ausentes))}",
    )]
