"""Validacao semantica fiscal: CST x aliquota zero, CST x CFOP, monofasicos.

Camada 3 do motor de validacao -- regras que verificam se o tratamento
tributario informado faz sentido fiscalmente, alem da consistencia numerica.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from .helpers import (
    CFOP_DEVOLUCAO,
    CFOP_EXPORTACAO,
    CFOP_REMESSA_RETORNO,
    CFOP_VENDA,
    CST_DIFERIMENTO,
    CST_ISENTO_NT,
    CST_TRIBUTADO,
    get_field,
    make_error,
    to_float,
    trib,
)

if TYPE_CHECKING:
    from ..services.context_builder import ValidationContext

# ──────────────────────────────────────────────
# Constantes locais — CST (nao compartilhadas)
# ──────────────────────────────────────────────

# IPI — CSTs que indicam tributacao efetiva (saida tributada / entrada com credito)
# 49 (Outras Entradas) e 99 (Outras Saidas) sao residuais e nao exigem valores
_CST_IPI_TRIBUTADO = {"00", "01", "50"}

# PIS/COFINS — CSTs que indicam operacao tributavel (aliquota normal)
_CST_PIS_COFINS_TRIBUTAVEL = {"01", "02", "03", "49"}

# PIS/COFINS — CST monofasico (revenda a aliquota zero)
_CST_PIS_COFINS_MONOFASICO = {"04"}

# PIS/COFINS — CST substituicao tributaria PIS/COFINS
_CST_PIS_COFINS_ST = {"05"}

# CFOPs interestaduais (comecam com 2 ou 6)
_CFOP_INTERESTADUAL_PREFIXOS = ("2", "6")

# ──────────────────────────────────────────────
# Constantes — NCMs monofasicos por legislacao
# ──────────────────────────────────────────────
# Prefixos NCM (4 digitos) cujos produtos estao sujeitos a incidencia
# monofasica de PIS/COFINS conforme legislacao federal.
# Fonte: Lei 10.147/2000, Lei 10.485/2002, Lei 10.833/2003 Arts. 49-52,
#        Lei 10.865/2004, Lei 11.116/2005, Decreto 5.059/2004.

# Combustiveis e lubrificantes — Lei 10.865/2004, Lei 11.116/2005
_NCM_MONOFASICO_COMBUSTIVEIS = {
    "2207",  # Alcool etilico (etanol)
    "2710",  # Oleos de petroleo (gasolina, diesel, querosene)
    "2711",  # Gas de petroleo e hidrocarbonetos gasosos (GLP, GNV)
    "2713",  # Coque de petroleo
    "2714",  # Betumes e asfaltos naturais
    "3403",  # Preparacoes lubrificantes (exceto oleos)
    "3811",  # Preparacoes antidetonantes, aditivos
    "3826",  # Biodiesel e misturas
}

# Produtos farmaceuticos — Lei 10.147/2000, Lei 10.548/2002
_NCM_MONOFASICO_FARMACEUTICOS = {
    "3001",  # Glandulas e outros orgaos para usos opoterapicos
    "3002",  # Sangue humano; antissoros; vacinas
    "3003",  # Medicamentos (exceto posicao 3002/3005/3006)
    "3004",  # Medicamentos em doses ou acondicionados para venda
    "3005",  # Algodao, gaze, ataduras e artigos analogos
    "3006",  # Preparacoes e artigos farmaceuticos
}

# Produtos de perfumaria, toucador e higiene pessoal — Lei 10.147/2000
_NCM_MONOFASICO_HIGIENE = {
    "3303",  # Perfumes e aguas de colonia
    "3304",  # Produtos de beleza, maquiagem, cuidados da pele
    "3305",  # Preparacoes capilares
    "3306",  # Preparacoes para higiene bucal/dentaria
    "3307",  # Preparacoes para barbear, desodorantes
}

# Bebidas frias — Lei 10.833/2003 Arts. 49-52, Lei 13.097/2015
_NCM_MONOFASICO_BEBIDAS = {
    "2106",  # Preparacoes alimenticias (inclui xaropes p/ bebidas)
    "2201",  # Aguas minerais e aguas gaseificadas
    "2202",  # Aguas com adicao de acucar (refrigerantes, energeticos)
}

# Veiculos e autopecas — Lei 10.485/2002
_NCM_MONOFASICO_VEICULOS = {
    "8429",  # Bulldozers, niveladoras, etc.
    "8432",  # Maquinas e aparelhos agricolas
    "8433",  # Maquinas para colheita
    "8701",  # Tratores
    "8702",  # Veiculos para transporte coletivo (>10 pessoas)
    "8703",  # Automoveis de passageiros
    "8704",  # Veiculos para transporte de mercadorias
    "8705",  # Veiculos para usos especiais
    "8706",  # Chassis com motor
    "8711",  # Motocicletas e ciclos
}

# Autopecas — Lei 10.485/2002, Decreto 5.059/2004
# Principais posicoes (lista nao exaustiva -- abrange as mais comuns)
_NCM_MONOFASICO_AUTOPECAS = {
    "3917",  # Tubos de plastico (mangueiras automotivas)
    "4009",  # Tubos de borracha vulcanizada
    "4010",  # Correias transportadoras de borracha vulcanizada
    "4011",  # Pneumaticos (pneus) novos de borracha
    "4012",  # Pneus recauchutados/usados
    "4013",  # Camaras de ar de borracha
    "4504",  # Cortica aglomerada (juntas)
    "5910",  # Correias de transmissao de materias texteis
    "6306",  # Toldos (capotas)
    "6813",  # Guarnicoes de friccao (pastilhas de freio)
    "7007",  # Vidros de seguranca (para-brisas)
    "7009",  # Espelhos de vidro (retrovisores)
    "7014",  # Vidros para farois/sinais
    "7311",  # Recipientes para gas comprimido
    "7320",  # Molas e folhas de mola de ferro/aco
    "7325",  # Obras moldadas de ferro/aco (pecas fundidas)
    "7806",  # Obras de chumbo (baterias, balanceamento)
    "8301",  # Cadeados, fechaduras (fechaduras automotivas)
    "8302",  # Guarnicoes, ferragens
    "8307",  # Tubos flexiveis de metais comuns
    "8407",  # Motores de pistao de ignicao por centelha
    "8408",  # Motores de pistao de ignicao por compressao (diesel)
    "8409",  # Partes de motores (pistoes, bielas, etc.)
    "8413",  # Bombas (combustivel, agua)
    "8414",  # Bombas de ar, compressores
    "8415",  # Aparelhos de ar condicionado
    "8421",  # Centrifugadores, filtros
    "8425",  # Talhas, cadernais, macacos
    "8431",  # Partes de maquinas (8425-8430)
    "8481",  # Torneiras, valvulas
    "8482",  # Rolamentos
    "8483",  # Arvores de transmissao, engrenagens
    "8484",  # Juntas metaloplasticas
    "8505",  # Eletroimas (embreagens eletromagneticas)
    "8507",  # Acumuladores eletricos (baterias)
    "8511",  # Aparelhos de ignicao/arranque
    "8512",  # Aparelhos de iluminacao/sinalizacao
    "8527",  # Aparelhos receptores (radios automotivos)
    "8536",  # Aparelhos para interrupcao de circuitos (fusiveis)
    "8539",  # Lampadas eletricas (farois)
    "8544",  # Fios, cabos (chicotes eletricos)
    "8706",  # Chassis com motor
    "8707",  # Carrocerias para veiculos
    "8708",  # Partes e acessorios de veiculos automotores
    "8714",  # Partes e acessorios de motocicletas
    "9026",  # Instrumentos de medida (manometros)
    "9029",  # Contadores (velocimetros, tacometros)
    "9030",  # Osciloscopios, multimetros
    "9031",  # Instrumentos de medida e controle
    "9032",  # Instrumentos de regulacao automatica
    "9104",  # Relogios para paineis
    "9401",  # Assentos (bancos automotivos)
}

# Papel e papel imune — Lei 10.865/2004 Art. 28
_NCM_MONOFASICO_PAPEL = {
    "4801",  # Papel de jornal em rolos ou folhas
    "4802",  # Papel de imprensa nao revestido
}

# Unificar todos os NCMs monofasicos num unico set para consulta rapida
_NCM_MONOFASICO_TODOS: set[str] = set()
_NCM_MONOFASICO_TODOS.update(_NCM_MONOFASICO_COMBUSTIVEIS)
_NCM_MONOFASICO_TODOS.update(_NCM_MONOFASICO_FARMACEUTICOS)
_NCM_MONOFASICO_TODOS.update(_NCM_MONOFASICO_HIGIENE)
_NCM_MONOFASICO_TODOS.update(_NCM_MONOFASICO_BEBIDAS)
_NCM_MONOFASICO_TODOS.update(_NCM_MONOFASICO_VEICULOS)
_NCM_MONOFASICO_TODOS.update(_NCM_MONOFASICO_AUTOPECAS)
_NCM_MONOFASICO_TODOS.update(_NCM_MONOFASICO_PAPEL)

# Mapeamento de prefixo NCM -> categoria legivel (para mensagens)
_NCM_MONOFASICO_CATEGORIAS: dict[str, str] = {}
for _ncm in _NCM_MONOFASICO_COMBUSTIVEIS:
    _NCM_MONOFASICO_CATEGORIAS[_ncm] = "Combustivel/Lubrificante (Lei 10.865/04)"
for _ncm in _NCM_MONOFASICO_FARMACEUTICOS:
    _NCM_MONOFASICO_CATEGORIAS[_ncm] = "Farmaceutico (Lei 10.147/00)"
for _ncm in _NCM_MONOFASICO_HIGIENE:
    _NCM_MONOFASICO_CATEGORIAS[_ncm] = "Higiene/Perfumaria (Lei 10.147/00)"
for _ncm in _NCM_MONOFASICO_BEBIDAS:
    _NCM_MONOFASICO_CATEGORIAS[_ncm] = "Bebida Fria (Lei 10.833/03)"
for _ncm in _NCM_MONOFASICO_VEICULOS:
    _NCM_MONOFASICO_CATEGORIAS[_ncm] = "Veiculo (Lei 10.485/02)"
for _ncm in _NCM_MONOFASICO_AUTOPECAS:
    _NCM_MONOFASICO_CATEGORIAS[_ncm] = "Autopeca (Lei 10.485/02)"
for _ncm in _NCM_MONOFASICO_PAPEL:
    _NCM_MONOFASICO_CATEGORIAS[_ncm] = "Papel Imune (Lei 10.865/04)"


def _ncm_is_monofasico(ncm: str) -> str | None:
    """Verifica se um NCM pertence a categoria monofasica.

    Compara os 4 primeiros digitos do NCM (posicao/capitulo).
    Retorna a categoria se monofasico, None caso contrario.
    """
    if not ncm or len(ncm) < 4:
        return None
    prefixo = ncm[:4]
    return _NCM_MONOFASICO_CATEGORIAS.get(prefixo)


# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def validate_fiscal_semantics(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Executa validacoes semanticas fiscais nos registros C170.

    Regras implementadas:
    - Classificacao de cenario aliquota zero (ICMS, IPI, PIS/COFINS)
    - Cruzamento CST x CFOP
    - Validacao monofasica PIS/COFINS (CST 04 x NCM x aliquota)

    Se context.regime == SIMPLES_NACIONAL, pula regras de CST Tabela A.
    """
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    is_simples = False
    if context is not None:
        from ..services.context_builder import TaxRegime
        is_simples = context.regime == TaxRegime.SIMPLES_NACIONAL

    # Construir mapa COD_ITEM -> NCM a partir do cadastro 0200
    # 0200: pos 1=COD_ITEM, pos 7=COD_NCM (pode variar; campo NCM e posicao 7)
    item_ncm: dict[str, str] = {}
    for r in groups.get("0200", []):
        cod_item = get_field(r, "COD_ITEM")
        ncm = get_field(r, "COD_NCM")
        if cod_item and ncm:
            item_ncm[cod_item] = ncm

    for rec in groups.get("C170", []):
        if not is_simples:
            # Regras de CST Tabela A ICMS — só para Regime Normal
            errors.extend(_classify_zero_rate_icms(rec))
            errors.extend(_validate_cst_cfop(rec))
        errors.extend(_classify_zero_rate_ipi(rec))
        errors.extend(_classify_zero_rate_pis_cofins(rec))
        errors.extend(_validate_monofasico(rec, item_ncm))

    return errors


