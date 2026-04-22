"""Servico de revisao de erros por IA — tribunal de validacao.

Monta dossie com dados reais do SPED e XML, envia para OpenAI com
prompt de auditor fiscal, e retorna veredito sobre o grupo de erros.

Fluxo:
  1. Coleta amostras de erros do grupo (ate 5)
  2. Para cada amostra, busca dados reais: C100, C170, C190, E210, XML
  3. Monta dossie estruturado com todos os dados
  4. Envia para OpenAI (GPT-4o) como auditor fiscal
  5. Se inconclusivo, refina com dados adicionais (2a rodada)
  6. Retorna veredito: valido | falso_positivo | inconclusivo
  7. Cacheia resultado por (file_id, error_type)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime

from .db_types import AuditConnection

logger = logging.getLogger(__name__)

MODEL_OPENAI = "gpt-4o"
MODEL_CLAUDE = "claude-sonnet-4-20250514"


_SYSTEM_PROMPT = """Voce e um auditor fiscal senior especializado em SPED EFD ICMS/IPI.

Sua funcao e ANALISAR se um apontamento de erro de validacao e CORRETO ou se e um FALSO POSITIVO,
com base nos dados reais do SPED e dos XMLs de NF-e.

PROCESSO DE ANALISE:
1. Leia o erro apontado pelo sistema
2. Leia os dados reais do SPED (registros C100, C170, C190, E210, etc.)
3. Leia os dados reais do XML da NF-e (quando disponivel)
4. Compare os dados e avalie se o apontamento faz sentido fiscalmente
5. Considere o contexto: regime tributario, UF, tipo de operacao, CFOP, CST

REGRAS DE ANALISE:
- COD_SIT=02/03 (cancelada): campos monetarios DEVEM ser vazios — isso e CORRETO
- COD_SIT=06 (NF complementar): valores podem divergir legitimamente
- COD_SIT=08 (regime especial): regras proprias
- Entradas com ST (CFOP 2403): VL_ICMS pode ser zero no C100 se o destinatario nao tem direito a credito
- C190.VL_OPR inclui frete, seguro, IPI e ICMS-ST — pode ser maior que soma dos C170.VL_ITEM
- E210.VL_RETENCAO_ST vem dos documentos, outros campos podem vir de ajustes E220

FORMATO DE RESPOSTA OBRIGATORIO:
VEREDITO: [VALIDO|FALSO_POSITIVO|INCONCLUSIVO]

JUSTIFICATIVA:
[Explicacao em 2-4 frases com base nos dados analisados]

DADOS QUE SUSTENTAM:
[Cite valores especificos dos registros que sustentam sua conclusao]

