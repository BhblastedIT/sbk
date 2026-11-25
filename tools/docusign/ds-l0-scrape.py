#!/usr/bin/env python3
"""DocuSign contract details scraper (L0)."""





























from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from sbk_config import DOCUSIGN_RAW_DIR, safe_write_json, safe_write_parquet



RAW_DIR = DOCUSIGN_RAW_DIR
OUTPUT_DIR = RAW_DIR / "raw"
PROCESSED_DIR = RAW_DIR / "processed"
METADATA_FILE = RAW_DIR / "contracts-metadata.json"
DETAILS_FILE = OUTPUT_DIR / "contract-details.json"
ERRORS_FILE = OUTPUT_DIR / "_scrape_errors.json"

DEFAULT_DELAY = 3.0
CHROME_JS_TIMEOUT = 30
DOCUSIGN_DOMAIN = "docusign"

# DocuSign API region base and envelope start date: set these to match your
# account via env vars (the region base must match the account's data center).
DOCUSIGN_API_BASE = os.environ.get("DOCUSIGN_API_BASE", "https://na4.docusign.net")
DOCUSIGN_FROM_DATE = os.environ.get("DOCUSIGN_FROM_DATE", "2020-01-01T00:00:00Z")

log = logging.getLogger("docusign-scraper")





