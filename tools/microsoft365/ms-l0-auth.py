#!/usr/bin/env python3
"""Microsoft 365 sign-in, once per mailbox label.

Signs you in with your own app registration (public client, no secret) and stores the
refresh token in the Keychain (sbk-microsoft365/<label>). Default flow: authorization
code + PKCE in your browser (redirect http://localhost). --device-code prints a code to
type at the Microsoft page instead (some organisations block that flow).

    uv run python tools/microsoft365/ms-l0-auth.py --account outlook
    uv run python tools/microsoft365/ms-l0-auth.py --account work --tenant organizations --device-code
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ms_graph as mg  # noqa: E402


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Microsoft 365 sign-in (personal app, per-user read-only scopes for your "
        "own account)"
    )
    p.add_argument(
        "--account",
        default="outlook",
        help="label of this mailbox (folder name in emails/ and calendars/)",
    )
    p.add_argument(
        "--tenant",
        default=None,
        help="common (default: personal + work), consumers (personal only), organizations, or your tenant id",
    )
    p.add_argument(
        "--device-code", action="store_true", help="device code flow instead of the browser"
    )
    p.add_argument(
        "--check", action="store_true", help="only test the stored sign-in, no new login"
    )
    return p.parse_args(argv)


# The only scopes another plugin of the kit adds to this label's sign-in, and so the only ones
# asked again here: per-user scopes of your own account, none needs admin consent. Teams
# (tools/teams/tm_graph.py TEAMS_SCOPES) adds Chat.Read. Lower case, compared without case.
KEPT_SCOPES_ALLOWED = frozenset({"chat.read"})


def _recorded_extra(existing: dict | None, tenant: str) -> list[str]:
    """Scopes of the stored sign-in's requested_scopes that this plugin does not ask for itself."""
    if not existing or str(tenant).lower() == "consumers":
        return []
    own = {s.lower() for s in mg.SCOPES}
    out: list[str] = []
    for s in str(existing.get("requested_scopes") or "").split():
        if s.lower() not in own and s not in out:
            out.append(s)
    return out


def kept_scopes(existing: dict | None, tenant: str) -> tuple[str, ...]:
    """Scopes of the stored sign-in that another plugin of the kit added, asked again here.

    Only scopes in KEPT_SCOPES_ALLOWED are kept, so a stored sign-in can never make this
    plugin ask for anything else (an admin scope, say). Empty when there is no stored
    sign-in, when it records no requested_scopes, or when the new sign-in is for personal
    accounts only (tenant consumers), where the Teams scope cannot be granted.
    """
    return tuple(s for s in _recorded_extra(existing, tenant) if s.lower() in KEPT_SCOPES_ALLOWED)


def dropped_scopes(existing: dict | None, tenant: str) -> tuple[str, ...]:
    """Scopes recorded in the stored sign-in that are not asked again (not in the allowlist)."""
    return tuple(
        s for s in _recorded_extra(existing, tenant) if s.lower() not in KEPT_SCOPES_ALLOWED
    )


def main(argv=None, http=None) -> int:
    args = parse_args(argv)
    label = mg.check_label(args.account)
    http = http or mg.Http()
    if args.check:
        tp = mg.TokenProvider(label, http)
        me = mg.whoami(mg.Graph(tp, http))
        print(f"microsoft365/{label}: signed in as {me['email'] or me['display_name']}")
        return 0
    cid = mg.client_id()
    if not cid:
        raise mg.SetupError(
            f"microsoft365: no app client id; set {mg.ENV_CLIENT_ID} or microsoft365.client_id "
            f"in sbk.config.json ({mg.SETUP_HINT})"
        )
    tenant = args.tenant or mg.default_tenant()
    # Scopes another plugin added to this label's sign-in (Teams adds Chat.Read with
    # tools/teams/tm-l0-auth.py) are asked again, so signing in here does not drop them.
    stored = mg.load_token_record(label)
    extra = kept_scopes(stored, tenant)
    dropped = dropped_scopes(stored, tenant)
    if dropped:
        print(
            f"microsoft365/{label}: not asked again: {', '.join(dropped)} (only the per-user "
            "scopes of the kit's own plugins are kept)",
            file=sys.stderr,
        )
    scopes = (*mg.SCOPES, *extra)
    kw = {"scopes": scopes} if extra else {}
    if args.device_code:
        tok = mg.device_code_login(cid, tenant, http, **kw)
    else:
        tok = mg.browser_login(cid, tenant, http, **kw)
    if not tok.get("refresh_token"):
        raise mg.TokenError("no refresh token returned: offline_access was not granted")
    missing = mg.missing_scopes(tok.get("scope", ""))
    record = {
        "refresh_token": tok["refresh_token"],
        "client_id": cid,
        "tenant": tenant,
        "scopes": tok.get("scope", ""),
        "requested_scopes": " ".join(scopes),
    }
    tp = mg.TokenProvider(label, http, record=record)
    tp._access, tp._expires = tok["access_token"], time.time() + int(tok.get("expires_in", 3600))
    me = mg.whoami(mg.Graph(tp, http))
    record["username"] = me["email"]
    where = mg.save_token_record(label, record)
    print(
        f"microsoft365/{label}: signed in as {me['email'] or me['display_name']}; "
        f"sign-in stored in {where}"
    )
    if missing:
        print(
            f"Warning: not granted: {', '.join(missing)}; the parts that need them will be skipped",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (mg.SetupError, mg.TokenError, mg.GraphError) as e:
        print(mg.one_line(e), file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("microsoft365: sign-in interrupted, nothing stored", file=sys.stderr)
        sys.exit(130)
