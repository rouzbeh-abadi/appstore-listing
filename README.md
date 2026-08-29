# appstore-listing

[![CI](https://github.com/rouzbeh-abadi/appstore-listing/actions/workflows/ci.yml/badge.svg)](https://github.com/rouzbeh-abadi/appstore-listing/actions/workflows/ci.yml)

Publish an App Store listing from your own machine. Screenshots, app name,
subtitle, description, keywords, promotional text and what's new, in every
language you ship. No Fastlane, no Ruby.

A release usually means opening App Store Connect and pasting the same eight
things into eight language tabs. This does it in one command, checks everything
against Apple's limits before it sends a byte, and writes only what actually
changed.

```bash
appstore-listing upload -d ./iPhone-6.9 -d ./iPad-13 -b com.example.myapp
appstore-listing metadata listing.json -b com.example.myapp
```

## Install

```bash
uv sync                                 # fetches Python 3.13 and dependencies
cp .env.example .env                    # then fill it in, see below
```

## Credentials

From App Store Connect → **Users and Access → Integrations → Keys**. The key
needs the **App Manager** role to edit version metadata, and the `.p8` downloads
once.

```ini
ASC_KEY_ID=ABCD123456                   # the code beside the key
ASC_ISSUER_ID=69a6de70-xxxx-xxxx-xxxx   # the UUID above the key table
ASC_KEY_PATH=~/private_keys/AuthKey_ABCD123456.p8
ASC_BUNDLE_ID=com.example.myapp         # optional, pre-fills the field
```

`.env` and `*.p8` are both gitignored. Never commit either. Real environment
variables win over the file, so CI can set them directly.

## Screenshots

One folder per device size, each read the way you happen to keep it:

```
iPhone-6.9/                 iPad-13-Landscape/
  de-DE/                      01.png       <- no language folders here,
    01.png  02.png            02.png          so these go up as en-US
  en-US/
    01.png  02.png
```

It works out the display type and locale from the folder names, creates the
sets, uploads the images and puts them in order.

```bash
appstore-listing scan -d ./iPhone-6.9 -d ./iPad-13-Landscape   # no network
appstore-listing upload -d ./iPhone-6.9 -b com.example.myapp --dry-run
appstore-listing upload -d ./iPhone-6.9 -b com.example.myapp
```

Separators, case and orientation are ignored, so `iPhone-6.9`, `iphone_69` and
`iPhone-6.9-Portrait` all mean the same thing. `appstore-listing devices` prints
every name it knows. Language folders are normalised to App Store locale codes,
which are irregular: `it-IT` becomes `it` and `zh-CN` becomes `zh-Hans`, while
`de-DE` and `pt-BR` keep their region.

For a folder name it cannot guess, drop a `listing.json` beside your folders (`snapshots.json` still works):

```json
{ "devices": { "Hero-Shots": "APP_IPHONE_67" }, "languages": { "brazil": "pt-BR" } }
```

## The words

One JSON file, one object per language:

```json
{
  "en-US": {
    "name": "Vision Board by SuccessKit",
    "subtitle": "Plan, journal, look back",
    "description": "Build a vision board, write a line a day…",
    "keywords": "vision board,journal,gratitude",
    "promotionalText": "Now in four more languages.",
    "whatsNew": "German, French, Spanish and Simplified Chinese."
  },
  "de-DE": {
    "subtitle": "Planen, schreiben, zurückblicken",
    "whatsNew": "Jetzt auf Deutsch."
  }
}
```

```bash
appstore-listing metadata listing.json --check                  # no network
appstore-listing metadata listing.json -b com.example.myapp --dry-run
appstore-listing metadata listing.json -b com.example.myapp
```

`appstore-listing fields` lists every field, its character limit, and whether it
belongs to the version or to the app.

### What it does for you

**Checks the whole file before sending anything.** Languages Apple does not
take, fields that do not exist, and text over the limit are reported together,
and nothing is uploaded until every one is fixed. A half-applied push that left
some languages updated and others not would be worse than no push at all.

**Writes only what changed.** Every field is compared against what is live
first, so a re-run is cheap, and a value someone edited in the web UI is not
overwritten by a file that merely repeats the old text. `--dry-run` prints the
exact diff it would have written.

**Matches languages loosely.** `de`, `de-DE` and `German` all mean `de-DE`, the
same as the screenshot folders. Field names are forgiving too: `whatsNew`,
`whats_new` and `"What's New"` are one field.

**Creates missing languages.** A language in the file with no localization on
the version yet gets one.

**Holds back the app name and subtitle** unless you pass `--include-app-info`.
Unlike keywords and what's new, those two live on the app rather than the
version and carry across every release, so a stale file would quietly rename
your app.

**Refuses what's new on a first release,** because Apple does, and says so
rather than making you guess.

Omit a field, or set it to `""` or `null`, to leave whatever is there alone.
Keys starting with `_` are ignored, so you can keep notes in the file.

## The interface

```bash
uv run streamlit run streamlit_app.py
```

Choose your folders, tick **Apple Watch** or **Mac** if you have those, check
the bundle ID and press Upload. It targets the newest editable version and names
the version it wrote to when it finishes.

**Text for each language** takes the same JSON: point it at a path or drop the
file in. It validates as soon as it has one, and **Preview changes** shows what
would be written before you send it.

*Advanced* holds the locale for screenshots with no language folder, and
replace-vs-append.

## Device folders

| Folder | Display type |
| --- | --- |
| `iPhone-6.9`, `iPhone-6.7` | `APP_IPHONE_67` |
| `iPad-13-Landscape`, `iPad-12.9` | `APP_IPAD_PRO_3GEN_129` |
| `Mac`, `Apple-Watch-Ultra`, `Apple-TV` | `APP_DESKTOP`, `APP_WATCH_ULTRA`, `APP_APPLE_TV` |

## Everything else

```bash
appstore-listing apps                   # every app this key can see
appstore-listing versions <app-id>      # versions, and which are editable
appstore-listing fields                 # fields, limits, and where they land
appstore-listing devices                # display types and folder names
appstore-listing --help
```

## Development

```bash
uv run pytest          # 117 tests, no network
uv run ruff check .
```

MIT.
