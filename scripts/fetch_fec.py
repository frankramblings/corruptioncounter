#!/usr/bin/env python3
"""
Fetch direct contributions from pro-Israel PACs to federal candidates
for the 2026 cycle from the OpenFEC API, and write the total to
data/total.json.

Includes AIPAC's PAC and other pro-Israel PACs from OpenSecrets'
Pro-Israel industry list (Q05).

Requires the FEC_API_KEY environment variable.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode

# Pro-Israel PACs: name -> FEC Committee ID
# Source: OpenSecrets Pro-Israel industry (Q05), FEC.gov
COMMITTEES = {
    "American Israel Public Affairs Cmte (AIPAC PAC)": "C00797670",
    "NORPAC": "C00247403",
    "JStreetPAC": "C00441949",
    "DMFI PAC (Democratic Majority for Israel)": "C00710848",
    "Joint Action Committee for Political Affairs (JACPAC)": "C00139659",
    "National Action Committee (NACPAC)": "C00147983",
    "Citizens Organized PAC": "C00110585",
    "Desert Caucus": "C00102368",
    "Hudson Valley PAC": "C00158865",
    "To Protect Our Heritage PAC": "C00135541",
    "St Louisians for Better Government": "C00148155",
    "World Alliance for Israel": "C00236596",
    "Republican Jewish Coalition PAC": "C00345132",
    "Florida Congressional Committee / US Israel PAC": "C00127811",
    "Maryland Assoc. for Concerned Citizens": "C00195024",
    "National PAC (NATPAC)": "C00150995",
    "CityPAC": "C00187526",
    "Pro-Israel America PAC": "C00699470",
    "Christians for Israel PAC": "C00720128",
    "Friends of Israel PAC (FIPAC)": "C00141747",
    "Sun PAC (SUNPAC)": "C00378216",
    "Heartland PAC": "C00131557",
    "Delaware Valley PAC": "C00152579",
    "Pacific Northwest PAC": "C00811802",
    "Washington PAC (WAPAC)": "C00138560",
    "BayPAC": "C00155713",
    "Americans for Good Government (AGG)": "C00138701",
    "MOPAC": "C00199950",
}

API_BASE = "https://api.open.fec.gov/v1"
TWO_YEAR_PERIOD = 2026
PER_PAGE = 100
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "total.json")

# Rate-limit: FEC allows 1000 requests/hour with a key. Be polite.
REQUEST_DELAY = 0.5  # seconds between requests


def get_api_key():
    key = os.environ.get("FEC_API_KEY", "").strip()
    if not key:
        print("ERROR: FEC_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    return key


def fetch_json(url):
    """Fetch a URL and return parsed JSON."""
    req = Request(url, headers={"User-Agent": "ProIsraelPACCounter/1.0"})
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        print(f"HTTP error {e.code}: {e.reason} for {url}", file=sys.stderr)
        raise
    except URLError as e:
        print(f"URL error: {e.reason} for {url}", file=sys.stderr)
        raise


def fetch_committee_contributions(api_key, committee_id, committee_name):
    """
    Fetch Schedule B disbursements from a single committee to
    House (H), Senate (S), and Presidential (P) candidate committees.
    Returns the total amount in USD.
    """
    total = 0.0

    for committee_type in ["H", "S", "P"]:
        page = 1
        last_index = None
        last_amount = None

        while True:
            params = {
                "api_key": api_key,
                "committee_id": committee_id,
                "two_year_transaction_period": TWO_YEAR_PERIOD,
                "per_page": PER_PAGE,
                "sort": "-disbursement_date",
                "recipient_committee_type": committee_type,
            }

            if last_index is not None:
                params["last_index"] = last_index
                params["last_disbursement_amount"] = last_amount

            url = f"{API_BASE}/schedules/schedule_b/?{urlencode(params)}"
            data = fetch_json(url)
            results = data.get("results", [])

            for item in results:
                total += item.get("disbursement_amount", 0)

            pagination = data.get("pagination", {})
            pages = pagination.get("pages", 1)

            if not results or page >= pages:
                break

            last_indexes = pagination.get("last_indexes", {})
            last_index = last_indexes.get("last_index")
            last_amount = last_indexes.get("last_disbursement_amount")

            if last_index is None:
                break

            page += 1
            time.sleep(REQUEST_DELAY)

        time.sleep(REQUEST_DELAY)

    return total


def main():
    api_key = get_api_key()
    print(f"Fetching pro-Israel PAC contributions for {TWO_YEAR_PERIOD}...")
    print(f"Querying {len(COMMITTEES)} committees.\n")

    grand_total = 0.0
    breakdown = {}

    for name, committee_id in COMMITTEES.items():
        try:
            amount = fetch_committee_contributions(api_key, committee_id, name)
            breakdown[committee_id] = {
                "name": name,
                "usd": round(amount, 2),
            }
            grand_total += amount
            if amount > 0:
                print(f"  {name} ({committee_id}): ${amount:,.2f}")
            else:
                print(f"  {name} ({committee_id}): $0.00")
        except Exception as e:
            print(f"  {name} ({committee_id}): ERROR - {e}", file=sys.stderr)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    output = {
        "usd": round(grand_total, 2),
        "last_updated": now,
        "committees_queried": len(COMMITTEES),
        "breakdown": breakdown,
    }

    output_path = os.path.normpath(OUTPUT_PATH)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
        f.write("\n")

    print(f"\nGrand total: ${grand_total:,.2f}")
    print(f"Written to {output_path}")


if __name__ == "__main__":
    main()
