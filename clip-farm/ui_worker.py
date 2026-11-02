"""Isolated worker for the existing CLI pipeline. Optional VOD downloads; no model downloads."""
import json
import sys

import clip_farm

if __name__ == '__main__':
    try:
        print('Preparing local transcription and video tools…', flush=True)
        folder = clip_farm.main(sys.argv[1:])
        print('STUDIO_RESULT ' + json.dumps({'folder': str(folder)}), flush=True)
    except Exception as exc:
        print(f'Error: {exc}', flush=True)
        sys.exit(1)
