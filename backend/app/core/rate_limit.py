from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from app.core.config import settings


class LocalRateLimitMiddleware:
    """Small per-process abuse limit; use a shared edge limiter for multi-instance deployments."""

    def __init__(self, app):
        self.app = app
        self._lock = Lock()
        self._requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        if method == "OPTIONS" or path == "/health":
            await self.app(scope, receive, send)
            return
        content_length = next((value for key, value in scope.get("headers", []) if key.lower() == b"content-length"), None)
        if content_length is not None:
            try:
                if int(content_length) > 65_536:
                    body = b'{"detail":"Request body is too large"}'
                    await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                    await send({"type": "http.response.body", "body": body})
                    return
            except ValueError:
                body = b'{"detail":"Invalid Content-Length"}'
                await send({"type": "http.response.start", "status": 400, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        client = scope.get("client")
        peer = client[0] if client else "unknown"
        category = "login" if path == "/api/auth/login" else "api"
        limit = settings.login_rate_limit_per_minute if category == "login" else settings.api_rate_limit_per_minute
        now = monotonic()
        key = (category, peer)
        with self._lock:
            bucket = self._requests[key]
            while bucket and bucket[0] <= now - 60:
                bucket.popleft()
            if len(bucket) >= limit:
                body = b'{"detail":"Too many requests; try again shortly"}'
                await send({"type": "http.response.start", "status": 429, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"retry-after", b"60")]})
                await send({"type": "http.response.body", "body": body})
                return
            bucket.append(now)
            # Bound memory for long-running processes with many distinct peers.
            if len(self._requests) > 20_000:
                self._requests = defaultdict(deque, {k: v for k, v in self._requests.items() if v and v[-1] > now - 60})
        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {key.lower() for key, _ in headers}
                for key, value in ((b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"), (b"x-frame-options", b"DENY")):
                    if key not in present:
                        headers.append((key, value))
                message = {**message, "headers": headers}
            await send(message)
        await self.app(scope, receive, secure_send)
