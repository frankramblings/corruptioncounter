#!/usr/bin/env python3
"""
Fetch AIPAC PAC (C00797670) direct contributions to federal candidates
for calendar year 2026 from the OpenFEC API, and write the total to
data/total.json.

Requires the FEC_API_KEY environment variable.
"""

import json
import os
import sys
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode

COMMITTEE_ID = "C00797670"  # AIPAC PAC
API_BASE = "https://api.open.fec.gov/v1"
TWO_YEAR_PERIOD = 2026
PER_PAGE = 100
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "total.json")


def get_api_key():
    key = os.environ.get("FEC_API_KEY", "").strip()
    if not key:
        print("ERROR: FEC_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    return key


def fetch_json(url):
    """Fetch a URL and return parsed JSON."""
    req = Request(url, headers={"User-Agent": "AIPACCounter/1.0"})
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        print(f"HTTP error {e.code}: {e.reason} for {url}", file=sys.stderr)
        raise
    except URLError as e:
        print(f"URL error: {e.reason} for {url}", file=sys.stderr)
        raise


def fetch_contributions(api_key):
    """
    Use the /schedules/schedule_b/ endpoint (disbursements) filtered to
    the AIPAC PAC committee, with disbursement purpose matching
    contributions to candidates. We also use the /schedules/schedule_a/
    by_recipient approach, but the most direct way is to query
    Schedule B disbursements from the committee that are contributions
    to candidates.

    Actually, the cleanest FEC endpoint for "contributions made BY a
    committee TO candidates" is:

      /committee/{id}/schedules/schedule_b/
        ?two_year_transaction_period=2026
        &disbursement_purpose_category=CONTRIBUTIONS

    OR we can use the dedicated endpoint:

      /schedules/schedule_b/
        ?committee_id=C00797670
        &two_year_transaction_period=2026

    We'll sum all disbursement_amount values.
    """
    total = 0.0
    page = 1
    last_index = None
    last_amount = None

    while True:
        params = {
            "api_key": api_key,
            "committee_id": COMMITTEE_ID,
            "two_year_transaction_period": TWO_YEAR_PERIOD,
            "per_page": PER_PAGE,
            "sort": "-disbursement_date",
            "recipient_committee_type": "H",  # will also need S and P
        }

        # The FEC API uses keyset pagination via last_index/last_offset
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

        # Use last_indexes for keyset pagination
        last_indexes = pagination.get("last_indexes", {})
        last_index = last_indexes.get("last_index")
        last_amount = last_indexes.get("last_disbursement_amount")

        if last_index is None:
            break

        page += 1

    return total


def fetch_all_candidate_contributions(api_key):
    """
    Fetch disbursements to House, Senate, and Presidential candidate
    committees.
    """
    total = 0.0

    for committee_type in ["H", "S", "P"]:
        page = 1
        last_index = None
        last_amount = None

        while True:
            params = {
                "api_key": api_key,
                "committee_id": COMMITTEE_ID,
                "two_year_transaction_period": TWO_YEAR_PERIOD,
                "per_page": PER_PAGE,
                "sort": "-disbursement_date",
            }

            if committee_type:
                params["recipient_committee_type"] = committee_type

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

    return total


def main():
    api_key = get_api_key()
    print(f"Fetching AIPAC PAC contributions for {TWO_YEAR_PERIOD}...")

    total_usd = fetch_all_candidate_contributions(api_key)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    output = {
        "usd": round(total_usd, 2),
        "last_updated": now,
    }

    output_path = os.path.normpath(OUTPUT_PATH)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
        f.write("\n")

    print(f"Total: ${total_usd:,.2f}")
    print(f"Written to {output_path}")


if __name__ == "__main__":
    main()
