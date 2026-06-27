from __future__ import annotations

from bilibili2txt.services.markdown import (
    TranscriptMetadata,
    adjust_heading_levels,
    build_markdown,
    replace_ai_summary,
)


def test_adjust_heading_levels():
    # Test case 1: highest heading is H1, shift by +2
    summary = "# Title\n## Subtitle\n### Sub-subtitle\nSome text"
    expected = "### Title\n#### Subtitle\n##### Sub-subtitle\nSome text"
    assert adjust_heading_levels(summary) == expected

    # Test case 2: highest heading is H2, shift by +1
    summary = "## Title\n### Subtitle"
    expected = "### Title\n#### Subtitle"
    assert adjust_heading_levels(summary) == expected

    # Test case 3: highest heading is H3, shift by 0
    summary = "### Title\n#### Subtitle"
    expected = "### Title\n#### Subtitle"
    assert adjust_heading_levels(summary) == expected

    # Test case 4: highest heading is H4, shift by -1
    summary = "#### Title\n##### Subtitle"
    expected = "### Title\n#### Subtitle"
    assert adjust_heading_levels(summary) == expected

    # Test case 5: no headings
    summary = "Some plain text\nWith no headers"
    assert adjust_heading_levels(summary) == summary

    # Test case 6: preserving hashes that are part of text and not headings
    summary = "#Title\n##Title"
    assert adjust_heading_levels(summary) == summary

    # Test case 7: check tabs and multiple spaces normalization
    summary = "##\tTitle\n###   Subtitle"
    expected = "### Title\n#### Subtitle"
    assert adjust_heading_levels(summary) == expected


def test_build_markdown_adjusts_headings():
    meta = TranscriptMetadata(
        filename="test.text",
        timestamp="2026-06-16_10-00-00",
        up_name="UP主",
        title="测试标题",
        bvid="BV1abc",
        date_folder="2026-06-16",
        formatted_time="2026-06-16 10:00:00",
    )
    summary = "# AI 总结标题\n## 内容一"
    transcript = "这里是文稿"
    content = build_markdown(meta, transcript, summary, "TestAI")

    # The summary portion should have adjusted headings
    assert "### AI 总结标题" in content
    assert "#### 内容一" in content
    # The main document title should still be H1
    assert content.startswith("# 测试标题")


def test_replace_ai_summary_adjusts_headings():
    existing_content = """# 测试标题

- **UP主**: UP主
- **BVID**: BV1abc
- **视频链接**: <https://www.bilibili.com/video/BV1abc>
- **文件时间**: 2026-06-16 10:00:00

---

## tags



## 总结



## AI总结

> 本总结由 TestAI 生成

### 旧总结

## 视频文稿

这里是文稿
"""
    new_summary = "# 新 AI 总结标题\n## 新内容"
    updated_content = replace_ai_summary(existing_content, new_summary, "TestAI")

    # Verify that the new summary has shifted headings in the updated content
    assert "### 新 AI 总结标题" in updated_content
    assert "#### 新内容" in updated_content
    assert "### 旧总结" not in updated_content