# ──────────────────────────────────────────────
# FRENTE 2 — Classificador de cenario aliquota zero
# ──────────────────────────────────────────────

def _classify_zero_rate_icms(record: SpedRecord) -> list[ValidationError]:
    """Classifica cenarios de ICMS com aliquota/valores zerados.

    Substitui o 'skip condition' cego por analise inteligente:
    - CST tributado + BC > 0 + ALIQ = 0 -> alerta forte
    - CST tributado + tudo zero -> alerta moderado
    - CST isento/NT + tudo zero -> OK (sem alerta)
    - CST diferimento + tudo zero -> OK (sem alerta)
    """
    cst_icms = get_field(record, "CST_ICMS")
    if not cst_icms:
        return []

    t = trib(cst_icms)
    vl_bc = to_float(get_field(record, "VL_BC_ICMS"))
    aliq = to_float(get_field(record, "ALIQ_ICMS"))
    vl_icms = to_float(get_field(record, "VL_ICMS"))

    # So analisa cenarios zerados
    if aliq > 0:
        return []

    # CST isento/NT/suspensao com tudo zero -> OK
    if t in CST_ISENTO_NT:
        return []

    # CST diferimento com tudo zero -> OK
    if t in CST_DIFERIMENTO:
        return []

    # CST tributado com aliquota zero
    if t in CST_TRIBUTADO:
        cfop = get_field(record, "CFOP")

        # Exportacao com aliquota zero e esperado
        if cfop in CFOP_EXPORTACAO:
            return []

        # Remessa/retorno com aliquota zero e comum
        if cfop in CFOP_REMESSA_RETORNO:
            return []

        if vl_bc > 0 and aliq == 0:
            # Caso 1: BC preenchida mas aliquota zero -> forte
            return [make_error(
                record, "ALIQ_ICMS", "CST_ALIQ_ZERO_FORTE",
                (
                    f"CST {cst_icms} indica tributacao, mas ALIQ_ICMS=0 com "
                    f"BC={vl_bc:.2f}. Verifique se o item deveria usar CST de "
                    f"isencao (40), nao-tributacao (41), suspensao (50) ou "
                    f"diferimento (51), ou se houve erro de parametrizacao."
                ),
                field_no=14,
                value=f"CST={cst_icms} BC={vl_bc:.2f} ALIQ=0",
            )]

        if vl_bc == 0 and aliq == 0 and vl_icms == 0:
            # Caso 2: Tudo zerado com CST tributado -> moderado
            return [make_error(
                record, "CST_ICMS", "CST_ALIQ_ZERO_MODERADO",
                (
                    f"CST {cst_icms} indica tributacao integral, mas base, "
                    f"aliquota e imposto estao zerados. Verifique se ha "
                    f"classificacao fiscal incorreta ou lancamento incompleto. "
                    f"Se a operacao for isenta, utilize CST 40; se nao "
                    f"tributada, CST 41; se suspensa, CST 50."
                ),
                field_no=10,
                value=f"CST={cst_icms} BC=0 ALIQ=0 ICMS=0",
            )]

    return []


