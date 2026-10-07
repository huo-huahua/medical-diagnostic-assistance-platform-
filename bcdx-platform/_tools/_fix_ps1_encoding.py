"""Normalise a .ps1 file so Windows PowerShell 5.1 reads its non-ASCII text correctly.

Windows PowerShell 5.1 decodes a script as ANSI unless the file starts with a
UTF-8 BOM. Without the BOM the Chinese output strings come out as mojibake,
which is worse than English. CRLF is also used, matching Windows convention.

Run:  python _tools/_fix_ps1_encoding.py scripts/verify-docker.ps1
"""

from __future__ import annotations

import sys
from pathlib import Path

BOM = b"\xef\xbb\xbf"


def normalise(path: Path) -> None:
    raw = path.read_bytes()
    had_bom = raw.startswith(BOM)
    text = raw.decode("utf-8-sig")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    body = text.replace("\n", "\r\n").encode("utf-8")
    path.write_bytes(BOM + body)
    print(
        f"{path}: {len(raw)} -> {len(BOM) + len(body)} bytes, "
        f"BOM was {'present' if had_bom else 'missing'}, CRLF lines {body.count(b'\\r\\n')}"
    )


if __name__ == "__main__":
    targets = sys.argv[1:] or ["scripts/verify-docker.ps1"]
    for t in targets:
        normalise(Path(t))
