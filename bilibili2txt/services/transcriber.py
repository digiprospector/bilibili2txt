from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..models import Task


class TranscriptionError(RuntimeError):
    pass


@dataclass
class Cue:
    index: int
    start_ms: int
    end_ms: int
    text: str


def parse_srt_time(t_str: str) -> int:
    t_str = t_str.replace(".", ",")
    parts = t_str.split(",")
    ms = int(parts[1].strip()) if len(parts) > 1 else 0
    subparts = parts[0].split(":")
    h = int(subparts[0].strip())
    m = int(subparts[1].strip())
    s = int(subparts[2].strip())
    return ((h * 3600 + m * 60 + s) * 1000) + ms


def format_srt_time(ms: int) -> str:
    s, m = divmod(ms // 1000, 60)
    h, m = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s%60:02d},{ms%1000:03d}"


def parse_srt(content: str) -> list[Cue]:
    blocks = content.replace("\r\n", "\n").replace("\r", "\n").strip().split("\n\n")
    cues = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) < 2:
            continue
        try:
            if "-->" in lines[1]:
                index = int(lines[0])
                timing = lines[1]
                text = "\n".join(lines[2:])
            elif "-->" in lines[0]:
                index = len(cues) + 1
                timing = lines[0]
                text = "\n".join(lines[1:])
            else:
                continue
            start_str, end_str = timing.split("-->")
            start_ms = parse_srt_time(start_str)
            end_ms = parse_srt_time(end_str)
            cues.append(Cue(index, start_ms, end_ms, text))
        except Exception:
            continue
    return cues


def render_srt(cues: list[Cue]) -> str:
    lines = []
    for idx, cue in enumerate(cues, start=1):
        lines.append(str(idx))
        lines.append(f"{format_srt_time(cue.start_ms)} --> {format_srt_time(cue.end_ms)}")
        lines.append(cue.text)
        lines.append("")
    return "\n".join(lines)


def probe_duration_s(media_file: Path) -> float:
    command = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(media_file)
    ]
    try:
        res = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="ignore", check=True)
        return float(res.stdout.strip())
    except Exception as exc:
        raise TranscriptionError(f"Failed to probe audio duration for {media_file}: {exc}") from exc


def detect_silences(audio_file: Path) -> list[tuple[float, float]]:
    command = [
        "ffmpeg",
        "-i", str(audio_file),
        "-af", "silencedetect=noise=-35dB:d=0.5",
        "-f", "null",
        "-"
    ]
    res = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    
    silences = []
    current_start = None
    for line in res.stderr.splitlines():
        if "silence_start:" in line:
            parts = line.split("silence_start:")
            try:
                current_start = float(parts[1].split()[0])
            except (ValueError, IndexError):
                pass
        elif "silence_end:" in line:
            parts = line.split("silence_end:")
            try:
                end = float(parts[1].split()[0])
                if current_start is not None:
                    silences.append((current_start, end))
                    current_start = None
            except (ValueError, IndexError):
                pass
    return silences


def cut_audio(source: Path, target: Path, start_s: float, end_s: float) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-ss", f"{start_s:.3f}",
        "-to", f"{end_s:.3f}",
        "-i", str(source),
        "-c:a", "copy",
        str(target)
    ]
    try:
        subprocess.run(command, capture_output=True, check=True)
    except subprocess.CalledProcessError:
        fallback_command = [
            "ffmpeg",
            "-y",
            "-ss", f"{start_s:.3f}",
            "-to", f"{end_s:.3f}",
            "-i", str(source),
            str(target)
        ]
        subprocess.run(fallback_command, check=True)


