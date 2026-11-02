"""Opt-in network smoke test: W3C-hosted Blender CC-BY trailer, no publishing."""
import json
import threading
import uuid

from playwright.sync_api import sync_playwright

import clip_farm
import studio

URL = 'https://media.w3.org/2010/05/bunny/trailer.mp4'


def main():
    artifacts = studio.ROOT / 'test-artifacts' / ('url-' + uuid.uuid4().hex[:8])
    app = studio.Studio(artifacts / 'clips', artifacts / 'state', lambda _: None)
    server = studio.make_server(app, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.get_by_text('Local engine connected', exact=False).wait_for()
            page.locator('#urlTab').click()
            page.locator('#vodUrl').fill(URL)
            page.locator('#top').fill('1')
            page.locator('#duration').fill('15')
            page.locator('#captions').uncheck()  # Trailer is music; local ASR has its own browser regression.
            page.screenshot(path=str(artifacts / 'url-input.png'), full_page=True)
            page.locator('#run').click()
            page.wait_for_function("['READY TO REVIEW','FAILED'].includes(document.getElementById('statusBadge').textContent)", timeout=300000)
            assert page.locator('#statusBadge').inner_text() == 'READY TO REVIEW', page.locator('#logs').inner_text()
            job = app.details(app.history()[0]['id'])
            assert any('Downloading ' in line and '%' in line for line in job['logs']), job['logs']
            assert (studio.Path(job['folder']) / 'source.mp4').is_file()
            output = app.media(job['id'], 0)
            info = clip_farm.probe(output)
            video = next(s for s in info['streams'] if s['codec_type'] == 'video')
            assert (video['width'], video['height']) == (720, 1280)
            assert abs(clip_farm.video_duration(info) - 15) < .2
            page.locator('.clip-screen').click()
            page.locator('#previewVideo').evaluate('(v) => v.play()')
            page.wait_for_function("document.getElementById('previewVideo').currentTime > .3")
            page.locator('#closePreview').click()
            page.locator('#logDetails').evaluate('(e) => e.open = true')
            page.screenshot(path=str(artifacts / 'complete.png'), full_page=True)
            assert not errors, errors
            browser.close()
        report = dict(passed=True, source=URL, attribution='(c) copyright 2008, Blender Foundation / www.bigbuckbunny.org; CC BY 3.0',
                      license='https://peach.blender.org/about/', clip=str(output), logs=job['logs'],
                      checks=['URL UI', 'real yt-dlp download', 'live progress', 'source retained in run folder',
                              'existing FFmpeg pipeline', '720x1280 15-second output', 'browser playback', 'no JS errors'])
        (artifacts / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2), flush=True)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
