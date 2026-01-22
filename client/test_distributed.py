#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试分布式 AI 处理逻辑
"""

import sys
from pathlib import Path

# 添加路径
SCRIPT_DIR = Path(__file__).parent
sys.path.append(str((SCRIPT_DIR.parent / "libs").absolute()))
sys.path.append(str((SCRIPT_DIR.parent / "common").absolute()))

from ai_utils import process_tasks_distributed

def test_distribution():
    print("开始分布式测试...")
    
    # 模拟 10 个简单任务
    test_tasks = [f"测试文本 {i}" for i in range(1, 11)]
    
    print(f"提交 {len(test_tasks)} 个任务到所有可用 AI...")
    
    # 我们使用一个简单的 system_prompt 减少 AI 消耗
    system_prompt = "你是一个测试助手，请简单回复 '收到内容: ' + 我发给你的内容"
    
    results = process_tasks_distributed(test_tasks, system_prompt=system_prompt)
    
    print("\n--- 测试结果 ---")
    ai_usage = {}
    for i, (name, res) in enumerate(results):
        print(f"任务 {i+1} handled by [{name}]: {res[:50]}...")
        ai_usage[name] = ai_usage.get(name, 0) + 1
        
    print("\n--- AI 负载分布 ---")
    for name, count in ai_usage.items():
        print(f"AI [{name}]: 处理了 {count} 个任务")

if __name__ == "__main__":
    test_distribution()
