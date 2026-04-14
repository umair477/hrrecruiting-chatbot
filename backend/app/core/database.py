from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
import json
import logging
from typing import Any

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, delete, insert, inspect, select, text
from sqlmodel import Session, SQLModel, create_engine

from backend.app.core.config import settings


logger = logging.getLogger(__name__)

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, echo=False, connect_args=connect_args)

CHECKPOINT_NAMESPACE = "leave_management"

checkpoint_metadata = MetaData()
checkpoints_table = Table(
    "checkpoints",
    checkpoint_metadata,
    Column("thread_id", String, primary_key=True),
    Column("checkpoint_ns", String, primary_key=True, default=CHECKPOINT_NAMESPACE),
    Column("checkpoint_id", String, nullable=False),
    Column("workflow", String, nullable=False),
    Column("state", Text, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)
checkpoint_writes_table = Table(
    "checkpoint_writes",
    checkpoint_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("thread_id", String, nullable=False, index=True),
    Column("checkpoint_ns", String, nullable=False),
    Column("checkpoint_id", String, nullable=False),
    Column("workflow", String, nullable=False),
    Column("event_type", String, nullable=False),
    Column("payload", Text, nullable=False),
    Column("created_at", DateTime, nullable=False),
)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
    checkpoint_metadata.create_all(engine)
    _ensure_employee_auth_columns()
    _ensure_leave_schema_columns()
    _ensure_candidate_interview_columns()
    _migrate_leave_statuses()
    _migrate_user_roles()


def _ensure_employee_auth_columns() -> None:
    inspector = inspect(engine)
    try:
        employee_columns = {column["name"] for column in inspector.get_columns("employee")}
    except Exception:
        logger.exception("Database Error: failed to inspect employee table for auth columns.")
        return

    employee_missing = {
        "full_name": "TEXT NOT NULL DEFAULT ''",
        "official_email": "TEXT NOT NULL DEFAULT ''",
        "designation": "TEXT NOT NULL DEFAULT ''",
        "date_of_joining": "DATE",
        "password_hash": "TEXT",
        "is_active": "BOOLEAN NOT NULL DEFAULT TRUE",
        "failed_login_attempts": "INTEGER NOT NULL DEFAULT 0",
        "locked_until": "TIMESTAMP",
        "last_login_at": "TIMESTAMP",
    }

    try:
        with engine.begin() as connection:
            for column_name, definition in employee_missing.items():
                if column_name not in employee_columns:
                    connection.execute(text(f"ALTER TABLE employee ADD COLUMN {column_name} {definition}"))

            connection.execute(
                text(
                    """
                    UPDATE employee
                    SET full_name = name
                    WHERE COALESCE(full_name, '') = ''
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE employee
                    SET date_of_joining = CURRENT_DATE
                    WHERE date_of_joining IS NULL
                    """
                )
            )
    except Exception:
        logger.exception("Database Error: failed to add missing employee auth columns.")


def _ensure_leave_schema_columns() -> None:
    inspector = inspect(engine)
    try:
        employee_columns = {column["name"] for column in inspector.get_columns("employee")}
        leave_columns = {column["name"] for column in inspector.get_columns("leaverequest")}
    except Exception:
        logger.exception("Database Error: failed to inspect leave-related tables for missing columns.")
        return

    employee_missing = {
        "annual_allowance": "FLOAT NOT NULL DEFAULT 20",
    }
    leave_missing = {
        "handover_contact": "TEXT NOT NULL DEFAULT ''",
        "leave_type": "VARCHAR NOT NULL DEFAULT 'Annual'",
        "total_days": "INTEGER NOT NULL DEFAULT 1",
        "hr_note": "TEXT NOT NULL DEFAULT ''",
        "submitted_at": "TIMESTAMP",
    }

    try:
        with engine.begin() as connection:
            for column_name, definition in employee_missing.items():
                if column_name not in employee_columns:
                    connection.execute(text(f"ALTER TABLE employee ADD COLUMN {column_name} {definition}"))
            for column_name, definition in leave_missing.items():
                if column_name not in leave_columns:
                    connection.execute(text(f"ALTER TABLE leaverequest ADD COLUMN {column_name} {definition}"))
    except Exception:
        logger.exception("Database Error: failed to add missing leave schema columns.")


def _ensure_candidate_interview_columns() -> None:
    inspector = inspect(engine)
    try:
        columns = {column["name"] for column in inspector.get_columns("candidate")}
    except Exception:
        logger.exception("Database Error: failed to inspect candidate table for interview session columns.")
        return

    definitions = _candidate_column_definitions()
    missing_columns = [name for name in definitions if name not in columns]
    if not missing_columns:
        return

    try:
        with engine.begin() as connection:
            for column_name in missing_columns:
                connection.execute(text(f"ALTER TABLE candidate ADD COLUMN {column_name} {definitions[column_name]}"))
    except Exception:
        logger.exception("Database Error: failed to add missing candidate interview columns.")


def _candidate_column_definitions() -> dict[str, str]:
    is_sqlite = settings.database_url.startswith("sqlite")
    json_array_default = "TEXT NOT NULL DEFAULT '[]'" if is_sqlite else "JSON NOT NULL DEFAULT '[]'"
    interview_status_default = (
        "VARCHAR NOT NULL DEFAULT 'pending'"
        if is_sqlite
        else "VARCHAR NOT NULL DEFAULT 'pending'"
    )
    return {
        "first_name": "TEXT NOT NULL DEFAULT ''",
        "last_name": "TEXT NOT NULL DEFAULT ''",
        "job_id": "INTEGER",
        "job_description": "TEXT NOT NULL DEFAULT ''",
        "cv_summary": "TEXT NOT NULL DEFAULT ''",
        "resume_score": "INTEGER NOT NULL DEFAULT 0",
        "interview_score": "INTEGER NOT NULL DEFAULT 0",
        "skim_insights": json_array_default,
        "screening_questions": json_array_default,
        "raw_answers": json_array_default,
        "interview_status": interview_status_default,
        "current_question_index": "INTEGER NOT NULL DEFAULT 0",
    }


def _migrate_leave_statuses() -> None:
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE leaverequest
                    SET status = 'REJECTED'
                    WHERE status::text = 'DENIED'
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE leaverequest
                    SET submitted_at = created_at
                    WHERE submitted_at IS NULL
                    """
                )
            )
    except Exception:
        logger.exception("Database Error: failed to migrate leave request statuses.")


def _migrate_user_roles() -> None:
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE "user"
                    SET role = 'EMPLOYEE'
                    WHERE role::text = 'USER' AND employee_id IS NOT NULL
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE "user"
                    SET role = 'CANDIDATE'
                    WHERE role::text = 'USER' AND candidate_id IS NOT NULL AND employee_id IS NULL
                    """
                )
            )
    except Exception:
        logger.exception("Database Error: failed to migrate legacy USER roles to EMPLOYEE/CANDIDATE.")


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def has_checkpoint(
    thread_id: str,
    *,
    workflow: str,
    checkpoint_ns: str = CHECKPOINT_NAMESPACE,
) -> bool:
    statement = (
        select(checkpoints_table.c.thread_id)
        .where(checkpoints_table.c.thread_id == thread_id)
        .where(checkpoints_table.c.workflow == workflow)
        .where(checkpoints_table.c.checkpoint_ns == checkpoint_ns)
        .limit(1)
    )
    try:
        with engine.begin() as connection:
            return connection.execute(statement).first() is not None
    except Exception:
        logger.exception(
            "Persistence Error: failed to read checkpoint availability for thread_id=%s workflow=%s",
            thread_id,
            workflow,
        )
        return False


