"""ReferenceLoader: carrega tabelas externas de referência (alíquotas, FCP, municípios, NCM).

Utilizado pelo difal_validator e outros módulos que dependem de dados
externos parametrizáveis em data/reference/.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "reference"
_DB_DIR = Path(__file__).parent.parent.parent / "db"
_JSON_BENEFICIOS_DIR = Path(__file__).parent.parent.parent / "data" / "JSON"

_logger = logging.getLogger(__name__)

# Regex para extrair apenas os 4 dígitos numéricos de strings como "1403 — compra para..."
_RE_CFOP_DIGITOS = re.compile(r"^\d{4}")


# ── BeneficioProfile ──

@dataclass
class BeneficioProfile:
    """Perfil enxuto de um benefício fiscal, construído a partir do JSON."""

    codigo: str
    nome: str
    cfops: set[str]
    csts: set[str]
    exige_cbenef: bool
    cbenef_permitidos: list[str]
    apto_producao_cbenef: bool
    apuracao_segregada: bool
    codigos_receita: dict[str, str]
    exige_estorno: bool
    criterio_estorno: str | None
    limite_credito_entrada: str | None
    vedacoes: list[str]
    tipo_beneficio: list[str]
    registros_afetados: list[str]
    campos_criticos: list[str]
    validacoes: list[dict]
    alertas: list[dict]
    raw: dict = field(repr=False)

    @classmethod
    def from_json(cls, data: dict) -> BeneficioProfile:
        """Constroi BeneficioProfile a partir do JSON carregado."""
        impactos = data.get("impactos_fiscais", {})
        regras_doc = data.get("regras_documentais", {})
        regras_sped = data.get("regras_sped", {})
        regras_estorno = data.get("regras_estorno", {})
        elegibilidade = data.get("elegibilidade", {})

        # Normalizar CFOPs — extrair apenas os 4 dígitos iniciais
        cfops_raw = regras_doc.get("cfops_comuns", [])
        cfops: set[str] = set()
        for c in cfops_raw:
            m = _RE_CFOP_DIGITOS.match(str(c).strip())
            if m:
                cfops.add(m.group())

        # CSTs aceitos
        csts = set(str(c).strip() for c in regras_doc.get("csts_aceitos", []))

        # cBenef
        cbenef_permitidos = impactos.get("cbenef_permitidos", []) or []
        cbenef_status = impactos.get("cbenef_status", "")
        apto_producao = bool(
            cbenef_permitidos
            and cbenef_status != "pendente_parametrizacao"
            and cbenef_status != "nao_aplicavel"
        )

        # Códigos de receita — montar dict contextual
        codigos_receita: dict[str, str] = {}
        # Fonte 1: campo direto (ex: codigo_receita_apuracao)
        if impactos.get("codigo_receita_apuracao"):
            codigos_receita["apuracao"] = str(impactos["codigo_receita_apuracao"])
        # Fonte 2: sub-dict codigos_recolhimento
        for k, v in (impactos.get("codigos_recolhimento") or {}).items():
            if k != "observacao" and k != "referencia" and v:
                # Chave tipo "codigo_industria" -> "industria"
                chave = k.replace("codigo_", "").replace("codigo_ordinario_", "")
                codigos_receita[chave] = str(v)

        return cls(
            codigo=data.get("codigo_beneficio", ""),
            nome=data.get("nome_beneficio", ""),
            cfops=cfops,
            csts=csts,
            exige_cbenef=bool(impactos.get("exige_cbenef", False)),
            cbenef_permitidos=cbenef_permitidos,
            apto_producao_cbenef=apto_producao,
            apuracao_segregada=bool(impactos.get("apuracao_em_separado", False)),
            codigos_receita=codigos_receita,
            exige_estorno=bool(regras_estorno.get("exige_estorno", False)),
            criterio_estorno=regras_estorno.get("criterio"),
            limite_credito_entrada=impactos.get("limite_credito_entrada"),
            vedacoes=elegibilidade.get("vedacoes", []),
            tipo_beneficio=impactos.get("tipo_beneficio", []),
            registros_afetados=regras_sped.get("registros_afetados", []),
            campos_criticos=regras_sped.get("campos_criticos", []),
            validacoes=regras_sped.get("validacoes", []),
            alertas=data.get("alertas_motor", []),
            raw=data,
        )


class ReferenceLoader:
    """Carrega e consulta tabelas YAML de referência."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or _DATA_DIR
        self._aliquotas: dict[str, float] | None = None
        self._fcp: dict[str, float] | None = None
        self._aliq_meta: dict | None = None
        self._fcp_meta: dict | None = None
        self._municipios: set[str] | None = None
        self._ncm_map: dict[str, str] | None = None
        self._matriz_data: dict | None = None
        self._codigos_ajuste: dict[str, list[dict]] | None = None
        self._mva_data: dict[str, list[dict]] | None = None
        self._csosn_data: dict[str, dict] | None = None
        self._cst_pis_cofins_sn: dict[str, dict] | None = None
        self._cst_pis_cofins_proibidos: dict[str, dict] | None = None
        self._sn_anexos: dict | None = None
        self._sn_sublimites: dict[str, float] | None = None
        self._sn_limite_maximo: float | None = None
        self._ncm_vigente: dict[str, dict] | None = None
        self._cst_vigente: dict[str, dict] | None = None  # id -> row completa
        self._cst_por_tipo: dict[str, dict[str, dict]] | None = None  # tipo -> {codigo -> row}
        self._difal_vigente: dict[str, dict] | None = None  # id -> row
        self._difal_por_tipo: dict[str, list[dict]] | None = None  # tipo -> [rows]
        self._beneficios: dict[str, BeneficioProfile] | None = None
        # CST efeitos carregados do JSON (codigo_trib -> set de efeitos)
        self._cst_efeitos: dict[str, set[str]] | None = None

    # ── Carregamento lazy ──

    def _ensure_aliquotas(self) -> None:
        if self._aliquotas is not None:
            return
        path = self._data_dir / "aliquotas_internas_uf.yaml"
        if not path.exists():
            self._aliquotas = {}
            self._aliq_meta = {}
            return
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self._aliq_meta = data.get("meta", {})
        raw = data.get("aliquotas", {})
        self._aliquotas = {uf: float(v) for uf, v in raw.items()}

    def _ensure_fcp(self) -> None:
        if self._fcp is not None:
            return
        path = self._data_dir / "fcp_por_uf.yaml"
        if not path.exists():
            self._fcp = {}
            self._fcp_meta = {}
            return
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self._fcp_meta = data.get("meta", {})
        raw = data.get("fcp", {})
        self._fcp = {uf: float(v) for uf, v in raw.items()}

    def _ensure_municipios(self) -> None:
        if self._municipios is not None:
            return
        path = self._data_dir / "ibge_municipios.yaml"
        if not path.exists():
            self._municipios = set()
            return
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        items = data.get("municipios", [])
        self._municipios = {str(m["codigo"]) for m in items if "codigo" in m}

    def _ensure_ncm(self) -> None:
        if self._ncm_map is not None:
            return
        path = self._data_dir / "ncm_tipi_categorias.yaml"
        if not path.exists():
            self._ncm_map = {}
            return
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        categorias = data.get("categorias", [])
        self._ncm_map = {}
        for item in categorias:
            ncm = str(item.get("ncm", ""))
            tributacao = item.get("tributacao", "normal")
            if ncm:
                self._ncm_map[ncm] = tributacao

    def _ensure_codigos_ajuste(self) -> None:
        if self._codigos_ajuste is not None:
            return
        path = self._data_dir / "codigos_ajuste_uf.yaml"
        if not path.exists():
            self._codigos_ajuste = {}
            return
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self._codigos_ajuste = data.get("ajustes", {})

    def _ensure_mva(self) -> None:
        if self._mva_data is not None:
            return
        path = self._data_dir / "mva_por_ncm_uf.yaml"
        if not path.exists():
            self._mva_data = {}
            return
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        # Flatten: NCM prefix -> mva_pct
        self._mva_data = {}
        for seg_data in (data.get("segmentos") or {}).values():
            for item in seg_data.get("ncms", []):
                ncm = str(item.get("ncm", ""))
                if ncm:
                    self._mva_data[ncm] = item

    def _ensure_cst_pis_cofins_sn(self) -> None:
        if self._cst_pis_cofins_sn is not None:
            return
        path = self._data_dir / "cst_pis_cofins_sn.yaml"
        if not path.exists():
            self._cst_pis_cofins_sn = {}
            return
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self._cst_pis_cofins_sn = data.get("cst_pis_cofins", {})
        self._cst_pis_cofins_proibidos = data.get("cst_proibidos", {})

    def _ensure_sn_anexos(self) -> None:
        if self._sn_anexos is not None:
            return
        path = self._data_dir / "sn_anexos_aliquotas.yaml"
        if not path.exists():
            self._sn_anexos = {}
            return
        with open(path, encoding="utf-8") as f:
            self._sn_anexos = yaml.safe_load(f) or {}

    def _ensure_sn_sublimites(self) -> None:
        if self._sn_sublimites is not None:
            return
        path = self._data_dir / "sn_sublimites_uf.yaml"
        if not path.exists():
            self._sn_sublimites = {}
            self._sn_limite_maximo = 4_800_000.0
            return
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self._sn_limite_maximo = float(data.get("limite_maximo_sn", 4_800_000.0))
        raw = data.get("sublimites", {})
        self._sn_sublimites = {uf: float(v) for uf, v in raw.items()}

    def _ensure_csosn(self) -> None:
        if self._csosn_data is not None:
            return
        path = self._data_dir / "csosn_tabela_b.yaml"
        if not path.exists():
            self._csosn_data = {}
            return
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self._csosn_data = data.get("csosn", {})

    def _ensure_ncm_vigente(self) -> None:
        if self._ncm_vigente is not None:
            return

        db_path = _DB_DIR / "sped.db"
        _DB_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)

        # Criar tabela se nao existir
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ncm_vigente (
                codigo TEXT PRIMARY KEY,
                descricao TEXT,
                data_inicio TEXT,
                data_fim TEXT,
                tipo_ato TEXT,
                numero_ato TEXT,
                ano_ato TEXT
            )
        """)

        # Verificar se ja tem dados
        count = conn.execute("SELECT COUNT(*) FROM ncm_vigente").fetchone()[0]

        if count == 0:
            # Popular a partir do JSON
            json_dir = (
                self._data_dir.parent / "JSON"
                if self._data_dir != _DATA_DIR
                else _JSON_BENEFICIOS_DIR
            )
            # Procurar arquivo NCM (nome pode variar com data)
            ncm_files = sorted(json_dir.glob("Tabela_NCM_Vigente*.json"))
            if ncm_files:
                try:
                    with open(ncm_files[-1], encoding="utf-8") as f:
                        data = json.load(f)
                    noms = data.get("Nomenclaturas", [])
                    if noms:
                        conn.executemany(
                            "INSERT OR IGNORE INTO ncm_vigente "
                            "(codigo, descricao, data_inicio, data_fim, tipo_ato, numero_ato, ano_ato) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            [
                                (
                                    n.get("Codigo", ""),
                                    n.get("Descricao", ""),
                                    n.get("Data_Inicio", ""),
                                    n.get("Data_Fim", ""),
                                    n.get("Tipo_Ato_Ini", ""),
                                    n.get("Numero_Ato_Ini", ""),
                                    n.get("Ano_Ato_Ini", ""),
                                )
                                for n in noms
                                if n.get("Codigo")
                            ],
                        )
                        conn.commit()
                        # Criar indice para busca por prefixo
                        conn.execute(
                            "CREATE INDEX IF NOT EXISTS idx_ncm_codigo ON ncm_vigente(codigo)"
                        )
                        conn.commit()
                        _logger.info(
                            "NCM vigente: %d registros carregados de %s",
                            len(noms), ncm_files[-1].name,
                        )
                except Exception:
                    _logger.warning("Erro ao carregar NCM vigente do JSON", exc_info=True)

        # Carregar em memória (dict codigo -> info)
        try:
            rows = conn.execute(
                "SELECT codigo, descricao, data_inicio, data_fim FROM ncm_vigente"
            ).fetchall()
        except sqlite3.OperationalError:
            self._ncm_vigente = {}
            conn.close()
            return

        self._ncm_vigente = {}
        for codigo, descricao, dt_ini, dt_fim in rows:
            self._ncm_vigente[codigo] = {
                "descricao": descricao,
                "data_inicio": dt_ini,
                "data_fim": dt_fim,
            }
        conn.close()

    def _ensure_cst_vigente(self) -> None:
        if self._cst_vigente is not None:
            return
        db_path = _DB_DIR / "sped.db"
        if not db_path.exists():
            self._cst_vigente = {}
            self._cst_por_tipo = {}
            return
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        try:
            rows = conn.execute(
                "SELECT id, codigo, descricao, tipo, categoria_normativa, "
                "tributo, regime, efeitos, incompativel_com, tags FROM cst_vigente"
            ).fetchall()
        except sqlite3.OperationalError:
            self._cst_vigente = {}
            self._cst_por_tipo = {}
            conn.close()
            return
        self._cst_vigente = {}
        self._cst_por_tipo = {}
        for row_id, codigo, descricao, tipo, cat, tributo, regime, efeitos, incompat, tags in rows:
            entry = {
                "id": row_id,
                "codigo": codigo,
                "descricao": descricao,
                "tipo": tipo,
                "categoria_normativa": cat,
                "tributo": json.loads(tributo) if tributo else [],
                "regime": json.loads(regime) if regime else [],
                "efeitos": json.loads(efeitos) if efeitos else [],
                "incompativel_com": json.loads(incompat) if incompat else [],
                "tags": json.loads(tags) if tags else [],
            }
            self._cst_vigente[row_id] = entry
            self._cst_por_tipo.setdefault(tipo, {})[codigo] = entry
        conn.close()

    def _ensure_difal_vigente(self) -> None:
        if self._difal_vigente is not None:
            return
        db_path = _DB_DIR / "sped.db"
        if not db_path.exists():
            self._difal_vigente = {}
            self._difal_por_tipo = {}
            return
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        try:
            rows = conn.execute(
                "SELECT id, codigo, descricao, tipo, categoria_normativa, "
                "tributo, regime, operacao_tipo, destinatario_tipo, "
                "sujeito_passivo, perfil, formula_calculo, base_calculo, "
                "efeitos, incompativel_com, tags, status_juridico "
                "FROM difal_vigente"
            ).fetchall()
        except sqlite3.OperationalError:
            self._difal_vigente = {}
            self._difal_por_tipo = {}
            conn.close()
            return
        self._difal_vigente = {}
        self._difal_por_tipo = {}
        for (row_id, codigo, descricao, tipo, cat, tributo, regime,
             op_tipo, dest_tipo, suj_passivo, perfil, formula, base_calc,
             efeitos, incompat, tags, status) in rows:
            entry = {
                "id": row_id,
                "codigo": codigo,
                "descricao": descricao,
                "tipo": tipo,
                "categoria_normativa": cat,
                "tributo": json.loads(tributo) if tributo else [],
                "regime": json.loads(regime) if regime else [],
                "operacao_tipo": json.loads(op_tipo) if op_tipo else [],
                "destinatario_tipo": dest_tipo or "",
                "sujeito_passivo": suj_passivo or "",
                "perfil": perfil or "",
                "formula_calculo": formula or "",
                "base_calculo": base_calc or "",
                "efeitos": json.loads(efeitos) if efeitos else [],
                "incompativel_com": json.loads(incompat) if incompat else [],
                "tags": json.loads(tags) if tags else [],
                "status_juridico": status or "vigente",
            }
            self._difal_vigente[row_id] = entry
            self._difal_por_tipo.setdefault(tipo, []).append(entry)
        conn.close()

    def _ensure_matriz(self) -> None:
        if self._matriz_data is not None:
            return
        vigencias_dir = self._data_dir / "vigencias" / "matriz_aliquotas_uf"
        if not vigencias_dir.exists():
            self._matriz_data = {}
            return
        files = sorted(vigencias_dir.glob("*.yaml"), reverse=True)
        if not files:
            self._matriz_data = {}
            return
        # Carrega todos os arquivos de vigência ordenados por data decrescente
        self._matriz_data = {"vigencias": []}
        for fpath in files:
            vigencia_date = fpath.stem  # e.g. '2013-01-01'
            with open(fpath, encoding="utf-8") as f:
                content = yaml.safe_load(f) or {}
            content["_vigencia_de"] = vigencia_date
            self._matriz_data["vigencias"].append(content)

    # ── API pública ──

    def get_aliquota_interna(self, uf: str, dt: date | None = None) -> float | None:
        """Retorna alíquota interna padrão da UF, ou None se indisponível."""
        self._ensure_aliquotas()
        assert self._aliquotas is not None
        return self._aliquotas.get(uf.upper())

    def get_fcp(self, uf: str, dt: date | None = None) -> float:
        """Retorna percentual de FCP da UF (0.0 se não cobrado)."""
        self._ensure_fcp()
        assert self._fcp is not None
        return self._fcp.get(uf.upper(), 0.0)

    def is_municipio_valido(self, cod_mun: str) -> bool:
        """Valida código IBGE de 7 dígitos contra tabela de municípios.

        Retorna True se o código existe na tabela ibge_municipios.yaml.
        Se a tabela não estiver disponível, retorna True (fallback permissivo).
        """
        self._ensure_municipios()
        assert self._municipios is not None
        if not self._municipios:
            return True  # fallback: sem tabela, não rejeita
        return cod_mun.strip() in self._municipios

    def get_ncm_tributacao(self, ncm: str) -> str | None:
        """Retorna tipo de tributação do NCM: 'normal'|'isento'|'monofasico'|'nt' ou None.

        Retorna None se o NCM não estiver catalogado na tabela de referência.
        """
        self._ensure_ncm()
        assert self._ncm_map is not None
        return self._ncm_map.get(ncm.strip())

    @staticmethod
    def _ncm_formatar(ncm_raw: str) -> str:
        """Converte NCM de formato SPED (8 digitos sem pontos) para formato tabela (com pontos).

        SPED: '39011020' → Tabela: '3901.10.20'
        Se ja tiver pontos, retorna como esta.
        """
        ncm = ncm_raw.strip().replace(".", "")
        if len(ncm) == 8:
            return f"{ncm[:4]}.{ncm[4:6]}.{ncm[6:8]}"
        if len(ncm) == 6:
            return f"{ncm[:4]}.{ncm[4:6]}"
        if len(ncm) == 4:
            return f"{ncm[:2]}.{ncm[2:4]}"
        return ncm_raw.strip()

    def ncm_existe(self, ncm: str) -> bool:
        """Retorna True se o NCM existe na tabela oficial vigente.

        Aceita formato SPED (8 digitos: '39011020') ou tabela ('3901.10.20').
        Busca exata primeiro, depois por prefixos decrescentes.
        NCM '00000000' (placeholder) e ignorado.
        """
        self._ensure_ncm_vigente()
        assert self._ncm_vigente is not None
        if not self._ncm_vigente:
            return True  # fallback permissivo se tabela indisponível
        ncm = ncm.strip()
        if ncm == "00000000" or ncm == "0":
            return True  # placeholder, nao validar

        # Normalizar para formato com pontos
        ncm_fmt = self._ncm_formatar(ncm)

        # Busca exata
        if ncm_fmt in self._ncm_vigente:
            return True
        # Busca no formato original (caso tabela use formato diferente)
        if ncm in self._ncm_vigente:
            return True

        # Busca por prefixo hierarquico (a tabela pode ter apenas nivel superior)
        ncm_limpo = ncm.replace(".", "")
        for length in (6, 4, 2):
            prefixo = self._ncm_formatar(ncm_limpo[:length]) if length >= 4 else ncm_limpo[:length]
            if prefixo in self._ncm_vigente:
                return True
        return False

    def _ncm_lookup(self, ncm: str) -> dict | None:
        """Busca info do NCM normalizando formato SPED→tabela."""
        self._ensure_ncm_vigente()
        assert self._ncm_vigente is not None
        # Tentar formato original
        info = self._ncm_vigente.get(ncm.strip())
        if info:
            return info
        # Tentar formato com pontos
        return self._ncm_vigente.get(self._ncm_formatar(ncm))

    def ncm_vigente_no_periodo(self, ncm: str, dt_ini: date, dt_fim: date) -> bool | None:
        """Verifica se o NCM estava vigente no período informado.

        Aceita formato SPED ('39011020') ou tabela ('3901.10.20').
        Retorna True se vigente, False se expirado, None se NCM não encontrado.
        """
        info = self._ncm_lookup(ncm)
        if info is None:
            return None
        # Parsear datas DD/MM/YYYY
        try:
            d_ini = date(int(info["data_inicio"][6:10]), int(info["data_inicio"][3:5]), int(info["data_inicio"][0:2]))
            d_fim = date(int(info["data_fim"][6:10]), int(info["data_fim"][3:5]), int(info["data_fim"][0:2]))
        except (ValueError, IndexError):
            return True  # se não conseguir parsear, assumir vigente
        return d_ini <= dt_fim and d_fim >= dt_ini

    def get_ncm_descricao(self, ncm: str) -> str:
        """Retorna descrição oficial do NCM, ou string vazia se não encontrado.

        Aceita formato SPED ('39011020') ou tabela ('3901.10.20').
        """
        info = self._ncm_lookup(ncm)
        return info["descricao"] if info else ""

    def has_ncm_vigente_table(self) -> bool:
        """Retorna True se a tabela ncm_vigente está disponível e não vazia."""
        self._ensure_ncm_vigente()
        assert self._ncm_vigente is not None
        return len(self._ncm_vigente) > 0

    # ── CST Vigente (sped.db) ──

    def has_cst_vigente_table(self) -> bool:
        """Retorna True se a tabela cst_vigente está disponível e não vazia."""
        self._ensure_cst_vigente()
        assert self._cst_vigente is not None
        return len(self._cst_vigente) > 0

    def get_csts_validos(self, tipo: str) -> set[str]:
        """Retorna conjunto de códigos válidos para um tipo (CST_ICMS, CSOSN, etc.).

        Para CST_ICMS retorna apenas tabela_b_tributacao (códigos de 2 dígitos).
        """
        self._ensure_cst_vigente()
        assert self._cst_por_tipo is not None
        entries = self._cst_por_tipo.get(tipo, {})
        return set(entries.keys())

    def get_cst_info(self, tipo: str, codigo: str) -> dict | None:
        """Retorna info completa de um CST (efeitos, incompatibilidades, etc.)."""
        self._ensure_cst_vigente()
        assert self._cst_por_tipo is not None
        return self._cst_por_tipo.get(tipo, {}).get(codigo)

    def get_cst_efeitos(self, tipo: str, codigo: str) -> list[str]:
        """Retorna lista de efeitos do CST (ex: debito_proprio, monofasico)."""
        info = self.get_cst_info(tipo, codigo)
        return info["efeitos"] if info else []

    def get_cst_incompativeis(self, tipo: str, codigo: str) -> list[str]:
        """Retorna IDs de CSTs incompatíveis com este código."""
        info = self.get_cst_info(tipo, codigo)
        return info["incompativel_com"] if info else []

    def cst_valido_para_regime(self, tipo: str, codigo: str, regime: str) -> bool | None:
        """Verifica se o CST é válido para o regime informado.

        Retorna True/False, ou None se CST não encontrado.
        """
        info = self.get_cst_info(tipo, codigo)
        if info is None:
            return None
        regimes = info.get("regime", [])
        if not regimes:
            return True  # sem restrição de regime
        return regime in regimes

    def cst_tem_efeito(self, tipo: str, codigo: str, efeito: str) -> bool:
        """Retorna True se o CST tem o efeito especificado."""
        return efeito in self.get_cst_efeitos(tipo, codigo)

    def get_cst_descricao(self, tipo: str, codigo: str) -> str:
        """Retorna descrição oficial do CST."""
        info = self.get_cst_info(tipo, codigo)
        return info["descricao"] if info else ""

    # ── DIFAL Vigente (sped.db) ──

    def has_difal_vigente_table(self) -> bool:
        """Retorna True se a tabela difal_vigente está disponível."""
        self._ensure_difal_vigente()
        assert self._difal_vigente is not None
        return len(self._difal_vigente) > 0

    def get_difal_situacao(
        self, regime: str, destinatario_tipo: str, operacao_tipo: str = "",
    ) -> dict | None:
        """Encontra a situação DIFAL aplicável com base no regime, tipo de destinatário e operação.

        Retorna a primeira situação que casa com os critérios, ou None.
        """
        self._ensure_difal_vigente()
        assert self._difal_por_tipo is not None
        for sit in self._difal_por_tipo.get("DIFAL_SITUACAO", []):
            # Filtrar por regime
            if sit["regime"] and regime not in sit["regime"]:
                continue
            # Filtrar por destinatário
            dt = sit["destinatario_tipo"]
            if dt and dt != "ambos" and dt != destinatario_tipo:
                continue
            # Filtrar por operação
            if operacao_tipo and sit["operacao_tipo"] and operacao_tipo not in sit["operacao_tipo"]:
                continue
            return sit
        return None

    def get_difal_formula(self, situacao_id: str) -> dict | None:
        """Retorna a regra de cálculo mais adequada para a situação.

        Analisa efeitos da situação para determinar se usa cálculo por dentro,
        com FCP, com redução, etc.
        """
        self._ensure_difal_vigente()
        assert self._difal_vigente is not None
        assert self._difal_por_tipo is not None
        sit = self._difal_vigente.get(situacao_id)
        if not sit:
            return None
        efeitos = set(sit.get("efeitos", []))
        regras = self._difal_por_tipo.get("DIFAL_REGRA_CALCULO", [])
        # Priorizar regra com FCP se situação tem FCP
        if "fundo_combate_pobreza" in efeitos:
            for r in regras:
                if "fundo_combate_pobreza" in r.get("efeitos", []):
                    return r
        # Por dentro se indicado
        if "base_calculo_por_dentro" in efeitos:
            for r in regras:
                if "base_calculo_por_dentro" in r.get("efeitos", []):
                    return r
        # Padrão: primeira regra (cálculo simples)
        return regras[0] if regras else None

    def get_difal_aliquota_interestadual(self, origem_nacional: bool = True) -> list[dict]:
        """Retorna regras de alíquotas interestaduais aplicáveis."""
        self._ensure_difal_vigente()
        assert self._difal_por_tipo is not None
        return self._difal_por_tipo.get("DIFAL_ALIQUOTA_INTERESTADUAL", [])

    def get_difal_partilha(self, ano: int) -> dict | None:
        """Retorna regra de partilha aplicável ao ano informado."""
        self._ensure_difal_vigente()
        assert self._difal_por_tipo is not None
        for p in self._difal_por_tipo.get("DIFAL_PARTILHA", []):
            # Extrair ano do código (ex: DIFAL_PARTILHA_2019)
            try:
                ano_partilha = int(p["id"].split("_")[-1])
            except (ValueError, IndexError):
                continue
            if ano >= ano_partilha:
                return p  # a mais recente que cobre o ano
        return None

    def get_difal_info(self, difal_id: str) -> dict | None:
        """Retorna info completa de um registro DIFAL pelo ID."""
        self._ensure_difal_vigente()
        assert self._difal_vigente is not None
        return self._difal_vigente.get(difal_id)

    def difal_is_controverso(self, difal_id: str) -> bool:
        """Retorna True se a situação DIFAL é juridicamente controversa."""
        info = self.get_difal_info(difal_id)
        return info.get("status_juridico") == "controverso" if info else False

    def get_matriz_aliquota(self, uf_origem: str, uf_destino: str, dt: date | None = None) -> float | None:
        """Retorna alíquota interestadual entre UFs para a data informada.

        Retorna None se origem == destino (operação interna).
        Usa regra RS 13/2012: Sul/Sudeste -> N/NE/CO/ES = 7%, demais = 12%.
        """
        self._ensure_matriz()
        assert self._matriz_data is not None

        origem = uf_origem.strip().upper()
        destino = uf_destino.strip().upper()

        if origem == destino:
            return None  # operação interna

        vigencias = self._matriz_data.get("vigencias", [])
        if not vigencias:
            return None

        # Seleciona vigência aplicável à data
        selected = vigencias[0]  # mais recente por padrão
        if dt:
            for v in vigencias:
                vig_de = v.get("_vigencia_de", "")
                if vig_de and vig_de <= dt.isoformat():
                    selected = v
                    break

        sul_sudeste = set(selected.get("sul_sudeste", []))
        demais = set(selected.get("demais", []))

        if origem in sul_sudeste and destino in demais:
            return 7.0
        return 12.0

    def get_codigos_ajuste(self, uf: str) -> list[dict]:
        """Retorna lista de códigos de ajuste (tabela 5.1.1) para a UF."""
        self._ensure_codigos_ajuste()
        assert self._codigos_ajuste is not None
        return self._codigos_ajuste.get(uf.upper(), [])

    def get_codigo_ajuste_info(self, codigo: str) -> dict | None:
        """Retorna info de um código de ajuste específico (ex: 'SP020001')."""
        uf = codigo[:2].upper() if len(codigo) >= 2 else ""
        for item in self.get_codigos_ajuste(uf):
            if item.get("codigo") == codigo:
                return item
        return None

    def get_mva(self, ncm: str) -> float | None:
        """Retorna MVA original (%) para o NCM, buscando por prefixo.

        Ex: NCM '40111000' casa com entrada '4011' (pneumáticos, MVA 45.19%).
        Retorna None se não encontrado.
        """
        self._ensure_mva()
        assert self._mva_data is not None
        # Busca por prefixo decrescente: 8 dígitos, 6, 4
        for length in (8, 6, 4):
            prefix = ncm[:length]
            if prefix in self._mva_data:
                return float(self._mva_data[prefix].get("mva_pct", 0))
        return None

    def get_cst_pis_cofins_sn_validos(self) -> set[str]:
        """Retorna conjunto de CSTs PIS/COFINS válidos para Simples Nacional."""
        self._ensure_cst_pis_cofins_sn()
        assert self._cst_pis_cofins_sn is not None
        return set(self._cst_pis_cofins_sn.keys())

    def get_cst_pis_cofins_sn_info(self, cst: str) -> dict | None:
        """Retorna info de um CST PIS/COFINS SN (descrição, exige_ncm_monofasico)."""
        self._ensure_cst_pis_cofins_sn()
        assert self._cst_pis_cofins_sn is not None
        return self._cst_pis_cofins_sn.get(cst)

    def get_cst_pis_cofins_sn_descricao(self, cst: str) -> str:
        """Retorna descrição legível do CST PIS/COFINS para SN."""
        info = self.get_cst_pis_cofins_sn_info(cst)
        if info:
            return info.get("descricao", cst)
        return cst

    def cst_pis_cofins_exige_monofasico(self, cst: str) -> bool:
        """Retorna True se o CST exige que o NCM seja monofásico."""
        info = self.get_cst_pis_cofins_sn_info(cst)
        if info:
            return bool(info.get("exige_ncm_monofasico", False))
        return False

    def get_cst_pis_cofins_sn_proibidos(self) -> dict[str, dict]:
        """Retorna CSTs PIS/COFINS explicitamente proibidos para SN com motivo."""
        self._ensure_cst_pis_cofins_sn()
        assert self._cst_pis_cofins_proibidos is not None
        return self._cst_pis_cofins_proibidos

    def get_sn_sublimite(self, uf: str) -> float:
        """Retorna sublimite de ICMS/ISS da UF para o Simples Nacional."""
        self._ensure_sn_sublimites()
        assert self._sn_sublimites is not None
        assert self._sn_limite_maximo is not None
        return self._sn_sublimites.get(uf.upper(), self._sn_limite_maximo)

    def get_sn_limite_maximo(self) -> float:
        """Retorna limite máximo anual do Simples Nacional."""
        self._ensure_sn_sublimites()
        assert self._sn_limite_maximo is not None
        return self._sn_limite_maximo

    def get_sn_aliquota_efetiva(self, anexo: str, rbt12: float) -> dict | None:
        """Calcula alíquota efetiva do SN para um anexo e receita bruta.

        Retorna dict com faixa, aliquota_nominal, parcela_deduzir,
        aliquota_efetiva, partilha. None se anexo não encontrado.
        """
        self._ensure_sn_anexos()
        assert self._sn_anexos is not None
        key = f"anexo_{anexo}" if not anexo.startswith("anexo_") else anexo
        anexo_data = self._sn_anexos.get(key)
        if not anexo_data:
            return None
        faixas = anexo_data.get("faixas", [])
        selected = None
        for f in faixas:
            limite = f.get("rbt12_ate", 0)
            if rbt12 <= limite:
                selected = f
                break
        if not selected:
            selected = faixas[-1] if faixas else None
        if not selected:
            return None
        nominal = selected["aliquota_nominal"]
        pd = selected["parcela_deduzir"]
        efetiva = ((rbt12 * nominal) - pd) / rbt12 if rbt12 > 0 else 0
        return {
            "faixa": selected.get("faixa"),
            "aliquota_nominal": nominal,
            "parcela_deduzir": pd,
            "aliquota_efetiva": round(efetiva, 6),
            "partilha": selected.get("partilha", {}),
        }

    def get_sn_credito_icms_range(self) -> tuple[float, float]:
        """Retorna (pCredSN_max, pCredSN_tipico_max) para validação de range.

        Calculado a partir dos limites teóricos das faixas do SN.
        Sem conhecer o RBT12, valida se o crédito está dentro do possível.
        """
        self._ensure_sn_anexos()
        assert self._sn_anexos is not None
        credito = self._sn_anexos.get("credito_icms", {})
        return (
            float(credito.get("pCredSN_max", 0.0401)),
            float(credito.get("pCredSN_tipico_max", 0.0200)),
        )

    def get_csosn_validos(self) -> set[str]:
        """Retorna conjunto de CSOSNs válidos da Tabela B."""
        self._ensure_csosn()
        assert self._csosn_data is not None
        return set(self._csosn_data.keys())

    def get_csosn_info(self, csosn: str) -> dict | None:
        """Retorna info completa de um CSOSN (descrição, permite_credito, exige_st, campos)."""
        self._ensure_csosn()
        assert self._csosn_data is not None
        return self._csosn_data.get(csosn)

    def get_csosn_com_credito(self) -> set[str]:
        """Retorna CSOSNs que permitem crédito de ICMS."""
        self._ensure_csosn()
        assert self._csosn_data is not None
        return {k for k, v in self._csosn_data.items() if v.get("permite_credito") is True}

    def get_csosn_com_st(self) -> set[str]:
        """Retorna CSOSNs que exigem ST."""
        self._ensure_csosn()
        assert self._csosn_data is not None
        return {
            k for k, v in self._csosn_data.items()
            if v.get("aplica_st") is True or v.get("exige_st") is True
        }

    def get_csosn_descricao(self, csosn: str) -> str:
        """Retorna descrição legível do CSOSN."""
        info = self.get_csosn_info(csosn)
        if info:
            return info.get("descricao", csosn)
        return csosn

    def has_municipios_table(self) -> bool:
        """Retorna True se a tabela de municípios está disponível e não vazia."""
        self._ensure_municipios()
        assert self._municipios is not None
        return len(self._municipios) > 0

    # ── Benefícios Fiscais (JSON) ──

    def _ensure_beneficios(self) -> None:
        if self._beneficios is not None:
            return
        self._beneficios = {}
        # Se o loader usa data_dir customizado (ex: testes), derivar JSON dir dele
        json_dir = (
            self._data_dir.parent / "JSON"
            if self._data_dir != _DATA_DIR
            else _JSON_BENEFICIOS_DIR
        )
        if not json_dir.exists():
            return
        for path in sorted(json_dir.glob("*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                # Filtrar: apenas JSONs de benefício (têm codigo_beneficio)
                codigo = data.get("codigo_beneficio")
                if not codigo:
                    continue
                self._beneficios[codigo] = BeneficioProfile.from_json(data)
            except Exception:
                _logger.warning("Erro ao carregar beneficio %s", path.name, exc_info=True)

    @staticmethod
    def _normalizar_codigo_beneficio(codigo: str) -> str:
        """Normaliza código de benefício para match flexível.

        'COMPETE ATACADISTA' → 'COMPETE_ATACADISTA'
        'compete atacadista' → 'COMPETE_ATACADISTA'
        'COMPETE-ATACADISTA' → 'COMPETE_ATACADISTA'
        """
        return codigo.strip().upper().replace(" ", "_").replace("-", "_")

    def get_beneficio(self, codigo: str) -> BeneficioProfile | None:
        """Retorna o perfil do benefício pelo codigo_beneficio, ou None.

        Faz match normalizado (espaço/hífen → underscore, case insensitive).
        """
        self._ensure_beneficios()
        assert self._beneficios is not None
        # Match exato primeiro
        if codigo in self._beneficios:
            return self._beneficios[codigo]
        # Match normalizado
        norm = self._normalizar_codigo_beneficio(codigo)
        for key, profile in self._beneficios.items():
            if self._normalizar_codigo_beneficio(key) == norm:
                return profile
        return None

    def get_beneficios_do_cliente(self, codigos: list[str]) -> list[BeneficioProfile]:
        """Retorna lista de perfis para os benefícios declarados do cliente.

        Faz match normalizado para tolerar diferenças MySQL vs JSON.
        """
        self._ensure_beneficios()
        assert self._beneficios is not None
        result = []
        for c in codigos:
            profile = self.get_beneficio(c)  # usa match normalizado
            if profile:
                result.append(profile)
        return result

    # ── CST Efeitos (JSON) ──

    def _ensure_cst_efeitos(self) -> None:
        if self._cst_efeitos is not None:
            return
        self._cst_efeitos = {}
        json_dir = (
            self._data_dir.parent / "JSON"
            if self._data_dir != _DATA_DIR
            else _JSON_BENEFICIOS_DIR
        )
        path = json_dir / "Tabela_CST_Vigente.json"
        if not path.exists():
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            tab_b = data.get("blocos", {}).get("CST_ICMS", {}).get("tabela_b_tributacao", [])
            codigos = tab_b if isinstance(tab_b, list) else tab_b.get("codigos", [])
            for entry in codigos:
                codigo = entry.get("codigo", "")
                efeitos = entry.get("efeitos", [])
                if codigo:
                    self._cst_efeitos[codigo] = set(efeitos)
        except Exception:
            _logger.warning("Erro ao carregar Tabela_CST_Vigente.json", exc_info=True)

    def get_cst_efeitos(self, cst_trib: str) -> set[str]:
        """Retorna efeitos do CST (últimos 2 dígitos) a partir do JSON."""
        self._ensure_cst_efeitos()
        assert self._cst_efeitos is not None
        return self._cst_efeitos.get(cst_trib, set())

    def cst_tem_efeito(self, cst_trib: str, efeito: str) -> bool:
        """Verifica se um CST tem determinado efeito."""
        return efeito in self.get_cst_efeitos(cst_trib)

    def csts_com_efeito(self, efeito: str) -> set[str]:
        """Retorna todos os CSTs que têm determinado efeito."""
        self._ensure_cst_efeitos()
        assert self._cst_efeitos is not None
        return {cod for cod, efs in self._cst_efeitos.items() if efeito in efs}

    def available_tables(self) -> list[str]:
        """Retorna lista de tabelas disponíveis em data/reference/."""
        tables: list[str] = []
        if (self._data_dir / "aliquotas_internas_uf.yaml").exists():
            tables.append("aliquotas_internas_uf")
        if (self._data_dir / "fcp_por_uf.yaml").exists():
            tables.append("fcp_por_uf")
        if (self._data_dir / "ibge_municipios.yaml").exists():
            tables.append("ibge_municipios")
        if (self._data_dir / "ncm_tipi_categorias.yaml").exists():
            tables.append("ncm_tipi_categorias")
        if (self._data_dir / "codigos_ajuste_uf.yaml").exists():
            tables.append("codigos_ajuste_uf")
        if (self._data_dir / "mva_por_ncm_uf.yaml").exists():
            tables.append("mva_por_ncm_uf")
        if (self._data_dir / "csosn_tabela_b.yaml").exists():
            tables.append("csosn_tabela_b")
        if (self._data_dir / "cst_pis_cofins_sn.yaml").exists():
            tables.append("cst_pis_cofins_sn")
        if (self._data_dir / "sn_anexos_aliquotas.yaml").exists():
            tables.append("sn_anexos_aliquotas")
        if (self._data_dir / "sn_sublimites_uf.yaml").exists():
            tables.append("sn_sublimites_uf")
        if (_DB_DIR / "sped.db").exists():
            tables.append("ncm_vigente")
            tables.append("cst_vigente")
            tables.append("difal_vigente")
        # Vigências
        vig_dir = self._data_dir / "vigencias"
        if vig_dir.exists():
            for subdir in sorted(vig_dir.iterdir()):
                if subdir.is_dir() and any(subdir.glob("*.yaml")):
                    tables.append(f"vigencias/{subdir.name}")
        # Benefícios fiscais (JSON)
        self._ensure_beneficios()
        if self._beneficios:
            tables.append("beneficios_fiscais")
        return tables


# ── Funções de conveniência (standalone, sem instância) ──

from functools import lru_cache as _lru_cache


@_lru_cache(maxsize=1)
def load_aliquotas_internas_uf() -> dict[str, float]:
    """Carrega alíquotas internas por UF do arquivo YAML de referência."""
    path = _DATA_DIR / "aliquotas_internas_uf.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    raw = data.get("aliquotas", data)  # suporta formato com ou sem meta
    return {uf: float(v) for uf, v in raw.items() if isinstance(v, (int, float))}


def get_aliquota_interna_uf(uf: str, default: float = 17.0) -> float:
    """Retorna a alíquota interna padrão para a UF informada."""
    tabela = load_aliquotas_internas_uf()
    return float(tabela.get(uf.upper(), default))
