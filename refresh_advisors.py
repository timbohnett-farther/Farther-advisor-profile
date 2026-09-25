#!/usr/bin/env python3
"""
Pull the active Farther advisor roster from Sanity and save it to:

    data/advisors.json   full data, for Claude
    data/advisors.csv    same data, flat, opens in Excel

The files are only rewritten when the roster actually changed, so the
nightly job only makes a commit when something real happened.

Safety check: if the pull comes back empty, or the roster shrinks by more
than MAX_DROP_PERCENT since the last save, the script stops with an error
and writes nothing. GitHub emails you when a run fails. To accept a big
drop on purpose, run the workflow by hand with "force" checked.

Standard library only. Runs the same on GitHub, Mac, or Windows:
    python3 scripts/refresh_advisors.py          (Mac / GitHub)
    py scripts\\refresh_advisors.py              (Windows)
"""

import argparse
import csv
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ----------------------------------------------------------------------------
# Settings (override any of these with environment variables)
# ----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
QUERY_FILE = ROOT / "scripts" / "advisors.groq"
DATA_DIR = ROOT / "data"
JSON_OUT = DATA_DIR / "advisors.json"
CSV_OUT = DATA_DIR / "advisors.csv"

PROJECT_ID = os.environ.get("SANITY_PROJECT_ID", "c4sm4c5k")
DATASET = os.environ.get("SANITY_DATASET", "production")
API_VERSION = os.environ.get("SANITY_API_VERSION", "v2024-01-01")
MAX_DROP = float(os.environ.get("MAX_DROP_PERCENT", "15")) / 100
MIN_ADVISORS = int(os.environ.get("MIN_ADVISORS", "50"))
FORCE = os.environ.get("FORCE", "0") == "1"

# Sanity resizes and converts images on request. Most headshots are AVIF,
# which PowerPoint, Word and many older tools can't open, so we add JPG links.
HEADSHOT_JPG_PARAMS = "fm=jpg&q=90"
HEADSHOT_SQUARE_PARAMS = "w=600&h=600&fit=crop&fm=jpg&q=85"

# Parts of a name that look like designations but belong to the name.
NAME_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}

CSV_COLUMNS = [
    "display_name", "designations", "name_as_published", "title", "email",
    "phone", "phone_ext", "phone_display", "city", "state", "team_name",
    "team_url", "team_logo_url", "profile_url", "headshot_url",
    "headshot_jpg_url", "headshot_square_url", "credentials", "slug",
]


# ----------------------------------------------------------------------------
# Pull
# ----------------------------------------------------------------------------
def build_url(query: str) -> str:
    base = f"https://{PROJECT_ID}.apicdn.sanity.io/{API_VERSION}/data/query/{DATASET}"
    return f"{base}?query={urllib.parse.quote(query, safe='')}"


