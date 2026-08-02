from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", "__pycache__", ".pytest_cache", ".engineering", "engineering-graphs", "graphify-out"}
PRIVATE_TERMS = [
    "ka" + "ka",
    "phi" + "lips",
    "requirements[ _-]?" + "agent",
    "ar" + "nab",
    "abis" + "was",
    "tm" + "id",
    "office " + "automations",
]
PATTERNS = {
    "personal path": re.compile(
        r"(?i)(?:[a-z]:\\" + "us" + r"ers\\[^<\\/]+|/(?:" + "us" + "ers|" + "ho" + r"me)/[^<\\/]+)"
    ),
    "email address": re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b"),
    "private identifier": re.compile(r"(?i)\b(?:" + "|".join(PRIVATE_TERMS) + r")\b"),
    "credential-shaped value": re.compile(r"\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})\b"),
}


def files() -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        check=True,
        capture_output=True,
    )
    return [ROOT / item for item in result.stdout.decode("utf-8").split("\0") if item]


def main() -> int:
    failures: list[str] = []
    for path in files():
        relative = path.relative_to(ROOT)
        if any(part in SKIP_PARTS for part in relative.parts) or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.append(f"{relative.as_posix()}: non-UTF-8 tracked file")
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                failures.append(f"{relative.as_posix()}: {label}")
    if failures:
        print("sensitive-data check failed")
        print("\n".join(sorted(failures)))
        return 1
    print("sensitive-data check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