RECOMENDACAO:
[Se VALIDO: o que o contribuinte deve corrigir. Se FALSO_POSITIVO: por que o sistema errou e o que ajustar na regra.]"""


def review_error_group(
    db: AuditConnection,
    file_id: int,
    error_type: str,
) -> dict:
    """Revisa grupo de erros com triangulacao: Claude x GPT x Base Legal.

    Fluxo:
    1. Monta dossie com dados reais do SPED e XML
    2. Envia para Claude e GPT-4o em paralelo (quando ambas chaves disponiveis)
    3. Busca base legal na documentacao indexada (embeddings)
    4. Triangula: compara vereditos e cruza com base legal
    5. Gera veredito final com nivel de confianca

    Returns:
        dict com: veredito, confianca, justificativa, analise_claude, analise_gpt,
                  base_legal_relevante, amostras_analisadas, cached
    """
    # 1. Verificar cache
    cached = _get_cached_review(db, file_id, error_type)
    if cached:
        return cached

    # 2. Buscar amostras de erros
    amostras = _buscar_amostras(db, file_id, error_type, max_amostras=5)
    if not amostras:
        return {"veredito": "inconclusivo", "confianca": "baixa",
                "justificativa": "Nenhum erro encontrado para este grupo.", "cached": False}

    # 3. Buscar contexto do arquivo
    contexto = _buscar_contexto_arquivo(db, file_id)

    # 4. Montar dossie com dados reais
    dossie = _montar_dossie(db, file_id, error_type, amostras, contexto)

    # 5. Chamar Claude e GPT em paralelo
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    resultado_claude = None
    resultado_gpt = None

    if anthropic_key and openai_key:
        # Ambas chaves disponíveis — triangulacao completa
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def call_claude():
            return _chamar_claude(anthropic_key, dossie)

        def call_gpt():
            return _chamar_gpt(openai_key, dossie)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(call_claude): "claude",
                executor.submit(call_gpt): "gpt",
            }
            for future in as_completed(futures, timeout=60):
                provider = futures[future]
                try:
                    result = future.result()
                    if provider == "claude":
                        resultado_claude = result
                    else:
                        resultado_gpt = result
                except Exception as e:
                    logger.warning("Falha ao chamar %s: %s", provider, e)

    elif anthropic_key:
        resultado_claude = _chamar_claude(anthropic_key, dossie)
    elif openai_key:
        resultado_gpt = _chamar_gpt(openai_key, dossie)
    else:
        return {"veredito": "inconclusivo", "confianca": "baixa",
                "justificativa": "Nenhuma chave de IA configurada.", "cached": False}

    # 6. Buscar base legal para triangulacao
    register = amostras[0].get("register", "") if amostras else ""
    field_name = amostras[0].get("field_name", "") if amostras else ""
    base_legal = _buscar_base_legal(error_type, register, field_name)

    # 7. Triangular vereditos
    resultado = _triangular(resultado_claude, resultado_gpt, base_legal, error_type)
    resultado["amostras_analisadas"] = len(amostras)
    resultado["cached"] = False

    # 8. Cachear
    _salvar_cache(db, file_id, error_type, resultado)

    return resultado


def _triangular(
    claude: dict | None,
    gpt: dict | None,
    base_legal: str,
    error_type: str,
) -> dict:
    """Triangula vereditos de Claude, GPT e base legal.

    Regras de consenso:
    - Ambos concordam → confianca alta
    - Um concorda com base legal → confianca media (prevalece)
    - Discordam sem base legal → confianca baixa (inconclusivo)
    - Apenas um disponivel → confianca media
    """
    v_claude = (claude or {}).get("veredito", "")
    v_gpt = (gpt or {}).get("veredito", "")
    j_claude = (claude or {}).get("justificativa", "")
    j_gpt = (gpt or {}).get("justificativa", "")
    r_claude = (claude or {}).get("recomendacao", "")
    r_gpt = (gpt or {}).get("recomendacao", "")
    d_claude = (claude or {}).get("dados_sustentacao", "")
    d_gpt = (gpt or {}).get("dados_sustentacao", "")

    # Montar analises individuais para exibicao
    analise_claude = f"**Veredito:** {v_claude}\n{j_claude}" if v_claude else ""
    analise_gpt = f"**Veredito:** {v_gpt}\n{j_gpt}" if v_gpt else ""

    # Caso 1: Ambos disponíveis e concordam
    if v_claude and v_gpt and v_claude == v_gpt:
        return {
            "veredito": v_claude,
            "confianca": "alta",
            "justificativa": f"Claude e GPT-4o concordam: {j_claude or j_gpt}",
            "dados_sustentacao": d_claude or d_gpt,
            "recomendacao": r_claude or r_gpt,
            "analise_claude": analise_claude,
            "analise_gpt": analise_gpt,
            "base_legal_relevante": base_legal,
            "consenso": "unanime",
        }

    # Caso 2: Discordam
    if v_claude and v_gpt and v_claude != v_gpt:
        # Base legal como desempate
        veredito_final = "inconclusivo"
        confianca = "baixa"
        justificativa = (
            f"Divergencia entre modelos. "
            f"Claude: {v_claude}. GPT-4o: {v_gpt}. "
        )

        # Se um diz valido e outro falso_positivo, a base legal pode ajudar
        if base_legal:
            justificativa += "Base legal consultada para desempate."
            # O modelo que concorda com a legislacao prevalece
            # Heuristica: se base legal menciona obrigatoriedade do campo, erro e valido
            bl_lower = base_legal.lower()
            if any(kw in bl_lower for kw in ["obrigatorio", "deve corresponder", "vedado", "nao permitido"]):
                veredito_final = "valido"
                confianca = "media"
                justificativa += " A legislacao sustenta que o apontamento e pertinente."
            elif any(kw in bl_lower for kw in ["facultativo", "pode ser omitido", "nao obrigatorio"]):
                veredito_final = "falso_positivo"
                confianca = "media"
                justificativa += " A legislacao indica que o campo nao e obrigatorio neste contexto."
            else:
                justificativa += " Base legal nao foi conclusiva para desempate."
        else:
            justificativa += "Sem base legal para desempate — requer analise manual."

        return {
            "veredito": veredito_final,
            "confianca": confianca,
            "justificativa": justificativa,
            "dados_sustentacao": f"Claude: {d_claude}\nGPT: {d_gpt}",
            "recomendacao": r_claude or r_gpt,
            "analise_claude": analise_claude,
            "analise_gpt": analise_gpt,
            "base_legal_relevante": base_legal,
            "consenso": "divergente",
        }

    # Caso 3: Apenas um disponivel
    resultado = claude or gpt or {}
    veredito = resultado.get("veredito", "inconclusivo")
    modelo = "Claude" if claude else "GPT-4o"

    return {
        "veredito": veredito,
        "confianca": "media" if veredito != "inconclusivo" else "baixa",
        "justificativa": f"Analise por {modelo}: {resultado.get('justificativa', '')}",
        "dados_sustentacao": resultado.get("dados_sustentacao", ""),
        "recomendacao": resultado.get("recomendacao", ""),
        "analise_claude": analise_claude if claude else "",
        "analise_gpt": analise_gpt if gpt else "",
        "base_legal_relevante": base_legal,
        "consenso": "unico_modelo",
    }


def _buscar_amostras(db: AuditConnection, file_id: int, error_type: str, max_amostras: int = 5) -> list[dict]:
    """Busca ate N amostras de erros do grupo."""
    rows = db.execute(
        """SELECT id, line_number, register, field_name, value, expected_value, message, severity
           FROM validation_errors
           WHERE file_id = ? AND error_type = ? AND status = 'open'
           ORDER BY line_number
           LIMIT ?""",
        (file_id, error_type, max_amostras),
    ).fetchall()

    return [
        {
            "id": r[0], "line_number": r[1], "register": r[2], "field_name": r[3],
            "value": r[4], "expected_value": r[5], "message": r[6], "severity": r[7],
        }
        for r in rows
    ]


def _buscar_contexto_arquivo(db: AuditConnection, file_id: int) -> dict:
    """Busca informacoes do arquivo SPED."""
    row = db.execute(
        """SELECT filename, cnpj, company_name, uf, period_start, period_end,
                  regime_tributario, total_records, total_errors
           FROM sped_files WHERE id = ?""",
        (file_id,),
    ).fetchone()
    if not row:
        return {}
    return {
        "cnpj": row[1] or "", "empresa": row[2] or "", "uf": row[3] or "",
        "periodo_ini": row[4] or "", "periodo_fim": row[5] or "",
        "regime": row[6] or "", "total_registros": row[7] or 0,
    }


def _buscar_dados_sped(db: AuditConnection, file_id: int, line_number: int) -> dict:
    """Busca o registro SPED na linha indicada e seus vizinhos."""
    dados = {}

    # Registro do erro
    row = db.execute(
        "SELECT register, fields_json, raw_line FROM sped_records WHERE file_id = ? AND line_number = ?",
        (file_id, line_number),
    ).fetchone()
    if row:
        fields = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {})
        dados["registro"] = {"register": row[0], "line": line_number, "fields": fields}

    # Se for C190/C170, buscar C100 pai
    if row and row[0] in ("C170", "C190"):
        c100 = db.execute(
            """SELECT line_number, fields_json FROM sped_records
               WHERE file_id = ? AND register = 'C100' AND line_number < ?
               ORDER BY line_number DESC LIMIT 1""",
            (file_id, line_number),
        ).fetchone()
        if c100:
            f = json.loads(c100[1]) if isinstance(c100[1], str) else (c100[1] or {})
            dados["c100_pai"] = {"line": c100[0], "fields": f}

    # Se for C100, buscar filhos C170/C190
    if row and row[0] == "C100":
        next_c100 = db.execute(
            "SELECT MIN(line_number) FROM sped_records WHERE file_id = ? AND register = 'C100' AND line_number > ?",
            (file_id, line_number),
        ).fetchone()
        max_line = next_c100[0] if next_c100 and next_c100[0] else line_number + 500

        c170s = db.execute(
            """SELECT line_number, fields_json FROM sped_records
               WHERE file_id = ? AND register = 'C170' AND line_number > ? AND line_number < ?
               ORDER BY line_number LIMIT 10""",
            (file_id, line_number, max_line),
        ).fetchall()
        if c170s:
            dados["c170_filhos"] = [
                {"line": r[0], "fields": json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})}
                for r in c170s
            ]

        c190s = db.execute(
            """SELECT line_number, fields_json FROM sped_records
               WHERE file_id = ? AND register = 'C190' AND line_number > ? AND line_number < ?
               ORDER BY line_number LIMIT 10""",
            (file_id, line_number, max_line),
        ).fetchall()
        if c190s:
            dados["c190_filhos"] = [
                {"line": r[0], "fields": json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})}
                for r in c190s
            ]

    # Se for E210, buscar E200 pai
    if row and row[0] == "E210":
        e200 = db.execute(
            """SELECT line_number, fields_json FROM sped_records
               WHERE file_id = ? AND register = 'E200' AND line_number < ?
               ORDER BY line_number DESC LIMIT 1""",
            (file_id, line_number),
        ).fetchone()
        if e200:
            f = json.loads(e200[1]) if isinstance(e200[1], str) else (e200[1] or {})
            dados["e200_pai"] = {"line": e200[0], "fields": f}

    return dados


def _buscar_dados_xml(db: AuditConnection, file_id: int, chave_nfe: str) -> dict | None:
    """Busca dados do XML pela chave NF-e."""
    if not chave_nfe or len(chave_nfe) < 44:
        return None

    row = db.execute(
        """SELECT numero_nfe, vl_doc, vl_icms, vl_icms_st, vl_ipi,
                  prot_cstat, status, cnpj_emitente, uf_emitente, crt_emitente
           FROM nfe_xmls WHERE file_id = ? AND chave_nfe = ?""",
        (file_id, chave_nfe),
    ).fetchone()
    if not row:
        return None

    return {
        "numero_nfe": row[0], "vl_doc": float(row[1] or 0), "vl_icms": float(row[2] or 0),
        "vl_icms_st": float(row[3] or 0), "vl_ipi": float(row[4] or 0),
        "cStat": str(row[5] or ""), "status": row[6], "cnpj_emit": row[7],
        "uf_emit": row[8], "crt_emit": str(row[9] or ""),
    }


def _extrair_chave(dados_sped: dict) -> str:
    """Extrai CHV_NFE dos dados SPED."""
    for key in ("registro", "c100_pai"):
        reg = dados_sped.get(key, {})
        fields = reg.get("fields", {})
        chave = fields.get("CHV_NFE", "")
        if chave and len(chave) >= 44:
            return chave
    return ""


def _buscar_base_legal(error_type: str, register: str, field_name: str) -> str:
    """Busca base legal relevante na documentacao indexada."""
    try:
        from pathlib import Path
        doc_db = Path("db/sped.db")
        if not doc_db.exists():
            return ""

        from ..searcher import search_for_error
        results = search_for_error(
            register=register,
            field_name=field_name,
            field_no=0,
            error_message=error_type.replace("_", " "),
            db_path=str(doc_db),
            top_k=3,
        )
        if not results:
            return ""

        parts = ["BASE LEGAL (documentacao indexada):"]
        for r in results[:3]:
            fonte = r.chunk.source_file or ""
            if "/" in fonte:
                fonte = fonte.rsplit("/", 1)[-1]
            heading = r.chunk.heading or ""
            content = (r.chunk.content or "")[:300]
            parts.append(f"  [{fonte}] {heading}")
            parts.append(f"  {content}")
            parts.append("")
        return "\n".join(parts)
    except Exception:
        return ""


def _montar_dossie(
    db: AuditConnection,
    file_id: int,
    error_type: str,
    amostras: list[dict],
    contexto: dict,
) -> str:
    """Monta dossie textual com dados reais para a IA analisar."""
    parts = [
        f"TIPO DE ERRO: {error_type}",
        f"TOTAL DE OCORRENCIAS: {len(amostras)} amostras (pode haver mais)",
        f"\nCONTEXTO DO CONTRIBUINTE:",
        f"  Empresa: {contexto.get('empresa', '?')}",
        f"  CNPJ: {contexto.get('cnpj', '?')}",
        f"  UF: {contexto.get('uf', '?')}",
        f"  Regime: {contexto.get('regime', '?')}",
        f"  Periodo: {contexto.get('periodo_ini', '?')} a {contexto.get('periodo_fim', '?')}",
        "",
    ]

    # Base legal do banco de conhecimento
    register = amostras[0].get("register", "") if amostras else ""
    field_name = amostras[0].get("field_name", "") if amostras else ""
    base_legal = _buscar_base_legal(error_type, register, field_name)
    if base_legal:
        parts.append(base_legal)
        parts.append("")

    # Base legal ja gravada nos erros (se existir)
    if amostras:
        row = db.execute(
            "SELECT legal_basis FROM validation_errors WHERE id = ?",
            (amostras[0]["id"],),
        ).fetchone()
        if row and row[0]:
            try:
                lb = json.loads(row[0])
                parts.append(f"REFERENCIA LEGAL (do validador):")
                parts.append(f"  Fonte: {lb.get('fonte', '')}")
                parts.append(f"  Artigo: {lb.get('artigo', '')}")
                parts.append(f"  Trecho: {lb.get('trecho', '')[:300]}")
                parts.append("")
            except (json.JSONDecodeError, TypeError):
                pass

    for i, amostra in enumerate(amostras, 1):
        parts.append(f"{'='*60}")
        parts.append(f"AMOSTRA {i}/{len(amostras)}")
        parts.append(f"  Linha: {amostra['line_number']}")
        parts.append(f"  Registro: {amostra['register']}")
        parts.append(f"  Campo: {amostra['field_name'] or '(geral)'}")
        parts.append(f"  Valor SPED: {amostra['value'] or '(vazio)'}")
        parts.append(f"  Valor esperado: {amostra['expected_value'] or '(nenhum)'}")
        parts.append(f"  Mensagem: {amostra['message']}")
        parts.append(f"  Severidade: {amostra['severity']}")

        # Dados reais do SPED
        dados_sped = _buscar_dados_sped(db, file_id, amostra["line_number"])
        if dados_sped.get("registro"):
            reg = dados_sped["registro"]
            parts.append(f"\n  DADOS SPED (linha {reg['line']}, {reg['register']}):")
            for k, v in reg["fields"].items():
                if v:  # so mostrar campos preenchidos
                    parts.append(f"    {k} = {v}")

        if dados_sped.get("c100_pai"):
            pai = dados_sped["c100_pai"]
            parts.append(f"\n  C100 PAI (linha {pai['line']}):")
            for k in ["NUM_DOC", "COD_SIT", "IND_OPER", "VL_DOC", "VL_MERC", "VL_ICMS", "VL_ICMS_ST", "VL_IPI", "CHV_NFE"]:
                v = pai["fields"].get(k, "")
                if v:
                    parts.append(f"    {k} = {v}")

        if dados_sped.get("c170_filhos"):
            parts.append(f"\n  C170 ITENS ({len(dados_sped['c170_filhos'])}):")
            for c in dados_sped["c170_filhos"][:5]:
                f = c["fields"]
                parts.append(f"    Linha {c['line']}: CST={f.get('CST_ICMS','')} CFOP={f.get('CFOP','')} VL_ITEM={f.get('VL_ITEM','')} ALIQ={f.get('ALIQ_ICMS','')} VL_ICMS={f.get('VL_ICMS','')}")

        if dados_sped.get("c190_filhos"):
            parts.append(f"\n  C190 RESUMOS ({len(dados_sped['c190_filhos'])}):")
            for c in dados_sped["c190_filhos"]:
                f = c["fields"]
                parts.append(f"    Linha {c['line']}: CST={f.get('CST_ICMS','')} CFOP={f.get('CFOP','')} VL_OPR={f.get('VL_OPR','')} VL_ICMS={f.get('VL_ICMS','')} VL_ICMS_ST={f.get('VL_ICMS_ST','')}")

        if dados_sped.get("e200_pai"):
            pai = dados_sped["e200_pai"]
            parts.append(f"\n  E200 PAI (linha {pai['line']}): UF={pai['fields'].get('UF','')} DT_INI={pai['fields'].get('DT_INI','')} DT_FIN={pai['fields'].get('DT_FIN','')}")

        # Dados do XML
        chave = _extrair_chave(dados_sped)
        if chave:
            xml = _buscar_dados_xml(db, file_id, chave)
            if xml:
                parts.append(f"\n  XML NF-e (chave {chave[:20]}...):")
                parts.append(f"    NF: {xml['numero_nfe']} | cStat: {xml['cStat']} | status: {xml['status']}")
                parts.append(f"    VL_DOC={xml['vl_doc']:.2f} VL_ICMS={xml['vl_icms']:.2f} VL_ST={xml['vl_icms_st']:.2f} VL_IPI={xml['vl_ipi']:.2f}")
                parts.append(f"    CNPJ emit: {xml['cnpj_emit']} UF emit: {xml['uf_emit']} CRT: {xml['crt_emit']}")

        parts.append("")

    return "\n".join(parts)


def _expandir_dossie(db: AuditConnection, file_id: int, amostras: list[dict], dossie_original: str) -> str:
    """Adiciona dados complementares ao dossie para 2a rodada."""
    extras = []

    # Buscar E210, E220 se relevante
    e210s = db.execute(
        "SELECT line_number, fields_json FROM sped_records WHERE file_id = ? AND register = 'E210' LIMIT 5",
        (file_id,),
    ).fetchall()
    if e210s:
        extras.append("\nDADOS COMPLEMENTARES — E210 (Apuracao ST):")
        for r in e210s:
            f = json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})
            extras.append(f"  Linha {r[0]}: VL_RETENCAO_ST={f.get('VL_RETENCAO_ST','')} VL_ICMS_RECOL_ST={f.get('VL_ICMS_RECOL_ST','')} VL_SLD_CRED_ANT_ST={f.get('VL_SLD_CRED_ANT_ST','')}")

    e220s = db.execute(
        "SELECT line_number, fields_json FROM sped_records WHERE file_id = ? AND register = 'E220' LIMIT 5",
        (file_id,),
    ).fetchall()
    if e220s:
        extras.append("\nE220 (Ajustes ST):")
        for r in e220s:
            f = json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})
            extras.append(f"  Linha {r[0]}: COD_AJ={f.get('COD_AJ_APUR','')} VL_AJ={f.get('VL_AJ_APUR','')}")

    if not extras:
        return dossie_original

    return dossie_original + "\n" + "\n".join(extras)


def _chamar_claude(api_key: str, dossie: str) -> dict:
    """Envia dossie para Claude e parseia resposta."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=MODEL_CLAUDE,
            max_tokens=1000,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Analise o seguinte dossie:\n\n{dossie}"}],
        )
        content = response.content[0].text if response.content else ""
        result = _parsear_veredito(content)
        result["modelo"] = MODEL_CLAUDE
        return result
    except Exception as e:
        logger.warning("Falha ao chamar Claude: %s", e)
        return {"veredito": "inconclusivo", "justificativa": f"Erro Claude: {e}", "modelo": MODEL_CLAUDE}


