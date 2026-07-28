"""End-to-end smoke test for the API, thread manager and JSON storage.

Runs against a live uvicorn instance pointed at a throwaway data file:

    DATA_FILE=/tmp/vintagent_test.json ADMIN_PASSWORD=test123 \\
        uvicorn app.main:app --port 8124 &
    python scripts/smoke_test.py http://127.0.0.1:8124
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8124"
DATA_FILE = os.getenv("DATA_FILE", "/tmp/vintagent_test.json")
USERNAME = os.getenv("ADMIN_USERNAME", "admin")
PASSWORD = os.getenv("ADMIN_PASSWORD", "test123")

failures: list[str] = []


def call(method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, (json.loads(raw) if raw else None)


def check(label: str, condition: bool, detail: object = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f"  -> {detail}" if not condition else ""))
    if not condition:
        failures.append(label)


status, _ = call("GET", "/api/urls")
check("unauthenticated list is rejected", status == 401, status)

status, body = call("POST", "/api/auth/login", {"username": USERNAME, "password": "wrong"})
check("bad password is rejected", status == 401, status)

status, body = call("POST", "/api/auth/login", {"username": USERNAME, "password": PASSWORD})
check("login succeeds", status == 200, body)
token = body["access_token"] if status == 200 else ""

status, body = call("GET", "/api/auth/me", token=token)
check("token identifies the admin", status == 200 and body.get("username") == USERNAME, body)

status, body = call("POST", "/api/urls", {"name": "x", "url": "https://example.com/foo"}, token)
check("non-Vinted URL is rejected", status == 422, status)

created: list[str] = []
for i in range(11):
    status, body = call(
        "POST",
        "/api/urls",
        {"name": f"Test {i}", "url": f"https://www.vinted.pl/catalog?search_text=test{i}"},
        token,
    )
    if status == 201:
        created.append(body["id"])
check("created 11 URLs", len(created) == 11, len(created))

started = 0
rejected = 0
for url_id in created:
    status, body = call("POST", f"/api/urls/{url_id}/start", token=token)
    if status == 200:
        started += 1
    elif status == 409:
        rejected += 1
check("only 10 threads may start", started == 10 and rejected == 1, f"started={started} rejected={rejected}")

status, body = call("GET", "/api/stats", token=token)
check("stats report 10 active threads", status == 200 and body["active_threads"] == 10, body)

# Threads have no network here, so each poll must fail, record the error and survive.
time.sleep(6)
status, body = call("GET", "/api/urls", token=token)
running = [u for u in body if u["status"] == "running"]
alive = [u for u in running if u["thread_alive"]]
checked = [u for u in running if u["last_checked_at"]]
check("10 URLs marked running", len(running) == 10, len(running))
check("all running threads survived failing polls", len(alive) == 10, len(alive))
check("failed polls were recorded", len(checked) == 10, [u["last_error"] for u in running][:2])

with open(DATA_FILE, encoding="utf-8") as fh:
    persisted = json.load(fh)
check("data.json holds 11 records", len(persisted["urls"]) == 11, len(persisted["urls"]))
check(
    "data.json keeps status + error per record",
    sum(1 for r in persisted["urls"] if r["status"] == "running") == 10
    and all("seen_ids" in r for r in persisted["urls"]),
    persisted["urls"][0],
)

status, _ = call("POST", f"/api/urls/{created[0]}/stop", token=token)
check("stop succeeds", status == 200, status)
status, body = call("POST", f"/api/urls/{created[10]}/start", token=token)
check("a freed slot lets the 11th URL start", status == 200, (status, body))

status, body = call("PATCH", f"/api/urls/{created[1]}", {"name": "Renamed"}, token)
check("rename works", status == 200 and body["name"] == "Renamed", body)

status, body = call("GET", f"/api/urls/{created[1]}", token=token)
check("detail view returns the record with stats", status == 200 and "stats" in body, body)
check("polls are counted", status == 200 and body["stats"]["checks"] > 0, body.get("stats") if body else None)

status, body = call("GET", f"/api/urls/{created[1]}/stats?hours=6&tz_offset_minutes=120", token=token)
check(
    "stats endpoint returns chart-ready series",
    status == 200
    and len(body["found_timeline"]) == 6
    and len(body["listed_by_hour_of_day"]) == 24
    and len(body["found_by_hour_of_day"]) == 24,
    body,
)

status, _ = call("POST", f"/api/urls/{created[1]}/stats/reset", token=token)
status_after, body = call("GET", f"/api/urls/{created[1]}", token=token)
check("stats reset clears the counters", status_after == 200 and body["stats"]["checks"] == 0, body.get("stats"))

status, body = call("GET", "/api/session", token=token)
check("session status is exposed", status == 200 and "has_session" in body, body)

status, _ = call("DELETE", f"/api/urls/{created[2]}", token=token)
check("delete returns 204", status == 204, status)
status, body = call("GET", "/api/urls", token=token)
check("deleted URL is gone", status == 200 and len(body) == 10, len(body) if status == 200 else body)

status, body = call("GET", "/api/stats", token=token)
check("thread count follows start/stop/delete", status == 200 and body["active_threads"] == 9, body)

print()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
