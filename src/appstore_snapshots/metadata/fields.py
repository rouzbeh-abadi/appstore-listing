"""The text fields App Store Connect holds per language, and where each lives.

Apple splits localized text across two resources, and which one a field belongs
to is not guessable from its name:

* **App info** (``appInfoLocalizations``) carries what identifies the app —
  its name, its subtitle, the privacy policy link. These survive a version.
* **Version** (``appStoreVersionLocalizations``) carries what is being said
  about *this release* — description, keywords, promotional text, what's new.

Sending a field to the wrong one is a 409 with an unhelpful pointer, so the
routing lives here in one table rather than being spread through the pusher.

The character limits are Apple's. They are checked before anything is uploaded
because the API rejects the whole request when one field is over, and the error
does not always say which locale it came from.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Literal

Scope = Literal["app-info", "version"]


@dataclass(frozen=True, slots=True)
class Field:
    """One localizable App Store text field."""

    #: Key in the metadata JSON, and the attribute name the API expects.
    key: str
    #: Maximum length Apple accepts, in characters.
    limit: int
    #: Which resource it is written to.
    scope: Scope
    #: What it is called in App Store Connect, for error messages.
    label: str

    @property
    def is_url(self) -> bool:
        return self.key.endswith("Url")


FIELDS: tuple[Field, ...] = (
    # ---- app info: identity, carried across versions -----------------------
    Field("name", 30, "app-info", "App name"),
    Field("subtitle", 30, "app-info", "Subtitle"),
    Field("privacyPolicyUrl", 255, "app-info", "Privacy policy URL"),
    Field("privacyPolicyText", 4000, "app-info", "Privacy policy text"),
    Field("privacyChoicesUrl", 255, "app-info", "Privacy choices URL"),
    # ---- version: what this release says ------------------------------------
    Field("description", 4000, "version", "Description"),
    Field("keywords", 100, "version", "Keywords"),
    Field("promotionalText", 170, "version", "Promotional text"),
    Field("whatsNew", 4000, "version", "What's New"),
    Field("marketingUrl", 255, "version", "Marketing URL"),
    Field("supportUrl", 255, "version", "Support URL"),
)

BY_KEY: dict[str, Field] = {f.key: f for f in FIELDS}

APP_INFO_FIELDS: tuple[Field, ...] = tuple(f for f in FIELDS if f.scope == "app-info")
VERSION_FIELDS: tuple[Field, ...] = tuple(f for f in FIELDS if f.scope == "version")

#: Accepted spellings for each key, so a hand-written file does not have to
#: match Apple's camelCase exactly. "whats_new", "what's new" and "releaseNotes"
#: are all the same field.
ALIASES: dict[str, str] = {
    "appname": "name",
    "title": "name",
    "sub_title": "subtitle",
    "promo": "promotionalText",
    "promotional_text": "promotionalText",
    "promotiontext": "promotionalText",
    "whats_new": "whatsNew",
    "whatsnew": "whatsNew",
    "releasenotes": "whatsNew",
    "release_notes": "whatsNew",
    "desc": "description",
    "privacy_policy_url": "privacyPolicyUrl",
    "privacy_policy_text": "privacyPolicyText",
    "privacy_choices_url": "privacyChoicesUrl",
    "marketing_url": "marketingUrl",
    "support_url": "supportUrl",
}


def _normalise_key(name: str) -> str:
    return name.strip().lower().replace(" ", "").replace("-", "").replace("'", "")


def resolve_field(name: str) -> Field | None:
    """The :class:`Field` a JSON key refers to, or ``None`` if it is not one.

    Matching ignores case, spaces, hyphens and apostrophes, and consults
    :data:`ALIASES`, so ``"What's New"`` and ``whatsNew`` both land on the same
    field.
    """
    raw = name.strip()
    if raw in BY_KEY:
        return BY_KEY[raw]

    flat = _normalise_key(raw)
    for field in FIELDS:
        if _normalise_key(field.key) == flat:
            return field
    aliased = ALIASES.get(flat) or ALIASES.get(raw.strip().lower())
    return BY_KEY.get(aliased) if aliased else None


def suggest(name: str) -> str:
    """The closest real field name, for the "did you mean" in an error.

    Returns ``""`` when nothing is close enough to be worth guessing at — a
    wrong suggestion is more confusing than none.
    """
    flat = _normalise_key(name)
    candidates = {_normalise_key(key): key for key in BY_KEY}
    matches = difflib.get_close_matches(flat, candidates, n=1, cutoff=0.6)
    return candidates[matches[0]] if matches else ""
