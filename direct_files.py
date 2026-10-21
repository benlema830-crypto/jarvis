"""Small direct file operations with explicit paths and no overwrite or deletion."""
import os
from pathlib import Path
import shutil

import cc_guard

HOME = Path(__file__).resolve().parent.parent
ROOTS = tuple(HOME / name for name in ("Desktop", "Documents", "Downloads", "OneDrive", "Pictures", "Videos", "Music"))


def checked(path):
    raw = Path(os.path.expandvars(os.path.expanduser(path)))
    if not raw.is_absolute():
        raise ValueError("Use a full path, not a relative path.")
    resolved = raw.resolve()
    if not any(resolved.is_relative_to(root.resolve()) for root in ROOTS):
        raise ValueError("Direct file operations are limited to your personal folders.")
    if cc_guard.decide("Read", {"file_path": str(resolved)})[0] != "allow":
        raise ValueError("That app's files are off-limits.")
    if any(part.lower() in (".git", ".ssh", ".aws", ".codex", ".venv", "node_modules") for part in resolved.parts):
        raise ValueError("Use a project agent for internal project or configuration folders.")
    return resolved


def operate(action, path, destination=""):
    if action not in ("list", "create_folder", "copy_file", "rename"):
        raise ValueError("Choose list, create_folder, copy_file or rename.")
    source = checked(path)
    if action == "list":
        if not source.is_dir():
            raise ValueError("That path is not a folder.")
        entries = []
        with os.scandir(source) as listing:
            for item in listing:
                try:
                    checked(item.path)
                except ValueError:
                    continue
                entries.append((item.name, "folder" if item.is_dir(follow_symlinks=False) else "file"))
                if len(entries) > 100:
                    break
        limited = len(entries) > 100
        return "\n".join(f"{kind}: {name}" for name, kind in sorted(entries[:100])) + ("\nMore items exist; narrow the folder." if limited else "") or "Folder is empty."
    if action == "create_folder":
        source.mkdir(parents=False, exist_ok=False)
        return f"Created folder {source.name}."
    target = checked(destination)
    if target.exists():
        raise FileExistsError("The destination already exists; nothing was overwritten.")
    if action == "rename":
        original = Path(os.path.expandvars(os.path.expanduser(path)))
        if original.is_symlink() or original.is_junction():
            raise ValueError("Use an agent to rename links or junctions explicitly.")
        if source.parent != target.parent:
            raise ValueError("Rename must stay in the same folder. Use an agent for moving files between folders.")
        if any(source == root.resolve() for root in ROOTS):
            raise ValueError("Personal root folders cannot be renamed by this tool.")
        # Windows rename refuses an existing destination, including a race after the check.
        source.rename(target)
        return f"Renamed {source.name} to {target.name}."
    if not source.is_file():
        raise ValueError("Copy supports individual files only.")
    if source.stat().st_size > 100 * 1024 * 1024:
        raise ValueError("Use a project agent to copy files larger than 100 MB.")
    with source.open("rb") as reader, target.open("xb") as writer:
        shutil.copyfileobj(reader, writer)
    return f"Copied {source.name} to {target.name}."