def _chamar_gpt(api_key: str, dossie: str) -> dict:
    """Envia dossie para GPT-4o e parseia resposta."""
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=MODEL_OPENAI,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Analise o seguinte dossie:\n\n{dossie}"},
            ],
            temperature=0.1,
            max_tokens=1000,
        )
        content = response.choices[0].message.content or ""
        result = _parsear_veredito(content)
        result["modelo"] = MODEL_OPENAI
        return result
    except Exception as e:
        logger.warning("Falha ao chamar GPT-4o: %s", e)
        return {"veredito": "inconclusivo", "justificativa": f"Erro GPT: {e}", "modelo": MODEL_OPENAI}


def _parsear_veredito(content: str) -> dict:
    """Extrai veredito estruturado da resposta da IA."""
    resultado = {
        "veredito": "inconclusivo",
        "justificativa": "",
        "dados_sustentacao": "",
        "recomendacao": "",
        "resposta_completa": content,
    }

    lines = content.strip().split("\n")
    current_section = ""

    for line in lines:
        line_upper = line.strip().upper()

        if line_upper.startswith("VEREDITO:"):
            valor = line.split(":", 1)[1].strip().upper()
            if "FALSO" in valor or "FALSE" in valor:
                resultado["veredito"] = "falso_positivo"
            elif "VALIDO" in valor or "VALID" in valor:
                resultado["veredito"] = "valido"
            else:
                resultado["veredito"] = "inconclusivo"
            current_section = ""

        elif line_upper.startswith("JUSTIFICATIVA:"):
            current_section = "justificativa"
            texto = line.split(":", 1)[1].strip()
            if texto:
                resultado["justificativa"] = texto

        elif line_upper.startswith("DADOS QUE SUSTENTAM:"):
            current_section = "dados_sustentacao"
            texto = line.split(":", 1)[1].strip()
            if texto:
                resultado["dados_sustentacao"] = texto

        elif "RECOMENDA" in line_upper and ":" in line:
            current_section = "recomendacao"
            texto = line.split(":", 1)[1].strip()
            if texto:
                resultado["recomendacao"] = texto

        elif current_section and line.strip():
            resultado[current_section] += " " + line.strip()

    # Limpar espacos extras
    for key in ("justificativa", "dados_sustentacao", "recomendacao"):
        resultado[key] = resultado[key].strip()

    return resultado


