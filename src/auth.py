import base64
import json
import logging
import os


from fastapi import Header, HTTPException, status
from dotenv import load_dotenv


logger = logging.getLogger(__name__)


load_dotenv()
_DEV_MODE = os.getenv("DEV_MODE", "").lower() == "true"
_DEV_USER_OID = os.getenv("DEV_USER_OID", "")


async def get_current_user(
    x_ms_client_principal: str | None = Header(default=None),
    x_user_oid: str | None = Header(default=None),
) -> str:
    """FastAPI dependency that returns the authenticated user's OID.

    In production, reads the X-MS-CLIENT-PRINCIPAL header injected by
    Azure Container Apps Easy Auth. The header is base64-encoded JSON
    containing a claims array; we extract the 'oid' claim.

    In dev (DEV_MODE=true), returns DEV_USER_OID from environment if set,
    otherwise falls back to the X-User-OID header.
    """
    if _DEV_MODE:
        if _DEV_USER_OID:
            logger.debug(f"Dev mode: using DEV_USER_OID: {_DEV_USER_OID}")
            return _DEV_USER_OID
        if x_user_oid:
            logger.debug(f"Dev mode: using X-User-OID header: {x_user_oid}")
            return x_user_oid

    if not x_ms_client_principal:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )

    try:
        decoded = base64.b64decode(x_ms_client_principal).decode("utf-8")
        principal = json.loads(decoded)
        claims = {claim["typ"]: claim["val"] for claim in principal.get("claims", [])}
        oid = claims.get("oid")
    except Exception:
        logger.exception("Failed to parse X-MS-CLIENT-PRINCIPAL header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        )

    if not oid:
        logger.error("OID claim missing from principal. Available claims: %s", list(claims.keys()))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        )

    return oid