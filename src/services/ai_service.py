"""Serviço de IA para explicação de erros fiscais (cache incremental).

IA nunca cria regras fiscais. Apenas gera explicações e sugestões para
erros já detectados pelo motor determinístico.

Arquitetura:
  1. Busca no cache (ai_error_cache) por chave_hash
  2. Se encontrar → retorna texto cacheado, incrementa hits
  3. Se não encontrar → chama OpenAI → salva no cache → retorna
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)

PROMPT_VERSION = 1
MODEL_DEFAULT = "gpt-4o-mini"


# ──────────────────────────────────────────────
# Chave do cache
# ──────────────────────────────────────────────

def _build_cache_key(
    rule_id: str,
    error_type: str,
    regime: str,
    uf: str,
    beneficio_codigo: str = "",
    ind_oper: str = "",
    campo_principal: str = "",
) -> str:
    """Gera hash SHA256 da chave ampliada."""
    raw = f"{rule_id}|{error_type}|{regime}|{uf}|{beneficio_codigo}|{ind_oper}|{campo_principal}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ──────────────────────────────────────────────
# Cache lookup
# ──────────────────────────────────────────────

def get_cached_explanation(
    db: sqlite3.Connection,
    error_type: str,
    regime: str = "",
    uf: str = "",
    beneficio_codigo: str = "",
    ind_oper: str = "",
    campo_principal: str = "",
    rule_id: str = "",
) -> dict | None:
    """Busca explicação no cache. Retorna dict ou None se não encontrar."""
    chave_hash = _build_cache_key(
        rule_id or error_type, error_type, regime, uf,
        beneficio_codigo, ind_oper, campo_principal,
    )

    row = db.execute(
        "SELECT id, explicacao_texto, sugestao_texto, prompt_version, rule_version, hits "
        "FROM ai_error_cache WHERE chave_hash = ?",
        (chave_hash,),
    ).fetchone()

    if not row:
        return None

    # Verificar versão do prompt
    if row[3] != PROMPT_VERSION:
        return None  # Cache desatualizado — regenerar

    # Incrementar hits
    db.execute("UPDATE ai_error_cache SET hits = hits + 1 WHERE id = ?", (row[0],))
    db.commit()

    return {
        "explicacao": row[1],
        "sugestao": row[2],
        "cached": True,
        "hits": row[5] + 1,
    }


# ──────────────────────────────────────────────
# Geração via OpenAI
# ──────────────────────────────────────────────

def generate_explanation(
    db: sqlite3.Connection,
    error_type: str,
    message: str,
    regime: str = "",
    uf: str = "",
    beneficio_codigo: str = "",
    ind_oper: str = "",
    campo_principal: str = "",
    rule_id: str = "",
    value: str = "",
    expected_value: str = "",
    register: str = "",
    severity: str = "",
) -> dict:
    """Gera explicação via IA e salva no cache.

    Tenta buscar do cache primeiro. Se não encontrar, chama OpenAI.
    """
    # 1. Tentar cache
    cached = get_cached_explanation(
        db, error_type, regime, uf, beneficio_codigo, ind_oper, campo_principal, rule_id,
    )
    if cached:
        return cached

    # 2. Chamar OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            "explicacao": message,  # fallback para mensagem técnica
            "sugestao": "",
            "cached": False,
            "error": "OPENAI_API_KEY nao configurada",
        }

    try:
        import openai
        client = openai.OpenAI(api_key=api_key)

        prompt = _build_prompt(
            error_type, message, regime, uf, beneficio_codigo,
            value, expected_value, register, severity,
        )

        response = client.chat.completions.create(
            model=MODEL_DEFAULT,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=500,
        )

        content = response.choices[0].message.content or ""

        # Separar explicação e sugestão
        explicacao, sugestao = _parse_response(content)

    except Exception as e:
        logger.warning("Erro ao chamar OpenAI: %s", e)
        return {
            "explicacao": message,
            "sugestao": "",
            "cached": False,
            "error": str(e),
        }

    # 3. Salvar no cache
    chave_hash = _build_cache_key(
        rule_id or error_type, error_type, regime, uf,
        beneficio_codigo, ind_oper, campo_principal,
    )

    try:
        db.execute(
            """INSERT OR REPLACE INTO ai_error_cache
               (chave_hash, rule_id, error_type, regime, uf, beneficio_codigo,
                ind_oper, campo_principal, explicacao_texto, sugestao_texto,
                modelo_usado, prompt_version, rule_version, gerado_em, hits)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                chave_hash, rule_id, error_type, regime, uf, beneficio_codigo,
                ind_oper, campo_principal, explicacao, sugestao,
                MODEL_DEFAULT, PROMPT_VERSION, 1, datetime.now().isoformat(),
            ),
        )
        db.commit()
    except Exception:
        logger.warning("Erro ao salvar cache de IA", exc_info=True)

    return {
        "explicacao": explicacao,
        "sugestao": sugestao,
        "cached": False,
        "hits": 0,
    }