def _ensure_review_table(db: AuditConnection) -> None:
    """Cria/atualiza tabela ai_review_cache."""
    try:
        db.execute("""
            CREATE TABLE IF NOT EXISTS ai_review_cache (
                id SERIAL PRIMARY KEY,
                file_id INTEGER NOT NULL,
                error_type TEXT NOT NULL,
                veredito TEXT NOT NULL,
                confianca TEXT DEFAULT 'media',
                consenso TEXT DEFAULT '',
                justificativa TEXT,
                dados_sustentacao TEXT,
                recomendacao TEXT,
                analise_claude TEXT DEFAULT '',
                analise_gpt TEXT DEFAULT '',
                base_legal_relevante TEXT DEFAULT '',
                resposta_completa TEXT,
                amostras_analisadas INTEGER DEFAULT 0,
                gerado_em TEXT DEFAULT (now()::text),
                UNIQUE(file_id, error_type)
            )
        """)
        db.commit()
    except Exception:
        try:
            db._conn.rollback()  # type: ignore[attr-defined]
        except Exception:
            pass
    # Adicionar colunas novas se tabela ja existia
    for col, default in [
        ("confianca", "'media'"), ("consenso", "''"),
        ("analise_claude", "''"), ("analise_gpt", "''"),
        ("base_legal_relevante", "''"),
    ]:
        try:
            db.execute(f"ALTER TABLE ai_review_cache ADD COLUMN IF NOT EXISTS {col} TEXT DEFAULT {default}")
            db.commit()
        except Exception:
            try:
                db._conn.rollback()  # type: ignore[attr-defined]
            except Exception:
                pass


