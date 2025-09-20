"""Normalize AI-generated activities to importer schema."""
from __future__ import annotations

from datetime import date, datetime
import os
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from dateutil import parser as date_parser

SWEDISH_DAYS: List[str] = [
    "Måndag",
    "Tisdag",
    "Onsdag",
    "Torsdag",
    "Fredag",
    "Lördag",
    "Söndag",
]

STRICT_UNKNOWN = os.getenv("AI_PARSE_STRICT_UNKNOWN_PARTICIPANTS", "0") == "1"
# Whether AI parsing should reject unknown participants.
#
# The default is non-strict (drop unknown participants quietly). If this flag is
# enabled, the frontend must gracefully handle HTTP 422 responses triggered by
# unknown participants.

_DAY_NORMALIZATION = {
    "mandag": "Måndag",
    "måndag": "Måndag",
    "mån": "Måndag",
    "monday": "Måndag",
    "tisdag": "Tisdag",
    "tis": "Tisdag",
    "tuesday": "Tisdag",
    "onsdag": "Onsdag",
    "ons": "Onsdag",
    "wednesday": "Onsdag",
    "torsdag": "Torsdag",
    "tor": "Torsdag",
    "tors": "Torsdag",
    "thursday": "Torsdag",
    "fredag": "Fredag",
    "fre": "Fredag",
    "fred": "Fredag",
    "friday": "Fredag",
    "lordag": "Lördag",
    "lördag": "Lördag",
    "lör": "Lördag",
    "lörs": "Lördag",
    "saturday": "Lördag",
    "sondag": "Söndag",
    "söndag": "Söndag",
    "sön": "Söndag",
    "sunday": "Söndag",
}
def _coerce_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date:
    if isinstance(value, (datetime, date)):
        return value.date() if isinstance(value, datetime) else value
    if not isinstance(value, str):
        raise ValueError("Expected date string")
    try:
        parsed = date_parser.isoparse(value)
    except (ValueError, TypeError):
        parsed = date_parser.parse(value)
    return parsed.date()


def _date_components(value: Any) -> Tuple[str, int, int]:
    d = _parse_date(value)
    iso = d.isocalendar()
    day_name = SWEDISH_DAYS[iso.weekday - 1]
    return day_name, iso.week, iso.year


def _normalize_day_label(day: Any) -> Optional[str]:
    if not isinstance(day, str):
        return None
    stripped = day.strip()
    if not stripped:
        return None
    lowered = stripped.lower()
    normalized = _DAY_NORMALIZATION.get(lowered)
    if normalized:
        return normalized
    capitalized = stripped.capitalize()
    return capitalized if capitalized in SWEDISH_DAYS else None


