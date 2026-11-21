"""Replies are gzipped for a client that asks (a browser always does): the page and the JSON of every tab."""

import gzip
import json

import pytest

from jobwatch.web import accepts_gzip

from .conftest import TOKEN, request

OK = {"X-Jobwatch-Token": TOKEN}


@pytest.mark.parametrize("header, expected", [
    ("gzip", True), ("gzip, deflate, br", True), ("deflate, GZIP", True), ("br;q=1.0, gzip;q=0.8", True),
    ("gzip;q=0", False), ("gzip; q=0.0", False), ("identity", False), ("br, deflate", False), ("", False),
    ("*", False), ("gzip;q=.", True)])
def test_accepts_gzip_reads_the_header(header, expected):
    assert accepts_gzip(header) is expected


def test_the_page_is_gzipped_for_a_browser_and_plain_for_a_client_that_does_not_ask(server):
    status, plain, headers = request(server, "GET", "/", with_headers=True)
    assert status == 200 and "Content-Encoding" not in headers and len(plain) > 100_000
    status, packed, headers = request(server, "GET", "/", headers={"Accept-Encoding": "gzip, deflate, br"},
                                      with_headers=True)
    assert status == 200 and headers["Content-Encoding"] == "gzip" and headers["Vary"] == "Accept-Encoding"
    assert int(headers["Content-Length"]) == len(packed) < len(plain) / 3
    assert gzip.decompress(packed) == plain
    assert headers["Content-Type"] == "text/html; charset=utf-8"


def test_json_is_gzipped_when_it_is_big_enough_and_asked_for(server):
    settings = request(server, "GET", "/api/settings", headers=OK)[1]
    assert len(settings) > 1024  # the watchlist's settings are the bigger reply of a store with no jobs
    status, packed, headers = request(server, "GET", "/api/settings", headers={**OK, "Accept-Encoding": "gzip"},
                                      with_headers=True)
    assert status == 200 and headers["Content-Encoding"] == "gzip"
    assert json.loads(gzip.decompress(packed)) == json.loads(settings)
    # a tiny reply and a client that refuses gzip get it as it is
    small = request(server, "GET", "/api/pace", headers={**OK, "Accept-Encoding": "gzip"}, with_headers=True)
    assert small[0] == 200 and "Content-Encoding" not in small[2] and "pace" in json.loads(small[1])
    refused = request(server, "GET", "/api/settings", headers={**OK, "Accept-Encoding": "gzip;q=0"},
                      with_headers=True)
    assert "Content-Encoding" not in refused[2] and refused[1] == settings


def test_errors_and_the_token_check_still_answer_plainly_or_compressed_without_breaking_json(server):
    status, body = request(server, "GET", "/api/settings", headers={"X-Jobwatch-Token": "wrong",
                                                                    "Accept-Encoding": "gzip"})
    assert status == 403 and json.loads(body)["error"]  # under GZIP_MIN: plain


def test_a_stored_file_is_never_compressed(server):
    status, _, headers = request(server, "GET", "/manifest.webmanifest", headers={"Accept-Encoding": "gzip"},
                                 with_headers=True)
    assert status == 200 and "Content-Encoding" not in headers
