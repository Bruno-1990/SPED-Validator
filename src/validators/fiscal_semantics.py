"""Validação semântica fiscal: CST x alíquota zero, CST x CFOP, monofásicos.

Camada 3 do motor de validação — regras que verificam se o tratamento
tributário informado faz sentido fiscalmente, além da consistência numérica.
"""

from __future__ import annotations

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register

# ──────────────────────────────────────────────
# Constantes — CST
# ──────────────────────────────────────────────

# ICMS — CSTs que indicam tributação
_CST_ICMS_TRIBUTADO = {"00", "10", "20", "70", "90"}

# ICMS — CSTs que indicam isenção / não-tributação / suspensão
_CST_ICMS_ISENTO_NT = {"40", "41", "50", "60"}

# ICMS — CST diferimento
_CST_ICMS_DIFERIMENTO = {"51"}

# IPI — CSTs que indicam tributação (saída tributada / entrada com crédito)
_CST_IPI_TRIBUTADO = {"00", "01", "49", "50", "99"}

# PIS/COFINS — CSTs que indicam operação tributável (alíquota normal)
_CST_PIS_COFINS_TRIBUTAVEL = {"01", "02", "03", "49"}

# PIS/COFINS — CST monofásico (revenda a alíquota zero)
_CST_PIS_COFINS_MONOFASICO = {"04"}

# PIS/COFINS — CST substituição tributária PIS/COFINS
_CST_PIS_COFINS_ST = {"05"}

# ──────────────────────────────────────────────
# Constantes — NCMs monofásicos por legislação
# ──────────────────────────────────────────────
# Prefixos NCM (4 dígitos) cujos produtos estão sujeitos à incidência
# monofásica de PIS/COFINS conforme legislação federal.
# Fonte: Lei 10.147/2000, Lei 10.485/2002, Lei 10.833/2003 Arts. 49-52,
#        Lei 10.865/2004, Lei 11.116/2005, Decreto 5.059/2004.

# Combustíveis e lubrificantes — Lei 10.865/2004, Lei 11.116/2005
_NCM_MONOFASICO_COMBUSTIVEIS = {
    "2207",  # Álcool etílico (etanol)
    "2710",  # Óleos de petróleo (gasolina, diesel, querosene)
    "2711",  # Gás de petróleo e hidrocarbonetos gasosos (GLP, GNV)
    "2713",  # Coque de petróleo
    "2714",  # Betumes e asfaltos naturais
    "3403",  # Preparações lubrificantes (exceto óleos)
    "3811",  # Preparações antidetonantes, aditivos
    "3826",  # Biodiesel e misturas
}

# Produtos farmacêuticos — Lei 10.147/2000, Lei 10.548/2002
_NCM_MONOFASICO_FARMACEUTICOS = {
    "3001",  # Glândulas e outros órgãos para usos opoterápicos
    "3002",  # Sangue humano; antissoros; vacinas
    "3003",  # Medicamentos (exceto posição 3002/3005/3006)
    "3004",  # Medicamentos em doses ou acondicionados para venda
    "3005",  # Algodão, gaze, ataduras e artigos análogos
    "3006",  # Preparações e artigos farmacêuticos
}

# Produtos de perfumaria, toucador e higiene pessoal — Lei 10.147/2000
_NCM_MONOFASICO_HIGIENE = {
    "3303",  # Perfumes e águas de colônia
    "3304",  # Produtos de beleza, maquiagem, cuidados da pele
    "3305",  # Preparações capilares
    "3306",  # Preparações para higiene bucal/dentária
    "3307",  # Preparações para barbear, desodorantes
}

# Bebidas frias — Lei 10.833/2003 Arts. 49-52, Lei 13.097/2015
_NCM_MONOFASICO_BEBIDAS = {
    "2106",  # Preparações alimentícias (inclui xaropes p/ bebidas)
    "2201",  # Águas minerais e águas gaseificadas
    "2202",  # Águas com adição de açúcar (refrigerantes, energéticos)
}

# Veículos e autopeças — Lei 10.485/2002
_NCM_MONOFASICO_VEICULOS = {
    "8429",  # Bulldozers, niveladoras, etc.
    "8432",  # Máquinas e aparelhos agrícolas
    "8433",  # Máquinas para colheita
    "8701",  # Tratores
    "8702",  # Veículos para transporte coletivo (>10 pessoas)
    "8703",  # Automóveis de passageiros
    "8704",  # Veículos para transporte de mercadorias
    "8705",  # Veículos para usos especiais
    "8706",  # Chassis com motor
    "8711",  # Motocicletas e ciclos
}

