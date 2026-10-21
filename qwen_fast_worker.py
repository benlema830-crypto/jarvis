"""Offline CUDA-graph Qwen worker using the existing 1.7B model and clone."""
import contextlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path.home() / 'Documents' / 'Jarvis-LocalVoice'
sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor' / 'qwen_cuda'))
os.environ.update(HF_HOME=str(ROOT / 'model-cache'), HF_HUB_OFFLINE='1',
                  TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')


def main():
    protocol = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        import soundfile as sf
        from huggingface_hub import snapshot_download
        from faster_qwen3_tts import FasterQwen3TTS
        torch.set_num_threads(4)
        path = snapshot_download('Qwen/Qwen3-TTS-12Hz-1.7B-Base', local_files_only=True)
        model = FasterQwen3TTS.from_pretrained(path, device='cuda:0', dtype=torch.bfloat16)
        transcript = (ROOT / 'reference/transcript.txt').read_text(encoding='utf-8').strip()
    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            start = time.perf_counter()
            with contextlib.redirect_stdout(sys.stderr):
                audio, rate = model.generate_voice_clone(
                    text=request['text'], language='English',
                    ref_audio=ROOT / 'reference/voice.wav', ref_text=transcript,
                    xvec_only=False, append_silence=False, non_streaming_mode=False,
                    max_new_tokens=1600)
                sf.write(request['output'], audio[0], rate)
            result = {'id': request['id'], 'seconds': time.perf_counter() - start,
                      'audio_seconds': len(audio[0]) / rate}
        except Exception as exc:
            import traceback
            traceback.print_exc(file=sys.stderr)
            result = {'id': request.get('id'), 'error': str(exc)}
        print(json.dumps(result), file=protocol, flush=True)


if __name__ == '__main__':
    main()
