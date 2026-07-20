"""Filesystem browser for the run-launch directory picker.

Localhost-only, like the rest of the app: it lets the UI navigate the local
filesystem to choose a repository directory without hand-typing a path (and
without needing PROJECT_ROOTS configured).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..schemas import FsEntry, FsListing

router = APIRouter(prefix="/api/fs", tags=["fs"])


def _is_git_repo(path: Path) -> bool:
    try:
        return (path / ".git").exists()
    except OSError:
        return False


@router.get("/list", response_model=FsListing)
async def list_dir(path: str | None = None) -> FsListing:
    """List the subdirectories of `path` (defaults to the user's home dir)."""
    try:
        target = (Path(path).expanduser() if path else Path.home()).resolve()
    except OSError as exc:
        raise HTTPException(400, f"invalid path: {exc}") from exc
    if not target.is_dir():
        raise HTTPException(400, f"not a directory: {target}")
    try:
        children = sorted(
            (child for child in target.iterdir() if child.is_dir()),
            key=lambda child: child.name.lower(),
        )
    except PermissionError as exc:
        raise HTTPException(403, f"permission denied: {target}") from exc
    parent = str(target.parent) if target.parent != target else None
    return FsListing(
        path=str(target),
        parent=parent,
        is_git_repo=_is_git_repo(target),
        entries=[
            FsEntry(name=child.name, path=str(child), is_git_repo=_is_git_repo(child))
            for child in children
        ],
    )
