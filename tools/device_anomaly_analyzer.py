import os
import re
import json
import gzip
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from langchain_core.tools import tool

@tool
def analyze_device_anomalies(time_range_min: str = "300", top_n: str = "3") -> str:
    """
    分析物联网电动车设备上报频率异常。
    识别超高频上报设备（阈值：>30次/分）。
    
    Args:
        time_range_min: 追溯最近多少分钟的日志，默认 "300"。
        top_n: 返回前多少名高频设备，默认 "3"。
    """
    # 安全转换参数，处理 Agent 可能传入的空字符串或非数字字符
    try:
        t_range = int(time_range_min) if str(time_range_min).strip() else 300
    except (ValueError, TypeError):
        t_range = 300
        
    try:
        n_top = int(top_n) if str(top_n).strip() else 3
    except (ValueError, TypeError):
        n_top = 3

    # 优先尝试从环境配置获取日志目录，如果没设则尝试本地几个常用路径
    log_dir = os.getenv("LOG_DIRECTORY", "").strip().strip("'").strip('"')
    if not log_dir or not os.path.exists(log_dir):
        # 尝试相对于 workspace 的路径
        possible_dirs = [
            os.path.join(os.getcwd(), "log_agent/logs"),
            os.path.join(os.getcwd(), "logs"),
            "./log_agent/logs",
            "./logs"
        ]
        for d in possible_dirs:
            if os.path.exists(d):
                log_dir = d
                break
    
    if not log_dir:
        log_dir = "/home/ubuntu/logs/" # 最后的兜底
        
    tcp_log_base = os.path.join(log_dir, "protocol-message-tcp1801.log")
    
    now = datetime.now()
    # 强制将 now 设为日志中的时间，以便在离线日志分析时能匹配到数据
    # 如果是实时监控，则保持 datetime.now()
    # 这里为了兼容测试，可以尝试从最新日志文件中提取时间，但简单起见我们先按原逻辑
    start_time_limit = (now - timedelta(minutes=t_range)).replace(second=0, microsecond=0)
    
    # 1. 匹配规则定义
    time_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2})')
    # 增加对 IP 的提取
    dev_info_pattern = re.compile(r'设备\((?P<id>[^)]+)\)\s+IP\((?P<ip>[^)]+)\)')
    
    device_total_stats = Counter()
    device_ips = {} # 存储设备 ID 到最新 IP 的映射
    device_per_min = defaultdict(Counter)
    device_peak_freq = {}

    def get_related_files(base_path):
        if os.path.exists(base_path):
            return [base_path]
        return []

    # 2. 遍历处理日志
    related_files = get_related_files(tcp_log_base)
    if not related_files:
        return f"### 🚀 设备上报频率监控报告\n\n⚠️ 未找到 {os.path.basename(tcp_log_base)}* 日志文件，无法进行设备异常分析。"
    
    line_count = 0
    max_lines = 300000  # 安全限制，提升至 30w
    
    stop_all_files = False
    start_time_str = start_time_limit.strftime('%Y-%m-%d %H:%M')

    def read_lines_backwards(file_path, max_lines_to_read):
        """从后往前读取文件行，优化大文件分析性能"""
        is_gz = file_path.endswith('.gz')
        if is_gz:
            # GZ 文件不支持从后往前 seek，只能顺序读（通常旧日志才会压缩）
            with gzip.open(file_path, 'rt', encoding='utf-8', errors='ignore') as f:
                # 对于顺序读，我们只能先读入内存再反转，或者通过时间窗口过滤
                # 这里简单处理：读取前 max_lines 行并反转
                lines = []
                for line in f:
                    lines.append(line)
                    if len(lines) >= max_lines_to_read: break
                return reversed(lines)
        
        # 普通文件使用 seek 块读取
        lines_to_yield = []
        with open(file_path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            position = f.tell()
            buffer = b""
            block_size = 65536
            
            while position > 0 and len(lines_to_yield) < max_lines_to_read:
                read_size = min(position, block_size)
                position -= read_size
                f.seek(position)
                chunk = f.read(read_size)
                buffer = chunk + buffer
                lines = buffer.splitlines()
                
                # 保留第一个（可能不完整）的行到下次循环
                if position > 0:
                    buffer = lines.pop(0)
                else:
                    buffer = b""
                
                # 将当前块的行加入结果
                for line in reversed(lines):
                    lines_to_yield.append(line.decode('utf-8', errors='ignore'))
                    if len(lines_to_yield) >= max_lines_to_read:
                        break
        return lines_to_yield

    for file_path in related_files:
        if line_count > max_lines or stop_all_files: break
        try:
            # 使用反向读取，配合时间窗口早停
            for line in read_lines_backwards(file_path, max_lines - line_count):
                line_count += 1
                
                t_match = time_pattern.match(line)
                if not t_match: continue
                
                log_time_str = t_match.group(1)
                
                # 先尝试匹配设备信息
                info_match = dev_info_pattern.search(line)
                if info_match:
                    dev_id = info_match.group('id').strip()
                    dev_ip = info_match.group('ip').strip()
                    
                    # 过滤掉 ID 为空或仅包含“未知”字样的情况
                    if dev_id and dev_id not in ["", "未知", "null"]:
                        device_total_stats[dev_id] += 1
                        if dev_id not in device_ips:
                            device_ips[dev_id] = dev_ip
                        device_per_min[log_time_str][dev_id] += 1
                
                # 性能优化：时间窗口早停
                # 既然是从后（最新）往前（旧）读
                # 一旦读到早于设定时间的行，说明更旧的数据都不需要再读了
                if log_time_str < start_time_str:
                    stop_all_files = True
                    break
        except Exception as e:
            import sys
            print(f"处理文件 {file_path} 时出错: {e}", file=sys.stderr)
            continue

    # 3. 计算统计指标
    all_devs_stats = [] # (dev_id, total, peak)
    total_messages = sum(device_total_stats.values())
    tps = total_messages / (t_range * 60) if t_range > 0 else 0
    
    for dev_id, total in device_total_stats.items():
        # 获取该设备在所有分钟内的最大上报数
        peak = 0
        for minute_counts in device_per_min.values():
            peak = max(peak, minute_counts.get(dev_id, 0))
        device_peak_freq[dev_id] = peak
        all_devs_stats.append((dev_id, total, peak))

    # 4. 按总上报次数排序获取 Top N
    all_devs_stats.sort(key=lambda x: x[1], reverse=True)
    top_devs = all_devs_stats[:n_top]

    # 5. 生成报告
    report = [f"#### 🚩 高频上报设备 Top {n_top}"]
    report.append(f"(时段内总报文数: {total_messages} | 平均 TPS: {tps:.2f})")
    report.append(f"(共分析 {line_count} 条日志行)")
    
    for i, (dev_id, total, peak) in enumerate(top_devs, 1):
        dev_ip = device_ips.get(dev_id, "未知")
        
        # 动态阈值标注
        if peak > 30:
            status_label = "🔴 异常"
        elif peak > 15:
            status_label = "🟡 较活跃"
        else:
            status_label = "🟢 正常"
            
        report.append(f"- **Top {i}**: `{dev_id}` (IP: {dev_ip}) | 上报: {total} | 峰值: {peak}次/分 | {status_label}")
    
    if not top_devs:
        report.append("- 🟢 当前时段内未发现任何设备上报数据")

    return "\n".join(report)

