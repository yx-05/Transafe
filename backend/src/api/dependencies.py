"""API Security and Authentication dependencies."""

import os

from fastapi import Header, HTTPException, status


async def verify_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> str:
    """Verify standard User API key header.

    Args:
        x_api_key: Value of the X-API-Key request header.

    Returns:
        The valid API key string.

    Raises:
        HTTPException 401: If header is missing or invalid.
    """
    expected_key = os.getenv("API_KEY", "transafe-hackathon-key-2026")
    if not x_api_key or x_api_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "UNAUTHORIZED",
                "message": "Missing or invalid X-API-Key header",
            },
        )
    return x_api_key


async def verify_admin_key(
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
) -> str:
    """Verify Admin API key header.

    Args:
        x_admin_key: Value of the X-Admin-Key request header.

    Returns:
        The valid Admin API key string.

    Raises:
        HTTPException 401: If header is missing or invalid.
    """
    expected_key = os.getenv("ADMIN_API_KEY", "transafe-admin-key-2026")
    if not x_admin_key or x_admin_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "UNAUTHORIZED",
                "message": "Missing or invalid X-Admin-Key header",
            },
        )
    return x_admin_key
