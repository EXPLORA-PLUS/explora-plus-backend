from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class JsonHttpClient:
    user_agent = "explora-plus-tour-routes/1.0 (+https://github.com/EXPLORA-PLUS)"

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ):
        if params:
            query = urlencode(params)
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{query}"
        return self._open_json(url=url, data=None, headers=headers, timeout=timeout)

    def post_text_json(
        self,
        url: str,
        *,
        body: str,
        headers: dict[str, str] | None = None,
        timeout: float = 20.0,
    ):
        payload = body.encode("utf-8")
        request_headers = {"Content-Type": "text/plain; charset=utf-8"}
        if headers:
            request_headers.update(headers)
        return self._open_json(
            url=url,
            data=payload,
            headers=request_headers,
            timeout=timeout,
        )

    def _open_json(self, *, url: str, data, headers, timeout: float):
        request_headers = {"User-Agent": self.user_agent}
        if headers:
            request_headers.update(headers)

        request = Request(url=url, data=data, headers=request_headers)
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
