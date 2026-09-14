from cloudflare import AsyncCloudflare

from shared.config import get_settings
from src.api.services.cloudflare.exceptions import CloudflareAuthenticationError


def get_async_cloudflare_client(api_token: str | None = None) -> AsyncCloudflare:
    """Creates or returns an AsyncCloudflare client instance.

    Uses CLOUDFLARE_API_TOKEN from settings if token is not provided explicitly.
    Raises CloudflareAuthenticationError if no token is configured.
    """
    settings = get_settings()
    token = api_token or settings.cloudflare_api_token
    if not token:
        raise CloudflareAuthenticationError(
            "Cloudflare API token is not configured. Set CLOUDFLARE_API_TOKEN in the environment."
        )

    return AsyncCloudflare(api_token=token)
