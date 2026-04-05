"""Testes para deduplicação de erros no pipeline e serviços auxiliares.

Cobre:
- _deduplicate_errors (pipeline.py)
- format_friendly_message / get_guidance (error_messages.py)
- _severity_for (validation_service.py)
"""

from __future__ import annotations

import pytest

from src.models import ValidationError
from src.services.pipeline import _deduplicate_errors
from src.services.error_messages import format_friendly_message, get_guidance
from src.services.validation_service import _severity_for


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_error(
    error_type: str,
    line_number: int = 1,
    register: str = "C170",
    field_name: str = "ALIQ_ICMS",
    value: str = "0",
    message: str = "erro",
    expected_value: str | None = None,
) -> ValidationError:
    """Cria um ValidationError com defaults convenientes."""
    return ValidationError(
        line_number=line_number,
        register=register,
        field_no=10,
        field_name=field_name,
        value=value,
        error_type=error_type,
        message=message,
        expected_value=expected_value,
    )


# ══════════════════════════════════════════════
# Part 1: _deduplicate_errors
# ══════════════════════════════════════════════

class TestDeduplicateErrors:
    """Testa a lógica de supressão de erros genéricos por hipóteses."""

    def test_aliq_icms_ausente_suppresses_cst_aliq_zero_forte_same_line(self):
        """ALIQ_ICMS_AUSENTE deve suprimir CST_ALIQ_ZERO_FORTE na mesma linha."""
        errors = [
            _make_error("ALIQ_ICMS_AUSENTE", line_number=42),
            _make_error("CST_ALIQ_ZERO_FORTE", line_number=42),
        ]
        result = _deduplicate_errors(errors)

        types = [e.error_type for e in result]
        assert "ALIQ_ICMS_AUSENTE" in types
        assert "CST_ALIQ_ZERO_FORTE" not in types

    def test_cst_hipotese_suppresses_cst_aliq_zero_forte_same_line(self):
        """CST_HIPOTESE deve suprimir CST_ALIQ_ZERO_FORTE na mesma linha."""
        errors = [
            _make_error("CST_HIPOTESE", line_number=100),
            _make_error("CST_ALIQ_ZERO_FORTE", line_number=100),
        ]
        result = _deduplicate_errors(errors)

        types = [e.error_type for e in result]
        assert "CST_HIPOTESE" in types
        assert "CST_ALIQ_ZERO_FORTE" not in types

    def test_cst_hipotese_suppresses_cst_aliq_zero_moderado_same_line(self):
        """CST_HIPOTESE deve suprimir CST_ALIQ_ZERO_MODERADO na mesma linha."""
        errors = [
            _make_error("CST_HIPOTESE", line_number=55),
            _make_error("CST_ALIQ_ZERO_MODERADO", line_number=55),
        ]
        result = _deduplicate_errors(errors)

        types = [e.error_type for e in result]
        assert "CST_HIPOTESE" in types
        assert "CST_ALIQ_ZERO_MODERADO" not in types

    def test_different_lines_not_suppressed(self):
        """Erros em linhas diferentes NÃO devem ser suprimidos."""
        errors = [
            _make_error("ALIQ_ICMS_AUSENTE", line_number=10),
            _make_error("CST_ALIQ_ZERO_FORTE", line_number=20),
            _make_error("CST_HIPOTESE", line_number=30),
            _make_error("CST_ALIQ_ZERO_MODERADO", line_number=40),
        ]
        result = _deduplicate_errors(errors)

        assert len(result) == 4

    def test_non_hypothesis_errors_never_suppressed(self):
        """Erros não-hipotese (BENEFICIO_NAO_VINCULADO etc.) nunca são suprimidos."""
        errors = [
            _make_error("ALIQ_ICMS_AUSENTE", line_number=10),
            _make_error("BENEFICIO_NAO_VINCULADO", line_number=10),
            _make_error("CALCULO_DIVERGENTE", line_number=10),
            _make_error("MISSING_REQUIRED", line_number=10),
        ]
        result = _deduplicate_errors(errors)

        types = [e.error_type for e in result]
        assert "BENEFICIO_NAO_VINCULADO" in types
        assert "CALCULO_DIVERGENTE" in types
        assert "MISSING_REQUIRED" in types
        assert "ALIQ_ICMS_AUSENTE" in types

    def test_empty_list_returns_empty(self):
        """Lista vazia deve retornar lista vazia."""
        assert _deduplicate_errors([]) == []

    def test_no_hypotheses_returns_unchanged(self):
        """Lista sem hipóteses deve retornar inalterada."""
        errors = [
            _make_error("CALCULO_DIVERGENTE", line_number=1),
            _make_error("MISSING_REQUIRED", line_number=2),
            _make_error("CST_ALIQ_ZERO_FORTE", line_number=3),
        ]
        result = _deduplicate_errors(errors)

        assert len(result) == 3
        assert result == errors

    def test_multiple_hypotheses_different_lines_deduplicate_correctly(self):
        """Múltiplas hipóteses em linhas distintas deduplicam apenas suas linhas."""
        errors = [
            # Linha 10: ALIQ_ICMS_AUSENTE suprime CST_ALIQ_ZERO_FORTE
            _make_error("ALIQ_ICMS_AUSENTE", line_number=10),
            _make_error("CST_ALIQ_ZERO_FORTE", line_number=10),
            # Linha 20: CST_HIPOTESE suprime CST_ALIQ_ZERO_FORTE e CST_ALIQ_ZERO_MODERADO
            _make_error("CST_HIPOTESE", line_number=20),
            _make_error("CST_ALIQ_ZERO_FORTE", line_number=20),
            _make_error("CST_ALIQ_ZERO_MODERADO", line_number=20),
            # Linha 30: sem hipótese — CST_ALIQ_ZERO_FORTE sobrevive
            _make_error("CST_ALIQ_ZERO_FORTE", line_number=30),
        ]
        result = _deduplicate_errors(errors)

        # Deve restar: ALIQ(10), CST_HIP(20), CST_ALIQ_ZERO_FORTE(30)
        assert len(result) == 3
        result_pairs = [(e.error_type, e.line_number) for e in result]
        assert ("ALIQ_ICMS_AUSENTE", 10) in result_pairs
        assert ("CST_HIPOTESE", 20) in result_pairs
        assert ("CST_ALIQ_ZERO_FORTE", 30) in result_pairs