def _classify_zero_rate_ipi(record: SpedRecord) -> list[ValidationError]:
    """Classifica cenarios de IPI com CST tributado e valores zerados."""
    cst_ipi = get_field(record, "CST_IPI")
    if not cst_ipi:
        return []

    vl_bc_ipi = to_float(get_field(record, "VL_BC_IPI"))
    _aliq_ipi = to_float(get_field(record, "ALIQ_IPI"))
    _vl_ipi = to_float(get_field(record, "VL_IPI"))

    if cst_ipi not in _CST_IPI_TRIBUTADO:
        return []

    # Aliquota 0% na TIPI e valida para CST tributado — so exige BC preenchida
    if vl_bc_ipi == 0:
        return [make_error(
            record, "CST_IPI", "IPI_CST_ALIQ_ZERO",
            (
                f"CST_IPI {cst_ipi} indica tributacao, mas VL_BC_IPI esta "
                f"zerado. Verifique se o CST deveria ser 02 (isento), "
                f"03 (nao tributado), 04 (imune) ou 05 (suspenso), ou se "
                f"a base de calculo do IPI esta faltando."
            ),
            field_no=20,
            value=f"CST_IPI={cst_ipi}",
        )]

    return []


def _classify_zero_rate_pis_cofins(record: SpedRecord) -> list[ValidationError]:
    """Classifica cenarios de PIS/COFINS com CST tributavel e valores zerados."""
    errors: list[ValidationError] = []

    # PIS: CST na posicao 24, BC=25, ALIQ=26, VL=29
    cst_pis = get_field(record, "CST_PIS")
    if cst_pis and cst_pis in _CST_PIS_COFINS_TRIBUTAVEL:
        vl_bc = to_float(get_field(record, "VL_BC_PIS"))
        aliq = to_float(get_field(record, "ALIQ_PIS"))
        vl_pis = to_float(get_field(record, "VL_PIS"))
        if vl_bc == 0 and aliq == 0 and vl_pis == 0:
            errors.append(make_error(
                record, "CST_PIS", "PIS_CST_ALIQ_ZERO",
                (
                    f"CST_PIS {cst_pis} indica operacao tributavel, mas base, "
                    f"aliquota e valor estao zerados. Verifique se o CST "
                    f"deveria ser 04 (nao tributado), 06 (aliquota zero), "
                    f"07 (isento) ou 08 (sem incidencia)."
                ),
                field_no=25,
                value=f"CST_PIS={cst_pis}",
            ))

    # COFINS: CST na posicao 30, BC=31, ALIQ=32, VL=35
    cst_cofins = get_field(record, "CST_COFINS")
    if cst_cofins and cst_cofins in _CST_PIS_COFINS_TRIBUTAVEL:
        vl_bc = to_float(get_field(record, "VL_BC_COFINS"))
        aliq = to_float(get_field(record, "ALIQ_COFINS"))
        vl_cofins = to_float(get_field(record, "VL_COFINS"))
        if vl_bc == 0 and aliq == 0 and vl_cofins == 0:
            errors.append(make_error(
                record, "CST_COFINS", "COFINS_CST_ALIQ_ZERO",
                (
                    f"CST_COFINS {cst_cofins} indica operacao tributavel, mas "
                    f"base, aliquota e valor estao zerados. Verifique se o "
                    f"CST deveria ser 04 (nao tributado), 06 (aliquota zero), "
                    f"07 (isento) ou 08 (sem incidencia)."
                ),
                field_no=31,
                value=f"CST_COFINS={cst_cofins}",
            ))

    return errors