def _get_cached_review(db: AuditConnection, file_id: int, error_type: str) -> dict | None:
    """Busca revisao cacheada."""
    _ensure_review_table(db)
    try:
        row = db.execute(
            """SELECT veredito, justificativa, dados_sustentacao, recomendacao,
                      resposta_completa, amostras_analisadas, gerado_em,
                      confianca, consenso, analise_claude, analise_gpt, base_legal_relevante
               FROM ai_review_cache
               WHERE file_id = ? AND error_type = ?""",
            (file_id, error_type),
        ).fetchone()
    except Exception:
        try:
            db._conn.rollback()  # type: ignore[attr-defined]
        except Exception:
            pass
        return None

    if not row:
        return None

    return {
        "veredito": row[0],
        "justificativa": row[1],
        "dados_sustentacao": row[2],
        "recomendacao": row[3],
        "resposta_completa": row[4],
        "amostras_analisadas": row[5],
        "gerado_em": row[6],
        "confianca": row[7] or "media",
        "consenso": row[8] or "",
        "analise_claude": row[9] or "",
        "analise_gpt": row[10] or "",
        "base_legal_relevante": row[11] or "",
        "cached": True,
    }


def _salvar_cache(db: AuditConnection, file_id: int, error_type: str, resultado: dict) -> None:
    """Salva revisao no cache com todos os campos de triangulacao."""
    try:
        _ensure_review_table(db)
        db.execute(
            """INSERT INTO ai_review_cache
               (file_id, error_type, veredito, confianca, consenso,
                justificativa, dados_sustentacao, recomendacao,
                analise_claude, analise_gpt, base_legal_relevante,
                resposta_completa, amostras_analisadas, gerado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (file_id, error_type) DO UPDATE SET
                veredito = EXCLUDED.veredito,
                confianca = EXCLUDED.confianca,
                consenso = EXCLUDED.consenso,
                justificativa = EXCLUDED.justificativa,
                dados_sustentacao = EXCLUDED.dados_sustentacao,
                recomendacao = EXCLUDED.recomendacao,
                analise_claude = EXCLUDED.analise_claude,
                analise_gpt = EXCLUDED.analise_gpt,
                base_legal_relevante = EXCLUDED.base_legal_relevante,
                resposta_completa = EXCLUDED.resposta_completa,
                amostras_analisadas = EXCLUDED.amostras_analisadas,
                gerado_em = EXCLUDED.gerado_em""",
            (
                file_id, error_type, resultado["veredito"],
                resultado.get("confianca", "media"),
                resultado.get("consenso", ""),
                resultado.get("justificativa", ""),
                resultado.get("dados_sustentacao", ""),
                resultado.get("recomendacao", ""),
                resultado.get("analise_claude", ""),
                resultado.get("analise_gpt", ""),
                resultado.get("base_legal_relevante", ""),
                resultado.get("resposta_completa", ""),
                resultado.get("amostras_analisadas", 0),
                datetime.now().isoformat(),
            ),
        )
        db.commit()
    except Exception:
        logger.warning("Falha ao salvar cache de revisao IA", exc_info=True)
