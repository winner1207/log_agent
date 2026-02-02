"""
日志清理工具 - 自动清理旧的应用日志文件以释放磁盘空间
"""
import os
import time
import re
from pathlib import Path
from typing import List, Optional
from langchain_core.tools import tool
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 应用列表，参考 main.py 中的配置
APP_LIST = [
    "bms-server",
    "bms-server_1",
    "bms-server_2",
    "tcp1801-server",
    "tcp1801-server_1",
    "tcp1801-server_2",
    "devices-server",
    "member-server",
    "push-server",
    "system-server",
    "things-server",
    "gateway-server",
    "mqtt-server",
    "report-server",
    "trade-server",
    "infra-server",
    "protocol-message-bms",
    "protocol-message-tcp1801",
    # 增加对子目录核心日志的保护
    "broker", "namesrv", "remoting", "store", "storeerror", "transaction", "watermark",
    "naming", "config", "access", "remote", "server",
    "xxl-job-admin"
]

# 允许清理的子目录列表
SUBDIR_LIST = [
    "rocketmqlogs"
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
    
    # 路径安全校验 - 严格限制只允许清理 LOG_DIRECTORY 下的文件
    allowed_dir = os.getenv("LOG_DIRECTORY")
    if not allowed_dir:
        return "错误：未在环境变量中配置 LOG_DIRECTORY，出于安全考虑拒绝执行清理。"
    
    # 预定义活跃日志名集合，用于排除正在写入的文件
    active_log_names = {f"{app}.log" for app in APP_LIST}
    
    allowed_path = Path(allowed_dir).resolve()
    try:
        # 如果 log_directory 为空或未提供有效路径，默认使用 allowed_path
        if not log_directory or log_directory.lower() == "none":
            log_path = allowed_path
        else:
            requested_path = Path(log_directory).resolve()
            # 验证请求路径是否在允许的路径范围内（或是其子目录）
            requested_path.relative_to(allowed_path)
            log_path = requested_path
    except ValueError:
        return f"拒绝访问：指定的目录 '{log_directory}' 不在允许的清理范围 '{allowed_dir}' 内。"

    if not log_path.exists():
        return f"错误：日志目录不存在 - {log_path}"

    files_to_clean = []
    
    def collect_backup_files(directory: Path, check_prefixes: bool = True):
        """递归收集目录下的备份日志文件"""
        if not directory.exists() or not directory.is_dir():
            return
            
        for entry in directory.iterdir():
            if entry.is_dir():
                # 如果是预定义的子目录，或者我们在处理这些子目录内部，则递归
                if entry.name in SUBDIR_LIST or not check_prefixes:
                    collect_backup_files(entry, check_prefixes=False)
                continue
                
            if not entry.is_file():
                continue
                
            filename = entry.name
            
            # 1. 检查前缀（如果是根目录下的文件）
            if check_prefixes:
                is_app_log = any(filename.startswith(app) for app in APP_LIST)
                if not is_app_log:
                    continue
            
            # 2. 识别是否为备份/滚动日志文件
            is_backup = False
            
            if filename.endswith((".gz", ".tmp", ".bak", ".zip")):
                is_backup = True
            # 如果是 .log 结尾，但名字不在活跃日志名单中（说明是带了中间日期或序号的备份）
            elif filename.endswith(".log") and filename not in active_log_names:
                is_backup = True
            # RocketMQ/Nacos 专项匹配：.log 后面跟着日期或数字序号（即使不以 .log 结尾）
            # 例如: broker.log.20260129, access.log.2026-01-29, broker.log.1
            elif re.search(r'\.log[\._-][\d-]+$', filename):
                is_backup = True
                
            if is_backup:
                files_to_clean.append({
                    'path': entry,
                    'mtime': entry.stat().st_mtime,
                    'size_mb': entry.stat().st_size / (1024 * 1024)
                })

    # 开始收集文件
    collect_backup_files(log_path)

    if not files_to_clean:
        return f"信息：在 {log_path} 中未找到可清理的备份日志文件。"

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
