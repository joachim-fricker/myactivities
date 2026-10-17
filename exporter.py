#!/usr/bin/env python3
"""
my rewrite of garmin-export based on  the https://github.com/cyberjunky/python-garminconnect library
"""

import logging
import os
import sys
from datetime import date
from getpass import getpass
from pathlib import Path
import json
import time

import requests
from garth.exc import GarthException, GarthHTTPError

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

PAGE_SIZE = 200


def safe_api_call(api_method, *args, **kwargs):
    """
    Safe API call wrapper with comprehensive error handling.

    This demonstrates the error handling patterns used throughout the library.
    Returns (success: bool, result: Any, error_message: str)
    """
    try:
        result = api_method(*args, **kwargs)
        return True, result, None

    except GarthHTTPError as e:
        # Handle specific HTTP errors gracefully
        error_str = str(e)
        status_code = getattr(getattr(e, "response", None), "status_code", None)

        if status_code == 400 or "400" in error_str:
            return (
                False,
                None,
                "Endpoint not available (400 Bad Request) - Feature may not be enabled for your account",
            )
        elif status_code == 401 or "401" in error_str:
            return (
                False,
                None,
                "Authentication required (401 Unauthorized) - Please re-authenticate",
            )
        elif status_code == 403 or "403" in error_str:
            return (
                False,
                None,
                "Access denied (403 Forbidden) - Account may not have permission",
            )
        elif status_code == 404 or "404" in error_str:
            return (
                False,
                None,
                "Endpoint not found (404) - Feature may have been moved or removed",
            )
        elif status_code == 429 or "429" in error_str:
            return (
                False,
                None,
                "Rate limit exceeded (429) - Please wait before making more requests",
            )
        elif status_code == 500 or "500" in error_str:
            return (
                False,
                None,
                "Server error (500) - Garmin's servers are experiencing issues",
            )
        elif status_code == 503 or "503" in error_str:
            return (
                False,
                None,
                "Service unavailable (503) - Garmin's servers are temporarily unavailable",
            )
        else:
            return False, None, f"HTTP error: {e}"

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
            GarthHTTPError,
            GarminConnectConnectionError,
            requests.exceptions.HTTPError,
        ) as err:
            print(f"❌ Connection error: {err}")
            return None

        except KeyboardInterrupt:
            print("\n👋 Cancelled by user")
            return None


def fetch_all_activities(api: Garmin, page_size=100):
    start = 0

    while True:
        success, activities, error = safe_api_call(
            api.get_activities, start, page_size
        )

        if not success or not activities:
            return

        for activity in activities:
            yield activity

        start += page_size



def get_last_exported_activity_id(export_root: Path) -> int | None:
    if not export_root.exists():
        return None

    ids = []
    for p in export_root.iterdir():
        if p.is_dir() and p.name.isdigit():
            ids.append(int(p.name))

    return max(ids) if ids else None

def export_all_activities_with_resume(api: Garmin):
    EXPORT_ROOT = Path("exports/activities")
    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)

    last_id = get_last_exported_activity_id(EXPORT_ROOT)

    if last_id:
        print(f"⏩ Resume enabled – last exported activityId: {last_id}")
    else:
        print("🆕 No previous export found – full export")

    exported = 0
    skipped = 0

    for activity in fetch_all_activities(api):
        activity_id = activity.get("activityId")
        if not activity_id:
            continue

        if last_id and activity_id <= last_id:
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
    print("🏃‍♂️ Export of all garmin activities")
    print("=" * 60)

    # Initialize API with authentication (will only prompt for credentials if needed)
    api = init_api()

    if not api:
        print("❌ Failed to initialize API. Exiting.")
        return

    # export all activities
    export_all_activities_with_resume(api)

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
