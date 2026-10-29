"""Generate original test media locally; exercise real ASR and both rendering modes."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid

import clip_farm as farm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Existing cached Whisper model or local directory")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent / "test-artifacts" / uuid.uuid4().hex[:8]
    root.mkdir(parents=True)
    source = root / "synthetic.mp4"
    # FFmpeg's bundled Flite voice: synthetic speech, not a user's voice/reference.
    phrase = "This is a synthetic clip farm test. We found a highlight. The video pipeline is working."
    farm.run([
        "ffmpeg", "-nostdin", "-v", "error", "-n",
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=15:duration=44",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=44",
        "-f", "lavfi", "-i", f"flite=text='{phrase}':voice=kal",
        "-filter_complex",
        "[1:a]volume='if(between(t,8,11)+between(t,30,33),0.3,0.005)':eval=frame[tone];"
        "[2:a]asplit[a][b];[a]adelay=7000:all=1[first];[b]adelay=29000:all=1[second];"
        "[tone][first][second]amix=inputs=3:duration=longest:normalize=0[mix]",
        "-map", "0:v", "-map", "[mix]", "-t", "44", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)])
    chat = root / "chat.json"
    chat.write_text(json.dumps([{"time_seconds": 31 + i / 100} for i in range(30)]))
    common = [str(source), "--duration", "15", "--width", "360", "--out", str(root / "clips")]
    blur = farm.main(common + ["--top", "2", "--layout", "blur", "--model", args.model,
                               "--chat", str(chat), "--language", "en"])
    crop = farm.main(common + ["--top", "1", "--layout", "crop", "--no-captions"])
    manifest = json.loads((blur / "manifest.json").read_text())
    assert len(manifest["clips"]) == 2, "Expected two distinct activity peaks"
    assert all(c["caption_cues"] > 0 for c in manifest["clips"]), "No real ASR captions produced"
    assert all(c["width"] == 360 and c["height"] == 640 for c in manifest["clips"])
    assert "-->" in (blur / "clip-01.srt").read_text()
    # Check actual caption pixels: independently render the same frames without subtitles.
    first = manifest["clips"][0]
    no_subs = blur / "comparison-without-captions.mp4"
    render_args = farm.parser().parse_args([str(source), "--width", "360"])
    farm.render(source, first, no_subs, None, render_args)
    def frame_hashes(path):
        return farm.run(["ffmpeg", "-v", "error", "-i", str(path), "-an", "-f", "framemd5", "-"])
    assert frame_hashes(blur / "clip-01.mp4") != frame_hashes(no_subs), "Caption pixels were unchanged"
    # Confirm command-line entry point and no overwrite on a subsequent run.
    result = subprocess.run([sys.executable, str(Path(farm.__file__)), str(source),
                             "--no-captions", "--duration", "15", "--top", "1", "--width", "360",
                             "--out", str(root / "clips")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = {"passed": True, "synthetic_source": str(source), "captioned_blur": str(blur),
              "crop": str(crop), "real_whisper": True, "url_download_tested": False,
              "caption_pixel_difference": True}
    (root / "verification.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
