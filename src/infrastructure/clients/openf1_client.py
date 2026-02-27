import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config import settings

_REQUEST_INTERVAL = 0.35  # 3 req/s safe margin


def _build_session() -> requests.Session:
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class OpenF1Client:
    def __init__(self) -> None:
        self._session = _build_session()
        self._base_url = settings.OPENF1_BASE_URL

    def _get(self, endpoint: str, params: dict) -> list[dict]:
        url = f"{self._base_url}/{endpoint}"
        response = self._session.get(url, params=params, timeout=30)
        response.raise_for_status()
        time.sleep(_REQUEST_INTERVAL)
        return response.json()

    def get_sessions(self, year: int) -> list[dict]:
        return self._get("sessions", {"year": year})

    def get_drivers(self, session_key: int) -> list[dict]:
        return self._get("drivers", {"session_key": session_key})

    def get_laps(self, session_key: int) -> list[dict]:
        return self._get("laps", {"session_key": session_key})

    def get_intervals(self, session_key: int) -> list[dict]:
        return self._get("intervals", {"session_key": session_key})
