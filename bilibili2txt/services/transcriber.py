from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from ..models import Task


class TranscriptionError(RuntimeError):
    pass


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

        for index, audio_file in enumerate(audio_files, start=1):
            self._transcribe_one(audio_file)
            part_suffix = f"_{index}" if len(audio_files) > 1 else ""
            for suffix in (".text", ".txt", ".srt"):
                source = audio_file.with_suffix(suffix)
                if source.exists():
                    target = result_dir / f"transcript{part_suffix}{suffix}"
                    shutil.copy2(source, target)
                    self.logger.info("已保存转录文本：%s", target)

        task.write_json(result_dir / "task.json")
        return result_dir

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

