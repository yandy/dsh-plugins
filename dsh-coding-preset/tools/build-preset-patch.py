#!/usr/bin/env python3
"""Regenerate cordis.patch.yml from a shipped preset plus preset.delta.yml.

The Loader has no preset inheritance: a patched row's `config` is replaced
wholesale, and rows inside another preset's plugin list are not addressable by
patches at all. So a derived preset has to restate its baseline. This tool does
the restating mechanically instead of by hand:

  * it locates the baseline preset patch shipped by a bundle;
  * it copies every baseline row verbatim, substituting the rows that the delta
    replaces and inserting the rows it appends;
  * it writes the generated patch with a content hash of the baseline, so
    `--check` fails whenever the installation's baseline changes.

Usage:

    python3 tools/build-preset-patch.py             # rewrite cordis.patch.yml
    python3 tools/build-preset-patch.py --check      # verify, exit 1 on drift
    python3 tools/build-preset-patch.py --print      # write to stdout
    python3 tools/build-preset-patch.py --baseline PATH

Requires PyYAML.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DELTA_PATH = ROOT / "preset.delta.yml"
TARGET_PATH = ROOT / "cordis.patch.yml"

ROW_ID = re.compile(r"^(\s*)- id: (\S+)\s*$")
KEY = re.compile(r"^(\s*)([A-Za-z0-9_]+):\s*(.*)$")


class JsExpr(str):
    """A `!!js` scalar: preserved as a string, never evaluated here."""


class EntryLoader(yaml.SafeLoader):
    """Read entry lists carrying DSH's `!!js` tag."""


EntryLoader.add_constructor("tag:yaml.org,2002:js", lambda loader, node: JsExpr(loader.construct_scalar(node)))


def load_yaml(path: Path):
    with path.open(encoding="utf-8") as handle:
        return yaml.load(handle, Loader=EntryLoader)


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def scalar(value) -> str:
    """Render one YAML scalar, quoted only when YAML requires it."""
    if isinstance(value, JsExpr):
        return str(value)
    rendered = yaml.safe_dump({"v": value}, allow_unicode=True, width=10**6).strip()
    if rendered.startswith("v: ") and "\n" not in rendered:
        return rendered[3:]
    return json.dumps(value, ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def baseline_candidates(bundle: str, preset: str):
    """Yield plausible paths of `<bundle>/presets/<preset>.patch.yml`, best first."""
    relative = Path("node_modules") / bundle / "presets" / f"{preset}.patch.yml"
    seen: set[Path] = set()

    def offer(path: Path):
        if path not in seen:
            seen.add(path)
            return path
        return None

    homes = []
    home = Path(os.environ.get("DSH_HOME") or Path.home() / ".dsh")
    homes.append(home)
    profiles = home / "profiles"
    if profiles.is_dir():
        homes.extend(sorted(entry for entry in profiles.iterdir() if entry.is_dir()))
    homes.append(ROOT)

    for base in homes:
        cursor = base
        while True:
            candidate = offer(cursor / relative)
            if candidate is not None:
                yield candidate
            if cursor.parent == cursor:
                break
            cursor = cursor.parent

    # npx and pnpm caches, plus the installation that owns the `dsh` on PATH.
    for cached in sorted(Path.home().glob(".npm/_npx/*/node_modules")) + sorted(Path.home().glob(".local/share/pnpm/global/*/node_modules")):
        candidate = offer(cached / bundle / "presets" / f"{preset}.patch.yml")
        if candidate is not None:
            yield candidate
    executable = shutil.which("dsh")
    if executable is not None:
        resolved = Path(executable).resolve()
        for parent in resolved.parents:
            if parent.name == "node_modules":
                candidate = offer(parent / bundle / "presets" / f"{preset}.patch.yml")
                if candidate is not None:
                    yield candidate
                break


def find_baseline(bundle: str, preset: str, explicit: str | None) -> Path:
    if explicit is not None:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"baseline patch not found: {path}")
        return path
    for candidate in baseline_candidates(bundle, preset):
        if candidate.is_file():
            return candidate
    raise SystemExit(
        f"cannot locate {bundle}/presets/{preset}.patch.yml; pass --baseline /path/to/that/file"
    )


