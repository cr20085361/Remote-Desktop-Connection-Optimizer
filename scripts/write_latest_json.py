"""Write dist/latest.json after a release build."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--setup", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    setup = Path(args.setup)
    payload = {
        "name": "远程桌面连接优化器",
        "version": args.version.strip().lstrip("vV"),
        "installer": f"RdpOptimizer-Setup-{args.version.strip().lstrip('vV')}.exe",
        "sha256": "",
        "size": 0,
        "notes": args.notes,
    }
    if setup.is_file():
        data = setup.read_bytes()
        payload["sha256"] = hashlib.sha256(data).hexdigest()
        payload["size"] = len(data)
        payload["installer"] = setup.name
        payload["url"] = (
            "https://github.com/cr20085361/Remote-Desktop-Connection-Optimizer"
            f"/releases/download/v{payload['version']}/{setup.name}"
        )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