def load_checkpoint(
    thread_id: str,
    *,
    workflow: str,
    checkpoint_ns: str = CHECKPOINT_NAMESPACE,
) -> dict[str, Any] | None:
    statement = (
        select(checkpoints_table.c.state)
        .where(checkpoints_table.c.thread_id == thread_id)
        .where(checkpoints_table.c.workflow == workflow)
        .where(checkpoints_table.c.checkpoint_ns == checkpoint_ns)
        .limit(1)
    )
    try:
        with engine.begin() as connection:
            row = connection.execute(statement).mappings().first()
    except Exception:
        logger.exception(
            "Persistence Error: failed to load checkpoint for thread_id=%s workflow=%s",
            thread_id,
            workflow,
        )
        return None

    if row is None:
        return None

    try:
        return json.loads(str(row["state"]))
    except Exception:
        logger.exception(
            "Persistence Error: checkpoint payload was invalid for thread_id=%s workflow=%s",
            thread_id,
            workflow,
        )
        return None


def save_checkpoint(
    thread_id: str,
    *,
    workflow: str,
    state: dict[str, Any],
    event_type: str = "upsert",
    checkpoint_ns: str = CHECKPOINT_NAMESPACE,
) -> str:
    checkpoint_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    timestamp = datetime.utcnow()
    state_payload = json.dumps(state, default=str)
    write_payload = json.dumps({"workflow": workflow, "state": state}, default=str)

    try:
        with engine.begin() as connection:
            connection.execute(
                delete(checkpoints_table)
                .where(checkpoints_table.c.thread_id == thread_id)
                .where(checkpoints_table.c.workflow == workflow)
                .where(checkpoints_table.c.checkpoint_ns == checkpoint_ns)
            )
            connection.execute(
                insert(checkpoints_table).values(
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                    checkpoint_id=checkpoint_id,
                    workflow=workflow,
                    state=state_payload,
                    updated_at=timestamp,
                )
            )
            connection.execute(
                insert(checkpoint_writes_table).values(
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                    checkpoint_id=checkpoint_id,
                    workflow=workflow,
                    event_type=event_type,
                    payload=write_payload,
                    created_at=timestamp,
                )
            )
    except Exception:
        logger.exception(
            "Persistence Error: failed to write checkpoint for thread_id=%s workflow=%s",
            thread_id,
            workflow,
        )
        raise

    return checkpoint_id


def clear_checkpoint(
    thread_id: str,
    *,
    workflow: str,
    checkpoint_ns: str = CHECKPOINT_NAMESPACE,
) -> None:
    checkpoint_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    timestamp = datetime.utcnow()

    try:
        with engine.begin() as connection:
            connection.execute(
                insert(checkpoint_writes_table).values(
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                    checkpoint_id=checkpoint_id,
                    workflow=workflow,
                    event_type="delete",
                    payload=json.dumps({"workflow": workflow, "cleared": True}),
                    created_at=timestamp,
                )
            )
            connection.execute(
                delete(checkpoints_table)
                .where(checkpoints_table.c.thread_id == thread_id)
                .where(checkpoints_table.c.workflow == workflow)
                .where(checkpoints_table.c.checkpoint_ns == checkpoint_ns)
            )
    except Exception:
        logger.exception(
            "Persistence Error: failed to clear checkpoint for thread_id=%s workflow=%s",
            thread_id,
            workflow,
        )
        raise
