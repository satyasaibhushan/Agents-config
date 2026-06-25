#!/usr/bin/env python3
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "Skills"


def parse_github_tree_url(url):
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc != "github.com" or len(parts) < 5 or parts[2] != "tree":
        raise ValueError(
            "expected a GitHub tree URL like "
            "https://github.com/owner/repo/tree/ref/path/to/skill"
        )

    owner, repo, _, ref, *path_parts = parts
    if not path_parts:
        raise ValueError("GitHub tree URL must include a skill path")

    return f"{owner}/{repo}", ref, "/".join(path_parts)


def run(command):
    subprocess.run(command, check=True)


def import_skill(repo, ref, skill_path, name, force):
    skill_name = name or Path(skill_path).name
    dest = CANONICAL / skill_name

    if dest.exists() and not force:
        raise SystemExit(f"destination already exists: {dest}")

    with tempfile.TemporaryDirectory(prefix="agent-skill-") as tmp:
        checkout = Path(tmp) / "repo"
        run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--filter=blob:none",
                "--sparse",
                "--branch",
                ref,
                f"https://github.com/{repo}.git",
                str(checkout),
            ]
        )
        run(["git", "-C", str(checkout), "sparse-checkout", "set", skill_path])

        source = checkout / skill_path
        if not source.is_dir():
            raise SystemExit(f"skill path was not found after checkout: {skill_path}")
        if not (source / "SKILL.md").is_file():
            raise SystemExit(f"skill path does not contain SKILL.md: {skill_path}")

        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source, dest)

    print(f"Imported {repo}/{skill_path} to {dest}")


def main():
    parser = argparse.ArgumentParser(
        description="Import one skill directory from a GitHub repo into the canonical Skills folder."
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="GitHub tree URL, for example https://github.com/mattpocock/skills/tree/main/skills/in-progress/loop-me",
    )
    parser.add_argument("--repo", help="GitHub repo in owner/name form")
    parser.add_argument("--ref", default="main", help="Git ref to checkout when using --repo")
    parser.add_argument("--path", help="Path to the skill directory when using --repo")
    parser.add_argument("--name", help="Destination skill folder name. Defaults to the path basename.")
    parser.add_argument("--force", action="store_true", help="Replace an existing canonical skill folder.")
    args = parser.parse_args()

    if args.url:
        repo, ref, skill_path = parse_github_tree_url(args.url)
        if args.repo or args.path:
            raise SystemExit("pass either a URL or --repo/--path, not both")
    else:
        if not args.repo or not args.path:
            raise SystemExit("pass a GitHub tree URL or both --repo and --path")
        repo, ref, skill_path = args.repo, args.ref, args.path

    os.makedirs(CANONICAL, exist_ok=True)
    import_skill(repo, ref, skill_path, args.name, args.force)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
