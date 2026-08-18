from __future__ import annotations

import asyncio
import re
from pathlib import Path


class GitHubService:
    def __init__(self, repo_path: str, gh_token: str = ""):
        self.repo_path = Path(repo_path)
        self.gh_token = gh_token

    def _env(self) -> dict:
        env = {}
        if self.gh_token:
            env["GITHUB_TOKEN"] = self.gh_token
        return env

    async def create_pr(
        self, title: str, body: str, base_branch: str,
        head_branch: str, reviewer: str = "", labels: list[str] | None = None,
    ) -> dict:
        cmd = [
            "gh", "pr", "create",
            "--title", title, "--body", body,
            "--base", base_branch, "--head", head_branch,
        ]
        if reviewer:
            cmd.extend(["--reviewer", reviewer])
        if labels:
            for label in labels:
                cmd.extend(["--label", label])

        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.repo_path),
            env={**__import__("os").environ, **self._env()},
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode().strip()
        pr_url = ""
        m = re.search(r"(https://github\.com/\S+/pull/\d+)", output)
        if m:
            pr_url = m.group(1)

        return {
            "status": "created" if proc.returncode == 0 else "failed",
            "pr_url": pr_url,
            "branch": head_branch,
            "error": stderr.decode() if proc.returncode != 0 else "",
        }
