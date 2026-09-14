import logging
from typing import Any, Literal

from cloudflare import AsyncCloudflare
from pydantic import BaseModel

from shared.config import get_settings
from src.api.services.cloudflare.client import get_async_cloudflare_client
from src.api.services.cloudflare.exceptions import (
    CloudflareNotFoundError,
    CloudflareValidationError,
    map_cloudflare_exception,
)

logger = logging.getLogger("bdhost.cloudflare.dns")

RecordType = Literal[
    "A",
    "AAAA",
    "CNAME",
    "MX",
    "NS",
    "TXT",
    "SRV",
    "PTR",
    "CAA",
]


class DNSRecordData(BaseModel):
    """Normalized DNS record model decoupled from SDK-specific response classes."""

    id: str
    name: str
    type: str
    content: str
    ttl: int
    proxied: bool
    zone_id: str | None = None


class CloudflareDNSService:
    """Service abstraction for Cloudflare DNS management."""

    def __init__(self, client: AsyncCloudflare | None = None) -> None:
        self._client = client

    def _get_client(self) -> AsyncCloudflare:
        if self._client is not None:
            return self._client
        return get_async_cloudflare_client()

    async def create_record(
        self,
        zone_id: str,
        name: str,
        type: str,
        content: str,
        ttl: int = 1,
        proxied: bool = False,
    ) -> DNSRecordData:
        """Creates a DNS record in the specified zone."""
        client = self._get_client()
        logger.info(
            "Creating DNS record: zone_id=%s, name=%s, type=%s, proxied=%s",
            zone_id,
            name,
            type,
            proxied,
        )
        try:
            create_fn: Any = client.dns.records.create
            record = await create_fn(
                zone_id=zone_id,
                name=name,
                type=type,
                content=content,
                ttl=ttl,
                proxied=proxied,
            )
            if not record:
                raise CloudflareValidationError("Cloudflare returned an empty record response.")

            return DNSRecordData(
                id=record.id,
                name=record.name,
                type=record.type,
                content=getattr(record, "content", "") or "",
                ttl=int(getattr(record, "ttl", 1) or 1),
                proxied=bool(getattr(record, "proxied", False)),
                zone_id=getattr(record, "zone_id", zone_id),
            )
        except Exception as e:
            logger.error("Failed to create DNS record %s (%s): %s", name, type, e)
            raise map_cloudflare_exception(e) from e

    async def get_record(self, zone_id: str, record_id: str) -> DNSRecordData:
        """Retrieves a DNS record by ID."""
        client = self._get_client()
        try:
            record = await client.dns.records.get(
                dns_record_id=record_id,
                zone_id=zone_id,
            )
            if not record:
                raise CloudflareNotFoundError(f"DNS record '{record_id}' not found.")

            return DNSRecordData(
                id=record.id,
                name=record.name,
                type=record.type,
                content=getattr(record, "content", "") or "",
                ttl=int(getattr(record, "ttl", 1) or 1),
                proxied=bool(getattr(record, "proxied", False)),
                zone_id=getattr(record, "zone_id", zone_id),
            )
        except Exception as e:
            raise map_cloudflare_exception(e) from e

    async def update_record(
        self,
        zone_id: str,
        record_id: str,
        name: str,
        type: str,
        content: str,
        ttl: int = 1,
        proxied: bool = False,
    ) -> DNSRecordData:
        """Updates an existing DNS record."""
        client = self._get_client()
        logger.info(
            "Updating DNS record: id=%s, zone_id=%s, name=%s, type=%s",
            record_id,
            zone_id,
            name,
            type,
        )
        try:
            update_fn: Any = client.dns.records.update
            record = await update_fn(
                dns_record_id=record_id,
                zone_id=zone_id,
                name=name,
                type=type,
                content=content,
                ttl=ttl,
                proxied=proxied,
            )
            if not record:
                raise CloudflareNotFoundError(f"DNS record '{record_id}' could not be updated.")

            return DNSRecordData(
                id=record.id,
                name=record.name,
                type=record.type,
                content=getattr(record, "content", "") or "",
                ttl=int(getattr(record, "ttl", 1) or 1),
                proxied=bool(getattr(record, "proxied", False)),
                zone_id=getattr(record, "zone_id", zone_id),
            )
        except Exception as e:
            logger.error("Failed to update DNS record %s: %s", record_id, e)
            raise map_cloudflare_exception(e) from e

    async def delete_record(self, zone_id: str, record_id: str) -> bool:
        """Deletes a DNS record by ID."""
        client = self._get_client()
        logger.info("Deleting DNS record: id=%s, zone_id=%s", record_id, zone_id)
        try:
            await client.dns.records.delete(
                dns_record_id=record_id,
                zone_id=zone_id,
            )
            return True
        except Exception as e:
            logger.error("Failed to delete DNS record %s: %s", record_id, e)
            raise map_cloudflare_exception(e) from e

    async def list_records(
        self,
        zone_id: str,
        name: str | None = None,
        type: str | None = None,
    ) -> list[DNSRecordData]:
        """Lists DNS records in the specified zone, with optional name/type filters."""
        client = self._get_client()
        kwargs: dict[str, Any] = {"zone_id": zone_id}
        if name:
            kwargs["name"] = name
        if type:
            kwargs["type"] = type

        try:
            paginator = client.dns.records.list(**kwargs)
            results: list[DNSRecordData] = []

            # Handle both async iterator from SDK and synchronous/mock iterations
            if hasattr(paginator, "__aiter__"):
                async for r in paginator:
                    results.append(
                        DNSRecordData(
                            id=r.id,
                            name=r.name,
                            type=r.type,
                            content=getattr(r, "content", "") or "",
                            ttl=int(getattr(r, "ttl", 1) or 1),
                            proxied=bool(getattr(r, "proxied", False)),
                            zone_id=getattr(r, "zone_id", zone_id),
                        )
                    )
            elif hasattr(paginator, "__iter__"):
                for r in paginator:
                    results.append(
                        DNSRecordData(
                            id=r.id,
                            name=r.name,
                            type=r.type,
                            content=getattr(r, "content", "") or "",
                            ttl=int(getattr(r, "ttl", 1) or 1),
                            proxied=bool(getattr(r, "proxied", False)),
                            zone_id=getattr(r, "zone_id", zone_id),
                        )
                    )
            elif hasattr(paginator, "result") and hasattr(paginator.result, "__iter__"):
                for r in paginator.result:
                    results.append(
                        DNSRecordData(
                            id=r.id,
                            name=r.name,
                            type=r.type,
                            content=getattr(r, "content", "") or "",
                            ttl=int(getattr(r, "ttl", 1) or 1),
                            proxied=bool(getattr(r, "proxied", False)),
                            zone_id=getattr(r, "zone_id", zone_id),
                        )
                    )

            return results
        except Exception as e:
            logger.error("Failed to list DNS records for zone %s: %s", zone_id, e)
            raise map_cloudflare_exception(e) from e

    async def ensure_wildcard_record(
        self,
        zone_id: str | None = None,
        ip: str | None = None,
        proxied: bool = False,
    ) -> DNSRecordData:
        """Ensures the platform wildcard DNS record (*.bdappshub.com) exists.

        Idempotent operation:
        - If an A record for '*' or '*.{base_domain}' already exists, returns it without creating a duplicate.
        - If missing, creates a new A record pointing to app_runtime_ip.
        """
        settings = get_settings()
        zone = zone_id or settings.cloudflare_zone_id
        if not zone:
            raise CloudflareValidationError(
                "Cloudflare zone ID is required. Set CLOUDFLARE_ZONE_ID in settings or pass zone_id."
            )

        target_ip = ip or settings.app_runtime_ip
        if not target_ip:
            raise CloudflareValidationError(
                "App runtime IP is required. Set APP_RUNTIME_IP in settings or pass ip."
            )

        base_domain = settings.base_domain.lower()

        # Check existing A records
        existing = await self.list_records(zone_id=zone, type="A")
        for rec in existing:
            rec_name = rec.name.lower().rstrip(".")
            if rec_name in ("*", f"*.{base_domain}"):
                logger.info(
                    "Wildcard DNS record already exists: id=%s, name=%s, content=%s",
                    rec.id,
                    rec.name,
                    rec.content,
                )
                return rec

        # Create the wildcard record
        logger.info(
            "Wildcard DNS record not found. Creating wildcard record: '*.%s' -> %s",
            base_domain,
            target_ip,
        )
        return await self.create_record(
            zone_id=zone,
            name="*",
            type="A",
            content=target_ip,
            ttl=1,
            proxied=proxied,
        )
