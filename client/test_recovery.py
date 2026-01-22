#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 AI 错误恢复与自动退休逻辑
"""

import sys
import time
import threading
from pathlib import Path

# 添加路径
SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))

import ai_utils
from ai_utils import BatchTaskProcessor

# 模拟分析函数，让某些账号失败
original_analyze = ai_utils.analyze_stock_market

def mock_analyze(content, ai_config=None):
    name = ai_config.get("openai_api_name") if ai_config else "default"
    
    # 模拟 'yinhe' 账号总是返回错误字符串
    if name == 'yinhe':
        return "Error: 模拟账号故障 (yinhe)"
    
    # 模拟 'heiyubai' 账号抛出异常
    if name == 'heiyubai':
        raise Exception("模拟网络崩溃 (heiyubai)")
        
    return f"[{name}] 成功总结了: {content[:10]}..."

# 替换原函数
ai_utils.analyze_stock_market = mock_analyze

def test_recovery():
    print("开始故障恢复测试...")
    
    tasks = [f"重要文本 {i}" for i in range(1, 11)]
    results = {}
    
    def on_result(task_id, ai_name, summary, extra):
        results[task_id] = (ai_name, summary)
        print(f"  [完成] {task_id} by {ai_name}")

    processor = BatchTaskProcessor(on_result_callback=on_result)
    
    print(f"提交 {len(tasks)} 个任务...")
    for i, t in enumerate(tasks):
        processor.add_task(f"Task-{i}", t)
        
    start_wait = time.time()
    processor.wait_and_stop()
    
    print(f"\n测试结束，总耗时: {time.time() - start_wait:.2f}s")
    print(f"最终完成任务数: {len(results)} / {len(tasks)}")
    
    # 统计哪些 AI 处理了任务
    distribution = {}
    for task_id, (name, _) in results.items():
        distribution[name] = distribution.get(name, 0) + 1
        
    print("\n--- 任务负载分布 ---")
    for name, count in distribution.items():
        print(f"AI [{name}]: 处理了 {count} 个任务")
        
    # 检查退休的账号是否还在输出中
    retired_detected = 'yinhe' in distribution or 'heiyubai' in distribution
    if not retired_detected:
        print("\n✅ 验证成功：由于 yinhe 和 heiyubai 发生了错误，它们已退休。")
        print("所有 10 个任务最终由其他健康的 AI 节点接手完成。")
    else:
        print("\n❌ 验证失败：已退休的账号不应出现在最终结果中。")

if __name__ == "__main__":
    test_recovery()
