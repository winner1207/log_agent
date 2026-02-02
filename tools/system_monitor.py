"""
System monitoring tool - Check server resources and service status using psutil
"""
import os
import psutil
from langchain_core.tools import tool
from typing import Dict, Any
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 磁盘空间告警阈值
DISK_USAGE_THRESHOLD = int(os.getenv("DISK_USAGE_THRESHOLD", "80"))

# Define common Java service processes
COMMON_SERVICES = {
    'bms-server': 'yudao-module-bms-biz.jar',
    'mqtt-server': 'yudao-module-mqtt-biz.jar',
    'devices-server': 'yudao-module-devices-biz.jar',
    'push-server': 'yudao-module-push-biz.jar',
    'system-server': 'yudao-module-system-biz.jar',
    'rocketmq-namesrv': 'NamesrvStartup',      # RocketMQ 注册中心
    'rocketmq-proxy': 'ProxyStartup',          # RocketMQ 代理服务
    'nacos': 'nacos-server.jar',
    'gateway': 'yudao-gateway.jar',
    'report-server': 'yudao-module-report-biz.jar',
    'tcp1801-server': 'yudao-module-tcp1801-biz.jar',
    'things-server': 'yudao-module-things-biz.jar',
    'trade-server': 'yudao-module-trade-biz.jar',
    'member-server': 'yudao-module-member-biz.jar',
    'infra-server': 'yudao-module-infra-biz.jar',
}

def check_process_alive(service_name: str) -> Dict[str, Any]:
    """
    Check if a service process is still running
    
    Args:
        service_name: Service jar file name to search for
    
    Returns:
        {
            'service_name': service name,
            'alive': True/False,
            'pid': process ID or None,
            'memory_mb': memory usage (MB) or None,
            'cpu_percent': CPU usage % or None
        }
    """
    try:
        # Iterate all processes
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = ' '.join(proc.info.get('cmdline', []))
                # Check if cmdline contains service name
                if service_name in cmdline:
                    # Found it - extract process info
                    proc_obj = psutil.Process(proc.info['pid'])
                    try:
                        memory_mb = proc_obj.memory_info().rss / (1024 * 1024)
                        cpu_pct = proc_obj.cpu_percent(interval=0.1)
                    except:
                        memory_mb = None
                        cpu_pct = None
                    
                    return {
                        'service_name': service_name,
                        'alive': True,
                        'pid': proc.info['pid'],
                        'memory_mb': memory_mb,
                        'cpu_percent': cpu_pct
                    }
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        
        # Service not found
        return {
            'service_name': service_name,
            'alive': False,
            'pid': None,
            'memory_mb': None,
            'cpu_percent': None
        }
    except Exception as e:
        return {
            'service_name': service_name,
            'alive': False,
            'pid': None,
            'memory_mb': None,
            'cpu_percent': None,
            'error': str(e)
        }

@tool("check_service_status")
def check_service_status(query: str = "") -> str:
    """
    检查所有业务服务是否运行正常。
    返回格式化的报告：异常服务标红置顶，正常服务精简展示。
    """
    try:
        alive_services = []
        dead_services = []
        
        for service_name, jar_name in COMMON_SERVICES.items():
            service_info = check_process_alive(jar_name)
            
            if service_info['alive']:
                alive_services.append(service_name)
            else:
                dead_services.append(service_name)
        
        result = ["## 🛠️ 业务服务监控"]
        
        # 🔴 异常服务部分 (标红置顶)
        if dead_services:
            result.append(f"\n- **🔴 异常服务**: {len(dead_services)}")
            for svc in dead_services:
                result.append(f"  - {svc}: ❌ 已宕机 (请立即检查!)")
        else:
            result.append("\n- **🔴 异常服务**: 0 (无)")
            
        # 🟢 正常服务部分 (精简展示)
        result.append(f"- **🟢 正常服务**: {len(alive_services)}")
        if alive_services:
            result.append(f"  - {'、'.join(alive_services)}")
        else:
            result.append("  - 无")
        
        return "\n".join(result)
    except Exception as e:
        return f"检查服务状态出错: {str(e)}"