# Autopeças — Lei 10.485/2002, Decreto 5.059/2004
# Principais posições (lista não exaustiva — abrange as mais comuns)
_NCM_MONOFASICO_AUTOPECAS = {
    "3917",  # Tubos de plástico (mangueiras automotivas)
    "4009",  # Tubos de borracha vulcanizada
    "4010",  # Correias transportadoras de borracha vulcanizada
    "4011",  # Pneumáticos (pneus) novos de borracha
    "4012",  # Pneus recauchutados/usados
    "4013",  # Câmaras de ar de borracha
    "4504",  # Cortiça aglomerada (juntas)
    "5910",  # Correias de transmissão de matérias têxteis
    "6306",  # Toldos (capotas)
    "6813",  # Guarnições de fricção (pastilhas de freio)
    "7007",  # Vidros de segurança (pára-brisas)
    "7009",  # Espelhos de vidro (retrovisores)
    "7014",  # Vidros para faróis/sinais
    "7311",  # Recipientes para gás comprimido
    "7320",  # Molas e folhas de mola de ferro/aço
    "7325",  # Obras moldadas de ferro/aço (peças fundidas)
    "7806",  # Obras de chumbo (baterias, balanceamento)
    "8301",  # Cadeados, fechaduras (fechaduras automotivas)
    "8302",  # Guarnições, ferragens
    "8307",  # Tubos flexíveis de metais comuns
    "8407",  # Motores de pistão de ignição por centelha
    "8408",  # Motores de pistão de ignição por compressão (diesel)
    "8409",  # Partes de motores (pistões, bielas, etc.)
    "8413",  # Bombas (combustível, água)
    "8414",  # Bombas de ar, compressores
    "8415",  # Aparelhos de ar condicionado
    "8421",  # Centrifugadores, filtros
    "8425",  # Talhas, cadernais, macacos
    "8431",  # Partes de máquinas (8425-8430)
    "8481",  # Torneiras, válvulas
    "8482",  # Rolamentos
    "8483",  # Árvores de transmissão, engrenagens
    "8484",  # Juntas metaloplásticas
    "8505",  # Eletroímãs (embreagens eletromagnéticas)
    "8507",  # Acumuladores elétricos (baterias)
    "8511",  # Aparelhos de ignição/arranque
    "8512",  # Aparelhos de iluminação/sinalização
    "8527",  # Aparelhos receptores (rádios automotivos)
    "8536",  # Aparelhos para interrupção de circuitos (fusíveis)
    "8539",  # Lâmpadas elétricas (faróis)
    "8544",  # Fios, cabos (chicotes elétricos)
    "8706",  # Chassis com motor
    "8707",  # Carrocerias para veículos
    "8708",  # Partes e acessórios de veículos automotores
    "8714",  # Partes e acessórios de motocicletas
    "9026",  # Instrumentos de medida (manômetros)
    "9029",  # Contadores (velocímetros, tacômetros)
    "9030",  # Osciloscópios, multímetros
    "9031",  # Instrumentos de medida e controle
    "9032",  # Instrumentos de regulação automática
    "9104",  # Relógios para painéis
    "9401",  # Assentos (bancos automotivos)
}

# Papel e papel imune — Lei 10.865/2004 Art. 28
_NCM_MONOFASICO_PAPEL = {
    "4801",  # Papel de jornal em rolos ou folhas
    "4802",  # Papel de imprensa não revestido
}

# Unificar todos os NCMs monofásicos num único set para consulta rápida
_NCM_MONOFASICO_TODOS: set[str] = set()
_NCM_MONOFASICO_TODOS.update(_NCM_MONOFASICO_COMBUSTIVEIS)
_NCM_MONOFASICO_TODOS.update(_NCM_MONOFASICO_FARMACEUTICOS)
_NCM_MONOFASICO_TODOS.update(_NCM_MONOFASICO_HIGIENE)
_NCM_MONOFASICO_TODOS.update(_NCM_MONOFASICO_BEBIDAS)
_NCM_MONOFASICO_TODOS.update(_NCM_MONOFASICO_VEICULOS)
_NCM_MONOFASICO_TODOS.update(_NCM_MONOFASICO_AUTOPECAS)
_NCM_MONOFASICO_TODOS.update(_NCM_MONOFASICO_PAPEL)