def chrome_js(js_code: str, timeout: int = CHROME_JS_TIMEOUT) -> str | None:
    ""




    escaped = js_code.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    applescript = f'''
    tell application "Google Chrome"
        repeat with w in windows
            repeat with t in tabs of w
                if URL of t contains "{DOCUSIGN_DOMAIN}" then
                    tell t
                        set jsResult to execute javascript "{escaped}"
                    end tell
                    return jsResult
                end if
            end repeat
        end repeat
        return "ERROR_NO_DOCUSIGN_TAB"
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", applescript], capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        log.error(f"AppleScript timeout after {timeout}s")
        return None

    output = result.stdout.strip()
    if output == "ERROR_NO_DOCUSIGN_TAB":
        log.error("No DocuSign tab open in Chrome!")
        log.error("Open Chrome, go to apps.docusign.com and log in.")
        sys.exit(1)
    if result.returncode != 0:
        log.error(f"AppleScript error: {result.stderr[:300]}")
        return None

    return output













def test_connection() -> dict:
    ""



    js = """
    (function() {
        try {
            var url = window.location.href;
            var title = document.title;
            // Check if we're on DocuSign
            if (url.indexOf('docusign') === -1) {
                return JSON.stringify({error: 'not_docusign', url: url});
            }
            // Try to extract account ID from URL
            var match = url.match(/account-id=([^&]+)/);
            var accountId = match ? match[1] : '';
            // Or from the page
            if (!accountId) {
                match = url.match(/accounts\\/([a-f0-9-]+)/);
                accountId = match ? match[1] : '';
            }
            // Check if logged in (look for profile menu, nav buttons, or known URL paths)
            var profileEl = document.querySelector('[data-qa="header-profile-menu"]') ||
                           document.querySelector('[data-qa="header-MANAGE-tab-button"]') ||
                           document.querySelector('[data-qa="header-HOME-tab-button"]') ||
                           document.querySelector('[class*="profile"]') ||
                           document.querySelector('[aria-label*="profile"]');
            var loggedIn = profileEl !== null ||
                           url.indexOf('/manage') !== -1 ||
                           url.indexOf('/home') !== -1 ||
                           url.indexOf('/documents') !== -1;
            return JSON.stringify({
                ok: true,
                url: url,
                title: title,
                accountId: accountId,
                loggedIn: loggedIn
            });
        } catch(e) {
            return JSON.stringify({error: e.message});
        }
    })()
    """
    result = chrome_js(js)
    if not result:
        return {"error": "no_response"}
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        return {"error": "invalid_json", "raw": result[:500]}


def discover_envelope_ids_from_list_page() -> list[dict]:
    ""





    js = """
    (function() {
        try {
            var results = [];

            // Strategy 1: Look for envelope links in the agreement list
            // DocuSign uses data-qa attributes and links like /details/{envelopeId}
            var links = document.querySelectorAll('a[href*="envelopes"], a[href*="details"], a[href*="envelope"]');
            for (var i = 0; i < links.length; i++) {
                var href = links[i].href || '';
                var match = href.match(/(?:envelopes|details)\\/([a-f0-9-]{36})/i);
                if (match) {
                    results.push({
                        envelopeId: match[1],
                        name: (links[i].textContent || '').trim().substring(0, 200),
                        href: href
                    });
                }
            }

            // Strategy 2: Look for data attributes on rows (new + legacy selectors)
            if (results.length === 0) {
                var rows = document.querySelectorAll(
                    '[data-qa*="envelope"], [data-envelope-id], ' +
                    '[data-qa*="agreement"], [data-qa*="document-row"], ' +
                    'tr[class*="envelope"], [class*="agreement-row"], ' +
                    '[class*="EnvelopeRow"], [class*="document-row"], ' +
                    '[role="row"], table tbody tr'
                );
                for (var i = 0; i < rows.length; i++) {
                    var eid = rows[i].getAttribute('data-envelope-id') ||
                              rows[i].getAttribute('data-qa-value') ||
                              rows[i].getAttribute('data-id') || '';
                    // Also check for UUID in any href within the row
                    if (!eid || !eid.match(/^[a-f0-9-]{36}$/i)) {
                        var rowLink = rows[i].querySelector('a[href]');
                        if (rowLink) {
                            var m = (rowLink.href || '').match(/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})/i);
                            if (m) eid = m[1];
                        }
                    }
                    if (eid && eid.match(/^[a-f0-9-]{36}$/i)) {
                        var nameEl = rows[i].querySelector('[class*="subject"], [class*="name"], [class*="title"], a') || rows[i];
                        results.push({
                            envelopeId: eid,
                            name: (nameEl.textContent || '').trim().substring(0, 200)
                        });
                    }
                }
            }

            // Strategy 3: Scan all elements for envelope ID pattern in any attribute
            if (results.length === 0) {
                var allLinks = document.querySelectorAll('a[href]');
                for (var i = 0; i < allLinks.length; i++) {
                    var href = allLinks[i].href || '';
                    // UUID pattern in URL
                    var match = href.match(/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})/i);
                    if (match && href.indexOf('docusign') !== -1) {
                        results.push({
                            envelopeId: match[1],
                            name: (allLinks[i].textContent || '').trim().substring(0, 200),
                            href: href
                        });
                    }
                }
            }

            // Deduplicate by envelope ID
            var seen = {};
            var unique = [];
            for (var i = 0; i < results.length; i++) {
                if (!seen[results[i].envelopeId]) {
                    seen[results[i].envelopeId] = true;
                    unique.push(results[i]);
                }
            }

            return JSON.stringify({ok: true, count: unique.length, envelopes: unique});
        } catch(e) {
            return JSON.stringify({error: e.message});
        }
    })()
    """
    result = chrome_js(js, timeout=30)
    if not result:
        return []
    try:
        data = json.loads(result)
        if data.get("ok"):
            return data.get("envelopes", [])
        log.warning(f"discover_envelope_ids error: {data.get('error')}")
        return []
    except json.JSONDecodeError:
        return []


def fetch_envelope_recipients_via_api(envelope_id: str) -> dict | None:
    ""






    js = f"""
    (function() {{
        try {{
            // Extract account ID and base URL from the current page
            var url = window.location.href;

            // Try to find the API base from DocuSign's own config
            // The web app stores config in window.__env or similar
            var apiBase = '';
            var accountId = '';

            // Method 1: extract from URL
            var match = url.match(/accounts\\/([a-f0-9-]+)/i);
            if (match) accountId = match[1];

            // Method 2: look in page scripts/config
            if (!accountId) {{
                var scripts = document.querySelectorAll('script');
                for (var i = 0; i < scripts.length; i++) {{
                    var text = scripts[i].textContent || '';
                    var m = text.match(/"accountId"\\s*:\\s*"([a-f0-9-]+)"/i);
                    if (m) {{ accountId = m[1]; break; }}
                }}
            }}

            // Method 3: check meta tags or global vars
            if (!accountId) {{
                if (window.__env && window.__env.accountId) accountId = window.__env.accountId;
            }}

            if (!accountId) {{
                return JSON.stringify({{error: 'no_account_id', url: url}});
            }}

            // Determine API base (EU vs US)
            // EU uses eu.docusign.net, US uses na*.docusign.net
            if (url.indexOf('.eu.') !== -1 || url.indexOf('eu.docusign') !== -1) {{
                apiBase = 'https://eu.docusign.net';
            }} else if (url.indexOf('apps.docusign.com') !== -1) {{
                // apps.docusign.com may be US or EU; try both
                apiBase = 'https://docusign.net';
            }} else {{
                apiBase = 'https://docusign.net';
            }}

            // Try the recipients API call using the browser's session cookie
            var endpoints = [
                apiBase + '/restapi/v2.1/accounts/' + accountId + '/envelopes/{envelope_id}/recipients',
                'https://eu.docusign.net/restapi/v2.1/accounts/' + accountId + '/envelopes/{envelope_id}/recipients',
                'https://na4.docusign.net/restapi/v2.1/accounts/' + accountId + '/envelopes/{envelope_id}/recipients'
            ];

            for (var ei = 0; ei < endpoints.length; ei++) {{
                var xhr = new XMLHttpRequest();
                xhr.open('GET', endpoints[ei], false);
                xhr.withCredentials = true;

                // Try to get CSRF token if present
                var csrfMeta = document.querySelector('meta[name="csrf-token"]');
                if (csrfMeta) {{
                    xhr.setRequestHeader('X-CSRF-Token', csrfMeta.content);
                }}
                xhr.setRequestHeader('Accept', 'application/json');

                try {{
                    xhr.send();
                    if (xhr.status === 200) {{
                        var data = JSON.parse(xhr.responseText);
                        return JSON.stringify({{
                            ok: true,
                            accountId: accountId,
                            endpoint: endpoints[ei],
                            recipients: data
                        }});
                    }}
                }} catch(ex) {{
                    // Try next endpoint
                }}
            }}

            return JSON.stringify({{error: 'api_failed', accountId: accountId, status: xhr ? xhr.status : 0}});
        }} catch(e) {{
            return JSON.stringify({{error: e.message}});
        }}
    }})()
    """
    result = chrome_js(js, timeout=30)
    if not result:
        return None
    try:
        data = json.loads(result)
        return data
    except json.JSONDecodeError:
        return None


def scrape_recipients_from_detail_page(envelope_id: str) -> dict | None:
    ""






    js = """
    (function() {
        try {
            var recipients = [];

            // Look for recipient sections in the detail page
            // DocuSign shows recipients as a list with name + email

            // Strategy 1: Look for email patterns in specific containers
            var recipientContainers = document.querySelectorAll(
                '[class*="recipient"], [class*="signer"], [data-qa*="recipient"], ' +
                '[class*="Recipient"], [class*="Signer"], [role="listitem"]'
            );

            for (var i = 0; i < recipientContainers.length; i++) {
                var text = recipientContainers[i].textContent || '';
                var emailMatch = text.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}/);
                if (emailMatch) {
                    // Try to get the name (usually before the email)
                    var name = text.replace(emailMatch[0], '').trim();
                    // Clean up the name
                    name = name.replace(/\\s+/g, ' ').replace(/^[\\s,;|-]+|[\\s,;|-]+$/g, '').trim();
                    // Remove status words
                    name = name.replace(/\\b(Completed|Signed|Sent|Delivered|Viewed|Declined|Voided|Needs to sign|Needs to view|Action required)\\b/gi, '').trim();
                    name = name.replace(/^[\\s,;|-]+|[\\s,;|-]+$/g, '').trim();
                    if (name.length > 100) name = name.substring(0, 100);
                    recipients.push({
                        name: name,
                        email: emailMatch[0],
                        source: 'container'
                    });
                }
            }

            // Strategy 2: Scan the entire page for email patterns near person names
            if (recipients.length === 0) {
                var body = document.body.innerText || '';
                var emailRegex = /([A-Za-z][A-Za-z .'-]{1,60})\\s*[\\n\\r]+\\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,})/g;
                var match;
                while ((match = emailRegex.exec(body)) !== null) {
                    var name = match[1].trim();
                    var email = match[2].trim();
                    // Filter out generic UI text
                    if (name.length > 1 && name.length < 80 && !name.match(/^(From|To|CC|Subject|Date|Page|Status)/i)) {
                        recipients.push({
                            name: name,
                            email: email,
                            source: 'body_scan'
                        });
                    }
                }
            }

            // Strategy 3: Just get all emails on the page
            if (recipients.length === 0) {
                var body = document.body.innerText || '';
                var allEmails = body.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}/g) || [];
                for (var i = 0; i < allEmails.length; i++) {
                    recipients.push({
                        name: '',
                        email: allEmails[i],
                        source: 'page_emails'
                    });
                }
            }

            // Deduplicate by email
            var seen = {};
            var unique = [];
            for (var i = 0; i < recipients.length; i++) {
                var email = recipients[i].email.toLowerCase();
                if (!seen[email]) {
                    seen[email] = true;
                    unique.push(recipients[i]);
                }
            }

            // Get page title and URL for context
            return JSON.stringify({
                ok: true,
                url: window.location.href,
                title: document.title,
                recipientCount: unique.length,
                recipients: unique,
                pageTextLength: (document.body.innerText || '').length
            });
        } catch(e) {
            return JSON.stringify({error: e.message});
        }
    })()
    """
    result = chrome_js(js, timeout=30)
    if not result:
        return None
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        return None


def get_current_page_info() -> dict:
    ""
    js = """
    (function() {
        try {
            var url = window.location.href;
            var title = document.title;

            // Count visible contract rows
            var rows = document.querySelectorAll('tr, [class*="envelope-row"], [class*="agreement"]');

            // Check for pagination info
            var pageText = document.body.innerText;
            var pageMatch = pageText.match(/(\\d+)-(\\d+) of (\\d+)/);
            var pagination = pageMatch ? {
                from: parseInt(pageMatch[1]),
                to: parseInt(pageMatch[2]),
                total: parseInt(pageMatch[3])
            } : null;

            // Check for "Next" button
            var nextBtn = document.querySelector('[aria-label="Next"], [data-qa="pagination-next"], button:has(> [class*="next"])');
            var hasNext = nextBtn && !nextBtn.disabled;

            return JSON.stringify({
                url: url,
                title: title,
                visibleRows: rows.length,
                pagination: pagination,
                hasNext: hasNext
            });
        } catch(e) {
            return JSON.stringify({error: e.message});
        }
    })()
    """
    result = chrome_js(js)
    if not result:
        return {}
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        return {}





def discover_all_envelopes(metadata: list[dict]) -> list[dict]:
    ""





    log.info("Phase 1: Discovering envelope IDs from list pages...")

    all_envelopes = []
    page = 1
    max_pages = 20


    log.info("  Navigating to DocuSign Agreements page...")
    nav_js = """
    (function() {
        var btn = document.querySelector('[data-qa="header-MANAGE-tab-button"]');
        if (btn) { btn.click(); return 'clicked'; }
        return 'not_found';
    })()
    """
    nav_result = chrome_js(nav_js)
    if nav_result == "clicked":
        time.sleep(3)
        log.info("  Navigated to Agreements page")
    else:
        log.warning("  Could not find Agreements button, trying current page")

    while page <= max_pages:
        log.info(f"  Scanning page {page}...")


        page_info = get_current_page_info()
        log.info(f"    URL: {page_info.get('url', 'unknown')[:100]}")
        if page_info.get("pagination"):
            p = page_info["pagination"]
            log.info(f"    Showing {p['from']}-{p['to']} of {p['total']}")


        envelopes = discover_envelope_ids_from_list_page()
        log.info(f"    Found {len(envelopes)} envelope IDs")

        if envelopes:
            all_envelopes.extend(envelopes)


        if not page_info.get("hasNext", False):
            log.info("  No more pages (Next button disabled or not found).")
            break


        js_next = """
        (function() {
            var nextBtn = document.querySelector('[aria-label="Next"], [data-qa="pagination-next"]');
            if (nextBtn && !nextBtn.disabled) {
                nextBtn.click();
                return 'clicked';
            }
            // Try finding a next button another way
            var buttons = document.querySelectorAll('button');
            for (var i = 0; i < buttons.length; i++) {
                if (buttons[i].textContent.trim() === 'Next' ||
                    buttons[i].getAttribute('aria-label') === 'Next page') {
                    buttons[i].click();
                    return 'clicked_alt';
                }
            }
            return 'no_next';
        })()
        """
        result = chrome_js(js_next)
        if result == "no_next":
            log.info("  No next button found.")
            break


        time.sleep(3)
        page += 1


    seen = set()
    unique = []
    for env in all_envelopes:
        eid = env.get("envelopeId", "")
        if eid and eid not in seen:
            seen.add(eid)
            unique.append(env)

    log.info(f"\n  Total unique envelope IDs discovered: {len(unique)}")
    return unique





def scrape_all_recipients(
    envelopes: list[dict],
    existing_details: dict,
    delay: float = DEFAULT_DELAY,
    limit: int | None = None,
) -> dict:
    ""








    total = len(envelopes)
    if limit:
        envelopes = envelopes[:limit]
        log.info(f"Limiting to first {limit} envelopes")

    to_scrape = [e for e in envelopes if e.get("envelopeId") not in existing_details]
    already_done = len(envelopes) - len(to_scrape)

    log.info("\nPhase 2: Scraping recipient details...")
    log.info(f"  Total envelopes: {total}")
    log.info(f"  Already scraped: {already_done}")
    log.info(f"  To scrape: {len(to_scrape)}")
    log.info(f"  Delay: {delay}s between requests")
    log.info("")

    scraped = 0
    errors = 0
    error_list = []

    for i, env in enumerate(to_scrape):
        eid = env["envelopeId"]
        name = env.get("name", "")[:70]

        try:
            log.info(f"  [{i + 1}/{len(to_scrape)}] {eid[:12]}... {name}")


            api_result = fetch_envelope_recipients_via_api(eid)

            if api_result and api_result.get("ok"):
                recipients_data = api_result.get("recipients", {})


                recipients = []
                for role_key in [
                    "signers",
                    "carbonCopies",
                    "certifiedDeliveries",
                    "inPersonSigners",
                    "agents",
                    "editors",
                    "intermediaries",
                    "seals",
                    "witnesses",
                ]:
                    role_list = recipients_data.get(role_key, [])
                    if isinstance(role_list, list):
                        for r in role_list:
                            recipients.append(
                                {
                                    "name": r.get("name", ""),
                                    "email": r.get("email", ""),
                                    "role": role_key.rstrip("s"),
                                    "status": r.get("status", ""),
                                    "recipientId": r.get("recipientId", ""),
                                    "routingOrder": r.get("routingOrder", ""),
                                    "deliveredDateTime": r.get("deliveredDateTime", ""),
                                    "signedDateTime": r.get("signedDateTime", ""),
                                    "source": "api",
                                }
                            )

                existing_details[eid] = {
                    "envelopeId": eid,
                    "name": env.get("name", ""),
                    "recipients": recipients,
                    "recipientCount": len(recipients),
                    "scrapedAt": datetime.now(UTC).isoformat(),
                    "method": "api",
                    "apiEndpoint": api_result.get("endpoint", ""),
                }
                scraped += 1
                emails = [r["email"] for r in recipients if r.get("email")]
                log.info(f"    API OK: {len(recipients)} recipients — {', '.join(emails)}")

            else:








                log.warning(f"    SKIP: the API does not cover {eid}, and the owner's browser tab is not navigated")
                errors += 1
                error_list.append({"envelopeId": eid, "name": name, "error": "api_only"})


            time.sleep(delay)


            if (i + 1) % 25 == 0:
                save_details(existing_details)
                log.info(f"    [checkpoint saved: {len(existing_details)} total]")

        except KeyboardInterrupt:
            log.info("\n  Interrupted! Saving progress...")
            save_details(existing_details)
            break
        except Exception as e:
            errors += 1
            err_msg = str(e)[:120]
            log.error(f"    ERROR: {err_msg}")
            error_list.append({"envelopeId": eid, "name": name, "error": err_msg})

            if "timeout" in str(e).lower():
                log.info("    Pausa 5s per timeout...")
                time.sleep(5)


    if error_list:
        safe_write_json(ERRORS_FILE, error_list)
        log.info(f"  Errors saved to {ERRORS_FILE}")

    log.info(
        f"\n  Scrape results: {scraped} OK, {errors} errors, {already_done} skipped (already done)"
    )
    return existing_details





def discover_and_scrape_via_api(
    metadata: list[dict],
    existing_details: dict,
    delay: float = DEFAULT_DELAY,
    limit: int | None = None,
    api_base: str = DOCUSIGN_API_BASE,
    from_date: str = DOCUSIGN_FROM_DATE,
) -> dict:
    ""





    log.info("Attempting bulk envelope discovery via API...")

    js = """
    (function() {
        try {
            var url = window.location.href;
            var accountId = '';

            // Extract account ID
            var match = url.match(/accounts\\/([a-f0-9-]+)/i);
            if (match) accountId = match[1];

            if (!accountId) {
                // Try page content
                var body = document.body.innerHTML;
                match = body.match(/accountId['":\\s]+([a-f0-9-]{36})/i);
                if (match) accountId = match[1];
            }

            if (!accountId) {
                // Try localStorage (new DocuSign UI stores account info here)
                try {
                    for (var i = 0; i < localStorage.length; i++) {
                        var key = localStorage.key(i);
                        var val = localStorage.getItem(key);
                        if (val && val.length < 500) {
                            var lsMatch = val.match(/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})/i);
                            if (lsMatch && key.toLowerCase().indexOf('account') !== -1) {
                                accountId = lsMatch[1];
                                break;
                            }
                        }
                    }
                } catch(e) {}
            }

            if (!accountId) {
                return JSON.stringify({error: 'no_account_id'});
            }

            // Try to fetch envelopes list from API
            var apiBase = '__API_BASE__';
            var apiUrl = apiBase + '/restapi/v2.1/accounts/' + accountId +
                        '/envelopes?from_date=__FROM_DATE__&count=100&order=desc&order_by=last_modified';

            var xhr = new XMLHttpRequest();
            xhr.open('GET', apiUrl, false);
            xhr.withCredentials = true;
            xhr.setRequestHeader('Accept', 'application/json');
            xhr.send();

            if (xhr.status === 200) {
                var data = JSON.parse(xhr.responseText);
                var envelopes = (data.envelopes || []).map(function(e) {
                    return {
                        envelopeId: e.envelopeId,
                        name: e.emailSubject || '',
                        status: e.status || '',
                        sentDateTime: e.sentDateTime || '',
                        completedDateTime: e.completedDateTime || ''
                    };
                });
                return JSON.stringify({
                    ok: true,
                    accountId: accountId,
                    totalSetSize: data.totalSetSize || 0,
                    resultSetSize: data.resultSetSize || 0,
                    count: envelopes.length,
                    envelopes: envelopes,
                    nextUri: data.nextUri || ''
                });
            } else {
                return JSON.stringify({error: 'api_' + xhr.status, accountId: accountId});
            }
        } catch(e) {
            return JSON.stringify({error: e.message});
        }
    })()
    """

    js = js.replace("__API_BASE__", api_base).replace("__FROM_DATE__", from_date)

    all_envelopes = []
    result = chrome_js(js, timeout=45)

    if not result:
        log.warning("  API discovery failed: no response")
        return existing_details

    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        log.warning("  API discovery failed: invalid JSON")
        return existing_details

    if not data.get("ok"):
        log.warning(f"  API discovery failed: {data.get('error')}")
        return existing_details

    account_id = data.get("accountId", "")
    total = data.get("totalSetSize", 0)
    log.info(f"  API discovery OK! Account: {account_id}")
    log.info(f"  Total envelopes in account: {total}")
    log.info(f"  First batch: {data.get('count', 0)} envelopes")

    all_envelopes.extend(data.get("envelopes", []))


    next_uri = data.get("nextUri", "")
    page = 2
    while next_uri and len(all_envelopes) < int(total):
        log.info(f"  Fetching page {page}... ({len(all_envelopes)}/{total})")

        js_page = f"""
        (function() {{
            try {{
                var xhr = new XMLHttpRequest();
                xhr.open('GET', '{api_base}{next_uri}', false);
                xhr.withCredentials = true;
                xhr.setRequestHeader('Accept', 'application/json');
                xhr.send();
                if (xhr.status === 200) {{
                    var data = JSON.parse(xhr.responseText);
                    var envelopes = (data.envelopes || []).map(function(e) {{
                        return {{
                            envelopeId: e.envelopeId,
                            name: e.emailSubject || '',
                            status: e.status || '',
                            sentDateTime: e.sentDateTime || '',
                            completedDateTime: e.completedDateTime || ''
                        }};
                    }});
                    return JSON.stringify({{
                        ok: true,
                        count: envelopes.length,
                        envelopes: envelopes,
                        nextUri: data.nextUri || ''
                    }});
                }}
                return JSON.stringify({{error: 'page_' + xhr.status}});
            }} catch(e) {{
                return JSON.stringify({{error: e.message}});
            }}
        }})()
        """

        time.sleep(delay)
        page_result = chrome_js(js_page, timeout=45)
        if not page_result:
            break
        try:
            page_data = json.loads(page_result)
            if not page_data.get("ok"):
                break
            all_envelopes.extend(page_data.get("envelopes", []))
            next_uri = page_data.get("nextUri", "")
            page += 1
        except json.JSONDecodeError:
            break

    log.info(f"  Total envelopes discovered: {len(all_envelopes)}")


    return scrape_all_recipients(all_envelopes, existing_details, delay=delay, limit=limit)





def load_metadata() -> list[dict]:
    ""
    if not METADATA_FILE.exists():
        log.error(f"Metadata file not found: {METADATA_FILE}")
        sys.exit(1)
    with open(METADATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    data = [
        d
        for d in data
        if d.get("name", "").strip() and d["name"].strip().lower() != "send a document"
    ]
    log.info(f"Loaded {len(data)} contracts from metadata")
    return data


def load_existing_details() -> dict:
    ""
    if DETAILS_FILE.exists():
        try:
            with open(DETAILS_FILE, encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                return {d["envelopeId"]: d for d in data if "envelopeId" in d}
            elif isinstance(data, dict):
                return data
        except (json.JSONDecodeError, KeyError):
            log.warning(f"Could not load existing details from {DETAILS_FILE}, starting fresh")
    return {}


def save_details(details: dict):
    ""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    sorted_list = sorted(details.values(), key=lambda d: d.get("name", ""))
    safe_write_json(DETAILS_FILE, sorted_list)
    log.info(f"Saved {len(details)} contract details to {DETAILS_FILE}")





def show_stats(details: dict):
    ""
    if not details:
        log.info("No scraped data found. Run the scraper first.")
        return

    total = len(details)
    with_recipients = sum(1 for d in details.values() if d.get("recipients"))
    total_recipients = sum(len(d.get("recipients", [])) for d in details.values())


    all_emails = set()
    email_to_names = {}
    for d in details.values():
        for r in d.get("recipients", []):
            email = r.get("email", "").lower().strip()
            name = r.get("name", "").strip()
            if email:
                all_emails.add(email)
                if email not in email_to_names:
                    email_to_names[email] = set()
                if name:
                    email_to_names[email].add(name)


    methods = {}
    for d in details.values():
        m = d.get("method", "unknown")
        methods[m] = methods.get(m, 0) + 1

    log.info("=" * 60)
    log.info("DOCUSIGN SCRAPER — STATS")
    log.info("=" * 60)
    log.info("  Total scraped envelopes: %d", total)
    log.info("  With recipients: %d", with_recipients)
    log.info("  Total recipient entries: %d", total_recipients)
    log.info("  Unique emails: %d", len(all_emails))
    log.info("  Methods: %s", methods)

    if all_emails:
        log.info("  Top 30 emails:")

        email_freq = {}
        for d in details.values():
            for r in d.get("recipients", []):
                e = r.get("email", "").lower().strip()
                if e:
                    email_freq[e] = email_freq.get(e, 0) + 1

        for email, count in sorted(email_freq.items(), key=lambda x: -x[1])[:30]:
            names = email_to_names.get(email, set())
            name_str = f" ({', '.join(names)})" if names else ""
            log.info("    %3dx  %s%s", count, email, name_str)


    no_recipients = [d for d in details.values() if not d.get("recipients")]
    if no_recipients:
        log.info("  Contracts WITHOUT recipients (%d):", len(no_recipients))
        for d in no_recipients[:10]:
            log.info("    - %s", d.get("name", "unknown")[:80])
        if len(no_recipients) > 10:
            log.info("    ... and %d more", len(no_recipients) - 10)

    log.info("=" * 60)





def merge_emails_into_contacts(details: dict):
    ""





    try:
        import pandas as pd
    except ImportError:
        log.error("pandas required for merge. Install with: pip install pandas pyarrow")
        sys.exit(1)

    contacts_file = PROCESSED_DIR / "contacts-docusign.parquet"
    if not contacts_file.exists():
        log.error(f"contacts-docusign.parquet not found at {contacts_file}")
        log.error("Run docusign-enrich.py first to create it.")
        sys.exit(1)


    df = pd.read_parquet(contacts_file)
    log.info(f"Loaded {len(df)} existing contacts from {contacts_file.name}")
    before_with_email = (df["email"] != "").sum()
    log.info(f"  Currently {before_with_email} have email addresses")


    name_to_email = {}
    email_to_names = {}
    new_contacts = []

    for d in details.values():
        for r in d.get("recipients", []):
            email = r.get("email", "").strip()
            name = r.get("name", "").strip()
            role = r.get("role", "recipient")

            if email:
                email_lower = email.lower()
                if name:

                    name_normalized = name.strip()
                    name_to_email[name_normalized] = email
                    name_to_email[name_normalized.lower()] = email

                    if email_lower not in email_to_names:
                        email_to_names[email_lower] = {"name": name, "role": role}

    log.info(
        f"  Scraped data: {len(name_to_email)} name->email mappings, {len(email_to_names)} unique emails"
    )


    updated = 0
    for idx, row in df.iterrows():
        if row["email"]:
            continue

        contact_name = row["name"].strip()


        email = name_to_email.get(contact_name, "")


        if not email:
            email = name_to_email.get(contact_name.lower(), "")


        if not email:
            import re

            clean_name = re.sub(r"\s+", " ", contact_name).strip().lower()
            for scraped_name, scraped_email in name_to_email.items():
                clean_scraped = re.sub(r"\s+", " ", scraped_name).strip().lower()
                if clean_name == clean_scraped:
                    email = scraped_email
                    break

        if email:
            df.at[idx, "email"] = email
            updated += 1
            log.info(f"    Updated: {contact_name} -> {email}")


    existing_names = set(df["name"].str.lower().str.strip())
    existing_emails = set(df["email"].str.lower().str.strip()) - {""}

    added = 0
    for email_lower, info in email_to_names.items():
        if email_lower in existing_emails:
            continue
        name = info["name"]
        if name.lower().strip() in existing_names:
            continue


        new_row = {
            "name": name,
            "email": email_lower,
            "role": info.get("role", "recipient"),
            "is_company": False,
            "contract_count": 0,
            "first_contract": "",
            "last_contract": "",
            "contract_types": "",
        }
        new_contacts.append(new_row)
        added += 1

    if new_contacts:
        new_df = pd.DataFrame(new_contacts)
        df = pd.concat([df, new_df], ignore_index=True)


    after_with_email = (df["email"] != "").sum()


    backup_file = PROCESSED_DIR / "contacts-docusign.parquet.bak"
    import shutil

    shutil.copy2(contacts_file, backup_file)

    safe_write_parquet(df, contacts_file, index=False)

    log.info("\n  MERGE RESULTS:")
    log.info(f"    Updated existing contacts: {updated}")
    log.info(f"    Added new contacts: {added}")
    log.info(f"    Emails before: {before_with_email}")
    log.info(f"    Emails after: {after_with_email}")
    log.info(f"    Net new emails: {after_with_email - before_with_email}")
    log.info(f"    Total contacts now: {len(df)}")
    log.info(f"    Backup: {backup_file}")
    log.info(f"    Saved: {contacts_file}")





def main():
    parser = argparse.ArgumentParser(
        description="DocuSign Contract Details Scraper — SBK L0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # First: open Chrome and log in to apps.docusign.com

  python3 tools/docusign-scraper.py --dry-run     # test connection
  python3 tools/docusign-scraper.py                # full scrape
  python3 tools/docusign-scraper.py --limit 5      # test with 5 contracts
  python3 tools/docusign-scraper.py --delay 5      # slower (5s between requests)
  python3 tools/docusign-scraper.py --stats        # show stats from scraped data
  python3 tools/docusign-scraper.py --merge        # update contacts-docusign.parquet
        """,
    )
    parser.add_argument("--dry-run", action="store_true", help="Only test connection, don't scrape")
    parser.add_argument("--stats", action="store_true", help="Show stats from already-scraped data")
    parser.add_argument(
        "--merge", action="store_true", help="Merge scraped emails into contacts-docusign.parquet"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit number of envelopes to scrape"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help=f"Delay between requests in seconds (default: {DEFAULT_DELAY})",
    )





    parser.add_argument(
        "--use-owner-browser-tab",
        action="store_true",
        help="required for scraping: acknowledges that this drives the owner's Chrome tab",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    log.info("=" * 60)
    log.info("DOCUSIGN CONTRACT DETAILS SCRAPER")
    log.info("=" * 60)
    log.info("  Output: %s", OUTPUT_DIR)
    log.info("  Details: %s", DETAILS_FILE)


    if args.stats:
        details = load_existing_details()
        show_stats(details)
        return


    if args.merge:
        details = load_existing_details()
        if not details:
            log.error("No scraped data found. Run the scraper first.")
            sys.exit(1)
        merge_emails_into_contacts(details)
        return


    if not args.use_owner_browser_tab:
        log.error("This tool drives the owner's Chrome tab: it reads the list and clicks")
        log.error("through the pagination. If the owner is reading a contract, it changes under them.")
        log.error("Run again with --use-owner-browser-tab when you are sure they are not working.")
        sys.exit(2)


    metadata = load_metadata()


    existing_details = load_existing_details()
    if existing_details:
        log.info(f"Resuming: {len(existing_details)} contracts already scraped")


    log.info("Testing DocuSign connection...")
    conn = test_connection()

    if conn.get("error"):
        log.error(f"Connection failed: {conn}")
        log.error("Make sure Chrome has a DocuSign tab open and you are logged in.")
        sys.exit(1)

    log.info(f"  Connected! URL: {conn.get('url', '')[:100]}")
    log.info(f"  Title: {conn.get('title', '')[:80]}")
    log.info(f"  Account ID: {conn.get('accountId', 'not found')}")
    log.info(f"  Logged in: {conn.get('loggedIn', False)}")

    if args.dry_run:
        log.info("\n  DRY RUN — connection OK, not scraping.")

        log.info("\n  Testing envelope discovery...")
        envelopes = discover_envelope_ids_from_list_page()
        log.info(f"  Found {len(envelopes)} envelopes on current page:")
        for env in envelopes[:5]:
            log.info(f"    {env.get('envelopeId', '')[:12]}... {env.get('name', '')[:60]}")
        if len(envelopes) > 5:
            log.info(f"    ... and {len(envelopes) - 5} more")


        if envelopes:
            log.info("\n  Testing API recipient fetch on first envelope...")
            test_env = envelopes[0]
            api_result = fetch_envelope_recipients_via_api(test_env["envelopeId"])
            if api_result and api_result.get("ok"):
                recipients = api_result.get("recipients", {})
                for key in ["signers", "carbonCopies", "certifiedDeliveries"]:
                    items = recipients.get(key, [])
                    if items:
                        log.info(f"    {key}: {len(items)}")
                        for r in items[:3]:
                            log.info(f"      {r.get('name', '')} <{r.get('email', '')}>")
                log.info("  API approach works!")
            else:
                log.warning(f"  API failed: {api_result}")
                log.info("  Will need to use HTML scraping approach.")
        return


    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


    log.info("\n" + "=" * 60)
    log.info("STARTING SCRAPE")
    log.info("=" * 60)

    details = discover_and_scrape_via_api(
        metadata, existing_details, delay=args.delay, limit=args.limit
    )


    if len(details) == len(existing_details):
        log.info("\nAPI approach didn't discover new envelopes. Trying HTML list navigation...")
        envelopes = discover_all_envelopes(metadata)
        if envelopes:
            details = scrape_all_recipients(
                envelopes, existing_details, delay=args.delay, limit=args.limit
            )
        else:




            log.error("DocuSign: 0 envelopes found - scraper dead, not overwriting %s", DETAILS_FILE)
            sys.exit(2)


    save_details(details)


    show_stats(details)

    log.info("Next step: python3 tools/docusign-scraper.py --merge")
    log.info("(merges emails into contacts-docusign.parquet)")


from pipeline_decorator import pipeline_step


@pipeline_step(name="l0-docusign-scrape", source="docusign", stage="l0")
def run():
    main()


if __name__ == "__main__":
    run()
