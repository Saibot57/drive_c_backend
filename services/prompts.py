"""Prompt builders for AI-assisted schedule parsing."""
from __future__ import annotations

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
    """

    natural_text = (natural_text or "").strip()
    if not natural_text:
        raise ValueError("natural_text must be a non-empty string")

    fm_lines = _format_family_members(family_members)
    week_year = f"Vecka: {week}, År: {year}" if week and year else "Vecka/år: (ej specificerat)"

    return dedent(
        f"""
        Du är en schemaläggningsassistent. Svara ENBART med en JSON-array (ingen extra text, inga kodblock).
        Familjemedlemmar (namn → id):
        {fm_lines or "- (inga)"}
        Kontextramar: {week_year}

        OBLIGATORISKT OUTPUTSCHEMA (inga "date"/"dates" fält):
        [
          {{
            "name": string,
            "icon": string (valfritt),
            "participants": [string],     // FYLL ENDAST MED FAMILYMEMBER-ID (inte namn)
            "startTime": "HH:MM",         // 24h
            "endTime": "HH:MM",
            "days": {SWEDISH_DAYS},       // en eller flera av dessa strängar
            "week": number,               // ISO-vecka
            "year": number                // ISO-år
          }}
        ]

        Regler:
        - Deltagare: använd exakt id från listan ovan. Okända -> utelämna.
        - Om texten anger exakta datum (t.ex. "2025-10-03"), konvertera själv till rätt "days"/"week"/"year".
        - Tider: 24h "HH:MM".
        - Svara endast med JSON-array enligt schemat ovan.

        Fritext:
        \"\"\"{natural_text}\"\"\"
        """
    ).strip()
