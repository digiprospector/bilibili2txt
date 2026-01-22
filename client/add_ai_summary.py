from pathlib import Path
import re
import argparse
import sys
# 添加路径
SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))

from ai_utils import get_all_ai_summaries

def generate_and_insert_summary(file_path, content, debug=False):
    """
    提取视频文稿，调用AI生成总结，并插入到文件中。
    """
    transcript_match = re.search(r"^##\s+视频文稿", content, re.MULTILINE)
    if transcript_match:
        print("  -> 正在调用 AI (所有可用 API) 生成总结...")
        transcript = content[transcript_match.end():].strip()
        try:
            summary = get_all_ai_summaries(transcript)
            if summary:
                # 插入到 '## 视频文稿' 之前
                new_content = content[:transcript_match.start()] + f"## AI总结\n\n{summary}\n\n" + content[transcript_match.start():]
                
                if debug:
                    debug_path = file_path.with_name(f"{file_path.stem}_debug{file_path.suffix}")
                    debug_path.write_text(new_content, encoding='utf-8')
                    print(f"  -> [DEBUG] 已保存到新文件: {debug_path}")
                else:
                    file_path.write_text(new_content, encoding='utf-8')
                    print(f"  -> [✅ 已修复] AI总结已添加, {file_path}")
            else:
                print("  -> [⚠️ 失败] AI返回内容为空")
        except Exception as e:
            print(f"  -> [⚠️ 错误] {e}")

def check_markdown_titles(root_dir, debug=False):
    """
    遍历指定目录下的 markdown 文件，检查是否包含 '## AI总结' 二级标题。
    """
    
    root_path = Path(root_dir)
    # 检查目录是否存在
    if not root_path.exists():
        print(f"错误: 找不到目录 '{root_path}'")
        return

    # 正则表达式解释：
    # ^      : 匹配行的开始
    # ##     : 匹配二级标题的标记
    # \s+    : 匹配一个或多个空格
    # AI总结 : 匹配具体的标题文字
    # re.MULTILINE : 让 ^ 能匹配每一行的开始，而不仅仅是字符串的开始
    pattern = re.compile(r"^##\s+AI总结", re.MULTILINE)

    found_files = []
    missing_files = []
    error_files = []

    print(f"正在扫描目录: {root_path} ...\n")

    try:
        found_files_list = []
        for file_path in root_path.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() == '.md':
                found_files_list.append(file_path)

        for file_path in found_files_list:
            try:
                content = file_path.read_text(encoding='utf-8')
                
                if pattern.search(content):
                    print(f"[✅ 包含] {file_path}")
                    found_files.append(file_path)
                else:
                    print(f"[❌ 缺失] {file_path}")
                    missing_files.append(file_path)
                    generate_and_insert_summary(file_path, content, debug=debug)
                    if debug:
                        return
                    
            except UnicodeDecodeError:
                # 尝试使用 GBK 读取，以防是旧的 Windows 文件
                try:
                    content = file_path.read_text(encoding='gbk')
                    if pattern.search(content):
                        print(f"[✅ 包含] {file_path}")
                        found_files.append(file_path)
                    else:
                        print(f"[❌ 缺失] {file_path}")
                        missing_files.append(file_path)
                        generate_and_insert_summary(file_path, content, debug=debug)
                        if debug:
                            return
                except Exception as e:
                    print(f"[⚠️ 错误] 无法读取 {file_path}: {e}")
                    error_files.append(file_path)
            except Exception as e:
                print(f"[⚠️ 错误] 无法读取 {file_path}: {e}")
                error_files.append(file_path)
    except KeyboardInterrupt:
        print("\n[!] 用户强制中断")
        raise

    # 输出统计结果
    print("\n" + "="*30)
    print("扫描统计结果")
    print("="*30)
    print(f"总扫描文件数: {len(found_files) + len(missing_files) + len(error_files)}")
    print(f"包含 'AI总结': {len(found_files)}")
    print(f"缺失 'AI总结': {len(missing_files)}")
    if error_files:
        print(f"读取错误文件: {len(error_files)}")

    # 如果需要，可以在这里将缺失的文件列表写入日志
    # if missing_files:
    #     with open("missing_summary.log", "w", encoding="utf-8") as log:
    #         log.write("\n".join(missing_files))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="检查并添加AI总结")
    parser.add_argument("-d", "--debug", action="store_true", help="调试模式：只处理一个文件且不覆盖原文件")
    args = parser.parse_args()

    # 定义目标目录
    TARGET_DIR = Path("data") / "markdown"
    
    check_markdown_titles(TARGET_DIR, debug=args.debug)
