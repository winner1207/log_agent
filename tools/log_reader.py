"""
日志读取工具 - 为 Agent 提供文件读取能力

支持：
- 读取最近 N 行日志
- 提取错误和异常信息
- 支持多文件读取
"""
import os
from pathlib import Path
from typing import List, Optional
from langchain_core.tools import tool
from datetime import datetime, timedelta


@tool
def read_recent_logs(
    log_directory: str,
    log_files: Optional[List[str]] = None,
    lines_per_file: int = 100,
    error_level_only: bool = True
) -> str:
    """
    从指定目录读取最近的日志文件内容（面向 Agent 分析）
    
    这个工具让 Agent 能够自主读取日志，用于故障诊断和根因分析。
    
    Args:
        log_directory: 日志文件所在目录
        log_files: 要读取的日志文件列表（如果为 None，会读取所有常见日志文件）
        lines_per_file: 每个文件读取的最后 N 行
        error_level_only: 是否只提取 ERROR 及以上级別的日志
    
    Returns:
        格式化的日志文本，包含文件名、时间戳、错误级别和内容
    
    Example:
        >>> result = read_recent_logs(
        ...     log_directory="/var/log/app",
        ...     log_files=["bms-server.log", "devices-server.log"],
        ...     lines_per_file=50,
        ...     error_level_only=True
        ... )
    """
    import json
    
    # 处理 Agent 可能传递的 JSON 格式参数
    if isinstance(log_directory, str):
        log_directory = log_directory.strip().strip("'").strip('"')
        try:
            parsed = json.loads(log_directory)
            if isinstance(parsed, dict):
                if 'log_directory' in parsed:
                    log_directory = parsed['log_directory']
                if 'log_files' in parsed and parsed['log_files']:
                    log_files = parsed['log_files']
                if 'lines_per_file' in parsed:
                    lines_per_file = parsed['lines_per_file']
                if 'error_level_only' in parsed:
                    error_level_only = parsed['error_level_only']
            elif isinstance(parsed, str):
                log_directory = parsed
        except (json.JSONDecodeError, TypeError):
            pass
    
    # 再次清理引号和空白
    log_directory = str(log_directory).strip().strip("'").strip('"')
    # 处理路径（标准化反斜杠）
    log_directory = log_directory.replace('\\\\', '\\')
    
    if not Path(log_directory).exists():
        return f"错误：日志目录不存在 - {log_directory}"
    
    # 如果未指定文件列表，使用默认的常见文件
    if log_files is None:
        log_files = [
            "bms-server.log",
            "bms-server_1.log",
            "bms-server_2.log",
            "devices-server.log",
            "member-server.log",
            "push-server.log",
            "system-server.log",
            "things-server.log",
            "gateway-server.log",
            "mqtt-server.log",
            "report-server.log",
            "trade-server.log",
            "tcp1801-server.log",
            "rocketmq.log",
            "namesrv.log",
            "broker.log",
        ]
    
    result_parts = []
    found_files = 0
    total_errors = 0
    
    for log_file in log_files:
        # RocketMQ 日志从专用目录读取
        if log_file in ["rocketmq.log", "rocketmq_client.log", "namesrv.log", "broker.log"]:
            # 优先尝试 log_directory/rocketmqlogs (标准结构)
            rocketmq_dir = os.path.join(log_directory, "rocketmqlogs")
            if not os.path.exists(rocketmq_dir):
                # 尝试父目录同级的 rocketmqlogs
                rocketmq_dir = os.path.join(os.path.dirname(log_directory), "rocketmqlogs")
            
            file_path = Path(rocketmq_dir) / log_file
            # 如果指定为 rocketmq.log 但不存在，尝试映射到 rocketmq_client.log
            if not file_path.exists() and log_file == "rocketmq.log":
                file_path = Path(rocketmq_dir) / "rocketmq_client.log"
        else:
            file_path = Path(log_directory) / log_file
        
        if not file_path.exists():
            continue
        
        found_files += 1
        
        try:
            # 优化：使用 deque 只读取最后 N 行，避免大文件一次性 load 进内存
            from collections import deque
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                recent_lines = list(deque(f, maxlen=lines_per_file))
        except Exception as e:
            result_parts.append(f"\n【{log_file}】读取失败: {str(e)}")
            continue
        
        # 过滤错误日志
        if error_level_only:
            error_lines = [
                line for line in recent_lines
                if any(level in line for level in ['ERROR', 'FATAL', 'Exception', 'Error', 'WARN'])
            ]
        else:
            error_lines = recent_lines
        
        if error_lines:
            total_errors += len(error_lines)
            
            # 格式化输出
            result_parts.append(f"\n【{log_file}】(最后 {len(error_lines)} 条关键日志)")
            result_parts.append("=" * 80)
            
            for line in error_lines[-20:]:  # 最多显示 20 行
                result_parts.append(line.rstrip())
            
            if len(error_lines) > 20:
                result_parts.append(f"... (还有 {len(error_lines) - 20} 行日志)")
    
    # 汇总
    if found_files == 0:
        return f"警告：在 {log_directory} 中未找到任何日志文件"
    
    if total_errors == 0:
        summary = f"信息：扫描了 {found_files} 个日志文件，未发现 ERROR 级别的日志"
    else:
        summary = f"信息：扫描了 {found_files} 个日志文件，发现 {total_errors} 条关键日志"
    
    return summary + "\n" + "".join(result_parts)


@tool
def analyze_log_patterns(log_content: str, service_name: str = "unknown") -> str:
    """
    对日志内容进行模式识别，识别常见的故障模式
    
    Args:
        log_content: 日志文本内容
        service_name: 服务名称，用于上下文理解
    
    Returns:
        识别出的故障模式和相关信息
    """
    patterns = {
        "数据库连接": ["Connection reset", "Connection refused", "jdbc.SQLError", "mysql", "database", "pool exhausted"],
        "内存溢出": ["OutOfMemory", "heap space", "GC overhead", "PermGen"],
        "空指针": ["NullPointerException", "NPE"],
        "网络超时": ["timeout", "connect timeout", "read timeout", "SocketTimeoutException"],
        "线程问题": ["deadlock", "Thread", "lock", "synchronized"],
        "文件操作": ["FileNotFoundException", "IOException", "permission denied", "file not found"],
        "业务异常": ["IllegalArgumentException", "IllegalStateException", "ValidationException"],
    }
    
    result = []
    found_patterns = []
    
    for pattern_name, keywords in patterns.items():
        count = 0
        for keyword in keywords:
            count += log_content.count(keyword)
        
        if count > 0:
            found_patterns.append((pattern_name, count))
    
    if found_patterns:
        # 按频率排序
        found_patterns.sort(key=lambda x: x[1], reverse=True)
        result.append(f"【{service_name}】识别的故障模式：")
        for pattern_name, count in found_patterns:
            result.append(f"  - {pattern_name}: {count} 次出现")
    else:
        result.append(f"【{service_name}】未识别到已知的故障模式")
    
    return "\n".join(result)


@tool 
def get_log_summary_stats(log_directory: str, log_files: Optional[List[str]] = None) -> str:
    """
    获取日志目录的统计信息
    
    用于 Agent 快速了解系统整体状态
    
    Args:
        log_directory: 日志目录
        log_files: 要统计的日志文件列表
    
    Returns:
        包含文件数、错误行数、时间范围等信息
    """
    import json
    
    # 处理 Agent 可能传递的 JSON 格式参数
    if isinstance(log_directory, str):
        log_directory = log_directory.strip().strip("'").strip('"')
        try:
            parsed = json.loads(log_directory)
            if isinstance(parsed, dict):
                if 'log_directory' in parsed:
                    log_directory = parsed['log_directory']
                if 'log_files' in parsed and parsed['log_files']:
                    log_files = parsed['log_files']
            elif isinstance(parsed, str):
                log_directory = parsed
        except (json.JSONDecodeError, TypeError):
            pass
    
    # 再次清理引号和空白
    log_directory = str(log_directory).strip().strip("'").strip('"')
    # 处理路径（标准化反斜杠）
    log_directory = log_directory.replace('\\\\', '\\')
    
    if not Path(log_directory).exists():
        return f"错误：日志目录不存在 - {log_directory}"
    
    if log_files is None:
        log_files = [
            "bms-server.log",
            "bms-server_1.log",
            "bms-server_2.log",
            "devices-server.log",
            "member-server.log",
            "push-server.log",
            "system-server.log",
            "things-server.log",
            "gateway-server.log",
            "mqtt-server.log",
            "report-server.log",
            "trade-server.log",
            "tcp1801-server.log",
            "rocketmq.log",
            "namesrv.log",
            "broker.log",
        ]
    
    stats = {
        'total_files': 0,
        'total_size_mb': 0,
        'error_count': 0,
        'warn_count': 0,
        'services': [],
        'last_modified': None
    }
    
    for log_file in log_files:
        # RocketMQ 日志从专用目录读取
        if log_file in ["rocketmq.log", "rocketmq_client.log", "namesrv.log", "broker.log"]:
            # 优先尝试 log_directory/rocketmqlogs (标准结构)
            rocketmq_dir = os.path.join(log_directory, "rocketmqlogs")
            if not os.path.exists(rocketmq_dir):
                # 尝试父目录同级的 rocketmqlogs
                rocketmq_dir = os.path.join(os.path.dirname(log_directory), "rocketmqlogs")
            
            file_path = Path(rocketmq_dir) / log_file
            # 如果指定为 rocketmq.log 但不存在，尝试映射到 rocketmq_client.log
            if not file_path.exists() and log_file == "rocketmq.log":
                file_path = Path(rocketmq_dir) / "rocketmq_client.log"
        else:
            file_path = Path(log_directory) / log_file
        
        if not file_path.exists():
            continue
        
        stats['total_files'] += 1
        stats['services'].append(log_file.replace('.log', ''))
        
        # 文件大小
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        stats['total_size_mb'] += file_size_mb
        
        # 修改时间
        mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
        if stats['last_modified'] is None or mtime > stats['last_modified']:
            stats['last_modified'] = mtime
        
        # 统计错误（流式读取，避免大文件内存溢出）
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if 'ERROR' in line:
                        stats['error_count'] += 1
                    if 'WARN' in line:
                        stats['warn_count'] += 1
        except:
            pass
    
    result = [
        "【日志统计】",
        f"扫描日志文件数: {stats['total_files']}",
        f"总大小: {stats['total_size_mb']:.2f} MB",
        f"ERROR 级别日志: {stats['error_count']} 条",
        f"WARN 级别日志: {stats['warn_count']} 条",
        f"最后更新: {stats['last_modified'].strftime('%Y-%m-%d %H:%M:%S') if stats['last_modified'] else 'N/A'}",
        f"涉及服务: {len(stats['services'])} 个",
    ]
    
    return "\n".join(result)
