"""Rate limiter com janela deslizante em memória.

Limita requisições por IP nos endpoints críticos da API.
Thread-safe para uso com FastAPI (múltiplos workers na mesma thread).

NOTA: Em deployment com múltiplos processos (gunicorn multiprocessing),
use Redis-backed rate limiter em vez desta implementação.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class SlidingWindowRateLimiter:
    """Rate limiter com janela deslizante em memória."""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def is_allowed(self, client_id: str) -> tuple[bool, int]:
        """Verifica se a requisição é permitida.

        Returns:
            (allowed, retry_after_seconds)
        """
        now = time.time()
        window_start = now - self.window_seconds

        with self._lock:
            requests = self._requests[client_id]
            while requests and requests[0] < window_start:
                requests.popleft()

            if len(requests) >= self.max_requests:
                retry_after = int(requests[0] + self.window_seconds - now) + 1
                return False, retry_after

            requests.append(now)
            return True, 0


# Instâncias por tipo de endpoint
_upload_limiter = SlidingWindowRateLimiter(max_requests=10, window_seconds=60)
_validation_limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60)


def _api_rate_limit_disabled() -> bool:
    """Pytest / ambiente de CI: evita 429 em sequências longas de uploads/validações."""
    v = (os.environ.get("DISABLE_API_RATE_LIMIT") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def get_client_id(request: Request) -> str:
    """Extrai identificador do cliente (IP real, considerando proxies)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_upload_rate_limit(request: Request) -> None:
    if _api_rate_limit_disabled():
        return
    client_id = get_client_id(request)
    allowed, retry_after = _upload_limiter.is_allowed(client_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "RATE_LIMIT_EXCEEDED",
                "message": f"Limite de uploads excedido. Máximo: {_upload_limiter.max_requests} por minuto.",
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )


def check_validation_rate_limit(request: Request) -> None:
    if _api_rate_limit_disabled():
        return
    client_id = get_client_id(request)
    allowed, retry_after = _validation_limiter.is_allowed(client_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "RATE_LIMIT_EXCEEDED",
                "message": f"Limite de validações excedido. Máximo: {_validation_limiter.max_requests} por minuto.",
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )
