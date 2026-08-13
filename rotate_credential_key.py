"""Offline provider credential key rotation utility."""

import argparse
import json
from pathlib import Path

from credential_crypto import rotate_password


def main():
    parser = argparse.ArgumentParser(description="Rotate encrypted playlist credentials in a database export JSON file.")
    parser.add_argument("input", type=Path, help="JSON array containing playlist detail objects")
    parser.add_argument("output", type=Path, help="New JSON file; must not already exist")
    parser.add_argument("--old-key-file", required=True, type=Path)
    parser.add_argument("--new-key-file", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Output already exists; refusing to overwrite it")
    old_key = args.old_key_file.read_text(encoding="ascii").strip()
    new_key = args.new_key_file.read_text(encoding="ascii").strip()
    records = json.loads(args.input.read_text(encoding="utf-8"))
    for record in records:
        rotate_password(record, old_key, new_key)
    args.output.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
