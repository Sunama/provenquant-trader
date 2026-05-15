from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Exact paths or path prefixes that bypass API-key auth
_PUBLIC_EXACT = {"/"}
_PUBLIC_PREFIXES = (
    "/ws",               # WebSocket — public real-time feed
    "/api/market-data",  # OHLCV, orderbook, funding rates — public read-only data
)


def _is_public(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    for prefix in _PUBLIC_PREFIXES:
        if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
            return True
    return False


class APIKeyMiddleware(BaseHTTPMiddleware):
    """
    Requires `Authorization: Bearer <SERVER_SECRET>` on all non-public routes.
    Pass-through: OPTIONS (CORS preflight), /ws, /api/market-data/*, /
    """

    def __init__(self, app, api_key: str) -> None:
        super().__init__(app)
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next):
        # Always let CORS preflight through
        if request.method == "OPTIONS":
            return await call_next(request)

        if not _is_public(request.url.path):
            auth = request.headers.get("Authorization", "")
            if not (auth.startswith("Bearer ") and auth[7:] == self._api_key):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        return await call_next(request)
