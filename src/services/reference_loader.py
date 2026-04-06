"""ReferenceLoader: carrega tabelas externas de referência (alíquotas, FCP, municípios, NCM).

Utilizado pelo difal_validator e outros módulos que dependem de dados
externos parametrizáveis em data/reference/.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "reference"


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

    def has_municipios_table(self) -> bool:
        """Retorna True se a tabela de municípios está disponível e não vazia."""
        self._ensure_municipios()
        assert self._municipios is not None
        return len(self._municipios) > 0

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
        # Vigências
        vig_dir = self._data_dir / "vigencias"
        if vig_dir.exists():
            for subdir in sorted(vig_dir.iterdir()):
                if subdir.is_dir() and any(subdir.glob("*.yaml")):
                    tables.append(f"vigencias/{subdir.name}")
        return tables
