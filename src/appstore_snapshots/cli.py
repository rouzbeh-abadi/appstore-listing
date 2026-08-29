"""Command line interface: ``appstore-snapshots <command>``."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .connect import AppStoreConnectClient, Credentials, SnapshotUploader, UploadOptions, env
from .errors import SnapshotError
from .metadata import MetadataDocument, MetadataOptions, MetadataPusher
from .models import ProgressEvent, ScanResult
from .naming import DISPLAY_TYPE_LABELS
from .scanning import DEFAULT_LOCALE, SnapshotConfig, scan, scan_devices

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Upload App Store screenshots to App Store Connect, one device folder at a time.",
)
console = Console()

RootArg = Annotated[
    Path | None,
    typer.Argument(
        help="Parent folder holding one sub-folder per device. Omit when using --device."
    ),
]
DeviceOpt = Annotated[
    list[Path] | None,
    typer.Option(
        "--device",
        "-d",
        help="A single device folder (e.g. .../iPhone-6.9). Repeatable; skips the parent folder.",
    ),
]
LocaleOpt = Annotated[
    str,
    typer.Option(
        "--default-locale",
        help="Locale for screenshots that sit directly in a device folder.",
    ),
]
ConfigOpt = Annotated[
    Path | None, typer.Option("--config", "-c", help="Folder-name override file.")
]


def _load_config(anchor: Path, config: Path | None) -> SnapshotConfig:
    return SnapshotConfig.load(config) if config else SnapshotConfig.discover(anchor)


def _scan(
    root: Path | None,
    devices: list[Path] | None,
    cfg: SnapshotConfig,
    *,
    default_locale: str = DEFAULT_LOCALE,
    layout: str | None = None,
) -> ScanResult:
    """Scan either the device folders given with --device, or a parent folder."""
    if devices:
        return scan_devices(
            devices,
            default_locale=default_locale,
            device_overrides=cfg.devices,
            locale_overrides=cfg.languages,
        )
    if root is None:
        raise SnapshotError("Give a parent folder, or one or more --device folders.")
    return scan(
        root,
        device_overrides=cfg.devices,
        locale_overrides=cfg.languages,
        default_locale=default_locale,
        layout=layout,
    )


def _credentials(key: Path | None, key_id: str | None, issuer_id: str | None) -> Credentials:
    """Flags win, then the environment, then .env — via env.get(), not os.environ."""
    key_path = key or (Path(env.get(env.KEY_PATH)) if env.get(env.KEY_PATH) else None)
    if not key_path:
        raise SnapshotError("Pass --key /path/to/AuthKey_XXXX.p8 (or set ASC_KEY_PATH).")
    return Credentials.from_p8_file(
        key_path,
        key_id=key_id or env.get(env.KEY_ID) or None,
        issuer_id=issuer_id or env.get(env.ISSUER_ID),
    )


@app.command("scan")
def scan_command(
    root: RootArg = None,
    device: DeviceOpt = None,
    config: ConfigOpt = None,
    default_locale: LocaleOpt = DEFAULT_LOCALE,
    layout: Annotated[
        str | None, typer.Option(help="device-first | locale-first | flat (default: detect)")
    ] = None,
) -> None:
    """Show what would be uploaded, without contacting Apple."""
    cfg = _load_config(root or (device[0] if device else Path.cwd()), config)
    _print_scan(_scan(root, device, cfg, default_locale=default_locale, layout=layout))


def _print_scan(result: ScanResult) -> None:
    table = Table(title=f"{result.root}  ({result.layout})", header_style="bold")
    table.add_column("Device folder")
    table.add_column("Display type")
    table.add_column("Language folder")
    table.add_column("Locale")
    table.add_column("Shots", justify="right")
    for s in result.sets:
        table.add_row(
            s.device_folder,
            f"{s.display_type}\n[dim]{DISPLAY_TYPE_LABELS.get(s.display_type, '')}[/dim]",
            s.locale_folder or "[dim]— none —[/dim]",
            s.locale,
            str(len(s)),
        )
    console.print(table)
    console.print(
        f"[bold]{len(result.sets)}[/bold] set(s), "
        f"[bold]{result.total_screenshots}[/bold] screenshot(s), "
        f"{len(result.display_types)} device(s), {len(result.locales)} language(s)"
    )
    for issue in result.issues:
        console.print(f"[yellow]skipped[/yellow] {issue.path}: {issue.reason}")


@app.command("apps")
def apps_command(
    key: Annotated[Path | None, typer.Option("--key", help="Path to the .p8 file.")] = None,
    key_id: Annotated[str | None, typer.Option("--key-id")] = None,
    issuer_id: Annotated[str | None, typer.Option("--issuer-id")] = None,
) -> None:
    """List the apps this API key can see."""
    client = AppStoreConnectClient(_credentials(key, key_id, issuer_id))
    table = Table(header_style="bold")
    table.add_column("App ID")
    table.add_column("Name")
    table.add_column("Bundle ID")
    for item in client.list_apps():
        table.add_row(item.id, item.name, item.bundle_id)
    console.print(table)


@app.command("versions")
def versions_command(
    app_id: Annotated[str, typer.Argument(help="App Store Connect app id.")],
    key: Annotated[Path | None, typer.Option("--key")] = None,
    key_id: Annotated[str | None, typer.Option("--key-id")] = None,
    issuer_id: Annotated[str | None, typer.Option("--issuer-id")] = None,
    platform: str = "IOS",
) -> None:
    """List App Store versions and whether their metadata is editable."""
    client = AppStoreConnectClient(_credentials(key, key_id, issuer_id))
    table = Table(header_style="bold")
    table.add_column("Version ID")
    table.add_column("Version")
    table.add_column("Platform")
    table.add_column("State")
    table.add_column("Editable")
    for version in client.list_versions(app_id, platform):
        table.add_row(
            version.id,
            version.version_string,
            version.platform,
            version.state,
            "yes" if version.editable else "no",
        )
    console.print(table)


@app.command("upload")
def upload_command(
    root: RootArg = None,
    device: DeviceOpt = None,
    bundle_id: Annotated[
        str | None, typer.Option("--bundle-id", "-b", help="App bundle identifier.")
    ] = None,
    app_id: Annotated[
        str | None, typer.Option("--app-id", help="App Store Connect app id.")
    ] = None,
    version_id: Annotated[
        str | None, typer.Option("--version-id", help="Target version (default: latest editable).")
    ] = None,
    key: Annotated[Path | None, typer.Option("--key", help="Path to the .p8 file.")] = None,
    key_id: Annotated[str | None, typer.Option("--key-id")] = None,
    issuer_id: Annotated[str | None, typer.Option("--issuer-id")] = None,
    config: ConfigOpt = None,
    default_locale: LocaleOpt = DEFAULT_LOCALE,
    platform: str = "IOS",
    only_devices: Annotated[
        str | None,
        typer.Option("--only-devices", help="Comma-separated display types to include."),
    ] = None,
    only_languages: Annotated[
        str | None,
        typer.Option("--only-languages", help="Comma-separated locales to include."),
    ] = None,
    keep_existing: Annotated[
        bool, typer.Option("--keep-existing", help="Append instead of replacing each set.")
    ] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Plan only; change nothing.")] = False,
    workers: Annotated[int, typer.Option(help="Concurrent image uploads.")] = 4,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation prompt.")] = False,
) -> None:
    """Upload one or more device folders to an App Store version."""
    cfg = _load_config(root or (device[0] if device else Path.cwd()), config)
    result = _scan(root, device, cfg, default_locale=default_locale)
    selected = result.filtered(
        display_types={d.strip() for d in only_devices.split(",")} if only_devices else None,
        locales={loc.strip() for loc in only_languages.split(",")} if only_languages else None,
    )
    if not selected:
        console.print("[red]Nothing to upload.[/red]")
        raise typer.Exit(1)

    _print_scan(result)

    client = AppStoreConnectClient(_credentials(key, key_id, issuer_id))

    target_app_id = app_id
    if not target_app_id:
        resolved_bundle = bundle_id or cfg.bundle_id
        if not resolved_bundle:
            raise SnapshotError("Pass --app-id or --bundle-id (or set bundle_id in the config).")
        found = client.find_app(resolved_bundle)
        if not found:
            raise SnapshotError(
                f"No app with bundle id {resolved_bundle!r} is visible to this key."
            )
        console.print(f"App: [bold]{found}[/bold]  id={found.id}")
        target_app_id = found.id

    if not version_id:
        version = client.latest_editable_version(target_app_id, platform)
        if not version:
            raise SnapshotError(
                "No editable App Store version found. Create one in App Store Connect, "
                "or pass --version-id explicitly."
            )
        console.print(f"Version: [bold]{version}[/bold]  id={version.id}")
        version_id = version.id

    total = sum(len(s) for s in selected)
    if not (yes or dry_run):
        action = "append to" if keep_existing else "REPLACE"
        typer.confirm(
            f"Upload {total} screenshot(s) into {len(selected)} set(s) and {action} their "
            f"current contents?",
            abort=True,
        )

    def on_progress(event: ProgressEvent) -> None:
        colour = {"file_error": "red", "set_start": "cyan", "done": "green"}.get(event.kind, "")
        prefix = f"[{colour}]" if colour else ""
        suffix = f"[/{colour}]" if colour else ""
        console.print(f"{prefix}{event.message}{suffix}")

    uploader = SnapshotUploader(
        client,
        UploadOptions(
            replace_existing=not keep_existing,
            dry_run=dry_run,
            max_workers=max(1, workers),
        ),
        on_progress=on_progress,
    )
    report = uploader.upload(version_id, selected)

    console.print(
        f"\n[bold]{report.uploaded}[/bold] uploaded, "
        f"[bold]{report.deleted}[/bold] removed, "
        f"[bold]{report.sets_touched}[/bold] set(s) touched"
    )
    if report.errors:
        for error in report.errors:
            console.print(f"[red]error[/red] {error}")
        raise typer.Exit(1)


@app.command("metadata")
def metadata_command(
    file: Annotated[Path, typer.Argument(help="JSON file: one object per language.")],
    bundle_id: Annotated[
        str | None, typer.Option("--bundle-id", "-b", help="App bundle identifier.")
    ] = None,
    app_id: Annotated[
        str | None, typer.Option("--app-id", help="App Store Connect app id.")
    ] = None,
    version_id: Annotated[
        str | None, typer.Option("--version-id", help="Target version (default: latest editable).")
    ] = None,
    key: Annotated[Path | None, typer.Option("--key", help="Path to the .p8 file.")] = None,
    key_id: Annotated[str | None, typer.Option("--key-id")] = None,
    issuer_id: Annotated[str | None, typer.Option("--issuer-id")] = None,
    config: ConfigOpt = None,
    platform: str = "IOS",
    only_languages: Annotated[
        str | None,
        typer.Option("--only-languages", help="Comma-separated locales to include."),
    ] = None,
    include_app_info: Annotated[
        bool,
        typer.Option(
            "--include-app-info",
            help="Also write the app name and subtitle. Off by default — they persist "
            "across versions, so a stale file would quietly rename the app.",
        ),
    ] = False,
    check: Annotated[
        bool, typer.Option("--check", help="Validate the file and stop. No network.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would change; write nothing.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation prompt.")] = False,
) -> None:
    """Push descriptions, what's new and promotional text for every language."""
    document = MetadataDocument.load(file)
    _print_metadata(document, include_app_info=include_app_info)

    if document.issues:
        for issue in document.issues:
            console.print(f"[red]invalid[/red] {issue}")
        # Nothing is uploaded while any field is invalid: a partial push leaves
        # some languages updated and others not, which is worse than none.
        raise typer.Exit(1)

    if check:
        console.print("[green]The file is valid.[/green]")
        return

    wanted = {loc.strip() for loc in only_languages.split(",")} if only_languages else None
    client = AppStoreConnectClient(_credentials(key, key_id, issuer_id))

    cfg = _load_config(file.parent, config)
    target_app_id = app_id
    if not target_app_id:
        resolved_bundle = bundle_id or cfg.bundle_id or env.get(env.BUNDLE_ID)
        if not resolved_bundle:
            raise SnapshotError("Pass --app-id or --bundle-id (or set ASC_BUNDLE_ID).")
        found = client.find_app(resolved_bundle)
        if not found:
            raise SnapshotError(
                f"No app with bundle id {resolved_bundle!r} is visible to this key."
            )
        console.print(f"App: [bold]{found}[/bold]  id={found.id}")
        target_app_id = found.id

    if not version_id:
        version = client.latest_editable_version(target_app_id, platform)
        if not version:
            raise SnapshotError(
                "No editable App Store version found. Create one in App Store Connect, "
                "or pass --version-id explicitly."
            )
        console.print(f"Version: [bold]{version}[/bold]  id={version.id}")
        version_id = version.id

    if not (yes or dry_run):
        count = len(document.filtered(wanted))
        typer.confirm(f"Write metadata for {count} language(s) to this version?", abort=True)

    pusher = MetadataPusher(
        client,
        MetadataOptions(dry_run=dry_run, include_app_info=include_app_info),
        on_progress=lambda e: console.print(
            f"[cyan]{e.message}[/cyan]" if e.kind == "set_start" else e.message
        ),
    )
    report = pusher.push(version_id, document, app_id=target_app_id, locales=wanted)

    if report.changes:
        table = Table(title="Would write" if dry_run else "Written", header_style="bold")
        table.add_column("Language")
        table.add_column("Field")
        table.add_column("New value")
        table.add_column("Was", justify="right")
        for change in report.changes:
            table.add_row(
                change.locale,
                change.field,
                change.summary(width=54).split(": ", 1)[-1],
                "[dim]empty[/dim]" if change.is_new else f"{len(change.before)} chars",
            )
        console.print(table)

    console.print(
        f"\n[bold]{report.written}[/bold] field(s) "
        f"{'would be written' if dry_run else 'written'}, "
        f"[bold]{report.unchanged}[/bold] already up to date"
        + (
            f", [bold]{len(report.locales_created)}[/bold] language(s) added"
            if report.locales_created
            else ""
        )
    )
    if report.errors:
        for error in report.errors:
            console.print(f"[red]error[/red] {error}")
        raise typer.Exit(1)


