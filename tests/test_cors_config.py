"""Testes de configuracao CORS (bug #2).

Garante que o middleware CORS nao usa allow_origins=["*"] com allow_credentials=True
(combinacao proibida pela spec CORS) e que a lista vem de ALLOWED_ORIGINS no env.
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest
from fastapi.middleware.cors import CORSMiddleware


def _reload_api_main():
    """Reimporta api.main para pegar env atual. Retorna o modulo recem carregado."""
    # Remove do cache os modulos relacionados que leem env em import-time
    for mod_name in list(sys.modules.keys()):
        if mod_name == "api.main" or mod_name.startswith("api.main."):
            del sys.modules[mod_name]
    return importlib.import_module("api.main")


def _get_cors_options(app) -> dict:
    """Extrai as options do CORSMiddleware da lista de middlewares da app."""
    for mw in app.user_middleware:
        if mw.cls is CORSMiddleware:
            # Starlette >=0.35 armazena em mw.kwargs; versoes anteriores em mw.options
            return getattr(mw, "kwargs", None) or getattr(mw, "options", {})
    raise AssertionError("CORSMiddleware nao encontrado em app.user_middleware")


class TestCorsConfig:
    def test_cors_does_not_use_wildcard_with_credentials(self, monkeypatch):
        """Bug #2: allow_origins=['*'] + allow_credentials=True e invalido por spec."""
        monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
        mod = _reload_api_main()
        opts = _get_cors_options(mod.app)

        if opts.get("allow_credentials"):
            assert opts.get("allow_origins") != ["*"], (
                "CORS: allow_origins=['*'] com allow_credentials=True viola spec CORS"
            )

    def test_cors_reads_allowed_origins_from_env(self, monkeypatch):
        monkeypatch.setenv(
            "ALLOWED_ORIGINS", "https://a.example.com,https://b.example.com"
        )
        mod = _reload_api_main()
        opts = _get_cors_options(mod.app)

        origins = opts.get("allow_origins") or []
        assert "https://a.example.com" in origins
        assert "https://b.example.com" in origins
        assert len(origins) == 2

    def test_cors_defaults_include_localhost_dev(self, monkeypatch):
        monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
        mod = _reload_api_main()
        opts = _get_cors_options(mod.app)

        origins = opts.get("allow_origins") or []
        assert "http://localhost:5175" in origins, (
            f"Default deveria incluir porta dev 5175, got: {origins}"
        )

    def test_cors_allowed_origins_env_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv(
            "ALLOWED_ORIGINS", "  https://a.example.com , https://b.example.com  "
        )
        mod = _reload_api_main()
        opts = _get_cors_options(mod.app)

        origins = opts.get("allow_origins") or []
        assert "https://a.example.com" in origins
        assert "https://b.example.com" in origins
        # Nao deve conter strings vazias nem com espacos
        assert all(o.strip() == o for o in origins)
        assert all(o for o in origins)
