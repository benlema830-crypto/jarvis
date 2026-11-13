"""Browser regression for the workshop selector and scene execution; --live uses installed Qwen."""
import sys
import json
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import workshop
from test_workshop import SCRIPT
from check_brain_browser import serve, CHROME
from playwright.sync_api import sync_playwright


def main():
    scene = workshop.parse(SCRIPT)
    scenes = [scene]
    if '--live' in sys.argv:
        text = []
        workshop.generate(workshop.QWEN_MODEL, 'low', workshop.SYSTEM,
                          'Build a simple desk lamp with a base, upright arm and shade. Use three steps and keep the script brief.', on_text=text.append)
        scene = workshop.parse(''.join(text))
        assert scene['steps'], 'Qwen returned no steps'
        scenes = [scene]
        text = []
        workshop.generate(workshop.QWEN_MODEL, 'low', workshop.SYSTEM,
                          workshop.EDIT + '\nMake the shade red.\nCurrent script:\n' + workshop.script(scene), on_text=text.append)
        scenes.append(workshop.apply_patch(scene, workshop.parse(''.join(text))))
    cache = Path(tempfile.gettempdir()) / 'jarvis-workshop-browser-scenes.json'
    if '--live' in sys.argv: cache.write_text(json.dumps(scenes))
    if '--replay' in sys.argv: scenes = json.loads(cache.read_text())
    state = {'open': True, 'busy': '', 'selected_model': 'fable', 'model': 'fable', 'scene': None, 'recent': []}
    server = serve(with_checks=False)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=str(CHROME), headless=True, args=['--enable-unsafe-swiftshader'])
            page = browser.new_page(viewport={'width':1660, 'height':896})
            def route(r):
                if r.request.method == 'POST':
                    payload = r.request.post_data_json
                    if payload.get('action') == 'model': state['selected_model'] = payload['model']
                    r.fulfill(json={'ok': True})
                else: r.fulfill(json=state)
            def asset(r):
                from urllib.parse import urlparse
                name = urlparse(r.request.url).path.lstrip('/')
                mime = 'text/html' if name.endswith('.html') else 'text/javascript'
                r.fulfill(path=str(Path(__file__).resolve().parents[1] / 'hud' / name), content_type=mime,
                          headers={'Access-Control-Allow-Origin': '*'})
            page.route('**/workshop.js*', asset)
            page.route('**/workshop-frame.html*', asset)
            page.route('**/vendor/*.js', asset)
            page.route('**/workshop', route)
            page.add_init_script("window.frameMessages=[]; addEventListener('message',e=>{if(e.data?.t)frameMessages.push(e.data)});")
            page.goto(f'http://127.0.0.1:{server.server_port}/?workshop=1')
            pick = page.get_by_role('combobox', name='Workshop model')
            pick.wait_for(state='visible')
            assert pick.locator('option').count() == 2
            assert pick.evaluate("e=>getComputedStyle(e).pointerEvents") == 'auto'
            for choice in ['qwen','fable','qwen']:
                pick.select_option(choice)
                page.wait_for_function('(v)=>document.querySelector(".ws-head select").value===v && !document.querySelector(".ws-head select").disabled', arg=choice)
                assert state['selected_model'] == choice
            page.reload()
            pick.wait_for(state='visible')
            assert pick.input_value() == 'qwen'
            for scene in scenes:
                state['scene'] = dict(scene, id='browser-test', versions=0)
                page.evaluate('window.frameMessages=[]; J.workshop.sync(true)')
                page.wait_for_function("n=>frameMessages.some(m=>m.t==='error' || (m.t==='parts' && m.parts.length>=n))", arg=len(workshop.parts(scene)))
                page.wait_for_timeout(1500)
                errors = page.evaluate("frameMessages.filter(m=>m.t==='error')")
                assert not errors, errors
            state['busy']='build'
            page.evaluate('J.workshop.sync(false)')
            page.wait_for_function('document.querySelector(".ws-head select").disabled')
            browser.close()
            print('PASS: clickable selector, switching, reload persistence, busy state, and scene rendering' + (' with live Qwen build and edit' if '--live' in sys.argv else ''))
    finally:
        server.shutdown(); server.server_close()

if __name__ == '__main__': main()


