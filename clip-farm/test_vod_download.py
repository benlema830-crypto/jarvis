from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import vod_download as vod


class VodTests(unittest.TestCase):
    def test_url_validation(self):
        for url in ('file:///secret', 'ftp://example.com/a', 'https://', 'https://u:p@example.com/x', 'bad link'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                vod.validate_url(url)
        self.assertEqual(vod.validate_url(' https://www.twitch.tv/videos/123 '), 'https://www.twitch.tv/videos/123')

    def test_live_and_unbounded_streams_refused(self):
        for info in ({'is_live': True}, *({'live_status': s} for s in ('is_live', 'is_upcoming', 'post_live')),
                     {'protocol': 'm3u8_native'}, {'protocol': 'http_dash_segments', 'duration': float('inf')},
                     {'requested_formats': [{'protocol': 'm3u8_native'}]}):
            with self.subTest(info=info), self.assertRaises(ValueError):
                vod.require_vod(info)
        vod.require_vod({'live_status': 'was_live', 'protocol': 'm3u8_native', 'duration': 120})
        vod.require_vod({'protocol': 'https'})  # finite direct-file downloads have no pre-probe duration

    def test_restricted_and_playlists_refused(self):
        for info in ({'_type': 'playlist'}, {'_type': 'multi_video'}, {'availability': 'private'},
                     {'availability': 'subscriber_only'}, {'availability': 'needs_auth'}):
            with self.subTest(info=info), self.assertRaises(ValueError):
                vod.require_vod(info)

    def test_preflight_before_download_progress_and_merge(self):
        with tempfile.TemporaryDirectory() as directory, patch('yt_dlp.YoutubeDL') as cls:
            folder = Path(directory)
            client = cls.return_value.__enter__.return_value
            client.extract_info.return_value = {'protocol': 'https', 'duration': 33}
            def process(info, download):
                self.assertTrue(download)
                options = cls.call_args.args[0]
                self.assertEqual(options['merge_output_format'], 'mp4')
                self.assertTrue(options['noplaylist'])
                self.assertIs(options['match_filter'], vod.require_vod)
                options['progress_hooks'][0]({'status': 'downloading', 'downloaded_bytes': 50, 'total_bytes': 100})
                options['progress_hooks'][0]({'status': 'finished'})
                (folder / 'source.mp4').write_bytes(b'fixture')
            client.process_ie_result.side_effect = process
            output = io.StringIO()
            with redirect_stdout(output):
                result = vod.download('https://example.com/video', folder, True)
            client.extract_info.assert_called_once_with('https://example.com/video', download=False)
            self.assertEqual(result.name, 'source.mp4')
            self.assertIn('50.0%', output.getvalue())

    def test_live_does_not_start_media_download(self):
        with tempfile.TemporaryDirectory() as directory, patch('yt_dlp.YoutubeDL') as cls:
            client = cls.return_value.__enter__.return_value
            client.extract_info.return_value = {'is_live': True}
            with self.assertRaisesRegex(ValueError, 'Live'):
                vod.download('https://example.com/live', Path(directory), True)
            client.process_ie_result.assert_not_called()

    def test_permission_and_download_errors(self):
        from yt_dlp.utils import DownloadError
        with self.assertRaisesRegex(ValueError, 'allow-download'):
            vod.download('https://example.com/video', Path('.'), False)
        with patch('yt_dlp.YoutubeDL') as cls:
            cls.return_value.__enter__.return_value.extract_info.side_effect = DownloadError('HTTP 403')
            with self.assertRaisesRegex(ValueError, 'private, subscriber-only'):
                vod.download('https://example.com/video', Path('.'), True)


if __name__ == '__main__':
    unittest.main()
