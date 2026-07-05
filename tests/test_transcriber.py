import logging
from pathlib import Path
import pytest

from bilibili2txt.services.transcriber import (
    Cue,
    parse_srt_time,
    format_srt_time,
    parse_srt,
    render_srt,
    Transcriber,
)
from bilibili2txt.models import Task


def test_srt_time_conversion():
    assert parse_srt_time("00:00:00,000") == 0
    assert parse_srt_time("00:01:30,500") == 90500
    assert parse_srt_time("01:00:02.123") == 3602123

    assert format_srt_time(0) == "00:00:00,000"
    assert format_srt_time(90500) == "00:01:30,500"
    assert format_srt_time(3602123) == "01:00:02,123"


def test_srt_parsing_and_rendering():
    content = """1
00:00:01,000 --> 00:00:05,500
Hello World!

2
00:00:06,000 --> 00:00:10,000
Second segment
"""
    cues = parse_srt(content)
    assert len(cues) == 2
    assert cues[0].index == 1
    assert cues[0].start_ms == 1000
    assert cues[0].end_ms == 5500
    assert cues[0].text == "Hello World!"

    assert cues[1].index == 2
    assert cues[1].start_ms == 6000
    assert cues[1].end_ms == 10000
    assert cues[1].text == "Second segment"

    rendered = render_srt(cues)
    assert "1\n00:00:01,000 --> 00:00:05,500\nHello World!\n" in rendered
    assert "2\n00:00:06,000 --> 00:00:10,000\nSecond segment\n" in rendered


def test_merge_srts(tmp_path):
    srt1 = tmp_path / "chunk1.srt"
    srt1.write_text("""1
00:00:01,000 --> 00:00:04,000
First chunk subtitle
""", encoding="utf-8")

    srt2 = tmp_path / "chunk2.srt"
    srt2.write_text("""1
00:00:01,500 --> 00:00:03,000
Second chunk subtitle
""", encoding="utf-8")

    transcriber = Transcriber(Path("dummy"), tmp_path, logging.getLogger("test"))
    
    # srt1 starts at 0.0s, srt2 starts at 10.0s
    chunk_srts = [
        (srt1, 0.0),
        (srt2, 10.0),
    ]
    output_srt = tmp_path / "merged.srt"
    transcriber._merge_srts(chunk_srts, output_srt)

    cues = parse_srt(output_srt.read_text(encoding="utf-8"))
    assert len(cues) == 2
    assert cues[0].start_ms == 1000
    assert cues[0].end_ms == 4000
    assert cues[0].text == "First chunk subtitle"
    
    # 10s offset + 1.5s = 11.5s = 11500ms
    assert cues[1].start_ms == 11500
    assert cues[1].end_ms == 13000
    assert cues[1].text == "Second chunk subtitle"


def test_merge_txts(tmp_path):
    txt1 = tmp_path / "chunk1.txt"
    txt1.write_text("Hello from chunk 1.", encoding="utf-8")

    txt2 = tmp_path / "chunk2.txt"
    txt2.write_text("Hello from chunk 2.", encoding="utf-8")

    transcriber = Transcriber(Path("dummy"), tmp_path, logging.getLogger("test"))
    output_txt = tmp_path / "merged.txt"
    transcriber._merge_txts([txt1, txt2], output_txt)

    merged_content = output_txt.read_text(encoding="utf-8")
    assert merged_content == "Hello from chunk 1.\n\nHello from chunk 2."


def test_split_audio_planning(tmp_path, monkeypatch):
    # Mock detect_silences to return some silences
    # Audio duration is 4000s (longer than 1800s threshold)
    # We want chunk length of 1800s
    # Target split point for chunk 1 is 1800s.
    # The search window is [1800 - 300, 1800 + 300] = [1500, 2100].
    # We provide a silence at 1700s.
    # The split should happen at 1700s.
    
    def mock_detect_silences(audio_file):
        return [
            (1699.0, 1701.0),  # Midpoint is 1700.0
            (3500.0, 3502.0),
        ]
        
    def mock_cut_audio(source, target, start, end):
        target.touch()

    monkeypatch.setattr("bilibili2txt.services.transcriber.detect_silences", mock_detect_silences)
    monkeypatch.setattr("bilibili2txt.services.transcriber.cut_audio", mock_cut_audio)

    transcriber = Transcriber(Path("dummy"), tmp_path, logging.getLogger("test"))
    
    audio_file = tmp_path / "audio.mp3"
    audio_file.touch()

    chunks = transcriber._split_audio(audio_file, 4000.0, 1800.0)
    
    # Should split into:
    # 1. 0.0 -> 1700.0
    # 2. 1700.0 -> 3501.0
    # 3. 3501.0 -> 4000.0
    assert len(chunks) == 3
    assert chunks[0][1] == 0.0
    assert chunks[1][1] == 1700.0
    assert chunks[2][1] == 3501.0


def test_split_into_sentences():
    from bilibili2txt.services.transcriber import split_into_sentences

    # Test 1: splitting without timestamps
    text = "欢迎大家。我们开始直播。"
    segs = split_into_sentences(text, 0, 10000)
    assert len(segs) == 2
    assert segs[0]["text"] == "欢迎大家。"
    assert segs[0]["start"] == 0
    assert segs[0]["end"] == 4166
    assert segs[1]["text"] == "我们开始直播。"
    assert segs[1]["start"] == 4166
    assert segs[1]["end"] == 10000

    # Test 2: splitting with character timestamps
    text_with_ts = "欢迎大家。我们开始。"
    # 8 non-punctuation/non-space characters
    # '欢', '迎', '大', '家', '我', '们', '开', '始'
    char_timestamps = [
        [100, 200],   # 欢
        [200, 300],   # 迎
        [300, 400],   # 大
        [400, 550],   # 家
        [1000, 1100], # 我
        [1100, 1200], # 们
        [1200, 1300], # 开
        [1300, 1400], # 始
    ]
    segs_ts = split_into_sentences(text_with_ts, 0, 2000, char_timestamps)
    assert len(segs_ts) == 2
    assert segs_ts[0]["text"] == "欢迎大家。"
    assert segs_ts[0]["start"] == 100
    assert segs_ts[0]["end"] == 550
    assert segs_ts[1]["text"] == "我们开始。"
    assert segs_ts[1]["start"] == 1000
    assert segs_ts[1]["end"] == 1400
