"""Testes que garantem que segredos nao sao hardcoded no bundle frontend (bug #3).

O frontend nao tem framework de testes configurado, entao validamos via
string-grep no arquivo de fonte. O objetivo e impedir que o fallback hardcoded
'sped-audit-dev-key-2026-central-contabil' volte ao bundle publico.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CLIENT_TS = Path(__file__).parent.parent / "frontend" / "src" / "api" / "client.ts"


class TestFrontendSecrets:
    def test_client_ts_exists(self):
        assert CLIENT_TS.exists(), f"Arquivo nao encontrado: {CLIENT_TS}"

    def test_client_ts_has_no_hardcoded_dev_api_key(self):
        """Bug #3: fallback 'sped-audit-dev-key-...' nao deve existir no bundle."""
        content = CLIENT_TS.read_text(encoding="utf-8")
        assert "sped-audit-dev-key-2026-central-contabil" not in content, (
            "API_KEY dev-fallback encontrada em client.ts — remover para nao vazar no bundle"
        )

    def test_client_ts_has_missing_key_guard(self):
        """Bug #3: deve haver algum guard (console.error ou throw) se VITE_API_KEY ausente."""
        content = CLIENT_TS.read_text(encoding="utf-8")
        # Aceita qualquer um dos dois padroes como guard valido
        has_guard = (
            re.search(r"if\s*\(\s*!\s*API_KEY\s*\)", content)
            and (
                "console.error" in content
                or "throw new Error" in content
                or "throw Error" in content
            )
        )
        assert has_guard, (
            "client.ts deve ter bloco 'if (!API_KEY) { throw/console.error ... }'"
        )
