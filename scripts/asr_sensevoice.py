#!/usr/bin/env python3
"""Server-side SenseVoice ASR provider (sherpa-onnx, CPU, int8 model).

This is a drop-in alternative to ``scripts/asr_local.py`` for the Aliyun
2C/2GB server: it uses the compact int8 ONNX SenseVoice model through
sherpa-onnx instead of the 2.2 GB Paraformer PyTorch stack. It keeps the same
CLI (``--json <wav>``) and JSON fields so ``scripts/audio_receiver.py`` can
switch providers with configuration only.

The model files (``model.int8.onnx`` and ``tokens.txt``) are not in Git.
Download them with ``docs/experiments/017-cloud-ai-deployment.md`` and point
``--model-dir`` at the extracted directory.

Examples:
    work/sensevoice-venv/bin/python scripts/asr_sensevoice.py --json x.wav
    work/sensevoice-venv/bin/python scripts/asr_sensevoice.py --threads 2 x.wav
"""

from __future__ import annotations

import argparse
import array
import json
import os
import pathlib
import sys
import time
import wave

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_MODEL_DIR = ROOT / "work" / "models" / "sensevoice"
DEFAULT_THREADS = 2
DEFAULT_LANGUAGE = "zh"


def peak_rss_mb():
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmHWM:"):
                    return round(int(line.split()[1]) / 1024.0, 1)
    except (OSError, ValueError):
        pass
    return None


def inspect_wav(path):
    path = pathlib.Path(path)
    if not path.is_file():
        raise ValueError(f"file does not exist: {path}")
    try:
        with wave.open(str(path), "rb") as wav:
            rate = wav.getframerate()
            width = wav.getsampwidth()
            channels = wav.getnchannels()
            frames = wav.getnframes()
            comptype = wav.getcomptype()
            data = wav.readframes(frames)
    except (wave.Error, OSError) as exc:
        raise ValueError(f"cannot parse WAV {path}: {exc}") from None
    if comptype != "NONE":
        raise ValueError(f"unsupported compression: {comptype}")
    if rate != 16000:
        raise ValueError(f"expected 16000 Hz, got {rate}")
    if width != 2:
        raise ValueError(f"expected 16 bit, got {width * 8}")
    if channels != 1:
        raise ValueError(f"expected mono, got {channels}")
    if frames == 0:
        raise ValueError("WAV has no audio frames")
    samples = array.array("h")
    samples.frombytes(data)
    if sys.byteorder != "little":
        samples.byteswap()
    return rate, frames, [value / 32768.0 for value in samples]


class SenseVoiceEngine:
    def __init__(self, model_dir=DEFAULT_MODEL_DIR, threads=DEFAULT_THREADS,
                 language=DEFAULT_LANGUAGE, use_itn=False):
        model_dir = pathlib.Path(model_dir)
        model = model_dir / "model.int8.onnx"
        tokens = model_dir / "tokens.txt"
        if not model.is_file():
            raise FileNotFoundError(f"missing model: {model}")
        if not tokens.is_file():
            raise FileNotFoundError(f"missing tokens: {tokens}")
        try:
            import sherpa_onnx
        except Exception as exc:  # pragma: no cover - environment damage
            raise RuntimeError(f"cannot import sherpa_onnx: {exc}") from None
        if not 1 <= threads <= 4:
            raise ValueError("threads must be 1-4")
        started = time.perf_counter()
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model),
            tokens=str(tokens),
            num_threads=threads,
            use_itn=use_itn,
            language=language,
            debug=False,
            provider="cpu",
        )
        self.model_load_ms = (time.perf_counter() - started) * 1000.0
        self.language = language

    def transcribe(self, path):
        rate, frames, samples = inspect_wav(path)
        started = time.perf_counter()
        stream = self.recognizer.create_stream()
        stream.accept_waveform(rate, samples)
        self.recognizer.decode_stream(stream)
        text = str(stream.result.text or "").strip()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "text": text,
            "inference_ms": round(elapsed_ms, 1),
            "duration_s": round(frames / float(rate), 3),
            "frames": frames,
        }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="使用 sherpa-onnx SenseVoice 识别 16kHz/16bit/单声道 WAV")
    parser.add_argument("wav", type=pathlib.Path, nargs="+")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--model-dir", type=pathlib.Path,
                        default=DEFAULT_MODEL_DIR)
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS)
    parser.add_argument("--language", default=DEFAULT_LANGUAGE,
                        help="zh/en/ja/ko/yue/auto（默认 zh）")
    parser.add_argument("--itn", action="store_true",
                        help="开启逆文本标准化（默认关闭）")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    def log(message):
        print(message, file=sys.stderr if args.json else sys.stdout,
              flush=True)

    def fail(wav, reason, message):
        record = {
            "status": "error",
            "provider": "sensevoice",
            "model": "sherpa-onnx-sense-voice-int8",
            "wav": pathlib.Path(wav).name if wav else "",
            "wav_path": str(wav) if wav else "",
            "reason": reason,
            "error": message,
            "text": "",
        }
        if args.json:
            print(json.dumps(record, ensure_ascii=False), flush=True)
        else:
            print(f"ERR [{wav}]: {reason}: {message}", file=sys.stderr,
                  flush=True)

    try:
        engine = SenseVoiceEngine(args.model_dir, args.threads,
                                  args.language, args.itn)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        fail(None, "model_error", str(exc))
        return 1
    log(f"model=sherpa-onnx-sense-voice-int8 "
        f"path={args.model_dir} load_ms={engine.model_load_ms:.1f} "
        f"threads={args.threads}")

    failures = 0
    for wav in args.wav:
        try:
            result = engine.transcribe(wav)
        except (ValueError, OSError) as exc:
            failures += 1
            fail(wav, "bad_wav", str(exc))
            continue
        if not result["text"]:
            failures += 1
            fail(wav, "empty_text", "SenseVoice returned an empty transcript")
            continue
        record = {
            "status": "success",
            "provider": "sensevoice",
            "model": "sherpa-onnx-sense-voice-int8",
            "wav": pathlib.Path(wav).name,
            "wav_path": str(wav),
            "text": result["text"],
            "language": args.language,
            "duration_s": result["duration_s"],
            "frames": result["frames"],
            "model_load_ms": round(engine.model_load_ms, 1),
            "inference_ms": result["inference_ms"],
            "rtf": round(result["inference_ms"] / 1000.0
                         / result["duration_s"], 4),
            "peak_rss_mb": peak_rss_mb(),
        }
        if args.json:
            print(json.dumps(record, ensure_ascii=False), flush=True)
        else:
            print(f"{record['wav']}: {record['text']}")
            print(f"  duration={record['duration_s']:.2f}s "
                  f"inference={record['inference_ms']:.1f}ms "
                  f"rss={record['peak_rss_mb']}MB", flush=True)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