def locate_preset_row(lines: list[str], row_id: str) -> tuple[int, int]:
    """Return the half-open line range of the `- id: <row_id>` item."""
    start = None
    for index, line in enumerate(lines):
        match = ROW_ID.match(line)
        if match is not None and match.group(2) == row_id:
            start = index
            break
    if start is None:
        raise SystemExit(f"baseline has no preset row {row_id!r}")
    row_indent = indent_of(lines[start])
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() == "":
            continue
        if indent_of(line) <= row_indent:
            end = index
            break
    return start, end


def split_plugin_rows(lines: list[str], plugins_key: int, row_end: int) -> tuple[int, list[list[str]]]:
    """Split the `plugins:` list into top-level row chunks."""
    key_indent = indent_of(lines[plugins_key])
    first = plugins_key + 1
    while first < row_end and lines[first].strip() == "":
        first += 1
    if first >= row_end or indent_of(lines[first]) <= key_indent:
        raise SystemExit("baseline preset declares an empty plugins list")
    item_indent = indent_of(lines[first])
    chunks: list[list[str]] = []
    current: list[str] = []
    for index in range(first, row_end):
        line = lines[index]
        if line.strip() == "":
            current.append(line)
            continue
        if indent_of(line) == item_indent and line.lstrip().startswith("- "):
            if current:
                chunks.append(current)
            current = [line]
            continue
        if indent_of(line) < item_indent:
            break
        current.append(line)
    if current:
        chunks.append(current)
    return item_indent, chunks


def chunk_id(chunk: list[str]) -> str:
    for line in chunk:
        match = ROW_ID.match(line)
        if match is not None:
            return match.group(2)
    raise SystemExit(f"plugin row has no id: {chunk[0]!r}")


def reindent(fragment: str, width: int) -> list[str]:
    """Shift a delta fragment to the plugin list's indentation."""
    body = fragment.rstrip("\n")
    if body.strip() == "":
        return []
    return [(" " * width + line) if line.strip() else "" for line in body.split("\n")]


def render(delta: dict, baseline_path: Path, baseline_text: str) -> str:
    bundle = delta["baseline"]["bundle"]
    baseline_preset = delta["baseline"]["preset"]
    preset = delta["preset"]
    replace = {str(key): value for key, value in (delta.get("replace") or {}).items()}
    append = delta.get("append") or {}

    baseline_row = delta["baseline"].get("row") or f"preset-{baseline_preset}"

    lines = baseline_text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    row_start, row_end = locate_preset_row(lines, baseline_row)

    plugins_key = None
    for index in range(row_start, row_end):
        match = KEY.match(lines[index])
        if match is not None and match.group(2) == "plugins" and match.group(3) == "":
            plugins_key = index
            break
    if plugins_key is None:
        raise SystemExit(f"baseline preset {baseline_row!r} declares no plugins list")

    item_indent, chunks = split_plugin_rows(lines, plugins_key, row_end)
    row_indent = indent_of(lines[row_start])
    row_field = row_indent + 2
    config_field = row_field + 2
    # `plugins` is a direct child of `config`, alongside `id` and `order`.
    plugins_field = config_field

    # The preset plugin name comes from the baseline so a package rename upstream
    # is carried over instead of hidden.
    plugin_name = None
    for index in range(row_start, plugins_key):
        match = KEY.match(lines[index])
        if match is not None and match.group(2) == "name":
            plugin_name = match.group(3).strip()
    if plugin_name is None:
        raise SystemExit(f"baseline preset {baseline_row!r} declares no plugin name")

    seen = [chunk_id(chunk) for chunk in chunks]
    unknown = sorted(set(replace) - set(seen))
    if unknown:
        raise SystemExit(f"replace names rows the baseline does not have: {', '.join(unknown)}")
    append_after = append.get("after")
    if append and append_after not in (None, "end") and append_after not in seen:
        raise SystemExit(f"append.after names a row the baseline does not have: {append_after}")

    header = [
        f"# Generated by tools/build-preset-patch.py — do not edit by hand.",
        f"# baseline: {bundle}/presets/{baseline_preset}.patch.yml (sha256 {sha256_text(baseline_text)[:16]})",
        f"# delta:    preset.delta.yml",
        "#",
        f"# Every row below is copied verbatim from the baseline unless preset.delta.yml",
        f"# restates it. Re-run the tool after a DSH upgrade and review the diff;",
        f"# `--check` fails while cordis.patch.yml is stale.",
    ]

    insert_start = 0
    for index, line in enumerate(lines[:row_start]):
        if line.startswith("- insert:"):
            insert_start = index
            break

    out: list[str] = list(header)
    out.extend(lines[insert_start:row_start])
    out.append(f"{' ' * row_indent}- id: {preset['row']}")
    out.append(f"{' ' * row_field}name: {plugin_name}")
    out.append(f"{' ' * row_field}config:")
    out.append(f"{' ' * config_field}id: {scalar(preset['id'])}")
    if preset.get("name") is not None:
        out.append(f"{' ' * config_field}name: {scalar(preset['name'])}")
    if preset.get("description") is not None:
        out.append(f"{' ' * config_field}description: {scalar(preset['description'])}")
    if preset.get("order") is not None:
        out.append(f"{' ' * config_field}order: {scalar(preset['order'])}")
    out.append(f"{' ' * plugins_field}plugins:")

    appended = False
    for chunk in chunks:
        row_id = chunk_id(chunk)
        if row_id in replace:
            out.extend(reindent(replace[row_id], item_indent))
        else:
            out.extend(chunk)
        if append and append_after == row_id:
            out.extend(reindent(append.get("rows") or "", item_indent))
            appended = True
    if append and append_after in (None, "end"):
        out.extend(reindent(append.get("rows") or "", item_indent))
        appended = True
    if append and not appended:
        raise SystemExit("append.rows produced nothing")

    out.extend(lines[row_end:])
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


