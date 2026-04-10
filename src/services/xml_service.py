"""Serviço de cruzamento NF-e XML x SPED EFD.

Parseia XMLs de NF-e, salva no banco e cruza com registros C100/C170/0200.
17 regras de cruzamento (XML001-XML017).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Namespace da NF-e
_NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}


# ──────────────────────────────────────────────
# Normalização (Etapa 0)
# ──────────────────────────────────────────────

def _norm_chave(chave: str) -> str:
    return re.sub(r"\D", "", (chave or "").strip())


def _norm_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", (cnpj or "")).zfill(14)


def _norm_cfop(cfop: str) -> str:
    return re.sub(r"\D", "", (cfop or "").strip())[:4]


def _norm_cst(cst: str) -> str:
    c = (cst or "").strip()
    return c.zfill(3) if len(c) == 2 else c


def _norm_ncm(ncm: str) -> str:
    return re.sub(r"\D", "", (ncm or "").strip())[:8]


def _norm_date_iso(dt_str: str) -> str:
    """ISO 8601 → DDMMAAAA."""
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%d%m%Y")
    except (ValueError, TypeError):
        return (dt_str or "")[:10].replace("-", "")


def _parse_ddmmaaaa(s: str) -> date | None:
    """DDMMAAAA → date."""
    s = (s or "").strip()
    if len(s) != 8:
        return None
    try:
        return date(int(s[4:8]), int(s[2:4]), int(s[0:2]))
    except (ValueError, TypeError):
        return None


def _classificar_periodo(dh_emissao_iso: str, dt_ini: str, dt_fin: str) -> str:
    """Classifica a NF-e em relacao ao periodo do SPED.

    Retorna:
      "dentro"      — dentro do periodo ou ate 1 mes antes (aceito sem perguntar)
      "fora"        — 2+ meses antes ou qualquer mes apos o periodo (requer confirmacao)
      "indeterminado" — nao consegue determinar (tratado como dentro)
    """
    emissao_ddmmaaaa = _norm_date_iso(dh_emissao_iso)
    emissao_date = _parse_ddmmaaaa(emissao_ddmmaaaa)
    ini_date = _parse_ddmmaaaa(dt_ini)
    fin_date = _parse_ddmmaaaa(dt_fin)
    if not emissao_date or not ini_date or not fin_date:
        return "indeterminado"

    # Dentro do periodo exato
    if ini_date <= emissao_date <= fin_date:
        return "dentro"

    # Ate 1 mes antes do inicio: aceito sem perguntar
    # Calcula 1 mes antes de dt_ini
    mes_anterior_mes = ini_date.month - 1 if ini_date.month > 1 else 12
    mes_anterior_ano = ini_date.year if ini_date.month > 1 else ini_date.year - 1
    try:
        limite_1_mes = date(mes_anterior_ano, mes_anterior_mes, 1)
    except ValueError:
        limite_1_mes = ini_date
    if limite_1_mes <= emissao_date < ini_date:
        return "dentro"  # periodo -1 aceito sem questionar

    # Qualquer data apos o periodo OU 2+ meses antes → fora
    return "fora"


def _dentro_periodo(dh_emissao_iso: str, dt_ini: str, dt_fin: str) -> bool:
    """Compat: retorna True se classificacao e 'dentro' ou 'indeterminado'."""
    return _classificar_periodo(dh_emissao_iso, dt_ini, dt_fin) != "fora"


def _fmt_ddmmaaaa(s: str) -> str:
    """DDMMAAAA → DD/MM/AAAA."""
    if len(s) != 8:
        return s
    return f"{s[0:2]}/{s[2:4]}/{s[4:8]}"


def _to_float(val) -> float:
    if val is None:
        return 0.0
    try:
        return round(float(val), 2)
    except (ValueError, TypeError):
        return 0.0


def _find(el, path_ns: str, path_plain: str):
    """Busca elemento com namespace, fallback sem namespace. Evita DeprecationWarning."""
    result = el.find(path_ns, _NS)
    if result is None:
        result = el.find(path_plain)
    return result


def _text(el, path: str, ns: dict | None = None) -> str:
    """Extrai texto de um elemento XML, retornando '' se não encontrado."""
    node = el.find(path, ns or _NS)
    return (node.text or "").strip() if node is not None else ""


# ──────────────────────────────────────────────
# Parser de XML NF-e
# ──────────────────────────────────────────────

def parse_nfe_xml(xml_bytes: bytes) -> dict | None:
    """Parseia XML de NF-e para dict estruturado.

    Aceita <nfeProc> (com protocolo) e <NFe> (sem protocolo).
    Retorna None se XML malformado.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        logger.warning("XML malformado — não é XML válido")
        return None

    # Detectar envelope
    tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag

    if tag == "nfeProc":
        nfe_el = _find(root, "nfe:NFe", "NFe")
        prot_el = _find(root, "nfe:protNFe", "protNFe")
    elif tag == "NFe":
        nfe_el = root
        prot_el = None
    else:
        # Tentar sem namespace
        nfe_el = root.find(".//NFe") or root
        prot_el = root.find(".//protNFe")

    if nfe_el is None:
        logger.warning("XML sem elemento NFe")
        return None

    inf = _find(nfe_el, "nfe:infNFe", "infNFe")
    if inf is None:
        logger.warning("XML sem infNFe")
        return None

    # Identificação
    ide = _find(inf, "nfe:ide", "ide")
    emit = _find(inf, "nfe:emit", "emit")
    dest = _find(inf, "nfe:dest", "dest")
    total_el = _find(inf, "nfe:total", "total")
    icms_tot = None
    if total_el is not None:
        icms_tot = _find(total_el, "nfe:ICMSTot", "ICMSTot")

    chave = (inf.attrib.get("Id", "") or "").replace("NFe", "")
    if not chave and ide is not None:
        chave = _text(ide, "nfe:cNF", _NS) or _text(ide, "cNF")

    result = {
        "chave_nfe": _norm_chave(chave),
        "numero_nfe": _text(ide, "nfe:nNF", _NS) or _text(ide, "nNF") if ide else "",
        "serie": _text(ide, "nfe:serie", _NS) or _text(ide, "serie") if ide else "",
        "dh_emissao": _text(ide, "nfe:dhEmi", _NS) or _text(ide, "dhEmi") if ide else "",
        "cnpj_emitente": _norm_cnpj(
            _text(emit, "nfe:CNPJ", _NS) or _text(emit, "CNPJ") if emit else ""
        ),
        "cnpj_destinatario": _norm_cnpj(
            _text(dest, "nfe:CNPJ", _NS) or _text(dest, "CNPJ") if dest else ""
        ),
        "crt_emitente": _text(emit, "nfe:CRT", _NS) or _text(emit, "CRT") if emit else "",
        "totais": {},
        "itens": [],
        "prot_cstat": "",
    }

    # Totais
    if icms_tot is not None:
        for campo in ["vBC", "vICMS", "vICMSDeson", "vBCST", "vST", "vFCP",
                       "vFCPST", "vFCPUFDest", "vICMSUFDest", "vICMSUFRemet",
                       "vProd", "vFrete", "vSeg", "vDesc", "vII", "vIPI",
                       "vIPIDevol", "vPIS", "vCOFINS", "vOutro", "vNF"]:
            val = _text(icms_tot, f"nfe:{campo}", _NS) or _text(icms_tot, campo)
            result["totais"][campo] = _to_float(val)

    result["vl_doc"] = result["totais"].get("vNF", 0.0)
    result["vl_icms"] = result["totais"].get("vICMS", 0.0)
    result["vl_icms_st"] = result["totais"].get("vST", 0.0)
    result["vl_ipi"] = result["totais"].get("vIPI", 0.0)
    result["vl_pis"] = result["totais"].get("vPIS", 0.0)
    result["vl_cofins"] = result["totais"].get("vCOFINS", 0.0)

    # Itens
    dets = inf.findall("nfe:det", _NS) or inf.findall("det")
    for det in dets:
        prod = _find(det, "nfe:prod", "prod")
        imp = _find(det, "nfe:imposto", "imposto")

        item = {
            "num_item": int(det.attrib.get("nItem", 0)),
            "cod_produto": _text(prod, "nfe:cProd", _NS) or _text(prod, "cProd") if prod else "",
            "ncm": _norm_ncm(_text(prod, "nfe:NCM", _NS) or _text(prod, "NCM") if prod else ""),
            "cfop": _norm_cfop(_text(prod, "nfe:CFOP", _NS) or _text(prod, "CFOP") if prod else ""),
            "vl_prod": _to_float(_text(prod, "nfe:vProd", _NS) or _text(prod, "vProd") if prod else "0"),
            "vl_desc": _to_float(_text(prod, "nfe:vDesc", _NS) or _text(prod, "vDesc") if prod else "0"),
        }

        # Tributos ICMS
        icms_group = None
        if imp is not None:
            icms_el = _find(imp, "nfe:ICMS", "ICMS")
            if icms_el is not None:
                # ICMS tem um filho dinâmico (ICMS00, ICMS10, ICMSSN101, etc.)
                for child in icms_el:
                    icms_group = child
                    break

        if icms_group is not None:
            orig = _text(icms_group, "nfe:orig", _NS) or _text(icms_group, "orig")
            cst = _text(icms_group, "nfe:CST", _NS) or _text(icms_group, "CST")
            csosn = _text(icms_group, "nfe:CSOSN", _NS) or _text(icms_group, "CSOSN")
            item["cst_icms"] = _norm_cst(f"{orig}{csosn}" if csosn else f"{orig}{cst}")
            item["vbc_icms"] = _to_float(
                _text(icms_group, "nfe:vBC", _NS) or _text(icms_group, "vBC")
            )
            item["aliq_icms"] = _to_float(
                _text(icms_group, "nfe:pICMS", _NS) or _text(icms_group, "pICMS")
            )
            item["vl_icms"] = _to_float(
                _text(icms_group, "nfe:vICMS", _NS) or _text(icms_group, "vICMS")
            )
        else:
            item.update({"cst_icms": "", "vbc_icms": 0.0, "aliq_icms": 0.0, "vl_icms": 0.0})

        # IPI
        if imp is not None:
            ipi_el = _find(imp, "nfe:IPI", "IPI")
            if ipi_el is not None:
                ipi_trib = _find(ipi_el, "nfe:IPITrib", "IPITrib")
                if ipi_trib is not None:
                    item["cst_ipi"] = _text(ipi_trib, "nfe:CST", _NS) or _text(ipi_trib, "CST")
                    item["vl_ipi"] = _to_float(
                        _text(ipi_trib, "nfe:vIPI", _NS) or _text(ipi_trib, "vIPI")
                    )
                else:
                    ipi_nt = _find(ipi_el, "nfe:IPINT", "IPINT")
                    item["cst_ipi"] = _text(ipi_nt, "nfe:CST", _NS) or _text(ipi_nt, "CST") if ipi_nt else ""
                    item["vl_ipi"] = 0.0
            else:
                item.update({"cst_ipi": "", "vl_ipi": 0.0})
        else:
            item.update({"cst_ipi": "", "vl_ipi": 0.0})

        # PIS/COFINS simplificado
        item.update({"cst_pis": "", "vl_pis": 0.0, "cst_cofins": "", "vl_cofins": 0.0})

        result["itens"].append(item)

    result["qtd_itens"] = len(result["itens"])

    # Protocolo
    if prot_el is not None:
        inf_prot = _find(prot_el, "nfe:infProt", "infProt")
        if inf_prot is not None:
            result["prot_cstat"] = _text(inf_prot, "nfe:cStat", _NS) or _text(inf_prot, "cStat")
            prot_chave = _text(inf_prot, "nfe:chNFe", _NS) or _text(inf_prot, "chNFe")
            if prot_chave and not result["chave_nfe"]:
                result["chave_nfe"] = _norm_chave(prot_chave)

    return result


