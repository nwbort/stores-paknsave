#!/usr/bin/env python3
"""
Fetch PAK'nSAVE store locations and details from the Foodstuffs edge API.

The store finder on www.paknsave.co.nz first obtains an anonymous access token
from /api/user/get-current-user, then calls the edge API, which returns every
store with its full details (address, coordinates, opening hours, online
shopping settings) in a single response. The per-store endpoint returns the
same data, so there is no separate details step.

Writes:
  api-prod.paknsave.co.nz-stores.json  raw API response
  paknsave.co.nz-stores.json           summary list: id, name, storeCode, region, city
  store-details/{id}.json              one file per store
  paknsave.co.nz-store-details.json    all store details combined, sorted by id

Usage:
  python3 fetch_stores.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

SITE_URL = "https://www.paknsave.co.nz"
TOKEN_URL = f"{SITE_URL}/api/user/get-current-user"
API_URL = "https://api-prod.paknsave.co.nz/v1/edge/store"

RAW_JSON = "api-prod.paknsave.co.nz-stores.json"
STORES_JSON = "paknsave.co.nz-stores.json"
DETAILS_DIR = "store-details"
COMBINED_JSON = "paknsave.co.nz-store-details.json"

# Refuse to overwrite existing data if the response looks truncated
MIN_STORES = 40

MAX_RETRIES = 3
RETRY_BACKOFF = [5, 10, 20]  # seconds between retries

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-NZ,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Origin": SITE_URL,
    "Referer": f"{SITE_URL}/store-finder",
}


def request_json(url, data=None, headers=None):
    """GET (or POST when data is given) a URL and return the decoded JSON, with retries."""
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        if attempt > 0:
            delay = RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)]
            print(f"Retrying in {delay}s ({last_error})")
            time.sleep(delay)

        req = urllib.request.Request(url, data=data, headers={**HEADERS, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}"
            if e.code not in (403, 429, 500, 502, 503, 504):
                break  # non-retryable
        except urllib.error.URLError as e:
            last_error = f"URL error: {e.reason}"
        except json.JSONDecodeError as e:
            last_error = f"invalid JSON: {e}"
            break
        except Exception as e:
            last_error = str(e)

    sys.exit(f"Error: failed to fetch {url}: {last_error}")


def fetch():
    user = request_json(TOKEN_URL, data=b"{}", headers={"Content-Type": "application/json"})
    token = user.get("access_token") if isinstance(user, dict) else None
    if not token:
        sys.exit("Error: no access_token in get-current-user response")
    return request_json(API_URL, headers={"Authorization": f"Bearer {token}"})


def detail_path(store_id):
    return os.path.join(DETAILS_DIR, f"{store_id}.json")


def main():
    data = fetch()

    stores_list = data.get("stores") if isinstance(data, dict) else None
    if not isinstance(stores_list, list):
        sys.exit("Error: response has no stores list")

    details = {}
    for entry in stores_list:
        store_id = entry.get("id")
        if store_id:
            details[store_id] = entry

    if len(details) < MIN_STORES:
        sys.exit(f"Error: only {len(details)} stores returned, expected at least {MIN_STORES}")

    with open(RAW_JSON, "w") as f:
        json.dump(data, f, indent=2)

    stores = []
    for store_id in sorted(details):
        store = details[store_id]
        address = store.get("physicalAddress") or {}
        stores.append({
            "id": store_id,
            "name": store.get("name"),
            "storeCode": store.get("physicalStoreCode"),
            "region": address.get("regionName"),
            "city": address.get("cityName"),
        })
    with open(STORES_JSON, "w") as f:
        json.dump(stores, f, indent=2)
    print(f"Saved {len(stores)} stores to {STORES_JSON}")

    os.makedirs(DETAILS_DIR, exist_ok=True)
    for store_id, entry in details.items():
        with open(detail_path(store_id), "w") as f:
            json.dump(entry, f, indent=2)

    # Drop detail files for stores no longer returned by the API
    removed = 0
    for fname in os.listdir(DETAILS_DIR):
        if fname.endswith(".json") and fname[:-5] not in details:
            os.remove(os.path.join(DETAILS_DIR, fname))
            removed += 1
    print(f"Wrote {len(details)} files to {DETAILS_DIR}/ ({removed} removed)")

    with open(COMBINED_JSON, "w") as f:
        json.dump([details[i] for i in sorted(details)], f, indent=2)
    print(f"Rebuilt {COMBINED_JSON} with {len(details)} stores.")


if __name__ == "__main__":
    main()
