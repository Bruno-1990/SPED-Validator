"""Teste de thread-safety do cache _corrigivel_cache (bug #7).

O cache global dict era inicializado sem lock. O bug real: thread A faz
`_corrigivel_cache = {}` ANTES de `load_all_rules()` (que e lento). Thread B
chegando entre esses dois passos ve `{}` (nao None), pula o bloco de inicializacao
e le do dict vazio, retornando "proposta" (default) em vez do valor real da regra.
"""

from __future__ import annotations

import threading
import time

import pytest

import src.services.correction_service as cs


class _FakeLoader:
    """Loader controlado que retorna regras previsiveis com atraso."""
    def __init__(self):
        self.call_count = 0

    def load_all_rules(self):
        self.call_count += 1
        time.sleep(0.1)  # forca outras threads a entrarem no bloco
        return [
            {"id": "TEST_RULE", "corrigivel": "automatico"},
            {"id": "OTHER_RULE", "corrigivel": "investigar"},
        ]


class TestCorrigivelCacheThreadSafety:
    def test_concurrent_cold_access_returns_real_value_not_default(self, monkeypatch):
        """Bug #7: sem lock, threads chegando durante load_all_rules veem cache vazio
        e retornam 'proposta' (default) em vez de 'automatico' (valor real da regra)."""
        cs._corrigivel_cache = None

        fake = _FakeLoader()
        # Substitui o RuleLoader() dentro de _get_corrigivel
        monkeypatch.setattr(cs, "RuleLoader", lambda: fake)

        N = 20
        barrier = threading.Barrier(N)
        results: list[str] = [""] * N

        def worker(i: int) -> None:
            barrier.wait()
            results[i] = cs._get_corrigivel("TEST_RULE")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Com lock: TODAS as threads veem cache populado -> "automatico"
        # Sem lock (bug): algumas threads veem cache={} e retornam "proposta"
        assert all(r == "automatico" for r in results), (
            f"Race condition: nem todas as threads obtiveram o valor real. "
            f"Resultados: {results.count('automatico')}x automatico, "
            f"{results.count('proposta')}x proposta (default de dict vazio)"
        )

        # Com lock: loader e chamado 1 vez. Sem lock: pode ser chamado varias vezes.
        assert fake.call_count == 1, (
            f"RuleLoader.load_all_rules foi chamado {fake.call_count} vezes, "
            f"esperado 1 (cache deveria ser compartilhado)"
        )

    def test_subsequent_access_does_not_reload(self, monkeypatch):
        """Apos cache populado, chamadas seguintes nao invocam loader."""
        cs._corrigivel_cache = {"FOO": "automatico"}

        fake = _FakeLoader()
        monkeypatch.setattr(cs, "RuleLoader", lambda: fake)

        for _ in range(10):
            assert cs._get_corrigivel("FOO") == "automatico"

        assert fake.call_count == 0
