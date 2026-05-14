from __future__ import annotations

import argparse
import csv
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "human_eval_site" / "data"
THEME_CATALOG_PATH = DATA_ROOT / "theme_catalog.json"
INVITE_TOKENS_PATH = DATA_ROOT / "invite_tokens.json"
INVITE_LINKS_CSV = DATA_ROOT / "invite_links.csv"

MODES = ("image", "text")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_catalog() -> dict:
    return json.loads(THEME_CATALOG_PATH.read_text(encoding="utf-8-sig"))


def build_invite(base_url: str, token: str, mode: str) -> str:
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}token={token}&mode={mode}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate invite tokens for human eval site.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000/", help="Base URL of deployed/local site.")
    parser.add_argument("--raters-per-theme", type=int, default=1, help="Invite count per mode per theme.")
    parser.add_argument("--batch-prefix", default="prod", help="Batch ID prefix.")
    args = parser.parse_args()

    catalog = load_catalog()
    created_at = utc_now_iso()

    tokens = []
    for mode in MODES:
        batch_id = f"{args.batch_prefix}_{mode}_{created_at[:10].replace('-', '')}"
        for theme in catalog["themes"]:
            for slot_index in range(1, args.raters_per_theme + 1):
                token = secrets.token_urlsafe(10)
                tokens.append(
                    {
                        "token": token,
                        "themeId": theme["themeId"],
                        "themeTitle": theme["title"],
                        "mode": mode,
                        "slotIndex": slot_index,
                        "batchId": batch_id,
                        "createdAt": created_at,
                        "claimedAt": None,
                        "submittedAt": None,
                        "submissionCount": 0,
                        "evaluatorId": "",
                        "inviteUrl": build_invite(args.base_url.rstrip("/"), token, mode),
                    }
                )

    payload = {"updatedAt": created_at, "tokens": tokens}
    INVITE_TOKENS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with INVITE_LINKS_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["token", "themeId", "themeTitle", "mode", "slotIndex", "batchId", "inviteUrl"],
        )
        writer.writeheader()
        for item in tokens:
            writer.writerow(
                {
                    "token": item["token"],
                    "themeId": item["themeId"],
                    "themeTitle": item["themeTitle"],
                    "mode": item["mode"],
                    "slotIndex": item["slotIndex"],
                    "batchId": item["batchId"],
                    "inviteUrl": item["inviteUrl"],
                }
            )

    print(f"Wrote {len(tokens)} invite links to {INVITE_TOKENS_PATH}")
    print(f"Wrote CSV summary to {INVITE_LINKS_CSV}")


if __name__ == "__main__":
    main()

