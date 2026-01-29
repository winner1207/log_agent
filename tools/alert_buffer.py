"""
告警缓冲池 (Alert Buffer)

防止告警风暴问题：如果系统每秒报错 10 次，不能发 10 封邮件

聚合机制：
- 同一种异常（根据异常类名 + 报错位置 Hash）在 5 分钟内只发一封邮件
- 邮件中注明"该错误在 5 分钟内发生了 N 次"
"""
import hashlib
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict


class AlertBuffer:
    """告警缓冲池，实现告警聚合和去重"""
    
    # 缓冲时间窗口（秒）
    BUFFER_WINDOW_SECONDS = 300  # 5 分钟
    
    # 告警严重级别
    LEVEL_FATAL = "FATAL"
    LEVEL_ERROR = "ERROR"
    LEVEL_WARN = "WARN"
    
    def __init__(self, buffer_window_seconds: int = 300):
        """
        初始化告警缓冲池
        
        Args:
            buffer_window_seconds: 缓冲时间窗口（默认 300 秒 = 5 分钟）
        """
        self.buffer_window_seconds = buffer_window_seconds
        
        # 存储告警：异常 Hash -> {count, timestamp, first_occurrence, alerts}
        self.alert_buffer: Dict[str, Dict] = {}
        
        # 待发送的告警队列
        self.send_queue: List[Dict] = []
    
    @staticmethod
    def calculate_exception_hash(exception_type: str, location: Optional[str] = None) -> str:
        """
        计算异常的唯一 Hash（用于去重）
        
        Args:
            exception_type: 异常类型（如 NullPointerException）
            location: 报错位置（如 BatteryService.java:234）
            
        Returns:
            异常 Hash 值
        """
        key = f"{exception_type}:{location or 'unknown'}"
        return hashlib.md5(key.encode()).hexdigest()[:8]
    
    def add_alert(self, 
                  exception_type: str, 
                  exception_message: str,
                  location: Optional[str] = None,
                  level: str = LEVEL_ERROR,
                  root_cause: Optional[str] = None,
                  stacktrace: Optional[str] = None,
                  device_id: Optional[str] = None) -> Tuple[bool, Optional[Dict]]:
        """
        添加告警到缓冲池
        
        Args:
            exception_type: 异常类型
            exception_message: 异常消息
            location: 报错位置
            level: 告警级别 (FATAL, ERROR, WARN)
            root_cause: 根因（如有）
            stacktrace: 堆栈跟踪
            device_id: 设备 ID（如有）
            
        Returns:
            (是否应该立即发送, 应发送的告警对象)
            - 如果是新异常或上次发送已超过 5 分钟，返回 (True, alert_obj)
            - 否则返回 (False, None)
        """
        exception_hash = self.calculate_exception_hash(exception_type, location)
        current_time = time.time()
        
        # 立即发送 FATAL 级别的告警（不缓冲）
        if level == self.LEVEL_FATAL:
            alert_obj = {
                'id': exception_hash,
                'exception_type': exception_type,
                'exception_message': exception_message,
                'location': location,
                'level': level,
                'root_cause': root_cause,
                'stacktrace': stacktrace,
                'device_id': device_id,
                'count': 1,
                'first_occurrence': datetime.now().isoformat(),
                'last_occurrence': datetime.now().isoformat(),
                'occurrences': [datetime.now().isoformat()],
                'should_send': True,
                'is_aggregated': False,
            }
            self.send_queue.append(alert_obj)
            return True, alert_obj
        
        # 处理 ERROR 和 WARN 的缓冲聚合
        if exception_hash not in self.alert_buffer:
            # 新异常，立即发送
            alert_obj = {
                'id': exception_hash,
                'exception_type': exception_type,
                'exception_message': exception_message,
                'location': location,
                'level': level,
                'root_cause': root_cause,
                'stacktrace': stacktrace,
                'device_id': device_id,
                'count': 1,
                'first_occurrence': datetime.now().isoformat(),
                'last_occurrence': datetime.now().isoformat(),
                'occurrences': [datetime.now().isoformat()],
            }
            
            self.alert_buffer[exception_hash] = {
                'count': 1,
                'timestamp': current_time,
                'first_occurrence': current_time,
                'last_occurrence': current_time,
                'occurrences': [datetime.now().isoformat()],
                'alert_obj': alert_obj,
            }
            
            alert_obj['should_send'] = True
            alert_obj['is_aggregated'] = False
            self.send_queue.append(alert_obj)
            
            return True, alert_obj
        else:
            # 已存在相同异常
            buffer_entry = self.alert_buffer[exception_hash]
            time_since_first = current_time - buffer_entry['timestamp']
            
            if time_since_first >= self.buffer_window_seconds:
                # 超过缓冲时间窗口，可以再次发送
                alert_obj = {
                    'id': exception_hash,
                    'exception_type': exception_type,
                    'exception_message': exception_message,
                    'location': location,
                    'level': level,
                    'root_cause': root_cause,
                    'stacktrace': stacktrace,
                    'device_id': device_id,
                    'count': 1,
                    'first_occurrence': datetime.now().isoformat(),
                    'last_occurrence': datetime.now().isoformat(),
                    'occurrences': [datetime.now().isoformat()],
                    'should_send': True,
                    'is_aggregated': False,
                }
                
                # 重置缓冲
                self.alert_buffer[exception_hash] = {
                    'count': 1,
                    'timestamp': current_time,
                    'first_occurrence': current_time,
                    'last_occurrence': current_time,
                    'occurrences': [datetime.now().isoformat()],
                    'alert_obj': alert_obj,
                }
                
                self.send_queue.append(alert_obj)
                return True, alert_obj
            else:
                # 在缓冲时间内，聚合计数
                buffer_entry['count'] += 1
                buffer_entry['last_occurrence'] = current_time
                buffer_entry['occurrences'].append(datetime.now().isoformat())
                
                # 更新关联的告警对象
                if 'alert_obj' in buffer_entry:
                    buffer_entry['alert_obj']['count'] = buffer_entry['count']
                    buffer_entry['alert_obj']['last_occurrence'] = datetime.now().isoformat()
                    buffer_entry['alert_obj']['occurrences'] = buffer_entry['occurrences']
                
                return False, None
    
    def get_aggregated_alerts(self) -> List[Dict]:
        """
        获取需要立即发送的告警列表
        
        Returns:
            告警对象列表
        """
        alerts = self.send_queue.copy()
        self.send_queue.clear()
        return alerts
    
    def get_pending_alerts(self) -> List[Dict]:
        """
        获取缓冲中等待聚合的告警
        
        返回仍在聚合时间窗口内的告警信息
        """
        pending = []
        current_time = time.time()
        
        for exception_hash, buffer_entry in self.alert_buffer.items():
            time_remaining = self.buffer_window_seconds - (current_time - buffer_entry['timestamp'])
            
            if time_remaining > 0:
                pending.append({
                    'id': exception_hash,
                    'count': buffer_entry['count'],
                    'exception_type': buffer_entry['alert_obj'].get('exception_type'),
                    'location': buffer_entry['alert_obj'].get('location'),
                    'time_remaining_seconds': time_remaining,
                    'occurrences': buffer_entry['occurrences'],
                })
        
        return pending
    
    def clear_expired_buffers(self):
        """清除已过期的缓冲项"""
        current_time = time.time()
        expired_hashes = []
        
        for exception_hash, buffer_entry in self.alert_buffer.items():
            time_since_first = current_time - buffer_entry['timestamp']
            
            if time_since_first >= self.buffer_window_seconds:
                expired_hashes.append(exception_hash)
        
        for hash_key in expired_hashes:
            del self.alert_buffer[hash_key]
    
    def get_statistics(self) -> Dict:
        """获取缓冲池统计信息"""
        self.clear_expired_buffers()
        
        total_buffered = sum(entry['count'] for entry in self.alert_buffer.values())
        
        return {
            'buffered_unique_exceptions': len(self.alert_buffer),
            'total_buffered_occurrences': total_buffered,
            'pending_alerts': len(self.send_queue),
            'buffer_details': self.get_pending_alerts(),
        }
    
    def reset(self):
        """重置缓冲池"""
        self.alert_buffer.clear()
        self.send_queue.clear()


