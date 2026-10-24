import threading
import unittest
from unittest.mock import patch

import requests

from application.services.riot_rate_limiter import (
    RiotRateLimiter,
    shared_rate_limiter,
)
from application.services.riot_service import RiotService


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self.payload = payload
        self.headers = headers or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class CountingLimiter:
    def __init__(self):
        self.calls = 0

    def wait(self):
        self.calls += 1


class RiotRateLimiterTests(unittest.TestCase):
    def build(self, limits):
        self.now = 0.0
        self.sleeps = []

        def sleep(seconds):
            self.sleeps.append(seconds)
            self.now += seconds

        return RiotRateLimiter(limits=limits, clock=lambda: self.now, sleep=sleep)

    def test_waits_until_the_oldest_request_leaves_the_window(self):
        limiter = self.build(((2, 1.0),))

        limiter.wait()
        self.now = 0.25
        limiter.wait()
        limiter.wait()

        self.assertEqual(self.sleeps, [0.75])

    def test_requests_outside_the_window_do_not_count(self):
        limiter = self.build(((2, 1.0),))

        limiter.wait()
        limiter.wait()
        self.now = 5.0
        limiter.wait()

        self.assertEqual(self.sleeps, [])

    def test_defaults_stay_below_development_key_limits(self):
        count_by_window = {window: count for count, window in shared_rate_limiter.limits}

        self.assertLess(count_by_window[1.0], 20)
        self.assertLess(count_by_window[120.0], 100)

    def test_concurrent_callers_never_exceed_a_limit(self):
        limiter = RiotRateLimiter(limits=((5, 0.2),))
        moments = []
        lock = threading.Lock()

        def worker():
            for _ in range(3):
                limiter.wait()

                with lock:
                    moments.append(limiter.clock())

        threads = [threading.Thread(target=worker) for _ in range(4)]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        moments.sort()

        for index in range(len(moments) - 5):
            self.assertGreaterEqual(moments[index + 5] - moments[index], 0.19)


class RiotServiceMatchHistoryTests(unittest.TestCase):
    def setUp(self):
        key_patch = patch(
            "application.services.riot_service.RiotApiKeyService.get_api_key",
            return_value="RGAPI-synthetic-key",
        )
        key_patch.start()
        self.addCleanup(key_patch.stop)

        self.limiter = CountingLimiter()
        self.sleeps = []
        self.service = RiotService(rate_limiter=self.limiter, sleep=self.sleeps.append)

    def patch_responses(self, *responses):
        request_patch = patch(
            "application.services.riot_service.requests.request",
            side_effect=list(responses),
        )
        mocked = request_patch.start()
        self.addCleanup(request_patch.stop)
        return mocked

    def test_match_ids_use_the_regional_route_and_paging_parameters(self):
        mocked = self.patch_responses(FakeResponse(200, ["EUW1_2", "EUW1_1"]))

        match_ids = self.service.get_match_ids("puuid/with+chars", "euw1", start=100, count=50, queue=420)

        self.assertEqual(match_ids, ["EUW1_2", "EUW1_1"])
        call = mocked.call_args.kwargs
        self.assertEqual(
            call["url"],
            "https://europe.api.riotgames.com/lol/match/v5/matches/by-puuid/puuid%2Fwith%2Bchars/ids",
        )
        self.assertEqual(call["params"], {"start": 100, "count": 50, "queue": 420})
        self.assertEqual(call["headers"]["X-Riot-Token"], "RGAPI-synthetic-key")
        self.assertEqual(self.limiter.calls, 1)

    def test_match_ids_omit_queue_when_not_filtered(self):
        mocked = self.patch_responses(FakeResponse(200, []))

        self.assertEqual(self.service.get_match_ids("p", "NA1"), [])
        self.assertEqual(mocked.call_args.kwargs["params"], {"start": 0, "count": 100})
        self.assertIn("americas.api.riotgames.com", mocked.call_args.kwargs["url"])

    def test_match_returns_document_or_none_when_gone(self):
        self.patch_responses(FakeResponse(200, {"metadata": {}}), FakeResponse(404))

        self.assertEqual(self.service.get_match("EUW1_1", "EUW1"), {"metadata": {}})
        self.assertIsNone(self.service.get_match("EUW1_2", "EUW1"))

    def test_rate_limited_and_temporary_failures_are_retried(self):
        self.patch_responses(
            FakeResponse(429, headers={"Retry-After": "7"}),
            FakeResponse(503),
            FakeResponse(200, ["EUW1_1"]),
        )

        self.assertEqual(self.service.get_match_ids("p", "EUW1"), ["EUW1_1"])
        self.assertEqual(self.sleeps, [7, 4])
        self.assertEqual(self.limiter.calls, 3)

    def test_rejected_key_raises_without_retrying(self):
        mocked = self.patch_responses(FakeResponse(403))

        with self.assertRaises(requests.HTTPError):
            self.service.get_match("EUW1_1", "EUW1")

        self.assertEqual(mocked.call_count, 1)

    def test_persistent_rate_limiting_eventually_raises(self):
        self.patch_responses(*[FakeResponse(429, headers={"Retry-After": "1"})] * 5)

        with self.assertRaises(requests.HTTPError):
            self.service.get_match_ids("p", "EUW1")

        self.assertEqual(len(self.sleeps), 4)

    def test_invalid_payloads_and_arguments_are_rejected(self):
        self.patch_responses(FakeResponse(200, {"not": "a list"}), FakeResponse(200, ["not", "a", "dict"]))

        with self.assertRaises(ValueError):
            self.service.get_match_ids("p", "EUW1")

        with self.assertRaises(ValueError):
            self.service.get_match("EUW1_1", "EUW1")

        with self.assertRaises(ValueError):
            self.service.get_match_ids(" ", "EUW1")

        with self.assertRaises(ValueError):
            self.service.get_match("", "EUW1")

    def test_account_lookup_uses_asia_for_sea_platforms(self):
        mocked = self.patch_responses(FakeResponse(200, {"puuid": "p"}))

        self.service.get_account_by_riot_id("Name", "OCE", "OC1")

        self.assertTrue(mocked.call_args.kwargs["url"].startswith("https://asia.api.riotgames.com/riot/account/v1/"))
        self.assertEqual(RiotService.get_regional_route("OC1"), "sea")
        self.assertEqual(RiotService.get_account_regional_route("EUW1"), "europe")


if __name__ == "__main__":
    unittest.main()
