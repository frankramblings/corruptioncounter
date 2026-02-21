#!/usr/bin/env python3
"""
Scrape candidate contribution data (PACs, IEs, Bundlers) from TrackAIPAC.com
and merge bundler amounts into our existing candidates.json and total.json.

TrackAIPAC is a Squarespace site. We try the Squarespace JSON API first
(?format=json), then fall back to HTML parsing.

This script runs AFTER fetch_fec.py and enriches the data it produced.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = "https://www.trackaipac.com"
CANDIDATES_PAGE = "/candidates"
CONGRESS_PAGE = "/congress"

DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data"))
CANDIDATES_PATH = os.path.join(DATA_DIR, "candidates.json")
TOTAL_PATH = os.path.join(DATA_DIR, "total.json")
TRACKAIPAC_PATH = os.path.join(DATA_DIR, "trackaipac.json")

REQUEST_DELAY = 1.0  # seconds between requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def fetch_url(url, retries=3, delay=2):
    """Fetch a URL with retries and exponential backoff."""
    for attempt in range(retries):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except (HTTPError, URLError) as e:
            status = getattr(e, "code", None)
            print(
                f"  Attempt {attempt + 1}/{retries} failed for {url}: "
                f"{status or e.reason}",
                file=sys.stderr,
            )
            if attempt < retries - 1:
                wait = delay * (2 ** attempt)
                time.sleep(wait)
    return None


def fetch_json_api(path):
    """Try Squarespace ?format=json endpoint."""
    url = f"{BASE_URL}{path}?format=json"
    raw = fetch_url(url)
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            print(f"  Response from {url} is not valid JSON", file=sys.stderr)
    return None


def fetch_html(path):
    """Fetch a page as HTML."""
    url = f"{BASE_URL}{path}"
    return fetch_url(url)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
class TextExtractor(HTMLParser):
    """Simple HTML-to-text converter."""

    def __init__(self):
        super().__init__()
        self._pieces = []

    def handle_data(self, data):
        self._pieces.append(data)

    def get_text(self):
        return " ".join(self._pieces)


def html_to_text(html_str):
    parser = TextExtractor()
    parser.feed(html_str)
    return parser.get_text()


def parse_money(text):
    """Parse a dollar amount like '$199,040' or '199040' to float."""
    cleaned = re.sub(r"[^\d.]", "", text)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Squarespace JSON parsing
# ---------------------------------------------------------------------------
def parse_squarespace_json(data):
    """
    Parse Squarespace collection JSON. Items may be in:
    - data["items"]
    - data["collection"]["items"]
    - data["past"] / data["upcoming"]
    """
    items = []
    if isinstance(data, dict):
        items = data.get("items", [])
        if not items:
            coll = data.get("collection", {})
            items = coll.get("items", [])
    return items


def extract_candidate_from_item(item):
    """
    Extract candidate data from a Squarespace collection item.
    The body HTML likely contains contribution breakdowns.
    """
    title = item.get("title", "")
    body_html = item.get("body", "")
    custom = item.get("customContent", {}) or {}

    # Try to extract amounts from body text
    body_text = html_to_text(body_html) if body_html else ""

    # Look for patterns like "PACs: $18,475" "Bundlers: $199,040" "IE: $0"
    pac_match = re.search(r"PACs?[:\s]*\$?([\d,]+)", body_text, re.IGNORECASE)
    bundler_match = re.search(
        r"Bundlers?[:\s]*\$?([\d,]+)", body_text, re.IGNORECASE
    )
    ie_match = re.search(r"IE[:\s]*\$?([\d,]+)", body_text, re.IGNORECASE)
    total_match = re.search(r"Total[:\s]*\$?([\d,]+)", body_text, re.IGNORECASE)

    pacs = parse_money(pac_match.group(1)) if pac_match else 0
    bundlers = parse_money(bundler_match.group(1)) if bundler_match else 0
    ie = parse_money(ie_match.group(1)) if ie_match else 0
    total = parse_money(total_match.group(1)) if total_match else (pacs + bundlers + ie)

    # Try to extract state/party from tags, categories, or body
    tags = item.get("tags", []) or []
    categories = item.get("categories", []) or []

    state = ""
    party = ""
    office = ""
    district = ""

    # Look for state codes in tags
    state_pattern = re.compile(r"^[A-Z]{2}$")
    for tag in tags + categories:
        if state_pattern.match(tag):
            state = tag
        elif tag.upper() in ("DEM", "REP", "D", "R", "DEMOCRAT", "REPUBLICAN"):
            party = "DEM" if tag.upper() in ("DEM", "D", "DEMOCRAT") else "REP"
        elif tag.upper() in ("HOUSE", "SENATE", "PRESIDENT"):
            office = tag[0].upper()

    # Also check custom content fields
    for key in ("state", "party", "office", "district"):
        if key in custom:
            if key == "state":
                state = custom[key]
            elif key == "party":
                party = custom[key]
            elif key == "office":
                office = custom[key]
            elif key == "district":
                district = str(custom[key])

    return {
        "name": title.strip(),
        "state": state,
        "party": party,
        "office": office,
        "district": district,
        "pac_total": pacs,
        "bundler_total": bundlers,
        "ie_total": ie,
        "total": total,
    }


# ---------------------------------------------------------------------------
# HTML parsing fallback
# ---------------------------------------------------------------------------
def parse_html_page(html):
    """
    Parse candidate data from raw HTML.
    Look for structured patterns in the page content.
    """
    candidates = []

    # Strategy 1: Look for structured blocks with candidate info
    # TrackAIPAC likely uses Squarespace summary blocks or custom code blocks
    # Pattern: name followed by dollar amounts labeled PACs/IE/Bundlers

    # Find blocks that contain contribution data
    # Look for patterns like "PACs: $X ... Bundlers: $Y"
    blocks = re.findall(
        r"(?:PACs?[:\s]*\$[\d,]+.*?Bundlers?[:\s]*\$[\d,]+)",
        html,
        re.DOTALL | re.IGNORECASE,
    )

    if blocks:
        print(f"  Found {len(blocks)} contribution blocks in HTML")

    # Strategy 2: Look for JSON-LD or embedded JSON data
    json_matches = re.findall(
        r'<script[^>]*type=["\']application/(?:ld\+)?json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    for jm in json_matches:
        try:
            data = json.loads(jm)
            print(f"  Found embedded JSON: {type(data).__name__}")
        except json.JSONDecodeError:
            pass

    # Strategy 3: Look for __NEXT_DATA__ or similar hydration data
    next_data = re.search(
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if next_data:
        try:
            data = json.loads(next_data.group(1))
            print("  Found __NEXT_DATA__ - site uses Next.js")
            return extract_from_nextjs(data)
        except json.JSONDecodeError:
            pass

    # Strategy 4: Look for Squarespace static content / collection data
    sqs_data = re.search(
        r'Static\.SQUARESPACE_CONTEXT\s*=\s*(\{.*?\});',
        html,
        re.DOTALL,
    )
    if sqs_data:
        print("  Found Squarespace context data")

    # Strategy 5: Parse visible text for tabular data
    # Look for rows with: Name ... $Amount ... PACs: $X ... Bundlers: $Y
    candidate_pattern = re.compile(
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)'  # Name
        r'.*?'
        r'PACs?[:\s]*\$?([\d,]+)'  # PAC amount
        r'.*?'
        r'Bundlers?[:\s]*\$?([\d,]+)',  # Bundler amount
        re.DOTALL | re.IGNORECASE,
    )

    for match in candidate_pattern.finditer(html_to_text(html)):
        name = match.group(1).strip()
        pac_amt = parse_money(match.group(2))
        bundler_amt = parse_money(match.group(3))

        candidates.append(
            {
                "name": name,
                "state": "",
                "party": "",
                "office": "",
                "district": "",
                "pac_total": pac_amt,
                "bundler_total": bundler_amt,
                "ie_total": 0,
                "total": pac_amt + bundler_amt,
            }
        )

    return candidates


def extract_from_nextjs(data):
    """Extract candidate data from Next.js page props."""
    candidates = []
    # Traverse the data looking for candidate arrays
    props = data.get("props", {}).get("pageProps", {})
    for key, val in props.items():
        if isinstance(val, list) and len(val) > 0:
            if isinstance(val[0], dict) and any(
                k in val[0] for k in ("name", "total", "bundlers", "pacs")
            ):
                for item in val:
                    candidates.append(
                        {
                            "name": item.get("name", ""),
                            "state": item.get("state", ""),
                            "party": item.get("party", ""),
                            "office": item.get("office", ""),
                            "district": item.get("district", ""),
                            "pac_total": item.get("pacs", 0),
                            "bundler_total": item.get("bundlers", 0),
                            "ie_total": item.get("ie", 0),
                            "total": item.get("total", 0),
                        }
                    )
    return candidates


# ---------------------------------------------------------------------------
# Candidate name normalization for matching
# ---------------------------------------------------------------------------
def normalize_name(name):
    """Normalize a candidate name for fuzzy matching."""
    name = name.lower().strip()
    # Remove common suffixes
    name = re.sub(r"\s+(jr|sr|iii|ii|iv)\.?$", "", name)
    # Remove periods and extra whitespace
    name = re.sub(r"\.", "", name)
    name = re.sub(r"\s+", " ", name)
    return name


def match_candidates(trackaipac_list, fec_list):
    """
    Match TrackAIPAC candidates to FEC candidates by name similarity.
    Returns a dict: fec_index -> trackaipac_candidate
    """
    matches = {}
    ta_by_name = {}
    for tc in trackaipac_list:
        key = normalize_name(tc["name"])
        ta_by_name[key] = tc
        # Also store by last name for fallback
        parts = key.split()
        if parts:
            last = parts[-1]
            ta_by_name.setdefault(f"_last_{last}", [])
            ta_by_name[f"_last_{last}"].append(tc)

    for i, fc in enumerate(fec_list):
        fec_name = normalize_name(fc["name"])

        # Exact match
        if fec_name in ta_by_name:
            matches[i] = ta_by_name[fec_name]
            continue

        # Try matching by last name + state
        parts = fec_name.split()
        if parts:
            last = parts[-1]
            last_matches = ta_by_name.get(f"_last_{last}", [])
            for tc in last_matches:
                if tc.get("state") and fc.get("state"):
                    if tc["state"].upper() == fc["state"].upper():
                        matches[i] = tc
                        break

    return matches


# ---------------------------------------------------------------------------
# Merge with existing FEC data
# ---------------------------------------------------------------------------
def merge_data(trackaipac_candidates):
    """
    Merge TrackAIPAC bundler data into existing candidates.json and total.json.
    """
    # Read existing FEC data
    if os.path.exists(CANDIDATES_PATH):
        with open(CANDIDATES_PATH) as f:
            cand_data = json.load(f)
    else:
        cand_data = {"last_updated": "", "candidates": []}

    if os.path.exists(TOTAL_PATH):
        with open(TOTAL_PATH) as f:
            total_data = json.load(f)
    else:
        total_data = {"usd": 0, "last_updated": ""}

    fec_candidates = cand_data.get("candidates", [])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Match TrackAIPAC candidates to FEC candidates
    matches = match_candidates(trackaipac_candidates, fec_candidates)
    matched_count = len(matches)
    print(f"  Matched {matched_count} of {len(fec_candidates)} FEC candidates")

    bundler_grand_total = 0.0

    # Enrich FEC candidates with bundler data
    for i, fc in enumerate(fec_candidates):
        if i in matches:
            tc = matches[i]
            fc["bundler_total"] = tc["bundler_total"]
            fc["ie_total"] = tc.get("ie_total", 0)
            fc["pac_total"] = fc.get("total", 0)  # FEC total is PAC-only
            fc["total"] = fc["pac_total"] + fc["bundler_total"]
            bundler_grand_total += tc["bundler_total"]
        else:
            # No match - keep existing data, set bundler to 0
            fc["bundler_total"] = fc.get("bundler_total", 0)
            fc["ie_total"] = fc.get("ie_total", 0)
            fc["pac_total"] = fc.get("pac_total", fc.get("total", 0))

    # Add TrackAIPAC candidates not in FEC data
    fec_names = {normalize_name(c["name"]) for c in fec_candidates}
    new_count = 0
    for tc in trackaipac_candidates:
        if normalize_name(tc["name"]) not in fec_names:
            fec_candidates.append(
                {
                    "name": tc["name"],
                    "party": tc.get("party", ""),
                    "state": tc.get("state", ""),
                    "office": tc.get("office", ""),
                    "district": tc.get("district", ""),
                    "total": tc["total"],
                    "pac_total": tc.get("pac_total", 0),
                    "bundler_total": tc.get("bundler_total", 0),
                    "ie_total": tc.get("ie_total", 0),
                    "recipient_id": "",
                    "pacs": [],
                }
            )
            bundler_grand_total += tc.get("bundler_total", 0)
            new_count += 1

    if new_count:
        print(f"  Added {new_count} new candidates from TrackAIPAC")

    # Re-sort by total descending
    fec_candidates.sort(key=lambda x: x.get("total", 0), reverse=True)

    # Update candidates.json
    cand_data["candidates"] = fec_candidates
    cand_data["trackaipac_updated"] = now
    with open(CANDIDATES_PATH, "w") as f:
        json.dump(cand_data, f, indent=2)
        f.write("\n")

    # Update total.json
    fec_total = total_data.get("usd", 0)
    total_data["pac_usd"] = fec_total
    total_data["bundler_usd"] = round(bundler_grand_total, 2)
    total_data["usd"] = round(fec_total + bundler_grand_total, 2)
    total_data["trackaipac_updated"] = now
    with open(TOTAL_PATH, "w") as f:
        json.dump(total_data, f, indent=2)
        f.write("\n")

    print(f"\n  PAC total:     ${fec_total:,.2f}")
    print(f"  Bundler total: ${bundler_grand_total:,.2f}")
    print(f"  Combined:      ${fec_total + bundler_grand_total:,.2f}")

    return bundler_grand_total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("Fetching TrackAIPAC data...")
    all_candidates = []

    # Try both pages: /candidates (2026 cycle) and /congress (career totals)
    # We want /candidates for 2026 cycle consistency
    for page_path in [CANDIDATES_PAGE, CONGRESS_PAGE]:
        print(f"\nTrying {BASE_URL}{page_path}...")

        # Attempt 1: Squarespace JSON API
        print("  Trying Squarespace JSON API...")
        json_data = fetch_json_api(page_path)
        if json_data:
            items = parse_squarespace_json(json_data)
            if items:
                print(f"  Found {len(items)} items via JSON API")
                for item in items:
                    candidate = extract_candidate_from_item(item)
                    if candidate["name"] and candidate["total"] > 0:
                        all_candidates.append(candidate)
                if all_candidates:
                    break

        time.sleep(REQUEST_DELAY)

        # Attempt 2: HTML parsing
        print("  Trying HTML parsing...")
        html = fetch_html(page_path)
        if html:
            candidates = parse_html_page(html)
            if candidates:
                print(f"  Found {len(candidates)} candidates via HTML parsing")
                all_candidates.extend(candidates)
                break
            else:
                # Log what we did find for debugging
                text = html_to_text(html)
                print(f"  Page fetched ({len(html)} bytes) but no candidates parsed")
                # Save raw HTML for debugging
                debug_path = os.path.join(DATA_DIR, "trackaipac_debug.html")
                with open(debug_path, "w") as f:
                    f.write(html)
                print(f"  Saved raw HTML to {debug_path} for inspection")
        else:
            print("  Failed to fetch HTML (likely Cloudflare blocked)")

        time.sleep(REQUEST_DELAY)

    # Save raw TrackAIPAC data
    os.makedirs(DATA_DIR, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    trackaipac_output = {
        "last_updated": now,
        "source": "trackaipac.com",
        "candidates_found": len(all_candidates),
        "candidates": all_candidates,
    }
    with open(TRACKAIPAC_PATH, "w") as f:
        json.dump(trackaipac_output, f, indent=2)
        f.write("\n")

    if not all_candidates:
        print(
            "\nWARNING: No candidates scraped from TrackAIPAC. "
            "The site may be blocking automated requests (Cloudflare).",
            file=sys.stderr,
        )
        print(
            "Consider running with a headless browser or using cached data.",
            file=sys.stderr,
        )
        print(f"Raw data saved to {TRACKAIPAC_PATH}")
        # Don't fail the workflow - FEC data is still valid
        return

    print(f"\nScraped {len(all_candidates)} candidates from TrackAIPAC")

    # Merge with existing FEC data
    print("\nMerging with FEC data...")
    bundler_total = merge_data(all_candidates)

    print(f"\nDone. TrackAIPAC data saved to {TRACKAIPAC_PATH}")
    print(f"Updated {CANDIDATES_PATH}")
    print(f"Updated {TOTAL_PATH}")


if __name__ == "__main__":
    main()
