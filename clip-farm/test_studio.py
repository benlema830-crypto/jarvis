import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import studio


class StudioTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.opener = mock.Mock()
        self.app = studio.Studio(root / 'clips', root / 'state', self.opener)
        self.server = studio.make_server(self.app, 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, data=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        base = {'X-Studio-Token': self.app.token}
        if isinstance(data, dict):
            data = json.dumps(data).encode()
            base['Content-Type'] = 'application/json'
        base.update(headers or {})
        try:
            conn.request(method, path, body=data, headers=base)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def upload(self):
        status, _, body = self.request('PUT', '/api/upload/video', b'fixture', {'X-File-Name': '../../source.mp4'})
        self.assertEqual(status, 200)
        return json.loads(body)['id']

    def completed(self):
        folder = self.app.output / 'run-fixture'
        folder.mkdir()
        (folder / 'clip-01.mp4').write_bytes(b'0123456789')
        (folder / 'clip-01.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nHello\n')
        studio.atomic_json(folder / 'manifest.json', {'clips': [{'file': 'clip-01.mp4', 'score': .8}]})
        self.app.history()
        return folder

    def test_page_static_assets_and_host_guards(self):
        for path in ('/', '/app.js', '/style.css'):
            code, _, body = self.request('GET', path)
            self.assertEqual(code, 200)
            self.assertTrue(body)
        self.assertEqual(self.request('GET', '/api/runs', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('POST', '/api/runs', {}, {'X-Studio-Token': ''})[0], 403)
        self.assertEqual(self.request('POST', '/api/runs', {}, {'Origin': 'https://evil.example'})[0], 403)

    def test_upload_paths_and_invalid_types(self):
        upload_id = self.upload()
        path, meta = self.app.upload(upload_id, 'video')
        self.assertEqual(meta['name'], 'source.mp4')
        self.assertEqual(path.parent, self.app.state / 'uploads')
        self.assertEqual(path.read_bytes(), b'fixture')
        self.assertEqual(self.request('PUT', '/api/upload/video', b'x', {'X-File-Name': 'x.exe'})[0], 400)
        self.assertEqual(self.request('POST', '/api/runs', {'video': '../../.env'})[0], 400)

    def test_validation_and_only_one_worker(self):
        upload_id = self.upload()
        base = dict(video=upload_id, top=1, duration=15, captions=False, layout='crop')
        for changes in ({'top': 0}, {'duration': 61}, {'layout': 'bad'}, {'captions': 'yes'}):
            self.assertEqual(self.request('POST', '/api/runs', base | changes)[0], 400)
        with mock.patch.object(studio.threading, 'Thread') as thread, mock.patch.object(studio.shutil, 'which', return_value='tool'):
            job_id = self.app.start(base)
            self.assertEqual(self.app.get(job_id)['status'], 'running')
            with self.assertRaises(RuntimeError):
                self.app.start(base)
            self.assertEqual(thread.call_count, 1)

    def test_url_job_uses_shared_cli_download_flag(self):
        for url in ('not a URL', 'file:///secret', 'https://user:pass@example.com/a'):
            self.assertEqual(self.request('POST', '/api/runs', {'url': url})[0], 400)
        with mock.patch.object(studio.threading, 'Thread') as thread:
            job_id = self.app.start(dict(url='https://www.twitch.tv/videos/123', captions=False))
            args = thread.call_args.kwargs['args'][1]
            self.assertIn('--allow-download', args)
            self.assertEqual(args[0], 'https://www.twitch.tv/videos/123')
            self.assertEqual(self.app.get(job_id)['name'], 'www.twitch.tv VOD')

    def test_video_ranges_and_no_path_escape(self):
        folder = self.completed()
        status, headers, data = self.request('GET', '/media/run-fixture/0', headers={'Range': 'bytes=2-5'})
        self.assertEqual((status, data), (206, b'2345'))
        self.assertEqual(headers['Content-Range'], 'bytes 2-5/10')
        self.assertEqual(self.request('GET', '/media/run-fixture/0', headers={'Range': 'bytes=-3'})[2], b'789')
        self.assertEqual(self.request('GET', '/media/run-fixture/0', headers={'Range': 'bytes=99-'})[0], 416)
        self.assertEqual(self.request('GET', '/media/run-fixture/10')[0], 400)
        studio.atomic_json(folder / 'manifest.json', {'clips': [{'file': '../../secret.mp4'}]})
        self.assertEqual(self.request('GET', '/media/run-fixture/0')[0], 400)

    def test_approve_reject_persistence_and_open_is_explicit(self):
        folder = self.completed()
        self.app.review('run-fixture', 0, 'approved')
        dest = self.app.output / 'approved/run-fixture'
        self.assertEqual((dest / 'clip-01.mp4').read_bytes(), b'0123456789')
        self.assertTrue((dest / 'clip-01.srt').is_file())
        self.app.review('run-fixture', 0, 'approved')
        fresh = studio.Studio(self.app.output, self.app.state, self.opener)
        self.assertEqual(fresh.details('run-fixture')['clips'][0]['review'], 'approved')
        fresh.review('run-fixture', 0, 'rejected')
        self.assertFalse((dest / 'clip-01.mp4').exists())
        self.assertTrue((folder / 'clip-01.mp4').exists())
        self.opener.assert_not_called()
        self.assertEqual(self.request('POST', '/api/runs/run-fixture/open', {})[0], 200)
        self.opener.assert_called_once_with(str(folder))

    def test_restart_marks_running_job_interrupted(self):
        self.app.save(dict(id='test', status='running', phase='rendering'))
        self.app.recover()
        self.assertEqual(self.app.get('test')['status'], 'interrupted')

    def test_worker_failure_is_persisted_and_releases_run_slot(self):
        job = dict(id='failed-job', status='running', phase='Preparing', folder=None, logs=[])
        self.app.active = job['id']
        with mock.patch.object(studio.subprocess, 'Popen') as popen:
            process = popen.return_value.__enter__.return_value
            process.stdout = iter(['Preparing local tools\n', 'Error: invalid video\n'])
            process.wait.return_value = 1
            self.app.worker(job, ['source.mp4', '--no-captions'])
        saved = self.app.get(job['id'])
        self.assertEqual(saved['status'], 'failed')
        self.assertIn('Error: invalid video', saved['logs'])
        self.assertIsNone(self.app.active)


if __name__ == '__main__':
    unittest.main()
