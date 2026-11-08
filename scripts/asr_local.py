#!/usr/bin/env python3
"""本地中文语音识别（FunASR Paraformer，CPU）。

用法:
    env -u PYTHONPATH work/asr-venv/bin/python scripts/asr_local.py work/mic-*.wav

首次运行会把模型下载到 work/models（ModelScope 缓存，约 889 MB），
之后复用缓存。音频只在本机读取，不上传网络。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import wave
from pathlib import Path

DEFAULT_MODEL = "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
DEFAULT_CACHE = Path(__file__).resolve().parent.parent / "work" / "models"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用 FunASR Paraformer 在本地 CPU 上识别中文 WAV（16kHz/16bit/单声道）。"
    )
    parser.add_argument("wav", type=Path, help="待识别 WAV 路径")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"FunASR/ModelScope 模型 ID（默认: {DEFAULT_MODEL}）",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE,
        help=f"ModelScope 模型缓存目录（默认: {DEFAULT_CACHE}）",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="推理设备（默认: cpu；本机无 NVIDIA GPU）",
    )
    return parser.parse_args()


def inspect_wav(path: Path) -> float:
    """校验 WAV 格式并返回时长（秒）；失败时抛出 ValueError。"""
    if not path.is_file():
        raise ValueError(f"文件不存在: {path}")
    try:
        with wave.open(str(path), "rb") as wav:
            rate = wav.getframerate()
            width = wav.getsampwidth()
            channels = wav.getnchannels()
            frames = wav.getnframes()
            comptype = wav.getcomptype()
    except wave.Error as exc:
        raise ValueError(f"无法解析为 WAV: {path} ({exc})") from exc

    if comptype != "NONE":
        raise ValueError(f"不支持的 WAV 压缩格式: {comptype}")
    if rate != 16000:
        raise ValueError(f"采样率应为 16000 Hz，实际 {rate} Hz")
    if width != 2:
        raise ValueError(f"位深应为 16 bit，实际 {width * 8} bit")
    if channels != 1:
        raise ValueError(f"声道数应为 1（单声道），实际 {channels}")
    if frames == 0:
        raise ValueError("WAV 不含音频帧")

    duration = frames / float(rate)
    print(f"音频: {path}")
    print(f"格式: {rate} Hz, {width * 8} bit, 单声道, {frames} 帧")
    print(f"时长: {duration:.3f} s")
    return duration


def main() -> int:
    args = parse_args()

    try:
        duration = inspect_wav(args.wav)
    except ValueError as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return 1

    args.cache_dir = args.cache_dir.resolve()
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MODELSCOPE_CACHE"] = str(args.cache_dir)

    try:
        from funasr import AutoModel
    except Exception as exc:  # pragma: no cover - 环境损坏时给出明确原因
        print(f"ERR: 无法导入 funasr: {exc}", file=sys.stderr)
        return 1

    print(f"模型: {args.model}")
    print(f"设备: {args.device}")
    print(f"缓存: {args.cache_dir}")
    print("首次运行需下载模型权重，请耐心等待……" if not any(args.cache_dir.iterdir()) else "使用本地模型缓存")

    try:
        load_start = time.perf_counter()
        model = AutoModel(
            model=args.model,
            device=args.device,
            disable_update=True,
            disable_pbar=True,
        )
        load_s = time.perf_counter() - load_start
    except Exception as exc:
        print(f"ERR: 模型加载失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    try:
        cpu_before = os.times()
        infer_start = time.perf_counter()
        results = model.generate(input=str(args.wav), batch_size_s=300)
        infer_s = time.perf_counter() - infer_start
        cpu_after = os.times()
    except Exception as exc:
        print(f"ERR: 识别失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    text = ""
    if results and isinstance(results, list):
        text = str(results[0].get("text", "")).strip()

    rtf = infer_s / duration if duration > 0 else float("nan")
    peak_rss_mb = _peak_rss_mb()
    cpu_user = cpu_after.user - cpu_before.user
    cpu_sys = cpu_after.system - cpu_before.system
    cpu_total = cpu_user + cpu_sys
    avg_cores = cpu_total / infer_s if infer_s > 0 else float("nan")

    print(f"模型加载: {load_s:.2f} s")
    print(f"推理耗时: {infer_s:.2f} s")
    print(f"RTF: {rtf:.3f}（推理耗时/音频时长）")
    print(f"CPU 时间: user {cpu_user:.2f} s + sys {cpu_sys:.2f} s，平均 {avg_cores:.2f} 核")
    print(f"峰值内存: {peak_rss_mb:.1f} MB (RSS)")
    print(f"识别文本: {text if text else '(空)'}")

    if not text:
        print("ERR: 未识别出任何文本", file=sys.stderr)
        return 1
    return 0


def _peak_rss_mb() -> float:
    try:
        import resource
    except ImportError:  # pragma: no cover - 非 Linux
        return float("nan")
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


if __name__ == "__main__":
    sys.exit(main())