# Mapeamento de prefixo NCM → categoria legível (para mensagens)
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
    """Verifica se um NCM pertence a categoria monofásica.

    Compara os 4 primeiros dígitos do NCM (posição/capítulo).
    Retorna a categoria se monofásico, None caso contrário.
    """
    if not ncm or len(ncm) < 4:
        return None
    prefixo = ncm[:4]
    return _NCM_MONOFASICO_CATEGORIAS.get(prefixo)

# ──────────────────────────────────────────────
# Constantes — Famílias de CFOP
# ──────────────────────────────────────────────

# CFOPs de venda / receita de mercadoria (internos e interestaduais)
_CFOP_VENDA = {
    "5101", "5102", "5103", "5104", "5105", "5106", "5109", "5110",
    "5111", "5112", "5113", "5114", "5115", "5116", "5117", "5118",
    "5119", "5120", "5122", "5123", "5124", "5125",
    "6101", "6102", "6103", "6104", "6105", "6106", "6107", "6108",
    "6109", "6110", "6111", "6112", "6113", "6114", "6115", "6116",
    "6117", "6118", "6119", "6120", "6122", "6123", "6124", "6125",
}

# CFOPs de devolução (compra devolvida / venda devolvida)
_CFOP_DEVOLUCAO = {
    "1201", "1202", "1203", "1204", "1208", "1209", "1410", "1411",
    "1503", "1504",
    "2201", "2202", "2203", "2204", "2208", "2209", "2410", "2411",
    "2503", "2504",
    "5201", "5202", "5208", "5209", "5210", "5410", "5411",
    "5503", "5504",
    "6201", "6202", "6208", "6209", "6210", "6410", "6411",
    "6503", "6504",
}

# CFOPs de remessa / retorno (não geram receita/débito fiscal típico)
_CFOP_REMESSA_RETORNO = {
    "5901", "5902", "5903", "5904", "5905", "5906", "5907", "5908",
    "5909", "5910", "5911", "5912", "5913", "5914", "5915", "5916",
    "5917", "5918", "5919", "5920", "5921", "5922", "5923", "5924",
    "5925", "5926", "5927", "5928", "5929", "5949",
    "6901", "6902", "6903", "6904", "6905", "6906", "6907", "6908",
    "6909", "6910", "6911", "6912", "6913", "6914", "6915", "6916",
    "6917", "6918", "6919", "6920", "6921", "6922", "6923", "6924",
    "6925", "6926", "6927", "6928", "6929", "6949",
    "1901", "1902", "1903", "1904", "1905", "1906", "1907", "1908",
    "1909", "1910", "1911", "1912", "1913", "1914", "1915", "1916",
    "1917", "1918", "1919", "1920", "1921", "1922", "1923", "1924",
    "1925", "1926", "1949",
    "2901", "2902", "2903", "2904", "2905", "2906", "2907", "2908",
    "2909", "2910", "2911", "2912", "2913", "2914", "2915", "2916",
    "2917", "2918", "2919", "2920", "2921", "2922", "2923", "2924",
    "2925", "2949",
}

# CFOPs de exportação (alíquota zero é esperada)
_CFOP_EXPORTACAO = {
    "7101", "7102", "7105", "7106", "7127", "7201", "7202", "7210",
    "7211", "7251", "7301", "7358", "7501", "7504", "7551", "7553",
    "7556", "7651", "7654", "7667", "7930", "7949",
}

# CFOPs interstaduais (começam com 2 ou 6)
_CFOP_INTERESTADUAL_PREFIXOS = ("2", "6")


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _get(record: SpedRecord, idx: int) -> str:
    if idx < len(record.fields):
        return record.fields[idx].strip()
    return ""


def _float(value: str) -> float:
    if not value:
        return 0.0
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return 0.0


def _trib(cst: str) -> str:
    """Extrai a parte da tributação (últimos 2 dígitos) de um CST."""
    if len(cst) >= 2:
        return cst[-2:]
    return cst


