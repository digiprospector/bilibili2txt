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
    s, ms_part = divmod(ms, 1000)
    m, s_part = divmod(s, 60)
    h, m_part = divmod(m, 60)
    return f"{h:02d}:{m_part:02d}:{s_part:02d},{ms_part:03d}"


def format_txt_time(ms: int) -> str:
    s, ms_part = divmod(ms, 1000)
    m, s_part = divmod(s, 60)
    h, m_part = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m_part:02d}:{s_part:02d}.{ms_part:03d}"
    else:
        return f"{m_part:02d}:{s_part:02d}.{ms_part:03d}"


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


def split_into_sentences(
    text: str,
    start_ms: int,
    end_ms: int,
    char_timestamps: list[list[int]] | None = None
) -> list[dict]:
    delimiters = {'。', '？', '！', '；', '\n'}
    segments = []
    
    ts_idx = 0
    char_times = []
    for char in text:
        if (
            char_timestamps and 
            ts_idx < len(char_timestamps) and 
            not char.isspace() and 
            char not in delimiters and 
            char not in {'，', ',', '.', '?', '!', ';', ':'}
        ):
            char_times.append(char_timestamps[ts_idx])
            ts_idx += 1
        else:
            char_times.append(None)
            
    current_sentence = []
    current_times = []
    
    def add_current():
        if not current_sentence:
            return
        s_text = "".join(current_sentence).strip()
        if not s_text:
            return
        valid_times = [t for t in current_times if t is not None]
        if valid_times:
            s_start = valid_times[0][0]
            s_end = valid_times[-1][1]
        else:
            s_start = start_ms
            s_end = end_ms
        segments.append({
            "text": s_text,
            "start": s_start,
            "end": s_end
        })
        current_sentence.clear()
        current_times.clear()

    for idx, char in enumerate(text):
        current_sentence.append(char)
        current_times.append(char_times[idx])
        
        is_delimiter = char in delimiters
        is_long_comma = (char == '，' or char == ',') and len(current_sentence) > 30
        
        if is_delimiter or is_long_comma:
            add_current()
            
    add_current()
    
    if len(segments) > 1:
        needs_proportion = False
        if not char_timestamps:
            needs_proportion = True
        else:
            starts = {seg["start"] for seg in segments}
            ends = {seg["end"] for seg in segments}
            if len(starts) == 1 and len(ends) == 1:
                needs_proportion = True
                
        if needs_proportion:
            total_chars = sum(len(seg["text"]) for seg in segments)
            if total_chars > 0:
                current_ms = start_ms
                duration = end_ms - start_ms
                for idx, seg in enumerate(segments):
                    seg_len = len(seg["text"])
                    if idx == len(segments) - 1:
                        seg["start"] = current_ms
                        seg["end"] = end_ms
                    else:
                        seg_dur = int(duration * (seg_len / total_chars))
                        seg["start"] = current_ms
                        seg["end"] = current_ms + seg_dur
                        current_ms = seg["end"]
                        
    return segments


