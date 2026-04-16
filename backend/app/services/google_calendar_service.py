from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import logging
from typing import Any
from uuid import uuid4

from backend.app.core.config import settings


logger = logging.getLogger(__name__)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_hhmm(value: str, fallback: str) -> time:
    candidate = (value or fallback).strip()
    try:
        hour_text, minute_text = candidate.split(":", 1)
        return time(hour=int(hour_text), minute=int(minute_text))
    except Exception:
        hour_text, minute_text = fallback.split(":", 1)
        return time(hour=int(hour_text), minute=int(minute_text))


class GoogleCalendarService:
    def __init__(self) -> None:
        self._calendar_id = (settings.google_calendar_id or "primary").strip() or "primary"
        self._client = self._build_google_client()

    def _build_google_client(self) -> Any | None:
        client_id = settings.google_client_id.strip()
        client_secret = settings.google_client_secret.strip()
        refresh_token = settings.google_refresh_token.strip()

        if not client_id or not client_secret or not refresh_token:
            logger.warning(
                "Google Calendar credentials are incomplete. Falling back to local slot generation mode."
            )
            return None

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except Exception:
            logger.warning(
                "Google Calendar dependencies are missing. Install google-auth, google-auth-oauthlib, "
                "and google-api-python-client to enable real provider calls."
            )
            return None

        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        try:
            credentials.refresh(Request())
            return build("calendar", "v3", credentials=credentials, cache_discovery=False)
        except Exception:
            logger.exception("Failed to initialize Google Calendar client. Falling back to local mode.")
            return None

    def get_available_slots(
        self,
        date_range_start: datetime,
        date_range_end: datetime,
        duration_minutes: int,
        working_hours: dict[str, str] | None = None,
    ) -> list[dict[str, datetime]]:
        range_start = _as_utc(date_range_start)
        range_end = _as_utc(date_range_end)
        if range_end <= range_start:
            return []

        busy_windows = self._fetch_busy_windows(range_start, range_end)

        working_start = _parse_hhmm((working_hours or {}).get("start", ""), settings.working_hours_start)
        working_end = _parse_hhmm((working_hours or {}).get("end", ""), settings.working_hours_end)
        duration = timedelta(minutes=max(duration_minutes, 15))
        min_start = datetime.now(timezone.utc) + timedelta(hours=24)
        slot_step = timedelta(minutes=30)

        slots: list[dict[str, datetime]] = []
        current_day = range_start.date()
        end_day = range_end.date()

        while current_day <= end_day and len(slots) < 10:
            if current_day.weekday() < 5:
                day_start = datetime.combine(current_day, working_start, tzinfo=timezone.utc)
                day_end = datetime.combine(current_day, working_end, tzinfo=timezone.utc)
                cursor = day_start
                while cursor + duration <= day_end and len(slots) < 10:
                    candidate_start = cursor
                    candidate_end = cursor + duration
                    if candidate_start >= min_start and not self._overlaps_busy(
                        candidate_start,
                        candidate_end,
                        busy_windows,
                    ):
                        slots.append({"start": candidate_start, "end": candidate_end})
                    cursor += slot_step
            current_day += timedelta(days=1)

        return slots

    def _fetch_busy_windows(self, range_start: datetime, range_end: datetime) -> list[tuple[datetime, datetime]]:
        if self._client is None:
            return []

        try:
            response = (
                self._client.freebusy()
                .query(
                    body={
                        "timeMin": range_start.isoformat(),
                        "timeMax": range_end.isoformat(),
                        "items": [{"id": self._calendar_id}],
                    }
                )
                .execute()
            )
            calendar_payload = response.get("calendars", {}).get(self._calendar_id, {})
            busy_items = calendar_payload.get("busy", [])
        except Exception:
            logger.exception("Google Calendar freebusy query failed. Assuming no busy blocks.")
            return []

        busy_windows: list[tuple[datetime, datetime]] = []
        for item in busy_items:
            start_raw = item.get("start")
            end_raw = item.get("end")
            if not start_raw or not end_raw:
                continue
            try:
                start = _as_utc(datetime.fromisoformat(str(start_raw).replace("Z", "+00:00")))
                end = _as_utc(datetime.fromisoformat(str(end_raw).replace("Z", "+00:00")))
            except ValueError:
                continue
            if end > start:
                busy_windows.append((start, end))
        return busy_windows

    @staticmethod
    def _overlaps_busy(
        start_at: datetime,
        end_at: datetime,
        busy_windows: list[tuple[datetime, datetime]],
    ) -> bool:
        for busy_start, busy_end in busy_windows:
            if start_at < busy_end and end_at > busy_start:
                return True
        return False

    def create_calendar_event(
        self,
        title: str,
        description: str,
        start_datetime: datetime,
        end_datetime: datetime,
        attendee_emails: list[str],
        location_or_link: str,
        meet_link: bool = False,
    ) -> dict[str, str | None]:
        start_at = _as_utc(start_datetime)
        end_at = _as_utc(end_datetime)
        attendees = [{"email": email} for email in attendee_emails if email.strip()]

        if self._client is None:
            synthetic_event_id = f"local-{uuid4()}"
            return {
                "event_id": synthetic_event_id,
                "event_link": "",
                "google_meet_link": location_or_link.strip() or None,
            }

        event_body: dict[str, Any] = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_at.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end_at.isoformat(), "timeZone": "UTC"},
            "attendees": attendees,
            "location": location_or_link,
        }

        conference_data_version = 0
        if meet_link:
            conference_data_version = 1
            event_body["conferenceData"] = {
                "createRequest": {
                    "requestId": str(uuid4()),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }

        try:
            created_event = (
                self._client.events()
                .insert(
                    calendarId=self._calendar_id,
                    body=event_body,
                    conferenceDataVersion=conference_data_version,
                    sendUpdates="all",
                )
                .execute()
            )
        except Exception:
            logger.exception("Failed to create Google Calendar event. Returning synthetic fallback details.")
            synthetic_event_id = f"local-{uuid4()}"
            return {
                "event_id": synthetic_event_id,
                "event_link": "",
                "google_meet_link": location_or_link.strip() or None,
            }

        meet_url: str | None = created_event.get("hangoutLink")
        conference_data = created_event.get("conferenceData") or {}
        for entry in conference_data.get("entryPoints", []):
            if entry.get("entryPointType") == "video" and entry.get("uri"):
                meet_url = str(entry["uri"]).strip()
                break

        return {
            "event_id": str(created_event.get("id", "")),
            "event_link": str(created_event.get("htmlLink", "")),
            "google_meet_link": meet_url,
        }

    def cancel_calendar_event(self, event_id: str) -> None:
        normalized_event_id = (event_id or "").strip()
        if not normalized_event_id:
            return
        if self._client is None or normalized_event_id.startswith("local-"):
            return

        try:
            (
                self._client.events()
                .delete(
                    calendarId=self._calendar_id,
                    eventId=normalized_event_id,
                    sendUpdates="all",
                )
                .execute()
            )
        except Exception:
            logger.exception("Failed to cancel Google Calendar event id=%s", normalized_event_id)
