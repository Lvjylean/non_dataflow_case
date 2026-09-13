#!/usr/bin/env python3
"""Refresh exact .gitignore paths for untracked files larger than 50 MiB."""
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
limit = 50 * 1024 * 1024
output = subprocess.check_output(
    ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=root
)
ignore = root / ".gitignore"
start = "# BEGIN GENERATED LARGE FILES\n"
end = "# END GENERATED LARGE FILES"
content = ignore.read_text()
before, tail = content.split(start, 1)
existing, after = tail.split(end, 1)
entries = set(existing.splitlines())
for raw in output.split(b"\0"):
    if not raw:
        continue
    rel = os.fsdecode(raw)
    path = root / rel
    if path.is_symlink() or not path.is_file():
        continue
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        continue
    if size <= limit:
        continue
    if "\n" in rel or "\r" in rel:
        raise SystemExit("Cannot encode a newline in a gitignore path")
    escaped = "".join("\\" + c if c in "\\*?[] !#" else c for c in rel)
    entries.add("/" + escaped)
ignore.write_text(before + start + "".join(x + "\n" for x in sorted(entries) if x) + end + after)
print(f"Maintaining {len(entries)} explicit large-file exclusions (limit: 50 MiB).")
