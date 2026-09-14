import mimetypes
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, BinaryIO, cast

import aioboto3
from botocore.exceptions import ClientError

from shared.config import get_settings

ALLOWED_EXTENSIONS: set[str] = {
    "html",
    "css",
    "js",
    "mjs",
    "json",
    "svg",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "ico",
    "woff",
    "woff2",
    "ttf",
    "map",
    "txt",
    "md",
    "xml",
}

# Ensure common web mimetypes are registered
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/ttf", ".ttf")


def is_allowed_extension(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[-1].lower()
    return ext in ALLOWED_EXTENSIONS


def get_content_type(filename: str, fallback: str = "application/octet-stream") -> str:
    content_type, _ = mimetypes.guess_type(filename)
    return content_type or fallback


class R2Client:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.session = aioboto3.Session()

    @asynccontextmanager
    async def _get_client(self) -> AsyncGenerator[Any, None]:
        async with self.session.client(
            "s3",
            endpoint_url=self.settings.r2_endpoint_url,
            aws_access_key_id=self.settings.r2_access_key_id,
            aws_secret_access_key=self.settings.r2_secret_access_key,
            region_name=self.settings.r2_region,
        ) as client:
            yield client

    async def put_object(
        self,
        key: str,
        data: bytes | BinaryIO,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if content_type is None:
            content_type = get_content_type(key)

        kwargs: dict[str, Any] = {
            "Bucket": self.settings.r2_bucket,
            "Key": key,
            "Body": data,
            "ContentType": content_type,
        }
        if metadata:
            kwargs["Metadata"] = metadata

        async with self._get_client() as client:
            response = await client.put_object(**kwargs)
            return cast(dict[str, Any], response)

    async def get_object(self, key: str) -> dict[str, Any] | None:
        try:
            async with self._get_client() as client:
                response = await client.get_object(
                    Bucket=self.settings.r2_bucket,
                    Key=key,
                )
                # Read entire content into memory for simplicity and non-leaking sessions
                # Body in aioboto3 is StreamingBody
                body_bytes = await response["Body"].read()
                return {
                    "body": body_bytes,
                    "content_type": response.get("ContentType", "application/octet-stream"),
                    "content_length": response.get("ContentLength", len(body_bytes)),
                    "etag": response.get("ETag", "").strip('"'),
                    "metadata": response.get("Metadata", {}),
                }
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code in ("NoSuchKey", "404"):
                return None
            raise

    async def delete_object(self, key: str) -> bool:
        try:
            async with self._get_client() as client:
                await client.delete_object(
                    Bucket=self.settings.r2_bucket,
                    Key=key,
                )
                return True
        except ClientError:
            return False

    async def list_objects(self, prefix: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        async with self._get_client() as client:
            paginator = client.get_paginator("list_objects_v2")
            async for page in paginator.paginate(
                Bucket=self.settings.r2_bucket,
                Prefix=prefix,
            ):
                for obj in page.get("Contents", []):
                    results.append(
                        {
                            "key": obj["Key"],
                            "size": obj["Size"],
                            "last_modified": obj.get("LastModified"),
                            "etag": obj.get("ETag", "").strip('"'),
                        }
                    )
        return results

    async def calculate_prefix_size(self, prefix: str) -> int:
        objects = await self.list_objects(prefix)
        return sum(obj["size"] for obj in objects)

    async def delete_objects_by_prefix(self, prefix: str) -> int:
        objects = await self.list_objects(prefix)
        if not objects:
            return 0

        async with self._get_client() as client:
            # S3 batch delete allows max 1000 objects per request
            keys_to_delete = [{"Key": obj["key"]} for obj in objects]
            for i in range(0, len(keys_to_delete), 1000):
                batch = keys_to_delete[i : i + 1000]
                await client.delete_objects(
                    Bucket=self.settings.r2_bucket,
                    Delete={"Objects": batch, "Quiet": True},
                )
        return len(objects)


_r2_client: R2Client | None = None


def get_r2_client() -> R2Client:
    global _r2_client
    if _r2_client is None:
        _r2_client = R2Client()
    return _r2_client
