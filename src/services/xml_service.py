"""Serviço de cruzamento NF-e XML x SPED EFD.

Parseia XMLs de NF-e, salva no banco e cruza com registros C100/C170/0200.
17 regras de cruzamento (XML001-XML017).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

from .db_types import AuditConnection
from ..validators.tolerance import tolerancia_proporcional

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
        return round(float(str(val).replace(",", ".")), 2)
    except (ValueError, TypeError):
        return 0.0


def _track_status(raw_val) -> str:
    """Determina status de rastreamento de um valor bruto do XML."""
    if raw_val is None:
        return "missing"
    s = str(raw_val).strip()
    if s == "":
        return "missing"
    if s == "0" or s == "0.00" or s == "0.0":
        return "explicit_zero"
    try:
        float(s)
        return "ok"
    except (ValueError, TypeError):
        return "parse_error"


def _extract_uf_emitente(emit) -> str:
    """Extrai UF do emitente do elemento emit do XML NF-e."""
    if emit is None:
        return ""
    ender = emit.find(f"{{{_NS.get('nfe', '')}}}enderEmit") if _NS else None
    if ender is None:
        ender = emit.find("enderEmit")
    if ender is None:
        return ""
    uf = ender.find(f"{{{_NS.get('nfe', '')}}}UF") if _NS else None
    if uf is None:
        uf = ender.find("UF")
    return uf.text.strip() if uf is not None and uf.text else ""


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
        "uf_emitente": _extract_uf_emitente(emit),
        "nome_emitente": (_text(emit, "nfe:xNome", _NS) or _text(emit, "xNome")) if emit is not None else "",
        "totais": {},
        "itens": [],
        "prot_cstat": "",
        "_tracked": {},
    }

    # Totais
    if icms_tot is not None:
        for campo in ["vBC", "vICMS", "vICMSDeson", "vBCST", "vST", "vFCP",
                       "vFCPST", "vFCPUFDest", "vICMSUFDest", "vICMSUFRemet",
                       "vProd", "vFrete", "vSeg", "vDesc", "vII", "vIPI",
                       "vIPIDevol", "vPIS", "vCOFINS", "vOutro", "vNF"]:
            val = _text(icms_tot, f"nfe:{campo}", _NS) or _text(icms_tot, campo)
            result["totais"][campo] = _to_float(val)
            result["_tracked"][f"totais.{campo}"] = {
                "raw_value": val if val else None,
                "source_xpath": f".//infNFe/total/ICMSTot/{campo}",
                "status": _track_status(val if val else None),
            }

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

        _raw_vl_prod = (_text(prod, "nfe:vProd", _NS) or _text(prod, "vProd")) if prod else None
        _raw_vl_desc = (_text(prod, "nfe:vDesc", _NS) or _text(prod, "vDesc")) if prod else None
        _raw_qcom = (_text(prod, "nfe:qCom", _NS) or _text(prod, "qCom")) if prod else None

        item = {
            "num_item": int(det.attrib.get("nItem", 0)),
            "cod_produto": _text(prod, "nfe:cProd", _NS) or _text(prod, "cProd") if prod else "",
            "ncm": _norm_ncm(_text(prod, "nfe:NCM", _NS) or _text(prod, "NCM") if prod else ""),
            "cfop": _norm_cfop(_text(prod, "nfe:CFOP", _NS) or _text(prod, "CFOP") if prod else ""),
            "vl_prod": _to_float(_raw_vl_prod or "0"),
            "vl_desc": _to_float(_raw_vl_desc or "0"),
            "qtd": None if _raw_qcom is None or str(_raw_qcom).strip() == "" else _to_float(_raw_qcom),
            "_tracked": {
                "vl_prod": {
                    "raw_value": _raw_vl_prod if _raw_vl_prod else None,
                    "source_xpath": ".//infNFe/det/prod/vProd",
                    "status": _track_status(_raw_vl_prod if _raw_vl_prod else None),
                },
                "vl_desc": {
                    "raw_value": _raw_vl_desc if _raw_vl_desc else None,
                    "source_xpath": ".//infNFe/det/prod/vDesc",
                    "status": _track_status(_raw_vl_desc if _raw_vl_desc else None),
                },
            },
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

            _raw_vbc_icms = _text(icms_group, "nfe:vBC", _NS) or _text(icms_group, "vBC")
            _raw_aliq_icms = _text(icms_group, "nfe:pICMS", _NS) or _text(icms_group, "pICMS")
            _raw_vl_icms = _text(icms_group, "nfe:vICMS", _NS) or _text(icms_group, "vICMS")
            _raw_vbcst = _text(icms_group, "nfe:vBCST", _NS) or _text(icms_group, "vBCST")
            _raw_vicmsst = _text(icms_group, "nfe:vICMSST", _NS) or _text(icms_group, "vICMSST")

            # cBenef e vICMSDeson — mapeamento XML→SPED (E115/C197/E111)
            _raw_cbenef = _text(icms_group, "nfe:cBenef", _NS) or _text(icms_group, "cBenef")
            _raw_vl_icms_deson = _text(icms_group, "nfe:vICMSDeson", _NS) or _text(icms_group, "vICMSDeson")

            item["vbc_icms"] = _to_float(_raw_vbc_icms)
            item["aliq_icms"] = _to_float(_raw_aliq_icms)
            item["vl_icms"] = _to_float(_raw_vl_icms)
            item["vbc_icms_st"] = _to_float(_raw_vbcst or "0")
            item["vl_icms_st"] = _to_float(_raw_vicmsst or "0")
            item["cbenef"] = (_raw_cbenef or "").strip()
            item["vl_icms_deson"] = _to_float(_raw_vl_icms_deson or "0")

            item["_tracked"]["vbc_icms"] = {
                "raw_value": _raw_vbc_icms if _raw_vbc_icms else None,
                "source_xpath": ".//infNFe/det/imposto/ICMS/*/vBC",
                "status": _track_status(_raw_vbc_icms if _raw_vbc_icms else None),
            }
            item["_tracked"]["aliq_icms"] = {
                "raw_value": _raw_aliq_icms if _raw_aliq_icms else None,
                "source_xpath": ".//infNFe/det/imposto/ICMS/*/pICMS",
                "status": _track_status(_raw_aliq_icms if _raw_aliq_icms else None),
            }
            item["_tracked"]["vl_icms"] = {
                "raw_value": _raw_vl_icms if _raw_vl_icms else None,
                "source_xpath": ".//infNFe/det/imposto/ICMS/*/vICMS",
                "status": _track_status(_raw_vl_icms if _raw_vl_icms else None),
            }
            item["_tracked"]["cbenef"] = {
                "raw_value": _raw_cbenef if _raw_cbenef else None,
                "source_xpath": ".//infNFe/det/imposto/ICMS/*/cBenef",
                "status": _track_status(_raw_cbenef if _raw_cbenef else None),
            }
            item["_tracked"]["vl_icms_deson"] = {
                "raw_value": _raw_vl_icms_deson if _raw_vl_icms_deson else None,
                "source_xpath": ".//infNFe/det/imposto/ICMS/*/vICMSDeson",
                "status": _track_status(_raw_vl_icms_deson if _raw_vl_icms_deson else None),
            }
        else:
            item.update({
                "cst_icms": "", "vbc_icms": 0.0, "aliq_icms": 0.0, "vl_icms": 0.0,
                "vbc_icms_st": 0.0, "vl_icms_st": 0.0,
                "cbenef": "", "vl_icms_deson": 0.0,
            })
            item["_tracked"]["vbc_icms"] = {"raw_value": None, "source_xpath": ".//infNFe/det/imposto/ICMS/*/vBC", "status": "missing"}
            item["_tracked"]["aliq_icms"] = {"raw_value": None, "source_xpath": ".//infNFe/det/imposto/ICMS/*/pICMS", "status": "missing"}
            item["_tracked"]["vl_icms"] = {"raw_value": None, "source_xpath": ".//infNFe/det/imposto/ICMS/*/vICMS", "status": "missing"}
            item["_tracked"]["cbenef"] = {"raw_value": None, "source_xpath": ".//infNFe/det/imposto/ICMS/*/cBenef", "status": "missing"}
            item["_tracked"]["vl_icms_deson"] = {"raw_value": None, "source_xpath": ".//infNFe/det/imposto/ICMS/*/vICMSDeson", "status": "missing"}

        # IPI
        _raw_vl_ipi = None
        if imp is not None:
            ipi_el = _find(imp, "nfe:IPI", "IPI")
            if ipi_el is not None:
                ipi_trib = _find(ipi_el, "nfe:IPITrib", "IPITrib")
                if ipi_trib is not None:
                    item["cst_ipi"] = _text(ipi_trib, "nfe:CST", _NS) or _text(ipi_trib, "CST")
                    _raw_vl_ipi = _text(ipi_trib, "nfe:vIPI", _NS) or _text(ipi_trib, "vIPI")
                    item["vl_ipi"] = _to_float(_raw_vl_ipi)
                else:
                    ipi_nt = _find(ipi_el, "nfe:IPINT", "IPINT")
                    item["cst_ipi"] = _text(ipi_nt, "nfe:CST", _NS) or _text(ipi_nt, "CST") if ipi_nt else ""
                    item["vl_ipi"] = 0.0
            else:
                item.update({"cst_ipi": "", "vl_ipi": 0.0})
        else:
            item.update({"cst_ipi": "", "vl_ipi": 0.0})

        item["_tracked"]["vl_ipi"] = {
            "raw_value": _raw_vl_ipi if _raw_vl_ipi else None,
            "source_xpath": ".//infNFe/det/imposto/IPI/IPITrib/vIPI",
            "status": _track_status(_raw_vl_ipi if _raw_vl_ipi else None),
        }

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


def _is_pg(db) -> bool:
    return type(db).__name__ == "PgConnection"


def _upsert_emitente_crt(db, parsed: dict, crt_int: int, uf_emitente: str) -> None:
    """Persiste CRT na tabela emitentes_crt."""
    try:
        db.execute("SAVEPOINT _upsert_crt")
        db.execute(
            """INSERT INTO emitentes_crt
               (cnpj_emitente, crt, razao_social, uf_emitente, last_seen, fonte)
               VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 'xml')
               ON CONFLICT (cnpj_emitente) DO UPDATE SET
                 crt = EXCLUDED.crt,
                 razao_social = EXCLUDED.razao_social,
                 uf_emitente = EXCLUDED.uf_emitente,
                 last_seen = CURRENT_TIMESTAMP""",
            (parsed["cnpj_emitente"], crt_int,
             parsed.get("nome_emitente", ""), uf_emitente),
        )
        db.execute("RELEASE SAVEPOINT _upsert_crt")
    except Exception:
        try:
            db.execute("ROLLBACK TO SAVEPOINT _upsert_crt")
        except Exception:
            pass


# ──────────────────────────────────────────────
# Upload batch de XMLs
# ──────────────────────────────────────────────

def upload_nfe_xmls(
    db: AuditConnection,
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

        # Extrair CRT e cStat para novos campos (Migration 14)
        crt_raw = parsed.get("crt_emitente", "")
        crt_int = int(crt_raw) if crt_raw and crt_raw.isdigit() else None
        c_sit = parsed.get("prot_cstat", "")
        uf_emitente = parsed.get("uf_emitente", "")

        cur = db.execute(
            """INSERT INTO nfe_xmls
               (file_id, chave_nfe, numero_nfe, serie, cnpj_emitente,
                cnpj_destinatario, dh_emissao, vl_doc, vl_icms, vl_icms_st,
                vl_ipi, vl_pis, vl_cofins, qtd_itens, prot_cstat, status, parsed_json,
                crt_emitente, uf_emitente, c_sit)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?,
                       ?, ?, ?)""",
            (
                file_id, chave, parsed["numero_nfe"], parsed["serie"],
                parsed["cnpj_emitente"], parsed["cnpj_destinatario"],
                parsed["dh_emissao"],
                parsed["vl_doc"], parsed["vl_icms"], parsed["vl_icms_st"],
                parsed["vl_ipi"], parsed["vl_pis"], parsed["vl_cofins"],
                parsed["qtd_itens"], parsed["prot_cstat"],
                json.dumps(parsed, ensure_ascii=False),
                crt_int, uf_emitente, c_sit,
            ),
        )
        nfe_id = cur.lastrowid

        # Persistir CRT na tabela incremental emitentes_crt (Fase 5)
        if crt_int and parsed.get("cnpj_emitente"):
            _upsert_emitente_crt(db, parsed, crt_int, uf_emitente)

        # Inserir itens
        for item in parsed["itens"]:
            db.execute(
                """INSERT INTO nfe_itens
                   (nfe_id, num_item, cod_produto, ncm, cfop, vl_prod, vl_desc,
                    cst_icms, vbc_icms, aliq_icms, vl_icms, cst_ipi, vl_ipi,
                    cst_pis, vl_pis, cst_cofins, vl_cofins,
                    cbenef, vl_icms_deson)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    nfe_id, item["num_item"], item["cod_produto"], item["ncm"],
                    item["cfop"], item["vl_prod"], item["vl_desc"],
                    item["cst_icms"], item["vbc_icms"], item["aliq_icms"],
                    item["vl_icms"], item.get("cst_ipi", ""), item.get("vl_ipi", 0),
                    item.get("cst_pis", ""), item.get("vl_pis", 0),
                    item.get("cst_cofins", ""), item.get("vl_cofins", 0),
                    item.get("cbenef", ""), item.get("vl_icms_deson", 0),
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
# C190 vs XML items (agrupamento por CST+CFOP+ALIQ)
# ──────────────────────────────────────────────

