"""
日志清理工具 - 自动清理旧的应用日志文件以释放磁盘空间
"""
import os
import time
from pathlib import Path
from typing import List, Optional
from langchain_core.tools import tool

# 应用列表，参考 main.py 中的配置
APP_LIST = [
    "bms-server",
    "bms-server_1",
    "bms-server_2",
    "devices-server",
    "member-server",
    "push-server",
    "system-server",
    "things-server",
    "gateway-server",
    "mqtt-server",
    "report-server",
    "trade-server",
    "tcp1801-server",
    "infra-server",
    "protocol-message-bms",
    "protocol-message-tcp1801"
]

@tool
def clean_app_logs(log_directory: str, max_files_to_delete: int = 100) -> str:
    """
    清理应用相关的历史日志文件（.log 或 .log.gz）。
    当磁盘空间不足时，Agent 应调用此工具。
    工具会识别应用日志的滚动备份文件，并按修改时间从早到晚进行清理。
    
    Args:
        log_directory: 日志文件所在的绝对路径
        max_files_to_delete: 单次清理的最大文件数，默认为 100
    """
    import json
    
    # 处理 Agent 可能传递的 JSON 格式参数或带引号的字符串
    if isinstance(log_directory, str):
        log_directory = log_directory.strip().strip("'").strip('"')
        try:
            parsed = json.loads(log_directory)
            if isinstance(parsed, dict) and 'log_directory' in parsed:
                log_directory = parsed['log_directory']
            elif isinstance(parsed, str):
                log_directory = parsed
        except (json.JSONDecodeError, TypeError):
            pass
            
    # 再次清理引号和处理路径分隔符
    log_directory = str(log_directory).strip().strip("'").strip('"')
    log_directory = log_directory.replace('\\\\', '\\')
    
    log_path = Path(log_directory)
    if not log_path.exists():
        return f"错误：日志目录不存在 - {log_directory}"

    files_to_clean = []
    
    # 遍历目录下的所有文件
    for file in log_path.iterdir():
        if not file.is_file():
            continue
            
        filename = file.name
        
        # 检查是否属于应用日志前缀
        is_app_log = any(filename.startswith(app) for app in APP_LIST)
        if not is_app_log:
            continue
            
        # 识别是否为备份/滚动日志文件
        # 活跃日志通常是 app.log，备份日志通常包含日期或数字后缀，如 app.log.2026-01-01.log 或 app.log.gz
        is_backup = False
        
        # 1. 包含 .gz 后缀
        if filename.endswith(".gz"):
            is_backup = True
        # 2. 包含日期模式或被重命名的旧日志（如 bms-server.log.2025-12-29.log）
        # 简单判断逻辑：如果文件名比 "app.log" 长，且包含 ".log." 或以数字结尾
        elif ".log." in filename or (filename.endswith(".log") and len(filename) > max(len(app + ".log") for app in APP_LIST)):
            is_backup = True
            
        if is_backup:
            # 记录文件路径和最后修改时间
            files_to_clean.append({
                'path': file,
                'mtime': file.stat().st_mtime,
                'size_mb': file.stat().st_size / (1024 * 1024)
            })

    if not files_to_clean:
        return f"信息：在 {log_directory} 中未找到可清理的备份日志文件。"

    # 按修改时间从旧到新排序（mtime 越小越旧）
    files_to_clean.sort(key=lambda x: x['mtime'])
    
    # 执行删除
    deleted_count = 0
    freed_space_mb = 0
    deleted_files = []
    
    for file_info in files_to_clean[:max_files_to_delete]:
        try:
            file_size = file_info['size_mb']
            file_info['path'].unlink()
            deleted_count += 1
            freed_space_mb += file_size
            deleted_files.append(file_info['path'].name)
        except Exception as e:
            print(f"删除文件 {file_info['path'].name} 失败: {e}")

    summary = [
        f"成功清理了 {deleted_count} 个旧日志文件",
        f"释放空间: {freed_space_mb:.2f} MB",
        f"清理的文件列表:",
    ]
    summary.extend([f"  - {f}" for f in deleted_files])
    
    return "\n".join(summary)
