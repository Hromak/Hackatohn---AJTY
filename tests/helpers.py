"""Shared helpers for event tests."""
import uuid

from tests.conftest import auth


class Api:
    """A team's view of one match."""

    def __init__(self, client, team, kind="training"):
        self.client = client
        self.headers = auth(team["token"])
        self.match = team[kind]
        self.base = f"/api/v1/matches/{self.match}"
        roster = client.get(f"{self.base}/roster", headers=self.headers).json()
        self.home = {p["jersey"]: p["id"] for p in roster["home"]}
        self.away = {p["jersey"]: p["id"] for p in roster["away"]}

    def put(self, client_id, body):
        return self.client.put(f"{self.base}/events/{client_id}", json=body, headers=self.headers)

    def get(self, client_id):
        return self.client.get(f"{self.base}/events/{client_id}", headers=self.headers)

    def delete(self, client_id):
        return self.client.delete(f"{self.base}/events/{client_id}", headers=self.headers)

    def events(self, include_deleted=False):
        suffix = "?include_deleted=1" if include_deleted else ""
        return self.client.get(f"{self.base}/events{suffix}", headers=self.headers).json()

    def reset(self):
        return self.client.post(f"{self.base}/reset", headers=self.headers)

    def shot(self, **over):
        body = {"type": "shot", "team": "home", "period": 1, "time": "07:42", "x": 600, "y": 250,
                "result": "on_goal", "shooter_id": self.home[10]}
        body.update(over)
        return body

    def sub(self, jerseys=(10, 11, 12, 13, 14), team="home", **over):
        ids = self.home if team == "home" else self.away
        body = {"type": "substitution", "team": team, "period": 1, "time": "00:00",
                "players": [ids[j] for j in jerseys]}
        body.update(over)
        return body


def cid() -> str:
    return str(uuid.uuid4())
