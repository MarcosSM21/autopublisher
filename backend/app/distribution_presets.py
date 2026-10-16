"""Destination presets: named sets of accounts of a project (Feature 017).

A preset stores only its name and destinations. Applying one is done by the client,
which already knows which accounts are selectable for a content.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_session, utc_now
from app.errors import ConflictError, FieldErrorEntry, NotFoundError, field_errors
from app.models import Account, DistributionPreset, DistributionPresetAccount
from app.normalization import normalize_key
from app.projects import get_project_or_404
from app.schemas import (
    DistributionPresetCreate,
    DistributionPresetRead,
    DistributionPresetUpdate,
)

router = APIRouter(prefix="/api", tags=["distribution-presets"])

SessionDep = Annotated[Session, Depends(get_session)]


def get_preset_or_404(session: Session, preset_id: int) -> DistributionPreset:
    preset = session.get(DistributionPreset, preset_id)
    if preset is None:
        raise NotFoundError("Preset not found.")
    return preset


def ensure_preset_name_available(
    session: Session, project_id: int, name_key: str, exclude_id: int | None = None
) -> None:
    query = select(DistributionPreset.id).where(
        DistributionPreset.project_id == project_id,
        DistributionPreset.name_key == name_key,
    )
    if exclude_id is not None:
        query = query.where(DistributionPreset.id != exclude_id)
    if session.scalars(query).first() is not None:
        raise ConflictError(
            "duplicate", "A preset with this name already exists.", field="name"
        )


def _validate_accounts(
    session: Session, project_id: int, account_ids: list[int]
) -> None:
    """Every account must exist and belong to the project (inactive ones are
    allowed: they are skipped when the preset is applied)."""
    projects = {
        account_id: account_project_id
        for account_id, account_project_id in session.execute(
            select(Account.id, Account.project_id).where(Account.id.in_(account_ids))
        )
    }
    problems: list[FieldErrorEntry] = []
    for account_id in account_ids:
        if account_id not in projects:
            problems.append(
                ("account_ids", f"Account {account_id} not found.", account_id)
            )
        elif projects[account_id] != project_id:
            problems.append(
                (
                    "account_ids",
                    f"Account {account_id} does not belong to this project.",
                    account_id,
                )
            )
    if problems:
        raise field_errors(problems)


def _account_ids(session: Session, preset_id: int) -> list[int]:
    return list(
        session.scalars(
            select(DistributionPresetAccount.account_id)
            .where(DistributionPresetAccount.preset_id == preset_id)
            .order_by(DistributionPresetAccount.account_id)
        )
    )


def _set_accounts(session: Session, preset_id: int, account_ids: list[int]) -> None:
    session.execute(
        delete(DistributionPresetAccount).where(
            DistributionPresetAccount.preset_id == preset_id
        )
    )
    session.add_all(
        DistributionPresetAccount(preset_id=preset_id, account_id=account_id)
        for account_id in account_ids
    )


def _preset_read(
    session: Session, preset: DistributionPreset
) -> DistributionPresetRead:
    return DistributionPresetRead(
        id=preset.id,
        project_id=preset.project_id,
        name=preset.name,
        account_ids=_account_ids(session, preset.id),
        created_at=preset.created_at,
        updated_at=preset.updated_at,
    )


@router.get(
    "/projects/{project_id}/distribution-presets",
    response_model=list[DistributionPresetRead],
)
def list_presets(project_id: int, session: SessionDep) -> list[DistributionPresetRead]:
    get_project_or_404(session, project_id)
    presets = session.scalars(
        select(DistributionPreset)
        .where(DistributionPreset.project_id == project_id)
        .order_by(DistributionPreset.name_key)
    )
    return [_preset_read(session, preset) for preset in presets]


@router.post(
    "/projects/{project_id}/distribution-presets",
    response_model=DistributionPresetRead,
    status_code=status.HTTP_201_CREATED,
)
def create_preset(
    project_id: int, body: DistributionPresetCreate, session: SessionDep
) -> DistributionPresetRead:
    get_project_or_404(session, project_id)
    name_key = normalize_key(body.name)
    ensure_preset_name_available(session, project_id, name_key)
    _validate_accounts(session, project_id, body.account_ids)
    now = utc_now()
    preset = DistributionPreset(
        project_id=project_id,
        name=body.name,
        name_key=name_key,
        created_at=now,
        updated_at=now,
    )
    session.add(preset)
    session.flush()
    _set_accounts(session, preset.id, body.account_ids)
    session.commit()
    return _preset_read(session, preset)


@router.patch(
    "/distribution-presets/{preset_id}", response_model=DistributionPresetRead
)
def update_preset(
    preset_id: int, body: DistributionPresetUpdate, session: SessionDep
) -> DistributionPresetRead:
    """Apply only effective changes; `account_ids` replaces the whole set."""
    preset = get_preset_or_404(session, preset_id)
    changed = False
    if body.name is not None and body.name != preset.name:
        name_key = normalize_key(body.name)
        ensure_preset_name_available(
            session, preset.project_id, name_key, exclude_id=preset.id
        )
        preset.name = body.name
        preset.name_key = name_key
        changed = True
    if body.account_ids is not None and sorted(body.account_ids) != _account_ids(
        session, preset.id
    ):
        _validate_accounts(session, preset.project_id, body.account_ids)
        _set_accounts(session, preset.id, body.account_ids)
        changed = True
    if changed:
        preset.updated_at = utc_now()
        session.commit()
    return _preset_read(session, preset)


@router.delete(
    "/distribution-presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_preset(preset_id: int, session: SessionDep) -> Response:
    """Deletes the preset and its destinations; accounts and publications stay."""
    preset = get_preset_or_404(session, preset_id)
    session.delete(preset)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
