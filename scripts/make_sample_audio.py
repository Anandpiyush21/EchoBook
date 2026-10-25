"""Generate stand-in voice memos for the demo using Piper (open-source, local TTS).

Usage:
    python scripts/make_sample_audio.py --voice path/to/en_GB-northern_english_male-medium.onnx

Voices: https://huggingface.co/rhasspy/piper-voices
Replace these with real recordings whenever you have them; EchoBook doesn't care where audio comes from.
"""
import argparse
import json
import wave
from pathlib import Path

from piper import PiperVoice, SynthesisConfig

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", required=True, help="Path to a Piper .onnx voice model")
    parser.add_argument("--out", default=str(ROOT / "sample_audio"))
    args = parser.parse_args()

    voice = PiperVoice.load(args.voice)
    # A slightly slower, more varied delivery sounds more like an elderly speaker rambling.
    syn = SynthesisConfig(length_scale=1.15, noise_scale=0.75, noise_w_scale=0.9)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for item in json.loads((ROOT / "scripts" / "sample_scripts.json").read_text()):
        path = out / item["file"]
        with wave.open(str(path), "wb") as wav:
            voice.synthesize_wav(item["text"], wav, syn_config=syn)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
