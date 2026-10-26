"""Write the JSON reports into ``results/``."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json(directory: Path, filename: str, payload: dict[str, Any]) -> Path:
    """Write ``payload`` atomically so a crash never leaves half a report."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f".{filename}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.chmod(tmp_name, 0o644)  # mkstemp makes 0600; reports must be readable by other users
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return target