def _check_c190_vs_xml(
    db: AuditConnection,
    file_id: int,
    nfe_id: int,
    chave: str,
    sped: dict,
    findings: list[dict],
    nf_label: str,
) -> None:
    """Compara C190 do SPED com itens XML agrupados por (CST, CFOP, ALIQ).

    Agrupa itens XML (nfe_itens) pela mesma chave de consolidacao usada no C190
    e compara VL_BC_ICMS e VL_ICMS. Diferenca alem da tolerancia gera finding.
    """
    record_id = sped["record_id"]
    line_no = sped["line"]

    # Buscar C190 filhos deste C100 (entre line_number do C100 e proximo C100/C990)
    next_boundary = db.execute(
        "SELECT MIN(line_number) FROM sped_records "
        "WHERE file_id = ? AND register IN ('C100', 'C990') "
        "AND line_number > ?",
        (file_id, line_no),
    ).fetchone()
    max_line = next_boundary[0] if next_boundary and next_boundary[0] else 999999999

    c190_rows = db.execute(
        "SELECT fields_json FROM sped_records "
        "WHERE file_id = ? AND register = 'C190' "
        "AND line_number > ? AND line_number < ?",
        (file_id, line_no, max_line),
    ).fetchall()

    if not c190_rows:
        return

    # Montar dict C190 por chave (CST, CFOP, ALIQ)
    c190_by_key: dict[tuple, dict] = {}
    for row in c190_rows:
        f190 = json.loads(row[0]) if row[0] else {}
        cst = _norm_cst(f190.get("CST_ICMS", "").strip())
        cfop = f190.get("CFOP", "").strip()
        try:
            aliq = round(float(str(f190.get("ALIQ_ICMS", "0")).replace(",", ".")), 2)
        except (ValueError, TypeError):
            aliq = 0.0
        key = (cst, cfop, aliq)
        c190_by_key[key] = {
            "VL_BC_ICMS": _to_float(f190.get("VL_BC_ICMS")),
            "VL_ICMS": _to_float(f190.get("VL_ICMS")),
            "VL_OPR": _to_float(f190.get("VL_OPR")),
        }

    # Carregar itens XML (nfe_itens) para esta NF-e
    xml_items = db.execute(
        "SELECT cst_icms, cfop, aliq_icms, vbc_icms, vl_icms FROM nfe_itens WHERE nfe_id = ?",
        (nfe_id,),
    ).fetchall()

    if not xml_items:
        return

    # Agrupar itens XML pela mesma chave (CST, CFOP, ALIQ)
    xml_by_key: dict[tuple, dict] = {}
    for cst_raw, cfop_raw, aliq_raw, vbc, vicms in xml_items:
        cst = _norm_cst((cst_raw or "").strip())
        cfop = (cfop_raw or "").strip()
        aliq = round(float(aliq_raw or 0), 2)
        key = (cst, cfop, aliq)
        if key not in xml_by_key:
            xml_by_key[key] = {"VL_BC_ICMS": 0.0, "VL_ICMS": 0.0}
        xml_by_key[key]["VL_BC_ICMS"] += float(vbc or 0)
        xml_by_key[key]["VL_ICMS"] += float(vicms or 0)

    # Comparar cada grupo C190 com o agrupamento XML
    tol_base = 0.10  # tolerancia consolidacao
    for key, c190_vals in c190_by_key.items():
        cst_k, cfop_k, aliq_k = key
        xml_vals = xml_by_key.get(key)

        if not xml_vals:
            # C190 existe no SPED mas sem itens XML correspondentes — skip
            # (pode ser diferenca de normalizacao CST)
            continue

        # VL_BC_ICMS
        diff_bc = abs(round(c190_vals["VL_BC_ICMS"] - xml_vals["VL_BC_ICMS"], 2))
        tol = max(tol_base, tolerancia_proporcional(max(c190_vals["VL_BC_ICMS"], xml_vals["VL_BC_ICMS"])))
        if diff_bc > tol:
            findings.append(_finding(
                file_id, nfe_id, chave, "XML_C190_DIVERGE", "high",
                f"XML.soma(vBC) [{cst_k}/{cfop_k}/{aliq_k}%]",
                f"{xml_vals['VL_BC_ICMS']:.2f}",
                f"C190.VL_BC_ICMS [{cst_k}/{cfop_k}/{aliq_k}%]",
                f"{c190_vals['VL_BC_ICMS']:.2f}",
                diff_bc,
                f"{nf_label}: C190 VL_BC_ICMS={c190_vals['VL_BC_ICMS']:.2f} vs "
                f"XML soma(vBC)={xml_vals['VL_BC_ICMS']:.2f} "
                f"(CST={cst_k} CFOP={cfop_k} ALIQ={aliq_k}%) dif=R${diff_bc:.2f}.",
            ))

        # VL_ICMS
        diff_icms = abs(round(c190_vals["VL_ICMS"] - xml_vals["VL_ICMS"], 2))
        tol_icms = max(tol_base, tolerancia_proporcional(max(c190_vals["VL_ICMS"], xml_vals["VL_ICMS"])))
        if diff_icms > tol_icms:
            findings.append(_finding(
                file_id, nfe_id, chave, "XML_C190_DIVERGE", "high",
                f"XML.soma(vICMS) [{cst_k}/{cfop_k}/{aliq_k}%]",
                f"{xml_vals['VL_ICMS']:.2f}",
                f"C190.VL_ICMS [{cst_k}/{cfop_k}/{aliq_k}%]",
                f"{c190_vals['VL_ICMS']:.2f}",
                diff_icms,
                f"{nf_label}: C190 VL_ICMS={c190_vals['VL_ICMS']:.2f} vs "
                f"XML soma(vICMS)={xml_vals['VL_ICMS']:.2f} "
                f"(CST={cst_k} CFOP={cfop_k} ALIQ={aliq_k}%) dif=R${diff_icms:.2f}.",
            ))