@tool("check_system_status")
def check_system_status(query: str = "") -> str:
    """
    检查当前系统状态，包括 CPU、内存、磁盘和网络。
    返回格式化的 Markdown 列表。
    """
    try:
        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count()
        
        # 内存
        memory = psutil.virtual_memory()
        
        # 磁盘
        disk_usage_list = []
        partitions = psutil.disk_partitions(all=True)
        processed_mounts = set()
        
        for part in partitions:
            if part.mountpoint in processed_mounts:
                continue
            if os.name != 'nt':
                if any(x in part.mountpoint for x in ['/proc', '/sys', '/dev', '/run', '/var/lib/docker']):
                    continue
                if part.fstype in ['tmpfs', 'devtmpfs', 'squashfs', 'iso9660']:
                    continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disk_usage_list.append({
                    'mountpoint': part.mountpoint,
                    'total': usage.total / (1024**3),
                    'free': usage.free / (1024**3),
                    'percent': usage.percent
                })
                processed_mounts.add(part.mountpoint)
            except:
                continue
        
        # 网络
        try:
            net_io = psutil.net_io_counters()
            net_info = f"- **网络IO**: 发送 {net_io.bytes_sent/(1024**2):.2f} MB / 接收 {net_io.bytes_recv/(1024**2):.2f} MB"
        except:
            net_info = "- **网络IO**: 无法获取"
            
        # 线程监控 (P0 事故点优化)
        total_threads = 0
        top_thread_procs = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'num_threads', 'cmdline']):
                try:
                    num = proc.info.get('num_threads') or 0
                    total_threads += num
                    if num > 500: # 记录线程数过高的进程
                        cmdline = ' '.join(proc.info.get('cmdline', []) or [])
                        top_thread_procs.append({
                            'pid': proc.info['pid'],
                            'name': proc.info['name'],
                            'threads': num,
                            'cmd': (cmdline[:80] + "...") if len(cmdline) > 80 else cmdline
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            top_thread_procs.sort(key=lambda x: x['threads'], reverse=True)
        except:
            pass
        
        thread_status = "✅ 正常" if total_threads < 20000 else "🚨 线程数极高"
        thread_info = f"- **系统线程数**: {total_threads} {thread_status}"
        
        result = [
            "## 🖥️ 系统状态",
            f"\n- **CPU使用率**: {cpu_percent}% ({cpu_count}核心) {'✅ 正常' if cpu_percent < 80 else '⚠️ 负载高'}",
            f"- **内存使用率**: {memory.percent}% (可用 {memory.available/(1024**3):.2f} GB / 总计 {memory.total/(1024**3):.2f} GB) {'✅ 正常' if memory.percent < 85 else '⚠️ 内存紧张'}",
            thread_info,
            f"- **磁盘状态** (告警阈值: {DISK_USAGE_THRESHOLD}%):"
        ]
        
        if not disk_usage_list:
            result.append("  - 无法获取磁盘状态")
        else:
            for disk in disk_usage_list:
                status = "✅ 正常" if disk['percent'] < DISK_USAGE_THRESHOLD else "🚨 空间不足"
                result.append(f"  - {disk['mountpoint']} 分区: {disk['percent']}% (空闲 {disk['free']:.2f} GB) {status}")
        
        # 如果线程数异常，追加详细列表供 LLM 诊断
        if total_threads > 10000 and top_thread_procs:
            result.append("\n- **高线程进程详情**:")
            for p in top_thread_procs[:5]:
                result.append(f"  - PID: {p['pid']} | 线程: {p['threads']} | 进程: {p['name']}")
                result.append(f"    - 命令: {p['cmd']}")
        
        result.append(net_info)
        return "\n".join(result)
    except Exception as e:
        return f"检查系统状态出错: {str(e)}"
