import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import User
from src.api.deps import get_current_user, get_db
from src.api.schemas import DeployResponse, FileItemOut, FileListResponse
from src.api.services.file_service import (
    delete_app_file,
    deploy_zip_archive,
    list_app_files,
    upload_single_file,
)

router = APIRouter(prefix="/apps/{app_id}", tags=["files"])


@router.post("/files", response_model=FileItemOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    app_id: uuid.UUID,
    file: UploadFile = File(...),
    path: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileItemOut:
    return await upload_single_file(
        db=db,
        app_id=str(app_id),
        file=file,
        relative_path=path,
        user=current_user,
    )


@router.post("/deploy", response_model=DeployResponse)
async def deploy_zip(
    app_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeployResponse:
    return await deploy_zip_archive(
        db=db,
        app_id=str(app_id),
        zip_file=file,
        user=current_user,
    )


@router.get("/files", response_model=FileListResponse)
async def get_files(
    app_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileListResponse:
    return await list_app_files(
        db=db,
        app_id=str(app_id),
        user=current_user,
    )


@router.delete("/files", status_code=status.HTTP_204_NO_CONTENT)
async def remove_file(
    app_id: uuid.UUID,
    path: str = Query(..., description="Relative path of the file to delete"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    await delete_app_file(
        db=db,
        app_id=str(app_id),
        path=path,
        user=current_user,
    )