def _make_error(
    record: SpedRecord,
    field_name: str,
    error_type: str,
    message: str,
    field_no: int = 0,
    value: str = "",
) -> ValidationError:
    return ValidationError(
        line_number=record.line_number,
        register=record.register,
        field_no=field_no,
        field_name=field_name,
        value=value,
        error_type=error_type,
        message=message,
    )


# ──────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────

def validate_fiscal_semantics(records: list[SpedRecord]) -> list[ValidationError]:
    """Executa validações semânticas fiscais nos registros C170.

    Regras implementadas:
    - Classificação de cenário alíquota zero (ICMS, IPI, PIS/COFINS)
    - Cruzamento CST x CFOP
    - Validação monofásica PIS/COFINS (CST 04 x NCM x alíquota)
    """
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    # Construir mapa COD_ITEM → NCM a partir do cadastro 0200
    # 0200: pos 1=COD_ITEM, pos 7=COD_NCM (pode variar; campo NCM é posição 7)
    item_ncm: dict[str, str] = {}
    for r in groups.get("0200", []):
        cod_item = _get(r, 1)
        ncm = _get(r, 7)
        if cod_item and ncm:
            item_ncm[cod_item] = ncm

    for rec in groups.get("C170", []):
        errors.extend(_classify_zero_rate_icms(rec))
        errors.extend(_classify_zero_rate_ipi(rec))
        errors.extend(_classify_zero_rate_pis_cofins(rec))
        errors.extend(_validate_cst_cfop(rec))
        errors.extend(_validate_monofasico(rec, item_ncm))

    return errors


# ──────────────────────────────────────────────
# FRENTE 2 — Classificador de cenário alíquota zero
# ──────────────────────────────────────────────

def _classify_zero_rate_icms(record: SpedRecord) -> list[ValidationError]:
    """Classifica cenários de ICMS com alíquota/valores zerados.

    Substitui o 'skip condition' cego por análise inteligente:
    - CST tributado + BC > 0 + ALIQ = 0 → alerta forte
    - CST tributado + tudo zero → alerta moderado
    - CST isento/NT + tudo zero → OK (sem alerta)
    - CST diferimento + tudo zero → OK (sem alerta)
    """
    cst_icms = _get(record, 9)
    if not cst_icms:
        return []

    trib = _trib(cst_icms)
    vl_bc = _float(_get(record, 12))
    aliq = _float(_get(record, 13))
    vl_icms = _float(_get(record, 14))

    # Só analisa cenários zerados
    if aliq > 0:
        return []

    # CST isento/NT/suspensão com tudo zero → OK
    if trib in _CST_ICMS_ISENTO_NT:
        return []

    # CST diferimento com tudo zero → OK
    if trib in _CST_ICMS_DIFERIMENTO:
        return []

    # CST tributado com alíquota zero
    if trib in _CST_ICMS_TRIBUTADO:
        cfop = _get(record, 10)

        # Exportação com alíquota zero é esperado
        if cfop in _CFOP_EXPORTACAO:
            return []

        # Remessa/retorno com alíquota zero é comum
        if cfop in _CFOP_REMESSA_RETORNO:
            return []

        if vl_bc > 0 and aliq == 0:
            # Caso 1: BC preenchida mas alíquota zero → forte
            return [_make_error(
                record, "ALIQ_ICMS", "CST_ALIQ_ZERO_FORTE",
                (
                    f"CST {cst_icms} indica tributação, mas ALIQ_ICMS=0 com "
                    f"BC={vl_bc:.2f}. Verifique se o item deveria usar CST de "
                    f"isenção (40), não-tributação (41), suspensão (50) ou "
                    f"diferimento (51), ou se houve erro de parametrização."
                ),
                field_no=14,
                value=f"CST={cst_icms} BC={vl_bc:.2f} ALIQ=0",
            )]

        if vl_bc == 0 and aliq == 0 and vl_icms == 0:
            # Caso 2: Tudo zerado com CST tributado → moderado
            return [_make_error(
                record, "CST_ICMS", "CST_ALIQ_ZERO_MODERADO",
                (
                    f"CST {cst_icms} indica tributação integral, mas base, "
                    f"alíquota e imposto estão zerados. Verifique se há "
                    f"classificação fiscal incorreta ou lançamento incompleto. "
                    f"Se a operação for isenta, utilize CST 40; se não "
                    f"tributada, CST 41; se suspensa, CST 50."
                ),
                field_no=10,
                value=f"CST={cst_icms} BC=0 ALIQ=0 ICMS=0",
            )]

    return []


