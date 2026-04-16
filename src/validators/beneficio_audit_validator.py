"""Regras de auditoria fiscal para beneficios e ajustes E111 do SPED EFD.

Camada de auditoria especializada na analise de beneficios fiscais,
creditos presumidos, ajustes de apuracao (E111/E112/E113) e sua
consistencia com os documentos fiscais (C170/C190) e apuracao (E110).
"""

from __future__ import annotations

from collections import defaultdict

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import ValidationContext
from .helpers import (
    ALIQ_INTERESTADUAIS,
    CFOP_DEVOLUCAO,
    CFOP_REMESSA_SAIDA,
    CST_ISENTO_NT,
    CST_ST,
    CST_TRIBUTADO,
    F_0000_UF,
    F_0150_COD_PART,
    F_0150_UF,
    F_0200_COD_ITEM,
    F_C100_COD_PART,
    F_C100_IND_OPER,
    F_C100_VL_ICMS_ST,
    F_C170_ALIQ_ICMS,
    F_C170_CFOP,
    F_C170_COD_ITEM,
    F_C170_CST_COFINS,
    F_C170_CST_ICMS,
    F_C170_CST_PIS,
    F_C170_VL_ICMS,
    F_C190_ALIQ,
    F_C190_CFOP,
    F_C190_CST,
    F_C190_VL_BC,
    F_C190_VL_ICMS,
    F_C190_VL_OPR,
    F_E110_VL_AJ_CREDITOS,
    F_E110_VL_AJ_DEBITOS,
    F_E110_VL_ESTORNOS_CRED,
    F_E110_VL_ESTORNOS_DEB,
    F_E110_VL_SLD_CREDOR_TRANSPORTAR,
    F_E110_VL_TOT_AJ_CREDITOS,
    F_E110_VL_TOT_AJ_DEBITOS,
    F_E110_VL_TOT_CREDITOS,
    F_E110_VL_TOT_DEBITOS,
    F_E110_VL_TOT_DED,
    F_E111_COD_AJ_APUR,
    F_E111_DESCR_COMPL,
    F_E111_VL_AJ_APUR,
    F_H010_COD_ITEM,
    F_H010_QTD,
    F_H010_VL_ITEM,
    get_field,
    make_error,
    make_generic_error,
    to_float,
    trib,
)
from .tolerance import get_tolerance

# ──────────────────────────────────────────────
# Posicoes de campo locais (nao presentes em helpers)
# ──────────────────────────────────────────────

_C100_COD_SIT = 5

_E112_NUM_DA = 1
_E112_NUM_PROC = 2
_E112_TXT_COMPL = 5

_E113_COD_PART = 1
_E113_CHV_DOC = 9

_E200_UF = 1
_E200_DT_INI = 2

_E210_IND_MOV_ST = 1
_E210_VL_SLD_APURADO_ST = "VL_SLD_DEV_ANT_ST"

_H005_DT_INV = 1
_H005_VL_INV = 2

# ──────────────────────────────────────────────
# Constantes locais
# ──────────────────────────────────────────────

_CFOP_CANCELAMENTO = {
    "5201", "5202", "5411", "5412",
    "6201", "6202", "6411", "6412",
}

_UFS_VALIDAS = {
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA",
    "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN",
    "RO", "RR", "RS", "SC", "SE", "SP", "TO",
}

_REGISTROS_AUDITORIA = {"0150", "0200", "C170", "C190", "E110", "E111", "H010"}

# CSTs PIS/COFINS tributados
_CST_PIS_COFINS_TRIBUTADO = {"01", "02", "03", "05"}
_CST_PIS_COFINS_ISENTO = {"04", "05", "06", "07", "08", "09", "49"}


# ──────────────────────────────────────────────
# Estrutura E111 com filhos
# ──────────────────────────────────────────────

class _E111Agrupado:
    """Um registro E111 com seus filhos E112 e E113."""

    def __init__(self, record: SpedRecord) -> None:
        self.record = record
        self.cod_aj = get_field(record, F_E111_COD_AJ_APUR)
        self.descr = get_field(record, F_E111_DESCR_COMPL)
        self.valor = to_float(get_field(record, F_E111_VL_AJ_APUR))
        self.filhos_e112: list[SpedRecord] = []
        self.filhos_e113: list[SpedRecord] = []

    @property
    def tem_lastro(self) -> bool:
        return len(self.filhos_e112) > 0 or len(self.filhos_e113) > 0

    @property
    def natureza(self) -> str:
        """Natureza do ajuste conforme posicao [3] do COD_AJ_APUR.

        Formato COD_AJ_APUR: UUTNNnnn
        [0-1]=UF, [2]=Tipo (0=ICMS proprio), [3]=Natureza:
        0=Outros debitos        -> E110.VL_TOT_AJ_DEBITOS
        1=Estorno de creditos   -> E110.VL_ESTORNOS_CRED
        2=Outros creditos       -> E110.VL_TOT_AJ_CREDITOS
        3=Estorno de debitos    -> E110.VL_ESTORNOS_DEB
        4=Deducoes              -> E110.VL_TOT_DED
        """
        if len(self.cod_aj) >= 4:
            return self.cod_aj[3]
        return ""

    @property
    def eh_credito(self) -> bool:
        """Natureza indica outros creditos (pos[3]=2)."""
        return self.natureza == "2"

    @property
    def eh_debito(self) -> bool:
        """Natureza indica outros debitos (pos[3]=0)."""
        return self.natureza == "0"

    @property
    def eh_estorno_debito(self) -> bool:
        """Natureza indica estorno de debito (pos[3]=3)."""
        return self.natureza == "3"

    @property
    def eh_estorno_credito(self) -> bool:
        """Natureza indica estorno de credito (pos[3]=1)."""
        return self.natureza == "1"

    @property
    def eh_deducao(self) -> bool:
        """Natureza indica deducao (pos[3]=4)."""
        return self.natureza == "4"

    @property
    def eh_codigo_generico(self) -> bool:
        return self.cod_aj.endswith("999") or self.cod_aj.endswith("000")

    @property
    def eh_credito_presumido(self) -> bool:
        """Credito presumido: natureza credito + descricao confirma presumido/outorgado."""
        if not self.eh_credito:
            return False
        descr_lower = (self.descr or "").lower()
        return any(kw in descr_lower for kw in ("presumido", "outorgado"))


# ──────────────────────────────────────────────
# Contexto de auditoria de beneficios
# ──────────────────────────────────────────────

