"""Quick smoke test for hub routes (empty unit/phase catalogs)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402

ROUTES_GET = [
    "/login",
    "/planner",
    "/planner/create-flow",
    "/admin/evaluation-lists/",
    "/admin/dilemmas/",
    "/admin/information-bank",
    "/judge/evaluation-lists",
    "/judge/dilemmas",
    "/chief-judge/evaluation-lists",
    "/analyst/evaluation-criteria",
    "/control/",
]

ROUTES_POST = [
    ("/admin/evaluation-lists/", {}),
    ("/admin/dilemmas/", {}),
]


def main() -> int:
    app = create_app()
    client = app.test_client()
    failures: list[str] = []

    with client.session_transaction() as sess:
        sess["user_id"] = None

    for path in ROUTES_GET:
        r = client.get(path, follow_redirects=False)
        code = r.status_code
        if code in (302, 303) and path != "/login":
            loc = r.headers.get("Location", "")
            if "/login" in loc:
                continue
        if code >= 500:
            failures.append(f"GET {path} -> {code}")
        elif code == 405:
            failures.append(f"GET {path} -> 405")

    for path, data in ROUTES_POST:
        r = client.post(path, data=data, follow_redirects=False)
        if r.status_code == 405:
            failures.append(f"POST {path} -> 405")
        elif r.status_code >= 500:
            failures.append(f"POST {path} -> {r.status_code}")

    if failures:
        for f in failures:
            print("FAIL", f)
        return 1
    print("OK", len(ROUTES_GET), "GET +", len(ROUTES_POST), "POST (unauthenticated redirects allowed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
