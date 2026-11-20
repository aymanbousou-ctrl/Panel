"""Speichert eine oeffentliche Suchseite, damit ein Parser dafuer gebaut werden kann.

Aufruf:  py tools\\capture.py "https://www.willhaben.at/..." [Ausgabedatei]

Das Tool ruft genau eine Seite ab, mit demselben Netzcode wie FlipRadar, und
meldet vorher, ob robots.txt den Pfad erlaubt. Es umgeht keinen Schutz: bei
403/429 oder einer Bot-Pruefung wird nur das Ergebnis gemeldet.
Die Datei enthaelt keine Zugangsdaten und kann geteilt werden.
"""

import re
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

sys.path[:0] = [str(Path(__file__).resolve().parents[1]),
                str(Path(__file__).resolve().parents[1] / "vendor")]
from flipradar.net import read  # noqa: E402

MARKERS = {
    "__NEXT_DATA__": r'id="__NEXT_DATA__"',
    "JSON-LD": r"application/ld\+json",
    "__CONFIG__": r"__CONFIG__",
    "Bot-Pruefung": r"captcha|datadome|are you a robot|access denied|cloudflare",
}


def robots_allows(url):
    parts = urlsplit(url)
    parser = RobotFileParser()
    try:
        body, _ = read(f"{parts.scheme}://{parts.netloc}/robots.txt", timeout=15)
    except (OSError, ValueError) as exc:
        return None, f"robots.txt nicht lesbar ({type(exc).__name__})"
    parser.parse(body.decode("utf-8", "replace").splitlines())
    return parser.can_fetch("*", url), "robots.txt gelesen"


def main(argv):
    if not argv or urlsplit(argv[0]).scheme != "https":
        print(__doc__)
        return 2
    url = argv[0]
    out = Path(argv[1] if len(argv) > 1 else f"capture_{urlsplit(url).hostname}.html")
    allowed, note = robots_allows(url)
    print(f"{note}: {'erlaubt' if allowed else 'VERBOTEN' if allowed is False else 'unklar'}")
    if allowed is False:
        print("Abbruch: robots.txt untersagt diesen Pfad.")
        return 1
    try:
        body, final = read(url)
    except HTTPError as exc:
        print(f"HTTP {exc.code} fuer {url}")
        exc.close()
        return 1
    except (OSError, ValueError) as exc:
        print(f"Abruf fehlgeschlagen: {type(exc).__name__} {exc}")
        return 1
    out.write_bytes(body)
    text = body.decode("utf-8", "replace")
    print(f"OK: {len(body)} Bytes von {final}\nGespeichert: {out.resolve()}")
    for name, pattern in MARKERS.items():
        print(f"  {name}: {'ja' if re.search(pattern, text, re.I) else 'nein'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