# ──────────────────────────────────────────────
# FRENTE 1 — Cruzamento CST x CFOP
# ──────────────────────────────────────────────

def _validate_cst_cfop(record: SpedRecord) -> list[ValidationError]:
    """Valida compatibilidade semantica entre CST e CFOP.

    Regras:
    - CFOP de venda tributada + CST isento/NT -> alerta
    - CFOP interestadual + aliquota zero (CST tributado) -> alerta
    - CFOP de exportacao + CST tributado com aliquota > 0 -> alerta
    """
    cst_icms = get_field(record, "CST_ICMS")
    cfop = get_field(record, "CFOP")

    if not cst_icms or not cfop:
        return []

    t = trib(cst_icms)
    aliq = to_float(get_field(record, "ALIQ_ICMS"))
    errors: list[ValidationError] = []

    # REGRA 1: CFOP de venda + CST isento/NT (sem remessa/exportacao)
    if cfop in CFOP_VENDA and t in CST_ISENTO_NT:
        errors.append(make_error(
            record, "CST_ICMS", "CST_CFOP_INCOMPATIVEL",
            (
                f"CFOP {cfop} indica venda de mercadoria, mas CST {cst_icms} "
                f"indica isencao/nao-tributacao. Verifique se a operacao "
                f"possui beneficio fiscal que justifique a combinacao, ou se "
                f"o CST ou o CFOP estao incorretos."
            ),
            field_no=10,
            value=f"CST={cst_icms} CFOP={cfop}",
        ))

    # REGRA 2: CFOP interestadual + CST tributado + aliquota zero
    if (cfop[:1] in _CFOP_INTERESTADUAL_PREFIXOS
            and t in CST_TRIBUTADO
            and aliq == 0
            and cfop not in CFOP_REMESSA_RETORNO
            and cfop not in CFOP_DEVOLUCAO):
        errors.append(make_error(
            record, "ALIQ_ICMS", "CST_CFOP_INCOMPATIVEL",
            (
                f"Operacao interestadual (CFOP {cfop}) com CST tributado "
                f"{cst_icms} e aliquota zero. Operacoes interestaduais "
                f"normalmente possuem aliquota de 4%, 7% ou 12%. Verifique "
                f"se ha beneficio fiscal ou se a aliquota esta incorreta."
            ),
            field_no=14,
            value=f"CST={cst_icms} CFOP={cfop} ALIQ=0",
        ))

    # REGRA 3: CFOP de exportacao + CST tributado com aliquota > 0
    if cfop in CFOP_EXPORTACAO and t in CST_TRIBUTADO and aliq > 0:
        errors.append(make_error(
            record, "CST_ICMS", "CST_CFOP_INCOMPATIVEL",
            (
                f"CFOP {cfop} indica exportacao, mas CST {cst_icms} indica "
                f"tributacao com aliquota {aliq:.2f}%. Exportacoes "
                f"normalmente tem imunidade de ICMS. Verifique se o CST "
                f"deveria ser 41 (nao tributado) ou se o CFOP esta incorreto."
            ),
            field_no=10,
            value=f"CST={cst_icms} CFOP={cfop} ALIQ={aliq:.2f}",
        ))

    return errors


