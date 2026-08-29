"""Read and check the metadata JSON before anything is sent to Apple.

The file is one object per language::

    {
      "en-US": { "description": "...", "whatsNew": "...", "promotionalText": "..." },
      "de-DE": { "description": "...", "whatsNew": "...", "promotionalText": "..." }
    }

Every problem that can be found without the network is found here — unknown
languages, unknown fields, text over Apple's limits — and all of them are
reported at once. The API rejects a whole request for a single over-long field
and does not reliably say which language it came from, so finding them locally
is the difference between one clear list and a dozen round trips.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path

from ..errors import SnapshotError, UnknownLocaleError
from ..naming import resolve_locale
from .fields import BY_KEY, Field, resolve_field, suggest


class MetadataError(SnapshotError):
    """The metadata file could not be read or does not describe valid metadata."""


@dataclass(frozen=True, slots=True)
class MetadataIssue:
    """One problem with the file, tied to where it came from."""

    locale: str
    field: str
    reason: str

    def __str__(self) -> str:
        where = f"{self.locale}.{self.field}" if self.field else self.locale
        return f"{where}: {self.reason}"


@dataclass(slots=True)
class LocaleMetadata:
    """The values given for one language, keyed by canonical field name."""

    locale: str
    #: Name the language appeared under in the file, when it was not canonical.
    source_name: str
    values: dict[str, str] = dataclass_field(default_factory=dict)

    def scoped(self, scope: str) -> dict[str, str]:
        """Just the values that belong to ``"app-info"`` or ``"version"``."""
        return {k: v for k, v in self.values.items() if BY_KEY[k].scope == scope}

    def __len__(self) -> int:
        return len(self.values)


@dataclass(slots=True)
class MetadataDocument:
    """A parsed, validated metadata file."""

    path: Path | None
    locales: list[LocaleMetadata] = dataclass_field(default_factory=list)
    issues: list[MetadataIssue] = dataclass_field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def total_fields(self) -> int:
        return sum(len(entry) for entry in self.locales)

    def by_locale(self) -> dict[str, LocaleMetadata]:
        return {entry.locale: entry for entry in self.locales}

    def filtered(self, locales: set[str] | None) -> list[LocaleMetadata]:
        if locales is None:
            return list(self.locales)
        return [entry for entry in self.locales if entry.locale in locales]

    # ------------------------------------------------------------------ load

    @classmethod
    def load(cls, path: Path) -> MetadataDocument:
        """Parse ``path``. Raises only if the file itself cannot be read.

        Content problems land in :attr:`issues` rather than raising, so the
        caller can show every one of them instead of the first.
        """
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise MetadataError(f"No metadata file at {path}") from exc
        except json.JSONDecodeError as exc:
            raise MetadataError(f"{path} is not valid JSON: {exc}") from exc
        return cls.from_mapping(raw, path=path)

    @classmethod
    def from_mapping(cls, raw: object, *, path: Path | None = None) -> MetadataDocument:
        doc = cls(path=path)
        if not isinstance(raw, Mapping):
            raise MetadataError(
                "The metadata file must be an object whose keys are languages, "
                'e.g. {"en-US": {"description": "..."}}.'
            )

        for locale_name, block in raw.items():
            # Keys starting with "_" are notes to whoever edits the file.
            if locale_name.startswith("_"):
                continue
            doc._add_locale(str(locale_name), block)

        if not doc.locales and not doc.issues:
            raise MetadataError("The metadata file has no languages in it.")
        return doc

    def _add_locale(self, locale_name: str, block: object) -> None:
        try:
            locale = resolve_locale(locale_name)
        except UnknownLocaleError:
            self.issues.append(
                MetadataIssue(locale_name, "", "not a language App Store Connect accepts")
            )
            return

        if not isinstance(block, Mapping):
            self.issues.append(
                MetadataIssue(locale, "", "should be an object of field: text pairs")
            )
            return

        entry = LocaleMetadata(locale=locale, source_name=locale_name)
        before = len(self.issues)
        for key, value in block.items():
            if str(key).startswith("_"):
                continue
            self._add_field(entry, str(key), value)

        if entry.values:
            self.locales.append(entry)
        elif len(self.issues) == before:
            # Only worth saying when nothing else was reported for this language.
            # After a rejected field it just repeats the error in vaguer words.
            self.issues.append(MetadataIssue(locale, "", "has no fields to send"))

    def _add_field(self, entry: LocaleMetadata, key: str, value: object) -> None:
        found = resolve_field(key)
        if found is None:
            hint = suggest(key)
            self.issues.append(
                MetadataIssue(
                    entry.locale,
                    key,
                    f"not an App Store field{f'. Did you mean {hint}?' if hint else ''}",
                )
            )
            return

        if value is None:
            return  # an explicit null means "leave whatever is there alone"
        if not isinstance(value, str):
            self.issues.append(
                MetadataIssue(
                    entry.locale, found.key, f"should be text, got {type(value).__name__}"
                )
            )
            return

        text = value.strip("\n") if "\n" in value else value.strip()
        if not text:
            return  # empty means the same as absent: do not touch it

        problem = _check_length(found, text)
        if problem:
            self.issues.append(MetadataIssue(entry.locale, found.key, problem))
            return

        if found.key in entry.values:
            self.issues.append(MetadataIssue(entry.locale, found.key, "given more than once"))
            return

        entry.values[found.key] = text


def _check_length(field: Field, text: str) -> str | None:
    """Apple counts characters, not bytes, so ``len`` is the right measure."""
    if len(text) <= field.limit:
        return None
    return (
        f"{field.label} is {len(text)} characters, {field.limit} is the maximum "
        f"({len(text) - field.limit} too many)"
    )