class Transcriber:
    def __init__(self, faster_whisper_path: Path, temp_dir: Path, logger: logging.Logger):
        self.faster_whisper_path = faster_whisper_path
        self.temp_dir = temp_dir
        self.logger = logger

    def transcribe_audio_files(self, task: Task, audio_files: list[Path]) -> Path:
        if not audio_files:
            raise TranscriptionError("no audio files available")
        if not self.faster_whisper_path.exists():
            raise TranscriptionError(f"faster-whisper path does not exist: {self.faster_whisper_path}")

        result_dir = self.temp_dir / "server_results" / task.task_id
        if result_dir.exists():
            shutil.rmtree(result_dir)
        result_dir.mkdir(parents=True, exist_ok=True)

        chunk_threshold_s = 1800.0  # 30分钟阈值

        for index, audio_file in enumerate(audio_files, start=1):
            duration_s = probe_duration_s(audio_file)
            part_suffix = f"_{index}" if len(audio_files) > 1 else ""

            if duration_s > chunk_threshold_s:
                self.logger.info("音频文件 %s 时长为 %.2f 秒，超过 30 分钟，将进行分片识别...", audio_file.name, duration_s)
                chunks = self._split_audio(audio_file, duration_s, chunk_threshold_s)
                
                chunk_srts = []
                chunk_txts = []
                chunk_texts = []

                for chunk_idx, (chunk_file, start_s) in enumerate(chunks, start=1):
                    chunk_srt = chunk_file.with_suffix(".srt")
                    chunk_txt = chunk_file.with_suffix(".txt")
                    chunk_text = chunk_file.with_suffix(".text")

                    if chunk_srt.exists() and chunk_txt.exists() and chunk_text.exists():
                        self.logger.info("分片 %d 字幕已缓存，跳过识别：%s", chunk_idx, chunk_file.name)
                    else:
                        self.logger.info("识别分片 %d/%d：%s", chunk_idx, len(chunks), chunk_file.name)
                        self._transcribe_one(chunk_file)

                    chunk_srts.append((chunk_srt, start_s))
                    chunk_txts.append(chunk_txt)
                    chunk_texts.append(chunk_text)

                merged_srt_path = result_dir / f"transcript{part_suffix}.srt"
                merged_txt_path = result_dir / f"transcript{part_suffix}.txt"
                merged_text_path = result_dir / f"transcript{part_suffix}.text"

                self._merge_srts(chunk_srts, merged_srt_path)
                self._merge_txts(chunk_txts, merged_txt_path)
                self._merge_txts(chunk_texts, merged_text_path)
            else:
                self.logger.info("直接识别完整音频文件：%s", audio_file.name)
                self._transcribe_one(audio_file)
                for suffix in (".text", ".txt", ".srt"):
                    source = audio_file.with_suffix(suffix)
                    if source.exists():
                        target = result_dir / f"transcript{part_suffix}{suffix}"
                        shutil.copy2(source, target)
                        self.logger.info("已保存转录文本：%s", target)

        task.write_json(result_dir / "task.json")
        return result_dir

    def _split_audio(self, audio_file: Path, duration_s: float, chunk_len_s: float) -> list[tuple[Path, float]]:
        self.logger.info("使用 ffmpeg 进行静音检测...")
        silences = detect_silences(audio_file)
        self.logger.info("共检测到 %d 个静音区间", len(silences))

        split_points = []
        start_s = 0.0
        search_window_s = 300.0  # 搜索窗口前后 5 分钟
        min_chunk_s = 60.0       # 最小分片 1 分钟

        while duration_s - start_s > chunk_len_s:
            target_split = start_s + chunk_len_s
            lower_s = max(start_s + min_chunk_s, target_split - search_window_s)
            upper_s = min(duration_s, target_split + search_window_s)

            candidates = []
            for s_start, s_end in silences:
                mid = (s_start + s_end) / 2.0
                if lower_s <= mid <= upper_s:
                    candidates.append(mid)

            if candidates:
                split_s = min(candidates, key=lambda c: abs(c - target_split))
                self.logger.info("在区间 [%.1fs - %.1fs] 找到最佳静音切分点：%.1fs", lower_s, upper_s, split_s)
            else:
                split_s = min(target_split, duration_s)
                self.logger.info("在区间 [%.1fs - %.1fs] 未找到静音点，执行硬切分：%.1fs", lower_s, upper_s, split_s)

            split_points.append((start_s, split_s))
            start_s = split_s

        split_points.append((start_s, duration_s))

        chunk_dir = self.temp_dir / "chunks" / audio_file.stem
        chunk_dir.mkdir(parents=True, exist_ok=True)
        
        chunks = []
        for idx, (s_start, s_end) in enumerate(split_points, start=1):
            chunk_file = chunk_dir / f"{audio_file.stem}.chunk{idx:03d}{audio_file.suffix}"
            if not chunk_file.exists():
                self.logger.info("裁剪分片 %d: %.1fs -> %.1fs", idx, s_start, s_end)
                cut_audio(audio_file, chunk_file, s_start, s_end)
            else:
                self.logger.info("分片音频已缓存：%s", chunk_file.name)
            chunks.append((chunk_file, s_start))

        return chunks

    def _merge_srts(self, chunk_srts: list[tuple[Path, float]], output_path: Path) -> None:
        merged_cues = []
        for srt_path, start_s in chunk_srts:
            if not srt_path.exists():
                self.logger.warning("分片字幕不存在，跳过合并：%s", srt_path.name)
                continue
            
            content = srt_path.read_text(encoding="utf-8-sig", errors="ignore")
            cues = parse_srt(content)
            offset_ms = int(start_s * 1000)
            
            for cue in cues:
                merged_cues.append(
                    Cue(
                        index=0,
                        start_ms=cue.start_ms + offset_ms,
                        end_ms=cue.end_ms + offset_ms,
                        text=cue.text
                    )
                )

        merged_cues.sort(key=lambda c: c.start_ms)
        output_content = render_srt(merged_cues)
        output_path.write_text(output_content, encoding="utf-8")
        self.logger.info("已生成合并后的字幕文件：%s", output_path)

    def _merge_txts(self, chunk_txts: list[Path], output_path: Path) -> None:
        txt_contents = []
        for txt_path in chunk_txts:
            if not txt_path.exists():
                continue
            txt_contents.append(txt_path.read_text(encoding="utf-8", errors="ignore").strip())
        
        output_path.write_text("\n\n".join(txt_contents), encoding="utf-8")
        self.logger.info("已生成合并后的文本文件：%s", output_path)

    def _transcribe_one(self, audio_file: Path) -> None:
        self.logger.info("运行 faster-whisper：%s", audio_file)
        command = [
            str(self.faster_whisper_path),
            str(audio_file),
            "-m",
            "large-v2",
            "-l",
            "Chinese",
            "--vad_method",
            "pyannote_v3",
            "--ff_vocal_extract",
            "mdx_kim2",
            "--sentence",
            "-v",
            "true",
            "-o",
            "source",
            "-f",
            "txt",
            "srt",
            "text",
        ]
        subprocess.run(command, check=True)