def _classify_zero_rate_ipi(record: SpedRecord) -> list[ValidationError]:
    """Classifica cenários de IPI com CST tributado e valores zerados."""
    cst_ipi = _get(record, 19)
    if not cst_ipi:
        return []

    vl_bc_ipi = _float(_get(record, 21))
    aliq_ipi = _float(_get(record, 22))
    vl_ipi = _float(_get(record, 23))

    if cst_ipi not in _CST_IPI_TRIBUTADO:
        return []

    if vl_bc_ipi == 0 and aliq_ipi == 0 and vl_ipi == 0:
        return [_make_error(
            record, "CST_IPI", "IPI_CST_ALIQ_ZERO",
            (
                f"CST_IPI {cst_ipi} indica tributação, mas base, alíquota "
                f"e valor de IPI estão zerados. Verifique se o CST deveria "
                f"ser 02 (isento), 03 (não tributado), 04 (imune) ou "
                f"05 (suspenso)."
            ),
            field_no=20,
            value=f"CST_IPI={cst_ipi}",
        )]

    return []


def _classify_zero_rate_pis_cofins(record: SpedRecord) -> list[ValidationError]:
    """Classifica cenários de PIS/COFINS com CST tributável e valores zerados."""
    errors: list[ValidationError] = []

    # PIS: CST na posição 24, BC=25, ALIQ=26, VL=29
    cst_pis = _get(record, 24)
    if cst_pis and cst_pis in _CST_PIS_COFINS_TRIBUTAVEL:
        vl_bc = _float(_get(record, 25))
        aliq = _float(_get(record, 26))
        vl_pis = _float(_get(record, 29))
        if vl_bc == 0 and aliq == 0 and vl_pis == 0:
            errors.append(_make_error(
                record, "CST_PIS", "PIS_CST_ALIQ_ZERO",
                (
                    f"CST_PIS {cst_pis} indica operação tributável, mas base, "
                    f"alíquota e valor estão zerados. Verifique se o CST "
                    f"deveria ser 04 (não tributado), 06 (alíquota zero), "
                    f"07 (isento) ou 08 (sem incidência)."
                ),
                field_no=25,
                value=f"CST_PIS={cst_pis}",
            ))

    # COFINS: CST na posição 30, BC=31, ALIQ=32, VL=35
    cst_cofins = _get(record, 30)
    if cst_cofins and cst_cofins in _CST_PIS_COFINS_TRIBUTAVEL:
        vl_bc = _float(_get(record, 31))
        aliq = _float(_get(record, 32))
        vl_cofins = _float(_get(record, 35))
        if vl_bc == 0 and aliq == 0 and vl_cofins == 0:
            errors.append(_make_error(
                record, "CST_COFINS", "COFINS_CST_ALIQ_ZERO",
                (
                    f"CST_COFINS {cst_cofins} indica operação tributável, mas "
                    f"base, alíquota e valor estão zerados. Verifique se o "
                    f"CST deveria ser 04 (não tributado), 06 (alíquota zero), "
                    f"07 (isento) ou 08 (sem incidência)."
                ),
                field_no=31,
                value=f"CST_COFINS={cst_cofins}",
            ))

    return errors


# ──────────────────────────────────────────────
# FRENTE 1 — Cruzamento CST x CFOP
# ──────────────────────────────────────────────

