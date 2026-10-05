from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session, utc_now
from app.errors import ConflictError, NotFoundError
from app.models import Project
from app.normalization import normalize_key
from app.schemas import ProjectCreate, ProjectRead, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])

SessionDep = Annotated[Session, Depends(get_session)]


def get_project_or_404(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found.")
    return project


def ensure_name_available(
    session: Session, name_key: str, exclude_id: int | None = None
) -> None:
    query = select(Project.id).where(Project.name_key == name_key)
    if exclude_id is not None:
        query = query.where(Project.id != exclude_id)
    if session.scalars(query).first() is not None:
        raise ConflictError(
            "duplicate", "A project with this name already exists.", field="name"
        )


@router.get("", response_model=list[ProjectRead])
def list_projects(session: SessionDep) -> list[Project]:
    return list(session.scalars(select(Project).order_by(Project.name_key)))


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, session: SessionDep) -> Project:
    name_key = normalize_key(body.name)
    ensure_name_available(session, name_key)
    now = utc_now()
    project = Project(
        name=body.name,
        name_key=name_key,
        description=body.description,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    session.add(project)
    session.commit()
    return project


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, session: SessionDep) -> Project:
    return get_project_or_404(session, project_id)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int, body: ProjectUpdate, session: SessionDep
) -> Project:
    """Apply only effective changes; updated_at is kept when nothing changes."""
    project = get_project_or_404(session, project_id)
    fields = body.model_fields_set
    changed = False

    if "name" in fields and body.name is not None and body.name != project.name:
        name_key = normalize_key(body.name)
        ensure_name_available(session, name_key, exclude_id=project.id)
        project.name = body.name
        project.name_key = name_key
        changed = True
    if "description" in fields and body.description != project.description:
        project.description = body.description
        changed = True
    if (
        "is_active" in fields
        and body.is_active is not None
        and body.is_active != project.is_active
    ):
        project.is_active = body.is_active
        changed = True

    if changed:
        project.updated_at = utc_now()
        session.commit()
    return project