# ──────────────────────────────────────────────
# Prompts
# ──────────────────────────────────────────────

_SYSTEM_PROMPT = """Você é um assistente fiscal especializado em SPED EFD ICMS/IPI.
Sua função é explicar erros de validação para contadores e auditores de forma clara e objetiva.

Regras:
- Use português brasileiro, linguagem acessível ao contador (não ao programador)
- Cite base legal quando relevante (LC 87/1996, Guia Prático EFD, RICMS)
- Seja direto: máximo 3 parágrafos
- Primeiro parágrafo: O QUE está errado
- Segundo parágrafo: POR QUE provavelmente aconteceu
- Terceiro parágrafo (opcional): COMO corrigir
- Se mencionar sugestão de correção, comece com "SUGESTÃO:"
- Nunca afirme que algo está definitivamente errado sem contexto — use "possivelmente", "provável"
- Você é sugestão não vinculante, não parecer definitivo"""


def _build_prompt(
    error_type: str, message: str, regime: str, uf: str,
    beneficio: str, value: str, expected: str, register: str, severity: str,
) -> str:
    parts = [f"Erro: {error_type}", f"Mensagem técnica: {message}"]
    if regime:
        parts.append(f"Regime tributário: {regime}")
    if uf:
        parts.append(f"UF do contribuinte: {uf}")
    if beneficio:
        parts.append(f"Benefício fiscal ativo: {beneficio}")
    if register:
        parts.append(f"Registro SPED: {register}")
    if severity:
        parts.append(f"Severidade: {severity}")
    if value:
        parts.append(f"Valor encontrado: {value}")
    if expected:
        parts.append(f"Valor esperado: {expected}")
    parts.append("\nExplique este erro para o contador e sugira como corrigir.")
    return "\n".join(parts)


def _parse_response(content: str) -> tuple[str, str]:
    """Separa explicação e sugestão da resposta da IA."""
    if "SUGESTÃO:" in content.upper():
        idx = content.upper().index("SUGESTÃO:")
        explicacao = content[:idx].strip()
        sugestao = content[idx:].strip()
        # Remover o prefixo "SUGESTÃO:" da sugestão
        sugestao = sugestao.split(":", 1)[-1].strip() if ":" in sugestao else sugestao
    else:
        explicacao = content.strip()
        sugestao = ""
    return explicacao, sugestao


# ──────────────────────────────────────────────
# Estatísticas do cache
# ──────────────────────────────────────────────

def get_cache_stats(db: sqlite3.Connection) -> dict:
    """Retorna estatísticas do cache de IA."""
    total = db.execute("SELECT COUNT(*) FROM ai_error_cache").fetchone()[0]
    total_hits = db.execute("SELECT COALESCE(SUM(hits), 0) FROM ai_error_cache").fetchone()[0]
    top = db.execute(
        "SELECT error_type, hits FROM ai_error_cache ORDER BY hits DESC LIMIT 5"
    ).fetchall()
    return {
        "total_entries": total,
        "total_hits": total_hits,
        "prompt_version": PROMPT_VERSION,
        "model": MODEL_DEFAULT,
        "top_5": [{"error_type": r[0], "hits": r[1]} for r in top],
    }
