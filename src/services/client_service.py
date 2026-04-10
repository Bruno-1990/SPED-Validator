"""Servico de consulta de clientes no banco MySQL (DCTF_WEB).

Consulta a tabela `clientes` pelo CNPJ para trazer regime tributario,
beneficios fiscais e dados cadastrais que enriquecem o ValidationContext.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import config

logger = logging.getLogger(__name__)

# Colunas que trazemos do MySQL (evita SELECT *)
_COLUNAS_CLIENTE = (
    "id",
    "razao_social",
    "fantasia",
    "cnpj_limpo",
    "codigo_sci",
    "uf",
    "municipio",
    "cep",
    "tipo_estabelecimento",
    "situacao_cadastral",
    "porte",
    "natureza_juridica",
    "atividade_principal_code",
    "atividade_principal_text",
    "simples_optante",
    "simples_data_opcao",
    "simples_data_exclusao",
    "simei_optante",
    "simei_data_opcao",
    "simei_data_exclusao",
    "regime_tributario",
    "beneficios_fiscais",
    "tipo_empresa",
    "capital_social",
)

_SELECT_SQL = f"""
    SELECT {', '.join(_COLUNAS_CLIENTE)}
    FROM clientes
    WHERE cnpj_limpo = %s
    LIMIT 1
"""


@dataclass
class ClienteInfo:
    """Dados do cliente vindos do MySQL relevantes para validacao."""

    id: int = 0
    razao_social: str = ""
    fantasia: str = ""
    cnpj: str = ""
    codigo_sci: str = ""
    uf: str = ""
    municipio: str = ""
    cep: str = ""
    tipo_estabelecimento: str = ""
    situacao_cadastral: str = ""
    porte: str = ""
    natureza_juridica: str = ""
    atividade_principal_code: str = ""
    atividade_principal_text: str = ""
    simples_optante: bool = False
    simples_data_opcao: str = ""
    simples_data_exclusao: str = ""
    simei_optante: bool = False
    simei_data_opcao: str = ""
    simei_data_exclusao: str = ""
    regime_tributario: str = ""
    beneficios_fiscais: list[str] = field(default_factory=list)
    tipo_empresa: str = ""
    capital_social: str = ""
    encontrado: bool = False


def _get_mysql_connection():
    """Cria conexao com o MySQL usando as variaveis do config."""
    import mysql.connector

    return mysql.connector.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        charset="utf8mb4",
        connect_timeout=5,
    )


def _parse_beneficios(raw: Any) -> list[str]:
    """Converte o campo beneficios_fiscais (string/JSON) em lista."""
    if not raw:
        return []
    import json
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        raw = raw.strip()
        if raw.startswith("["):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                pass
        # Separado por virgula ou ponto-e-virgula
        sep = ";" if ";" in raw else ","
        return [b.strip() for b in raw.split(sep) if b.strip()]
    return []


def buscar_cliente(cnpj: str) -> ClienteInfo:
    """Consulta a tabela clientes pelo CNPJ (somente digitos).

    Retorna ClienteInfo com encontrado=True se achou, senao retorna
    ClienteInfo vazio com encontrado=False (nunca levanta excecao).
    """
    cnpj_limpo = "".join(c for c in cnpj if c.isdigit())
    if not cnpj_limpo:
        return ClienteInfo()

    try:
        conn = _get_mysql_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(_SELECT_SQL, (cnpj_limpo,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
    except Exception:
        logger.warning("Falha ao consultar MySQL para CNPJ %s", cnpj_limpo, exc_info=True)
        return ClienteInfo()

    if not row:
        logger.info("Cliente nao encontrado no MySQL: CNPJ %s", cnpj_limpo)
        return ClienteInfo()

    return ClienteInfo(
        id=row.get("id", 0),
        razao_social=row.get("razao_social") or "",
        fantasia=row.get("fantasia") or "",
        cnpj=cnpj_limpo,
        codigo_sci=row.get("codigo_sci") or "",
        uf=row.get("uf") or "",
        municipio=row.get("municipio") or "",
        cep=row.get("cep") or "",
        tipo_estabelecimento=row.get("tipo_estabelecimento") or "",
        situacao_cadastral=row.get("situacao_cadastral") or "",
        porte=row.get("porte") or "",
        natureza_juridica=row.get("natureza_juridica") or "",
        atividade_principal_code=row.get("atividade_principal_code") or "",
        atividade_principal_text=row.get("atividade_principal_text") or "",
        simples_optante=bool(row.get("simples_optante")),
        simples_data_opcao=str(row.get("simples_data_opcao") or ""),
        simples_data_exclusao=str(row.get("simples_data_exclusao") or ""),
        simei_optante=bool(row.get("simei_optante")),
        simei_data_opcao=str(row.get("simei_data_opcao") or ""),
        simei_data_exclusao=str(row.get("simei_data_exclusao") or ""),
        regime_tributario=row.get("regime_tributario") or "",
        beneficios_fiscais=_parse_beneficios(row.get("beneficios_fiscais")),
        tipo_empresa=row.get("tipo_empresa") or "",
        capital_social=str(row.get("capital_social") or ""),
        encontrado=True,
    )
