"""Create or reset users for the simulator login.

Usage:
  python manage_users.py add  email1 [email2 ...]   # generates a random password for each
  python manage_users.py remove email
  python manage_users.py list

Only password hashes are stored in users.json (safe to commit).
Generated passwords are appended to credentials.local.txt (git-ignored) - share them privately.
"""
import json
import secrets
import string
import sys
from datetime import datetime
from pathlib import Path

from app.auth import USERS_FILE, hash_password, load_users

CREDENTIALS_FILE = Path(__file__).resolve().parent / "credentials.local.txt"
ALPHABET = string.ascii_letters + string.digits


def generate_password(length: int = 14) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def save(users: dict) -> None:
    USERS_FILE.write_text(json.dumps(users, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("add", "remove", "list"):
        print(__doc__)
        sys.exit(1)
    cmd, emails = sys.argv[1], [e.strip().lower() for e in sys.argv[2:]]
    users = load_users()

    if cmd == "list":
        print("\n".join(sorted(users)) or "(no users)")
    elif cmd == "remove":
        for e in emails:
            print(f"removed {e}" if users.pop(e, None) else f"not found {e}")
        save(users)
    else:
        lines = [f"# Generated {datetime.now():%Y-%m-%d %H:%M}"]
        for e in emails:
            pwd = generate_password()
            users[e] = hash_password(pwd)
            lines.append(f"{e}\t{pwd}")
            print(f"created/reset {e}")
        save(users)
        with CREDENTIALS_FILE.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n\n")
        print(f"Passwords written to {CREDENTIALS_FILE.name}")


if __name__ == "__main__":
    main()