# ──────────────────────────────────────────────
# Upload batch de XMLs
# ──────────────────────────────────────────────

def upload_nfe_xmls(
    db: sqlite3.Connection,
    file_id: int,
    xml_files: list[tuple[str, bytes]],
    period_start: str | None = None,
    period_end: str | None = None,
    modo_periodo: str = "validar",
) -> dict:
    """Parseia e salva batch de XMLs vinculados a um SPED.

    Args:
        period_start: DT_INI do SPED (DDMMAAAA). Se fornecido, valida periodo.
        period_end: DT_FIN do SPED (DDMMAAAA). Se fornecido, valida periodo.
        modo_periodo: "validar" (default) para-se houver fora de periodo,
                      "importar_todos" importa tudo, "pular_fora" pula fora de periodo.

    Retorna resumo com status "ok" ou "periodo_pendente".
    """
    stats: dict = {
        "status": "ok",
        "total": 0, "autorizadas": 0, "canceladas": 0,
        "duplicadas": 0, "invalidos": 0,
    }
    check_periodo = bool(period_start and period_end)
    fora_periodo_list: list[dict] = []
    # XMLs parseados que passaram validacao basica (para inserir depois)
    to_insert: list[tuple[str, dict]] = []

    for filename, xml_bytes in xml_files:
        stats["total"] += 1

        parsed = parse_nfe_xml(xml_bytes)
        if parsed is None:
            stats["invalidos"] += 1
            continue

        chave = parsed["chave_nfe"]
        if not chave or len(chave) != 44:
            stats["invalidos"] += 1
            continue

        # Checar duplicata (mesma chave no mesmo SPED)
        existing = db.execute(
            "SELECT id, status FROM nfe_xmls WHERE file_id = ? AND chave_nfe = ?",
            (file_id, chave),
        ).fetchone()

        if existing:
            stats["duplicadas"] += 1
            continue

        # Verificar periodo
        if check_periodo:
            dh = parsed.get("dh_emissao", "")
            if dh and not _dentro_periodo(dh, period_start, period_end):
                emissao_fmt = _norm_date_iso(dh)
                fora_periodo_list.append({
                    "filename": filename,
                    "chave_nfe": chave,
                    "dh_emissao": _fmt_ddmmaaaa(emissao_fmt) if len(emissao_fmt) == 8 else dh[:10],
                })
                if modo_periodo == "pular_fora":
                    continue
                # modo "validar": coleta tudo, depois decide
                # modo "importar_todos": insere normalmente (cai no to_insert)

        to_insert.append((filename, parsed))

    # Se modo "validar" e ha NF-e fora de periodo, retornar sem inserir
    if modo_periodo == "validar" and fora_periodo_list:
        stats["status"] = "periodo_pendente"
        stats["fora_periodo"] = fora_periodo_list
        stats["dentro_periodo_count"] = len(to_insert) - len(fora_periodo_list)
        stats["period_start_fmt"] = _fmt_ddmmaaaa(period_start) if period_start else ""
        stats["period_end_fmt"] = _fmt_ddmmaaaa(period_end) if period_end else ""
        return stats

    # Inserir XMLs validos
    for filename, parsed in to_insert:
        chave = parsed["chave_nfe"]

        db.execute(
            """INSERT INTO nfe_xmls
               (file_id, chave_nfe, numero_nfe, serie, cnpj_emitente,
                cnpj_destinatario, dh_emissao, vl_doc, vl_icms, vl_icms_st,
                vl_ipi, vl_pis, vl_cofins, qtd_itens, prot_cstat, status, parsed_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)""",
            (
                file_id, chave, parsed["numero_nfe"], parsed["serie"],
                parsed["cnpj_emitente"], parsed["cnpj_destinatario"],
                parsed["dh_emissao"],
                parsed["vl_doc"], parsed["vl_icms"], parsed["vl_icms_st"],
                parsed["vl_ipi"], parsed["vl_pis"], parsed["vl_cofins"],
                parsed["qtd_itens"], parsed["prot_cstat"],
                json.dumps(parsed, ensure_ascii=False),
            ),
        )
        nfe_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Inserir itens
        for item in parsed["itens"]:
            db.execute(
                """INSERT INTO nfe_itens
                   (nfe_id, num_item, cod_produto, ncm, cfop, vl_prod, vl_desc,
                    cst_icms, vbc_icms, aliq_icms, vl_icms, cst_ipi, vl_ipi,
                    cst_pis, vl_pis, cst_cofins, vl_cofins)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    nfe_id, item["num_item"], item["cod_produto"], item["ncm"],
                    item["cfop"], item["vl_prod"], item["vl_desc"],
                    item["cst_icms"], item["vbc_icms"], item["aliq_icms"],
                    item["vl_icms"], item.get("cst_ipi", ""), item.get("vl_ipi", 0),
                    item.get("cst_pis", ""), item.get("vl_pis", 0),
                    item.get("cst_cofins", ""), item.get("vl_cofins", 0),
                ),
            )

        cstat = parsed["prot_cstat"]
        if cstat == "100":
            stats["autorizadas"] += 1
        elif cstat in ("101", "135"):
            stats["canceladas"] += 1

    db.commit()
    return stats


# ──────────────────────────────────────────────
# Cruzamento XML vs SPED (17 regras)
# ──────────────────────────────────────────────

def cruzar_xml_vs_sped(
    db: sqlite3.Connection,
    file_id: int,
    on_progress: callable | None = None,
) -> list[dict]:
    """Executa as 17 regras de cruzamento e salva em nfe_cruzamento.

    Args:
        on_progress: callback(pct: int, msg: str) para reportar progresso.
    """
    def _emit(pct: int, msg: str) -> None:
        if on_progress:
            on_progress(pct, msg)

    _emit(0, "Limpando cruzamento anterior...")

    # Limpar cruzamento anterior (tabela propria + validation_errors)
    db.execute("DELETE FROM nfe_cruzamento WHERE file_id = ?", (file_id,))
    db.execute(
        "DELETE FROM validation_errors WHERE file_id = ? AND categoria = 'cruzamento_xml'",
        (file_id,),
    )

    findings: list[dict] = []

    _emit(5, "Carregando XMLs do banco...")

    # Carregar XMLs
    xmls = db.execute(
        "SELECT id, chave_nfe, vl_doc, vl_icms, vl_icms_st, vl_ipi, qtd_itens, "
        "prot_cstat, cnpj_emitente, cnpj_destinatario, dh_emissao "
        "FROM nfe_xmls WHERE file_id = ? AND status = 'active'",
        (file_id,),
    ).fetchall()
    xml_by_chave = {r[1]: r for r in xmls}

    _emit(10, f"{len(xmls)} XMLs carregados. Carregando registros C100...")

    # Carregar C100 do SPED
    c100s = db.execute(
        "SELECT id, fields_json, line_number FROM sped_records "
        "WHERE file_id = ? AND register = 'C100'",
        (file_id,),
    ).fetchall()

    sped_by_chave: dict[str, dict] = {}
    for rec_id, fields_json, line_no in c100s:
        fields = json.loads(fields_json) if fields_json else {}
        chv = _norm_chave(fields.get("CHV_NFE", ""))
        if chv:
            sped_by_chave[chv] = {
                "record_id": rec_id, "line": line_no, "fields": fields, "chave": chv,
            }

    _emit(15, f"{len(c100s)} registros C100 carregados. Iniciando cruzamento...")

    all_chaves = sorted(set(xml_by_chave.keys()) | set(sped_by_chave.keys()))
    total_chaves = len(all_chaves)

    _emit(20, f"Cruzando {total_chaves} chaves NF-e...")

    for idx, chave in enumerate(all_chaves):
        # Progresso de 20% a 80% durante o cruzamento
        if total_chaves > 0 and idx % max(1, total_chaves // 10) == 0:
            pct = 20 + int((idx / total_chaves) * 60)
            _emit(pct, f"Regra XML001-XML015: {idx}/{total_chaves} chaves analisadas...")

        xml = xml_by_chave.get(chave)
        sped = sped_by_chave.get(chave)

        # XML001: NF-e no XML mas ausente no SPED
        if xml and not sped:
            findings.append(_finding(file_id, xml[0], chave, "XML001", "critical",
                                     "chave_nfe", chave, "C100.CHV_NFE", "(ausente)",
                                     None, f"NF-e {chave[:20]}... presente no XML mas ausente na escrituracao SPED."))
            continue

        # XML002: NF-e no SPED mas ausente nos XMLs
        if sped and not xml:
            findings.append(_finding(file_id, None, chave, "XML002", "error",
                                     "(ausente)", "(ausente)", "C100.CHV_NFE", chave,
                                     None, f"C100 com CHV_NFE {chave[:20]}... sem XML correspondente."))
            continue

        # Ambos existem — comparar
        assert xml is not None and sped is not None
        nfe_id = xml[0]
        sf = sped["fields"]

        # XML011: NF-e cancelada escriturada
        if xml[7] and xml[7] != "100":
            findings.append(_finding(file_id, nfe_id, chave, "XML011", "critical",
                                     "prot_cstat", xml[7], "C100", "presente",
                                     None, f"NF-e cancelada (cStat={xml[7]}) mas escriturada no SPED."))

        # XML003: VL_DOC
        _compare_value(findings, file_id, nfe_id, chave, "XML003", "critical",
                       "totais.vNF", xml[2], "C100.VL_DOC", _to_float(sf.get("VL_DOC", "0")), 0.02)

        # XML004: VL_ICMS
        _compare_value(findings, file_id, nfe_id, chave, "XML004", "critical",
                       "totais.vICMS", xml[3], "C100.VL_ICMS", _to_float(sf.get("VL_ICMS", "0")), 0.02)

        # XML005: VL_ICMS_ST
        _compare_value(findings, file_id, nfe_id, chave, "XML005", "error",
                       "totais.vST", xml[4], "C100.VL_ICMS_ST", _to_float(sf.get("VL_ICMS_ST", "0")), 0.02)

        # XML006: VL_IPI
        _compare_value(findings, file_id, nfe_id, chave, "XML006", "error",
                       "totais.vIPI", xml[5], "C100.VL_IPI", _to_float(sf.get("VL_IPI", "0")), 0.02)

        # XML012: Quantidade de itens
        qtd_xml = xml[6] or 0
        qtd_sped = db.execute(
            "SELECT COUNT(*) FROM sped_records WHERE file_id = ? AND register = 'C170' "
            "AND line_number > (SELECT line_number FROM sped_records WHERE id = ?) "
            "AND line_number < COALESCE("
            "  (SELECT MIN(line_number) FROM sped_records "
            "   WHERE file_id = ? AND register IN ('C100','C190','C990') "
            "   AND line_number > (SELECT line_number FROM sped_records WHERE id = ?)), 999999999)",
            (file_id, sped["record_id"], file_id, sped["record_id"]),
        ).fetchone()[0]
        if qtd_xml != qtd_sped:
            findings.append(_finding(file_id, nfe_id, chave, "XML012", "error",
                                     "qtd_itens", str(qtd_xml), "count(C170)", str(qtd_sped),
                                     abs(qtd_xml - qtd_sped),
                                     f"XML tem {qtd_xml} itens, SPED tem {qtd_sped} C170."))

        # XML013: CNPJ participante
        cod_part = sf.get("COD_PART", "")
        if cod_part:
            part_row = db.execute(
                "SELECT fields_json FROM sped_records WHERE file_id = ? AND register = '0150' "
                "AND fields_json LIKE ?",
                (file_id, f'%"{cod_part}"%'),
            ).fetchone()
            if part_row:
                part_fields = json.loads(part_row[0]) if part_row[0] else {}
                cnpj_sped = _norm_cnpj(part_fields.get("CNPJ", ""))
                cnpj_xml = _norm_cnpj(xml[8] if sf.get("IND_EMIT", "") == "1" else (xml[9] or ""))
                if cnpj_xml and cnpj_sped and cnpj_xml != cnpj_sped:
                    findings.append(_finding(file_id, nfe_id, chave, "XML013", "error",
                                             "cnpj", cnpj_xml, "0150.CNPJ", cnpj_sped,
                                             None, f"CNPJ do XML ({cnpj_xml}) diverge do participante no SPED ({cnpj_sped})."))

        # XML014: Data emissão
        dt_xml = _norm_date_iso(xml[10] if len(xml) > 10 else "")
        dt_sped = sf.get("DT_DOC", "")
        if dt_xml and dt_sped and dt_xml != dt_sped:
            findings.append(_finding(file_id, nfe_id, chave, "XML014", "error",
                                     "dh_emissao", dt_xml, "C100.DT_DOC", dt_sped,
                                     None, f"Data emissao XML ({dt_xml}) diverge do SPED ({dt_sped})."))

        # XML015: Data entrada/saída
        dt_es_sped = sf.get("DT_E_S", "")
        if dt_es_sped and dt_xml and dt_xml != dt_es_sped:
            findings.append(_finding(file_id, nfe_id, chave, "XML015", "warning",
                                     "dh_emissao", dt_xml, "C100.DT_E_S", dt_es_sped,
                                     None, f"Data XML ({dt_xml}) diverge de DT_E_S ({dt_es_sped})."))

    _emit(80, f"Cruzamento concluido: {len(findings)} divergencias. Persistindo...")

    # Persistir
    for f in findings:
        db.execute(
            """INSERT INTO nfe_cruzamento
               (file_id, nfe_id, chave_nfe, rule_id, severity, campo_xml,
                valor_xml, campo_sped, valor_sped, diferenca, message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (f["file_id"], f["nfe_id"], f["chave_nfe"], f["rule_id"],
             f["severity"], f["campo_xml"], f["valor_xml"], f["campo_sped"],
             f["valor_sped"], f["diferenca"], f["message"]),
        )
    db.commit()

    _emit(90, "Gerando erros de validacao com sugestoes automaticas...")

    # ── Gerar validation_errors com sugestão automática do XML ──
    _gerar_erros_com_sugestao_xml(db, file_id, findings, sped_by_chave)

    _emit(100, f"Concluido: {len(findings)} divergencias encontradas.")

    return findings


# ──────────────────────────────────────────────
# Campos corrigíveis automaticamente pelo XML
# ──────────────────────────────────────────────

# Mapeamento rule_id → (campo SPED no C100/C170, nome do campo, corrigível)
_CORRIGIVEL_POR_XML: dict[str, tuple[str, str, bool]] = {
    "XML003": ("VL_DOC", "C100", True),
    "XML004": ("VL_ICMS", "C100", True),
    "XML005": ("VL_ICMS_ST", "C100", True),
    "XML006": ("VL_IPI", "C100", True),
    "XML014": ("DT_DOC", "C100", False),      # Data — investigar, não corrigir auto
    "XML015": ("DT_E_S", "C100", False),       # Data — investigar
    "XML011": (None, "C100", False),            # Cancelada — não corrigível, requer exclusão
    "XML001": (None, None, False),              # Ausente no SPED — não corrigível
    "XML002": (None, None, False),              # Ausente nos XMLs — não corrigível
    "XML013": (None, "0150", False),            # CNPJ participante — investigar
    "XML012": (None, None, False),              # Qtd itens — estrutural
}


def _gerar_erros_com_sugestao_xml(
    db: sqlite3.Connection,
    file_id: int,
    findings: list[dict],
    sped_by_chave: dict[str, dict],
) -> None:
    """Gera validation_errors para divergências XML vs SPED.

    Para campos corrigíveis, o expected_value vem do XML (fonte da verdade)
    e auto_correctable=1.
    """
    for f in findings:
        rule_id = f["rule_id"]
        chave = f["chave_nfe"]
        sped = sped_by_chave.get(chave)

        corr_info = _CORRIGIVEL_POR_XML.get(rule_id, (None, None, False))
        campo_sped, register, corrigivel = corr_info

        # Determinar record_id e line_number do C100 correspondente
        record_id = sped["record_id"] if sped else None
        line_no = sped["line"] if sped else 0

        # Severidade mapeada
        sev_map = {"critical": "critical", "error": "error", "warning": "warning"}
        severity = sev_map.get(f["severity"], "error")

        # Expected value = valor do XML (fonte da verdade)
        expected = f["valor_xml"] if corrigivel and f["valor_xml"] else None
        auto_corr = 1 if corrigivel and expected else 0

        # Mensagem enriquecida
        msg = f"[XML] {f['message']}"
        if corrigivel:
            msg += f" Sugestao: corrigir {campo_sped} para {expected} (conforme XML da NF-e)."

        friendly = (
            f"O valor no SPED ({f['valor_sped']}) diverge do XML da NF-e ({f['valor_xml']}). "
            f"O XML e a fonte da verdade — o valor correto e {f['valor_xml']}."
        ) if corrigivel else f"Divergencia entre XML e SPED: {f['message']}"

        try:
            db.execute(
                """INSERT INTO validation_errors
                   (file_id, record_id, line_number, register, field_no, field_name,
                    value, expected_value, error_type, severity, message,
                    friendly_message, auto_correctable, categoria, certeza, impacto)
                   VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, 'cruzamento_xml', 'objetivo', 'critico')""",
                (
                    file_id, record_id, line_no, register or "C100",
                    campo_sped or f["campo_sped"],
                    f["valor_sped"], expected,
                    rule_id, severity, msg, friendly, auto_corr,
                ),
            )
        except Exception as exc:
            logger.warning("Falha ao inserir validation_error XML %s: %s", rule_id, exc)

    db.commit()


def _finding(file_id, nfe_id, chave, rule_id, severity,
             campo_xml, valor_xml, campo_sped, valor_sped, diferenca, message):
    return {
        "file_id": file_id, "nfe_id": nfe_id, "chave_nfe": chave,
        "rule_id": rule_id, "severity": severity,
        "campo_xml": campo_xml, "valor_xml": str(valor_xml) if valor_xml is not None else "",
        "campo_sped": campo_sped, "valor_sped": str(valor_sped) if valor_sped is not None else "",
        "diferenca": diferenca, "message": message,
    }


def _compare_value(findings, file_id, nfe_id, chave, rule_id, severity,
                   campo_xml, val_xml, campo_sped, val_sped, tolerance):
    val_x = _to_float(val_xml)
    val_s = _to_float(val_sped)
    diff = abs(val_x - val_s)
    if diff > tolerance:
        findings.append(_finding(
            file_id, nfe_id, chave, rule_id, severity,
            campo_xml, f"{val_x:.2f}", campo_sped, f"{val_s:.2f}", diff,
            f"{campo_xml}={val_x:.2f} vs {campo_sped}={val_s:.2f} (dif={diff:.2f}).",
        ))
