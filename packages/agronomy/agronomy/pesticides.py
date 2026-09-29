"""
Naming a pesticide India has banned, when someone mentions one.

The platform already refuses to emit a dose. That was the right first rule,
and it is not enough: a farmer can ask "should I spray endosulfan on my
brinjal", and an assistant that answers the question as asked — even without
a dose — has helped them use a product the Supreme Court banned in 2011.

The check is deliberately blunt. It looks for regulated actives in what the
farmer wrote and in what the assistant is about to say, and when it finds
one it states the legal position. No judgement about whether the advice was
otherwise sound, and no refusal to continue. The farmer may have a shed full
of the stuff and a genuine question about what to do with it.

Three categories, kept apart, because collapsing them is itself
misinformation:

  **banned**      — no lawful agricultural use in India
  **withdrawn**   — registration withdrawn pending data
  **restricted**  — lawful, but only in certain ways or on certain crops

Monocrotophos is the case that makes the distinction matter. It is on every
informal "banned in India" list on the internet, and it is not banned: it is
banned *on vegetables*. Telling a cotton grower that the product in their
shed is illegal is a false statement about the law, and being wrong in that
direction spends the credibility the genuinely banned entries rely on.

Matching is on normalised text so that a farmer typing in Gurmukhi,
Devanagari or Latin gets the same answer, and trade names are included
because that is what is printed on the packet in the shop.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_FILE = Path(__file__).parent / "data" / "pesticides.json"
_table: dict | None = None


def _load() -> dict:
    global _table
    if _table is None:
        try:
            _table = json.loads(_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            # No table is a normal state: the check simply stops firing. It
            # must never be the reason an answer fails to reach a farmer.
            _table = {"banned": [], "withdrawn": [], "restricted": {},
                      "banned_formulations": [], "aliases": {}}
    return _table


def _normalise(text: str) -> str:
    """One spelling for letters that can be typed two ways.

    Gurmukhi ਫ਼ and Devanagari फ़ each have a composed and a decomposed form,
    and a farmer's keyboard may produce either. Without NFC the same word
    fails to match itself.
    """
    return unicodedata.normalize("NFC", text or "").lower()


@dataclass(frozen=True)
class Finding:
    """One regulated pesticide named in a piece of text."""
    name: str
    status: str          # "banned" | "withdrawn" | "restricted"
    detail: str

    def sentence(self) -> str:
        if self.status == "banned":
            return (f"{self.name} is banned in India — it may not lawfully be "
                    f"manufactured, imported or used.")
        if self.status == "withdrawn":
            return (f"{self.name} has had its registration withdrawn in India "
                    f"and should not be used.")
        return f"{self.name}: {self.detail}"


def _terms() -> list[tuple[str, str, str]]:
    """(searchable term, canonical name, status) for everything regulated."""
    table = _load()
    out: list[tuple[str, str, str]] = []

    def add(name: str, status: str) -> None:
        out.append((_normalise(name), name, status))
        for alias in table.get("aliases", {}).get(name, []):
            out.append((_normalise(alias), name, status))

    for name in table.get("banned", []):
        add(name, "banned")
    for name in table.get("banned_formulations", []):
        add(name, "banned")
    for name in table.get("withdrawn", []):
        add(name, "withdrawn")
    for name in table.get("restricted", {}):
        add(name, "restricted")
    # Longest first, so "Methyl Parathion" wins over "Ethyl Parathion" and
    # "Paraquat Dimethyl Sulphate" over a bare "paraquat" alias.
    out.sort(key=lambda row: -len(row[0]))
    return out


_compiled: list[tuple[re.Pattern, str, str]] | None = None


def _patterns() -> list[tuple[re.Pattern, str, str]]:
    global _compiled
    if _compiled is None:
        _compiled = [
            # Word boundaries on the Latin side only; Indic scripts have no
            # \b that means what we want, and a substring match is right
            # there because these are distinctive words.
            (re.compile(rf"(?<![a-z]){re.escape(term)}(?![a-z])")
             if term.isascii() else re.compile(re.escape(term)),
             name, status)
            for term, name, status in _terms()
        ]
    return _compiled


def find_regulated(text: str) -> list[Finding]:
    """Every banned, withdrawn or restricted pesticide named in `text`.

    Ordered with banned first, because that is the one that has to be said.
    """
    haystack = _normalise(text)
    if not haystack:
        return []
    table = _load()
    seen: set[str] = set()
    found: list[Finding] = []
    for pattern, name, status in _patterns():
        if name in seen or not pattern.search(haystack):
            continue
        seen.add(name)
        found.append(Finding(
            name=name, status=status,
            detail=table.get("restricted", {}).get(name, ""),
        ))
    order = {"banned": 0, "withdrawn": 1, "restricted": 2}
    found.sort(key=lambda f: order.get(f.status, 3))
    return found


def notice(findings: list[Finding]) -> str | None:
    """What to add to an answer that named a regulated pesticide."""
    if not findings:
        return None
    lines = [f.sentence() for f in findings[:3]]
    lines.append(
        "This is the Central Insecticides Board list. Ask your KVK or "
        "agriculture officer what is approved for your crop."
    )
    return " ".join(lines)


def is_verified() -> bool:
    return bool(_load().get("verified_on"))
