"""FieldComparator — Motor de comparacao tipado SPED x XML (Fase 5).

Compara campos SPED vs XML usando tipos de comparacao definidos em field_map.yaml:
- EXACT: igualdade de string apos normalizacao
- MONETARY: decimal com tolerancia proporcional (BUG-005)
- PERCENTAGE: decimal com tolerancia 0.001%
- DATE: normaliza para AAAA-MM-DD
- CST_AWARE: CST ou CSOSN conforme CRT do emitente (BUG-001)
- DERIVED: campo calculado (mapeamento especifico)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from ..validators.tolerance import tolerancia_proporcional
from .beneficio_engine import CSOSN_TO_CST

logger = logging.getLogger(__name__)


@dataclass
class CompareResult:
    """Resultado de uma comparacao campo-a-campo."""
    status: str  # "ok" | "diverge" | "skip" | "ok_arredondamento"
    sped_val: str = ""
    xml_val: str = ""
    diferenca: float = 0.0
    percentual: float = 0.0
    nota: str = ""

    @classmethod
    def ok(cls) -> "CompareResult":
        return cls(status="ok")

    @classmethod
    def ok_arredondamento(cls, diff: float) -> "CompareResult":
        return cls(status="ok_arredondamento", diferenca=diff)

    @classmethod
    def diverge(cls, sped_val: str = "", xml_val: str = "",
                diferenca: float = 0.0, percentual: float = 0.0,
                nota: str = "") -> "CompareResult":
        return cls(status="diverge", sped_val=str(sped_val), xml_val=str(xml_val),
                   diferenca=diferenca, percentual=percentual, nota=nota)

    SKIP = None  # Sentinela; compare() retorna None para SKIP


class FieldComparator:
    """Motor de comparacao tipado entre campos SPED e XML."""

    def compare(self, sped_val, xml_val, tipo: str,
                context: dict | None = None) -> CompareResult | None:
        """Compara valores SPED vs XML conforme tipo de comparacao.

        Args:
            sped_val: Valor do campo SPED
            xml_val: Valor do campo XML
            tipo: Tipo de comparacao (EXACT, MONETARY, PERCENTAGE, DATE, CST_AWARE, DERIVED)
            context: Contexto adicional (emitentes_sn, crt_emitente, mapeamento)

        Returns:
            CompareResult ou None (SKIP)
        """
        if tipo == "EXACT":
            return self._exact(sped_val, xml_val)
        if tipo == "MONETARY":
            return self._monetary(sped_val, xml_val)
        if tipo == "PERCENTAGE":
            return self._percentage(sped_val, xml_val)
        if tipo == "DATE":
            return self._date(sped_val, xml_val)
        if tipo == "CST_AWARE":
            return self._cst_aware(sped_val, xml_val, context or {})
        if tipo == "DERIVED":
            return self._derived(sped_val, xml_val, context or {})
        return None  # SKIP

    def _exact(self, sped: str | None, xml: str | None) -> CompareResult:
        """Comparacao exata apos normalizacao."""
        def _norm(v):
            return str(v or "").strip().upper().replace(".", "").replace("-", "").replace("/", "")
        s, x = _norm(sped), _norm(xml)
        if s == x:
            return CompareResult.ok()
        return CompareResult.diverge(sped_val=str(sped or ""), xml_val=str(xml or ""))

    def _monetary(self, sped, xml) -> CompareResult:
        """Comparacao decimal com tolerancia proporcional (BUG-005).

        Politica de ausencia (mapeamento robusto):
        - Ambos ausentes/None → OK (sem divergencia)
        - Ambos zero → OK
        - Um ausente e outro tem valor → diverge (ausente != zero)
        """
        sped_is_none = sped is None or str(sped).strip() == ""
        xml_is_none = xml is None or str(xml).strip() == ""

        # Ambos ausentes → OK
        if sped_is_none and xml_is_none:
            return CompareResult.ok()

        sped_d = self._to_decimal(sped)
        xml_d = self._to_decimal(xml)

        # Um ausente e outro com valor significativo → diverge
        if sped_is_none and xml_d != Decimal("0"):
            return CompareResult.diverge(
                sped_val="(ausente)", xml_val=f"{float(xml_d):.2f}",
                diferenca=float(xml_d),
                nota="Campo ausente no SPED mas presente no XML",
            )
        if xml_is_none and sped_d != Decimal("0"):
            return CompareResult.diverge(
                sped_val=f"{float(sped_d):.2f}", xml_val="(ausente)",
                diferenca=float(sped_d),
                nota="Campo ausente no XML mas presente no SPED",
            )

        diff = abs(sped_d - xml_d)
        tol = Decimal(str(tolerancia_proporcional(float(max(sped_d, xml_d)))))

        if diff <= tol:
            if diff > 0:
                return CompareResult.ok_arredondamento(diff=float(diff))
            return CompareResult.ok()

        pct = float(diff / max(sped_d, Decimal("0.01")) * 100)
        return CompareResult.diverge(
            sped_val=f"{float(sped_d):.2f}",
            xml_val=f"{float(xml_d):.2f}",
            diferenca=float(diff),
            percentual=pct,
        )

    def _percentage(self, sped, xml) -> CompareResult:
        """Comparacao de aliquota com tolerancia 0.001%."""
        sped_f = self._to_float(sped)
        xml_f = self._to_float(xml)
        diff = abs(sped_f - xml_f)
        if diff <= 0.001:
            return CompareResult.ok()
        return CompareResult.diverge(
            sped_val=f"{sped_f:.2f}",
            xml_val=f"{xml_f:.2f}",
            diferenca=diff,
        )

    def _date(self, sped: str | None, xml: str | None) -> CompareResult:
        """Comparacao de datas (SPED=DDMMAAAA, XML=AAAA-MM-DDThh:mm:ss)."""
        s = str(sped or "").strip()
        x = str(xml or "").strip()

        # Normalizar SPED: DDMMAAAA → AAAA-MM-DD
        if len(s) == 8 and s.isdigit():
            s_norm = f"{s[4:8]}-{s[2:4]}-{s[0:2]}"
        else:
            s_norm = s

        # Normalizar XML: truncar horario
        x_norm = x[:10] if len(x) >= 10 else x

        if s_norm == x_norm:
            return CompareResult.ok()
        return CompareResult.diverge(sped_val=s, xml_val=x)

    def _cst_aware(self, sped_cst: str | None, xml_cst: str | None,
                   context: dict) -> CompareResult:
        """CST ou CSOSN conforme CRT do emitente (corrige falsos positivos SN)."""
        sped_n = str(sped_cst or "").strip()
        xml_n = str(xml_cst or "").strip()

        # Detectar se XML usa CSOSN (emitente SN)
        emitente_sn = xml_n in CSOSN_TO_CST
        crt = context.get("crt_emitente")
        if crt and int(crt) in (1, 2):
            emitente_sn = True

        if emitente_sn:
            cst_equiv = CSOSN_TO_CST.get(xml_n, xml_n)
            # Normalizar SPED para 2 digitos
            sped_norm = sped_n[-2:] if len(sped_n) > 2 else sped_n.zfill(2)
            if sped_norm == cst_equiv:
                return CompareResult.ok()
            return CompareResult.diverge(
                sped_val=sped_n, xml_val=xml_n,
                nota=f"Emitente SN (CRT={crt or '?'}): CSOSN {xml_n} → CST esperado {cst_equiv}",
            )

        # Regime normal: comparacao direta
        if sped_n == xml_n:
            return CompareResult.ok()
        return CompareResult.diverge(sped_val=sped_n, xml_val=xml_n)

    def _derived(self, sped_val, xml_val, context: dict) -> CompareResult:
        """Campo derivado com mapeamento especifico (ex: COD_SIT × cStat)."""
        mapeamento = context.get("mapeamento", {})
        xml_str = str(xml_val or "").strip()
        sped_str = str(sped_val or "").strip()

        expected = mapeamento.get(xml_str)
        if expected is None:
            return None  # Sem mapeamento → skip
        if sped_str == expected:
            return CompareResult.ok()
        return CompareResult.diverge(
            sped_val=sped_str, xml_val=xml_str,
            nota=f"Esperado COD_SIT={expected} para cStat={xml_str}",
        )

    @staticmethod
    def _to_decimal(val) -> Decimal:
        if val is None:
            return Decimal("0")
        try:
            return Decimal(str(val).replace(",", ".").strip())
        except Exception:
            return Decimal("0")

    @staticmethod
    def _to_float(val) -> float:
        if val is None:
            return 0.0
        try:
            return float(str(val).replace(",", ".").strip())
        except (ValueError, TypeError):
            return 0.0
