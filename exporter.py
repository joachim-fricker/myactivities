#!/usr/bin/env python3
"""
my rewrite of garmin-export based on the https://github.com/cyberjunky/python-garminconnect library
"""

import argparse
import logging
import os
import sys
from datetime import date
from getpass import getpass
from pathlib import Path
import json
import time

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

# Suppress garminconnect library logging to avoid tracebacks in normal operation
logging.getLogger("garminconnect").setLevel(logging.CRITICAL)

EXPORT_DIR = Path("activities")
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
LAST_LOADED_FILE = EXPORT_DIR / "lastLoaded.txt"

PAGE_SIZE = 200


def safe_api_call(api_method, *args, **kwargs):
    """
    Safe API call wrapper with comprehensive error handling.
    Returns (success: bool, result: Any, error_message: str)
    """
    try:
        result = api_method(*args, **kwargs)
        return True, result, None

    except FileNotFoundError:
        return (
            False,
            None,
            "No valid tokens found. Please login with your email/password to create new tokens.",
        )

    except GarminConnectAuthenticationError as e:
        return False, None, f"Authentication issue: {e}"

    except GarminConnectConnectionError as e:
        return False, None, f"Connection issue: {e}"

    except GarminConnectTooManyRequestsError as e:
        return False, None, f"Rate limit exceeded: {e}"

    except Exception as e:
        return False, None, f"Unexpected error: {e}"


def get_credentials():
    """Get email and password from environment or user input."""
    email = os.getenv("EMAIL")
    password = os.getenv("PASSWORD")

    if not email:
        email = input("Login email: ")
    if not password:
        password = getpass("Enter password: ")

    return email, password


def init_api() -> Garmin | None:
    """Initialize Garmin API with authentication."""
    print("🔄 Logging in with credentials...")

    while True:
        try:
            email, password = get_credentials()

            tokenstore = os.getenv("GARMINTOKENS", "~/.garminconnect")
            tokenstore_path = str(Path(tokenstore).expanduser())

            garmin = Garmin(
                email=email, password=password, is_cn=False, return_on_mfa=True
            )

            result1, result2 = garmin.login()

            if result1 == "needs_mfa":
                print("🔐 Multi-factor authentication required in GitHub Actions.")
                print("💡 Tipp: Logge dich einmal lokal auf deinem PC ein und lade den Ordner .garminconnect hoch, damit MFA hier umgangen wird.")
                sys.exit(1)

            print("✅ Login successful!")
            return garmin

        except GarminConnectAuthenticationError:
            print("❌ Authentication failed: Please check your username and password.")
            continue

        except (
            FileNotFoundError,
            GarminConnectConnectionError,
        ) as err:
            print(f"❌ Connection error: {err}")
            return None

        except KeyboardInterrupt:
            print("\n👋 Cancelled by user")
            return None


def fetch_all_activities(api: Garmin, page_size=100, max_limit=None):
    """Generates activities up to max_limit if specified."""
    start = 0
    fetched_count = 0

    while True:
        current_page_size = page_size
        if max_limit is not None:
            remaining = max_limit - fetched_count
            if remaining <= 0:
                return
            if remaining < page_size:
                current_page_size = remaining

        success, activities, error = safe_api_call(
            api.get_activities, start, current_page_size
        )

        if not success or not activities:
            return

        for activity in activities:
            yield activity
            fetched_count += 1
            if max_limit is not None and fetched_count >= max_limit:
                return

        start += current_page_size


def get_last_exported_activity_id() -> int | None:
    """Liest die ID der zuletzt geladenen Aktivität aus der Triggerdatei."""
    if not LAST_LOADED_FILE.exists():
        return None
    try:
        content = LAST_LOADED_FILE.read_text(encoding="utf-8").strip()
        return int(content) if content.isdigit() else None
    except Exception:
        return None


def save_last_exported_activity_id(activity_id: int):
    """Speichert die ID der zuletzt geladenen Aktivität in die Triggerdatei."""
    LAST_LOADED_FILE.write_text(str(activity_id), encoding="utf-8")


def export_all_activities_with_resume(api: Garmin, limit: int | None = None):
    # 3. Zuerst alle alten/existierenden Aktivitäten laden (Garmin liefert standardmäßig von neu nach alt).
    # Da wir von oben nach unten durchgehen, merken wir uns die allererste (neueste) gesehene Aktivität für lastLoaded.txt.
    last_id = get_last_exported_activity_id()

    if last_id:
        print(f"⏩ Resume enabled – last exported activityId from {LAST_LOADED_FILE.name}: {last_id}")
    else:
        print("🆕 No previous export found – full export")

    if limit is not None:
        print(f"🎯 Limit set to max {limit} activities")

    exported = 0
    skipped = 0
    newest_activity_id_seen = None

    for activity in fetch_all_activities(api, max_limit=limit):
        activity_id = activity.get("activityId")
        if not activity_id:
            continue

        # Die allererste Aktivität im Stream ist die neueste
        if newest_activity_id_seen is None:
            newest_activity_id_seen = activity_id

        # 5. Anhand von last_id (aus lastLoaded.txt) prüfen, ob Aktivität übersprungen werden kann
        if last_id and activity_id <= last_id:
            skipped += 1
            continue

        print(f"➡️ Exporting activity {activity_id}")
        export_activity(api, activity)
        exported += 1

    # 4. Aktualisiere lastLoaded.txt mit der neuesten gesehenen Aktivität, falls welche da waren
    if newest_activity_id_seen is not None:
        save_last_exported_activity_id(newest_activity_id_seen)
        print(f"📌 Updated {LAST_LOADED_FILE.name} with latest activityId: {newest_activity_id_seen}")

    print(f"\n✅ Export done: {exported} new, {skipped} skipped")


def export_activity(api: Garmin, activity: dict):
    activity_id = activity.get("activityId")
    if not activity_id:
        return

    base_dir = EXPORT_DIR / str(activity_id)
    base_dir.mkdir(exist_ok=True)

    json_path = EXPORT_DIR / f"{activity_id}.json"
    gpx_path = EXPORT_DIR / f"{activity_id}.gpx"

    # ---- JSON ----
    if not json_path.exists():
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(activity, f, indent=2, ensure_ascii=False)
        print(f"🧾 JSON saved: {json_path.name}")

    # ---- GPX ----
    if not gpx_path.exists():
        success, gpx_data, error = safe_api_call(
            api.download_activity, activity_id, api.ActivityDownloadFormat.GPX
        )

        if success and gpx_data:
            gpx_path.write_bytes(gpx_data)
            print(f"🗺️ GPX saved: {gpx_path.name}")
            time.sleep(0.2)  # freundlich zu Garmin 😇
        else:
            print(f"⚠️ GPX failed for {activity_id}: {error}")


def main():
    parser = argparse.ArgumentParser(description="Export Garmin activities.")
    parser.add_argument(
        "limit",
        nargs="?",
        type=int,
        default=None,
        help="Optional: Anzahl der maximal abzurufenden Aktivitäten",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("🏃‍♂️ Export of garmin activities")
    print("=" * 60)

    api = init_api()

    if not api:
        print("❌ Failed to initialize API. Exiting.")
        return

    export_all_activities_with_resume(api, limit=args.limit)

    print("\n" + "=" * 60)
    print("✅ All done")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n🚪 Exiting example. Goodbye! 👋")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")