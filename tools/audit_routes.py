"""Audit app routes: login as roles and report 4xx/5xx."""
from __future__ import annotations

import re
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.seed import DEMO_PASSWORD  # noqa: E402

SKIP_PREFIXES = (
    "/static/",
    "/eval-criterion-media/",
    "/visual-documents/",
)
SKIP_IF_HAS = ("<",)  # path params — test separately

EXTRA_PATHS = [
    "/admin/evaluation-lists/",
    "/admin/dilemmas/",
    "/planner/create-flow",
    "/admin/information-bank",
    "/analyst/evaluation-criteria",
    "/control/evaluation-results-report",
    "/admin/exercises/objectives",
    "/admin/exercises/create",
    "/admin/battle-organization",
    "/admin/users",
    "/library",
    "/login",
]

ROLES = ("admin", "planner", "control", "judge", "analyst", "chief_judge")


def collect_rules(app):
    rules = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint.startswith("static"):
            continue
        path = rule.rule
        if any(path.startswith(p) for p in SKIP_PREFIXES):
            continue
        if any(ch in path for ch in SKIP_IF_HAS):
            continue
        methods = sorted(rule.methods - {"HEAD", "OPTIONS"})
        rules.append((path, methods, rule.endpoint))
    return rules


def login(client, username: str) -> bool:
    r = client.post(
        "/login",
        data={"username": username, "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    return r.status_code in (302, 303)


def main() -> int:
    app = create_app()
    client = app.test_client()
    rules = collect_rules(app)
    paths = {p for p, _, _ in rules}
    for p in EXTRA_PATHS:
        if p not in paths:
            rules.append((p, ["GET"], "extra"))

    failures: list[str] = []
    errors_500: list[str] = []

    for role in ROLES:
        client = app.test_client()
        if not login(client, role):
            failures.append(f"LOGIN FAIL {role}")
            continue
        role_fails: list[str] = []
        for path, methods, ep in sorted(rules, key=lambda x: x[0]):
            for method in methods:
                if method not in ("GET", "POST"):
                    continue
                try:
                    if method == "GET":
                        r = client.get(path, follow_redirects=True)
                    else:
                        r = client.post(path, data={}, follow_redirects=True)
                except Exception as e:
                    errors_500.append(f"{role} {method} {path} EXC: {e}")
                    continue
                if r.status_code >= 500:
                    errors_500.append(f"{role} {method} {path} -> {r.status_code}")
                elif r.status_code == 405:
                    role_fails.append(f"405 {method} {path} ({ep})")
        if role_fails:
            failures.extend([f"[{role}] {x}" for x in role_fails[:15]])
            if len(role_fails) > 15:
                failures.append(f"[{role}] ... +{len(role_fails) - 15} more 405s")

    print("=== 500 / exceptions ===")
    for x in errors_500[:40]:
        print(x)
    if len(errors_500) > 40:
        print(f"... +{len(errors_500) - 40} more")
    print("=== 405 (sample) ===")
    for x in failures[:50]:
        print(x)
    print(
        f"Summary: 500={len(errors_500)} 405_samples={len(failures)} rules={len(rules)}"
    )
    return 1 if errors_500 else 0


if __name__ == "__main__":
    raise SystemExit(main())
