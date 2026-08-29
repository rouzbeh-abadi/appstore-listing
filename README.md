# appstore-snapshots

[![CI](https://github.com/rouzbeh-abadi/appstore-snapshots/actions/workflows/ci.yml/badge.svg)](https://github.com/rouzbeh-abadi/appstore-snapshots/actions/workflows/ci.yml)

Upload App Store screenshots *and* the text that goes with them — description,
what's new, promotional text — to App Store Connect, in every language. No
Fastlane, no Ruby.

You give it one folder per device size, and each is read the way you happen to
keep it:

```
iPhone-6.9/                 iPad-13-Landscape/
  de-DE/                      01.png       <- no language folders here,
    01.png  02.png            02.png          so these go up as en-US
  en-US/
    01.png  02.png
```

It works out the App Store display type and locale for each folder, creates the
sets, uploads the images and puts them in order.

## Quick start

```bash
uv sync                                 # fetches Python 3.13 and all dependencies
cp .env.example .env                    # then fill it in, see below
uv run streamlit run streamlit_app.py
```

## Your credentials

From App Store Connect → **Users and Access → Integrations → Keys**. The key needs
the **App Manager** role to edit version metadata, and the `.p8` downloads once.

Put them in `.env`:

```ini
ASC_KEY_ID=ABCD123456                   # the code beside the key
ASC_ISSUER_ID=69a6de70-xxxx-xxxx-xxxx   # the UUID above the key table
ASC_KEY_PATH=~/private_keys/AuthKey_ABCD123456.p8
ASC_BUNDLE_ID=com.example.myapp         # optional, pre-fills the field
```

Both `.env` and `*.p8` are gitignored. Never commit either. Real environment
variables override the file, so CI can set them directly.

## The app

Choose your iPhone and iPad folders, tick **Apple Watch** or **Mac** if you have
those, check the bundle ID and press Upload. It targets the newest editable
version of the app and names the version it wrote to when it finishes.

*Advanced* holds two things: the locale for screenshots with no language folder,
and replace-vs-append.

Below the upload button, **Text for each language** takes the metadata JSON —
point it at a path or drop the file in. It checks the file as soon as it has
one, and **Preview changes** shows what would be written before you send it.

## The text for each language

Screenshots come from folders; the words come from one JSON file, one object per
language:

```json
{
  "en-US": {
    "description": "Build a vision board, write a line a day…",
    "keywords": "vision board,journal,gratitude",
    "promotionalText": "Now in four more languages.",
    "whatsNew": "German, French, Spanish and Simplified Chinese."
  },
  "de-DE": {
    "description": "Baue ein Vision Board…",
    "whatsNew": "Jetzt auf Deutsch."
  }
}
```

Copy `metadata.example.json` to start. `appstore-snapshots fields` lists every
field, its character limit, and which record it is written to.

```bash
appstore-snapshots metadata metadata.json --check                  # no network
appstore-snapshots metadata metadata.json -b com.example.myapp --dry-run
appstore-snapshots metadata metadata.json -b com.example.myapp
```

Worth knowing:

* **The file is checked before anything is sent.** Languages Apple does not
  take, fields that do not exist, and text over the limit are all reported
  together, and nothing is uploaded until every one is fixed — a half-applied
  push leaves some languages updated and others not.
* **Only what changed is written.** Each field is compared against what is live
  first, so a re-run is cheap and a value someone edited in the web UI is not
  overwritten by a file that merely repeats the old text. `--dry-run` prints
  exactly the diff it would have written.
* **Languages are matched loosely.** `de`, `de-DE` and `German` all mean
  `de-DE`, the same as the screenshot folders. Field names are forgiving too:
  `whatsNew`, `whats_new` and `"What's New"` are one field.
* **Missing languages are created.** A language in the file that has no
  localization on the version yet gets one.
* **The app name and subtitle are held back** unless you pass
  `--include-app-info`. They carry across versions, so a stale file would
  quietly rename the app.
* **What's New only works on an update.** Apple rejects it on an app's first
  release; the error says so rather than making you guess.
* Omit a field, or set it to `""` or `null`, to leave whatever is there alone.
  Keys starting with `_` are ignored, so you can keep notes in the file.

## The command line

```bash
appstore-snapshots scan -d ./iPhone-6.9 -d ./iPad-13-Landscape    # no network calls
appstore-snapshots upload -d ./iPhone-6.9 -b com.example.myapp --dry-run
appstore-snapshots upload -d ./iPhone-6.9 -b com.example.myapp
appstore-snapshots --help                                          # the rest
```

## Folder names

Separators, case and orientation are ignored, so `iPhone-6.9`, `iphone_69` and
`iPhone-6.9-Portrait` all mean the same thing.

| Folder | Display type |
| --- | --- |
| `iPhone-6.9`, `iPhone-6.7` | `APP_IPHONE_67` |
| `iPad-13-Landscape`, `iPad-12.9` | `APP_IPAD_PRO_3GEN_129` |
| `Mac`, `Apple-Watch-Ultra`, `Apple-TV` | `APP_DESKTOP`, `APP_WATCH_ULTRA`, `APP_APPLE_TV` |

`appstore-snapshots devices` prints the full list. Language folders are normalised
to App Store locale codes, which are irregular: `it-IT` becomes `it` and `zh-CN`
becomes `zh-Hans`, while `de-DE` and `pt-BR` keep their region.

For a name it cannot guess, drop a `snapshots.json` beside your folders:

```json
{ "devices": { "Hero-Shots": "APP_IPHONE_67" }, "languages": { "brazil": "pt-BR" } }
```

Handing it a parent folder instead of individual device folders works too, and
the inverted `<language>/<device>/` layout is recognised automatically.

## Worth knowing

* Uploading **replaces** what is already in each set, and a set holds at most 10
  images. Use `--keep-existing` to append instead.
* Apple never added separate display types for the 6.9-inch iPhone or the 13-inch
  iPad. Those screenshots belong to the 6.7-inch and 12.9-inch types, whose
  accepted resolutions were widened instead.
* The target version has to be editable. If there isn't one, create the next
  version in App Store Connect first.

## Development

```bash
uv run pytest
uv run ruff check . && uv run ruff format .
```

CI runs the same checks on Ubuntu and macOS for every push and pull request.

The package is split by role: `naming/` maps folder names to App Store values,
`scanning/` turns folders into screenshot sets, `metadata/` reads and pushes the
per-language text, `connect/` does auth, REST and uploading, and `ui/` is the
Streamlit page.
