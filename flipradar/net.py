"""Network calls with bounded reads, timeouts and same-host redirects."""

import json
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener


class SameHost(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if (
            urlsplit(newurl).scheme != "https"
            or urlsplit(newurl).netloc != urlsplit(req.full_url).netloc
        ):
            raise ValueError("Unerwartete Weiterleitung auf eine andere Domain")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read(url, *, data=None, headers=None, timeout=18):
    request = Request(
        url, data=data, headers={"User-Agent": "FlipRadar/2.1", **(headers or {})}
    )
    with build_opener(SameHost()).open(request, timeout=timeout) as response:
        body = response.read(8_000_001)
        if len(body) > 8_000_000:
            raise ValueError("Antwort groesser als 8 MB")
        return body, response.url


def read_json(url, **kwargs):
    return json.loads(read(url, **kwargs)[0])
