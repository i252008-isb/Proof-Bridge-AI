from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Evidence, User
from app.schemas import EvidenceResponse
from app.security import (
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER,
    require_role
)
from app.services.file_storage import (
    UPLOAD_KIND_EVIDENCE,
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
    get_project_or_404
)


router = APIRouter(
    prefix="/projects/{project_id}/evidence",
    tags=["Evidence"]
)

freelancer_only = require_role(ROLE_FREELANCER)

project_reader = require_role(
    ROLE_CLIENT,
    ROLE_FREELANCER,
    ROLE_REVIEWER
)


@router.post(
    "",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED
)
def upload_evidence(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(freelancer_only)
):
    project = get_project_or_404(db, project_id)

    if project.freelancer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the project's assigned freelancer can upload evidence."
        )

    ensure_project_mutable(project)

    data = read_upload_bytes(file)
    detected = detect_upload_type(data)
    display_name = sanitize_filename(file.filename, detected.extension)

    stored_path = store_upload(
        data,
        UPLOAD_KIND_EVIDENCE,
        project.id,
        detected.extension
    )

    evidence = Evidence(
        project_id=project.id,
        uploaded_by=current_user.id,
        filename=display_name,
        stored_path=stored_path,
        mime_type=detected.mime_type
    )

    db.add(evidence)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        delete_stored_file(stored_path)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Evidence could not be saved for this project."
        )
    except Exception:
        db.rollback()
        delete_stored_file(stored_path)
        raise

    db.refresh(evidence)

    return evidence


@router.get("", response_model=list[EvidenceResponse])
def list_evidence(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader)
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    return (
        db.query(Evidence)
        .filter(Evidence.project_id == project.id)
        .order_by(Evidence.id)
        .all()
    )


@router.get("/{evidence_id}/download")
def download_evidence(
    project_id: int,
    evidence_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(project_reader)
):
    project = get_project_or_404(db, project_id)
    ensure_project_access(project, current_user)

    evidence = db.get(Evidence, evidence_id)

    if evidence is None or evidence.project_id != project.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence not found."
        )

    path = resolve_stored_path(evidence.stored_path)

    return FileResponse(
        path=path,
        media_type=media_type_for(evidence.stored_path, evidence.mime_type),
        filename=download_filename(
            evidence.filename,
            evidence.stored_path
        ),
        headers={"X-Content-Type-Options": "nosniff"}
    )