def plugin_ids(text: str) -> tuple[str, list[str]]:
    """Read a generated patch's preset id and flattened plugin row ids."""
    document = yaml.load(text, Loader=EntryLoader)
    row = document[0]["insert"][0]
    config = row["config"]
    ids: list[str] = []

    def walk(rows):
        for entry in rows:
            ids.append(entry["id"])
            if entry.get("group") is True:
                walk(entry.get("config") or [])

    walk(config["plugins"])
    return config["id"], ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="compare with cordis.patch.yml and exit non-zero when it differs")
    parser.add_argument("--print", dest="to_stdout", action="store_true", help="write the result to stdout")
    parser.add_argument("--baseline", help="explicit path to the baseline preset patch")
    parser.add_argument("--delta", default=str(DELTA_PATH), help="delta file (default: preset.delta.yml)")
    args = parser.parse_args()

    delta_path = Path(args.delta).expanduser().resolve()
    delta = load_yaml(delta_path)
    baseline_path = find_baseline(delta["baseline"]["bundle"], delta["baseline"]["preset"], args.baseline)
    baseline_text = baseline_path.read_text(encoding="utf-8")
    generated = render(delta, baseline_path, baseline_text)

    preset_id, ids = plugin_ids(generated)
    if preset_id != delta["preset"]["id"]:
        raise SystemExit(f"generated preset id {preset_id!r} does not match the delta")
    if len(ids) != len(set(ids)):
        raise SystemExit("generated patch repeats a plugin row id")

    if args.to_stdout:
        sys.stdout.write(generated)
        return 0

    current = TARGET_PATH.read_text(encoding="utf-8") if TARGET_PATH.is_file() else None
    if args.check:
        if current == generated:
            print(f"{TARGET_PATH.name} is up to date with {baseline_path}")
            return 0
        print(f"{TARGET_PATH.name} differs from the generated patch:", file=sys.stderr)
        diff = difflib.unified_diff(
            (current or "").split("\n"), generated.split("\n"),
            fromfile="cordis.patch.yml (on disk)", tofile="generated", lineterm="",
        )
        for line in list(diff)[:80]:
            print(line, file=sys.stderr)
        return 1

    TARGET_PATH.write_text(generated, encoding="utf-8")
    print(f"wrote {TARGET_PATH} from {baseline_path}")
    print(f"preset {preset_id}: {len(ids)} plugin rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
