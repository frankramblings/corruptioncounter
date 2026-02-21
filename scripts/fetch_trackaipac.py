#!/usr/bin/env python3
"""
Scrape candidate contribution data (PACs, IEs, Bundlers) from TrackAIPAC.com
and merge bundler amounts into our existing candidates.json and total.json.

TrackAIPAC is a Squarespace site behind Cloudflare. We try:
1. cloudscraper (handles Cloudflare JS challenges) with Squarespace JSON API
2. Plain urllib with Squarespace JSON API
3. HTML parsing fallback

Squarespace JSON API returns 20 items per page; use &offset=N to paginate.

This script runs AFTER fetch_fec.py and enriches the data it produced.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
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
SQS_PAGE_SIZE = 20  # Squarespace returns 20 items per page
MAX_PAGES = 30  # safety cap: 30 pages = 600 members

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
# HTTP helpers — cloudscraper preferred, urllib fallback
# ---------------------------------------------------------------------------
_session = None


def _get_session():
    """Get or create an HTTP session. Prefers cloudscraper for Cloudflare."""
    global _session
    if _session is not None:
        return _session

    try:
        import cloudscraper

        _session = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "darwin"}
        )
        print("  Using cloudscraper (Cloudflare bypass)")
        return _session
    except ImportError:
        pass

    try:
        import requests as _requests

        _session = _requests.Session()
        _session.headers.update(HEADERS)
        print("  Using requests (no Cloudflare bypass)")
        return _session
    except ImportError:
        pass

    # Bare-minimum fallback: no session, use urllib in fetch_url_urllib
    print("  Using urllib (no Cloudflare bypass, no session)")
    return None


def fetch_url(url, retries=3, delay=2):
    """Fetch a URL with retries and exponential backoff."""
    session = _get_session()

    for attempt in range(retries):
        try:
            if session is not None:
                resp = session.get(url, timeout=30)
                if resp.status_code == 200:
                    return resp.text
                print(
                    f"  Attempt {attempt + 1}/{retries}: HTTP {resp.status_code} "
                    f"for {url}",
                    file=sys.stderr,
                )
            else:
                return _fetch_url_urllib(url)
        except Exception as e:
            print(
                f"  Attempt {attempt + 1}/{retries} failed for {url}: {e}",
                file=sys.stderr,
            )
        if attempt < retries - 1:
            wait = delay * (2 ** attempt)
            time.sleep(wait)
    return None


def _fetch_url_urllib(url):
    """Fallback fetch using stdlib urllib."""
    from urllib.request import urlopen, Request
    from urllib.error import URLError, HTTPError

    req = Request(url, headers=HEADERS)
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except (HTTPError, URLError) as e:
        status = getattr(e, "code", None)
        print(f"  urllib error: {status or e.reason} for {url}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# Squarespace JSON API — paginated
# ---------------------------------------------------------------------------
def fetch_squarespace_collection(path):
    """
    Fetch all items from a Squarespace collection page using the JSON API.
    Paginates with ?format=json&offset=N (20 items per page).
    Returns list of raw Squarespace item dicts.
    """
    all_items = []
    offset = 0

    for page_num in range(MAX_PAGES):
        url = f"{BASE_URL}{path}?format=json&offset={offset}"
        if page_num == 0:
            print(f"  Fetching {url}")
        else:
            print(f"  Fetching page {page_num + 1} (offset={offset})...")

        raw = fetch_url(url, retries=2, delay=2)
        if not raw:
            break

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            print(f"  Response is not valid JSON (likely Cloudflare challenge page)")
            break

        # Extract items from various Squarespace response shapes
        items = []
        if isinstance(data, dict):
            items = data.get("items", [])
            if not items:
                coll = data.get("collection", {})
                items = coll.get("items", [])
            if not items:
                # Some pages put items under "past" or "upcoming"
                items = data.get("past", []) + data.get("upcoming", [])

        if not items:
            if page_num == 0:
                print(f"  No items found in JSON response")
                # Log response keys for debugging
                if isinstance(data, dict):
                    print(f"  Response keys: {list(data.keys())}")
            break

        all_items.extend(items)
        print(f"  Got {len(items)} items (total: {len(all_items)})")

        # If we got fewer than a full page, we've reached the end
        if len(items) < SQS_PAGE_SIZE:
            break

        offset += SQS_PAGE_SIZE
        time.sleep(REQUEST_DELAY)

    return all_items


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
# Squarespace item parsing
# ---------------------------------------------------------------------------
def extract_candidate_from_item(item):
    """
    Extract candidate data from a Squarespace collection item.
    The body HTML likely contains contribution breakdowns like:
      "PACs: $18,475  IE: $0  Bundlers: $199,040"
    or:
      "Israel Lobby Total: $217,515"
    """
    title = item.get("title", "")
    body_html = item.get("body", "")
    excerpt = item.get("excerpt", "")
    custom = item.get("customContent", {}) or {}

    # Combine all text sources for pattern matching
    body_text = html_to_text(body_html) if body_html else ""
    all_text = f"{body_text} {excerpt}"

    # Also check structured excerpt (Squarespace sometimes puts data here)
    if not body_text and excerpt:
        all_text = html_to_text(excerpt) if "<" in excerpt else excerpt

    # Look for patterns like "PACs: $18,475" "Bundlers: $199,040" "IE: $0"
    pac_match = re.search(
        r"PACs?\s*(?:donations?)?\s*[:\s]*\$?([\d,]+)", all_text, re.IGNORECASE
    )
    bundler_match = re.search(
        r"Bundlers?\s*(?:donations?)?\s*[:\s]*\$?([\d,]+)", all_text, re.IGNORECASE
    )
    ie_match = re.search(
        r"(?:IE|Independent\s+[Ee]xpenditures?)\s*[:\s]*\$?([\d,]+)",
        all_text,
        re.IGNORECASE,
    )
    total_match = re.search(
        r"(?:Israel\s+Lobby\s+)?Total[:\s]*\$?([\d,]+)", all_text, re.IGNORECASE
    )

    pacs = parse_money(pac_match.group(1)) if pac_match else 0
    bundlers = parse_money(bundler_match.group(1)) if bundler_match else 0
    ie = parse_money(ie_match.group(1)) if ie_match else 0
    total = (
        parse_money(total_match.group(1))
        if total_match
        else (pacs + bundlers + ie)
    )

    # Try to extract state/party from tags, categories, or custom content
    tags = item.get("tags", []) or []
    categories = item.get("categories", []) or []

    state = ""
    party = ""
    office = ""
    district = ""

    state_pattern = re.compile(r"^[A-Z]{2}$")
    party_map = {"DEM": "DEM", "REP": "REP", "D": "DEM", "R": "REP",
                 "DEMOCRAT": "DEM", "REPUBLICAN": "REP"}
    office_map = {"HOUSE": "H", "SENATE": "S", "PRESIDENT": "P"}

    for tag in tags + categories:
        tag_upper = tag.upper().strip()
        if state_pattern.match(tag.strip()):
            state = tag.strip().upper()
        elif tag_upper in party_map:
            party = party_map[tag_upper]
        elif tag_upper in office_map:
            office = office_map[tag_upper]

    # Also check customContent fields
    for key, target in [("state", "state"), ("party", "party"),
                        ("office", "office"), ("district", "district")]:
        if key in custom and custom[key]:
            val = str(custom[key]).strip()
            if key == "state":
                state = val.upper()
            elif key == "party":
                party = party_map.get(val.upper(), val.upper())
            elif key == "office":
                office = office_map.get(val.upper(), val[0].upper())
            elif key == "district":
                district = val

    # Try to extract state/party from body text as last resort
    if not state:
        state_in_text = re.search(r"\b([A-Z]{2})-(\d{2})\b", all_text)
        if state_in_text:
            state = state_in_text.group(1)
            district = state_in_text.group(2)

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
    Parse candidate data from raw HTML when JSON API fails.
    """
    candidates = []

    # Strategy 1: Look for JSON-LD or embedded JSON data
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

    # Strategy 2: Look for __NEXT_DATA__ (in case site migrated off Squarespace)
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

    # Strategy 3: Parse visible text for contribution patterns
    text = html_to_text(html)

    # Pattern: "Name ... PACs: $X ... Bundlers: $Y"
    # Use a broad pattern that captures name-like strings near dollar amounts
    candidate_pattern = re.compile(
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)'  # Name (2+ capitalized words)
        r'.*?'
        r'PACs?\s*(?:donations?)?\s*[:\s]*\$?([\d,]+)'
        r'.*?'
        r'Bundlers?\s*(?:donations?)?\s*[:\s]*\$?([\d,]+)',
        re.DOTALL | re.IGNORECASE,
    )

    for match in candidate_pattern.finditer(text):
        name = match.group(1).strip()
        pac_amt = parse_money(match.group(2))
        bundler_amt = parse_money(match.group(3))

        candidates.append({
            "name": name,
            "state": "",
            "party": "",
            "office": "",
            "district": "",
            "pac_total": pac_amt,
            "bundler_total": bundler_amt,
            "ie_total": 0,
            "total": pac_amt + bundler_amt,
        })

    return candidates


