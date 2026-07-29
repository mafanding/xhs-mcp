"""Unified CLI for XiaoHongShu operations.

Mirrors the TypeScript CLI's commands, flags, JSON output shape and exit codes,
so existing scripts keep working.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import click

from ..core.auth.auth_service import AuthService
from ..core.browser.browser_manager import BrowserManager
from ..core.feeds.feed_service import FeedService
from ..core.notes.note_service import NoteService
from ..core.publishing.publish_service import PublishService
from ..server.http_server import XHSHTTPMCPServer
from ..server.mcp_server import XHSMCPServer
from ..server.schemas.tool_schemas import XHS_TOOL_SCHEMAS
from ..shared.config import get_config
from ..shared.utils import omit_none

T = TypeVar("T")

_BOX_DRAWING_RE = re.compile(r"[─-╿]+")
_STACK_LINE_RE = re.compile(r"^\s+(?:at|File)\s+.*$", re.MULTILINE)

_KNOWN_MESSAGE_FRAGMENTS = (
    "Either --note-id or --last-published must be specified",
    "Please specify either",
    "User not logged in",
    "Note not found",
    "Delete button not found",
)


class CLIState:
    """Holds process-wide CLI options and the managers that need tearing down."""

    def __init__(self) -> None:
        self.compact = False
        self.browser_managers: list[BrowserManager] = []

    def track(self, *services: Any) -> None:
        for service in services:
            manager = getattr(service, "browser_manager", None)
            if manager is not None and manager not in self.browser_managers:
                self.browser_managers.append(manager)

    async def cleanup(self) -> None:
        for manager in self.browser_managers:
            try:
                await manager.cleanup()
            except Exception:
                pass
        self.browser_managers.clear()


def format_error_message(error: BaseException | str) -> str:
    """Condense an exception into a single user-facing line."""
    raw = str(error)

    if re.search(r"Executable doesn't exist|puppeteer browsers install", raw, re.I):
        return (
            "Chromium is not installed. Run: xhs-mcp browser to download the "
            "CloakBrowser stealth Chromium"
        )

    if any(fragment in raw for fragment in _KNOWN_MESSAGE_FRAGMENTS):
        return raw

    condensed = _STACK_LINE_RE.sub("", _BOX_DRAWING_RE.sub("", raw)).strip()
    return condensed or raw


def write_json(state: CLIState, output: Any, exit_code: int = 0) -> None:
    """Print a JSON payload and exit with ``exit_code``."""
    text = (
        json.dumps(output, ensure_ascii=False, default=str)
        if state.compact
        else json.dumps(output, ensure_ascii=False, indent=2, default=str)
    )
    sys.stdout.write(f"{text}\n")
    sys.stdout.flush()
    sys.exit(exit_code)


def print_success(state: CLIState, result: Any, message: str | None = None) -> None:
    if isinstance(result, dict) and "success" in result:
        write_json(state, result, 0)
    else:
        payload = omit_none(
            {
                "success": True,
                "message": message
                or (result.get("message") if isinstance(result, dict) else None),
                "data": result,
            },
            "message",
        )
        write_json(state, payload, 0)


def print_error(state: CLIState, error: BaseException | str, code: str | None = None) -> None:
    write_json(
        state,
        omit_none(
            {
                "success": False,
                "message": format_error_message(error),
                "code": code,
                "status": "error",
            },
            "code",
        ),
        1,
    )


def print_usage_error(state: CLIState, command: str, message: str) -> None:
    """Report a usage problem as JSON, pointing at the subcommand's help."""
    write_json(
        state,
        {
            "success": False,
            "message": message,
            "status": "error",
            "usage": f"Use 'xhs-mcp {command} --help' for more information",
        },
        1,
    )


def run_command(state: CLIState, coro_factory: Callable[[], Awaitable[T]]) -> None:
    """Run an async command, always tearing the browser down afterwards."""

    async def runner() -> None:
        try:
            result = await coro_factory()
        except SystemExit:
            raise
        except BaseException as error:  # noqa: BLE001 - surfaced as JSON
            await state.cleanup()
            print_error(state, error)
            return
        await state.cleanup()
        print_success(state, result)

    asyncio.run(runner())


pass_state = click.make_pass_decorator(CLIState, ensure=True)


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=False,
)
@click.option("--compact", is_flag=True, help="Output compact one-line JSON (no pretty print)")
@click.pass_context
def cli(ctx: click.Context, compact: bool) -> None:
    """XiaoHongShu CLI with subcommands."""
    state = ctx.ensure_object(CLIState)
    state.compact = compact


# ----------------------------------------------------------------------
# Authentication
# ----------------------------------------------------------------------


