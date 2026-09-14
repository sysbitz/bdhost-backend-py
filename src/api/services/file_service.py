import io
import posixpath
import uuid
import zipfile

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import DeployResponse, FileItemOut, FileListResponse
from api.services.app_service import get_app
from api.services.quota_service import verify_storage_quota
from shared.db.models import User
from shared.storage.r2_client import (
    ALLOWED_EXTENSIONS,
    get_content_type,
    get_r2_client,
    is_allowed_extension,
)

# Zip security limits
MAX_ZIP_FILES = 2000
MAX_ZIP_UNCOMPRESSED_BYTES = 250 * 1024 * 1024  # 250 MB


def sanitize_relative_path(path_str: str) -> str:
    """Normalizes and ensures path is safe, relative, and posix-compliant without leading slashes or '..'"""
    clean_path = posixpath.normpath(path_str.replace("\\", "/"))
    if clean_path.startswith("/") or clean_path.startswith("../") or clean_path == "..":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file path: {path_str}",
        )
    return clean_path.lstrip("./")


async def upload_single_file(
    db: AsyncSession,
    app_id: uuid.UUID | str,
    file: UploadFile,
    relative_path: str | None,
    user: User,
) -> FileItemOut:
    app_uuid = uuid.UUID(str(app_id)) if isinstance(app_id, str) else app_id
    app = await get_app(db, app_uuid, user)

    filename = relative_path or file.filename or "index.html"
    safe_path = sanitize_relative_path(filename)

    if not is_allowed_extension(safe_path):
        ext = safe_path.rsplit(".", 1)[-1] if "." in safe_path else "none"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File extension '.{ext}' is not permitted. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    content = await file.read()
    file_size = len(content)

    # Check quota
    await verify_storage_quota(db, app, file_size)

    r2 = get_r2_client()
    key = f"apps/{app.id}/{safe_path}"
    content_type = get_content_type(safe_path)

    await r2.put_object(
        key=key,
        data=content,
        content_type=content_type,
        metadata={"relative_path": safe_path},
    )

    # Increment app storage
    app.storage_bytes_used += file_size
    await db.commit()

    return FileItemOut(key=safe_path, size=file_size)


async def deploy_zip_archive(
    db: AsyncSession,
    app_id: uuid.UUID | str,
    zip_file: UploadFile,
    user: User,
) -> DeployResponse:
    app_uuid = uuid.UUID(str(app_id)) if isinstance(app_id, str) else app_id
    app = await get_app(db, app_uuid, user)

    content = await zip_file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is not a valid zip archive.",
        )

    infolist = zf.infolist()
    if len(infolist) > MAX_ZIP_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Archive contains too many files (max: {MAX_ZIP_FILES}).",
        )

    # Validation pass before any writes
    total_uncompressed_bytes = 0
    valid_entries: list[tuple[str, zipfile.ZipInfo]] = []

    for info in infolist:
        # Skip directories
        if info.is_dir():
            continue

        raw_name = info.filename
        try:
            safe_name = sanitize_relative_path(raw_name)
        except HTTPException:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Security error: Invalid path inside archive: {raw_name}",
            )

        # Skip macOS or hidden metadata folders
        parts = safe_name.split("/")
        if any(part.startswith(".") or part == "__MACOSX" for part in parts):
            continue

        if not is_allowed_extension(safe_name):
            ext = safe_name.rsplit(".", 1)[-1] if "." in safe_name else "none"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Archive contains disallowed file '{safe_name}' (extension '.{ext}'). Allowed: {sorted(ALLOWED_EXTENSIONS)}",
            )

        total_uncompressed_bytes += info.file_size
        if total_uncompressed_bytes > MAX_ZIP_UNCOMPRESSED_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Archive exceeds maximum decompressed size ({MAX_ZIP_UNCOMPRESSED_BYTES / (1024 * 1024)}MB).",
            )

        valid_entries.append((safe_name, info))

    if not valid_entries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Zip archive contains no valid files to deploy.",
        )

    # Check quota against the total uncompressed bytes before uploading anything
    await verify_storage_quota(db, app, total_uncompressed_bytes)

    # Upload all files
    r2 = get_r2_client()
    for safe_name, info in valid_entries:
        file_bytes = zf.read(info)
        key = f"apps/{app.id}/{safe_name}"
        content_type = get_content_type(safe_name)
        await r2.put_object(
            key=key,
            data=file_bytes,
            content_type=content_type,
            metadata={"relative_path": safe_name},
        )

    # Recompute total storage used from R2
    actual_size = await r2.calculate_prefix_size(f"apps/{app.id}/")
    app.storage_bytes_used = actual_size
    await db.commit()

    return DeployResponse(
        success=True,
        message="Deploy completed successfully.",
        deployed_files=len(valid_entries),
        total_bytes_written=total_uncompressed_bytes,
        storage_bytes_used=actual_size,
    )


async def list_app_files(
    db: AsyncSession,
    app_id: uuid.UUID | str,
    user: User,
) -> FileListResponse:
    app_uuid = uuid.UUID(str(app_id)) if isinstance(app_id, str) else app_id
    app = await get_app(db, app_uuid, user)
    r2 = get_r2_client()
    prefix = f"apps/{app.id}/"
    raw_objects = await r2.list_objects(prefix)

    file_items: list[FileItemOut] = []
    for obj in raw_objects:
        relative_key = obj["key"].removeprefix(prefix)
        file_items.append(
            FileItemOut(
                key=relative_key,
                size=obj["size"],
                last_modified=obj.get("last_modified"),
                etag=obj.get("etag", ""),
            )
        )

    return FileListResponse(
        app_id=app.id,
        storage_bytes_used=app.storage_bytes_used,
        files=file_items,
    )


async def delete_app_file(
    db: AsyncSession,
    app_id: uuid.UUID | str,
    path: str,
    user: User,
) -> bool:
    app_uuid = uuid.UUID(str(app_id)) if isinstance(app_id, str) else app_id
    app = await get_app(db, app_uuid, user)
    safe_path = sanitize_relative_path(path)
    r2 = get_r2_client()
    key = f"apps/{app.id}/{safe_path}"

    deleted = await r2.delete_object(key)
    if deleted:
        # Recalculate storage
        actual_size = await r2.calculate_prefix_size(f"apps/{app.id}/")
        app.storage_bytes_used = actual_size
        await db.commit()

    return deleted
