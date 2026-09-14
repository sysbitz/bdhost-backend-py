from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from cloudflare import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    RateLimitError,
)

from src.api.services.cloudflare.dns import CloudflareDNSService, DNSRecordData
from src.api.services.cloudflare.exceptions import (
    CloudflareAuthenticationError,
    CloudflareNotFoundError,
    CloudflareRateLimitError,
    CloudflareRecordExistsError,
    CloudflareValidationError,
    map_cloudflare_exception,
)


def _make_dummy_response(status_code: int = 400) -> httpx.Response:
    request = httpx.Request("GET", "https://api.cloudflare.com")
    return httpx.Response(status_code=status_code, request=request)


class MockRecord:
    def __init__(
        self,
        id: str = "rec-123",
        name: str = "test.bdappshub.com",
        type: str = "A",
        content: str = "1.2.3.4",
        ttl: int = 1,
        proxied: bool = False,
        zone_id: str = "zone-abc",
    ) -> None:
        self.id = id
        self.name = name
        self.type = type
        self.content = content
        self.ttl = ttl
        self.proxied = proxied
        self.zone_id = zone_id


@pytest.fixture
def mock_cf_client() -> MagicMock:
    client = MagicMock()
    client.dns = MagicMock()
    client.dns.records = MagicMock()
    return client


@pytest.mark.asyncio
async def test_create_record_success(mock_cf_client: MagicMock) -> None:
    mock_cf_client.dns.records.create = AsyncMock(
        return_value=MockRecord(id="rec-new", name="app.bdappshub.com", content="1.2.3.4")
    )
    service = CloudflareDNSService(client=mock_cf_client)

    rec = await service.create_record(
        zone_id="zone-123",
        name="app.bdappshub.com",
        type="A",
        content="1.2.3.4",
        ttl=1,
        proxied=False,
    )

    assert isinstance(rec, DNSRecordData)
    assert rec.id == "rec-new"
    assert rec.name == "app.bdappshub.com"
    assert rec.content == "1.2.3.4"
    mock_cf_client.dns.records.create.assert_awaited_once_with(
        zone_id="zone-123",
        name="app.bdappshub.com",
        type="A",
        content="1.2.3.4",
        ttl=1,
        proxied=False,
    )


@pytest.mark.asyncio
async def test_get_record_success(mock_cf_client: MagicMock) -> None:
    mock_cf_client.dns.records.get = AsyncMock(
        return_value=MockRecord(id="rec-abc", name="foo.bdappshub.com")
    )
    service = CloudflareDNSService(client=mock_cf_client)

    rec = await service.get_record(zone_id="zone-123", record_id="rec-abc")
    assert rec.id == "rec-abc"
    assert rec.name == "foo.bdappshub.com"
    mock_cf_client.dns.records.get.assert_awaited_once_with(
        dns_record_id="rec-abc",
        zone_id="zone-123",
    )


@pytest.mark.asyncio
async def test_get_record_not_found(mock_cf_client: MagicMock) -> None:
    resp = _make_dummy_response(404)
    mock_cf_client.dns.records.get = AsyncMock(
        side_effect=NotFoundError("Record not found", response=resp, body=None)
    )
    service = CloudflareDNSService(client=mock_cf_client)

    with pytest.raises(CloudflareNotFoundError):
        await service.get_record(zone_id="zone-123", record_id="non-existent")


@pytest.mark.asyncio
async def test_update_record_success(mock_cf_client: MagicMock) -> None:
    mock_cf_client.dns.records.update = AsyncMock(
        return_value=MockRecord(id="rec-up", name="updated.bdappshub.com", content="5.6.7.8")
    )
    service = CloudflareDNSService(client=mock_cf_client)

    rec = await service.update_record(
        zone_id="zone-123",
        record_id="rec-up",
        name="updated.bdappshub.com",
        type="A",
        content="5.6.7.8",
    )
    assert rec.id == "rec-up"
    assert rec.content == "5.6.7.8"
    mock_cf_client.dns.records.update.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_record_success(mock_cf_client: MagicMock) -> None:
    mock_cf_client.dns.records.delete = AsyncMock(return_value=None)
    service = CloudflareDNSService(client=mock_cf_client)

    deleted = await service.delete_record(zone_id="zone-123", record_id="rec-del")
    assert deleted is True
    mock_cf_client.dns.records.delete.assert_awaited_once_with(
        dns_record_id="rec-del",
        zone_id="zone-123",
    )


