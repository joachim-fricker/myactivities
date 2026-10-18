#!/usr/bin/env python3
"""
Garmin Export Script - tracking all processed activity IDs in ids.txt
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
IDS_FILE = EXPORT_DIR / "ids.txt"

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


def get_processed_ids() -> set[int]:
    """Liest alle verarbeiteten IDs aus ids.txt als Set für schnellen Abgleich."""
    abs_path = IDS_FILE.resolve()
    print(f"🔍 DEBUG: Suche ids.txt unter: {abs_path}")
    
    if not IDS_FILE.exists():
        print(f"⚠️ DEBUG: Datei existiert physisch NICHT unter diesem Pfad.")
        return set()
        
    try:
        content = IDS_FILE.read_text(encoding="utf-8")
        print(f"📄 DEBUG: Datei erfolgreich gelesen. Länge: {len(content)} Zeichen.")
        lines = content.splitlines()
        ids = {int(line.strip()) for line in lines if line.strip().isdigit()}
        print(f"🔢 DEBUG: {len(ids)} IDs erfolgreich eingelesen.")
        return ids
    except Exception as e:
        print(f"❌ DEBUG: Fehler beim Lesen der ids.txt: {e}")
        return set()

def append_processed_id(activity_id: int):
    """Hängt die neue Aktivitäts-ID ans Ende von ids.txt an (letzte Zeile = zuletzt verarbeitete ID)."""
    with IDS_FILE.open("a", encoding="utf-8") as f:
        f.write(f"{activity_id}\n")


def export_activities(api: Garmin, limit: int | None = None):
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

    # Umkehren, damit wir in der Vergangenheit (älteste) anfangen
    all_activities.reverse()

    processed_ids = get_processed_ids()
    if processed_ids:
        print(f"⏩ {len(processed_ids)} bereits verarbeitete IDs in {IDS_FILE.name} gefunden.")
    else:
        print(f"🆕 Keine {IDS_FILE.name} gefunden – starte frischen Export.")

    exported = 0
    skipped = 0
    processed_count = 0

    for activity in all_activities:
        activity_id = activity.get("activityId")
        if not activity_id:
            continue

        # Prüfen, ob die ID bereits verarbeitet wurde
        if activity_id in processed_ids:
            skipped += 1
            continue

        if limit is not None and processed_count >= limit:
            break

        print(f"➡️ Exporting activity {activity_id}")
        export_activity(api, activity)
        
        # ID am Ende von ids.txt anhängen
        append_processed_id(activity_id)
        processed_ids.add(activity_id)
        
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
    print("🏃‍♂️ Chronological Garmin Export with ids.txt")
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