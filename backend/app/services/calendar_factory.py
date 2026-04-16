from __future__ import annotations

from backend.app.core.config import settings
from backend.app.services.google_calendar_service import GoogleCalendarService


class CalendarServiceFactory:
    _cached_service: GoogleCalendarService | None = None

    @classmethod
    def get_service(cls) -> GoogleCalendarService:
        provider = (settings.calendar_provider or "google").strip().lower()
        if provider != "google":
            provider = "google"

        if cls._cached_service is None:
            cls._cached_service = GoogleCalendarService()

        return cls._cached_service
