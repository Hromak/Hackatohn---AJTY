#!/usr/bin/env python3
"""Projde službu od začátku do konce tak, jak ji použije aplikace zapisovatele.

  python3 scripts/smoke.py --base-url http://localhost:8000 --token demo
  python3 scripts/smoke.py --base-url http://localhost:8000 --token demo --origin https://moje.app

Používá první utkání týmu a na začátku ho vyprázdní. Stačí čistý Python 3, bez knihoven.
Skončí nenulovým kódem na první neshodě.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

STEP = 0


class Client:
    def __init__(self, base: str, token: str, origin: str | None):
        self.base, self.token, self.origin = base.rstrip("/"), token, origin

    def call(self, method: str, path: str, body=None, token: str | None = None):
        headers = {"Authorization": f"Bearer {token or self.token}"}
        if self.origin:
            headers["Origin"] = self.origin
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        for _ in range(20):
            request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=15) as response:
                    raw, status, got = response.read(), response.status, response.headers
            except urllib.error.HTTPError as error:
                raw, status, got = error.read(), error.code, error.headers
            if status != 429:
                break
            # Limit požadavků: počkat, kolik služba řekla, a zkusit to znovu – jako slušný klient.
            time.sleep(float(got.get("Retry-After", "1")))
        if self.origin and got.get("Access-Control-Allow-Origin") != "*":
            fail(f"{method} {path}: chybí hlavička Access-Control-Allow-Origin (stav {status})")
        try:
            return status, (json.loads(raw) if raw else None)
        except ValueError:
            fail(f"{method} {path}: odpověď není JSON (stav {status}). Je na adrese {self.base} tahle služba?")


def fail(message: str):
    print(f"CHYBA  {message}")
    sys.exit(1)


def check(label: str, condition: bool, detail=""):
    global STEP
    STEP += 1
    if not condition:
        fail(f"{STEP:02d} {label} {detail}")
    print(f"ok  {STEP:02d} {label}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--token", default="demo")
    ap.add_argument("--origin", help="pošle hlavičku Origin a ověří CORS u každé odpovědi")
    a = ap.parse_args()
    c = Client(a.base_url, a.token, a.origin)

    status, health = c.call("GET", "/api/health")
    check("služba žije", status == 200 and health == {"status": "ok"}, f"{status} {health}")
    status, me = c.call("GET", "/api/v1/me")
    check("token platí", status == 200, f"{status} {me}")
    match = me["matches"][0]["id"]
    base = f"/api/v1/matches/{match}"
    status, _ = c.call("POST", f"{base}/reset")
    check("utkání vyprázdněno", status == 200)
    status, header = c.call("GET", base)
    check("hlavička utkání má hrací části", status == 200 and len(header["periods"]) >= 3)
    _, roster = c.call("GET", f"{base}/roster")
    _, forms = c.call("GET", f"{base}/formations")
    check("soupisky a formace", len(roster["home"]) >= 10 and len(forms["home"]) >= 2)

    def line(side, number):
        f = forms[side][number - 1]
        return [f[k] for k in ("lw", "c", "rw", "ld", "rd") if f[k] is not None]

    keeper = {s: next(p["id"] for p in roster[s] if p["position"] == "G") for s in ("home", "away")}
    queue: list[tuple[str, dict]] = []

    def event(body):
        cid = str(uuid.uuid4())
        queue.append((cid, body))
        return cid

    def sub(team, time, players, **extra):
        return event({"type": "substitution", "team": team, "period": 1, "time": time,
                      "players": players, **extra})

    def shot(team, time, x, y, result, shooter, **extra):
        return event({"type": "shot", "team": team, "period": 1, "time": time, "x": x, "y": y,
                      "result": result, "shooter_id": shooter, **extra})

    # 6 střídání (jedno v přesilovce), 4 střely (mimo, na branku, tyčka, gól s asistencí)
    sub("home", "00:00", line("home", 1))
    sub("away", "00:00", line("away", 1))
    wrong = shot("home", "00:41", 640, 250, "on_goal", line("home", 1)[0], goalkeeper_id=keeper["away"])
    sub("home", "01:05", line("home", 2))
    shot("away", "01:30", 210, 180, "miss", line("away", 1)[1])
    sub("away", "01:32", line("away", 2))
    shot("home", "02:10", 700, 300, "post", line("home", 2)[0])
    sub("home", "02:40", line("home", 1), strength="power_play")
    last_sub = sub("away", "02:40", line("away", 1)[:4], strength="short_handed")
    goal = shot("home", "03:05", 760, 240, "goal", line("home", 1)[0], strength="power_play",
                goalkeeper_id=keeper["away"], assist_id=line("home", 1)[1],
                on_ice={"home": [keeper["home"], *line("home", 1)],
                        "away": [keeper["away"], *line("away", 1)[:4]]})

    statuses = [c.call("PUT", f"{base}/events/{cid}", body)[0] for cid, body in queue]
    check("10 událostí zapsáno (6 střídání, 4 střely)", statuses == [201] * 10, str(statuses))

    # oprava: první střela nebyla domácích, ale hostů
    fixed = dict(queue[2][1], team="away", shooter_id=line("away", 1)[0], goalkeeper_id=keeper["home"], x=250)
    status, body = c.call("PUT", f"{base}/events/{wrong}", fixed)
    check("oprava upravila původní událost", status == 200 and body["event"]["version"] == 2
          and body["event"]["team"] == "away", f"{status} {body}")
    queue[2] = (wrong, fixed)

    # fronta po výpadku: všechno ještě jednou
    replies = [c.call("PUT", f"{base}/events/{cid}", body) for cid, body in queue]
    check("opakované doručení fronty nic nezměnilo",
          all(s == 200 and b["unchanged"] for s, b in replies), str([s for s, _ in replies]))
    _, listing = c.call("GET", f"{base}/events")
    check("v utkání je právě 10 událostí", len(listing["events"]) == 10, str(len(listing["events"])))
    stored_goal = next(e for e in listing["events"] if e["client_id"] == goal)
    check("gól má asistenci a hráče na hřišti", stored_goal["assist_id"] is not None
          and len(stored_goal["on_ice"]["home"]) == 6)
    stored_sub = next(e for e in listing["events"] if e["client_id"] == last_sub)
    check("střídání vrací, kdo přišel a kdo odešel", "in" in stored_sub and len(stored_sub["out"]) >= 1)

    status, body = c.call("PUT", f"{base}/events/{str(uuid.uuid4())}",
                          {"type": "substitution", "team": "home", "period": 1, "time": "02:40",
                           "players": line("home", 2)})
    check("dvě střídání týmu ve stejném čase → 409 duplicate_time",
          status == 409 and body["error"]["code"] == "duplicate_time", f"{status} {body}")
    status, body = c.call("PUT", f"{base}/events/{str(uuid.uuid4())}", dict(queue[4][1], shooter_id=999999))
    check("neznámý hráč → 422 unknown_player s polem fields",
          status == 422 and body["error"]["fields"] == {"shooter_id": "unknown_player"}, f"{status} {body}")
    status, body = c.call("PUT", f"{base}/events/{wrong}", dict(fixed, x=260, version=1))
    check("zastaralá verze → 409 version_conflict s aktuálním stavem",
          status == 409 and body["event"]["version"] == 2, f"{status} {body}")

    status, _ = c.call("DELETE", f"{base}/events/{queue[4][0]}")
    again, _ = c.call("DELETE", f"{base}/events/{queue[4][0]}")
    check("smazání je opakovatelné", (status, again) == (204, 204), f"{status} {again}")
    status, body = c.call("PUT", f"{base}/events/{queue[4][0]}", queue[4][1])
    check("smazaná událost se neoživí → 410 deleted", status == 410 and body["error"]["code"] == "deleted")

    status, body = c.call("GET", "/api/v1/me", token="tohle-neni-token")
    check("cizí token → 401", status == 401 and body["error"]["code"] == "unauthorized")

    status, _ = c.call("PUT", "/api/v1/me/error-mode", {"mode": "reject"})
    s2, body = c.call("PUT", f"{base}/events/{str(uuid.uuid4())}", queue[6][1] | {"time": "04:00"})
    check("vynucená chyba: zápis → 422 forced_rejection",
          status == 200 and s2 == 422 and body["error"]["code"] == "forced_rejection", f"{s2} {body}")
    s3, _ = c.call("GET", f"{base}/events")
    check("vynucená chyba: čtení funguje dál", s3 == 200)
    c.call("PUT", "/api/v1/me/error-mode", {"mode": "unavailable"})
    s4, body = c.call("GET", f"{base}/events")
    check("vynucená chyba: nedostupná služba → 503 forced_unavailable",
          s4 == 503 and body["error"]["code"] == "forced_unavailable", f"{s4} {body}")
    c.call("PUT", "/api/v1/me/error-mode", {"mode": "off"})
    s5, _ = c.call("PUT", f"{base}/events/{str(uuid.uuid4())}", queue[6][1] | {"time": "04:00"})
    check("po vypnutí režimu zápis projde", s5 == 201, str(s5))

    print(f"\nHotovo, {STEP} kroků v pořádku.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
