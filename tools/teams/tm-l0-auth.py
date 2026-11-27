#!/usr/bin/env python3
"""Microsoft Teams sign-in, once per account label.

Uses the app registration of the microsoft365 plugin (public client, no secret) and stores
the sign-in in the same place (Keychain sbk-microsoft365/<label>), so one sign-in serves
both plugins. It asks for the per-user scope Chat.Read (your own account, no admin consent) on top of
offline_access and User.Read. When the label already holds a microsoft365 sign-in (one with
Mail.Read, Calendars.Read or Contacts.Read), it also asks again for that plugin's scopes, so
the stored sign-in keeps working for Outlook; a Teams-only sign-in stays Teams-only. It
refuses to replace a label's sign-in with another person's account.

    uv run python tools/teams/tm-l0-auth.py --account work
    uv run python tools/teams/tm-l0-auth.py --account work --device-code
    uv run python tools/teams/tm-l0-auth.py --account work --check
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tm_graph as tg  # noqa: E402

mg = tg.mg


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Microsoft Teams sign-in (your own app registration, per-user Chat.Read for "
        "your own work or school account). Shares the microsoft365 plugin's stored sign-in."
    )
    p.add_argument(
        "--account",
        default=None,
        help="label of the account (default: teams.account, else microsoft365.default_account, "
        "else outlook); the same label the microsoft365 plugin uses for that mailbox",
    )
    p.add_argument(
        "--tenant",
        default=None,
        help="organizations, your tenant id, or common (default: microsoft365.tenant or common). "
        "Personal accounts (consumers) cannot read Teams chats through Graph",
    )
    p.add_argument(
        "--device-code", action="store_true", help="device code flow instead of the browser"
    )
    p.add_argument(
        "--check", action="store_true", help="only test the stored sign-in, no new login"
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--with-outlook",
        action="store_true",
        help="also ask for the microsoft365 plugin's scopes (Mail, Calendars, Contacts read)",
    )
    g.add_argument(
        "--teams-only",
        action="store_true",
        help="ask only for offline_access, User.Read and Chat.Read, even if a microsoft365 "
        "sign-in exists for this label (that plugin will then need ms-l0-auth.py again)",
    )
    return p.parse_args(argv)


def probe_chats(graph, label: str, who: str) -> None:
    """One request to the chats endpoint: does Graph serve chats to this sign-in?"""
    try:
        graph.get("/me/chats", params={"$top": "1"})
    except tg.GraphError as e:
        raise tg.SetupError(
            f"teams: '{label}' signed in as {who}, but Graph refused the chats (HTTP {e.status} "
            f"{e.code}): personal Microsoft accounts are not supported, and an organization can "
            f"block this access ({tg.SETUP_HINT})"
        ) from None


def serves_outlook(record: dict | None) -> bool:
    """Does the label's stored sign-in carry the microsoft365 plugin's own scopes?

    True when its scopes include Mail.Read, Calendars.Read or Contacts.Read, or when the
    record says nothing about its scopes (a seed from SBK_MS365_TOKEN_<LABEL>), so that
    signing in again for Teams never drops what Outlook needs. A Teams-only sign-in stays
    Teams-only: it is never widened to mail, calendars and contacts behind your back.
    """
    if record is None:
        return False
    names = tg.scope_names(str(record.get("requested_scopes") or record.get("scopes") or ""))
    outlook_only = {s.lower() for s in tg.outlook_scopes()} - {s.lower() for s in tg.TEAMS_SCOPES}
    return not names or bool(names & outlook_only)


def main(argv=None, http=None, open_browser=None, sleep=None) -> int:
    args = parse_args(argv)
    label = tg.check_label(args.account or tg.default_label())
    http = http or mg.Http()
    sleep = sleep or time.sleep
    if args.check:
        tp = tg.TeamsTokenProvider(label, http)
        graph = tg.PacedGraph(tp, http, sleep=sleep)
        me = tg.whoami(graph)
        who = me["mail"] or me["userPrincipalName"] or me["displayName"]
        probe_chats(graph, label, who)
        print(f"teams/{label}: signed in as {who}; chats readable")
        return 0
    cid = mg.client_id()
    if not cid:
        raise tg.SetupError(
            f"teams: no app client id; set {mg.ENV_CLIENT_ID} or microsoft365.client_id in "
            f"sbk.config.json ({tg.SETUP_HINT})"
        )
    tenant = args.tenant or mg.default_tenant()
    if tenant.lower() == "consumers":
        raise tg.SetupError(
            "teams: tenant consumers is for personal Microsoft accounts, and Microsoft Graph does "
            "not serve Teams chats to them; use organizations or your tenant id"
        )
    existing = mg.load_token_record(label)
    with_outlook = args.with_outlook or (serves_outlook(existing) and not args.teams_only)
    scopes = tg.sign_in_scopes(with_outlook)
    with tg.graph_scopes(scopes):
        if args.device_code:
            tok = mg.device_code_login(cid, tenant, http)
        else:
            tok = mg.browser_login(cid, tenant, http, open_browser=open_browser)
    if not tok.get("refresh_token"):
        raise mg.TokenError("no refresh token returned: offline_access was not granted")
    granted = tok.get("scope", "")
    have = tg.scope_names(granted)
    if have and tg.CHAT_SCOPE.lower() not in have:
        raise mg.TokenError(f"{tg.CHAT_SCOPE} was not granted, nothing stored")
    missing = [s for s in scopes if s != "offline_access" and have and s.lower() not in have]
    record = {
        "refresh_token": tok["refresh_token"],
        "client_id": cid,
        "tenant": tenant,
        "scopes": granted,
        "requested_scopes": " ".join(scopes),
    }
    tp = tg.TeamsTokenProvider(label, http, record=record)
    tp._access, tp._expires = tok["access_token"], time.time() + int(tok.get("expires_in", 3600))
    graph = tg.PacedGraph(tp, http, sleep=sleep)
    me = tg.whoami(graph)
    who = me["mail"] or me["userPrincipalName"] or me["displayName"]
    # The label's stored sign-in is shared with microsoft365: replacing it with another
    # person's account would pour a different mailbox into the same label's files.
    before = str((existing or {}).get("username") or "").strip().lower()
    now_ids = {str(me["mail"]).lower(), str(me["userPrincipalName"]).lower()} - {""}
    if before and now_ids and before not in now_ids:
        raise tg.SetupError(
            f"teams: label '{label}' holds the sign-in of {before}, but you signed in as {who}; "
            "nothing stored (sign in with that account, or use another --account label)"
        )
    probe_chats(graph, label, who)
    record["username"] = me["mail"] or me["userPrincipalName"]
    where = mg.save_token_record(label, record)
    print(f"teams/{label}: signed in as {who}; chats readable; sign-in stored in {where}")
    if missing:
        print(
            f"Warning: not granted: {', '.join(missing)}; the parts that need them will be skipped",
            file=sys.stderr,
        )
    if serves_outlook(existing) and args.teams_only:
        print(
            f"Note: this sign-in has only the Teams scopes; if the microsoft365 plugin then "
            f"refuses '{label}', run tm-l0-auth.py --with-outlook (one sign-in for both)",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (tg.SetupError, tg.TokenError, mg.SetupError, mg.TokenError, mg.GraphError) as e:
        print(tg.one_line(e), file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("teams: sign-in interrupted, nothing stored", file=sys.stderr)
        sys.exit(130)