@cli.command()
@click.option(
    "-t",
    "--timeout",
    type=int,
    default=None,
    help="Login timeout in seconds",
)
@pass_state
def login(state: CLIState, timeout: int | None) -> None:
    """Start XiaoHongShu login flow (opens browser, saves cookies)."""
    config = get_config()
    timeout_sec = timeout if timeout is not None else config.browser.login_timeout
    service = AuthService(config)
    state.track(service)
    run_command(state, lambda: service.login(None, timeout_sec))


@cli.command()
@pass_state
def logout(state: CLIState) -> None:
    """Logout from XiaoHongShu and clear saved cookies."""
    service = AuthService(get_config())
    state.track(service)
    run_command(state, service.logout)


@cli.command()
@pass_state
def status(state: CLIState) -> None:
    """Check current XiaoHongShu login status."""
    service = AuthService(get_config())
    state.track(service)
    run_command(state, lambda: service.check_status(None))


# ----------------------------------------------------------------------
# Browser dependency
# ----------------------------------------------------------------------


@cli.command()
@click.option(
    "--with-deps",
    is_flag=True,
    help="Accepted for compatibility; CloakBrowser ships a self-contained binary",
)
@pass_state
def browser(state: CLIState, with_deps: bool) -> None:
    """Ensure the CloakBrowser stealth Chromium is installed; downloads if missing."""
    from cloakbrowser import binary_info, ensure_binary

    try:
        info = binary_info()

        if info.get("installed"):
            print_success(
                state,
                {"installed": True, "executablePath": info.get("binary_path")},
                "Chromium is ready",
            )
            return

        # Not cached yet: this downloads roughly 200MB on first use.
        executable_path = ensure_binary()

        after = binary_info()
        if after.get("installed"):
            print_success(
                state,
                {
                    "installed": True,
                    "executablePath": executable_path or after.get("binary_path"),
                },
                "Chromium installed and ready",
            )
        else:
            print_error(state, Exception("Failed to install or launch Chromium"))
    except SystemExit:
        raise
    except BaseException as error:  # noqa: BLE001 - surfaced as JSON
        print_error(state, error)


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------


@cli.command()
@click.option("-b", "--browser-path", default=None, help="Custom browser binary path")
@pass_state
def feeds(state: CLIState, browser_path: str | None) -> None:
    """Discover home page feeds."""
    service = FeedService(get_config())
    state.track(service)
    run_command(state, lambda: service.get_feed_list(browser_path))


@cli.command()
@click.option("-k", "--keyword", required=True, help="Search keyword")
@click.option("-b", "--browser-path", default=None, help="Custom browser binary path")
@pass_state
def search(state: CLIState, keyword: str, browser_path: str | None) -> None:
    """Search notes by keyword."""
    service = FeedService(get_config())
    state.track(service)
    run_command(state, lambda: service.search_feeds(keyword, browser_path))


@cli.command()
@click.option("--feed-id", required=True, help="Feed ID")
@click.option("--xsec-token", required=True, help="Security token for the feed")
@click.option("-n", "--note", required=True, help="Comment content")
@click.option("-b", "--browser-path", default=None, help="Custom browser binary path")
@pass_state
def comment(
    state: CLIState,
    feed_id: str,
    xsec_token: str,
    note: str,
    browser_path: str | None,
) -> None:
    """Comment on a note."""
    service = FeedService(get_config())
    state.track(service)
    run_command(
        state, lambda: service.comment_on_feed(feed_id, xsec_token, note, browser_path)
    )


# ----------------------------------------------------------------------
# User notes
# ----------------------------------------------------------------------


@cli.group()
def usernote() -> None:
    """Current user's note management operations."""


@usernote.command("list")
@click.option("-l", "--limit", default="20", help="Maximum number of notes to retrieve")
@click.option("-c", "--cursor", default=None, help="Pagination cursor for next page")
@click.option("-b", "--browser-path", default=None, help="Custom browser binary path")
@pass_state
def usernote_list(
    state: CLIState, limit: str, cursor: str | None, browser_path: str | None
) -> None:
    """List current user's published notes."""
    service = NoteService(get_config())
    state.track(service)

    try:
        parsed_limit = int(limit) or 20
    except ValueError:
        parsed_limit = 20

    run_command(state, lambda: service.get_user_notes(parsed_limit, cursor, browser_path))


