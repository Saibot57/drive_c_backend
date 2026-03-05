"""Prompt builders for AI-assisted schedule parsing."""
from __future__ import annotations

from datetime import date
from textwrap import dedent
from typing import Iterable, Mapping, Optional

SWEDISH_DAYS = '["Måndag","Tisdag","Onsdag","Torsdag","Fredag","Lördag","Söndag"]'


def _format_family_members(family_members: Iterable[Mapping[str, object]]) -> str:
    lines: list[str] = []
    for member in family_members:
        name = str(member.get("name", "")).strip()
        identifier = member.get("id")
        if not name:
            continue
        lines.append(f'- "{name}" (id: {identifier})')
    return "\n".join(lines)


def build_parse_prompt(
    natural_text: str,
    family_members: Iterable[Mapping[str, object]],
    week: Optional[int],
    year: Optional[int],
    today: Optional[date] = None,
) -> str:
    """Build a strict prompt instructing the LLM to return activity JSON.

    Parameters
    ----------
    natural_text:
        The free-form schedule text submitted by the user.
    family_members:
        Iterable containing dict-like objects with ``name`` and ``id`` keys.
    week, year:
        Optional ISO week/year context that helps the model interpret relative
        descriptions.
    today:
        Current date for resolving relative expressions like "från nu".
    """

    natural_text = (natural_text or "").strip()
    if not natural_text:
        raise ValueError("natural_text must be a non-empty string")

    fm_lines = _format_family_members(family_members)
    week_year = f"Vecka: {week}, År: {year}" if week and year else "Vecka/år: (ej specificerat)"
    today_str = (today or date.today()).isoformat()
    today_iso = (today or date.today()).isocalendar()

    return dedent(
        f"""
        Du är en schemaläggningsassistent. Svara ENBART med en JSON-array (ingen extra text, inga kodblock).
        Familjemedlemmar (namn → id):
        {fm_lines or "- (inga)"}
        Kontextramar: {week_year}
        Dagens datum: {today_str} (vecka {today_iso.week}, {today_iso.year})

        OBLIGATORISKT OUTPUTSCHEMA (inga "date"/"dates" fält):
        [
          {{
            "name": string,
            "icon": string (valfritt),
            "participants": [string],     // FYLL ENDAST MED FAMILYMEMBER-ID (inte namn)
            "startTime": "HH:MM",         // 24h
            "endTime": "HH:MM",
            "days": {SWEDISH_DAYS},       // en eller flera av dessa strängar
            "week": number,               // ISO-vecka (startvecka)
            "year": number,               // ISO-år (startår)
            "recurringEndDate": "YYYY-MM-DD" // valfritt, se nedan
          }}
        ]

        Regler:
        - Deltagare: använd exakt id från listan ovan. Okända -> utelämna.
        - Om texten anger exakta datum (t.ex. "2025-10-03"), konvertera själv till rätt "days"/"week"/"year".
        - Tider: 24h "HH:MM".
        - Återkommande aktiviteter som sträcker sig över flera veckor (t.ex. "varje fredag från vecka 10 till vecka 20"):
          Sätt "week"/"year" till startveckan och lägg till "recurringEndDate" med slutdatumet (sista dagen i slutveckan, söndag) i formatet "YYYY-MM-DD".
          Använd INTE recurringEndDate för aktiviteter som bara gäller en enda vecka.
        - Svara endast med JSON-array enligt schemat ovan.

        Exempel – återkommande:
        Input: "Varje fredag från vecka 10 till vecka 20 simning för Rut 17:00-19:00" (Rut har id 3)
        Output: [{{"name":"Simning","participants":["3"],"startTime":"17:00","endTime":"19:00","days":["Fredag"],"week":10,"year":2026,"recurringEndDate":"2026-05-17"}}]

        Fritext:
        \"\"\"{natural_text}\"\"\"
        """
    ).strip()