def _print_metadata(document: MetadataDocument, *, include_app_info: bool) -> None:
    table = Table(title=str(document.path or "metadata"), header_style="bold")
    table.add_column("Language")
    table.add_column("Fields")
    table.add_column("Longest", justify="right")
    for entry in document.locales:
        shown = entry.values if include_app_info else entry.scoped("version")
        if not shown:
            continue
        longest = max(((len(v), k) for k, v in shown.items()), default=(0, "—"))
        table.add_row(entry.locale, ", ".join(sorted(shown)), f"{longest[1]} {longest[0]}")
    console.print(table)
    skipped = ""
    if not include_app_info:
        held = sum(len(e.scoped("app-info")) for e in document.locales)
        if held:
            skipped = (
                f"  [dim]({held} app-name/subtitle field(s) held back; "
                "--include-app-info to send)[/dim]"
            )
    console.print(
        f"[bold]{len(document.locales)}[/bold] language(s), "
        f"[bold]{document.total_fields}[/bold] field(s){skipped}"
    )


@app.command("fields")
def fields_command() -> None:
    """List every metadata field, its limit, and which record it is written to."""
    from .metadata import FIELDS

    table = Table(header_style="bold")
    table.add_column("JSON key")
    table.add_column("App Store Connect")
    table.add_column("Limit", justify="right")
    table.add_column("Written to")
    for field_def in FIELDS:
        table.add_row(
            field_def.key,
            field_def.label,
            str(field_def.limit),
            "app info" if field_def.scope == "app-info" else "version",
        )
    console.print(table)