@usernote.command("delete")
@click.option("--note-id", default=None, help="Specific note ID to delete")
@click.option("--last-published", is_flag=True, help="Delete the last published note")
@click.option("-b", "--browser-path", default=None, help="Custom browser binary path")
@pass_state
def usernote_delete(
    state: CLIState,
    note_id: str | None,
    last_published: bool,
    browser_path: str | None,
) -> None:
    """Delete user notes."""
    service = NoteService(get_config())
    state.track(service)

    if last_published:
        run_command(state, lambda: service.delete_last_published_note(browser_path))
    elif note_id:
        run_command(state, lambda: service.delete_note(note_id, browser_path))
    else:
        # Show help rather than a JSON error when no target was given.
        click.echo("Usage: xhs-mcp usernote delete [options]\n")
        click.echo("Delete user notes\n")
        click.echo("Options:")
        click.echo("  --note-id <id>             Specific note ID to delete")
        click.echo("  --last-published           Delete the last published note")
        click.echo("  -b, --browser-path <path>  Custom browser binary path")
        click.echo("  -h, --help                 display help for command")
        sys.exit(0)


# ----------------------------------------------------------------------
# Publishing
# ----------------------------------------------------------------------


@cli.command()
@click.option(
    "-t",
    "--type",
    "content_type",
    required=True,
    help='Content type: "image" for images, "video" for videos',
)
@click.option("--title", required=True, help="Content title (<= 20 chars)")
@click.option("--content", required=True, help="Content description (<= 1000 chars)")
@click.option(
    "-m",
    "--media",
    required=True,
    help=(
        "Comma-separated media file paths (1-18 images for image posts, "
        "exactly 1 video for videos)"
    ),
)
@click.option("--tags", default=None, help="Comma-separated tags")
@click.option("-b", "--browser-path", default=None, help="Custom browser binary path")
@pass_state
def publish(
    state: CLIState,
    content_type: str,
    title: str,
    content: str,
    media: str,
    tags: str | None,
    browser_path: str | None,
) -> None:
    """Publish content to XiaoHongShu (supports both images and videos)."""
    service = PublishService(get_config())
    state.track(service)

    if content_type not in ("image", "video"):
        print_error(state, Exception('Type must be "image" or "video"'))
        return

    media_paths = [path.strip() for path in media.split(",") if path.strip()]

    run_command(
        state,
        lambda: service.publish_content(
            content_type, title, content, media_paths, tags or "", browser_path
        ),
    )


# ----------------------------------------------------------------------
# MCP server
# ----------------------------------------------------------------------


@cli.command()
@click.option("-m", "--mode", default="stdio", help="Server mode: stdio or http")
@click.option("-p", "--port", default="3000", help="HTTP server port (only for http mode)")
def mcp(mode: str, port: str) -> None:
    """Start XHS MCP server (stdio or http mode)."""
    try:
        if mode == "http":
            try:
                parsed_port = int(port)
            except ValueError:
                parsed_port = 3000
            asyncio.run(XHSHTTPMCPServer(parsed_port).start())
        else:
            # stdio mode must keep stdout free of anything but MCP frames.
            asyncio.run(XHSMCPServer().start())
    except KeyboardInterrupt:
        sys.exit(0)
    except BaseException as error:  # noqa: BLE001
        if os.environ.get("XHS_ENABLE_LOGGING") == "true":
            sys.stderr.write(f"Server failed to start: {error}\n")
        sys.exit(1)


# ----------------------------------------------------------------------
# Tool listing
# ----------------------------------------------------------------------


@cli.command()
@click.option("-j", "--json", "as_json", is_flag=True, help="Output in JSON format")
@click.option("-d", "--detailed", is_flag=True, help="Show detailed tool information")
@pass_state
def tools(state: CLIState, as_json: bool, detailed: bool) -> None:
    """List available MCP tools."""
    try:
        tool_schemas = XHS_TOOL_SCHEMAS

        if as_json:
            if detailed:
                click.echo(json.dumps(tool_schemas, ensure_ascii=False, indent=2))
            else:
                click.echo(
                    json.dumps(
                        [
                            {"name": t["name"], "description": t["description"]}
                            for t in tool_schemas
                        ],
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return

        click.echo("\n📋 Available MCP Tools:\n")

        for index, tool in enumerate(tool_schemas, start=1):
            click.echo(f"{index}. {tool['name']}")
            click.echo(f"   {tool['description']}")

            if detailed:
                required = tool["inputSchema"].get("required", [])
                properties = tool["inputSchema"].get("properties", {})

                if properties:
                    click.echo("   Parameters:")
                    for key, prop in properties.items():
                        mark = " (required)" if key in required else " (optional)"
                        click.echo(
                            f"     - {key}: {prop.get('description', 'No description')}{mark}"
                        )
            click.echo("")

        click.echo(f"Total: {len(tool_schemas)} tools available")
        click.echo("\nUse --detailed for parameter information")
        click.echo("Use --json for machine-readable output")
    except SystemExit:
        raise
    except BaseException as error:  # noqa: BLE001
        print_error(state, error)


def main() -> None:
    try:
        cli(obj=CLIState())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
