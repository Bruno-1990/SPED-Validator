"""Detecção robusta de regime tributário com múltiplos sinais.

Usa IND_PERFIL, presença de CSOSN, CST Tabela A e outros sinais
para inferir o regime com grau de confiança.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..models import SpedRecord
from .helpers import get_field


class RegimeTributario(str, Enum):
    REGIME_NORMAL = "NORMAL"               # Lucro Real ou Presumido
    SIMPLES_NACIONAL = "SIMPLES_NACIONAL"  # LC 123/2006
    MEI = "MEI"                            # Microempreendedor Individual
    DESCONHECIDO = "DESCONHECIDO"          # Não foi possível determinar


@dataclass
class DetectionResult:
    regime: RegimeTributario
    confidence: float          # 0.0 a 1.0
    signals: list[str] = field(default_factory=list)
    needs_confirmation: bool = True


class RegimeDetector:
    """Detecta o regime tributário a partir dos registros do arquivo SPED.

    Usa múltiplos sinais com pesos para aumentar confiança.

    Sinais usados:
    1. IND_PERFIL no 0000: C = Simples Nacional (forte)
    2. Presença de CSOSN nos C170: indica SN (forte)
    3. IND_PERFIL A/B: indica Regime Normal (forte)
    4. Presença de CST Tabela A (00-90) nos C170: indica Normal (moderado)
    """

    from .helpers import (
        CST_DIFERIMENTO, CST_ISENTO_NT, CST_RESIDUAL, CST_TRIBUTADO, CSOSN_VALIDOS,
    )
    CSOSN_VALUES = CSOSN_VALIDOS
    CST_NORMAL_VALUES = CST_TRIBUTADO | CST_ISENTO_NT | CST_DIFERIMENTO | CST_RESIDUAL

    @classmethod
    def detect(cls, records: list[SpedRecord]) -> DetectionResult:
        signals: list[str] = []
        sn_score = 0.0
        normal_score = 0.0

        # Sinal 1: IND_PERFIL no 0000
        reg_0000 = next((r for r in records if r.register == "0000"), None)
        if reg_0000:
            ind_perfil = get_field(reg_0000, "IND_PERFIL")
            if ind_perfil == "C":
                sn_score += 0.7
                signals.append("IND_PERFIL=C no 0000 (forte indício de Simples Nacional)")
            elif ind_perfil in ("A", "B"):
                normal_score += 0.7
                signals.append(f"IND_PERFIL={ind_perfil} no 0000 (indica Regime Normal)")

        # Sinal 2: presença de CSOSN nos C170
        c170_records = [r for r in records if r.register == "C170"]
        has_csosn = False
        has_normal_cst = False

        for r in c170_records[:200]:  # Amostra dos primeiros 200 itens
            cst = get_field(r, "CST_ICMS")
            if cst in cls.CSOSN_VALUES:
                has_csosn = True
            if cst in cls.CST_NORMAL_VALUES:
                has_normal_cst = True

        if has_csosn:
            sn_score += 0.6
            signals.append("CSOSN encontrado em itens C170 (indica Simples Nacional)")
        if has_normal_cst and not has_csosn:
            normal_score += 0.5
            signals.append("CST Tabela A encontrado em C170 sem CSOSN (indica Regime Normal)")

        # Determinar regime
        if sn_score >= 0.6:
            regime = RegimeTributario.SIMPLES_NACIONAL
            confidence = min(sn_score, 1.0)
        elif normal_score >= 0.6:
            regime = RegimeTributario.REGIME_NORMAL
            confidence = min(normal_score, 1.0)
        else:
            regime = RegimeTributario.DESCONHECIDO
            confidence = 0.0
            signals.append("Sinais insuficientes — confirme o regime manualmente")

        needs_confirmation = confidence < 0.8 or regime == RegimeTributario.DESCONHECIDO

        return DetectionResult(
            regime=regime,
            confidence=confidence,
            signals=signals,
            needs_confirmation=needs_confirmation,
        )