def _validate_cst_cfop(record: SpedRecord) -> list[ValidationError]:
    """Valida compatibilidade semântica entre CST e CFOP.

    Regras:
    - CFOP de venda tributada + CST isento/NT → alerta
    - CFOP interestadual + alíquota zero (CST tributado) → alerta
    - CFOP de exportação + CST tributado com alíquota > 0 → alerta
    """
    cst_icms = _get(record, 9)
    cfop = _get(record, 10)

    if not cst_icms or not cfop:
        return []

    trib = _trib(cst_icms)
    aliq = _float(_get(record, 13))
    errors: list[ValidationError] = []

    # REGRA 1: CFOP de venda + CST isento/NT (sem remessa/exportação)
    if cfop in _CFOP_VENDA and trib in _CST_ICMS_ISENTO_NT:
        errors.append(_make_error(
            record, "CST_ICMS", "CST_CFOP_INCOMPATIVEL",
            (
                f"CFOP {cfop} indica venda de mercadoria, mas CST {cst_icms} "
                f"indica isenção/não-tributação. Verifique se a operação "
                f"possui benefício fiscal que justifique a combinação, ou se "
                f"o CST ou o CFOP estão incorretos."
            ),
            field_no=10,
            value=f"CST={cst_icms} CFOP={cfop}",
        ))

    # REGRA 2: CFOP interestadual + CST tributado + alíquota zero
    if (cfop[:1] in _CFOP_INTERESTADUAL_PREFIXOS
            and trib in _CST_ICMS_TRIBUTADO
            and aliq == 0
            and cfop not in _CFOP_REMESSA_RETORNO
            and cfop not in _CFOP_DEVOLUCAO):
        errors.append(_make_error(
            record, "ALIQ_ICMS", "CST_CFOP_INCOMPATIVEL",
            (
                f"Operação interestadual (CFOP {cfop}) com CST tributado "
                f"{cst_icms} e alíquota zero. Operações interestaduais "
                f"normalmente possuem alíquota de 4%, 7% ou 12%. Verifique "
                f"se há benefício fiscal ou se a alíquota está incorreta."
            ),
            field_no=14,
            value=f"CST={cst_icms} CFOP={cfop} ALIQ=0",
        ))

    # REGRA 3: CFOP de exportação + CST tributado com alíquota > 0
    if cfop in _CFOP_EXPORTACAO and trib in _CST_ICMS_TRIBUTADO and aliq > 0:
        errors.append(_make_error(
            record, "CST_ICMS", "CST_CFOP_INCOMPATIVEL",
            (
                f"CFOP {cfop} indica exportação, mas CST {cst_icms} indica "
                f"tributação com alíquota {aliq:.2f}%. Exportações "
                f"normalmente têm imunidade de ICMS. Verifique se o CST "
                f"deveria ser 41 (não tributado) ou se o CFOP está incorreto."
            ),
            field_no=10,
            value=f"CST={cst_icms} CFOP={cfop} ALIQ={aliq:.2f}",
        ))

    return errors


# ──────────────────────────────────────────────
# Validação Monofásica PIS/COFINS
# ──────────────────────────────────────────────

def _validate_monofasico(
    record: SpedRecord,
    item_ncm: dict[str, str],
) -> list[ValidationError]:
    """Valida regras monofásicas PIS/COFINS cruzando CST x NCM x alíquota.

    Regras implementadas:
    1. CST 04 (monofásico) com alíquota > 0 → erro
    2. CST 04 em item cujo NCM não é monofásico → alerta
    3. NCM monofásico com CST tributável (01/02/03) em saída → alerta
    4. CST 04 com VL_PIS/VL_COFINS > 0 → erro (imposto já recolhido na origem)
    5. CST 04 em operação de entrada → alerta (monofásico se aplica à revenda)

    Legislação: Lei 10.147/00, Lei 10.485/02, Lei 10.833/03, Lei 10.865/04.
    """
    errors: list[ValidationError] = []

    cst_pis = _get(record, 24)
    cst_cofins = _get(record, 30)
    cfop = _get(record, 10)

    # Obter NCM via COD_ITEM → 0200
    cod_item = _get(record, 2)
    ncm = item_ncm.get(cod_item, "")
    categoria = _ncm_is_monofasico(ncm) if ncm else None

    # Determinar se é operação de entrada (CFOP 1/2/3xxx)
    is_entrada = cfop[:1] in ("1", "2", "3") if cfop else False

    # ── PIS ──
    errors.extend(_validate_monofasico_tributo(
        record, cst_pis, "PIS", 25, 26, 29,
        ncm, categoria, is_entrada,
    ))

    # ── COFINS ──
    errors.extend(_validate_monofasico_tributo(
        record, cst_cofins, "COFINS", 31, 32, 35,
        ncm, categoria, is_entrada,
    ))

    return errors


