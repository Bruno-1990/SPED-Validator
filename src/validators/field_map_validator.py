"""Conferência declarativa C100 ↔ XML via field_map.yaml (modo sped_xml).

Usa FieldComparator e colunas persistidas em nfe_xmls (MVP).
Campos do YAML sem coluna correspondente são ignorados até expandir o modelo.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..models import SpedRecord, ValidationError
from ..services.field_comparator import FieldComparator
from ..services.xml_service import _norm_cst as _norm_cst_xml
from .helpers import REGISTER_FIELDS

logger = logging.getLogger(__name__)

_FIELD_MAP_PATH = Path(__file__).resolve().parents[2] / "data" / "config" / "field_map.yaml"

# sped_campo (C100) → (coluna nfe_xmls, tipo lógico para extrair valor XML)
_NFE_XML_COL_MAP: dict[str, tuple[str, str]] = {
    "NUM_DOC": ("numero_nfe", "str"),
    "SER": ("serie", "str"),
    "COD_MOD": ("mod_nfe", "mod"),
    "DT_DOC": ("dh_emissao", "iso_dt"),
    "VL_DOC": ("vl_doc", "money"),
    "VL_ICMS": ("vl_icms", "money"),
    "VL_ICMS_ST": ("vl_icms_st", "money"),
    "VL_IPI": ("vl_ipi", "money"),
    "COD_SIT": ("prot_cstat", "str"),
}


def _norm_chave(ch: str) -> str:
    d = "".join(c for c in (ch or "") if c.isdigit())
    return d[:44] if len(d) >= 44 else d


@lru_cache(maxsize=1)
def _load_c100_header_rules() -> list[dict[str, Any]]:
    if not _FIELD_MAP_PATH.exists():
        logger.warning("field_map.yaml nao encontrado em %s", _FIELD_MAP_PATH)
        return []
    with _FIELD_MAP_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return list(data.get("c100_header") or [])


_NFE_SELECT_KEYS = (
    "chave_nfe", "numero_nfe", "serie", "mod_nfe", "dh_emissao",
    "vl_doc", "vl_icms", "vl_icms_st", "vl_ipi", "prot_cstat", "crt_emitente",
)


def _row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    if isinstance(row, (list, tuple)):
        return dict(zip(_NFE_SELECT_KEYS, row))
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}  # type: ignore[union-attr]
    return {}


def _load_nfe_by_chave(db: Any, file_id: int) -> dict[str, dict[str, Any]]:
    """chave_nfe normalizada → dict de colunas nfe_xmls."""
    try:
        rows = db.execute(
            "SELECT chave_nfe, numero_nfe, serie, mod_nfe, dh_emissao, vl_doc, vl_icms, "
            "vl_icms_st, vl_ipi, prot_cstat, crt_emitente "
            "FROM nfe_xmls WHERE file_id = ? AND status = 'active'",
            (file_id,),
        ).fetchall()
    except Exception as exc:
        logger.warning("nfe_xmls nao legivel: %s", exc)
        return {}

    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        d = _row_to_dict(row)
        ch = _norm_chave(str(d.get("chave_nfe") or ""))
        if not ch:
            continue
        out[ch] = d
    return out


def _xml_value_for_c100_field(xml_row: dict[str, Any], sped_campo: str) -> str | None:
    if sped_campo not in _NFE_XML_COL_MAP:
        return None
    col, kind = _NFE_XML_COL_MAP[sped_campo]
    raw = xml_row.get(col)
    if raw is None:
        return None
    if kind == "str":
        return str(raw).strip()
    if kind == "mod":
        try:
            return str(int(raw))
        except (TypeError, ValueError):
            return str(raw).strip()
    if kind == "iso_dt":
        return str(raw).strip()
    if kind == "money":
        try:
            return f"{float(raw):.2f}"
        except (TypeError, ValueError):
            return str(raw).strip()
    return str(raw).strip()


def _field_no(register: str, campo: str) -> int:
    names = REGISTER_FIELDS.get(register, [])
    if campo not in names:
        return 0
    return names.index(campo) + 1


def _has_cruzamento_xml_same_field(
    db: Any,
    file_id: int,
    line_number: int,
    field_name: str,
    register: str = "C100",
) -> bool:
    """Evita duplicar apontamento quando o cruzamento XML legado ja cobre o mesmo registro/campo."""
    fn = field_name or ""
    try:
        row = db.execute(
            """SELECT 1 FROM validation_errors
               WHERE file_id = ? AND line_number = ? AND register = ?
                 AND COALESCE(field_name, '') = ? AND categoria = 'cruzamento_xml'
                 AND status = 'open' LIMIT 1""",
            (file_id, line_number, register, fn),
        ).fetchone()
    except Exception as exc:
        msg = str(exc).lower()
        if "categoria" not in msg and "column" not in msg and "no such column" not in msg:
            raise
        return False
    return bool(row)


def _format_expected_like_sped(sped_campo: str, sped_raw: str, xml_canonical: str) -> str:
    """Valor de referência (XML) aproximado ao estilo do campo já gravado no SPED."""
    monetary_like = sped_campo == "QTD" or sped_campo.startswith("VL_")
    if not monetary_like:
        return xml_canonical
    try:
        v = float(str(xml_canonical).replace(",", "."))
    except ValueError:
        return xml_canonical
    dec = 4 if sped_campo == "QTD" else 2
    out = f"{v:.{dec}f}"
    if dec == 4:
        out = out.rstrip("0").rstrip(".")
    if "," in (sped_raw or "") and "." not in (sped_raw or ""):
        out = out.replace(".", ",")
    return out


def validate_field_map_c100(
    db: Any,
    file_id: int,
    records: list[SpedRecord],
    context: Any,
) -> list[ValidationError]:
    """Emite erros SPED↔XML para C100 conforme field_map e nfe_xmls."""
    if getattr(context, "mode", "sped_only") != "sped_xml":
        return []
    if not getattr(context, "has_xmls", False):
        return []

    rules = _load_c100_header_rules()
    if not rules:
        return []

    c100_names = set(REGISTER_FIELDS.get("C100", []))
    nfe_by_chave = _load_nfe_by_chave(db, file_id)
    if not nfe_by_chave:
        return []

    comparator = FieldComparator()
    errors: list[ValidationError] = []

    for rec in records:
        if rec.register != "C100":
            continue
        ch_raw = rec.fields.get("CHV_NFE", "").strip()
        if not ch_raw or ch_raw == "0" * 44:
            continue
        ch = _norm_chave(ch_raw)
        xml_row = nfe_by_chave.get(ch)
        if not xml_row:
            continue

        crt_emit = xml_row.get("crt_emitente")
        cmp_ctx = {
            "crt_emitente": crt_emit,
            "emitentes_sn": getattr(context, "emitentes_sn", set()) or set(),
        }

        for rule in rules:
            sped_campo = rule.get("sped_campo") or ""
            if not sped_campo or sped_campo == "CHV_NFE":
                continue
            if sped_campo not in c100_names:
                continue
            if sped_campo not in _NFE_XML_COL_MAP:
                continue

            sped_val = rec.fields.get(sped_campo, "")
            xml_raw = _xml_value_for_c100_field(xml_row, sped_campo)
            tipo = (rule.get("tipo") or "EXACT").upper()

            if tipo == "DERIVED" and sped_campo == "COD_SIT":
                mapeamento = rule.get("mapeamento") or {}
                cmp_ctx_rule = {**cmp_ctx, "mapeamento": mapeamento}
                res = comparator.compare(sped_val, xml_raw, "DERIVED", cmp_ctx_rule)
            elif tipo == "DATE":
                res = comparator.compare(sped_val, xml_raw, "DATE", cmp_ctx)
            elif tipo == "MONETARY":
                res = comparator.compare(sped_val, xml_raw, "MONETARY", cmp_ctx)
            elif tipo == "EXACT":
                res = comparator.compare(sped_val, xml_raw, "EXACT", cmp_ctx)
            else:
                res = comparator.compare(sped_val, xml_raw, "EXACT", cmp_ctx)

            if res is None or res.status in ("ok", "ok_arredondamento"):
                continue

            regra_id = rule.get("regra_id") or sped_campo
            error_type = f"FM_{regra_id}"[:80]
            fn = _field_no("C100", sped_campo)
            exp = _format_expected_like_sped(sped_campo, sped_val, res.xml_val or (xml_raw or ""))

            msg = (
                f"Divergencia SPED x XML (NF-e {ch[:8]}…): campo C100.{sped_campo} "
                f"SPED={res.sped_val or sped_val!r} vs XML={res.xml_val or xml_raw!r}."
            )
            if res.nota:
                msg += f" {res.nota}"

            if _has_cruzamento_xml_same_field(db, file_id, rec.line_number, sped_campo, "C100"):
                continue

            errors.append(
                ValidationError(
                    line_number=rec.line_number,
                    register="C100",
                    field_no=fn,
                    field_name=sped_campo,
                    value=str(sped_val),
                    error_type=error_type,
                    message=msg,
                    expected_value=exp,
                    categoria="field_map_xml",
                    certeza="objetivo",
                    impacto="relevante",
                )
            )

    return errors


# Onda 2: itens NF-e (parsed_json) x C170 — mesmos tipos do field_map.yaml (subconjunto).
_C170_WAVE2_CAMPOS = frozenset({
    "COD_ITEM",
    "CFOP",
    "QTD",
    "VL_ITEM",
    "CST_ICMS",
    "VL_BC_ICMS",
    "ALIQ_ICMS",
    "VL_ICMS",
})


@lru_cache(maxsize=1)
def _load_c170_wave_rules() -> list[dict[str, Any]]:
    if not _FIELD_MAP_PATH.exists():
        return []
    with _FIELD_MAP_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    rules = list(data.get("c170_items") or [])
    return [r for r in rules if (r.get("sped_campo") or "") in _C170_WAVE2_CAMPOS]


def _xml_item_value(item: dict[str, Any], sped_campo: str) -> str | None:
    """Extrai valor comparável do item do XML (estrutura parse_nfe_xml)."""
    if sped_campo == "COD_ITEM":
        v = item.get("cod_produto")
        return str(v).strip() if v is not None else None
    if sped_campo == "CFOP":
        v = item.get("cfop")
        return str(v).strip() if v is not None else None
    if sped_campo == "QTD":
        v = item.get("qtd")
        if v is None:
            return None
        return str(v).replace(",", ".")
    if sped_campo == "VL_ITEM":
        v = item.get("vl_prod")
        if v is None:
            return None
        return f"{float(v):.2f}"
    if sped_campo == "CST_ICMS":
        v = item.get("cst_icms")
        return str(v).strip() if v is not None else None
    if sped_campo == "VL_BC_ICMS":
        v = item.get("vbc_icms")
        if v is None:
            return None
        return f"{float(v):.2f}"
    if sped_campo == "ALIQ_ICMS":
        v = item.get("aliq_icms")
        if v is None:
            return None
        return str(v).replace(",", ".")
    if sped_campo == "VL_ICMS":
        v = item.get("vl_icms")
        if v is None:
            return None
        return f"{float(v):.2f}"
    return None


def _load_parsed_items_by_chave(
    db: Any, file_id: int
) -> tuple[dict[str, dict[int, dict[str, Any]]], dict[str, Any]]:
    """chave_nfe normalizada → (num_item → item dict); crt por chave."""
    items: dict[str, dict[int, dict[str, Any]]] = {}
    crt_by_chave: dict[str, Any] = {}
    try:
        rows = db.execute(
            "SELECT chave_nfe, parsed_json, crt_emitente FROM nfe_xmls "
            "WHERE file_id = ? AND status = 'active'",
            (file_id,),
        ).fetchall()
    except Exception as exc:
        logger.warning("nfe_xmls nao legivel para C170 field_map: %s", exc)
        return {}, {}

    for row in rows:
        if isinstance(row, dict):
            ch_raw = row.get("chave_nfe") or ""
            pj = row.get("parsed_json")
            crt = row.get("crt_emitente")
        else:
            ch_raw = row[0]
            pj = row[1]
            crt = row[2] if len(row) > 2 else None
        ch = _norm_chave(str(ch_raw or ""))
        if not ch:
            continue
        crt_by_chave[ch] = crt
        if not pj:
            continue
        if isinstance(pj, (dict, list)):
            data = pj  # type: ignore[assignment]
        else:
            try:
                data = json.loads(pj)
            except (json.JSONDecodeError, TypeError):
                continue
        itens = data.get("itens") if isinstance(data, dict) else None
        if not isinstance(itens, list):
            continue
        bucket: dict[int, dict[str, Any]] = {}
        for it in itens:
            if not isinstance(it, dict):
                continue
            try:
                ni = int(it.get("num_item") or 0)
            except (TypeError, ValueError):
                ni = 0
            if ni <= 0:
                continue
            bucket[ni] = it
        if bucket:
            items[ch] = bucket
    return items, crt_by_chave


def validate_field_map_c170(
    db: Any,
    file_id: int,
    records: list[SpedRecord],
    context: Any,
) -> list[ValidationError]:
    """Emite erros SPED↔XML para C170 (itens) conforme field_map c170_items (onda 2)."""
    if getattr(context, "mode", "sped_only") != "sped_xml":
        return []
    if not getattr(context, "has_xmls", False):
        return []

    rules = _load_c170_wave_rules()
    if not rules:
        return []

    c170_names = set(REGISTER_FIELDS.get("C170", []))
    items_by_chave, crt_by_chave = _load_parsed_items_by_chave(db, file_id)
    if not items_by_chave:
        return []

    comparator = FieldComparator()
    errors: list[ValidationError] = []
    last_chave = ""

    for rec in sorted(records, key=lambda r: r.line_number):
        if rec.register == "C100":
            ch_raw = (rec.fields.get("CHV_NFE") or "").strip()
            if ch_raw and ch_raw != "0" * 44:
                last_chave = _norm_chave(ch_raw)
            else:
                last_chave = ""
            continue

        if rec.register != "C170" or not last_chave:
            continue

        xml_bucket = items_by_chave.get(last_chave)
        if not xml_bucket:
            continue

        try:
            num_item = int(str(rec.fields.get("NUM_ITEM", "0")).strip())
        except (TypeError, ValueError):
            num_item = 0
        if num_item <= 0:
            continue

        xml_item = xml_bucket.get(num_item)
        if not xml_item:
            continue

        crt_emit = crt_by_chave.get(last_chave)
        cmp_ctx: dict[str, Any] = {
            "crt_emitente": crt_emit,
            "emitentes_sn": getattr(context, "emitentes_sn", set()) or set(),
        }

        for rule in rules:
            sped_campo = rule.get("sped_campo") or ""
            if not sped_campo or sped_campo not in c170_names:
                continue

            xml_raw = _xml_item_value(xml_item, sped_campo)
            if xml_raw is None and (rule.get("default_policy") or "").lower() == "optional":
                continue

            sped_val = rec.fields.get(sped_campo, "")
            tipo = (rule.get("tipo") or "EXACT").upper()

            if tipo == "MONETARY":
                res = comparator.compare(sped_val, xml_raw, "MONETARY", cmp_ctx)
            elif tipo == "PERCENTAGE":
                res = comparator.compare(sped_val, xml_raw, "PERCENTAGE", cmp_ctx)
            elif tipo == "CST_AWARE":
                res = comparator.compare(sped_val, xml_raw, "CST_AWARE", cmp_ctx)
            elif tipo == "EXACT":
                res = comparator.compare(sped_val, xml_raw, "EXACT", cmp_ctx)
            else:
                res = comparator.compare(sped_val, xml_raw, "EXACT", cmp_ctx)

            if res is None or res.status in ("ok", "ok_arredondamento"):
                continue

            regra_id = rule.get("regra_id") or sped_campo
            error_type = f"FM_{regra_id}"[:80]
            fn = _field_no("C170", sped_campo)
            exp = _format_expected_like_sped(sped_campo, sped_val, res.xml_val or (xml_raw or ""))

            msg = (
                f"Divergencia SPED x XML (NF-e {last_chave[:8]}…, item {num_item}): "
                f"C170.{sped_campo} SPED={res.sped_val or sped_val!r} vs XML={res.xml_val or xml_raw!r}."
            )
            if res.nota:
                msg += f" {res.nota}"

            if _has_cruzamento_xml_same_field(db, file_id, rec.line_number, sped_campo, "C170"):
                continue

            errors.append(
                ValidationError(
                    line_number=rec.line_number,
                    register="C170",
                    field_no=fn,
                    field_name=sped_campo,
                    value=str(sped_val),
                    error_type=error_type,
                    message=msg,
                    expected_value=exp,
                    categoria="field_map_xml",
                    certeza="objetivo",
                    impacto="relevante",
                )
            )

    return errors


# ── C190 agregado (field_map.yaml c190_aggregation) x soma dos itens no XML (parsed_json)

_XML_SOMA_TO_ITEM: dict[str, str] = {
    "vBC": "vbc_icms",
    "vICMS": "vl_icms",
    "vBCST": "vbc_icms_st",
    "vICMSST": "vl_icms_st",
}


def _cfop_agg_key(cfop: str) -> str:
    d = re.sub(r"\D", "", (cfop or "").strip())
    if len(d) >= 4:
        return d[-4:]
    return d.zfill(4)[:4] if d else ""


@lru_cache(maxsize=1)
def _load_c190_agg_campos() -> list[dict[str, Any]]:
    if not _FIELD_MAP_PATH.exists():
        return []
    with _FIELD_MAP_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    block = data.get("c190_aggregation") or {}
    return list(block.get("campos") or [])


def _aggregate_xml_c190_by_grupo(
    item_bucket: dict[int, dict[str, Any]],
    xml_soma: list[str],
) -> dict[tuple[str, str, float], dict[str, float]]:
    """Soma por (CST, CFOP, ALIQ) os montantes vindos dos itens do XML."""
    agg: dict[tuple[str, str, float], dict[str, float]] = defaultdict(
        lambda: {tag: 0.0 for tag in xml_soma}
    )
    for it in item_bucket.values():
        if not isinstance(it, dict):
            continue
        cst = _norm_cst_xml(str(it.get("cst_icms") or ""))
        cfop = _cfop_agg_key(str(it.get("cfop") or ""))
        try:
            aliq = round(float(str(it.get("aliq_icms") or "0").replace(",", ".")), 2)
        except (TypeError, ValueError):
            aliq = 0.0
        key = (cst, cfop, aliq)
        for tag in xml_soma:
            pyk = _XML_SOMA_TO_ITEM.get(tag)
            if not pyk:
                continue
            try:
                agg[key][tag] += float(it.get(pyk) or 0)
            except (TypeError, ValueError):
                pass
    return agg


def _aggregate_sped_c190_by_grupo(
    c190_recs: list[SpedRecord],
    sped_campos: list[str],
) -> tuple[dict[tuple[str, str, float], dict[str, float]], dict[tuple[str, str, float], int]]:
    """Soma por (CST, CFOP, ALIQ) os campos do C190; retorna tambem linha do primeiro C190 por grupo."""
    agg: dict[tuple[str, str, float], dict[str, float]] = defaultdict(
        lambda: {c: 0.0 for c in sped_campos}
    )
    line_by_key: dict[tuple[str, str, float], int] = {}
    for rec in c190_recs:
        cst = _norm_cst_xml(str(rec.fields.get("CST_ICMS") or ""))
        cfop = _cfop_agg_key(str(rec.fields.get("CFOP") or ""))
        try:
            aliq = round(float(str(rec.fields.get("ALIQ_ICMS") or "0").replace(",", ".")), 2)
        except (TypeError, ValueError):
            aliq = 0.0
        key = (cst, cfop, aliq)
        if key not in line_by_key:
            line_by_key[key] = rec.line_number
        for c in sped_campos:
            try:
                agg[key][c] += float(str(rec.fields.get(c) or "0").replace(",", "."))
            except (TypeError, ValueError):
                pass
    return agg, line_by_key


def _flush_c190_agg_for_chave(
    db: Any,
    file_id: int,
    chave: str,
    c190_recs: list[SpedRecord],
    item_bucket: dict[int, dict[str, Any]],
    context: Any,
) -> list[ValidationError]:
    out: list[ValidationError] = []
    campos_rules = _load_c190_agg_campos()
    if not campos_rules or not c190_recs or not item_bucket:
        return out

    comparator = FieldComparator()
    cmp_ctx: dict[str, Any] = {"emitentes_sn": getattr(context, "emitentes_sn", set()) or set()}

    for rule in campos_rules:
        xml_soma = list(rule.get("xml_soma") or [])
        sped_campos = list(rule.get("sped_campos") or [])
        if len(xml_soma) != len(sped_campos) or not xml_soma:
            continue
        regra_id = (rule.get("regra_id") or "XML_C190_DIVERGE")[:80]
        error_type = f"FM_{regra_id}"[:80]

        xml_agg = _aggregate_xml_c190_by_grupo(item_bucket, xml_soma)
        sped_agg, line_by_key = _aggregate_sped_c190_by_grupo(c190_recs, sped_campos)

        common_keys = set(xml_agg.keys()) & set(sped_agg.keys())
        for key in sorted(common_keys, key=lambda k: (k[0], k[1], k[2])):
            cst_k, cfop_k, aliq_k = key
            ln = line_by_key.get(key) or c190_recs[0].line_number
            for xml_tag, sped_field in zip(xml_soma, sped_campos):
                x = xml_agg[key].get(xml_tag, 0.0)
                s = sped_agg[key].get(sped_field, 0.0)
                x_str = f"{float(x):.2f}"
                s_str = f"{float(s):.2f}"
                res = comparator.compare(s_str, x_str, "MONETARY", cmp_ctx)
                if res is None or res.status in ("ok", "ok_arredondamento"):
                    continue
                fn = _field_no("C190", sped_field)
                sped_raw = ""
                for r in c190_recs:
                    if r.line_number == ln:
                        sped_raw = str(r.fields.get(sped_field, "") or "")
                        break
                if not sped_raw:
                    sped_raw = s_str
                exp = _format_expected_like_sped(sped_field, sped_raw, res.xml_val or x_str)
                msg = (
                    f"Divergencia SPED x XML (NF-e {chave[:8]}…, grupo CST={cst_k} CFOP={cfop_k} "
                    f"ALIQ={aliq_k}%): C190.{sped_field} consolidado SPED={res.sped_val or s_str!r} "
                    f"vs soma itens XML ({xml_tag})={res.xml_val or x_str!r}."
                )
                if res.nota:
                    msg += f" {res.nota}"
                if _has_cruzamento_xml_same_field(db, file_id, ln, sped_field, "C190"):
                    continue
                out.append(
                    ValidationError(
                        line_number=ln,
                        register="C190",
                        field_no=fn,
                        field_name=sped_field,
                        value=str(s_str),
                        error_type=error_type,
                        message=msg,
                        expected_value=exp,
                        categoria="field_map_xml",
                        certeza="objetivo",
                        impacto="relevante",
                    )
                )
    return out


def validate_field_map_c190(
    db: Any,
    file_id: int,
    records: list[SpedRecord],
    context: Any,
) -> list[ValidationError]:
    """Emite erros SPED x XML para C190 (agregacao por CST/CFOP/ALIQ) conforme field_map."""
    if getattr(context, "mode", "sped_only") != "sped_xml":
        return []
    if not getattr(context, "has_xmls", False):
        return []
    if not _load_c190_agg_campos():
        return []

    items_by_chave, _crt = _load_parsed_items_by_chave(db, file_id)
    if not items_by_chave:
        return []

    errors: list[ValidationError] = []
    prev_chave = ""
    pending_c190: list[SpedRecord] = []

    for rec in sorted(records, key=lambda r: r.line_number):
        if rec.register == "C100":
            if prev_chave and pending_c190:
                bucket = items_by_chave.get(prev_chave) or {}
                errors.extend(
                    _flush_c190_agg_for_chave(db, file_id, prev_chave, pending_c190, bucket, context)
                )
            pending_c190 = []
            ch_raw = (rec.fields.get("CHV_NFE") or "").strip()
            if ch_raw and ch_raw != "0" * 44:
                prev_chave = _norm_chave(ch_raw)
            else:
                prev_chave = ""
            continue
        if rec.register == "C190" and prev_chave:
            pending_c190.append(rec)

    if prev_chave and pending_c190:
        bucket = items_by_chave.get(prev_chave) or {}
        errors.extend(
            _flush_c190_agg_for_chave(db, file_id, prev_chave, pending_c190, bucket, context)
        )

    return errors
