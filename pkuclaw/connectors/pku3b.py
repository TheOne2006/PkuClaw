from __future__ import annotations

import subprocess
from pathlib import Path


class Pku3b:
    def __init__(self, bin_path: str | Path = "crates/pku3b/target/debug/pku3b") -> None:
        self.bin_path = Path(bin_path)

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        if not self.bin_path.exists():
            raise FileNotFoundError(f"pku3b binary not found: {self.bin_path}")
        return subprocess.run(
            [str(self.bin_path), *args],
            check=False,
            text=True,
            capture_output=True,
        )