class _BeneficioContext:
    """Dados pre-processados para as regras de auditoria de beneficios."""

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

        # Items cadastrados em 0200
        self.items_0200: set[str] = set()
        for r in groups.get("0200", []):
            cod = get_field(r, F_0200_COD_ITEM)
            if cod:
                self.items_0200.add(cod)

        # E111 com filhos E112/E113
        self.e111_list: list[_E111Agrupado] = []
        self._build_e111_hierarchy(groups)

        # E110 totais
        self.e110_vl_tot_debitos = 0.0
        self.e110_vl_aj_debitos = 0.0
        self.e110_vl_tot_aj_debitos = 0.0
        self.e110_vl_estornos_cred = 0.0
        self.e110_vl_tot_creditos = 0.0
        self.e110_vl_aj_creditos = 0.0
        self.e110_vl_tot_aj_creditos = 0.0
        self.e110_vl_estornos_deb = 0.0
        self.e110_vl_tot_ded = 0.0
        self.e110_vl_sld_credor = 0.0
        self.e110_presente = False
        for r in groups.get("E110", []):
            self.e110_presente = True
            self.e110_vl_tot_debitos = to_float(get_field(r, F_E110_VL_TOT_DEBITOS))
            self.e110_vl_aj_debitos = to_float(get_field(r, F_E110_VL_AJ_DEBITOS))
            self.e110_vl_tot_aj_debitos = to_float(get_field(r, F_E110_VL_TOT_AJ_DEBITOS))
            self.e110_vl_estornos_cred = to_float(get_field(r, F_E110_VL_ESTORNOS_CRED))
            self.e110_vl_tot_creditos = to_float(get_field(r, F_E110_VL_TOT_CREDITOS))
            self.e110_vl_aj_creditos = to_float(get_field(r, F_E110_VL_AJ_CREDITOS))
            self.e110_vl_tot_aj_creditos = to_float(get_field(r, F_E110_VL_TOT_AJ_CREDITOS))
            self.e110_vl_estornos_deb = to_float(get_field(r, F_E110_VL_ESTORNOS_DEB))
            self.e110_vl_tot_ded = to_float(get_field(r, F_E110_VL_TOT_DED))
            self.e110_vl_sld_credor = to_float(get_field(r, F_E110_VL_SLD_CREDOR_TRANSPORTAR))
            break

        # C190 totais por perfil
        self.c190_icms_saida_tributado = 0.0
        self.c190_icms_interestadual = 0.0
        self.c190_icms_interno = 0.0
        self.c190_vl_opr_total = 0.0
        self.c190_vl_opr_interno = 0.0
        self.c190_vl_opr_interestadual = 0.0
        self.c190_vl_opr_isento_nt = 0.0
        self.c190_vl_opr_devolucao = 0.0
        self.c190_vl_opr_remessa = 0.0
        self.c190_records = groups.get("C190", [])
        self._build_c190_totals()

        # C170 com mapa pai C100
        self.c170_parent: dict[int, SpedRecord] = {}
        self._build_c170_parent_map(groups)

        # Distribuicao CST em C170
        self.cst_counts: dict[str, int] = defaultdict(int)
        self.c170_cst020_items: set[str] = set()
        for r in groups.get("C170", []):
            cst = get_field(r, F_C170_CST_ICMS)
            if cst:
                self.cst_counts[trib(cst)] += 1
            if trib(cst) == "20":
                self.c170_cst020_items.add(get_field(r, F_C170_COD_ITEM))

        # E210 (ST)
        self.e210_presente = False
        self.e210_vl_sld_st = 0.0
        for r in groups.get("E210", []):
            self.e210_presente = True
            self.e210_vl_sld_st = to_float(get_field(r, _E210_VL_SLD_APURADO_ST))
            break

        # Registros presentes
        self.registros_presentes: set[str] = set(groups.keys())

        # Groups referencia
        self.groups = groups

    def _build_e111_hierarchy(self, groups: dict[str, list[SpedRecord]]) -> None:
        """Constroi E111 com filhos E112/E113 por ordem sequencial."""
        all_e_records: list[SpedRecord] = []
        for reg_type in ("E111", "E112", "E113"):
            for r in groups.get(reg_type, []):
                all_e_records.append(r)
        all_e_records.sort(key=lambda r: r.line_number)

        current_e111: _E111Agrupado | None = None
        for r in all_e_records:
            if r.register == "E111":
                current_e111 = _E111Agrupado(r)
                self.e111_list.append(current_e111)
            elif r.register == "E112" and current_e111 is not None:
                current_e111.filhos_e112.append(r)
            elif r.register == "E113" and current_e111 is not None:
                current_e111.filhos_e113.append(r)

    def _build_c190_totals(self) -> None:
        """Pre-calcula totais C190 por perfil de CFOP."""
        for r in self.c190_records:
            cfop = get_field(r, F_C190_CFOP)
            cst = get_field(r, F_C190_CST)
            vl_opr = to_float(get_field(r, F_C190_VL_OPR))
            vl_icms = to_float(get_field(r, F_C190_VL_ICMS))

            if not cfop:
                continue

            self.c190_vl_opr_total += vl_opr

            # Saidas tributadas
            if cfop[0] in ("5", "6", "7") and trib(cst) in CST_TRIBUTADO:
                self.c190_icms_saida_tributado += vl_icms

            # Interestadual (6xxx)
            if cfop[0] == "6" and cfop not in CFOP_REMESSA_SAIDA:
                self.c190_vl_opr_interestadual += vl_opr
                if trib(cst) in CST_TRIBUTADO:
                    self.c190_icms_interestadual += vl_icms

            # Interno (5xxx)
            if cfop[0] == "5" and cfop not in CFOP_REMESSA_SAIDA:
                self.c190_vl_opr_interno += vl_opr
                if trib(cst) in CST_TRIBUTADO:
                    self.c190_icms_interno += vl_icms

            # Isento/NT
            if trib(cst) in CST_ISENTO_NT:
                self.c190_vl_opr_isento_nt += vl_opr

            # Devolucao
            if cfop in CFOP_DEVOLUCAO:
                self.c190_vl_opr_devolucao += vl_opr

            # Remessa
            if cfop in CFOP_REMESSA_SAIDA:
                self.c190_vl_opr_remessa += vl_opr

    def _build_c170_parent_map(self, groups: dict[str, list[SpedRecord]]) -> None:
        """Constroi mapa C170.line -> C100 pai pela ordem dos registros."""
        all_c_records: list[SpedRecord] = []
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

    @property
    def total_e111_ajustes(self) -> float:
        return sum(e.valor for e in self.e111_list)

    @property
    def total_e111_creditos(self) -> float:
        """Natureza 2: outros creditos -> E110.VL_TOT_AJ_CREDITOS."""
        return sum(e.valor for e in self.e111_list if e.eh_credito)

    @property
    def total_e111_debitos(self) -> float:
        """Natureza 0: outros debitos -> E110.VL_TOT_AJ_DEBITOS."""
        return sum(e.valor for e in self.e111_list if e.eh_debito)

    @property
    def total_e111_estornos_deb(self) -> float:
        """Natureza 3: estorno de debitos -> E110.VL_ESTORNOS_DEB."""
        return sum(e.valor for e in self.e111_list if e.eh_estorno_debito)

    @property
    def total_e111_estornos_cred(self) -> float:
        """Natureza 1: estorno de creditos -> E110.VL_ESTORNOS_CRED."""
        return sum(e.valor for e in self.e111_list if e.eh_estorno_credito)

    @property
    def total_e111_deducoes(self) -> float:
        """Natureza 4: deducoes -> E110.VL_TOT_DED."""
        return sum(e.valor for e in self.e111_list if e.eh_deducao)

    @property
    def tem_credito_presumido(self) -> bool:
        return any(e.eh_credito_presumido for e in self.e111_list)


# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def validate_beneficio_audit(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Executa regras de auditoria de beneficios fiscais nos registros SPED.

    Regras implementadas (27):
    - Consistencia E111/E112/E113 com documentos e apuracao
    - Cruzamentos C190 x E110 x E111
    - Analise de perfil operacional vs beneficio
    - Sobreposicao de institutos tributarios
    - Meta-regras de classificacao e escopo
    """
    groups = group_by_register(records)
    if not groups:
        return []

    ctx = _BeneficioContext(groups)
    errors: list[ValidationError] = []

    # ── Regras E111 ──
    errors.extend(_check_debito_integral(ctx))
    errors.extend(_check_e111_sem_rastreabilidade(ctx))
    errors.extend(_check_e111_soma_vs_e110(ctx))
    errors.extend(_check_devolucao_sem_reversao(ctx))
    errors.extend(_check_saldo_credor_recorrente(ctx))
    errors.extend(_check_sobreposicao_beneficios(ctx))
    errors.extend(_check_beneficio_desproporcional(ctx))
    errors.extend(_check_st_apuracao(ctx))
    errors.extend(_check_e111_codigo_generico(ctx))
    errors.extend(_check_xml_sped_divergencia(ctx))
    errors.extend(_check_checklist_auditoria(ctx))
    errors.extend(_check_trilha_beneficio_incompleta(ctx))
    errors.extend(_check_icms_efetivo_sem_trilha(ctx))
    errors.extend(_check_beneficio_fora_escopo(ctx))
    errors.extend(_check_diagnostico_causa_raiz(ctx))
    errors.extend(_check_c190_mistura_cst(ctx))
    errors.extend(_check_inventario_reflexo(ctx))
    errors.extend(_check_beneficio_sem_governanca(ctx))
    errors.extend(_check_totalizacao_beneficiada(ctx))
    errors.extend(_check_perfil_operacional_beneficio(ctx))
    errors.extend(_check_beneficio_parametrizacao_errada(ctx))
    errors.extend(_check_destinatario_segregacao(ctx))
    errors.extend(_check_base_beneficio_inflada(ctx))
    errors.extend(_check_sped_vs_contribuicoes(ctx))
    errors.extend(_check_codigo_ajuste_incompativel(ctx))
    errors.extend(_check_trilha_beneficio_ausente(ctx))

    # ── Meta-regras (dependem dos erros anteriores) ──
    errors.extend(_check_classificacao_erro(errors))
    errors.extend(_check_escopo_apenas_sped(errors))
    errors.extend(_check_grau_confianca(errors))
    errors.extend(_check_amostragem_materialidade(errors, ctx))

    return errors


# ──────────────────────────────────────────────
# Regra 1: AUD_COMPETE_DEBITO_INTEGRAL
# ──────────────────────────────────────────────

def _check_debito_integral(ctx: _BeneficioContext) -> list[ValidationError]:
    """C190 VL_ICMS saida tributada vs E110 VL_TOT_DEBITOS."""
    if not ctx.e110_presente or ctx.c190_icms_saida_tributado <= 0:
        return []

    diff = abs(ctx.c190_icms_saida_tributado - ctx.e110_vl_tot_debitos)
    if diff <= get_tolerance("apuracao_e110"):
        return []

    # Verifica se ha ajuste E111 que justifique a diferenca
    if ctx.e111_list:
        return []

    return [make_generic_error(
        "BENEFICIO_DEBITO_NAO_INTEGRAL",
        (
            f"Soma do ICMS tributado em saidas (C190) = R$ {ctx.c190_icms_saida_tributado:,.2f} "
            f"diverge de E110.VL_TOT_DEBITOS = R$ {ctx.e110_vl_tot_debitos:,.2f} "
            f"(diferenca: R$ {diff:,.2f}) sem ajuste E111 que justifique a "
            f"divergencia. Verifique se todos os debitos estao sendo integralizados."
        ),
        register="E110",
        value=f"C190={ctx.c190_icms_saida_tributado:,.2f} E110={ctx.e110_vl_tot_debitos:,.2f}",
    )]


# ──────────────────────────────────────────────
# Regra 2/16: AUD_E111_SEM_RASTREABILIDADE / AUD_AJUSTE_SEM_LASTRO
# ──────────────────────────────────────────────

def _check_e111_sem_rastreabilidade(ctx: _BeneficioContext) -> list[ValidationError]:
    """E111 com valor > 1000 sem E112/E113."""
    errors: list[ValidationError] = []
    materialidade = 1000.0

    for e in ctx.e111_list:
        if e.valor > materialidade and not e.tem_lastro:
            errors.append(make_error(
                e.record, "VL_AJ_APUR", "AJUSTE_SEM_LASTRO_DOCUMENTAL",
                (
                    f"Ajuste E111 (COD={e.cod_aj}) com valor R$ {e.valor:,.2f} "
                    f"nao possui registros E112 ou E113 vinculados. Ajustes "
                    f"de apuracao devem ter lastro documental para fins de "
                    f"auditoria e comprovacao fiscal."
                ),
                field_no=3,
                value=f"COD={e.cod_aj} VL={e.valor:,.2f}",
            ))

    return errors


# ──────────────────────────────────────────────
# Regra 3: AUD_E111_SOMA_VS_E110
# ──────────────────────────────────────────────

def _check_e111_soma_vs_e110(ctx: _BeneficioContext) -> list[ValidationError]:
    """Soma E111 por natureza vs campo correspondente do E110.

    COD_AJ_APUR posicao [3] define a natureza:
    0 = Outros debitos        -> E110.VL_TOT_AJ_DEBITOS
    1 = Estorno de creditos   -> E110.VL_ESTORNOS_CRED
    2 = Outros creditos       -> E110.VL_TOT_AJ_CREDITOS
    3 = Estorno de debitos    -> E110.VL_ESTORNOS_DEB
    4 = Deducoes              -> E110.VL_TOT_DED
    """
    if not ctx.e110_presente or not ctx.e111_list:
        return []

    errors: list[ValidationError] = []

    # Comparacoes por natureza: (soma_e111, campo_e110, label)
    # E111 natureza 0 -> E110.VL_TOT_AJ_DEBITOS (idx 3)
    # E111 natureza 1 -> E110.VL_ESTORNOS_CRED  (idx 4)
    # E111 natureza 2 -> E110.VL_TOT_AJ_CREDITOS (idx 7)
    # E111 natureza 3 -> E110.VL_ESTORNOS_DEB   (idx 8)
    # E111 natureza 4 -> E110.VL_TOT_DED         (idx 11)
    # NB: VL_AJ_DEBITOS/VL_AJ_CREDITOS sao ajustes de documento (C197/D197)
    checks = [
        (ctx.total_e111_debitos, ctx.e110_vl_tot_aj_debitos,
         "outros debitos", "VL_TOT_AJ_DEBITOS"),
        (ctx.total_e111_creditos, ctx.e110_vl_tot_aj_creditos,
         "outros creditos", "VL_TOT_AJ_CREDITOS"),
        (ctx.total_e111_estornos_deb, ctx.e110_vl_estornos_deb,
         "estornos de debito", "VL_ESTORNOS_DEB"),
        (ctx.total_e111_estornos_cred, ctx.e110_vl_estornos_cred,
         "estornos de credito", "VL_ESTORNOS_CRED"),
        (ctx.total_e111_deducoes, ctx.e110_vl_tot_ded,
         "deducoes", "VL_TOT_DED"),
    ]

    for soma_e111, campo_e110, label, campo_nome in checks:
        if soma_e111 > 0 or campo_e110 > 0:
            diff = abs(soma_e111 - campo_e110)
            if diff > get_tolerance("apuracao_e110"):
                errors.append(make_generic_error(
                    "AJUSTE_SOMA_DIVERGENTE",
                    (
                        f"Soma dos ajustes E111 de {label} = R$ {soma_e111:,.2f} "
                        f"diverge de E110.{campo_nome} = R$ {campo_e110:,.2f} "
                        f"(diferenca: R$ {diff:,.2f})."
                    ),
                    register="E111",
                    value=f"E111={soma_e111:,.2f} E110.{campo_nome}={campo_e110:,.2f}",
                ))

    return errors


# ──────────────────────────────────────────────
# Regra 4: AUD_DEVOLUCAO_SEM_REVERSAO_BENEFICIO
# ──────────────────────────────────────────────

def _check_devolucao_sem_reversao(ctx: _BeneficioContext) -> list[ValidationError]:
    """Devolucoes significativas sem reversao proporcional no E111."""
    if not ctx.e111_list or ctx.c190_vl_opr_devolucao <= 0:
        return []

    total_ajuste = ctx.total_e111_ajustes
    if total_ajuste <= 0:
        return []

    pct_devolucao = ctx.c190_vl_opr_devolucao / (ctx.c190_vl_opr_total or 1) * 100
    if pct_devolucao <= 5:
        return []

    return [make_generic_error(
        "DEVOLUCAO_BENEFICIO_NAO_REVERTIDO",
        (
            f"Devolucoes representam {pct_devolucao:.1f}% das operacoes "
            f"(R$ {ctx.c190_vl_opr_devolucao:,.2f}), mas os ajustes E111 "
            f"totalizam R$ {total_ajuste:,.2f} sem reversao proporcional "
            f"visivel. Verifique se os beneficios fiscais foram corretamente "
            f"revertidos nas devolucoes conforme legislacao aplicavel."
        ),
        register="E111",
        value=f"DEV={ctx.c190_vl_opr_devolucao:,.2f} AJ={total_ajuste:,.2f}",
    )]


# ──────────────────────────────────────────────
# Regra 5: AUD_SALDO_CREDOR_RECORRENTE
# ──────────────────────────────────────────────

def _check_saldo_credor_recorrente(ctx: _BeneficioContext) -> list[ValidationError]:
    """Saldo credor com saidas tributadas — warning."""
    if ctx.e110_vl_sld_credor <= 0:
        return []

    saidas_tributadas = ctx.c190_icms_saida_tributado
    if saidas_tributadas <= 0:
        return []

    return [make_generic_error(
        "SALDO_CREDOR_RECORRENTE",
        (
            f"E110 apresenta saldo credor a transportar de R$ {ctx.e110_vl_sld_credor:,.2f} "
            f"mesmo com saidas tributadas de R$ {saidas_tributadas:,.2f}. "
            f"Saldo credor persistente com operacoes tributadas pode indicar "
            f"acumulo indevido de creditos ou excesso de beneficios."
        ),
        register="E110",
        value=f"SLD_CRED={ctx.e110_vl_sld_credor:,.2f} SAIDAS={saidas_tributadas:,.2f}",
    )]


# ──────────────────────────────────────────────
# Regra 6/23: AUD_SOBREPOSICAO_BENEFICIOS / AUD_MISTURA_INSTITUTOS
# ──────────────────────────────────────────────

def _check_sobreposicao_beneficios(ctx: _BeneficioContext) -> list[ValidationError]:
    """CST 020 (base reduzida) + E111 credito presumido = sobreposicao."""
    if not ctx.c170_cst020_items or not ctx.tem_credito_presumido:
        return []

    errors: list[ValidationError] = []

    errors.append(make_generic_error(
        "SOBREPOSICAO_BENEFICIOS",
        (
            f"Detectada potencial sobreposicao de beneficios: "
            f"{len(ctx.c170_cst020_items)} itens com CST 020 (base reduzida) "
            f"no C170 e ajustes de credito presumido no E111. "
            f"A cumulacao de reducao de base com credito presumido "
            f"pode configurar duplo beneficio indevido."
        ),
        register="C170",
        value=f"CST020={len(ctx.c170_cst020_items)} itens",
    ))

    # Regra 23: MISTURA_INSTITUTOS (mesma logica, error_type distinto)
    errors.append(make_generic_error(
        "MISTURA_INSTITUTOS_TRIBUTARIOS",
        (
            "Itens com base de calculo reduzida (CST 020) coexistem com "
            "ajustes de credito presumido (E111). A mistura de institutos "
            "tributarios distintos requer validacao da legislacao aplicavel "
            "para confirmar se a cumulacao e permitida."
        ),
        register="E111",
        value=f"CST020={len(ctx.c170_cst020_items)} + CRED_PRESUMIDO",
    ))

    return errors


# ──────────────────────────────────────────────
# Regra 7: AUD_BENEFICIO_DESPROPORCIONAL
# ──────────────────────────────────────────────

def _check_beneficio_desproporcional(ctx: _BeneficioContext) -> list[ValidationError]:
    """E111 creditos (natureza 2) > ICMS interestadual tributado."""
    if not ctx.e111_list or ctx.c190_icms_interestadual <= 0:
        return []

    # Apenas E111 de natureza 2 (outros creditos) sao beneficios.
    # Estornos de credito (natureza 1) sao debitos na apuracao, nao beneficios.
    total_creditos = ctx.total_e111_creditos
    if total_creditos <= 0 or total_creditos <= ctx.c190_icms_interestadual:
        return []

    return [make_generic_error(
        "BENEFICIO_VALOR_DESPROPORCIONAL",
        (
            f"Soma dos ajustes E111 de credito (R$ {total_creditos:,.2f}) excede o ICMS "
            f"total das operacoes interestaduais tributadas (R$ {ctx.c190_icms_interestadual:,.2f}). "
            f"O valor do beneficio nao pode ultrapassar o imposto devido "
            f"nas operacoes elegiveis."
        ),
        register="E111",
        value=f"AJ={total_creditos:,.2f} ICMS_INTER={ctx.c190_icms_interestadual:,.2f}",
    )]


# ──────────────────────────────────────────────
# Regra 8/17: AUD_ST_NOTA_OK_APURACAO_ERRADA / AUD_ST_APURACAO_DIVERGE
# ──────────────────────────────────────────────

def _check_st_apuracao(ctx: _BeneficioContext) -> list[ValidationError]:
    """Verifica consistencia entre ICMS-ST nos documentos e apuracao E210.

    Hierarquia de fontes para soma de ICMS-ST nos documentos:
      1) C170.VL_ICMS_ST (itens) — mais granular, preferido
      2) C100.VL_ICMS_ST (totalizador do documento) — fallback quando C170 ausente
      3) C190.VL_ICMS_ST (resumo CST/CFOP) — fallback final

    O E210 pode conter valores que nao vem apenas dos documentos:
      - VL_SLD_CRED_ANT_ST (saldo credor anterior)
      - VL_DEVOL_ST (devolucoes)
      - VL_RESSARC_ST (ressarcimentos)
      - VL_OUT_CRED_ST / VL_AJ_CREDITOS_ST (ajustes via E220)
      - VL_OUT_DEB_ST / VL_AJ_DEBITOS_ST (ajustes via E220)
      - VL_DEDUCOES_ST / DEB_ESP_ST

    Por isso, comparamos com VL_RETENCAO_ST (debito de ST gerado pelas
    retencoes nos documentos), que e a parcela que deve bater com os docs.
    """
    if not ctx.e210_presente:
        return []

    # ── Coletar todos os E210 por UF (via E200 pai) ──
    e210_por_uf: list[tuple[SpedRecord, str, float]] = []
    e200_uf_map: dict[int, str] = {}
    for r in ctx.groups.get("E200", []):
        uf = get_field(r, "UF")
        e200_uf_map[r.line_number] = uf

    for r in ctx.groups.get("E210", []):
        # Encontrar E200 pai (linha imediatamente anterior)
        uf = ""
        for e200_line in sorted(e200_uf_map.keys(), reverse=True):
            if e200_line < r.line_number:
                uf = e200_uf_map[e200_line]
                break
        vl_retencao = to_float(get_field(r, "VL_RETENCAO_ST"))
        if vl_retencao > 0:
            e210_por_uf.append((r, uf, vl_retencao))

    if not e210_por_uf:
        return []

    # ── Soma ICMS-ST nos documentos (C170 > C100 > C190) ──
    vl_st_docs = 0.0
    fonte = ""
    count_docs = 0

    # Tentar C170 primeiro
    for r in ctx.groups.get("C170", []):
        vl = to_float(get_field(r, "VL_ICMS_ST"))
        if vl > 0:
            vl_st_docs += vl
            count_docs += 1
    if count_docs > 0:
        fonte = "C170"

    # Fallback: C100.VL_ICMS_ST (saidas)
    if count_docs == 0:
        for r in ctx.groups.get("C100", []):
            ind_oper = get_field(r, F_C100_IND_OPER)
            if ind_oper != "1":
                continue
            vl = to_float(get_field(r, F_C100_VL_ICMS_ST))
            if vl > 0:
                vl_st_docs += vl
                count_docs += 1
        if count_docs > 0:
            fonte = "C100"

    # Fallback: C190.VL_ICMS_ST (saidas CFOP 5xxx/6xxx/7xxx)
    if count_docs == 0:
        for r in ctx.groups.get("C190", []):
            cfop = get_field(r, F_C190_CFOP)
            if cfop and cfop[0] in ("5", "6", "7"):
                vl = to_float(get_field(r, "VL_ICMS_ST"))
                if vl > 0:
                    vl_st_docs += vl
                    count_docs += 1
        if count_docs > 0:
            fonte = "C190"

    # ── Considerar ajustes E220 ──
    vl_ajustes_cred_st = 0.0
    vl_ajustes_deb_st = 0.0
    for r in ctx.groups.get("E220", []):
        vl_aj = to_float(get_field(r, "VL_AJ_APUR"))
        cod_aj = get_field(r, "COD_AJ_APUR")
        # Codigos de ajuste: 3o digito indica debito (0) ou credito (1)
        if cod_aj and len(cod_aj) >= 3:
            if cod_aj[2] == "1":
                vl_ajustes_cred_st += vl_aj
            else:
                vl_ajustes_deb_st += vl_aj

    # ── Comparar: soma total E210 vs docs ──
    vl_total_e210 = sum(vl for _, _, vl in e210_por_uf)

    # Se docs e E210 batem, tudo OK
    tol = get_tolerance("apuracao_e110")
    if abs(vl_st_docs - vl_total_e210) <= tol:
        return []

    # Se nao ha documentos com ST mas E210 tem retencao,
    # verificar se ajustes E220 explicam a diferenca
    if count_docs == 0 and (vl_ajustes_deb_st > 0 or vl_ajustes_cred_st > 0):
        # Ajustes podem explicar o valor — nao eh inconsistencia dos docs
        return []

    # Se documentos existem e a diferenca pode ser explicada por
    # saldo anterior, devolucoes e ajustes, nao apontar
    for e210_rec, _, vl_retencao in e210_por_uf:
        vl_sld_ant = to_float(get_field(e210_rec, "VL_SLD_CRED_ANT_ST"))
        vl_devol = to_float(get_field(e210_rec, "VL_DEVOL_ST"))
        vl_ressarc = to_float(get_field(e210_rec, "VL_RESSARC_ST"))
        vl_out_cred = to_float(get_field(e210_rec, "VL_OUT_CRED_ST"))
        vl_aj_cred = to_float(get_field(e210_rec, "VL_AJ_CREDITOS_ST"))
        if vl_sld_ant > 0 or vl_devol > 0 or vl_ressarc > 0 or vl_out_cred > 0 or vl_aj_cred > 0:
            # Existem creditos/ajustes que podem explicar a diferenca
            return []

    # ── Gerar erro com informacao completa ──
    errors: list[ValidationError] = []
    ufs_str = ", ".join(uf or "?" for _, uf, _ in e210_por_uf)
    e210_rec = e210_por_uf[0][0]

    if count_docs == 0:
        msg = (
            f"E210 indica retencao de ST de R$ {vl_total_e210:,.2f} (UF: {ufs_str}), "
            f"porem nao foram localizados valores de ICMS-ST nos documentos "
            f"(C100/C170/C190). Verifique se o montante decorre de saldo anterior, "
            f"ajustes (E220), ressarcimento, devolucao ou outro lancamento "
            f"especifico de ST. Caso nao exista fundamento fiscal, a apuracao "
            f"pode estar inconsistente."
        )
        val = f"docs_ST=0.00 E210_retencao={vl_total_e210:,.2f}"
    else:
        msg = (
            f"ICMS-ST nos documentos ({fonte}, {count_docs} registros) soma "
            f"R$ {vl_st_docs:,.2f}, mas a retencao ST no E210 indica "
            f"R$ {vl_total_e210:,.2f} (UF: {ufs_str}). "
            f"Diferenca: R$ {abs(vl_st_docs - vl_total_e210):,.2f}. "
            f"Verifique a consistencia entre documentos e apuracao ST."
        )
        val = f"{fonte}_ST={vl_st_docs:,.2f} E210_retencao={vl_total_e210:,.2f}"

    errors.append(make_error(
        e210_rec, "VL_RETENCAO_ST", "ST_APURACAO_INCONSISTENTE",
        msg,
        value=val,
    ))

    return errors


# ──────────────────────────────────────────────
# Regra 9/29: AUD_E111_CODIGO_GENERICO / AUD_E111_NUMERICO_JURIDICO
# ──────────────────────────────────────────────

def _check_e111_codigo_generico(ctx: _BeneficioContext) -> list[ValidationError]:
    """E111 com COD_AJ_APUR generico (999/000) e valor > 0."""
    errors: list[ValidationError] = []

    for e in ctx.e111_list:
        if e.eh_codigo_generico and e.valor > 0:
            errors.append(make_error(
                e.record, "COD_AJ_APUR", "AJUSTE_CODIGO_GENERICO",
                (
                    f"Ajuste E111 com codigo generico ({e.cod_aj}) e valor "
                    f"R$ {e.valor:,.2f}. Codigos terminados em 999 ou 000 sao "
                    f"residuais e nao identificam a natureza especifica do ajuste. "
                    f"Utilize o codigo adequado conforme tabela 5.1.1."
                ),
                field_no=1,
                value=f"COD={e.cod_aj} VL={e.valor:,.2f}",
            ))

            # Regra 29: validade juridica
            errors.append(make_error(
                e.record, "COD_AJ_APUR", "AJUSTE_NUMERICO_SEM_VALIDADE_JURIDICA",
                (
                    f"Ajuste E111 (COD={e.cod_aj}) com codigo generico que "
                    f"fecha numericamente com E110 mas carece de base legal "
                    f"especifica. Ajustes devem ter fundamentacao juridica "
                    f"identificavel pelo codigo de ajuste."
                ),
                field_no=1,
                value=f"COD={e.cod_aj} VL={e.valor:,.2f}",
            ))

    return errors


# ──────────────────────────────────────────────
# Regra 10: AUD_XML_SPED_DIVERGENCIA
# ──────────────────────────────────────────────

def _check_xml_sped_divergencia(ctx: _BeneficioContext) -> list[ValidationError]:
    """Desativada: validacao C170 vs C190 por combinacao analitica agora e feita
    no c190_validator.py (_check_c190_001) com agrupamento correto por documento
    e rateio de despesas do C100. Manter funcao para nao quebrar chamada."""
    return []


# ──────────────────────────────────────────────
# Regra 11: AUD_CHECKLIST_AUDITORIA_MINIMA
# ──────────────────────────────────────────────

def _check_checklist_auditoria(ctx: _BeneficioContext) -> list[ValidationError]:
    """Verifica presenca minima de registros para auditoria."""
    presentes = 0
    for reg in _REGISTROS_AUDITORIA:
        if reg in ctx.registros_presentes:
            presentes += 1

    if presentes >= 5:
        return []

    ausentes = _REGISTROS_AUDITORIA - ctx.registros_presentes
    err = make_generic_error(
        "CHECKLIST_INCOMPLETO",
        (
            f"Apenas {presentes} de {len(_REGISTROS_AUDITORIA)} registros essenciais "
            f"estao presentes no arquivo. Ausentes: {', '.join(sorted(ausentes))}. "
            f"A auditoria de beneficios requer no minimo 0150, 0200, C170, "
            f"C190, E110, E111 e H010 para analise completa."
        ),
        register="SPED",
        value=f"{presentes}/{len(_REGISTROS_AUDITORIA)} registros",
    )
    err.categoria = "governance"
    return [err]


# ──────────────────────────────────────────────
# Regra 12: AUD_TRILHA_BENEFICIO_INCOMPLETA
# ──────────────────────────────────────────────

def _check_trilha_beneficio_incompleta(ctx: _BeneficioContext) -> list[ValidationError]:
    """E111 sem lastro e sem correspondencia com C190 interestadual."""
    if not ctx.e111_list or ctx.c190_icms_interestadual <= 0:
        return []

    errors: list[ValidationError] = []
    for e in ctx.e111_list:
        if e.valor <= get_tolerance("apuracao_e110") or e.tem_lastro:
            continue

        # Sem lastro E112/E113 e sem proporcionalidade com interestadual
        if ctx.c190_icms_interestadual > 0:
            ratio = e.valor / ctx.c190_icms_interestadual
            if ratio > 1.0 or ratio < 0.001:
                errors.append(make_error(
                    e.record, "VL_AJ_APUR", "TRILHA_BENEFICIO_INCOMPLETA",
                    (
                        f"Ajuste E111 (COD={e.cod_aj}, VL=R$ {e.valor:,.2f}) "
                        f"sem lastro documental (E112/E113) e sem correspondencia "
                        f"proporcional com operacoes interestaduais "
                        f"(ICMS inter = R$ {ctx.c190_icms_interestadual:,.2f}). "
                        f"A trilha do beneficio esta incompleta."
                    ),
                    field_no=3,
                    value=f"COD={e.cod_aj} VL={e.valor:,.2f}",
                ))

    return errors


# ──────────────────────────────────────────────
# Regra 13: AUD_ICMS_EFETIVO_SEM_TRILHA
# ──────────────────────────────────────────────

def _check_icms_efetivo_sem_trilha(ctx: _BeneficioContext) -> list[ValidationError]:
    """C170 interestadual com aliquota atipica sem E111."""
    if ctx.e111_list:
        return []

    errors: list[ValidationError] = []
    for r in ctx.groups.get("C170", []):
        cfop = get_field(r, F_C170_CFOP)
        if not cfop or cfop[0] != "6":
            continue
        if cfop in CFOP_REMESSA_SAIDA:
            continue

        cst = get_field(r, F_C170_CST_ICMS)
        if trib(cst) not in CST_TRIBUTADO:
            continue

        aliq = to_float(get_field(r, F_C170_ALIQ_ICMS))
        if aliq <= 0 or aliq in ALIQ_INTERESTADUAIS:
            continue

        errors.append(make_error(
            r, "ALIQ_ICMS", "ICMS_EFETIVO_SEM_TRILHA",
            (
                f"Operacao interestadual (CFOP {cfop}) com aliquota {aliq:.2f}% "
                f"(nao padrao: 4/7/12%) e sem nenhum ajuste E111 no periodo. "
                f"A reducao de carga tributaria no documento sem reflexo "
                f"na apuracao indica ausencia de trilha de beneficio."
            ),
            field_no=14,
            value=f"CFOP={cfop} ALIQ={aliq:.2f}%",
        ))

    return errors


# ──────────────────────────────────────────────
# Regra 14: AUD_BENEFICIO_FORA_ESCOPO
# ──────────────────────────────────────────────

def _check_beneficio_fora_escopo(ctx: _BeneficioContext) -> list[ValidationError]:
    """E111 com beneficio mas operacoes predominantemente internas/isentas."""
    if not ctx.e111_list or ctx.c190_vl_opr_total <= 0:
        return []

    pct_interno = ctx.c190_vl_opr_interno / ctx.c190_vl_opr_total * 100

    if pct_interno <= 70:
        return []

    # Verifica se ha ajuste E111 tipico de beneficio interestadual
    tem_beneficio_inter = any(e.eh_credito for e in ctx.e111_list)
    if not tem_beneficio_inter:
        return []

    return [make_generic_error(
        "BENEFICIO_FORA_ESCOPO",
        (
            f"Operacoes internas representam {pct_interno:.1f}% do total "
            f"(R$ {ctx.c190_vl_opr_interno:,.2f} de R$ {ctx.c190_vl_opr_total:,.2f}), "
            f"mas existem ajustes E111 de credito. Beneficios para operacoes "
            f"interestaduais sao inaplicaveis quando o perfil operacional "
            f"e predominantemente interno."
        ),
        register="E111",
        value=f"INTERNO={pct_interno:.1f}%",
    )]


# ──────────────────────────────────────────────
# Regra 15: AUD_DIAGNOSTICO_CAUSA_RAIZ
# ──────────────────────────────────────────────

def _check_diagnostico_causa_raiz(ctx: _BeneficioContext) -> list[ValidationError]:
    """Divergencias em cascata C170->C190->E110."""
    erros_c170_c190 = 0
    erros_c190_e110 = 0

    # C170 -> C190: verificar por CST+CFOP+ALIQ (chave completa 3 digitos)
    # O C190 totaliza por CST_ICMS(3d) + CFOP + ALIQ conforme Guia Pratico.
    # Usar CST completo para nao colapsar origens diferentes (ex: 000 vs 500).
    c170_totais: dict[tuple[str, str, str], float] = defaultdict(float)
    for r in ctx.groups.get("C170", []):
        cst = get_field(r, F_C170_CST_ICMS)
        cfop = get_field(r, F_C170_CFOP)
        aliq = get_field(r, F_C170_ALIQ_ICMS)
        c170_totais[(cst, cfop, aliq)] += to_float(get_field(r, F_C170_VL_ICMS))

    c190_totais: dict[tuple[str, str, str], float] = defaultdict(float)
    for r in ctx.c190_records:
        cst = get_field(r, F_C190_CST)
        cfop = get_field(r, F_C190_CFOP)
        aliq = get_field(r, F_C190_ALIQ)
        c190_totais[(cst, cfop, aliq)] += to_float(get_field(r, F_C190_VL_ICMS))

    for key in set(c170_totais.keys()) | set(c190_totais.keys()):
        v170 = c170_totais.get(key, 0.0)
        v190 = c190_totais.get(key, 0.0)
        if abs(v170 - v190) > get_tolerance("consolidacao"):
            erros_c170_c190 += 1

    # C190 -> E110: soma total de ICMS saida vs debito
    if ctx.e110_presente and ctx.c190_icms_saida_tributado > 0:
        diff = abs(ctx.c190_icms_saida_tributado - ctx.e110_vl_tot_debitos)
        if diff > get_tolerance("apuracao_e110"):
            erros_c190_e110 += 1

    if erros_c170_c190 > 0 and erros_c190_e110 > 0:
        return [make_generic_error(
            "DIVERGENCIA_DOCUMENTO_ESCRITURACAO",
            (
                f"Detectadas divergencias em cascata: {erros_c170_c190} "
                f"inconsistencias entre C170 e C190, e {erros_c190_e110} "
                f"entre C190 e E110. Isso indica problema sistematico na "
                f"escrituracao que se propaga dos documentos ate a apuracao."
            ),
            register="SPED",
            value=f"C170xC190={erros_c170_c190} C190xE110={erros_c190_e110}",
        )]

    return []


# ──────────────────────────────────────────────
# Regra 18: AUD_C190_MISTURA_CST
# ──────────────────────────────────────────────

def _check_c190_mistura_cst(ctx: _BeneficioContext) -> list[ValidationError]:
    """C190 onde ALIQ declarada diverge de VL_ICMS/VL_BC_ICMS."""
    errors: list[ValidationError] = []

    for r in ctx.c190_records:
        vl_bc = to_float(get_field(r, F_C190_VL_BC))
        vl_icms = to_float(get_field(r, F_C190_VL_ICMS))
        aliq_decl = to_float(get_field(r, F_C190_ALIQ))

        if vl_bc <= 0 or aliq_decl <= 0:
            continue

        aliq_efetiva = (vl_icms / vl_bc) * 100
        diff_pct = abs(aliq_efetiva - aliq_decl)

        if diff_pct > 1.0:
            errors.append(make_error(
                r, "ALIQ_ICMS", "C190_CONSOLIDACAO_INDEVIDA",
                (
                    f"C190 com ALIQ declarada {aliq_decl:.2f}% mas aliquota "
                    f"efetiva (VL_ICMS/VL_BC) = {aliq_efetiva:.2f}% "
                    f"(diferenca: {diff_pct:.2f}pp). A consolidacao pode "
                    f"estar misturando CSTs ou aliquotas distintas."
                ),
                field_no=3,
                value=f"ALIQ_DECL={aliq_decl:.2f} EFET={aliq_efetiva:.2f}",
            ))

    return errors


# ──────────────────────────────────────────────
# Regra 19: AUD_CREDITO_SEM_SAIDA (delegado)
# ──────────────────────────────────────────────
# Implementacao compartilhada com audit_rules.py (_check_credito_uso_consumo).
# Aqui emitimos com error_type CREDITO_ENTRADA_SEM_SAIDA para E111 que
# tenham credito mas sem saidas correspondentes.
# Nota: a regra original esta em audit_rules.py. Nao duplicamos.


# ──────────────────────────────────────────────
# Regra 20: AUD_INVENTARIO_REFLEXO_TRIBUTARIO
# ──────────────────────────────────────────────

def _check_inventario_reflexo(ctx: _BeneficioContext) -> list[ValidationError]:
    """H010 com VL_ITEM zero/negativo, QTD irreal, ou item nao cadastrado."""
    errors: list[ValidationError] = []

    for r in ctx.groups.get("H010", []):
        cod_item = get_field(r, F_H010_COD_ITEM)
        qtd = to_float(get_field(r, F_H010_QTD))
        vl_item = to_float(get_field(r, F_H010_VL_ITEM))

        if vl_item <= 0:
            errors.append(make_error(
                r, "VL_ITEM", "INVENTARIO_INCONSISTENTE_TRIBUTARIO",
                (
                    f"Item {cod_item} no inventario (H010) com valor "
                    f"R$ {vl_item:,.2f} (zero ou negativo). Itens no "
                    f"inventario devem ter valorizacao positiva."
                ),
                field_no=5,
                value=f"COD_ITEM={cod_item} VL={vl_item:,.2f}",
            ))

        if qtd > 100000:
            errors.append(make_error(
                r, "QTD", "INVENTARIO_INCONSISTENTE_TRIBUTARIO",
                (
                    f"Item {cod_item} no inventario (H010) com quantidade "
                    f"atipica: {qtd:,.0f}. Quantidade acima de 100.000 "
                    f"unidades merece revisao para confirmar se nao ha "
                    f"erro na unidade de medida."
                ),
                field_no=3,
                value=f"COD_ITEM={cod_item} QTD={qtd:,.0f}",
            ))

        if cod_item and cod_item not in ctx.items_0200:
            errors.append(make_error(
                r, "COD_ITEM", "INVENTARIO_INCONSISTENTE_TRIBUTARIO",
                (
                    f"Item {cod_item} consta no inventario (H010) mas nao "
                    f"esta cadastrado no registro 0200. Todo item do "
                    f"inventario deve ter cadastro correspondente."
                ),
                field_no=1,
                value=f"COD_ITEM={cod_item}",
            ))

    return errors


# ──────────────────────────────────────────────
# Regra 21: AUD_BENEFICIO_SEM_GOVERNANCA
# ──────────────────────────────────────────────

def _check_beneficio_sem_governanca(ctx: _BeneficioContext) -> list[ValidationError]:
    """E111 com valor > tolerance, sem E112, e descricao vazia/curta."""
    errors: list[ValidationError] = []

    for e in ctx.e111_list:
        if e.valor <= get_tolerance("apuracao_e110"):
            continue
        if e.filhos_e112:
            continue

        descr = e.descr.strip()
        if len(descr) < 10:
            errors.append(make_error(
                e.record, "DESCR_COMPL_AJ", "BENEFICIO_SEM_GOVERNANCA",
                (
                    f"Ajuste E111 (COD={e.cod_aj}) com valor R$ {e.valor:,.2f}, "
                    f"sem registro E112 vinculado e descricao insuficiente "
                    f"('{descr}' - {len(descr)} caracteres). Ajustes de "
                    f"apuracao devem ter documentacao adequada para "
                    f"governanca tributaria."
                ),
                field_no=2,
                value=f"COD={e.cod_aj} DESCR='{descr}'",
            ))

    return errors


# ──────────────────────────────────────────────
# Regra 22: AUD_TOTALIZACAO_BENEFICIADA
# ──────────────────────────────────────────────

def _check_totalizacao_beneficiada(ctx: _BeneficioContext) -> list[ValidationError]:
    """Perfil C190 inconsistente com E110."""
    if not ctx.e110_presente or ctx.c190_vl_opr_total <= 0:
        return []

    pct_inter = ctx.c190_vl_opr_interestadual / ctx.c190_vl_opr_total * 100
    if pct_inter <= 30:
        return []

    # Se > 30% interestadual, E110 debitos devem refletir ICMS proporcional
    if ctx.e110_vl_tot_debitos <= 0:
        return []

    # Proporcao esperada: debitos interestaduais / total debitos
    icms_total_saida = ctx.c190_icms_saida_tributado
    if icms_total_saida <= 0:
        return []

    pct_icms_inter = ctx.c190_icms_interestadual / icms_total_saida * 100

    # Se o perfil mostra >30% interestadual mas ICMS interestadual < 10%, inconsistente
    if pct_icms_inter < 10 and pct_inter > 30:
        return [make_generic_error(
            "TOTALIZACAO_BENEFICIO_DIVERGENTE",
            (
                f"Saidas interestaduais representam {pct_inter:.1f}% das operacoes, "
                f"mas o ICMS interestadual representa apenas {pct_icms_inter:.1f}% "
                f"do total de debitos. A totalizacao do beneficio esta "
                f"inconsistente com o perfil operacional."
            ),
            register="E110",
            value=f"OPR_INTER={pct_inter:.1f}% ICMS_INTER={pct_icms_inter:.1f}%",
        )]

    return []


# ──────────────────────────────────────────────
# Regra 24: AUD_PERFIL_OPERACIONAL_BENEFICIO
# ──────────────────────────────────────────────

def _check_perfil_operacional_beneficio(ctx: _BeneficioContext) -> list[ValidationError]:
    """E111 com beneficio cujas operacoes nao correspondem ao perfil esperado."""
    if not ctx.e111_list or ctx.c190_vl_opr_total <= 0:
        return []

    # Contar CFOPs no C190
    cfop_dist: dict[str, float] = defaultdict(float)
    for r in ctx.c190_records:
        cfop = get_field(r, F_C190_CFOP)
        if cfop:
            cfop_dist[cfop[0]] += to_float(get_field(r, F_C190_VL_OPR))

    # Verificar se distribuicao e coerente com tipo de beneficio
    total_saida = cfop_dist.get("5", 0) + cfop_dist.get("6", 0) + cfop_dist.get("7", 0)
    if total_saida <= 0:
        return []

    tem_credito = any(e.eh_credito for e in ctx.e111_list)
    if not tem_credito:
        return []

    # Se predominam entradas (1/2xxx) e ha credito presumido na saida, incoerente
    total_entrada = cfop_dist.get("1", 0) + cfop_dist.get("2", 0) + cfop_dist.get("3", 0)
    if total_entrada > total_saida * 3:
        return [make_generic_error(
            "BENEFICIO_PERFIL_INCOMPATIVEL",
            (
                f"Perfil operacional predominantemente de entradas "
                f"(R$ {total_entrada:,.2f}) vs saidas (R$ {total_saida:,.2f}), "
                f"mas existem ajustes de credito presumido no E111. "
                f"Verifique se o beneficio e aplicavel ao perfil operacional."
            ),
            register="E111",
            value=f"ENTRADAS={total_entrada:,.2f} SAIDAS={total_saida:,.2f}",
        )]

    return []


# ──────────────────────────────────────────────
# Regra 25: AUD_BENEFICIO_PARAMETRIZACAO_ERRADA
# ──────────────────────────────────────────────

def _check_beneficio_parametrizacao_errada(ctx: _BeneficioContext) -> list[ValidationError]:
    """E111 presente mas C170 mostra CST/ALIQ/CFOP incompativeis."""
    if not ctx.e111_list:
        return []

    tem_beneficio_inter = any(e.eh_credito for e in ctx.e111_list)
    if not tem_beneficio_inter:
        return []

    # Conta C170 com CFOP interestadual vs interno
    c170_inter = 0
    c170_interno = 0
    for r in ctx.groups.get("C170", []):
        cfop = get_field(r, F_C170_CFOP)
        if not cfop:
            continue
        if cfop[0] == "6" and cfop not in CFOP_REMESSA_SAIDA:
            c170_inter += 1
        elif cfop[0] == "5" and cfop not in CFOP_REMESSA_SAIDA:
            c170_interno += 1

    total = c170_inter + c170_interno
    if total <= 0:
        return []

    # Se beneficio interestadual mas < 10% dos itens sao interestaduais
    pct_inter = c170_inter / total * 100
    if pct_inter < 10 and c170_interno > 10:
        return [make_generic_error(
            "BENEFICIO_EXECUCAO_INCORRETA",
            (
                f"E111 possui ajustes de credito (beneficio interestadual), "
                f"mas apenas {pct_inter:.1f}% dos itens em C170 sao "
                f"interestaduais ({c170_inter} de {total}). A parametrizacao "
                f"do beneficio pode estar incorreta para o perfil de operacoes."
            ),
            register="E111",
            value=f"INTER={c170_inter} INTERNO={c170_interno}",
        )]

    return []


# ──────────────────────────────────────────────
# Regra 26: AUD_DESTINATARIO_SEGREGACAO
# ──────────────────────────────────────────────

def _check_destinatario_segregacao(ctx: _BeneficioContext) -> list[ValidationError]:
    """E111 com beneficio e C170 mistura contribuintes e nao-contribuintes."""
    if not ctx.e111_list:
        return []

    tem_credito = any(e.eh_credito for e in ctx.e111_list)
    if not tem_credito:
        return []

    # Verificar se C170 mistura participantes de UFs diferentes
    # (proxy: COD_PART com e sem UF no 0150)
    ufs_destino: set[str] = set()
    parts_sem_uf: int = 0
    parts_com_uf: int = 0

    for r in ctx.groups.get("C170", []):
        cfop = get_field(r, F_C170_CFOP)
        if not cfop or cfop[0] not in ("5", "6"):
            continue

        parent = ctx.c170_parent.get(r.line_number)
        if not parent:
            continue

        cod_part = get_field(parent, F_C100_COD_PART)
        uf = ctx.part_uf.get(cod_part, "")
        if uf:
            ufs_destino.add(uf)
            parts_com_uf += 1
        else:
            parts_sem_uf += 1

    # Se mistura participantes com e sem UF (proxy para contribuinte/nao)
    if parts_sem_uf > 0 and parts_com_uf > 0:
        return [make_generic_error(
            "BENEFICIO_SEM_SEGREGACAO_DESTINATARIO",
            (
                f"E111 possui ajustes de credito (beneficio) e os documentos "
                f"C170 misturam destinatarios com UF identificada ({parts_com_uf}) "
                f"e sem UF ({parts_sem_uf}). A base do beneficio deve segregar "
                f"operacoes por tipo de destinatario (contribuinte vs nao-contribuinte)."
            ),
            register="C170",
            value=f"COM_UF={parts_com_uf} SEM_UF={parts_sem_uf}",
        )]

    return []


# ──────────────────────────────────────────────
# Regra 27: AUD_BASE_BENEFICIO_INFLADA
# ──────────────────────────────────────────────

def _check_base_beneficio_inflada(ctx: _BeneficioContext) -> list[ValidationError]:
    """E111 desproporcional a operacoes elegiveis (excl devolucao/remessa/cancel)."""
    if not ctx.e111_list:
        return []

    total_ajuste = ctx.total_e111_ajustes
    if total_ajuste <= 0:
        return []

    # Operacoes elegiveis = total - devolucao - remessa
    opr_elegivel = (
        ctx.c190_vl_opr_total
        - ctx.c190_vl_opr_devolucao
        - ctx.c190_vl_opr_remessa
    )

    if opr_elegivel <= 0:
        return []

    # ICMS elegivel estimado (usando aliquota media das saidas tributadas)
    icms_elegivel = ctx.c190_icms_saida_tributado
    if icms_elegivel <= 0:
        return []

    # Se ajuste > ICMS elegivel, a base esta inflada
    if total_ajuste > icms_elegivel:
        return [make_generic_error(
            "BASE_BENEFICIO_INFLADA",
            (
                f"Ajustes E111 totalizam R$ {total_ajuste:,.2f}, mas o ICMS "
                f"elegivel (excluindo devolucoes e remessas) e de "
                f"R$ {icms_elegivel:,.2f}. A base de calculo do beneficio "
                f"pode estar incluindo operacoes nao elegiveis."
            ),
            register="E111",
            value=f"AJ={total_ajuste:,.2f} ICMS_ELEG={icms_elegivel:,.2f}",
        )]

    return []


# ──────────────────────────────────────────────
# Regra 28: AUD_SPED_VS_CONTRIBUICOES
# ──────────────────────────────────────────────

def _check_sped_vs_contribuicoes(ctx: _BeneficioContext) -> list[ValidationError]:
    """C170 com CST_PIS e CST_COFINS divergentes entre si."""
    errors: list[ValidationError] = []

    for r in ctx.groups.get("C170", []):
        cst_pis = get_field(r, F_C170_CST_PIS)
        cst_cofins = get_field(r, F_C170_CST_COFINS)

        if not cst_pis or not cst_cofins:
            continue

        pis_tributado = cst_pis in _CST_PIS_COFINS_TRIBUTADO
        cofins_tributado = cst_cofins in _CST_PIS_COFINS_TRIBUTADO
        pis_isento = cst_pis in _CST_PIS_COFINS_ISENTO
        cofins_isento = cst_cofins in _CST_PIS_COFINS_ISENTO

        # Divergencia: um tributado e outro isento
        if (pis_tributado and cofins_isento) or (pis_isento and cofins_tributado):
            cod_item = get_field(r, F_C170_COD_ITEM)
            errors.append(make_error(
                r, "CST_PIS", "SPED_CONTRIBUICOES_DIVERGENTE",
                (
                    f"Item {cod_item}: CST_PIS={cst_pis} e CST_COFINS={cst_cofins} "
                    f"sao divergentes (um indica tributacao e outro isencao). "
                    f"PIS e COFINS devem ter tratamento tributario consistente "
                    f"para o mesmo item/operacao."
                ),
                field_no=24,
                value=f"CST_PIS={cst_pis} CST_COFINS={cst_cofins}",
            ))

    return errors


# ──────────────────────────────────────────────
# Regra 30: AUD_CODIGO_AJUSTE_INCOMPATIVEL
# ──────────────────────────────────────────────

def _check_codigo_ajuste_incompativel(ctx: _BeneficioContext) -> list[ValidationError]:
    """E111 COD_AJ_APUR com formato invalido."""
    errors: list[ValidationError] = []

    for e in ctx.e111_list:
        cod = e.cod_aj
        if not cod:
            continue

        problemas: list[str] = []

        # Deve ter 8 caracteres
        if len(cod) != 8:
            problemas.append(f"tamanho {len(cod)} (esperado 8)")

        # Primeiros 2 caracteres devem ser UF valida
        if len(cod) >= 2:
            uf_cod = cod[:2]
            if uf_cod not in _UFS_VALIDAS:
                problemas.append(f"UF '{uf_cod}' invalida")

        # Posicao 2 deve ser 0 (debito) ou 1 (credito)
        if len(cod) >= 3:
            natureza = cod[2]
            if natureza not in ("0", "1"):
                problemas.append(f"natureza '{natureza}' invalida (esperado 0 ou 1)")

        if problemas:
            errors.append(make_error(
                e.record, "COD_AJ_APUR", "CODIGO_AJUSTE_INCOMPATIVEL",
                (
                    f"COD_AJ_APUR '{cod}' com formato invalido: "
                    f"{'; '.join(problemas)}. O formato correto e UUNNNNnn "
                    f"(UU=UF, N=natureza+tipo, nn=sequencial)."
                ),
                field_no=1,
                value=f"COD={cod}",
            ))

    return errors


# ──────────────────────────────────────────────
# Regra 31: AUD_TRILHA_BENEFICIO_AUSENTE
# ──────────────────────────────────────────────

def _check_trilha_beneficio_ausente(ctx: _BeneficioContext) -> list[ValidationError]:
    """E111 com valor > 5000 sem E112/E113 (limiar mais alto)."""
    errors: list[ValidationError] = []
    limiar = 5000.0

    for e in ctx.e111_list:
        if e.valor > limiar and not e.tem_lastro:
            errors.append(make_error(
                e.record, "VL_AJ_APUR", "TRILHA_BENEFICIO_AUSENTE",
                (
                    f"Ajuste E111 (COD={e.cod_aj}) com valor relevante "
                    f"R$ {e.valor:,.2f} (acima de R$ {limiar:,.2f}) sem "
                    f"nenhum registro E112 ou E113 vinculado. Ajustes "
                    f"materiais devem ter trilha documental completa."
                ),
                field_no=3,
                value=f"COD={e.cod_aj} VL={e.valor:,.2f}",
            ))

    return errors


# ──────────────────────────────────────────────
# Regra 32: AUD_CLASSIFICACAO_ERRO (meta-regra)
# ──────────────────────────────────────────────

def _check_classificacao_erro(errors: list[ValidationError]) -> list[ValidationError]:
    """Meta-regra: classifica padrao de erros encontrados."""
    if not errors:
        return []

    # Contar erros por item/CFOP
    error_by_value: dict[str, int] = defaultdict(int)
    for e in errors:
        error_by_value[e.value] += 1

    total = len(errors)
    if total == 0:
        return []

    # Verificar se >80% dos erros vem do mesmo padrao
    max_count = max(error_by_value.values()) if error_by_value else 0
    pct_concentrado = max_count / total * 100

    if pct_concentrado > 80:
        classificacao = "parametrizacao"
        msg = (
            f"Analise dos {total} achados indica problema de parametrizacao "
            f"sistematica: {pct_concentrado:.0f}% dos erros concentrados no "
            f"mesmo padrao. Recomenda-se revisao da configuracao do ERP."
        )
    else:
        classificacao = "material"
        msg = (
            f"Analise dos {total} achados indica erros materiais dispersos "
            f"em {len(error_by_value)} padroes distintos. Recomenda-se "
            f"revisao individualizada de cada achado."
        )

    err = make_generic_error(
        "CLASSIFICACAO_TIPO_ERRO",
        msg,
        register="SPED",
        value=f"tipo={classificacao} total={total}",
    )
    err.categoria = "governance"
    return [err]


# ──────────────────────────────────────────────
# Regra 33: AUD_ESCOPO_APENAS_SPED (meta-regra)
# ──────────────────────────────────────────────

def _check_escopo_apenas_sped(errors: list[ValidationError]) -> list[ValidationError]:
    """Meta-regra: informa que achados sao baseados apenas no SPED."""
    if not errors:
        return []

    err = make_generic_error(
        "ACHADO_LIMITADO_AO_SPED",
        (
            f"Todos os {len(errors)} achados desta auditoria sao baseados "
            f"exclusivamente nos dados do SPED EFD, sem validacao contra "
            f"documentos fiscais eletronicos (XML NF-e), livros contabeis "
            f"ou outros sistemas. Recomenda-se cruzamento com fontes externas "
            f"para confirmacao dos achados."
        ),
        register="SPED",
        value=f"total_achados={len(errors)}",
    )
    err.categoria = "governance"
    return [err]


# ──────────────────────────────────────────────
# Regra 34: GOV_002 — Explicitar grau de confianca
# ──────────────────────────────────────────────

def _check_grau_confianca(errors: list[ValidationError]) -> list[ValidationError]:
    """GOV_002: resume o grau de confianca dos achados por certeza."""
    if not errors:
        return []

    # Contar achados por grau de certeza
    contagem: dict[str, int] = {"objetivo": 0, "provavel": 0, "indicio": 0}
    for e in errors:
        if e.categoria == "governance":
            continue
        certeza = e.certeza if e.certeza in contagem else "indicio"
        contagem[certeza] += 1

    total = sum(contagem.values())
    if total == 0:
        return []

    partes = []
    for grau, qtd in contagem.items():
        if qtd > 0:
            partes.append(f"{qtd} {grau}(s)")

    err = make_generic_error(
        "GRAU_CONFIANCA_ACHADOS",
        (
            f"Dos {total} achados fiscais: {', '.join(partes)}. "
            f"Achados 'objetivo' sao baseados em regras deterministicas. "
            f"'Provavel' depende de heuristica com alta confianca. "
            f"'Indicio' requer validacao manual pelo analista."
        ),
        register="SPED",
        value=f"total={total} " + " ".join(f"{k}={v}" for k, v in contagem.items()),
    )
    err.categoria = "governance"
    return [err]


# ──────────────────────────────────────────────
# Regra 35: AMOSTRA_001 — Amostragem por materialidade e risco
# ──────────────────────────────────────────────

def _check_amostragem_materialidade(
    errors: list[ValidationError],
    ctx: _BeneficioContext,
) -> list[ValidationError]:
    """AMOSTRA_001: resume amostragem de registros vs total do arquivo."""
    total_c170 = len(ctx.groups.get("C170", []))
    total_c190 = len(ctx.groups.get("C190", []))
    total_registros = total_c170 + total_c190

    if total_registros == 0:
        return []

    # Linhas com erro fiscal (nao governance)
    linhas_com_erro = {e.line_number for e in errors if e.categoria != "governance" and e.line_number > 0}
    cobertura = len(linhas_com_erro) / total_registros * 100 if total_registros > 0 else 0

    err = make_generic_error(
        "AMOSTRAGEM_MATERIALIDADE",
        (
            f"Universo auditado: {total_c170} itens (C170) e {total_c190} "
            f"consolidacoes (C190). Achados abrangem {len(linhas_com_erro)} "
            f"registros ({cobertura:.1f}% do universo). Registros sem achados "
            f"nao foram necessariamente validados em todas as dimensoes — "
            f"consulte o escopo das regras ativas."
        ),
        register="SPED",
        value=f"C170={total_c170} C190={total_c190} com_erro={len(linhas_com_erro)}",
    )
    err.categoria = "governance"
    return [err]
