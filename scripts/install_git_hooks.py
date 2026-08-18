"""Instala os hooks versionados do DecisionsSearch no repositório atual."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def install(repo: str | Path = ".") -> Path:
    root = Path(repo).resolve()
    hook_dir = root / ".githooks"
    hook = hook_dir / "post-commit"
    if not hook.is_file():
        raise FileNotFoundError(f"Hook não encontrado: {hook}")
    subprocess.run(
        ["git", "config", "core.hooksPath", ".githooks"],
        cwd=root,
        check=True,
    )
    return hook


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    hook = install(args.repo)
    print(f"Hooks instalados em {hook.parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