# ──────────────────────────────────────────────
# Validacao Monofasica PIS/COFINS
# ──────────────────────────────────────────────

def _validate_monofasico(
    record: SpedRecord,
    item_ncm: dict[str, str],
) -> list[ValidationError]:
    """Valida regras monofasicas PIS/COFINS cruzando CST x NCM x aliquota.

    Regras implementadas:
    1. CST 04 (monofasico) com aliquota > 0 -> erro
    2. CST 04 em item cujo NCM nao e monofasico -> alerta
    3. NCM monofasico com CST tributavel (01/02/03) em saida -> alerta
    4. CST 04 com VL_PIS/VL_COFINS > 0 -> erro (imposto ja recolhido na origem)
    5. CST 04 em operacao de entrada -> alerta (monofasico se aplica a revenda)

    Legislacao: Lei 10.147/00, Lei 10.485/02, Lei 10.833/03, Lei 10.865/04.
    """
    errors: list[ValidationError] = []

    cst_pis = get_field(record, "CST_PIS")
    cst_cofins = get_field(record, "CST_COFINS")
    cfop = get_field(record, "CFOP")

    # Obter NCM via COD_ITEM -> 0200
    cod_item = get_field(record, "COD_ITEM")
    ncm = item_ncm.get(cod_item, "")
    categoria = _ncm_is_monofasico(ncm) if ncm else None

    # Determinar se e operacao de entrada (CFOP 1/2/3xxx)
    is_entrada = cfop[:1] in ("1", "2", "3") if cfop else False

    # -- PIS --
    errors.extend(_validate_monofasico_tributo(
        record, cst_pis, "PIS", "VL_BC_PIS", "ALIQ_PIS", "VL_PIS",
        ncm, categoria, is_entrada,
    ))

    # -- COFINS --
    errors.extend(_validate_monofasico_tributo(
        record, cst_cofins, "COFINS", "VL_BC_COFINS", "ALIQ_COFINS", "VL_COFINS",
        ncm, categoria, is_entrada,
    ))

    return errors


