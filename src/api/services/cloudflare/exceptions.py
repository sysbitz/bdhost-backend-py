from typing import Any

from cloudflare import (
    APIError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)


class CloudflareError(Exception):
    """Base exception for all Cloudflare operations."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details


class CloudflareAuthenticationError(CloudflareError):
    """Raised when authentication with Cloudflare fails (invalid or expired token)."""


class CloudflareNotFoundError(CloudflareError):
    """Raised when a requested Cloudflare resource (zone, DNS record) is not found."""


class CloudflareRateLimitError(CloudflareError):
    """Raised when Cloudflare API rate limit (HTTP 429) is exceeded."""


class CloudflareValidationError(CloudflareError):
    """Raised when request payload or parameters fail Cloudflare validation."""


class CloudflareRecordExistsError(CloudflareError):
    """Raised when a DNS record already exists (HTTP 409 conflict)."""


def map_cloudflare_exception(exc: Exception) -> CloudflareError:
    """Translates raw Cloudflare SDK exceptions into domain-level CloudflareError instances.

    Ensures that secrets and internal SDK objects are not leaked.
    """
    if isinstance(exc, CloudflareError):
        return exc

    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return CloudflareAuthenticationError(
            message="Cloudflare authentication failed. Verify API token and permissions.",
            status_code=getattr(exc, "status_code", 401),
        )

    if isinstance(exc, NotFoundError):
        return CloudflareNotFoundError(
            message="Cloudflare resource not found.",
            status_code=404,
            details=getattr(exc, "body", None),
        )

    if isinstance(exc, RateLimitError):
        return CloudflareRateLimitError(
            message="Cloudflare rate limit exceeded. Please retry later.",
            status_code=429,
        )

    if isinstance(exc, ConflictError):
        return CloudflareRecordExistsError(
            message="Cloudflare DNS record already exists.",
            status_code=409,
            details=getattr(exc, "body", None),
        )

    if isinstance(exc, (BadRequestError, UnprocessableEntityError)):
        return CloudflareValidationError(
            message=f"Cloudflare validation error: {getattr(exc, 'message', str(exc))}",
            status_code=getattr(exc, "status_code", 400),
            details=getattr(exc, "body", None),
        )

    if isinstance(exc, APIError):
        return CloudflareError(
            message=f"Cloudflare API error: {getattr(exc, 'message', str(exc))}",
            status_code=getattr(exc, "status_code", None),
            details=getattr(exc, "body", None),
        )

    return CloudflareError(f"Unexpected Cloudflare error: {str(exc)}")
