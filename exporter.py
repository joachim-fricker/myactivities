#!/usr/bin/env python3
"""
my rewrite of garmin-export based on  the https://github.com/cyberjunky/python-garminconnect library
(Limited to 2 recent activities for fast syncing)
"""

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

EXPORT_DIR = Path("exports/activities")
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def safe_api_call(api_method, *args, **kwargs):
    """
    Safe API call wrapper with comprehensive error handling.

    This demonstrates the error handling patterns used throughout the library.
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
    
    # Loop for credential entry with retry on auth failure
    while True:
        try:
            email, password = get_credentials()

            # Token-Pfad definieren (falls unterstützt)
            tokenstore = os.getenv("GARMINTOKENS", "~/.garminconnect")
            tokenstore_path = str(Path(tokenstore).expanduser())

            # Garmin-Client initialisieren
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


def export_latest_activities(api: Garmin, limit=2):
    """Holt nur die neusten X Aktivitäten (Standard: 2) statt alle."""
    EXPORT_ROOT = Path("exports/activities")
    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)

    print(f"🚀 Lade die neuesten {limit} Aktivitäten von Garmin...")
    success, activities, error = safe_api_call(
        api.get_activities, 0, limit
    )

    if not success or not activities:
        print(f"⚠️ Konnte keine Aktivitäten abrufen: {error}")
        return

    exported = 0
    skipped = 0

    for activity in activities:
        activity_id = activity.get("activityId")
        if not activity_id:
            continue

        json_path = EXPORT_DIR / f"{activity_id}.json"
        gpx_path = EXPORT_DIR / f"{activity_id}.gpx"

        # Optional: Überspringen, wenn JSON bereits existiert
        if json_path.exists() and gpx_path.exists():
            print(f"⏩ Aktivität {activity_id} bereits vorhanden – übersprungen.")
            skipped += 1
            continue

        print(f"➡️ Exporting activity {activity_id}")
        export_activity(api, activity)
        exported += 1

    print(f"\n✅ Export done: {exported} new, {skipped} skipped")

def export_activity(api: Garmin, activity: dict):
    activity_id = activity.get("activityId")
    if not activity_id:
        return

    base_dir = EXPORT_DIR / str(activity_id)
    # Note that this empty directory is used to indicate that the activity has been exported
    base_dir.mkdir(exist_ok=True)


    json_path = EXPORT_DIR / f"{activity_id}.json"
    gpx_path = EXPORT_DIR / f"{activity_id}.gpx"

    # ---- JSON ----
    if not json_path.exists():
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(activity, f, indent=2, ensure_ascii=False)
        print(f"🧾 JSON saved: {json_path.name}")

    
    gpx_path = EXPORT_DIR / f"{activity_id}.gpx"

    
    # ---- GPX ----
    if not gpx_path.exists():

        success, gpx_data, error = safe_api_call(
            api.download_activity, activity_id,  api.ActivityDownloadFormat.GPX )

        if success and gpx_data:
            gpx_path.write_bytes(gpx_data)
            print(f"🗺️ GPX saved: {gpx_path.name}")
            time.sleep(0.2)  # freundlich zu Garmin 😇
        else:
            print(f"⚠️ GPX failed for {activity_id}: {error}")



def main():
    print("=" * 60)
    print("🏃‍♂️ Fast Export (Latest 2 Garmin Activities)")
    print("=" * 60)

    # Initialize API with authentication (will only prompt for credentials if needed)
    api = init_api()

    if not api:
        print("❌ Failed to initialize API. Exiting.")
        return

    # Nur die neusten 2 Aktivitäten exportieren
    export_latest_activities(api, limit=2)

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