@app.command("devices")
def devices_command() -> None:
    """List every screenshotDisplayType and the folder names that map to it."""
    table = Table(header_style="bold")
    table.add_column("Display type")
    table.add_column("Device")
    table.add_column("Example folder name")
    examples = {
        "APP_IPHONE_67": "iPhone-6.9",
        "APP_IPHONE_65": "iPhone-6.5",
        "APP_IPHONE_61": "iPhone-6.1",
        "APP_IPHONE_58": "iPhone-5.8",
        "APP_IPHONE_55": "iPhone-5.5",
        "APP_IPAD_PRO_3GEN_129": "iPad-13-Landscape",
        "APP_IPAD_PRO_3GEN_11": "iPad-11",
        "APP_IPAD_105": "iPad-10.5",
        "APP_IPAD_97": "iPad-9.7",
        "APP_DESKTOP": "Mac",
        "APP_WATCH_ULTRA": "Apple-Watch-Ultra",
        "APP_APPLE_TV": "Apple-TV",
        "APP_APPLE_VISION_PRO": "Vision-Pro",
    }
    for display_type, label in DISPLAY_TYPE_LABELS.items():
        table.add_row(display_type, label, examples.get(display_type, display_type))
    console.print(table)


@app.command("ui")
def ui_command(
    port: Annotated[int, typer.Option(help="Port for the Streamlit server.")] = 8501,
) -> None:
    """Launch the Streamlit interface (same page as `streamlit run streamlit_app.py`)."""
    try:
        from streamlit.web import cli as stcli
    except ImportError as exc:  # pragma: no cover - streamlit is a hard dependency
        raise SnapshotError("Streamlit is not installed. Run:  uv sync") from exc

    ui_path = Path(__file__).parent / "ui" / "streamlit_app.py"
    sys.argv = ["streamlit", "run", str(ui_path), "--server.port", str(port)]
    sys.exit(stcli.main())


def main() -> None:
    env.load()
    try:
        app()
    except SnapshotError as exc:
        console.print(f"[red]error[/red] {exc}")
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