# ══════════════════════════════════════════════
# Part 2: format_friendly_message
# ══════════════════════════════════════════════

class TestFormatFriendlyMessage:
    """Testa geração de mensagens amigáveis para erros."""

    def test_missing_required_returns_formatted(self):
        msg = format_friendly_message(
            "MISSING_REQUIRED",
            field_name="COD_PART",
            register="C100",
            line=5,
        )
        assert "COD_PART" in msg
        assert "obrigatório" in msg
        assert "C100" in msg
        assert "5" in msg

    def test_calculo_divergente_returns_formatted(self):
        msg = format_friendly_message(
            "CALCULO_DIVERGENTE",
            field_name="VL_ICMS",
            value="100.00",
            expected="120.00",
        )
        assert "VL_ICMS" in msg
        assert "100.00" in msg
        assert "120.00" in msg

    def test_cst_hipotese_returns_formatted(self):
        msg = format_friendly_message(
            "CST_HIPOTESE",
            register="C170",
            line=42,
            value="00",
        )
        assert "C170" in msg
        assert "42" in msg
        assert "00" in msg

    def test_aliq_icms_ausente_returns_formatted(self):
        msg = format_friendly_message(
            "ALIQ_ICMS_AUSENTE",
            register="C170",
            line=99,
        )
        assert "C170" in msg
        assert "99" in msg
        assert "0%" in msg or "ausente" in msg.lower() or "zerado" in msg.lower()

    def test_unknown_error_type_returns_default(self):
        msg = format_friendly_message(
            "TIPO_INEXISTENTE_XYZ",
            field_name="CAMPO",
            register="C100",
            line=1,
        )
        assert "CAMPO" in msg
        assert "C100" in msg

    def test_placeholders_are_filled(self):
        msg = format_friendly_message(
            "MISSING_REQUIRED",
            field_name="MY_FIELD",
            register="REG_X",
            line=777,
            value="val123",
        )
        assert "MY_FIELD" in msg
        assert "REG_X" in msg
        assert "777" in msg


# ══════════════════════════════════════════════
# Part 3: get_guidance
# ══════════════════════════════════════════════

class TestGetGuidance:
    """Testa retorno de orientações de correção."""

    @pytest.mark.parametrize("error_type", [
        "MISSING_REQUIRED",
        "CALCULO_DIVERGENTE",
        "CST_HIPOTESE",
        "ALIQ_ICMS_AUSENTE",
        "CST_ALIQ_ZERO_FORTE",
    ])
    def test_known_types_return_guidance(self, error_type: str):
        guidance = get_guidance(error_type)
        assert isinstance(guidance, str)
        assert len(guidance) > 10  # guidance real, não placeholder vazio

    def test_unknown_type_returns_default_guidance(self):
        guidance = get_guidance("TIPO_INEXISTENTE_XYZ")
        assert "Guia Prático" in guidance


# ══════════════════════════════════════════════
# Part 4: _severity_for
# ══════════════════════════════════════════════

class TestSeverityFor:
    """Testa mapeamento de error_type para severidade."""

    @pytest.mark.parametrize("error_type", [
        "CALCULO_DIVERGENTE",
        "ALIQ_ICMS_AUSENTE",
        "CST_HIPOTESE",
    ])
    def test_critical_types(self, error_type: str):
        assert _severity_for(error_type) == "critical"

    @pytest.mark.parametrize("error_type", [
        "CST_ALIQ_ZERO_FORTE",
        "CST_CFOP_INCOMPATIVEL",
    ])
    def test_warning_types(self, error_type: str):
        assert _severity_for(error_type) == "warning"

    @pytest.mark.parametrize("error_type", [
        "CST_ALIQ_ZERO_MODERADO",
    ])
    def test_info_types(self, error_type: str):
        assert _severity_for(error_type) == "info"

    def test_unknown_type_returns_error_default(self):
        assert _severity_for("TIPO_TOTALMENTE_DESCONHECIDO") == "error"
