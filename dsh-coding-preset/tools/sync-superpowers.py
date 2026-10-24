#!/usr/bin/env python3
"""Vendor the superpowers skills into this preset's `supo-skills/` tree.

This is the Python port of pi-packages/pi-superpowers's
`scripts/download-skills.mjs`, with the destination moved to a directory this
package owns (`supo-skills/`) instead of the shared skills root. Keeping the
vendored copy separate from `.agents/skills/` (which the skills CLI manages)
means the whole directory can be pruned on every sync. Everything else is
carried over unchanged:

  * `supo.config.json` pins the upstream repo, ref and skill list;
  * the repo is cached under the system temp dir and cloned / fetched only when
    the cache is missing or not at the requested ref;
  * every skill is copied to `supo-skills/supo-<name>/` with the `supo-` prefix
    added to its frontmatter `name`, to `superpowers:<skill>` cross-references
    and to relative `../<skill>` cross-skill paths;
  * `.skills-ref` records the ref that was last synced, so an unchanged ref
    with all skills present skips the copy / rewrite step;
  * directories in `supo-skills/` whose skill is no longer listed in
    `supo.config.json` are removed (`.agents/skills/` is never touched).

Usage:

    uv run tools/sync-superpowers.py
    python3 tools/sync-superpowers.py

Requires only the Python standard library and git.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "supo.config.json"
SKILLS_REF_PATH = ROOT / ".skills-ref"
CACHE_DIR = Path(tempfile.gettempdir()) / "dsh-coding-preset-superpowers-cache"
SKILLS_DIR = ROOT / "supo-skills"

PREFIX = "supo-"
SKILL_REFERENCE = re.compile(r"superpowers:([a-z][a-z0-9-]*)")
# Text files that may hold cross-skill references ("" = extensionless scripts).
TEXT_FILE_SUFFIXES = {"", ".md", ".js", ".cjs", ".ts", ".sh", ".dot", ".html"}


def log(message: str) -> None:
    print(message, flush=True)


def run_git(*args: str, cwd: Path | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def git(*args: str, cwd: Path | None = None, capture: bool = False) -> str:
    """Run git, raising a terse SystemExit when it fails."""
    result = run_git(*args, cwd=cwd, capture=capture)
    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        raise SystemExit(f"git {' '.join(args)} failed{': ' + detail if detail else ''}")
    return (result.stdout or "").strip() if capture else ""


def read_config() -> dict:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except OSError as error:
        raise SystemExit(f"cannot read {CONFIG_PATH}: {error}") from error
    except json.JSONDecodeError as error:
        raise SystemExit(f"invalid {CONFIG_PATH.name}: {error}") from error
    if (
        not isinstance(config, dict)
        or not isinstance(config.get("repo"), str)
        or not isinstance(config.get("ref"), str)
        or not isinstance(config.get("skills"), list)
        or not all(isinstance(name, str) for name in config["skills"])
    ):
        raise SystemExit(f"invalid {CONFIG_PATH.name}: must have repo, ref, and skills array of strings")
    return config


def clone_or_pull(repo: str, ref: str) -> None:
    # A cache without .git cannot be fetched; start over instead of failing.
    if CACHE_DIR.exists() and not (CACHE_DIR / ".git").exists():
        log("[cache] Corrupted cache (no .git), removing and re-cloning...")
        shutil.rmtree(CACHE_DIR)

    if not CACHE_DIR.exists():
        log(f"[cache] Cloning {repo} (ref: {ref})...")
        git("clone", "--branch", ref, repo, str(CACHE_DIR))
        return

    log("[cache] Fetching updates...")
    git("fetch", "origin", "--tags", cwd=CACHE_DIR)

    # Resolve the target ref to a commit hash, accepting tags and branches.
    tag = run_git("rev-parse", "--verify", "--quiet", f"refs/tags/{ref}^{{}}", cwd=CACHE_DIR, capture=True)
    if tag.returncode == 0:
        is_tag = True
        target_hash = tag.stdout.strip()
    else:
        branch = run_git("rev-parse", "--verify", "--quiet", f"origin/{ref}", cwd=CACHE_DIR, capture=True)
        if branch.returncode != 0:
            print(f'[error] Cannot resolve ref "{ref}" as a tag or an origin branch. Is the ref valid?', file=sys.stderr)
            raise SystemExit(1)
        is_tag = False
        target_hash = branch.stdout.strip()

    current_hash = git("rev-parse", "HEAD", cwd=CACHE_DIR, capture=True)
    if current_hash == target_hash:
        log(f"[cache] Already at {ref} ({target_hash[:7]}), up to date.")
        return

    # Switching refs with local dirt in the way is never intended.
    log(f"[cache] Switching to {ref} ({target_hash[:7]})...")
    git("reset", "--hard", "HEAD", cwd=CACHE_DIR)
    git("clean", "-fd", cwd=CACHE_DIR)

    git("checkout", ref, cwd=CACHE_DIR)
    if not is_tag:
        git("pull", "--ff-only", cwd=CACHE_DIR)


def relative_skill_path_pattern(skill_names: list[str]) -> re.Pattern[str]:
    """Match `../<skill>` pointing at a tracked skill, not `../<skill>-extra`."""
    alternation = "|".join(re.escape(name) for name in skill_names)
    return re.compile(rf"(\.\./)({alternation})(?![a-zA-Z0-9._-])")


def rewrite_frontmatter_name(content: str, name: str) -> str:
    """Replace `name:` inside the first `---` block, leaving the body alone."""
    parts = content.split("---")
    if len(parts) < 3:
        return content
    parts[1] = re.sub(
        r"^name:\s*(.+)$",
        f"name: {PREFIX}{name}",
        parts[1],
        count=1,
        flags=re.MULTILINE,
    )
    return "---".join(parts)


def transform_skill(name: str, cache_skills_dir: Path, relative_skill_path: re.Pattern[str]) -> bool:
    src = cache_skills_dir / name
    dest = SKILLS_DIR / f"{PREFIX}{name}"

    # Check before copying: a half-copied skill without SKILL.md is invisible to
    # the provider and would be worse than skipping the skill.
    if not (src / "SKILL.md").is_file():
        log(f"[warn] No SKILL.md found in {name}, skipping")
        return False

    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)

    for path in sorted(dest.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT_FILE_SUFFIXES:
            continue
        relative = path.relative_to(dest)
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            log(f"[warn] {name}/{relative} is not UTF-8, left untouched")
            continue

        if relative == Path("SKILL.md"):
            content = rewrite_frontmatter_name(content, name)

        if path.suffix == ".md":
            # Body cross-references: superpowers:<skill> -> supo-<skill>.
            content = SKILL_REFERENCE.sub(rf"{PREFIX}\1", content)

        # Cross-skill relative paths must follow the prefixed directory.
        content = relative_skill_path.sub(lambda match: f"{match.group(1)}{PREFIX}{match.group(2)}", content)

        path.write_text(content, encoding="utf-8")

    log(f"[done] {name} → {PREFIX}{name}")
    return True


def clean_stale(config_skills: list[str]) -> None:
    """Remove directories from the sync-owned root that the config dropped.

    `supo-skills/` exists only for vendored superpowers skills, so anything the
    config does not name is stale - no prefix filter needed. `.agents/skills/`
    belongs to the skills CLI and is never touched here.
    """
    if not SKILLS_DIR.is_dir():
        return
    expected = {f"{PREFIX}{name}" for name in config_skills}
    for entry in sorted(SKILLS_DIR.iterdir()):
        if not entry.is_dir() or entry.name in expected:
            continue
        log(f"[clean] Removing stale skill: {entry.name}")
        shutil.rmtree(entry)


def main() -> int:
    config = read_config()
    repo, ref, skills = config["repo"], config["ref"], config["skills"]

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    # Clone or pull; skips git operations when the cache is already at the ref.
    clone_or_pull(repo, ref)

    cached_ref = SKILLS_REF_PATH.read_text(encoding="utf-8").strip() if SKILLS_REF_PATH.is_file() else None
    up_to_date = cached_ref == ref and all(
        (SKILLS_DIR / f"{PREFIX}{name}" / "SKILL.md").is_file() for name in skills
    )
    if up_to_date:
        log(f"[skills] Already up to date for ref {ref}, skipping transform.")
        clean_stale(skills)
        log(f"\nDone! {len(skills)} skills (no changes needed).")
        return 0

    cache_skills_dir = CACHE_DIR / "skills"
    relative_skill_path = relative_skill_path_pattern(skills)
    processed = 0
    for name in skills:
        if not (cache_skills_dir / name).is_dir():
            log(f'[warn] Skill "{name}" not found in upstream, skipping')
            continue
        if transform_skill(name, cache_skills_dir, relative_skill_path):
            processed += 1

    # Record the ref only after the tree was written, so a partial run redoes it.
    SKILLS_REF_PATH.write_text(ref + "\n", encoding="utf-8")

    clean_stale(skills)

    log(f"\nDone! {processed} skills processed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
