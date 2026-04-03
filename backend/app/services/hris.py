from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from backend.app.models import Employee


SUPPORTED_HRIS_PROVIDERS = {"workday", "bamboohr"}


def get_provider_status() -> list[dict[str, object]]:
    return [
        {
            "provider": "workday",
            "enabled": False,
            "notes": "Mock sync endpoint ready. Replace with Workday REST credentials in production.",
        },
        {
            "provider": "bamboohr",
            "enabled": False,
            "notes": "Mock sync endpoint ready. Replace with BambooHR API key in production.",
        },
    ]


def sync_leave_balance(provider: str, employee_id: int, session: Session) -> dict[str, object]:
    normalized = provider.lower()
    if normalized not in SUPPORTED_HRIS_PROVIDERS:
        raise ValueError(f"Unsupported HRIS provider: {provider}")

    employee = session.exec(select(Employee).where(Employee.id == employee_id)).first()
    if employee is None:
        raise LookupError(f"Employee {employee_id} not found.")

    return {
        "provider": normalized,
        "employee_id": employee_id,
        "leave_balance": employee.leave_balance,
        "synced_at": datetime.utcnow(),
        "note": f"Mock {normalized.title()} sync completed successfully.",
    }