@pytest.mark.asyncio
async def test_list_records(mock_cf_client: MagicMock) -> None:
    mock_records = [
        MockRecord(id="rec-1", name="app1.bdappshub.com"),
        MockRecord(id="rec-2", name="*.bdappshub.com"),
    ]
    # list returns an iterable
    mock_cf_client.dns.records.list = MagicMock(return_value=mock_records)
    service = CloudflareDNSService(client=mock_cf_client)

    results = await service.list_records(zone_id="zone-123", type="A")
    assert len(results) == 2
    assert results[0].id == "rec-1"
    assert results[1].id == "rec-2"
    mock_cf_client.dns.records.list.assert_called_once_with(zone_id="zone-123", type="A")


@pytest.mark.asyncio
async def test_ensure_wildcard_record_when_already_exists(mock_cf_client: MagicMock) -> None:
    existing_wildcard = MockRecord(
        id="rec-wildcard",
        name="*.bdappshub.com",
        type="A",
        content="127.0.0.1",
    )
    mock_cf_client.dns.records.list = MagicMock(return_value=[existing_wildcard])
    mock_cf_client.dns.records.create = AsyncMock()

    service = CloudflareDNSService(client=mock_cf_client)
    res = await service.ensure_wildcard_record(zone_id="zone-123", ip="127.0.0.1")

    assert res.id == "rec-wildcard"
    assert res.name == "*.bdappshub.com"
    # Verify create was NOT called (idempotent!)
    mock_cf_client.dns.records.create.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_wildcard_record_when_missing(mock_cf_client: MagicMock) -> None:
    mock_cf_client.dns.records.list = MagicMock(return_value=[])
    created_wildcard = MockRecord(
        id="rec-new-wildcard",
        name="*",
        type="A",
        content="198.51.100.1",
    )
    mock_cf_client.dns.records.create = AsyncMock(return_value=created_wildcard)

    service = CloudflareDNSService(client=mock_cf_client)
    res = await service.ensure_wildcard_record(zone_id="zone-123", ip="198.51.100.1")

    assert res.id == "rec-new-wildcard"
    assert res.name == "*"
    assert res.content == "198.51.100.1"
    mock_cf_client.dns.records.create.assert_awaited_once_with(
        zone_id="zone-123",
        name="*",
        type="A",
        content="198.51.100.1",
        ttl=1,
        proxied=False,
    )


def test_exception_mapping() -> None:
    resp401 = _make_dummy_response(401)
    resp404 = _make_dummy_response(404)
    resp409 = _make_dummy_response(409)
    resp429 = _make_dummy_response(429)
    resp400 = _make_dummy_response(400)

    auth_err = map_cloudflare_exception(
        AuthenticationError("Invalid token", response=resp401, body=None)
    )
    assert isinstance(auth_err, CloudflareAuthenticationError)

    not_found_err = map_cloudflare_exception(
        NotFoundError("Not found", response=resp404, body=None)
    )
    assert isinstance(not_found_err, CloudflareNotFoundError)

    conflict_err = map_cloudflare_exception(
        ConflictError("Already exists", response=resp409, body=None)
    )
    assert isinstance(conflict_err, CloudflareRecordExistsError)

    rate_limit_err = map_cloudflare_exception(
        RateLimitError("Too many requests", response=resp429, body=None)
    )
    assert isinstance(rate_limit_err, CloudflareRateLimitError)

    val_err = map_cloudflare_exception(
        BadRequestError("Bad parameter", response=resp400, body=None)
    )
    assert isinstance(val_err, CloudflareValidationError)
