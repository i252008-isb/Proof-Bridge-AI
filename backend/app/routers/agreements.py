from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import AgreementResponse
from app.security import (
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
    require_role
)
from app.services.file_storage import (
    UPLOAD_KIND_AGREEMENT,
    delete_stored_file,
    detect_upload_type,
    download_filename,
    media_type_for,
    read_upload_bytes,
    resolve_stored_path,
    sanitize_filename,
    store_upload
)
from app.services.project_service import (
    ensure_project_access,
    ensure_project_mutable,
    ensure_project_owner,
    get_project_or_404,
    record_status
)


router = APIRouter(
    prefix="/projects/{project_id}/agreement",
    tags=["Agreements"]
)

client_only = require_role(ROLE_CLIENT)

project_reader = require_role(
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER
)


@router.post(
    "",
    response_model=AgreementResponse,
    status_code=status.HTTP_201_CREATED
)
def upload_agreement(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(client_only)
):
    project = get_project_or_404(db, project_id)
    ensure_project_owner(project, current_user)
    ensure_project_mutable(project)

    data = read_upload_bytes(file)
    detected = detect_upload_type(data)
    display_name = sanitize_filename(file.filename, detected.extension)

    stored_path = store_upload(
        data,
        UPLOAD_KIND_AGREEMENT,
        project.id,
        detected.extension
    )

    previous_path = project.agreement_path
    project.agreement_path = stored_path
    project.agreement_name = display_name

    record_status(
        db,
        project.id,
        project.status,
        current_user.id,
        "Agreement file uploaded."
    )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        delete_stored_file(stored_path)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agreement could not be saved for this project."
        )
    except Exception:
        db.rollback()
        delete_stored_file(stored_path)
        raise

    db.refresh(project)

    if previous_path and previous_path != stored_path:
        delete_stored_file(previous_path)

    return AgreementResponse(
        project_id=project.id,
        agreement_name=display_name,
        mime_type=detected.mime_type,
        size_bytes=len(data),
        replaced_existing=previous_path is not None
    )


@router.get("/download")
def download_agreement(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader)
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    if not project.agreement_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No agreement file has been uploaded for this project."
        )

    path = resolve_stored_path(project.agreement_path)

    return FileResponse(
        path=path,
        media_type=media_type_for(project.agreement_path, None),
        filename=download_filename(
            project.agreement_name,
            project.agreement_path
        ),
        headers={"X-Content-Type-Options": "nosniff"}
    )
