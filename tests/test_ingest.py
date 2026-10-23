from datetime import date

import pytest
import requests

from proc_intel.http import get_json, retry_delay
from proc_intel.ingest import page_file_name, page_is_older_than, page_offsets, parse_wb_date, partition_folder, slugify


def test_parse_wb_date():
    assert parse_wb_date("19-Oct-2026") == date(2026, 10, 19)
    assert parse_wb_date("2026-10-19") is None
    assert parse_wb_date(None) is None


def test_page_offsets():
    assert page_offsets(25, 10) == [0, 10, 20]
    assert page_offsets(0, 10) == []
    with pytest.raises(ValueError):
        page_offsets(10, 0)


def test_page_is_older_than():
    cutoff = date(2018, 1, 1)
    assert page_is_older_than([{"noticedate": "31-Dec-2017"}, {"noticedate": None}], cutoff)
    assert not page_is_older_than([{"noticedate": "31-Dec-2017"}, {"noticedate": "02-Jan-2018"}], cutoff)
    assert page_is_older_than([], cutoff)


def test_slugify_and_page_names():
    assert slugify("Cote d'Ivoire") == "cote_d_ivoire"
    assert slugify("Western and Central Africa") == "western_and_central_africa"
    assert page_file_name(500) == "page_0000500.json"


def test_partition_folder_is_unique_when_slugs_collide():
    assert slugify("Turkiye") == slugify("Türkiye")
    assert partition_folder("Turkiye") != partition_folder("Türkiye")
    assert partition_folder("Türkiye").startswith("turkiye_")


def test_retry_delay_prefers_server_hints():
    assert retry_delay(0, retry_after="7") == 7
    assert retry_delay(3, "Rate limit is exceeded. Try again in 24 seconds.") == 25
    assert retry_delay(0) == 2 and retry_delay(2) == 8
    assert retry_delay(20) == 120


class FakeResponse:
    def __init__(self, status, payload=None, text="", headers=None):
        self.status_code, self._payload, self.text, self.headers = status, payload, text, headers or {}

    def json(self):
        if self._payload is None:
            raise requests.JSONDecodeError("not json", "", 0)
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return self.responses.pop(0)


def test_get_json_retries_429_then_succeeds():
    session = FakeSession([FakeResponse(429, text="Try again in 1 seconds"), FakeResponse(200, {"ok": 1})])
    waits = []
    assert get_json("u", {}, session=session, sleep=waits.append) == {"ok": 1}
    assert session.calls == 2 and len(waits) == 1


def test_get_json_retries_non_json_body():
    session = FakeSession([FakeResponse(200, None, text="<html>"), FakeResponse(200, {"ok": 1})])
    assert get_json("u", {}, session=session, sleep=lambda s: None) == {"ok": 1}


def test_get_json_does_not_retry_client_errors():
    session = FakeSession([FakeResponse(400, text="bad request")])
    with pytest.raises(requests.HTTPError):
        get_json("u", {}, session=session, sleep=lambda s: None)
    assert session.calls == 1


def test_get_json_gives_up():
    session = FakeSession([FakeResponse(503)] * 3)
    with pytest.raises(RuntimeError):
        get_json("u", {}, session=session, max_retries=2, sleep=lambda s: None)