def _validate_monofasico_tributo(
    record: SpedRecord,
    cst: str,
    tributo: str,
    field_bc: str,
    field_aliq: str,
    field_valor: str,
    ncm: str,
    categoria: str | None,
    is_entrada: bool,
) -> list[ValidationError]:
    """Valida regras monofasicas para um tributo (PIS ou COFINS)."""
    errors: list[ValidationError] = []
    if not cst:
        return errors

    aliq = to_float(get_field(record, field_aliq))
    valor = to_float(get_field(record, field_valor))
    field_name = f"CST_{tributo}"
    cod_item = get_field(record, "COD_ITEM")

    # Mapeamento de field name -> field_no para backward compat de make_error
    _FIELD_NO = {
        "ALIQ_PIS": 27, "VL_PIS": 30,
        "ALIQ_COFINS": 33, "VL_COFINS": 36,
    }
    fn_aliq = _FIELD_NO.get(field_aliq, 0)
    fn_valor = _FIELD_NO.get(field_valor, 0)

    # -- REGRA 1: CST 04 com aliquota > 0 -> erro --
    # Monofasico na revenda = aliquota zero obrigatoriamente
    if cst in _CST_PIS_COFINS_MONOFASICO and aliq > 0:
        errors.append(make_error(
            record, field_name, "MONOFASICO_ALIQ_INVALIDA",
            (
                f"CST_{tributo} {cst} indica operacao monofasica (revenda a "
                f"aliquota zero), mas ALIQ_{tributo}={aliq:.2f}%. Na revenda "
                f"de produto monofasico, a aliquota deve ser zero pois o "
                f"tributo ja foi recolhido pelo fabricante/importador."
            ),
            field_no=fn_aliq,
            value=f"CST_{tributo}={cst} ALIQ={aliq:.2f}%",
        ))

    # -- REGRA 2: CST 04 com valor de tributo > 0 -> erro --
    if cst in _CST_PIS_COFINS_MONOFASICO and valor > 0:
        errors.append(make_error(
            record, field_name, "MONOFASICO_VALOR_INDEVIDO",
            (
                f"CST_{tributo} {cst} indica operacao monofasica, mas "
                f"VL_{tributo}={valor:.2f}. O valor deve ser zero na revenda, "
                f"pois o {tributo} ja foi recolhido na etapa anterior "
                f"(fabricante ou importador)."
            ),
            field_no=fn_valor,
            value=f"CST_{tributo}={cst} VL={valor:.2f}",
        ))

    # -- REGRA 3: CST 04 em NCM nao monofasico -> alerta --
    if cst in _CST_PIS_COFINS_MONOFASICO and ncm and not categoria:
        errors.append(make_error(
            record, field_name, "MONOFASICO_NCM_INCOMPATIVEL",
            (
                f"CST_{tributo} {cst} indica operacao monofasica, mas o "
                f"NCM {ncm} (item {cod_item}) nao consta na lista de "
                f"produtos sujeitos a incidencia monofasica. Verifique se "
                f"o CST deveria ser 01 (tributacao normal), 06 (aliquota "
                f"zero) ou outro, ou se o NCM do produto esta correto."
            ),
            field_no=fn_aliq,
            value=f"CST_{tributo}={cst} NCM={ncm}",
        ))

    # -- REGRA 4: NCM monofasico com CST tributavel normal em saida -> alerta --
    if (categoria
            and cst in _CST_PIS_COFINS_TRIBUTAVEL
            and not is_entrada):
        errors.append(make_error(
            record, field_name, "MONOFASICO_CST_INCORRETO",
            (
                f"O item {cod_item} possui NCM {ncm} ({categoria}), sujeito "
                f"a incidencia monofasica de {tributo}. Na revenda, o "
                f"CST_{tributo} deveria ser 04 (monofasico - revenda a "
                f"aliquota zero), mas esta informado como {cst} (operacao "
                f"tributavel). Verifique a classificacao fiscal."
            ),
            field_no=fn_aliq,
            value=f"CST_{tributo}={cst} NCM={ncm}",
        ))

    # -- REGRA 5: CST 04 em operacao de entrada -> alerta informativo --
    # Na entrada de mercadoria monofasica, o CST depende do contexto:
    # industrializador usa credito (CST 50-56), revendedor nao tem credito.
    # CST 04 na entrada pode indicar erro de classificacao.
    if cst in _CST_PIS_COFINS_MONOFASICO and is_entrada:
        cfop_val = get_field(record, "CFOP")
        errors.append(make_error(
            record, field_name, "MONOFASICO_ENTRADA_CST04",
            (
                f"CST_{tributo} {cst} (monofasico) informado em operacao de "
                f"entrada (CFOP {cfop_val}). Na entrada, o CST "
                f"monofasico se aplica a aquisicao para revenda sem direito a "
                f"credito. Se a empresa for industrializadora com direito a "
                f"credito, o CST deveria ser 50-56. Verifique a natureza "
                f"da operacao e o regime da empresa."
            ),
            field_no=fn_aliq,
            value=f"CST_{tributo}={cst} CFOP={cfop_val}",
        ))

    return errors