def extract_from_nextjs(data):
    """Extract candidate data from Next.js page props."""
    candidates = []
    props = data.get("props", {}).get("pageProps", {})
    for key, val in props.items():
        if isinstance(val, list) and len(val) > 0:
            if isinstance(val[0], dict) and any(
                k in val[0] for k in ("name", "total", "bundlers", "pacs")
            ):
                for item in val:
                    candidates.append({
                        "name": item.get("name", ""),
                        "state": item.get("state", ""),
                        "party": item.get("party", ""),
                        "office": item.get("office", ""),
                        "district": item.get("district", ""),
                        "pac_total": item.get("pacs", 0),
                        "bundler_total": item.get("bundlers", 0),
                        "ie_total": item.get("ie", 0),
                        "total": item.get("total", 0),
                    })
    return candidates


# ---------------------------------------------------------------------------
# Candidate name normalization for matching
# ---------------------------------------------------------------------------
def normalize_name(name):
    """Normalize a candidate name for fuzzy matching."""
    name = name.lower().strip()
    name = re.sub(r"\s+(jr|sr|iii|ii|iv)\.?$", "", name)
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

    matches = match_candidates(trackaipac_candidates, fec_candidates)
    matched_count = len(matches)
    print(f"  Matched {matched_count} of {len(fec_candidates)} FEC candidates")

    bundler_grand_total = 0.0

    for i, fc in enumerate(fec_candidates):
        if i in matches:
            tc = matches[i]
            fc["bundler_total"] = tc["bundler_total"]
            fc["ie_total"] = tc.get("ie_total", 0)
            fc["pac_total"] = fc.get("total", 0)  # FEC total is PAC-only
            fc["total"] = fc["pac_total"] + fc["bundler_total"]
            bundler_grand_total += tc["bundler_total"]
        else:
            fc["bundler_total"] = fc.get("bundler_total", 0)
            fc["ie_total"] = fc.get("ie_total", 0)
            fc["pac_total"] = fc.get("pac_total", fc.get("total", 0))

    # Add TrackAIPAC candidates not in FEC data
    fec_names = {normalize_name(c["name"]) for c in fec_candidates}
    new_count = 0
    for tc in trackaipac_candidates:
        if normalize_name(tc["name"]) not in fec_names:
            fec_candidates.append({
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
            })
            bundler_grand_total += tc.get("bundler_total", 0)
            new_count += 1

    if new_count:
        print(f"  Added {new_count} new candidates from TrackAIPAC")

    fec_candidates.sort(key=lambda x: x.get("total", 0), reverse=True)

    cand_data["candidates"] = fec_candidates
    cand_data["trackaipac_updated"] = now
    with open(CANDIDATES_PATH, "w") as f:
        json.dump(cand_data, f, indent=2)
        f.write("\n")

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

    # Try /candidates first (2026 cycle), fall back to /congress (career totals)
    for page_path in [CANDIDATES_PAGE, CONGRESS_PAGE]:
        print(f"\nTrying {BASE_URL}{page_path}...")

        # Attempt 1: Squarespace JSON API with pagination
        print("  Trying Squarespace JSON API (paginated)...")
        items = fetch_squarespace_collection(page_path)
        if items:
            print(f"  Found {len(items)} total items via JSON API")
            for item in items:
                candidate = extract_candidate_from_item(item)
                if candidate["name"] and candidate["total"] > 0:
                    all_candidates.append(candidate)

            if all_candidates:
                print(f"  Parsed {len(all_candidates)} candidates with data")
                break
            else:
                print("  Items found but no contribution data parsed")

        time.sleep(REQUEST_DELAY)

        # Attempt 2: HTML parsing
        print("  Trying HTML parsing...")
        html = fetch_url(f"{BASE_URL}{page_path}")
        if html:
            candidates = parse_html_page(html)
            if candidates:
                print(f"  Found {len(candidates)} candidates via HTML parsing")
                all_candidates.extend(candidates)
                break
            else:
                print(f"  Page fetched ({len(html)} bytes) but no candidates parsed")
                debug_path = os.path.join(DATA_DIR, "trackaipac_debug.html")
                os.makedirs(DATA_DIR, exist_ok=True)
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
            "Try: pip install cloudscraper  (or use Playwright for full browser)",
            file=sys.stderr,
        )
        print(f"Raw data saved to {TRACKAIPAC_PATH}")
        return

    print(f"\nScraped {len(all_candidates)} candidates from TrackAIPAC")

    # Merge with existing FEC data
    print("\nMerging with FEC data...")
    merge_data(all_candidates)

    print(f"\nDone. TrackAIPAC data saved to {TRACKAIPAC_PATH}")
    print(f"Updated {CANDIDATES_PATH}")
    print(f"Updated {TOTAL_PATH}")


if __name__ == "__main__":
    main()