def _validate_monofasico_tributo(
    record: SpedRecord,
    cst: str,
    tributo: str,
    pos_bc: int,
    pos_aliq: int,
    pos_valor: int,
    ncm: str,
    categoria: str | None,
    is_entrada: bool,
) -> list[ValidationError]:
    """Valida regras monofásicas para um tributo (PIS ou COFINS)."""
    errors: list[ValidationError] = []
    if not cst:
        return errors

    aliq = _float(_get(record, pos_aliq))
    valor = _float(_get(record, pos_valor))
    field_name = f"CST_{tributo}"
    cod_item = _get(record, 2)

    # ── REGRA 1: CST 04 com alíquota > 0 → erro ──
    # Monofásico na revenda = alíquota zero obrigatoriamente
    if cst in _CST_PIS_COFINS_MONOFASICO and aliq > 0:
        errors.append(_make_error(
            record, field_name, "MONOFASICO_ALIQ_INVALIDA",
            (
                f"CST_{tributo} {cst} indica operação monofásica (revenda a "
                f"alíquota zero), mas ALIQ_{tributo}={aliq:.2f}%. Na revenda "
                f"de produto monofásico, a alíquota deve ser zero pois o "
                f"tributo já foi recolhido pelo fabricante/importador."
            ),
            field_no=pos_aliq + 1,
            value=f"CST_{tributo}={cst} ALIQ={aliq:.2f}%",
        ))

    # ── REGRA 2: CST 04 com valor de tributo > 0 → erro ──
    if cst in _CST_PIS_COFINS_MONOFASICO and valor > 0:
        errors.append(_make_error(
            record, field_name, "MONOFASICO_VALOR_INDEVIDO",
            (
                f"CST_{tributo} {cst} indica operação monofásica, mas "
                f"VL_{tributo}={valor:.2f}. O valor deve ser zero na revenda, "
                f"pois o {tributo} já foi recolhido na etapa anterior "
                f"(fabricante ou importador)."
            ),
            field_no=pos_valor + 1,
            value=f"CST_{tributo}={cst} VL={valor:.2f}",
        ))

    # ── REGRA 3: CST 04 em NCM não monofásico → alerta ──
    if cst in _CST_PIS_COFINS_MONOFASICO and ncm and not categoria:
        errors.append(_make_error(
            record, field_name, "MONOFASICO_NCM_INCOMPATIVEL",
            (
                f"CST_{tributo} {cst} indica operação monofásica, mas o "
                f"NCM {ncm} (item {cod_item}) não consta na lista de "
                f"produtos sujeitos à incidência monofásica. Verifique se "
                f"o CST deveria ser 01 (tributação normal), 06 (alíquota "
                f"zero) ou outro, ou se o NCM do produto está correto."
            ),
            field_no=pos_aliq + 1,
            value=f"CST_{tributo}={cst} NCM={ncm}",
        ))

    # ── REGRA 4: NCM monofásico com CST tributável normal em saída → alerta ──
    if (categoria
            and cst in _CST_PIS_COFINS_TRIBUTAVEL
            and not is_entrada):
        errors.append(_make_error(
            record, field_name, "MONOFASICO_CST_INCORRETO",
            (
                f"O item {cod_item} possui NCM {ncm} ({categoria}), sujeito "
                f"à incidência monofásica de {tributo}. Na revenda, o "
                f"CST_{tributo} deveria ser 04 (monofásico - revenda a "
                f"alíquota zero), mas está informado como {cst} (operação "
                f"tributável). Verifique a classificação fiscal."
            ),
            field_no=pos_aliq + 1,
            value=f"CST_{tributo}={cst} NCM={ncm}",
        ))

    # ── REGRA 5: CST 04 em operação de entrada → alerta informativo ──
    # Na entrada de mercadoria monofásica, o CST depende do contexto:
    # industrializador usa crédito (CST 50-56), revendedor não tem crédito.
    # CST 04 na entrada pode indicar erro de classificação.
    if cst in _CST_PIS_COFINS_MONOFASICO and is_entrada:
        errors.append(_make_error(
            record, field_name, "MONOFASICO_ENTRADA_CST04",
            (
                f"CST_{tributo} {cst} (monofásico) informado em operação de "
                f"entrada (CFOP {_get(record, 10)}). Na entrada, o CST "
                f"monofásico se aplica à aquisição para revenda sem direito a "
                f"crédito. Se a empresa for industrializadora com direito a "
                f"crédito, o CST deveria ser 50-56. Verifique a natureza "
                f"da operação e o regime da empresa."
            ),
            field_no=pos_aliq + 1,
            value=f"CST_{tributo}={cst} CFOP={_get(record, 10)}",
        ))

    return errors