def fetch_roster(query: str) -> list:
    url = build_url(query)
    req = urllib.request.Request(url, headers={
        "User-Agent": "farther-advisor-roster-refresh/1.0",
        "Accept": "application/json",
    })
    last_error = None
    for attempt, wait in enumerate([0, 10, 30], start=1):
        if wait:
            print(f"Retrying in {wait}s (attempt {attempt} of 3)...")
            time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if "result" not in body or not isinstance(body["result"], list):
                raise ValueError(f"Unexpected response shape: keys={list(body)}")
            return body["result"]
        except (urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            print(f"Pull failed: {exc}")
    fail(f"Could not pull the roster from Sanity after 3 tries. Last error: {last_error}")


# ----------------------------------------------------------------------------
# Clean up
# ----------------------------------------------------------------------------
def split_name(full_name: str):
    """'Alan Gappinger, CLU®, ChFC®, CFP®' -> ('Alan Gappinger', ['CLU®', 'ChFC®', 'CFP®'])"""
    parts = [p.strip() for p in full_name.split(",")]
    suffixes, designations = [], []

    # 'Peter Sullivan CFP®, CPWA®' is missing a comma: peel marked
    # designations (® or ™) off the end of the name itself.
    base_tokens = parts[0].split()
    while len(base_tokens) > 1 and re.search(r"[®™]", base_tokens[-1]):
        designations.insert(0, base_tokens.pop())
    base = " ".join(base_tokens)

    for part in parts[1:]:
        for token in part.split():          # handles 'CFP® PhD' with a missing comma
            if token.lower() in NAME_SUFFIXES:
                suffixes.append(token)
            else:
                designations.append(token)
    display = base + (", " + " ".join(suffixes) if suffixes else "")
    return display, designations


def normalize_phone(raw):
    """Turn the ten different formats in Sanity into one.

    Returns (phone, ext, display), e.g. ('+19172102471', None, '(917) 210-2471').
    Anything that isn't a 10-digit US number is passed through untouched.
    """
    if not raw or not raw.strip():
        return None, None, None
    raw = raw.strip()
    ext = None
    match = re.search(r"(?:#|ext\.?|x)\s*(\d+)\s*$", raw, flags=re.IGNORECASE)
    main = raw
    if match:
        ext = match.group(1)
        main = raw[: match.start()]
    digits = re.sub(r"\D", "", main)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return raw, None, raw
    phone = "+1" + digits
    display = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    if ext:
        display += f" ext. {ext}"
    return phone, ext, display


def with_params(url, params):
    if not url:
        return None
    return url + ("&" if "?" in url else "?") + params


def clean_advisor(raw: dict) -> dict:
    name = (raw.get("name") or "").strip()
    display_name, designations = split_name(name)
    phone, phone_ext, phone_display = normalize_phone(raw.get("phone"))
    profile_url = raw.get("profileUrl")
    headshot = raw.get("headshotUrl")
    team = raw.get("team")
    return {
        "displayName": display_name,
        "designations": designations,
        "nameAsPublished": name,
        "title": raw.get("title"),
        "email": raw.get("email"),
        "phone": phone,
        "phoneExt": phone_ext,
        "phoneDisplay": phone_display,
        "city": raw.get("city"),
        "state": raw.get("state"),
        "team": {
            "name": team.get("name"),
            "url": team.get("url"),
            "logoUrl": team.get("logoUrl"),
        } if team else None,
        "profileUrl": profile_url,
        "headshotUrl": headshot,
        "headshotJpgUrl": with_params(headshot, HEADSHOT_JPG_PARAMS),
        "headshotSquareUrl": with_params(headshot, HEADSHOT_SQUARE_PARAMS),
        "credentials": raw.get("credentials") or [],
        "slug": profile_url.rstrip("/").rsplit("/", 1)[-1] if profile_url else None,
    }


# ----------------------------------------------------------------------------
# Compare with last save
# ----------------------------------------------------------------------------
def load_previous() -> list:
    if not JSON_OUT.exists():
        return []
    try:
        return json.loads(JSON_OUT.read_text(encoding="utf-8")).get("advisors", [])
    except (json.JSONDecodeError, AttributeError):
        print("Warning: existing advisors.json couldn't be read; treating this as a first run.")
        return []


def compare(old: list, new: list) -> dict:
    old_by_slug = {a["slug"]: a for a in old}
    new_by_slug = {a["slug"]: a for a in new}
    added = [new_by_slug[s]["displayName"] for s in new_by_slug if s not in old_by_slug]
    removed = [old_by_slug[s]["displayName"] for s in old_by_slug if s not in new_by_slug]
    changed = []
    for slug in new_by_slug.keys() & old_by_slug.keys():
        before, after = old_by_slug[slug], new_by_slug[slug]
        fields = [k for k in after if before.get(k) != after.get(k)]
        if fields:
            changed.append(f"{after['displayName']} ({', '.join(fields)})")
    return {"added": sorted(added), "removed": sorted(removed), "changed": sorted(changed)}


# ----------------------------------------------------------------------------
# Save
# ----------------------------------------------------------------------------
def write_json(advisors: list):
    payload = {
        "about": "Active Farther advisors, pulled nightly from the Sanity CMS behind farther.com.",
        "lastChanged": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(advisors),
        "advisors": advisors,
    }
    JSON_OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(advisors: list):
    # utf-8-sig so Excel shows ®, ™ and accented names correctly
    with CSV_OUT.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for a in advisors:
            team = a["team"] or {}
            writer.writerow({
                "display_name": a["displayName"],
                "designations": ", ".join(a["designations"]),
                "name_as_published": a["nameAsPublished"],
                "title": a["title"],
                "email": a["email"],
                "phone": a["phone"],
                "phone_ext": a["phoneExt"],
                "phone_display": a["phoneDisplay"],
                "city": a["city"],
                "state": a["state"],
                "team_name": team.get("name"),
                "team_url": team.get("url"),
                "team_logo_url": team.get("logoUrl"),
                "profile_url": a["profileUrl"],
                "headshot_url": a["headshotUrl"],
                "headshot_jpg_url": a["headshotJpgUrl"],
                "headshot_square_url": a["headshotSquareUrl"],
                "credentials": " | ".join(a["credentials"]),
                "slug": a["slug"],
            })


# ----------------------------------------------------------------------------
# GitHub Actions helpers
# ----------------------------------------------------------------------------
def set_output(key: str, value: str):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def add_summary(markdown: str):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(markdown + "\n")


def commit_message(diff: dict, total: int, first_run: bool) -> str:
    if first_run:
        return f"Roster: first pull, {total} active advisors"
    head = (f"Roster: +{len(diff['added'])} added, -{len(diff['removed'])} removed, "
            f"{len(diff['changed'])} updated ({total} active)")
    lines = [head, ""]
    for label in ("added", "removed", "changed"):
        if diff[label]:
            lines.append(f"{label.capitalize()}:")
            lines += [f"  - {item}" for item in diff[label]]
    return "\n".join(lines).rstrip() + "\n"


def fail(message: str):
    print(f"::error::{message}")
    add_summary(f"### Roster refresh stopped\n\n{message}")
    set_output("changed", "false")
    sys.exit(1)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-file", help="Use a saved Sanity response instead of pulling live (for testing).")
    args = parser.parse_args()

    if args.from_file:
        raw = json.loads(Path(args.from_file).read_text(encoding="utf-8"))["result"]
        print(f"Loaded {len(raw)} advisors from {args.from_file}")
    else:
        query = QUERY_FILE.read_text(encoding="utf-8")
        raw = fetch_roster(query)
        print(f"Pulled {len(raw)} active advisors from Sanity")

    advisors = [clean_advisor(a) for a in raw]

    missing = [a["nameAsPublished"] or "(no name)" for a in advisors if not a["slug"]]
    if missing:
        fail(f"{len(missing)} advisor(s) have no profile link, so they can't be tracked: {', '.join(missing[:10])}")
    slugs = [a["slug"] for a in advisors]
    dupes = sorted({s for s in slugs if slugs.count(s) > 1})
    if dupes:
        fail(f"Duplicate advisor profile links: {', '.join(dupes)}")

    advisors.sort(key=lambda a: (a["displayName"].lower(), a["slug"]))

    previous = load_previous()
    if len(advisors) < MIN_ADVISORS and not FORCE:
        fail(f"Only {len(advisors)} advisors came back (minimum is {MIN_ADVISORS}). Nothing was saved.")
    if previous and len(advisors) < len(previous) * (1 - MAX_DROP) and not FORCE:
        fail(f"Roster dropped from {len(previous)} to {len(advisors)}, more than {MAX_DROP:.0%}. "
             "Nothing was saved. If this is real, run the workflow by hand with 'force' checked.")

    if previous == advisors:
        print("No changes since the last save.")
        add_summary(f"### No roster changes\n\n{len(advisors)} active advisors, same as last run.")
        set_output("changed", "false")
        return

    diff = compare(previous, advisors)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_json(advisors)
    write_csv(advisors)

    message = commit_message(diff, len(advisors), first_run=not previous)
    msg_path = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())) / "commit_msg.txt"
    msg_path.write_text(message, encoding="utf-8")

    print(message)
    add_summary("### Roster updated\n\n```\n" + message + "```")
    set_output("changed", "true")


if __name__ == "__main__":
    main()