# ──────────────────────────────────────────────
# Cruzamento XML vs SPED (17 regras + C190)
# ──────────────────────────────────────────────

def cruzar_xml_vs_sped(
    db: AuditConnection,
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

    # Limpar apenas findings legacy (XML###), preservando XC### do Motor XC
    db.execute(
        "DELETE FROM nfe_cruzamento WHERE file_id = ? AND rule_id LIKE ?",
        (file_id, "XML%"),
    )
    db.execute(
        "DELETE FROM validation_errors WHERE file_id = ? AND categoria = 'cruzamento_xml'",
        (file_id,),
    )
    # Reinicia marcador de fim de cruzamento (evita "executado" de rodada anterior)
    try:
        db.execute(
            "UPDATE sped_files SET xml_crossref_completed_at = NULL WHERE id = ?",
            (file_id,),
        )
    except Exception:
        pass

    findings: list[dict] = []

    _emit(5, "Carregando XMLs do banco...")

    # Carregar XMLs (inclui numero_nfe para mensagens)
    xmls = db.execute(
        "SELECT id, chave_nfe, vl_doc, vl_icms, vl_icms_st, vl_ipi, qtd_itens, "
        "prot_cstat, cnpj_emitente, cnpj_destinatario, dh_emissao, numero_nfe "
        "FROM nfe_xmls WHERE file_id = ? AND status = 'active'",
        (file_id,),
    ).fetchall()
    xml_by_chave = {r[1]: r for r in xmls}
    # Mapa chave → numero_nfe para enriquecer mensagens
    _nfe_num: dict[str, str] = {}
    for r in xmls:
        _nfe_num[r[1]] = str(r[11] or "") if isinstance(r, tuple) else str(r["numero_nfe"] or "")

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
            _emit(pct, f"Cruzamento XML x SPED: {idx}/{total_chaves} chaves NF-e analisadas...")

        xml = xml_by_chave.get(chave)
        sped = sped_by_chave.get(chave)

        # XML001: NF-e no XML mas ausente no SPED
        if xml and not sped:
            num = _nfe_num.get(chave, "")
            nf_label = f"NF {num}" if num else f"Chave {chave[:20]}..."
            findings.append(_finding(file_id, xml[0], chave, "XML001", "critical",
                                     "chave_nfe", chave, "C100.CHV_NFE", "(ausente)",
                                     None, f"NF-e presente no XML mas ausente na escrituracao SPED.\nChave: {chave}"))
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
        num_nfe = _nfe_num.get(chave, "")
        _nf = f"NF {num_nfe}" if num_nfe else f"Chave {chave[:15]}..."

        # BUG-003 fix: Cruzamento COD_SIT (C100) x cStat (XML) com mapeamento completo
        cstat = str(xml[7] or "").strip()
        cod_sit = str(sf.get("COD_SIT", "")).strip()
        _CSTAT_TO_COD_SIT = {
            "100": "00",  # Autorizada → Normal
            "101": "02",  # Cancelada → Cancelada
            "135": "02",  # Cancelada fora prazo → Cancelada
            "110": "05",  # Denegada → Denegada
            "301": "05",  # Uso indevido → Denegada
        }
        if cstat:
            cod_sit_esperado = _CSTAT_TO_COD_SIT.get(cstat)
            if cod_sit_esperado and cod_sit != cod_sit_esperado:
                if cstat in ("101", "135") and cod_sit == "00":
                    findings.append(_finding(
                        file_id, nfe_id, chave, "NF_CANCELADA_ESCRITURADA", "critical",
                        "prot_cstat", cstat, "C100.COD_SIT", cod_sit, None,
                        f"NF-e cancelada (cStat={cstat}) escriturada como ativa (COD_SIT=00). "
                        f"Credito de ICMS indevido. Esperado COD_SIT=02.\nChave: {chave}"))
                elif cstat in ("110", "301") and cod_sit == "00":
                    findings.append(_finding(
                        file_id, nfe_id, chave, "NF_DENEGADA_ESCRITURADA", "critical",
                        "prot_cstat", cstat, "C100.COD_SIT", cod_sit, None,
                        f"NF-e denegada (cStat={cstat}) escriturada como ativa (COD_SIT=00). "
                        f"Esperado COD_SIT=05.\nChave: {chave}"))
                # NF-e autorizada no XML mas escriturada como cancelada/denegada no SPED
                elif cstat == "100" and cod_sit in ("02", "03"):
                    findings.append(_finding(
                        file_id, nfe_id, chave, "NF_ATIVA_ESCRITURADA_CANCELADA", "critical",
                        "prot_cstat", cstat, "C100.COD_SIT", cod_sit, None,
                        f"NF-e autorizada (cStat=100) escriturada como cancelada "
                        f"(COD_SIT={cod_sit}) no SPED. A nota esta valida na SEFAZ mas "
                        f"nao esta gerando efeitos fiscais na escrituracao.\n"
                        f"Chave: {chave}"))
                elif cstat == "100" and cod_sit in ("04", "05"):
                    findings.append(_finding(
                        file_id, nfe_id, chave, "NF_ATIVA_ESCRITURADA_DENEGADA", "critical",
                        "prot_cstat", cstat, "C100.COD_SIT", cod_sit, None,
                        f"NF-e autorizada (cStat=100) escriturada como denegada "
                        f"(COD_SIT={cod_sit}) no SPED. A nota esta valida na SEFAZ.\n"
                        f"Chave: {chave}"))
                elif cod_sit_esperado:
                    findings.append(_finding(
                        file_id, nfe_id, chave, "COD_SIT_DIVERGENTE_XML", "error",
                        "prot_cstat", cstat, "C100.COD_SIT", cod_sit, None,
                        f"COD_SIT={cod_sit} incompativel com cStat={cstat}. "
                        f"Esperado COD_SIT={cod_sit_esperado}.\nChave: {chave}"))

        # COD_SIT 02/03/04/05: campos monetarios ficam vazios por determinacao
        # do Guia Pratico. Nao comparar valores — o erro de status (acima) ja
        # foi registrado e e a causa raiz. Comparacoes monetarias seriam falsos positivos.
        if cod_sit in ("02", "03", "04", "05"):
            continue

        # XML003: VL_DOC
        _compare_value(findings, file_id, nfe_id, chave, "XML003", "critical",
                       "totais.vNF", xml[2], "C100.VL_DOC", _to_float(sf.get("VL_DOC")), 0.02,
                       tracked={"source_xpath_xml": ".//infNFe/total/ICMSTot/vNF",
                                "campo_sped": "C100.VL_DOC"})

        # XML004: VL_ICMS
        _compare_value(findings, file_id, nfe_id, chave, "XML004", "critical",
                       "totais.vICMS", xml[3], "C100.VL_ICMS", _to_float(sf.get("VL_ICMS")), 0.02,
                       tracked={"source_xpath_xml": ".//infNFe/total/ICMSTot/vICMS",
                                "campo_sped": "C100.VL_ICMS"})

        # XML005: VL_ICMS_ST
        _compare_value(findings, file_id, nfe_id, chave, "XML005", "error",
                       "totais.vST", xml[4], "C100.VL_ICMS_ST", _to_float(sf.get("VL_ICMS_ST")), 0.02,
                       tracked={"source_xpath_xml": ".//infNFe/total/ICMSTot/vST",
                                "campo_sped": "C100.VL_ICMS_ST"})

        # XML006: VL_IPI
        _compare_value(findings, file_id, nfe_id, chave, "XML006", "error",
                       "totais.vIPI", xml[5], "C100.VL_IPI", _to_float(sf.get("VL_IPI")), 0.02,
                       tracked={"source_xpath_xml": ".//infNFe/total/ICMSTot/vIPI",
                                "campo_sped": "C100.VL_IPI"})

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
                "AND CAST(fields_json AS TEXT) LIKE ?",
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

        # ── XML_C190_DIVERGE: Cruzamento C190 (SPED) vs itens agrupados (XML) ──
        _check_c190_vs_xml(db, file_id, nfe_id, chave, sped, findings, _nf)

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

    # Marca cruzamento concluído (mesmo com 0 divergências — senão nfe_cruzamento fica vazio e o contexto acha que não rodou)
    try:
        db.execute(
            "UPDATE sped_files SET xml_crossref_completed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (file_id,),
        )
        db.commit()
    except Exception:
        pass

    return findings


# ──────────────────────────────────────────────
# Campos corrigíveis automaticamente pelo XML
# ──────────────────────────────────────────────

# Mapeamento rule_id → (campo SPED no C100/C170, registro, corrigível, field_no)
_CORRIGIVEL_POR_XML: dict[str, tuple[str | None, str | None, bool]] = {
    "XML003": ("VL_DOC", "C100", True),
    "XML004": ("VL_ICMS", "C100", True),
    "XML005": ("VL_ICMS_ST", "C100", True),
    "XML006": ("VL_IPI", "C100", True),
    "XML014": ("DT_DOC", "C100", False),
    "XML015": ("DT_E_S", "C100", False),
    "XML011": (None, "C100", False),
    "XML001": (None, None, False),
    "XML002": (None, None, False),
    "NF_ATIVA_ESCRITURADA_CANCELADA": ("COD_SIT", "C100", False),
    "NF_ATIVA_ESCRITURADA_DENEGADA": ("COD_SIT", "C100", False),
    "XML013": (None, "0150", False),
    "XML012": (None, None, False),
    "XML_C190_DIVERGE": (None, "C190", False),
}

# Posicao (field_no) correta de cada campo no C100 para o RecordEditModal
_FIELD_NO_C100: dict[str, int] = {
    "COD_SIT": 5, "DT_DOC": 9, "DT_E_S": 10, "VL_DOC": 11,
    "VL_MERC": 15, "VL_FRT": 17, "VL_SEG": 18, "VL_OUT_DA": 19,
    "VL_BC_ICMS": 20, "VL_ICMS": 21, "VL_BC_ICMS_ST": 22,
    "VL_ICMS_ST": 23, "VL_IPI": 24, "VL_PIS": 25, "VL_COFINS": 26,
}


# ──────────────────────────────────────────────
# Mensagens ricas para o usuario (XML cruzamento)
# ──────────────────────────────────────────────

# Base legal por regra de cruzamento XML
_LEGAL_BASIS_XML: dict[str, dict] = {
    "XML001": {
        "fonte": "Guia Pratico EFD ICMS/IPI",
        "artigo": "Registro C100 — Obrigatoriedade",
        "trecho": (
            "Devem ser informadas todas as NF-e (mod. 55) emitidas e recebidas, "
            "conforme operacoes do periodo de apuracao. A omissao de documentos "
            "fiscais pode configurar infração a legislacao tributaria estadual."
        ),
    },
    "XML002": {
        "fonte": "Guia Pratico EFD ICMS/IPI",
        "artigo": "Registro C100 — Integridade documental",
        "trecho": (
            "Todo registro C100 deve corresponder a um documento fiscal valido. "
            "A escrituracao de NF-e sem XML correspondente impede a verificacao "
            "da autenticidade do documento pela administracao tributaria."
        ),
    },
    "XML003": {
        "fonte": "Guia Pratico EFD ICMS/IPI",
        "artigo": "Registro C100, campo 12 — VL_DOC",
        "trecho": (
            "VL_DOC deve corresponder ao valor total da NF-e (tag vNF do XML). "
            "Divergencias entre o valor escriturado e o documento fiscal original "
            "podem gerar glosa de creditos ou autuacao por subfaturamento."
        ),
    },
    "XML004": {
        "fonte": "Guia Pratico EFD ICMS/IPI",
        "artigo": "Registro C100, campo 22 — VL_ICMS",
        "trecho": (
            "VL_ICMS deve refletir o valor do ICMS destacado na NF-e (tag vICMS). "
            "Art. 23 da LC 87/96: o direito ao credito esta condicionado a "
            "escrituracao correta do imposto destacado no documento fiscal."
        ),
    },
    "XML005": {
        "fonte": "Guia Pratico EFD ICMS/IPI",
        "artigo": "Registro C100, campo 24 — VL_ICMS_ST",
        "trecho": (
            "VL_ICMS_ST deve corresponder ao valor do ICMS-ST da NF-e (tag vST). "
            "Divergencia pode indicar apropriacao indevida de credito de ST ou "
            "erro na parametrizacao do ERP."
        ),
    },
    "XML006": {
        "fonte": "Guia Pratico EFD ICMS/IPI",
        "artigo": "Registro C100, campo 25 — VL_IPI",
        "trecho": (
            "VL_IPI deve corresponder ao valor do IPI da NF-e (tag vIPI). "
            "Art. 190 do RIPI (Dec. 7.212/2010): o credito de IPI e vinculado "
            "ao valor efetivamente destacado no documento fiscal."
        ),
    },
    "XML011": {
        "fonte": "Ajuste SINIEF 07/2005, Art. 19",
        "artigo": "Cancelamento de NF-e",
        "trecho": (
            "NF-e cancelada nao produz efeitos fiscais. A escrituracao de "
            "documento cancelado como ativo configura credito indevido de ICMS, "
            "sujeito a multa e juros conforme legislacao estadual."
        ),
    },
    "XML012": {
        "fonte": "Guia Pratico EFD ICMS/IPI",
        "artigo": "Registro C170 — Itens do documento",
        "trecho": (
            "O numero de registros C170 deve corresponder a quantidade de itens "
            "do documento fiscal. Itens faltantes comprometem a apuracao por item "
            "e a verificacao de NCM, CST e CFOP individuais."
        ),
    },
    "XML013": {
        "fonte": "Guia Pratico EFD ICMS/IPI",
        "artigo": "Registro 0150 — Cadastro de participantes",
        "trecho": (
            "O CNPJ/CPF do participante deve ser consistente entre o registro "
            "0150, o C100 (COD_PART) e o documento fiscal original. "
            "Inconsistencia pode indicar escrituracao em nome de terceiros."
        ),
    },
    "XML014": {
        "fonte": "Guia Pratico EFD ICMS/IPI",
        "artigo": "Registro C100, campo 10 — DT_DOC",
        "trecho": (
            "DT_DOC deve corresponder a data de emissao da NF-e (tag dhEmi). "
            "Data incorreta pode levar a escrituracao em periodo de apuracao errado."
        ),
    },
    "XML015": {
        "fonte": "Guia Pratico EFD ICMS/IPI",
        "artigo": "Registro C100, campo 11 — DT_E_S",
        "trecho": (
            "DT_E_S deve corresponder a data de entrada/saida da mercadoria "
            "(tag dhSaiEnt). Impacta o periodo de aproveitamento do credito."
        ),
    },
    "NF_ATIVA_ESCRITURADA_CANCELADA": {
        "fonte": "Guia Pratico EFD ICMS/IPI + Ajuste SINIEF 07/2005",
        "artigo": "Registro C100, campo COD_SIT — Escrituracao de documentos",
        "trecho": (
            "Documentos fiscais autorizados devem ser escriturados com COD_SIT=00. "
            "A escrituracao de NF-e valida como cancelada resulta em omissao de "
            "receita ou perda de credito, conforme o caso."
        ),
    },
    "NF_ATIVA_ESCRITURADA_DENEGADA": {
        "fonte": "Guia Pratico EFD ICMS/IPI + Ajuste SINIEF 07/2005",
        "artigo": "Registro C100, campo COD_SIT — Escrituracao de documentos",
        "trecho": (
            "Documentos fiscais autorizados devem ser escriturados com COD_SIT=00. "
            "A escrituracao de NF-e valida como denegada impede o reflexo fiscal correto."
        ),
    },
    "NF_CANCELADA_ESCRITURADA": {
        "fonte": "Ajuste SINIEF 07/2005, Art. 19 + LC 87/96, Art. 23",
        "artigo": "Cancelamento — Vedacao de credito",
        "trecho": (
            "NF-e cancelada nao produz efeitos tributarios. O aproveitamento "
            "de credito de ICMS sobre documento cancelado e vedado, podendo "
            "configurar infraçao qualificada (dolo ou fraude)."
        ),
    },
    "NF_DENEGADA_ESCRITURADA": {
        "fonte": "Ajuste SINIEF 07/2005, Art. 20",
        "artigo": "Denegacao — Impedimento de uso",
        "trecho": (
            "NF-e com uso denegado nao autoriza circulacao de mercadorias "
            "nem gera direito a credito fiscal. Deve ser escriturada com COD_SIT=05."
        ),
    },
    "COD_SIT_DIVERGENTE_XML": {
        "fonte": "Guia Pratico EFD ICMS/IPI",
        "artigo": "Registro C100, campo 06 — COD_SIT",
        "trecho": (
            "COD_SIT deve refletir a situacao real do documento: "
            "00=Regular, 02=Cancelado, 05=Denegado. "
            "Mapeamento obrigatorio conforme cStat da SEFAZ."
        ),
    },
    "XML_C190_DIVERGE": {
        "fonte": "Guia Pratico EFD ICMS/IPI",
        "artigo": "Registro C190 — Consolidacao por CST/CFOP/ALIQ",
        "trecho": (
            "C190 consolida os valores dos itens (C170) agrupados por CST_ICMS, "
            "CFOP e aliquota. Os totais de VL_BC_ICMS e VL_ICMS devem ser "
            "consistentes com os documentos fiscais de origem (NF-e). "
            "Divergencia pode indicar erro de classificacao fiscal ou "
            "escrituracao incorreta dos itens."
        ),
    },
}

_CAMPO_LABEL: dict[str, str] = {
    "VL_DOC": "Valor do Documento (VL_DOC)",
    "VL_ICMS": "Valor do ICMS (VL_ICMS)",
    "VL_ICMS_ST": "Valor do ICMS-ST (VL_ICMS_ST)",
    "VL_IPI": "Valor do IPI (VL_IPI)",
    "DT_DOC": "Data de Emissao (DT_DOC)",
    "DT_E_S": "Data de Entrada/Saida (DT_E_S)",
}


def _build_friendly_xml(
    rule_id: str, numero_nfe: str, f: dict,
    campo_sped: str | None, corrigivel: bool,
) -> str:
    """Monta friendly_message formatada para exibicao no card de erro."""
    nf = numero_nfe or "?"
    label = _CAMPO_LABEL.get(campo_sped or "", campo_sped or f["campo_sped"])

    if rule_id == "XML001":
        chave = f.get("chave_nfe", "")
        return (
            f"NF-e {nf} presente no XML mas **ausente na escrituracao SPED**. "
            f"A nota fiscal foi emitida/recebida mas nao consta no arquivo.\n"
            f"Chave NF-e: **{chave}**"
        )
    if rule_id == "XML002":
        return (
            f"NF-e {nf} escriturada no SPED mas **sem XML correspondente**. "
            f"O documento fiscal de origem nao foi localizado."
        )
    if rule_id in ("XML003", "XML004", "XML005", "XML006") and corrigivel:
        return (
            f"**{label}** da NF-e {nf}: "
            f"SPED informa **R$ {f['valor_sped']}**, "
            f"XML informa **R$ {f['valor_xml']}**. "
            f"Diferenca de R$ {f.get('diferenca', '?')}."
        )
    if rule_id == "XML011":
        return (
            f"NF-e {nf} esta **cancelada na SEFAZ** mas foi escriturada "
            f"como ativa no SPED (COD_SIT=00)."
        )
    if rule_id == "XML012":
        return (
            f"NF-e {nf}: **quantidade de itens diverge** entre XML e SPED. "
            f"XML tem {f['valor_xml']} itens, SPED tem {f['valor_sped']}."
        )
    if rule_id == "XML013":
        return (
            f"NF-e {nf}: **CNPJ do participante diverge** entre XML e cadastro 0150."
        )
    if rule_id in ("XML014", "XML015"):
        return (
            f"NF-e {nf}: **data diverge** entre XML ({f['valor_xml']}) "
            f"e SPED ({f['valor_sped']})."
        )
    if rule_id == "NF_ATIVA_ESCRITURADA_CANCELADA":
        chave = f.get("chave_nfe", "")
        return (
            f"NF-e {nf} **autorizada na SEFAZ** (cStat=100) mas escriturada como "
            f"**cancelada** (COD_SIT={f['valor_sped']}) no SPED. "
            f"A nota e valida e deveria gerar efeitos fiscais.\n"
            f"Chave NF-e: **{chave}**"
        )
    if rule_id == "NF_ATIVA_ESCRITURADA_DENEGADA":
        chave = f.get("chave_nfe", "")
        return (
            f"NF-e {nf} **autorizada na SEFAZ** (cStat=100) mas escriturada como "
            f"**denegada** (COD_SIT={f['valor_sped']}) no SPED.\n"
            f"Chave NF-e: **{chave}**"
        )
    if rule_id == "NF_CANCELADA_ESCRITURADA":
        return (
            f"NF-e {nf} **cancelada** (cStat={f['valor_xml']}) escriturada como "
            f"ativa no SPED. **Credito de ICMS possivelmente indevido.**"
        )
    if rule_id == "NF_DENEGADA_ESCRITURADA":
        return (
            f"NF-e {nf} **denegada** (cStat={f['valor_xml']}) escriturada como "
            f"ativa no SPED."
        )
    if rule_id == "XML_C190_DIVERGE":
        return (
            f"NF-e {nf}: **C190 diverge dos itens XML**. "
            f"SPED informa **R$ {f['valor_sped']}**, "
            f"XML totaliza **R$ {f['valor_xml']}** "
            f"no grupo {f['campo_sped'].split('[')[-1].rstrip(']') if '[' in f['campo_sped'] else ''}."
        )
    # Fallback generico
    return f"NF-e {nf}: divergencia detectada — {f['message']}"


def _build_doc_suggestion_xml(
    rule_id: str, numero_nfe: str, f: dict,
    campo_sped: str | None, corrigivel: bool,
) -> str | None:
    """Monta doc_suggestion com secao **Como corrigir:** para o painel expandido."""
    nf = numero_nfe or "?"
    label = _CAMPO_LABEL.get(campo_sped or "", campo_sped or f["campo_sped"])

    if rule_id == "XML001":
        return (
            f"A NF-e {nf} consta nos XMLs enviados a SEFAZ, porem nao foi escriturada no SPED EFD.\n\n"
            f"Isso pode indicar nota fiscal nao contabilizada, gerando risco de omissao de receita "
            f"ou falta de aproveitamento de credito.\n\n"
            f"**Como corrigir:**\n"
            f"Inclua o registro C100 (e respectivos C170/C190) referente a esta NF-e no arquivo SPED. "
            f"Verifique no ERP se a nota foi escriturada em periodo diferente."
        )
    if rule_id == "XML002":
        return (
            f"A NF-e {nf} esta escriturada no SPED mas o XML correspondente nao foi localizado.\n\n"
            f"Pode ser nota de periodo anterior, XML extraviado ou escrituracao indevida.\n\n"
            f"**Como corrigir:**\n"
            f"Consulte a SEFAZ para verificar a situacao da nota. "
            f"Obtenha o XML pelo portal da NF-e ou solicite ao emitente."
        )
    if rule_id in ("XML003", "XML004", "XML005", "XML006") and corrigivel:
        return (
            f"O campo **{label}** no registro C100 da NF-e {nf} esta com valor "
            f"**R$ {f['valor_sped']}**, porem o XML autorizado pela SEFAZ registra "
            f"**R$ {f['valor_xml']}**.\n\n"
            f"Diferenca: R$ {f.get('diferenca', '?')}.\n\n"
            f"**Como corrigir:**\n"
            f"Compare o valor no SPED com o DANFE/XML original. "
            f"Se o XML estiver correto, clique em **Corrigir** para atualizar o campo {campo_sped} "
            f"no registro C100. Caso o XML esteja incorreto, emita carta de correcao ou "
            f"solicite cancelamento junto ao emitente."
        )
    if rule_id == "XML011":
        return (
            f"A NF-e {nf} foi cancelada junto a SEFAZ mas permanece escriturada como "
            f"documento ativo (COD_SIT=00) no SPED.\n\n"
            f"Documentos cancelados **nao devem gerar credito** de ICMS.\n\n"
            f"**Como corrigir:**\n"
            f"Altere o COD_SIT do registro C100 para 02 (cancelada). "
            f"Se creditos ja foram aproveitados, efetue o estorno na apuracao (E111)."
        )
    if rule_id == "XML012":
        return (
            f"O XML da NF-e {nf} possui {f['valor_xml']} itens, mas o SPED registra "
            f"{f['valor_sped']} itens (C170).\n\n"
            f"Itens faltantes podem resultar em creditos nao aproveitados ou divergencia "
            f"na apuracao.\n\n"
            f"**Como corrigir:**\n"
            f"Verifique os registros C170 vinculados a este C100 e compare item a item "
            f"com o XML. Inclua os itens faltantes ou remova os excedentes."
        )
    if rule_id == "XML013":
        return (
            f"O CNPJ do participante na NF-e {nf} nao corresponde ao cadastrado "
            f"no registro 0150 do SPED.\n\n"
            f"**Como corrigir:**\n"
            f"Verifique o cadastro 0150 e o COD_PART no C100. Corrija o CNPJ no "
            f"registro 0150 ou atualize o COD_PART no C100."
        )
    if rule_id in ("XML014", "XML015"):
        campo_dt = "DT_DOC" if rule_id == "XML014" else "DT_E_S"
        return (
            f"A data {campo_dt} no SPED ({f['valor_sped']}) difere da data no XML "
            f"({f['valor_xml']}) para a NF-e {nf}.\n\n"
            f"**Como corrigir:**\n"
            f"Confira a data no DANFE/XML original e corrija o campo {campo_dt} "
            f"no registro C100."
        )
    if rule_id == "NF_ATIVA_ESCRITURADA_CANCELADA":
        return (
            f"A NF-e {nf} esta **autorizada na SEFAZ** (cStat=100), porem foi escriturada "
            f"como cancelada (COD_SIT={f['valor_sped']}) no SPED.\n\n"
            f"Isso significa que a nota e valida mas **nao esta produzindo efeitos fiscais** "
            f"na escrituracao. Pode resultar em omissao de receita (saida) ou perda de "
            f"credito (entrada).\n\n"
            f"**Como corrigir:**\n"
            f"Verifique se a NF-e foi realmente cancelada consultando a SEFAZ. "
            f"Se estiver ativa, altere o COD_SIT para 00 e preencha os campos monetarios "
            f"do C100 (VL_DOC, VL_MERC, VL_ICMS, etc.) conforme o XML. "
            f"Inclua tambem os registros C170/C190 correspondentes."
        )
    if rule_id == "NF_ATIVA_ESCRITURADA_DENEGADA":
        return (
            f"A NF-e {nf} esta **autorizada na SEFAZ** (cStat=100), porem foi escriturada "
            f"como denegada (COD_SIT={f['valor_sped']}) no SPED.\n\n"
            f"**Como corrigir:**\n"
            f"Consulte a situacao na SEFAZ. Se estiver autorizada, altere COD_SIT para 00 "
            f"e preencha os campos do C100 conforme o XML."
        )
    if rule_id == "NF_CANCELADA_ESCRITURADA":
        return (
            f"A NF-e {nf} foi cancelada na SEFAZ (cStat={f['valor_xml']}), "
            f"mas esta escriturada como ativa no SPED (COD_SIT=00).\n\n"
            f"Isso configura **credito indevido de ICMS**, passivel de autuacao.\n\n"
            f"**Como corrigir:**\n"
            f"Altere COD_SIT para 02 (cancelada). Estorne creditos ja aproveitados "
            f"via ajuste E111. Verifique se ha outras notas do mesmo emitente na mesma situacao."
        )
    if rule_id == "NF_DENEGADA_ESCRITURADA":
        return (
            f"A NF-e {nf} teve autorizacao denegada (cStat={f['valor_xml']}), "
            f"mas foi escriturada como ativa no SPED.\n\n"
            f"NF-e denegada **nao gera efeitos fiscais**.\n\n"
            f"**Como corrigir:**\n"
            f"Altere COD_SIT para 05 (denegada). Remova creditos eventualmente tomados."
        )
    if rule_id == "COD_SIT_DIVERGENTE_XML":
        return (
            f"O COD_SIT informado no C100 da NF-e {nf} nao corresponde ao status "
            f"registrado na SEFAZ.\n\n"
            f"**Como corrigir:**\n"
            f"Consulte a situacao da NF-e no portal da SEFAZ e ajuste o COD_SIT "
            f"conforme o mapeamento: Autorizada=00, Cancelada=02, Denegada=05."
        )
    if rule_id == "XML_C190_DIVERGE":
        campo_info = f['campo_sped'] if f.get('campo_sped') else "C190"
        return (
            f"O registro **C190** da NF-e {nf} apresenta divergencia no campo "
            f"**{campo_info}** quando comparado com a soma dos itens do XML.\n\n"
            f"SPED (C190): **R$ {f['valor_sped']}**\n"
            f"XML (soma itens): **R$ {f['valor_xml']}**\n"
            f"Diferenca: R$ {f.get('diferenca', '?')}\n\n"
            f"Isso indica que a consolidacao dos itens no C190 nao reflete os "
            f"documentos fiscais de origem. Pode ser erro de classificacao fiscal "
            f"(CST/CFOP) ou divergencia nos valores dos itens.\n\n"
            f"**Como corrigir:**\n"
            f"Compare os itens do XML (det[]) com os registros C170 e C190 do SPED. "
            f"Verifique se o agrupamento por CST+CFOP+Aliquota esta correto e se "
            f"os valores de BC e ICMS dos itens foram escriturados corretamente. "
            f"Recalcule o C190 a partir dos C170 corrigidos."
        )
    return None


def _gerar_erros_com_sugestao_xml(
    db: AuditConnection,
    file_id: int,
    findings: list[dict],
    sped_by_chave: dict[str, dict],
) -> None:
    """Gera validation_errors para divergencias XML vs SPED.

    Para campos corrigiveis, o expected_value vem do XML e auto_correctable=1.
    NOTA: O XML tambem pode conter erros. A divergencia e apontada para
    conferencia do analista, nao como correcao automatica definitiva.
    """
    # Buscar numero_nfe para cada chave (para exibir na mensagem)
    nfe_numeros: dict[str, str] = {}
    try:
        rows_nfe = db.execute(
            "SELECT chave_nfe, numero_nfe FROM nfe_xmls WHERE file_id = ?",
            (file_id,),
        ).fetchall()
        for r in rows_nfe:
            ch = r[0] if isinstance(r, tuple) else r["chave_nfe"]
            num = r[1] if isinstance(r, tuple) else r["numero_nfe"]
            nfe_numeros[ch] = str(num or "")
    except Exception:
        pass

    for f in findings:
        rule_id = f["rule_id"]
        chave = f["chave_nfe"]
        sped = sped_by_chave.get(chave)
        numero_nfe = nfe_numeros.get(chave, "")

        corr_info = _CORRIGIVEL_POR_XML.get(rule_id, (None, None, False))
        campo_sped, register, corrigivel = corr_info

        # Determinar record_id e line_number do C100 correspondente
        record_id = sped["record_id"] if sped else None
        line_no = sped["line"] if sped else 0

        # Severidade mapeada
        sev_map = {"critical": "critical", "error": "error", "warning": "warning"}
        severity = sev_map.get(f["severity"], "error")

        # Expected value = valor do XML (sugestao, nao definitivo)
        expected = f["valor_xml"] if corrigivel and f["valor_xml"] else None
        auto_corr = 1 if corrigivel and expected else 0

        # Prefixo com numero da NF para identificacao
        nf_label = f"NF {numero_nfe}" if numero_nfe else f"Chave {chave[:15]}..."

        # Mensagem enriquecida (sem afirmar que XML e fonte da verdade)
        msg = f"[XML] {nf_label}: {f['message']}"
        if corrigivel:
            msg += f" Sugestao: verificar {campo_sped} — XML indica {expected}."

        friendly = _build_friendly_xml(
            rule_id, numero_nfe, f, campo_sped, corrigivel,
        )

        doc_sug = _build_doc_suggestion_xml(
            rule_id, numero_nfe, f, campo_sped, corrigivel,
        )

        # Base legal fixa por regra de cruzamento
        legal_data = _LEGAL_BASIS_XML.get(rule_id)
        legal_json = json.dumps(legal_data, ensure_ascii=False) if legal_data else None

        # field_no correto para que o modal de edicao destaque o campo certo
        field_no = _FIELD_NO_C100.get(campo_sped or "", 0) if (register or "C100") == "C100" else 0

        # Hash de deduplicacao
        from ..models import compute_error_hash
        err_hash = compute_error_hash(line_no, register or "C100", campo_sped or f["campo_sped"], rule_id, f["valor_sped"])

        try:
            db.execute(
                """INSERT INTO validation_errors
                   (file_id, record_id, line_number, register, field_no, field_name,
                    value, expected_value, error_type, severity, message,
                    friendly_message, auto_correctable, categoria, certeza, impacto,
                    doc_suggestion, legal_basis, error_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'cruzamento_xml', 'objetivo', 'critico', ?, ?, ?)""",
                (
                    file_id, record_id, line_no, register or "C100",
                    field_no, campo_sped or f["campo_sped"],
                    f["valor_sped"], expected,
                    rule_id, severity, msg, friendly, auto_corr,
                    doc_sug, legal_json, err_hash,
                ),
            )
        except Exception as exc:
            logger.warning("Falha ao inserir validation_error XML %s: %s", rule_id, exc)

    db.commit()


def _finding(file_id, nfe_id, chave, rule_id, severity,
             campo_xml, valor_xml, campo_sped, valor_sped, diferenca, message,
             tracked=None):
    result = {
        "file_id": file_id, "nfe_id": nfe_id, "chave_nfe": chave,
        "rule_id": rule_id, "severity": severity,
        "campo_xml": campo_xml, "valor_xml": str(valor_xml) if valor_xml is not None else "",
        "campo_sped": campo_sped, "valor_sped": str(valor_sped) if valor_sped is not None else "",
        "diferenca": diferenca, "message": message,
    }
    if tracked:
        result["tracked"] = tracked
    return result


def _compare_value(findings, file_id, nfe_id, chave, rule_id, severity,
                   campo_xml, val_xml, campo_sped, val_sped, tolerance,
                   tracked=None):
    # Ausente != zero: se qualquer lado for None/vazio, skip (sem falso positivo)
    if val_xml is None or val_sped is None:
        return
    val_x = _to_float(val_xml)
    val_s = _to_float(val_sped)
    diff = abs(val_x - val_s)
    if diff > tolerance:
        findings.append(_finding(
            file_id, nfe_id, chave, rule_id, severity,
            campo_xml, f"{val_x:.2f}", campo_sped, f"{val_s:.2f}", diff,
            f"{campo_xml}={val_x:.2f} vs {campo_sped}={val_s:.2f} (dif={diff:.2f}).",
            tracked=tracked,
        ))
