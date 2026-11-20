import hmac

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.settings import Settings

bearer_scheme = HTTPBearer(auto_error=False)


def require_control_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    token = Settings.from_env().control_token
    if not token:
        raise HTTPException(
            status_code=503,
            detail="Set CONTROL_TOKEN to enable protected job and status endpoints.",
        )
    if credentials is None or not hmac.compare_digest(credentials.credentials, token):
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token.")
