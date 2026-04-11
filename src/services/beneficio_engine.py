"""BeneficioEngine — Modulo dedicado para consultas fiscais de beneficios (Fase 3).

Instanciado uma vez no Stage 0 e disponivel para todos os estagios.
Responde perguntas fiscais concretas sobre beneficios ativos do contribuinte:
- Quais CSTs sao validos para saida?
- Qual a aliquota efetiva esperada?
- O beneficio exige debito integral?
- O NCM esta no escopo do beneficio?

Base legal:
- COMPETE-ES: Dec. 1.663-R/2005
- INVEST-ES: Dec. 1.599-R/2005
- FUNDAP: Lei 2.508/1970
- Res. CGSN 140/2018 Art. 59/60 (CSOSN → CST)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from .reference_loader import BeneficioProfile

logger = logging.getLogger(__name__)


# ── CSOSN → CST Mapping (Res. CGSN 140/2018 Art. 59/60) ──

CSOSN_TO_CST: dict[str, str] = {
    "101": "00",   # Tributada com permissao de credito
    "102": "20",   # Tributada com reducao de BC (DISTINTO de 103)
    "103": "40",   # Isenta — sem tributacao
    "201": "10",   # Com ST + debito proprio
    "202": "10",   # Com ST sem tributacao propria (efeito diferente de 201)
    "203": "30",   # ST sem debito proprio
    "300": "41",   # Imune
    "400": "40",   # Nao tributada pelo SN
    "500": "60",   # ST ja retida anteriormente
    "900": "90",   # Outros
}

# CSTs validos por tipo de beneficio ICMS-ES
_BENEFICIO_RULES: dict[str, dict] = {
    "COMPETE_ATACADISTA": {
        "cst_obrigatorio": {"00"},
        "aliq_efetiva": 0.03,  # 3% credito presumido via E111
        "debito_integral": True,
        "base_legal": "Dec. 1.663-R/2005",
    },
    "COMPETE_VAREJISTA_ECOMMERCE": {
        "cst_obrigatorio": {"00"},
        "aliq_efetiva": 0.03,  # 3-6% conforme faixa
        "debito_integral": True,
        "base_legal": "Dec. especifico e-commerce",
    },
    "COMPETE_IND_GRAFICAS": {
        "cst_obrigatorio": {"00"},
        "aliq_efetiva": None,  # Conforme decreto
        "debito_integral": True,
        "base_legal": "Conforme ato concessorio",
    },
    "COMPETE_IND_PAPELAO_MAT_PLAST": {
        "cst_obrigatorio": {"00"},
        "aliq_efetiva": None,
        "debito_integral": True,
        "base_legal": "Conforme ato concessorio",
    },
    "INVEST_ES_INDUSTRIA": {
        "cst_obrigatorio": {"51"},
        "aliq_efetiva": None,  # Diferimento
        "debito_integral": False,
        "base_legal": "Dec. 1.599-R/2005",
    },
    "INVEST_ES_IMPORTACAO": {
        "cst_obrigatorio": {"51"},
        "aliq_efetiva": None,
        "debito_integral": False,
        "base_legal": "Conforme decreto",
    },
    "FUNDAP": {
        "cst_obrigatorio": {"00"},
        "aliq_efetiva": None,  # Credito sobre pauta
        "debito_integral": True,
        "base_legal": "Lei 2.508/1970",
    },
}

# Beneficios mutuamente exclusivos
_EXCLUSIVOS: list[tuple[str, str]] = [
    ("COMPETE_ATACADISTA", "COMPETE_VAREJISTA_ECOMMERCE"),
    ("COMPETE_ATACADISTA", "COMPETE_IND_GRAFICAS"),
    ("COMPETE_ATACADISTA", "COMPETE_IND_PAPELAO_MAT_PLAST"),
    ("COMPETE_VAREJISTA_ECOMMERCE", "COMPETE_IND_GRAFICAS"),
]


@dataclass
class BeneficioAuditResult:
    """Resultado de auditoria de item contra beneficio."""
    rule_id: str
    severity: str
    message: str
    campo: str = ""
    valor_encontrado: str = ""
    valor_esperado: str = ""


class BeneficioEngine:
    """Motor de consultas fiscais sobre beneficios ativos do contribuinte.

    Instanciado no Stage 0 com os beneficios ativos do periodo.
    Imutavel apos construcao.
    """

    def __init__(
        self,
        beneficios: list[BeneficioProfile],
        uf: str = "ES",
        periodo_ini: date | None = None,
    ):
        self._beneficios = beneficios
        self._uf = uf
        self._periodo = periodo_ini
        self._by_codigo: dict[str, BeneficioProfile] = {
            b.codigo: b for b in beneficios
        }
        self._rules = {
            b.codigo: _BENEFICIO_RULES.get(b.codigo, {})
            for b in beneficios
        }

    @property
    def has_beneficios(self) -> bool:
        return len(self._beneficios) > 0

    # ── Consultas para validadores SPED ──

    def get_cst_validos_saida(self, cfop: str) -> set[str]:
        """CSTs validos para NF-e de saida dado CFOP e beneficios ativos.

        Union dos conjuntos de todos os beneficios aplicaveis ao CFOP.
        """
        result: set[str] = set()
        cfop_prefix = cfop[:1] if cfop else ""
        for b in self._beneficios:
            if cfop in b.cfops or cfop_prefix in ("5", "6"):
                # CSTs do JSON do beneficio
                result.update(b.csts)
                # CSTs das regras hardcoded
                rules = self._rules.get(b.codigo, {})
                cst_obr = rules.get("cst_obrigatorio")
                if cst_obr:
                    result.update(cst_obr)
        return result if result else set()

    def get_cst_validos_saida_all_cfops(self) -> set[str]:
        """Union de todos os CSTs validos para saidas, todos os beneficios."""
        result: set[str] = set()
        for b in self._beneficios:
            result.update(b.csts)
            rules = self._rules.get(b.codigo, {})
            cst_obr = rules.get("cst_obrigatorio")
            if cst_obr:
                result.update(cst_obr)
        return result

    def get_aliq_esperada(self, cfop: str, ncm: str | None = None) -> float | None:
        """Aliquota ICMS efetiva apos beneficio. None = sem beneficio aplicavel."""
        for b in self._beneficios:
            rules = self._rules.get(b.codigo, {})
            aliq = rules.get("aliq_efetiva")
            if aliq is not None:
                return aliq
        return None

    def get_aliq_map(self) -> dict[str, float]:
        """Mapa cfop_prefix → aliquota para todos os beneficios ativos."""
        result: dict[str, float] = {}
        for b in self._beneficios:
            rules = self._rules.get(b.codigo, {})
            aliq = rules.get("aliq_efetiva")
            if aliq is not None:
                for cfop in b.cfops:
                    result[cfop] = aliq
                # Prefixos genericos
                result["5"] = aliq
                result["6"] = aliq
        return result

    def get_reducao_bc(self, cfop: str, ncm: str | None = None) -> float | None:
        """% de reducao da BC esperado. None = sem reducao."""
        for b in self._beneficios:
            raw = b.raw
            impactos = raw.get("impactos_fiscais", {})
            if "reducao_base" in impactos:
                return float(impactos["reducao_base"])
        return None

    def get_debito_integral(self, cfop: str) -> bool:
        """Beneficio exige debito integral? (COMPETE = sim)."""
        for b in self._beneficios:
            rules = self._rules.get(b.codigo, {})
            if rules.get("debito_integral", False):
                return True
        return False

    def is_ncm_no_escopo(self, ncm: str, codigo_beneficio: str) -> bool:
        """Verifica se o NCM esta no escopo do beneficio."""
        b = self._by_codigo.get(codigo_beneficio)
        if not b:
            return True  # Se nao ha info, assumir no escopo
        raw = b.raw
        elegib = raw.get("elegibilidade", {})
        ncms = elegib.get("ncms_permitidos", [])
        if not ncms:
            return True  # Sem restricao de NCM
        return ncm in ncms or ncm[:4] in ncms or ncm[:6] in ncms

    # ── CRT do emitente ──

    @staticmethod
    def get_crt_expected_cst_set(crt: int) -> tuple[str, set[str]]:
        """(campo_cst, valores_validos) baseado no CRT do emitente."""
        if crt in (1, 2):  # SN ou SN excesso receita
            return ("CSOSN", set(CSOSN_TO_CST.keys()))
        return ("CST_ICMS", {
            "00", "10", "20", "30", "40", "41", "50", "51", "60", "70", "90",
        })

    # ── Conflitos entre beneficios ──

    def get_conflitos_beneficios(self) -> list[str]:
        """Lista de pares de beneficios mutuamente exclusivos ativos."""
        codigos = {b.codigo for b in self._beneficios}
        conflitos = []
        for a, b in _EXCLUSIVOS:
            if a in codigos and b in codigos:
                conflitos.append(f"{a} x {b}")
        return conflitos

    # ── Alertas de expiracao ──

    def get_beneficios_expirando(self, dias: int = 90) -> list[BeneficioProfile]:
        """Beneficios com vigencia expirando em N dias."""
        if not self._periodo:
            return []
        from datetime import timedelta
        limite = self._periodo + timedelta(days=dias)
        result = []
        for b in self._beneficios:
            raw = b.raw
            ato = raw.get("ato_concessorio_cliente", {})
            fim_str = ato.get("vigencia_fim")
            if fim_str:
                try:
                    fim = date.fromisoformat(fim_str)
                    if fim <= limite:
                        result.append(b)
                except (ValueError, TypeError):
                    pass
        return result

    # ── Auditoria de item XML × beneficio ──

    def audit_item_xml(
        self, cst_icms: str, aliq_icms: float, cfop: str, ncm: str = "",
        emitente_crt: int = 3,
    ) -> list[BeneficioAuditResult]:
        """Audita um item da NF-e contra as regras de beneficio ativo.

        Retorna lista de violacoes (vazia = OK).
        """
        results: list[BeneficioAuditResult] = []

        if not self._beneficios:
            return results

        # Apenas NF-e de saida (CFOP 5xxx/6xxx)
        if not cfop or cfop[0] not in ("5", "6"):
            return results

        cst_validos = self.get_cst_validos_saida(cfop)
        if cst_validos and cst_icms not in cst_validos:
            results.append(BeneficioAuditResult(
                rule_id="SPED_CST_BENEFICIO",
                severity="error",
                message=f"CST {cst_icms} incompativel com beneficios ativos. "
                        f"CSTs validos para CFOP {cfop}: {sorted(cst_validos)}.",
                campo="CST_ICMS",
                valor_encontrado=cst_icms,
                valor_esperado=",".join(sorted(cst_validos)),
            ))

        aliq_esperada = self.get_aliq_esperada(cfop, ncm)
        if aliq_esperada is not None and self.get_debito_integral(cfop):
            # COMPETE: debito integral = aliquota cheia, NAO reduzida
            # Se aliquota < aliquota interna, pode ser erro
            # Nota: aqui verificamos apenas se a aliquota e suspeitamente baixa
            if aliq_icms > 0 and aliq_icms < 10.0:
                results.append(BeneficioAuditResult(
                    rule_id="SPED_ALIQ_BENEFICIO",
                    severity="error",
                    message=f"Aliquota ICMS {aliq_icms:.1f}% em saida com beneficio que exige "
                            f"debito integral. Esperado aliquota cheia da UF (17% para ES).",
                    campo="ALIQ_ICMS",
                    valor_encontrado=f"{aliq_icms:.1f}",
                    valor_esperado="17.0",
                ))

        return results

    # ── Base legal por beneficio ──

    def get_base_legal(self, codigo_beneficio: str) -> str:
        """Retorna base legal do beneficio."""
        rules = self._rules.get(codigo_beneficio, {})
        return rules.get("base_legal", "")
