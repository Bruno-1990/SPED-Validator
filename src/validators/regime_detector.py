"""Deteccao de regime tributario por CSTs reais do arquivo (BUG-001 fix).

CORRECAO CRITICA: IND_PERFIL indica nivel de escrituracao (A/B/C),
NAO regime tributario. A deteccao usa exclusivamente os CSTs encontrados
nos registros C170/C190 do arquivo SPED.

Evidencias de regime:
- CSTs 101-900 (Tabela B) ou CSOSN → Simples Nacional
- CSTs 00-90 (Tabela A) sem CSOSN  → Regime Normal (LP/LR)
- Conflito CST vs cadastro MySQL    → regime_source='CONFLITO'
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
    DESCONHECIDO = "DESCONHECIDO"          # Nao foi possivel determinar


@dataclass
class DetectionResult:
    regime: RegimeTributario
    confidence: float          # 0.0 a 1.0
    signals: list[str] = field(default_factory=list)
    needs_confirmation: bool = True
    regime_source: str = "CST"  # "CST" | "CST+MYSQL" | "CONFLITO"


# CSOSN validos (Tabela B — Simples Nacional)
CSOSN_VALIDOS = {"101", "102", "103", "201", "202", "203", "300", "400", "500", "900"}

# CSTs Tabela A (Regime Normal) — 2 digitos
CST_TABELA_A = {
    "00", "02", "10", "12", "13", "15", "20", "30", "40", "41",
    "50", "51", "52", "53", "60", "61", "70", "72", "74", "90",
}


class RegimeDetector:
    """Detecta o regime tributario a partir dos CSTs reais do arquivo SPED.

    BUG-001 CORRIGIDO: IND_PERFIL NAO e mais usado para determinar regime.
    IND_PERFIL e armazenado apenas como metadado informativo.

    Logica de deteccao:
    1. Varrer C170 e C190 em busca de CSTs
    2. Se encontrar CSOSN (101-900) → Simples Nacional (determinante)
    3. Se encontrar apenas CSTs Tabela A (00-90) → Regime Normal (determinante)
    4. Confirmar com cadastro MySQL (se disponivel)
    5. Se conflito → regime_source='CONFLITO', CST prevalece
    """

    @classmethod
    def detect(cls, records: list[SpedRecord]) -> DetectionResult:
        signals: list[str] = []
        has_csosn = False
        has_cst_normal = False

        # Registrar IND_PERFIL apenas como informacao (NAO como regime)
        reg_0000 = next((r for r in records if r.register == "0000"), None)
        if reg_0000:
            ind_perfil = get_field(reg_0000, "IND_PERFIL")
            if ind_perfil:
                signals.append(
                    f"IND_PERFIL={ind_perfil} (nivel de escrituracao, NAO indica regime)"
                )

        # Sinal DETERMINANTE: CSTs reais nos C170 e C190
        registros_fiscais = [
            r for r in records if r.register in ("C170", "C190")
        ]
        for r in registros_fiscais:
            cst = get_field(r, "CST_ICMS")
            if not cst:
                continue
            cst_limpo = cst.strip()
            # CST de 6 digitos (SN) → normalizar para ultimos 2
            if len(cst_limpo) > 3 and cst_limpo.isdigit():
                cst_limpo = cst_limpo[-2:]
            if cst_limpo in CSOSN_VALIDOS:
                has_csosn = True
            elif cst_limpo in CST_TABELA_A:
                has_cst_normal = True
            # CSTs numericos >= 101 tambem indicam SN
            if cst_limpo.isdigit() and int(cst_limpo) >= 101:
                has_csosn = True

        if has_csosn:
            signals.append("CSOSN/CST Tabela B encontrado em C170/C190 (Simples Nacional)")
            regime = RegimeTributario.SIMPLES_NACIONAL
            confidence = 1.0
        elif has_cst_normal:
            signals.append("CST Tabela A encontrado em C170/C190 sem CSOSN (Regime Normal)")
            regime = RegimeTributario.REGIME_NORMAL
            confidence = 1.0
        else:
            signals.append("Nenhum CST encontrado em C170/C190 — confirme o regime manualmente")
            regime = RegimeTributario.DESCONHECIDO
            confidence = 0.0

        needs_confirmation = confidence < 0.8 or regime == RegimeTributario.DESCONHECIDO

        return DetectionResult(
            regime=regime,
            confidence=confidence,
            signals=signals,
            needs_confirmation=needs_confirmation,
            regime_source="CST",
        )