class Transcriber:
    def __init__(
        self,
        faster_whisper_path: Path,
        temp_dir: Path,
        logger: logging.Logger,
        *,
        engine: str = "whisper",
        funasr_config: dict | None = None
    ):
        self.faster_whisper_path = faster_whisper_path
        self.temp_dir = temp_dir
        self.logger = logger
        self.engine = engine
        self.funasr_config = funasr_config or {}

        # FunASR parameters
        self.drive_model_path = self.funasr_config.get("drive_model_path", "/content/drive/MyDrive/modelscope_cache")
        self.asr_model = self.funasr_config.get("asr_model", "speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch")
        self.vad_model = self.funasr_config.get("vad_model", "speech_fsmn_vad_zh-cn-16k-common-pytorch")
        self.punc_model = self.funasr_config.get("punc_model", "punc_ct-transformer_cn-en-common-vocab471067-large")

    def _resolve_model_path(self, model_name: str) -> str:
        if not model_name:
            return ""
        if model_name.startswith("/") or ":" in model_name:
            return model_name
        return f"{self.drive_model_path}/iic/{model_name}"

    def transcribe_audio_files(self, task: Task, audio_files: list[Path]) -> Path:
        if not audio_files:
            raise TranscriptionError("no audio files available")
        if self.engine == "whisper":
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
        if self.engine == "funasr":
            self._transcribe_one_funasr(audio_file)
        else:
            self._transcribe_one_whisper(audio_file)

    def _transcribe_one_whisper(self, audio_file: Path) -> None:
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

    def _get_funasr_model(self):
        if not hasattr(self, "_funasr_model"):
            import os
            from funasr import AutoModel
            
            os.environ['MODELSCOPE_CACHE'] = str(self.drive_model_path)
            os.environ['MODELSCOPE_DISABLE_REMOTE'] = "1"
            
            asr_path = self._resolve_model_path(self.asr_model)
            vad_path = self._resolve_model_path(self.vad_model)
            punc_path = self._resolve_model_path(self.punc_model)
            
            self.logger.info("初始化 FunASR 模型，缓存目录：%s", self.drive_model_path)
            self.logger.info("ASR 模型路径: %s", asr_path)
            self.logger.info("VAD 模型路径: %s", vad_path)
            self.logger.info("Punc 模型路径: %s", punc_path)
            
            self._funasr_model = AutoModel(
                disable_pbar=True,
                disable_update=True,
                model=asr_path,
                vad_model=vad_path,
                vad_kwargs={"max_single_segment_time": 30000},
                punc_model=punc_path,
            )
        return self._funasr_model

    def _transcribe_one_funasr(self, audio_file: Path) -> None:
        self.logger.info("运行 FunASR 识别：%s", audio_file)
        model = self._get_funasr_model()
        
        res = model.generate(
            input=str(audio_file),
            batch_size_s=300,
            return_sentence=True
        )
        
        if not res:
            raise TranscriptionError("FunASR 识别返回空结果")
            
        sentence_info = res[0].get("sentence_info", [])
        
        # 如果 sentence_info 为空但有文本，则退化为单段识别
        if not sentence_info and res[0].get("text"):
            sentence_info = [{
                "text": res[0]["text"],
                "start": 0,
                "end": int(probe_duration_s(audio_file) * 1000)
            }]
            
        # 对 sentence_info 中的每一段进行更细粒度的标点符号切分
        char_timestamps = res[0].get("timestamp")
        refined_sentence_info = []
        for seg in sentence_info:
            text = seg.get("text", "").strip()
            start = seg.get("start", 0)
            end = seg.get("end", 0)
            
            has_delimiters = any(d in text for d in {'。', '？', '！', '；', '\n'})
            if has_delimiters or (end - start > 30000):
                seg_ts = None
                if char_timestamps:
                    seg_ts = [ts for ts in char_timestamps if start <= ts[0] <= end]
                sub_segs = split_into_sentences(text, start, end, seg_ts)
                refined_sentence_info.extend(sub_segs)
            else:
                refined_sentence_info.append(seg)
        sentence_info = refined_sentence_info
            
        # 1. 写入 .text 文件（纯文本，每行一句）
        text_lines = [seg.get("text", "").strip() for seg in sentence_info]
        text_lines = [line for line in text_lines if line]
        text_content = "\n".join(text_lines)
        audio_file.with_suffix(".text").write_text(text_content, encoding="utf-8")
        
        # 2. 写入 .txt 文件（带时间戳标记：[MM:SS.mmm --> MM:SS.mmm]  文本）
        txt_lines = []
        for seg in sentence_info:
            start_ms = int(seg.get("start", 0))
            end_ms = int(seg.get("end", 0))
            text = seg.get("text", "").strip()
            if not text:
                continue
            start_str = format_txt_time(start_ms)
            end_str = format_txt_time(end_ms)
            txt_lines.append(f"[{start_str} --> {end_str}]  {text}")
        txt_content = "\n".join(txt_lines)
        audio_file.with_suffix(".txt").write_text(txt_content, encoding="utf-8")
        
        # 3. 写入 .srt 文件（标准 SRT 格式）
        cues = []
        for idx, seg in enumerate(sentence_info, start=1):
            start_ms = int(seg.get("start", 0))
            end_ms = int(seg.get("end", 0))
            text = seg.get("text", "").strip()
            cues.append(Cue(index=idx, start_ms=start_ms, end_ms=end_ms, text=text))
        srt_content = render_srt(cues)
        audio_file.with_suffix(".srt").write_text(srt_content, encoding="utf-8")
        
        self.logger.info("FunASR 识别完成，已成功生成 .text, .txt, .srt 文件")


