"""Kostenpflichtige Quellen ueber die Schnittstelle von Apify (Dienst von Dritten).

Jeder Aufruf startet einen Lauf, der Guthaben verbraucht. Der Token steht nur im
Header und nie in der URL.
"""

import json
import re
from urllib.parse import urlencode

from .net import read_json


def run_actor(actor, payload, token, timeout=330):
    """Startet einen Actor und wartet auf seine Ergebnisse (hoechstens ca. 5 Minuten)."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", actor):
        raise ValueError("Actor-Name ungueltig")
    rows = read_json(
        "https://api.apify.com/v2/acts/"
        + actor.replace("/", "~")
        + "/run-sync-get-dataset-items?"
        + urlencode({"format": "json", "clean": "true"}),
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
        timeout=timeout,
    )
    if not isinstance(rows, list):
        raise ValueError("Apify-Antwort ist keine Ergebnisliste")
    return rows