def expand_dates_to_week_schema(
    items: Iterable[Mapping[str, Any]],
    default_week: Optional[int] = None,
    default_year: Optional[int] = None,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue

        base: Dict[str, Any] = dict(item)
        date_value = base.pop("date", None)
        dates_value = base.pop("dates", None)
        day_value = base.pop("day", None)
        days_value = base.pop("days", None)
        week_value = base.pop("week", None)
        year_value = base.pop("year", None)

        if date_value:
            try:
                day_name, week_num, year_num = _date_components(date_value)
            except ValueError:
                continue
            entry = dict(base)
            entry["days"] = [day_name]
            entry["week"] = week_num
            entry["year"] = year_num
            results.append(entry)
            continue

        if isinstance(dates_value, Iterable) and not isinstance(dates_value, (str, bytes)):
            grouped: Dict[Tuple[int, int], List[str]] = {}
            for raw_date in dates_value:
                try:
                    day_name, week_num, year_num = _date_components(raw_date)
                except ValueError:
                    continue
                key = (week_num, year_num)
                grouped.setdefault(key, [])
                if day_name not in grouped[key]:
                    grouped[key].append(day_name)
            for (week_num, year_num), day_list in grouped.items():
                entry = dict(base)
                entry["days"] = day_list
                entry["week"] = week_num
                entry["year"] = year_num
                results.append(entry)
            if grouped:
                continue

        candidate_days: List[str] = []
        if isinstance(days_value, list):
            for val in days_value:
                normalized = _normalize_day_label(val)
                if normalized:
                    candidate_days.append(normalized)
        elif isinstance(days_value, str):
            normalized = _normalize_day_label(days_value)
            if normalized:
                candidate_days.append(normalized)

        if day_value:
            normalized = _normalize_day_label(day_value)
            if normalized and normalized not in candidate_days:
                candidate_days.append(normalized)

        entry = dict(base)
        if candidate_days:
            entry["days"] = candidate_days

        week_num = _coerce_int(week_value)
        year_num = _coerce_int(year_value)
        if week_num is None and default_week is not None:
            week_num = _coerce_int(default_week)
        if year_num is None and default_year is not None:
            year_num = _coerce_int(default_year)
        if week_num is not None:
            entry["week"] = week_num
        if year_num is not None:
            entry["year"] = year_num

        results.append(entry)

    return results


def map_participants_to_ids(
    items: Iterable[Mapping[str, Any]],
    fm_list: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    id_set = {str(member.get("id")) for member in fm_list if member.get("id") is not None}
    name_to_id = {
        str(member.get("name", "")).strip().lower(): str(member.get("id"))
        for member in fm_list
        if member.get("name")
    }

    results: List[Dict[str, Any]] = []

    for item in items:
        if not isinstance(item, Mapping):
            continue
        raw_participants = item.get("participants") or []
        mapped: List[str] = []
        unknowns: List[str] = []
        for participant in raw_participants:
            if participant is None:
                continue
            identifier = str(participant).strip()
            if not identifier:
                continue
            if identifier in id_set:
                if identifier not in mapped:
                    mapped.append(identifier)
                continue
            name_lookup = name_to_id.get(identifier.lower())
            if name_lookup:
                if name_lookup not in mapped:
                    mapped.append(name_lookup)
            else:
                unknowns.append(identifier)

        if STRICT_UNKNOWN and unknowns:
            raise ValueError(f"Unknown participants: {', '.join(unknowns)}")

        entry = dict(item)
        entry["participants"] = mapped
        results.append(entry)

    return results


def ensure_required_fields(items: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    required = {"name", "startTime", "endTime", "participants", "days", "week", "year"}
    results: List[Dict[str, Any]] = []

    for item in items:
        if not isinstance(item, Mapping):
            continue
        if not required.issubset(item.keys()):
            continue

        name = item.get("name")
        start_time = item.get("startTime")
        end_time = item.get("endTime")
        participants = item.get("participants")
        days = item.get("days")
        week = _coerce_int(item.get("week"))
        year = _coerce_int(item.get("year"))

        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(start_time, str) or not isinstance(end_time, str):
            continue
        if not isinstance(participants, list):
            continue
        if not isinstance(days, list) or not days:
            continue

        normalized_days = []
        for day in days:
            normalized = _normalize_day_label(day)
            if normalized and normalized not in normalized_days:
                normalized_days.append(normalized)

        if not normalized_days or week is None or year is None:
            continue

        entry = dict(item)
        entry["name"] = name.strip()
        entry["startTime"] = start_time.strip()
        entry["endTime"] = end_time.strip()
        entry["participants"] = [str(pid) for pid in entry.get("participants", [])]
        entry["days"] = normalized_days
        entry["week"] = week
        entry["year"] = year
        results.append(entry)

    return results


def normalize_and_align(
    items: Iterable[Mapping[str, Any]],
    fm_list: Iterable[Mapping[str, Any]],
    default_week: Optional[int] = None,
    default_year: Optional[int] = None,
) -> List[Dict[str, Any]]:
    expanded = expand_dates_to_week_schema(items, default_week=default_week, default_year=default_year)
    mapped = map_participants_to_ids(expanded, fm_list)
    return ensure_required_fields(mapped)
