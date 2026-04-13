"""DocumentScopeBuilder — constroi escopos de documento para cruzamento.

Le C100/C170/C190 do SPED e NF-e XMLs, pareia itens e gera DocumentScope
para cada par (C100, XML). Implementa etapas 0 e 4 do pipeline (spec).
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict

from .cross_engine_models import (
    XML_ELIGIBLE_MODELS,
    CrossValidationFinding,
    DocumentScope,
    ItemMatchState,
    ItemNature,
    ItemPair,
    RuleOutcome,
    Severity,
    SpedC170Item,
    XmlItemParsed,
    classify_item_nature,
)

logger = logging.getLogger(__name__)

MIN_ITEM_MATCH_SCORE = 0.70


def _to_float(val) -> float:
    if val is None:
        return 0.0
    try:
        return round(float(str(val).replace(",", ".")), 2)
    except (ValueError, TypeError):
        return 0.0


def _norm(s: str) -> str:
    return re.sub(r"\D", "", (s or "").strip())


def _fields_dict(fields_json: str) -> dict:
    """Converte fields_json armazenado no sped_records para dict."""
    if not fields_json:
        return {}
    if isinstance(fields_json, dict):
        return fields_json
    try:
        return json.loads(fields_json)
    except (json.JSONDecodeError, TypeError):
        return {}


# ───────────────��──────────────────────────────────────────────────────
# Construcao de C170 items a partir do banco
# ───────────────────────────────────────────────���──────────────────────

def _build_c170(row: dict) -> SpedC170Item:
    """Constroi SpedC170Item a partir de um row do sped_records."""
    f = _fields_dict(row.get("fields_json", ""))
    return SpedC170Item(
        record_id=row.get("id", 0),
        line_number=row.get("line_number", 0),
        num_item=int(f.get("NUM_ITEM", 0) or 0),
        cod_item=f.get("COD_ITEM", ""),
        ncm=f.get("NCM", ""),
        cfop=f.get("CFOP", "")[:4],
        vl_item=_to_float(f.get("VL_ITEM")),
        vl_desc=_to_float(f.get("VL_DESC")),
        qtd=_to_float(f.get("QTD")),
        unid=f.get("UNID", ""),
        cst_icms=f.get("CST_ICMS", ""),
        vl_bc_icms=_to_float(f.get("VL_BC_ICMS")),
        aliq_icms=_to_float(f.get("ALIQ_ICMS")),
        vl_icms=_to_float(f.get("VL_ICMS")),
        vl_bc_icms_st=_to_float(f.get("VL_BC_ICMS_ST")),
        vl_icms_st=_to_float(f.get("VL_ICMS_ST")),
        cst_ipi=f.get("CST_IPI", ""),
        vl_ipi=_to_float(f.get("VL_IPI")),
        cst_pis=f.get("CST_PIS", ""),
        vl_pis=_to_float(f.get("VL_PIS")),
        cst_cofins=f.get("CST_COFINS", ""),
        vl_cofins=_to_float(f.get("VL_COFINS")),
        ind_apur=f.get("IND_APUR", ""),
        fields=f,
    )


def _build_xml_item(row: dict) -> XmlItemParsed:
    """Constroi XmlItemParsed a partir de um row de nfe_itens."""
    return XmlItemParsed(
        num_item=row.get("num_item", 0) or 0,
        cod_produto=row.get("cod_produto", "") or "",
        ncm=row.get("ncm", "") or "",
        cfop=row.get("cfop", "") or "",
        vl_prod=_to_float(row.get("vl_prod")),
        vl_desc=_to_float(row.get("vl_desc")),
        cst_icms=row.get("cst_icms", "") or "",
        vbc_icms=_to_float(row.get("vbc_icms")),
        aliq_icms=_to_float(row.get("aliq_icms")),
        vl_icms=_to_float(row.get("vl_icms")),
        cst_ipi=row.get("cst_ipi", "") or "",
        vl_ipi=_to_float(row.get("vl_ipi")),
        cst_pis=row.get("cst_pis", "") or "",
        vl_pis=_to_float(row.get("vl_pis")),
        cst_cofins=row.get("cst_cofins", "") or "",
        vl_cofins=_to_float(row.get("vl_cofins")),
        grupo_icms=row.get("grupo_icms", "") or "",
        grupo_ipi=row.get("grupo_ipi") or None,
        grupo_pis=row.get("grupo_pis") or None,
        grupo_cofins=row.get("grupo_cofins") or None,
    )


# ────────────────��─────────────────────────────���───────────────────────
# Pareamento de itens (Etapa 4 do pipeline)
# ───────────────────────────────────────────────────���──────────────────

def _match_items_exact(
    c170_items: list[SpedC170Item],
    xml_items: list[XmlItemParsed],
) -> tuple[list[ItemPair], list[XmlItemParsed], list[SpedC170Item]]:
    """Pareamento exato por nItem (etapa 4 — MATCH_EXATO)."""
    xml_by_num = {xi.num_item: xi for xi in xml_items}
    pairs: list[ItemPair] = []
    c170_sem = []
    used_xml_nums = set()

    for c170 in c170_items:
        xi = xml_by_num.get(c170.num_item)
        if xi is not None:
            pairs.append(ItemPair(
                c170=c170,
                xml_item=xi,
                match_state=ItemMatchState.MATCH_EXATO,
                match_score=1.0,
                item_nature=classify_item_nature(c170.cfop, c170.vl_desc, c170.vl_item),
            ))
            used_xml_nums.add(c170.num_item)
        else:
            c170_sem.append(c170)

    xml_sem = [xi for xi in xml_items if xi.num_item not in used_xml_nums]
    return pairs, xml_sem, c170_sem


def _heuristic_score(c170: SpedC170Item, xi: XmlItemParsed) -> float:
    """Calcula score heuristico de match entre C170 e item XML."""
    score = 0.0
    total = 0.0

    # cod_item vs cod_produto (peso 30)
    total += 30
    if c170.cod_item and xi.cod_produto and c170.cod_item.strip() == xi.cod_produto.strip():
        score += 30

    # NCM (peso 25)
    total += 25
    ncm_c = _norm(c170.ncm)[:8]
    ncm_x = _norm(xi.ncm)[:8]
    if ncm_c and ncm_x:
        if ncm_c == ncm_x:
            score += 25
        elif ncm_c[:4] == ncm_x[:4]:
            score += 12

    # CFOP (peso 20)
    total += 20
    if c170.cfop and xi.cfop and c170.cfop[:4] == xi.cfop[:4]:
        score += 20

    # Valor (peso 25)
    total += 25
    if c170.vl_item > 0 and xi.vl_prod > 0:
        diff = abs(c170.vl_item - xi.vl_prod)
        if diff < 0.02:
            score += 25
        elif diff / max(c170.vl_item, xi.vl_prod) < 0.05:
            score += 15

    return score / total if total > 0 else 0.0


def _match_items_heuristic(
    c170_sem: list[SpedC170Item],
    xml_sem: list[XmlItemParsed],
) -> tuple[list[ItemPair], list[XmlItemParsed], list[SpedC170Item]]:
    """Pareamento heuristico para itens sem match exato."""
    if not c170_sem or not xml_sem:
        return [], xml_sem, c170_sem

    pairs: list[ItemPair] = []
    used_xml = set()
    still_unmatched_c170 = []

    for c170 in c170_sem:
        best_score = 0.0
        best_xi = None
        second_score = 0.0

        for i, xi in enumerate(xml_sem):
            if i in used_xml:
                continue
            s = _heuristic_score(c170, xi)
            if s > best_score:
                second_score = best_score
                best_score = s
                best_xi = (i, xi)
            elif s > second_score:
                second_score = s

        if best_xi is None or best_score < 0.50:
            still_unmatched_c170.append(c170)
            continue

        # Ambiguidade: dois candidatos com score equivalente
        if second_score > 0 and (best_score - second_score) < 0.10:
            pairs.append(ItemPair(
                c170=c170,
                xml_item=best_xi[1],
                match_state=ItemMatchState.AMBIGUO,
                match_score=best_score,
                item_nature=classify_item_nature(c170.cfop, c170.vl_desc, c170.vl_item),
            ))
            used_xml.add(best_xi[0])
            continue

        if best_score >= MIN_ITEM_MATCH_SCORE:
            state = ItemMatchState.MATCH_PROVAVEL
        else:
            state = ItemMatchState.MATCH_HEURISTICO

        pairs.append(ItemPair(
            c170=c170,
            xml_item=best_xi[1],
            match_state=state,
            match_score=best_score,
            item_nature=classify_item_nature(c170.cfop, c170.vl_desc, c170.vl_item),
        ))
        used_xml.add(best_xi[0])

    remaining_xml = [xi for i, xi in enumerate(xml_sem) if i not in used_xml]
    return pairs, remaining_xml, still_unmatched_c170


# ──────────────────────���───────────────────────��───────────────────────
# Deteccao de NF complementar
# ────────────���───────────────────────────────��─────────────────────────

def _detect_complementar(c100_fields: dict, has_c113: bool) -> int:
    """Dois sinais = is_complementar=1 (spec seção 3.9)."""
    cod_sit = c100_fields.get("COD_SIT", "")
    sinal_cod_sit = (cod_sit == "06")
    sinal_c113 = has_c113
    if sinal_cod_sit and sinal_c113:
        return 1
    return 0


# ─────────────���─────────────────────────────────���──────────────────────
# Builder principal
# ──────────────────────────────────────────────────────────────────────

class DocumentScopeBuilder:
    """Constroi DocumentScopes a partir do banco de dados.

    Etapa 0 (elegibilidade) e Etapa 4 (pareamento) do pipeline.
    """

    def __init__(self, db, file_id: int, regime: str = "", cod_ver: str = ""):
        self.db = db
        self.file_id = file_id
        self.regime = regime
        self.cod_ver = cod_ver

    def build_all(self) -> list[DocumentScope]:
        """Constroi todos os escopos para o file_id."""
        # 1. Carregar C100 com chave NF-e
        c100_rows = self._load_c100()
        if not c100_rows:
            return []

        # 2. Carregar XMLs
        xml_by_chave = self._load_xmls()

        # 3. Carregar C170 e C190 agrupados por C100 (parent_id ou ordem de linhas)
        c170_by_c100, c190_by_c100 = self._load_c170_and_c190(c100_rows)

        # 4. Carregar C113 para deteccao de complementar
        c113_chaves = self._load_c113_chaves()

        # 6. Carregar itens XML agrupados por nfe_id
        xml_items_by_nfe = self._load_xml_items(xml_by_chave)

        # 6. Construir escopos
        scopes: list[DocumentScope] = []
        for c100 in c100_rows:
            f = _fields_dict(c100.get("fields_json", ""))
            chave = _norm(f.get("CHV_NFE", ""))
            if not chave:
                continue

            cod_mod = f.get("COD_MOD", "55")
            scope = DocumentScope(
                file_id=self.file_id,
                chave_nfe=chave,
                c100_record_id=c100.get("id", 0),
                c100_line_number=c100.get("line_number", 0),
                c100_fields=f,
                regime=self.regime,
                ind_emit=f.get("IND_EMIT", "0"),
                cod_mod=cod_mod,
                cod_sit=f.get("COD_SIT", ""),
                dt_doc=f.get("DT_DOC", ""),
                dt_e_s=f.get("DT_E_S", ""),
                vl_doc=_to_float(f.get("VL_DOC")),
                vl_merc=_to_float(f.get("VL_MERC")),
                vl_icms=_to_float(f.get("VL_ICMS")),
                vl_icms_st=_to_float(f.get("VL_ICMS_ST")),
                vl_ipi=_to_float(f.get("VL_IPI")),
                vl_pis=_to_float(f.get("VL_PIS")),
                vl_cofins=_to_float(f.get("VL_COFINS")),
                vl_frt=_to_float(f.get("VL_FRT")),
                vl_seg=_to_float(f.get("VL_SEG")),
                vl_out_da=_to_float(f.get("VL_OUT_DA")),
            )

            # Elegibilidade por modelo (Etapa 0)
            if cod_mod not in XML_ELIGIBLE_MODELS:
                scope.xml_eligible = 0
                scope.match_status = "NAO_APLICAVEL"
                scopes.append(scope)
                continue

            # NF complementar
            has_c113 = chave in c113_chaves
            scope.is_complementar = _detect_complementar(f, has_c113)

            # Parear com XML
            xml = xml_by_chave.get(chave)
            if xml:
                scope.nfe_id = xml.get("id", 0)
                scope.xml_data = xml
                scope.match_status = "matched"

                # Verificar cancelamento/denegacao
                cstat = str(xml.get("prot_cstat", ""))
                if cstat in ("101", "135"):
                    scope.match_status = "cancelada"
                elif cstat in ("110", "301", "302"):
                    scope.match_status = "cancelada"

                # Parear itens
                c170_list = c170_by_c100.get(c100.get("id", 0), [])
                xml_item_list = xml_items_by_nfe.get(scope.nfe_id, [])

                exact_pairs, xml_rem, c170_rem = _match_items_exact(c170_list, xml_item_list)
                heur_pairs, xml_final, c170_final = _match_items_heuristic(c170_rem, xml_rem)

                scope.item_pairs = exact_pairs + heur_pairs
                scope.xml_items_sem_match = xml_final
                scope.c170_sem_match = c170_final
            else:
                scope.match_status = "sem_xml"
                # C170 sem XML
                c170_list = c170_by_c100.get(c100.get("id", 0), [])
                scope.c170_sem_match = c170_list

            # C190 do documento (para XC051 triangular)
            scope.c190_records = c190_by_c100.get(c100.get("id", 0), [])

            scopes.append(scope)

        # Gerar scopes para XMLs sem C100
        matched_chaves = {s.chave_nfe for s in scopes}
        for chave, xml in xml_by_chave.items():
            if chave not in matched_chaves:
                scope = DocumentScope(
                    file_id=self.file_id,
                    chave_nfe=chave,
                    nfe_id=xml.get("id", 0),
                    xml_data=xml,
                    match_status="sem_c100",
                    regime=self.regime,
                )
                xml_item_list = xml_items_by_nfe.get(scope.nfe_id, [])
                scope.xml_items_sem_match = xml_item_list
                scopes.append(scope)

        logger.info(
            "DocumentScopeBuilder: %d escopos construidos "
            "(matched=%d, sem_xml=%d, sem_c100=%d, nao_aplicavel=%d)",
            len(scopes),
            sum(1 for s in scopes if s.match_status == "matched"),
            sum(1 for s in scopes if s.match_status == "sem_xml"),
            sum(1 for s in scopes if s.match_status == "sem_c100"),
            sum(1 for s in scopes if s.match_status == "NAO_APLICAVEL"),
        )

        return scopes

    # ── Loaders de banco ─────────────────────────────────────────────

    def _load_c100(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT id, line_number, fields_json FROM sped_records "
            "WHERE file_id = ? AND register = 'C100' ORDER BY line_number",
            (self.file_id,),
        ).fetchall()
        return [dict(r) if hasattr(r, "keys") else {"id": r[0], "line_number": r[1], "fields_json": r[2]} for r in rows]

    def _load_xmls(self) -> dict[str, dict]:
        cur = self.db.execute(
            "SELECT * FROM nfe_xmls WHERE file_id = ? AND status = 'active'",
            (self.file_id,),
        )
        cols = [desc[0] for desc in cur.description] if cur.description else []
        rows = cur.fetchall()
        result = {}
        for r in rows:
            d = dict(r) if hasattr(r, "keys") else dict(zip(cols, r)) if cols else {}
            chave = _norm(d.get("chave_nfe", ""))
            if chave:
                # Sintetizar dict totais a partir dos campos flat do DB
                if "totais" not in d:
                    d["totais"] = {
                        "vNF": _to_float(d.get("vl_doc")),
                        "vICMS": _to_float(d.get("vl_icms")),
                        "vST": _to_float(d.get("vl_icms_st")),
                        "vIPI": _to_float(d.get("vl_ipi")),
                        "vPIS": _to_float(d.get("vl_pis")),
                        "vCOFINS": _to_float(d.get("vl_cofins")),
                        "vProd": _to_float(d.get("vl_merc", 0)),
                        "vFrete": 0.0,
                        "vSeg": 0.0,
                        "vOutro": 0.0,
                        "vICMSDeson": 0.0,
                    }
                result[chave] = d
        return result

    def _load_c170_and_c190(self, c100_rows: list[dict]) -> tuple[dict[int, list[SpedC170Item]], dict[int, list[dict]]]:
        """Carrega C170 e C190 agrupados pelo C100 pai.

        Usa parent_id quando disponivel. Quando parent_id e NULL (parser antigo),
        agrupa por ordem de linhas: C170/C190 pertencem ao C100 que os precede.
        """
        c100_ids = {r["id"] for r in c100_rows}
        c100_by_line = {r["line_number"]: r["id"] for r in c100_rows}

        # Tentar via parent_id primeiro
        has_parent = self.db.execute(
            "SELECT COUNT(*) FROM sped_records "
            "WHERE file_id = ? AND register IN ('C170','C190') AND parent_id IS NOT NULL LIMIT 1",
            (self.file_id,),
        ).fetchone()[0]

        c170_result: dict[int, list[SpedC170Item]] = defaultdict(list)
        c190_result: dict[int, list[dict]] = defaultdict(list)

        if has_parent:
            # Via parent_id (parser moderno)
            placeholders = ",".join("?" * len(c100_ids))
            for reg in ("C170", "C190"):
                rows = self.db.execute(
                    f"SELECT id, line_number, parent_id, fields_json FROM sped_records "
                    f"WHERE file_id = ? AND register = ? AND parent_id IN ({placeholders}) "
                    f"ORDER BY line_number",
                    [self.file_id, reg] + list(c100_ids),
                ).fetchall()
                for r in rows:
                    d = dict(r) if hasattr(r, "keys") else {"id": r[0], "line_number": r[1], "parent_id": r[2], "fields_json": r[3]}
                    parent = d.get("parent_id", 0)
                    if reg == "C170":
                        c170_result[parent].append(_build_c170(d))
                    else:
                        c190_result[parent].append(self._parse_c190_row(d))
        else:
            # Fallback: agrupar por ordem de linhas (C170/C190 seguem o C100 anterior)
            rows = self.db.execute(
                "SELECT id, line_number, register, fields_json FROM sped_records "
                "WHERE file_id = ? AND register IN ('C100','C170','C190') "
                "ORDER BY line_number",
                (self.file_id,),
            ).fetchall()

            current_c100_id = None
            c100_lines_sorted = sorted(c100_by_line.keys())

            for r in rows:
                d = dict(r) if hasattr(r, "keys") else {"id": r[0], "line_number": r[1], "register": r[2], "fields_json": r[3]}
                reg = d.get("register", "")
                line = d.get("line_number", 0)

                if reg == "C100":
                    current_c100_id = d.get("id", 0)
                elif reg == "C170" and current_c100_id is not None:
                    c170_result[current_c100_id].append(_build_c170(d))
                elif reg == "C190" and current_c100_id is not None:
                    c190_result[current_c100_id].append(self._parse_c190_row(d))

        return dict(c170_result), dict(c190_result)

    @staticmethod
    def _parse_c190_row(d: dict) -> dict:
        fields = _fields_dict(d.get("fields_json", ""))
        return {
            "record_id": d.get("id", 0),
            "line_number": d.get("line_number", 0),
            "CST_ICMS": fields.get("CST_ICMS", ""),
            "CFOP": fields.get("CFOP", "")[:4],
            "ALIQ_ICMS": _to_float(fields.get("ALIQ_ICMS")),
            "VL_OPR": _to_float(fields.get("VL_OPR")),
            "VL_BC_ICMS": _to_float(fields.get("VL_BC_ICMS")),
            "VL_ICMS": _to_float(fields.get("VL_ICMS")),
            "VL_BC_ICMS_ST": _to_float(fields.get("VL_BC_ICMS_ST")),
            "VL_ICMS_ST": _to_float(fields.get("VL_ICMS_ST")),
        }

    def _load_c113_chaves(self) -> set[str]:
        """Carrega chaves de NF-e referenciadas em C113."""
        rows = self.db.execute(
            "SELECT fields_json FROM sped_records "
            "WHERE file_id = ? AND register = 'C113'",
            (self.file_id,),
        ).fetchall()
        chaves = set()
        for r in rows:
            fj = r[0] if not hasattr(r, "keys") else r["fields_json"]
            f = _fields_dict(fj)
            chv = _norm(f.get("CHV_DOCe", "") or f.get("CHV_DOCE", ""))
            if chv:
                chaves.add(chv)
        return chaves

    def _load_xml_items(self, xml_by_chave: dict) -> dict[int, list[XmlItemParsed]]:
        """Carrega itens XML agrupados por nfe_id."""
        nfe_ids = [v.get("id") for v in xml_by_chave.values() if v.get("id")]
        if not nfe_ids:
            return {}

        placeholders = ",".join("?" * len(nfe_ids))
        cur = self.db.execute(
            f"SELECT * FROM nfe_itens WHERE nfe_id IN ({placeholders}) ORDER BY num_item",
            nfe_ids,
        )
        cols = [desc[0] for desc in cur.description] if cur.description else []
        rows = cur.fetchall()

        result: dict[int, list[XmlItemParsed]] = defaultdict(list)
        for r in rows:
            d = dict(r) if hasattr(r, "keys") else dict(zip(cols, r)) if cols else {}
            nfe_id = d.get("nfe_id", 0)
            result[nfe_id].append(_build_xml_item(d))

        return dict(result)
