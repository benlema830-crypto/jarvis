"""Real browser -> upload -> existing ASR/FFmpeg pipeline -> review. No external media."""
import json
from pathlib import Path
import threading
import time
import uuid

from playwright.sync_api import sync_playwright

import clip_farm
import studio


def main():
    source = next((studio.ROOT / 'test-artifacts').glob('*/synthetic.mp4'))
    artifacts = studio.ROOT / 'test-artifacts' / ('studio-' + uuid.uuid4().hex[:8])
    artifacts.mkdir()
    chat = artifacts / 'chat.csv'
    chat.write_text('time_seconds,message\n8.1,synthetic test\n8.2,synthetic test\n')
    opened = []
    app = studio.Studio(artifacts / 'clips', artifacts / 'state', opened.append)
    server = studio.make_server(app, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page(viewport={'width': 1512, 'height': 1100}, device_scale_factor=1)
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}', wait_until='networkidle')
            page.get_by_text('Local engine connected', exact=False).wait_for()
            page.screenshot(path=str(artifacts / 'empty.png'), full_page=True)
            page.locator('#urlTab').click()
            assert page.locator('#urlNotice').is_visible()
            assert page.locator('#vodUrl').is_visible()
            page.locator('#localTab').click()
            page.locator('#videoFile').set_input_files(str(source))
            page.wait_for_function("document.getElementById('videoName').textContent === 'synthetic.mp4'")
            first_upload = page.evaluate('video.id')
            page.evaluate("""() => { const data = new DataTransfer(); data.items.add(document.getElementById('videoFile').files[0]);
                document.getElementById('dropzone').dispatchEvent(new DragEvent('drop', {bubbles:true, dataTransfer:data})); }""")
            page.wait_for_function('old => video.id !== old && !uploading', arg=first_upload)
            page.locator('#chatFile').set_input_files(str(chat))
            page.wait_for_function("document.getElementById('chatName').textContent === 'chat.csv'")
            page.locator('#top').fill('1')
            page.locator('#duration').fill('15')
            models = studio.cached_models()
            model = next((m for m in models if 'large-v3-turbo' in m['name']), models[0])
            page.locator('#model').select_option(model['path'])
            page.locator('#run').click()
            page.wait_for_function("document.getElementById('statusBadge').textContent === 'RUNNING'", timeout=20000)
            page.wait_for_function("document.getElementById('statusBadge').textContent === 'READY TO REVIEW' || document.getElementById('statusBadge').textContent === 'FAILED'", timeout=300000)
            assert page.locator('#statusBadge').inner_text() == 'READY TO REVIEW', page.locator('#logs').inner_text()
            assert page.locator('.clip-card').count() == 1
            job_id = app.history()[0]['id']
            job = app.details(job_id)
            assert job['clips'][0]['caption_cues'] > 0
            output = app.media(job_id, 0)
            info = clip_farm.probe(output)
            video = next(s for s in info['streams'] if s['codec_type'] == 'video')
            assert (video['width'], video['height']) == (720, 1280)
            assert abs(clip_farm.video_duration(info) - 15) < .2
            page.locator('.clip-screen').click()
            page.wait_for_function("document.getElementById('previewVideo').readyState >= 2")
            assert '-->' in page.locator('#previewCaptions').inner_text()
            page.locator('#previewVideo').evaluate('(video) => video.play()')
            page.wait_for_function("document.getElementById('previewVideo').currentTime > .3")
            page.locator('#previewVideo').evaluate('(video) => video.pause()')
            page.screenshot(path=str(artifacts / 'preview.png'), full_page=True)
            page.locator('#previewActions .approve').click()
            page.wait_for_function("document.querySelector('#previewActions .approve').getAttribute('aria-pressed') === 'true'")
            assert (app.output / 'approved' / job_id / 'clip-01.mp4').read_bytes() == output.read_bytes()
            assert (app.output / 'approved' / job_id / 'clip-01.srt').is_file()
            page.locator('#closePreview').click()
            page.locator('#openFolder').click()
            page.wait_for_timeout(250)
            assert opened == [job['folder']], opened
            page.reload(wait_until='networkidle')
            page.locator('.clip-card.approved').wait_for()
            page.locator('[data-filter="rejected"]').click()
            assert page.locator('#filterEmpty').is_visible()
            page.locator('[data-filter="all"]').click()
            page.locator('.clip-card .reject').click()
            page.locator('.clip-card.rejected').wait_for()
            assert not (app.output / 'approved' / job_id / 'clip-01.mp4').exists()
            assert output.is_file()
            page.locator('.clip-card .approve').click()
            page.locator('.clip-card.approved').wait_for()
            page.evaluate('window.scrollTo(0, 0)')
            page.screenshot(path=str(artifacts / 'gallery.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            page.locator('#historyToggle').click()
            assert page.locator('.history-item').first.is_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile horizontal overflow'
            page.screenshot(path=str(artifacts / 'mobile.png'), full_page=True)
            assert not errors, errors
            browser.close()
        report = dict(passed=True, real_whisper=True, model=model['name'], source=str(source),
                      run_id=job_id, clip=str(output), resolution=[720, 1280], duration=15,
                      checks=['page load', 'video browse and drag/drop upload', 'chat upload', 'URL source tab', 'real captioned render',
                              'video playback', 'transcript', 'approve copy', 'reload persistence', 'filter',
                              'reject removes copy only', 'folder opener mocked', 'mobile overflow', 'no JS errors'])
        (artifacts / 'verification.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2), flush=True)
        print('Screenshots: ' + str(artifacts), flush=True)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
