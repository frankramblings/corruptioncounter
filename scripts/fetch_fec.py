#!/usr/bin/env python3
"""
Fetch direct contributions from pro-Israel PACs to federal candidates
for the 2026 cycle from the OpenFEC API, and write the total to
data/total.json and per-candidate data to data/candidates.json.

Also fetches independent expenditures (Schedule E) from the United
Democracy Project (UDP) Super PAC and writes per-candidate IE data
to data/independent_expenditures.json.

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

# Super PACs making independent expenditures (Schedule E)
IE_COMMITTEES = {
    "United Democracy Project (UDP)": "C00798280",
}

API_BASE = "https://api.open.fec.gov/v1"
TWO_YEAR_PERIOD = 2026
PER_PAGE = 100
DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data"))
TOTAL_PATH = os.path.join(DATA_DIR, "total.json")
CANDIDATES_PATH = os.path.join(DATA_DIR, "candidates.json")
IE_PATH = os.path.join(DATA_DIR, "independent_expenditures.json")

# Rate-limit: FEC allows 1000 requests/hour with a key. Be polite.
REQUEST_DELAY = 0.5  # seconds between requests


def get_api_key():
    key = os.environ.get("FEC_API_KEY", "").strip()
    if not key:
        print("ERROR: FEC_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    return key


def fetch_json(url, max_retries=4):
    """Fetch a URL and return parsed JSON, with retry/backoff for 429s and 422s."""
    for attempt in range(max_retries + 1):
        req = Request(url, headers={"User-Agent": "ProIsraelPACCounter/1.0"})
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            if e.code in (429, 422) and attempt < max_retries:
                wait = 2 ** (attempt + 1)  # 2, 4, 8, 16 seconds
                print(f"HTTP {e.code}, retrying in {wait}s... (attempt {attempt + 1}/{max_retries})", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"HTTP error {e.code}: {e.reason} for {url}", file=sys.stderr)
            raise
        except URLError as e:
            print(f"URL error: {e.reason} for {url}", file=sys.stderr)
            raise


def format_candidate_name(name):
    """Convert 'LASTNAME, FIRSTNAME M.' to 'Firstname M. Lastname'."""
    if not name:
        return "Unknown"
    if "," in name:
        parts = name.split(",", 1)
        last = parts[0].strip().title()
        first = parts[1].strip().title()
        return f"{first} {last}"
    return name.title()


def fetch_committee_contributions(api_key, committee_id, committee_name):
    """
    Fetch Schedule B disbursements from a single committee to
    House (H), Senate (S), and Presidential (P) candidate committees.
    Returns (total_usd, recipients_dict).

    recipients_dict: {recipient_committee_id: {committee_name, state, type, total}}
    """
    total = 0.0
    recipients = {}

    for committee_type in ["H", "S", "P"]:
        page = 1

        try:
            while True:
                params = {
                    "api_key": api_key,
                    "committee_id": committee_id,
                    "two_year_transaction_period": TWO_YEAR_PERIOD,
                    "per_page": PER_PAGE,
                    "sort": "-disbursement_date",
                    "recipient_committee_type": committee_type,
                    "page": page,
                }

                url = f"{API_BASE}/schedules/schedule_b/?{urlencode(params)}"
                data = fetch_json(url)
                results = data.get("results", [])

                for item in results:
                    amount = item.get("disbursement_amount", 0)
                    total += amount

                    rcpt_id = item.get("recipient_committee_id")
                    if rcpt_id:
                        if rcpt_id not in recipients:
                            recipients[rcpt_id] = {
                                "committee_name": item.get("recipient_name", ""),
                                "state": item.get("recipient_state", ""),
                                "type": committee_type,
                                "total": 0.0,
                            }
                        recipients[rcpt_id]["total"] += amount

                pagination = data.get("pagination", {})
                pages = pagination.get("pages", 1)

                if not results or page >= pages:
                    break

                page += 1
                time.sleep(REQUEST_DELAY)
        except Exception as e:
            print(f"  {committee_name} type={committee_type}: ERROR - {e}", file=sys.stderr)
            # Continue with next committee_type instead of losing all data

        time.sleep(REQUEST_DELAY)

    return total, recipients


def lookup_candidate_for_committee(api_key, committee_id):
    """
    Look up the candidate linked to a recipient committee.
    Returns candidate dict or None.
    """
    params = urlencode({"api_key": api_key})
    url = f"{API_BASE}/committee/{committee_id}/candidates/?{params}"
    try:
        data = fetch_json(url)
        results = data.get("results", [])
        if results:
            c = results[0]
            return {
                "candidate_id": c.get("candidate_id", ""),
                "name": format_candidate_name(c.get("name", "")),
                "party": c.get("party", ""),
                "state": c.get("state", ""),
                "district": c.get("district", ""),
                "office": c.get("office", ""),
            }
    except Exception as e:
        print(f"  Candidate lookup failed for {committee_id}: {e}", file=sys.stderr)
    return None


def fetch_independent_expenditures(api_key, committee_id, committee_name):
    """
    Fetch Schedule E independent expenditures from a single committee.
    Returns (total_usd, candidates_dict).

    candidates_dict: {candidate_id: {name, party, state, office, district,
                                      support, oppose}}
    """
    total = 0.0
    candidates = {}

    last_index = None
    last_expenditure_date = None
    page = 1

    while True:
        params = {
            "api_key": api_key,
            "committee_id": committee_id,
            "cycle": TWO_YEAR_PERIOD,
            "per_page": PER_PAGE,
            "sort": "-expenditure_date",
        }

        if last_index is not None:
            params["last_index"] = last_index
            if last_expenditure_date is not None:
                params["last_expenditure_date"] = last_expenditure_date

        url = f"{API_BASE}/schedules/schedule_e/?{urlencode(params)}"
        data = fetch_json(url)
        results = data.get("results", [])

        for item in results:
            # Skip memo entries to avoid double-counting
            if item.get("memo_code") == "X":
                continue

            amount = item.get("expenditure_amount", 0)
            total += amount

            cand_id = item.get("candidate_id")
            if cand_id:
                if cand_id not in candidates:
                    candidates[cand_id] = {
                        "name": format_candidate_name(
                            item.get("candidate_name", "")
                        ),
                        "party": item.get("candidate_party", ""),
                        "state": item.get("candidate_state", ""),
                        "office": item.get("candidate_office", ""),
                        "district": item.get("candidate_district", ""),
                        "support": 0.0,
                        "oppose": 0.0,
                    }
                indicator = item.get("support_oppose_indicator", "")
                if indicator == "S":
                    candidates[cand_id]["support"] += amount
                elif indicator == "O":
                    candidates[cand_id]["oppose"] += amount

        pagination = data.get("pagination", {})
        pages = pagination.get("pages", 1)

        if not results or page >= pages:
            break

        last_indexes = pagination.get("last_indexes", {})
        last_index = last_indexes.get("last_index")
        last_expenditure_date = last_indexes.get("last_expenditure_date")

        if last_index is None:
            break

        page += 1
        time.sleep(REQUEST_DELAY)

    return total, candidates


def main():
    api_key = get_api_key()
    print(f"Fetching pro-Israel PAC contributions for {TWO_YEAR_PERIOD}...")
    print(f"Querying {len(COMMITTEES)} committees.\n")

    grand_total = 0.0
    breakdown = {}
    # Aggregate recipients across all PACs: {rcpt_id: {info..., pacs: [{name, amount}]}}
    all_recipients = {}

    for name, committee_id in COMMITTEES.items():
        try:
            amount, recipients = fetch_committee_contributions(
                api_key, committee_id, name
            )
            breakdown[committee_id] = {
                "name": name,
                "usd": round(amount, 2),
            }
            grand_total += amount

            # Merge recipient data
            for rcpt_id, rcpt_data in recipients.items():
                if rcpt_id not in all_recipients:
                    all_recipients[rcpt_id] = {
                        "committee_name": rcpt_data["committee_name"],
                        "state": rcpt_data["state"],
                        "type": rcpt_data["type"],
                        "total": 0.0,
                        "pacs": [],
                    }
                all_recipients[rcpt_id]["total"] += rcpt_data["total"]
                if rcpt_data["total"] > 0:
                    all_recipients[rcpt_id]["pacs"].append({
                        "name": name,
                        "amount": round(rcpt_data["total"], 2),
                    })

            if amount > 0:
                print(f"  {name} ({committee_id}): ${amount:,.2f}")
            else:
                print(f"  {name} ({committee_id}): $0.00")
        except Exception as e:
            print(f"  {name} ({committee_id}): ERROR - {e}", file=sys.stderr)
            # Still record the committee so it's visible in the output
            breakdown[committee_id] = {
                "name": name,
                "usd": 0.0,
                "error": str(e),
            }

    # --- Look up candidate details for each recipient committee ---
    print(f"\nLooking up candidate details for {len(all_recipients)} recipients...")
    candidates_list = []

    for rcpt_id, rcpt_data in all_recipients.items():
        candidate_info = lookup_candidate_for_committee(api_key, rcpt_id)
        time.sleep(REQUEST_DELAY)

        if candidate_info:
            entry = {
                "candidate_id": candidate_info["candidate_id"],
                "name": candidate_info["name"],
                "party": candidate_info["party"],
                "state": candidate_info["state"],
                "office": candidate_info["office"],
                "district": candidate_info["district"],
                "total": round(rcpt_data["total"], 2),
                "recipient_id": rcpt_id,
                "pacs": sorted(
                    rcpt_data["pacs"], key=lambda x: x["amount"], reverse=True
                ),
            }
        else:
            # Fallback: use committee name as candidate name
            entry = {
                "candidate_id": "",
                "name": rcpt_data["committee_name"].title(),
                "party": "",
                "state": rcpt_data["state"],
                "office": rcpt_data["type"],
                "district": "",
                "total": round(rcpt_data["total"], 2),
                "recipient_id": rcpt_id,
                "pacs": sorted(
                    rcpt_data["pacs"], key=lambda x: x["amount"], reverse=True
                ),
            }

        candidates_list.append(entry)
        if entry["total"] > 0:
            print(f"  {entry['name']} ({entry['state']}): ${entry['total']:,.2f}")

    # Sort by total descending
    candidates_list.sort(key=lambda x: x["total"], reverse=True)

    # --- Fetch independent expenditures (Schedule E) ---
    print(f"\nFetching independent expenditures from {len(IE_COMMITTEES)} Super PAC(s)...")
    ie_grand_total = 0.0
    ie_breakdown = {}
    # Aggregate IE candidates across all IE committees
    all_ie_candidates = {}  # {candidate_id: {info..., committees: [{name, support, oppose}]}}

    for name, committee_id in IE_COMMITTEES.items():
        try:
            ie_amount, ie_candidates = fetch_independent_expenditures(
                api_key, committee_id, name
            )
            ie_breakdown[committee_id] = {
                "name": name,
                "usd": round(ie_amount, 2),
            }
            ie_grand_total += ie_amount

            # Merge candidate data
            for cand_id, cand_data in ie_candidates.items():
                if cand_id not in all_ie_candidates:
                    all_ie_candidates[cand_id] = {
                        "name": cand_data["name"],
                        "party": cand_data["party"],
                        "state": cand_data["state"],
                        "office": cand_data["office"],
                        "district": cand_data["district"],
                        "support": 0.0,
                        "oppose": 0.0,
                        "committees": [],
                    }
                all_ie_candidates[cand_id]["support"] += cand_data["support"]
                all_ie_candidates[cand_id]["oppose"] += cand_data["oppose"]
                if cand_data["support"] > 0 or cand_data["oppose"] > 0:
                    all_ie_candidates[cand_id]["committees"].append({
                        "name": name,
                        "support": round(cand_data["support"], 2),
                        "oppose": round(cand_data["oppose"], 2),
                    })

            if ie_amount > 0:
                print(f"  {name} ({committee_id}): ${ie_amount:,.2f}")
            else:
                print(f"  {name} ({committee_id}): $0.00")
        except Exception as e:
            print(f"  {name} ({committee_id}): ERROR - {e}", file=sys.stderr)
            ie_breakdown[committee_id] = {
                "name": name,
                "usd": 0.0,
                "error": str(e),
            }

    # Build IE candidates list
    ie_candidates_list = []
    for cand_id, cand_data in all_ie_candidates.items():
        total_ie = cand_data["support"] + cand_data["oppose"]
        if total_ie <= 0:
            continue
        ie_candidates_list.append({
            "candidate_id": cand_id,
            "name": cand_data["name"],
            "party": cand_data["party"],
            "state": cand_data["state"],
            "office": cand_data["office"],
            "district": cand_data["district"],
            "support": round(cand_data["support"], 2),
            "oppose": round(cand_data["oppose"], 2),
            "total": round(total_ie, 2),
            "committees": sorted(
                cand_data["committees"],
                key=lambda x: x["support"] + x["oppose"],
                reverse=True,
            ),
        })

    ie_candidates_list.sort(key=lambda x: x["total"], reverse=True)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # --- Write total.json ---
    total_output = {
        "usd": round(grand_total, 2),
        "independent_expenditures_usd": round(ie_grand_total, 2),
        "combined_usd": round(grand_total + ie_grand_total, 2),
        "last_updated": now,
        "committees_queried": len(COMMITTEES),
        "ie_committees_queried": len(IE_COMMITTEES),
        "breakdown": breakdown,
        "ie_breakdown": ie_breakdown,
    }

    os.makedirs(DATA_DIR, exist_ok=True)

    with open(TOTAL_PATH, "w") as f:
        json.dump(total_output, f, indent=2)
        f.write("\n")

    # --- Write candidates.json ---
    candidates_output = {
        "last_updated": now,
        "candidates": candidates_list,
    }

    with open(CANDIDATES_PATH, "w") as f:
        json.dump(candidates_output, f, indent=2)
        f.write("\n")

    # --- Write independent_expenditures.json ---
    ie_output = {
        "last_updated": now,
        "total_usd": round(ie_grand_total, 2),
        "ie_committees_queried": len(IE_COMMITTEES),
        "candidates": ie_candidates_list,
    }

    with open(IE_PATH, "w") as f:
        json.dump(ie_output, f, indent=2)
        f.write("\n")

    print(f"\nDirect contributions: ${grand_total:,.2f}")
    print(f"Independent expenditures: ${ie_grand_total:,.2f}")
    print(f"Combined total: ${grand_total + ie_grand_total:,.2f}")
    print(f"Candidates (direct): {len(candidates_list)}")
    print(f"Candidates (IE): {len(ie_candidates_list)}")
    print(f"Written to {TOTAL_PATH}")
    print(f"Written to {CANDIDATES_PATH}")
    print(f"Written to {IE_PATH}")


if __name__ == "__main__":
    main()
