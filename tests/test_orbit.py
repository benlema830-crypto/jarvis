"""The hologram's moons: next calendar events and the Spotify track, read-only and cached."""
import datetime
import unittest
from unittest import mock

import context
import music
import orbit
import spotify_mcp

PLAYING = {"is_playing": True, "progress_ms": 61000, "item": {
    "type": "track", "name": "Thunderstruck", "uri": "spotify:track:T", "duration_ms": 292000,
    "artists": [{"name": "AC/DC"}], "album": {"name": "The Razors Edge", "images": [
        {"url": "https://i.scdn.co/image/big", "width": 640}, {"url": "https://i.scdn.co/image/mid", "width": 300},
        {"url": "https://i.scdn.co/image/small", "width": 64}]}}}


class OrbitTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(orbit._cache, {"events": (0.0, []), "track": (0.0, None)})
        patcher.start(); self.addCleanup(patcher.stop)

    def test_track_reports_song_progress_and_mid_size_art(self):
        with mock.patch.object(music, "configured", return_value=True), \
                mock.patch.object(spotify_mcp, "api", return_value=PLAYING):
            track = orbit.snapshot()["track"]
        self.assertEqual((track["name"], track["artists"], track["art"]), ("Thunderstruck", ["AC/DC"], "https://i.scdn.co/image/mid"))
        self.assertEqual((track["progress_ms"], track["duration_ms"], track["playing"]), (61000, 292000, True))

    def test_art_only_from_spotifys_image_host(self):
        other = {**PLAYING, "item": {**PLAYING["item"], "album": {"images": [{"url": "https://evil.example/x.png"}]}}}
        with mock.patch.object(music, "configured", return_value=True), mock.patch.object(spotify_mcp, "api", return_value=other):
            self.assertEqual(orbit._track()["art"], "")

    def test_nothing_playing_errors_and_no_setup_leave_no_moon(self):
        with mock.patch.object(music, "configured", return_value=True):
            with mock.patch.object(spotify_mcp, "api", return_value={}):
                self.assertIsNone(orbit._track())
            with mock.patch.object(spotify_mcp, "api", side_effect=spotify_mcp.SpotifyError("down")):
                self.assertIsNone(orbit.snapshot()["track"])
        with mock.patch.object(music, "configured", return_value=False):
            self.assertIsNone(orbit._track())

    def test_results_are_cached_between_polls(self):
        with mock.patch.object(music, "configured", return_value=True), \
                mock.patch.object(spotify_mcp, "api", return_value=PLAYING) as api:
            orbit.snapshot(); orbit.snapshot()
        self.assertEqual(api.call_count, 1)

    def test_events_within_a_day_soonest_first(self):
        now = datetime.datetime.now().astimezone()
        events = [{"start": now + datetime.timedelta(hours=h), "title": f"E{h}", "location": "", "all_day": False} for h in (1, 3, 30)]
        with mock.patch.object(context, "calendar_urls", return_value=["https://example.com/c.ics"]), \
                mock.patch.object(context, "event_list", return_value=events):
            listed = orbit.snapshot()["events"]
        self.assertEqual([e["title"] for e in listed], ["E1", "E3"])
        with mock.patch.object(context, "calendar_urls", return_value=[]):
            self.assertEqual(orbit._events(), [])


if __name__ == "__main__":
    unittest.main()
