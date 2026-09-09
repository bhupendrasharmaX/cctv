"""
Access control for the command platform.

This is a deliberately minimal stopgap, not a finished identity design. The
platform previously had no access control of any kind: anyone who could reach
the port could read the camera registry (including RTSP URLs), read the
watchlist with owner names and FIR numbers, add or remove watchlist entries,
and start AI workers.

A single shared token closes that hole for a pilot deployment without
pretending to be per-officer authentication. It gives no audit trail and no
revocation beyond rotating the token, so a real deployment still needs proper
identity -- see docs/PROGRESS.md.

Behaviour:
  * SENTINEL_API_TOKEN unset  -> auth disabled, loud warning at startup.
                                 Local development is unchanged.
  * SENTINEL_API_TOKEN set    -> every /api route except /api/health requires
                                 the token, as does the alert WebSocket.
"""

import logging
import secrets
from typing import Optional

from fastapi import Header, HTTPException, Query, status

from backend.app.config import API_TOKEN

logger = logging.getLogger("cctv.security")


def auth_enabled() -> bool:
    return bool(API_TOKEN)


def _token_matches(candidate: Optional[str]) -> bool:
    if not candidate:
        return False
    # Constant-time comparison: a plain `==` leaks the token's prefix through
    # response timing, which is enough to recover it byte by byte.
    return secrets.compare_digest(candidate, API_TOKEN)


def _extract(authorization: Optional[str], x_api_token: Optional[str]) -> Optional[str]:
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            return value.strip()
    return x_api_token.strip() if x_api_token else None


async def require_token(
    authorization: Optional[str] = Header(default=None),
    x_api_token: Optional[str] = Header(default=None),
) -> None:
    """FastAPI dependency guarding the HTTP API."""
    if not auth_enabled():
        return

    if not _token_matches(_extract(authorization, x_api_token)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid command platform token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def websocket_token_ok(token: Optional[str]) -> bool:
    """
    Browsers cannot set headers on a WebSocket handshake, so the alert stream
    accepts the token as a query parameter instead.
    """
    if not auth_enabled():
        return True
    return _token_matches(token)


def log_auth_status() -> None:
    if auth_enabled():
        logger.info("API token authentication is ENABLED.")
    else:
        logger.warning(
            "SENTINEL_API_TOKEN is not set - the API is UNAUTHENTICATED. "
            "Anyone who can reach this port can read the camera registry and "
            "watchlist and control AI workers. Do not expose this beyond localhost."
        )