# 示例用法
if __name__ == "__main__":
    buffer = AlertBuffer(buffer_window_seconds=5)  # 为了演示，使用 5 秒缓冲
    
    print("=== 告警缓冲池演示 ===\n")
    
    # 添加第一条告警
    print("1. 添加 NullPointerException 第 1 次")
    should_send, alert = buffer.add_alert(
        exception_type="NullPointerException",
        exception_message="Cannot invoke method on null object",
        location="BatteryService.java:234",
        level=AlertBuffer.LEVEL_ERROR,
        root_cause="battery_data is null",
        device_id="YJP00000000321"
    )
    print(f"   应该发送: {should_send}")
    print(f"   告警数: {len(buffer.get_aggregated_alerts())}\n")
    
    # 短时间内添加相同异常（应该被缓冲）
    print("2. 添加 NullPointerException 第 2 次（立即）")
    should_send, alert = buffer.add_alert(
        exception_type="NullPointerException",
        exception_message="Cannot invoke method on null object",
        location="BatteryService.java:234",
        level=AlertBuffer.LEVEL_ERROR,
        device_id="YJP00000000321"
    )
    print(f"   应该发送: {should_send}")
    print(f"   缓冲统计: {buffer.get_statistics()}\n")
    
    # 添加 FATAL 告警（应该立即发送）
    print("3. 添加 FATAL 级别告警")
    should_send, alert = buffer.add_alert(
        exception_type="DatabaseConnectionError",
        exception_message="Failed to connect to database",
        level=AlertBuffer.LEVEL_FATAL,
        device_id="System"
    )
    print(f"   应该发送: {should_send}")
    print(f"   待发送告警数: {len(buffer.get_aggregated_alerts())}\n")
    
    # 获取待发送的告警
    alerts_to_send = buffer.get_aggregated_alerts()
    print(f"4. 获取待发送告警队列:")
    for alert in alerts_to_send:
        print(f"   - {alert['exception_type']} (level={alert['level']}, count={alert['count']})")
    
    print(f"\n5. 缓冲池统计:")
    print(buffer.get_statistics())
