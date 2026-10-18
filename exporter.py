#!/usr/bin/env python3
"""
Garmin Export Script - chronological sync based on lastLoaded.txt
"""

import argparse
import logging
import os
import sys
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

logging.getLogger("garminconnect").setLevel(logging.CRITICAL)

EXPORT_DIR = Path("activities")
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
LAST_LOADED_FILE = EXPORT_DIR / "lastLoaded.txt"

PAGE_SIZE = 100


def safe_api_call(api_method, *args, **kwargs):
    try:
        result = api_method(*args, **kwargs)
        return True, result, None
    except FileNotFoundError:
        return False, None, "No valid tokens found."
    except GarminConnectAuthenticationError as e:
        return False, None, f"Authentication issue: {e}"
    except GarminConnectConnectionError as e:
        return False, None, f"Connection issue: {e}"
    except GarminConnectTooManyRequestsError as e:
        return False, None, f"Rate limit exceeded: {e}"
    except Exception as e:
        return False, None, f"Unexpected error: {e}"


def get_credentials():
    email = os.getenv("EMAIL")
    password = os.getenv("PASSWORD")
    if not email:
        email = input("Login email: ")
    if not password:
        password = getpass("Enter password: ")
    return email, password


def init_api() -> Garmin | None:
    print("🔄 Logging in with credentials...")
    while True:
        try:
            email, password = get_credentials()
            tokenstore = os.getenv("GARMINTOKENS", "~/.garminconnect")
            tokenstore_path = str(Path(tokenstore).expanduser())

            garmin = Garmin(email=email, password=password, is_cn=False, return_on_mfa=True)
            result1, result2 = garmin.login()

            if result1 == "needs_mfa":
                print("🔐 MFA erforderlich. Bitte lokal einloggen und .garminconnect hochladen.")
                sys.exit(1)

            print("✅ Login successful!")
            return garmin
        except GarminConnectAuthenticationError:
            print("❌ Authentication failed.")
            continue
        except Exception as err:
            print(f"❌ Connection error: {err}")
            return None


def get_last_loaded_id() -> int | None:
    """Liest die ID aus lastLoaded.txt (letzte erfolgreich verarbeitete ID)."""
    if not LAST_LOADED_FILE.exists():
        return None
    try:
        content = LAST_LOADED_FILE.read_text(encoding="utf-8").strip()
        return int(content) if content.isdigit() else None
    except Exception:
        return None


def save_last_loaded_id(activity_id: int):
    LAST_LOADED_FILE.write_text(str(activity_id), encoding="utf-8")


def export_activities(api: Garmin, limit: int | None = None):
    # 1. Ermitteln, wie viele Aktivitäten es insgesamt gibt, um von "alt nach neu" zu arbeiten
    success, total_activities_list, error = safe_api_call(api.get_activities, 0, 1)
    if not success:
        print(f"❌ Konnte Aktivitäten nicht abrufen: {error}")
        return

    # Um von der Vergangenheit (älteste) zur Gegenwart (neueste) zu laden, 
    # holen wir uns alle IDs oder blättern rückwärts durch.
    # Alternativ holen wir alle Metadaten einmalig leicht ab:
    print("🔄 Hole Aktivitätsübersicht von Garmin...")
    all_activities = []
    start = 0
    while True:
        success, batch, error = safe_api_call(api.get_activities, start, PAGE_SIZE)
        if not success or not batch:
            break
        all_activities.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        start += PAGE_SIZE

    if not all_activities:
        print("📭 Keine Aktivitäten gefunden.")
        return

    # Garmin liefert Neueste zuerst -> Wir kehren die Liste um, damit wir in der Vergangenheit beginnen!
    all_activities.reverse()

    last_loaded_id = get_last_loaded_id()
    if last_loaded_id:
        print(f"⏩ Letzte geladene ID laut {LAST_LOADED_FILE.name}: {last_loaded_id}")
    else:
        print("🆕 Keine lastLoaded.txt gefunden – starte von den ältesten Aktivitäten.")

    exported = 0
    skipped = 0
    processed_count = 0

    for activity in all_activities:
        activity_id = activity.get("activityId")
        if not activity_id:
            continue

        # Wenn eine ID in lastLoaded steht, überspringen wir alles, was älter oder gleich ist
        if last_loaded_id and activity_id <= last_loaded_id:
            skipped += 1
            continue

        if limit is not None and processed_count >= limit:
            break

        print(f"➡️ Exporting activity {activity_id}")
        export_activity(api, activity)
        
        # Speichere fortlaufend die ID als "zuletzt geladen"
        save_last_loaded_id(activity_id)
        
        exported += 1
        processed_count += 1

    print(f"\n✅ Export beendet: {exported} neu exportiert, {skipped} übersprungen.")


def export_activity(api: Garmin, activity: dict):
    activity_id = activity.get("activityId")
    if not activity_id:
        return

    json_path = EXPORT_DIR / f"{activity_id}.json"
    gpx_path = EXPORT_DIR / f"{activity_id}.gpx"

    if not json_path.exists():
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(activity, f, indent=2, ensure_ascii=False)
        print(f"🧾 JSON saved: {json_path.name}")

    if not gpx_path.exists():
        success, gpx_data, error = safe_api_call(
            api.download_activity, activity_id, api.ActivityDownloadFormat.GPX
        )
        if success and gpx_data:
            gpx_path.write_bytes(gpx_data)
            print(f"🗺️ GPX saved: {gpx_path.name}")
            time.sleep(0.2)
        else:
            print(f"⚠️ GPX failed for {activity_id}: {error}")


def main():
    parser = argparse.ArgumentParser(description="Export Garmin activities chronologically.")
    parser.add_argument("limit", nargs="?", type=int, default=None, help="Max activities to load")
    args = parser.parse_args()

    print("=" * 60)
    print("🏃‍♂️ Chronological Garmin Export")
    print("=" * 60)

    api = init_api()
    if not api:
        print("❌ Failed to initialize API. Exiting.")
        return

    export_activities(api, limit=args.limit)

    print("\n" + "=" * 60)
    print("✅ All done")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n🚪 Exiting. Goodbye! 👋")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")