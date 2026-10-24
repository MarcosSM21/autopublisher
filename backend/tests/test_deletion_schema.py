"""Completeness guard of the delete order (Feature 021 T015, research §2).

A future table that points at a deletable object must be named in the explicit
delete order; otherwise this test fails before the RESTRICT foreign keys would make
a delete fail at COMMIT.
"""

from app.deletion import CONNECTION_MODELS, POST_ATTEMPT_DEPENDENTS, POST_DEPENDENTS
from app.models import Base

DELETABLE_TABLES = {
    "projects",
    "accounts",
    "contents",
    "publications",
    "publication_attempts",
    "library_folders",
}
# Tables deleted (or detached) by hand in `app.deletion`, or by a deliberate
# `ON DELETE CASCADE` (presets).
HANDLED_TABLES = {
    "accounts",
    "contents",
    "publications",
    "publication_attempts",
    "library_folders",
    "temporary_media_objects",
    "distribution_presets",
    "distribution_preset_accounts",
}


def test_every_dependent_table_is_in_the_delete_order() -> None:
    covered = HANDLED_TABLES | {
        model.__tablename__ for model in (*POST_ATTEMPT_DEPENDENTS, *POST_DEPENDENTS)
    }
    covered |= {model.__tablename__ for _, model in CONNECTION_MODELS}
    dependents = {
        table.name
        for table in Base.metadata.sorted_tables
        for key in table.foreign_keys
        if key.column.table.name in DELETABLE_TABLES
    }

    assert dependents - covered == set()


def test_post_dependents_point_at_publications() -> None:
    for model in (*POST_ATTEMPT_DEPENDENTS, *POST_DEPENDENTS):
        targets = {key.column.table.name for key in model.__table__.foreign_keys}
        assert "publications" in targets, model.__tablename__
