"""
钉钉通知管理器 (Notification Manager)

支持钉钉机器人接入，帮助发送结构化的诊断报告。
"""
import json
import logging
import time
import hmac
import hashlib
import base64
import urllib.parse
from typing import Dict, Optional, Callable
from datetime import datetime
from pathlib import Path


# 设置日志
logger = logging.getLogger(__name__)


class NotificationManager:
    """分级通知管理器"""
    
    # 通知级别
    LEVEL_P0 = "P0"  # 严重：宕机、磁盘满、核心中断
    LEVEL_P1 = "P1"  # 错误：普通报错
    LEVEL_P2 = "P2"  # 警告：性能抖动
    LEVEL_P3 = "P3"  # 报告：日报、周报
    
    # 向后兼容
    LEVEL_FATAL = LEVEL_P0
    LEVEL_ERROR = LEVEL_P1
    LEVEL_WARN = LEVEL_P2
    
    def __init__(self, 
                 dingtalk_access_token: Optional[str] = None,
                 dingtalk_secret: Optional[str] = None,
                 on_duty_mobiles: Optional[str] = None,
                 log_dir: str = "./notification_logs",
                 auto_load_from_env: bool = True):
        """
        初始化钉钉通知管理器
        
        Args:
            dingtalk_access_token: 钉钉机器人 Access Token
            dingtalk_secret: 钉钉机器人 Secret
            on_duty_mobiles: 值班人员手机号，多个用逗号分隔
            log_dir: 日志目录
            auto_load_from_env: 是否自动从环境变量加载配置
        """
        # 如果启用自动加载且相关参数为空，从环境变量读取
        if auto_load_from_env:
            import os
            from dotenv import load_dotenv
            load_dotenv()
            
            dingtalk_access_token = dingtalk_access_token or os.getenv("DINGTALK_ACCESS_TOKEN")
            dingtalk_secret = dingtalk_secret or os.getenv("DINGTALK_SECRET")
            on_duty_mobiles = on_duty_mobiles or os.getenv("DINGTALK_ON_DUTY_MOBILES")
        
        # 钉钉机器人配置
        self.dingtalk_access_token = dingtalk_access_token
        self.dingtalk_secret = dingtalk_secret
        self.on_duty_mobiles = [m.strip() for m in on_duty_mobiles.split(',')] if on_duty_mobiles else []
        
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # 自定义通知处理器
        self.custom_handlers: Dict[str, Callable] = {}
        
        # 通知统计
        self.notification_stats = {
            'sent': 0,
            'failed': 0,
        }
    
    def register_custom_handler(self, level: str, handler: Callable):
        """
        注册自定义通知处理器
        
        Args:
            level: 通知级别 (FATAL, ERROR, WARN)
            handler: 处理函数，签名为 handler(alert: Dict) -> bool
        """
        self.custom_handlers[level] = handler
    
    def handle_alert(self, alert: Dict) -> bool:
        """
        发送告警到钉钉
        
        Args:
            alert: 告警对象
            
        Returns:
            True 表示发送成功，False 表示失败
        """
        # 检查是否有自定义处理器
        level = alert.get('level', self.LEVEL_WARN)
        if level in self.custom_handlers:
            try:
                return self.custom_handlers[level](alert)
            except Exception as e:
                logger.error(f"Custom handler for {level} failed: {e}")
        
        # 发送到钉钉
        return self._send_dingtalk(alert)
    

    
    def _send_dingtalk(self, alert: Dict) -> bool:
        """发送钉钉机器人消息"""
        try:
            import requests
            
            # 生成签名
            timestamp = str(round(time.time() * 1000))
            secret_enc = self.dingtalk_secret.encode('utf-8')
            string_to_sign = f'{timestamp}\n{self.dingtalk_secret}'
            string_to_sign_enc = string_to_sign.encode('utf-8')
            hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            
            # 构建 Webhook URL
            webhook_url = f'https://oapi.dingtalk.com/robot/send?access_token={self.dingtalk_access_token}&timestamp={timestamp}&sign={sign}'
            
            message = self._format_dingtalk_message(alert)
            
            response = requests.post(
                webhook_url,
                json=message,
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            
            # 钉钉返回 200 且 body 中 errcode=0 表示成功
            if response.status_code == 200:
                try:
                    body = response.json()
                    if body.get('errcode') == 0:
                        logger.info(f"DingTalk notification sent successfully for {alert['exception_type']}")
                        self.notification_stats['sent'] += 1
                        return True
                    else:
                        logger.error(f"DingTalk API error: {body.get('errmsg', 'Unknown error')}")
                        self.notification_stats['failed'] += 1
                        return False
                except:
                    logger.info(f"DingTalk notification sent for {alert['exception_type']}")
                    self.notification_stats['sent'] += 1
                    return True
            else:
                logger.error(f"DingTalk notification failed with status {response.status_code}")
                self.notification_stats['failed'] += 1
                return False
        except Exception as e:
            logger.error(f"DingTalk send error: {e}")
            self.notification_stats['failed'] += 1
            return False
    

    

    def _format_dingtalk_message(self, alert: Dict) -> Dict:
        """格式化钉钉加签机器人消息"""
        # 获取通知级别，默认 P1
        level = alert.get('level', self.LEVEL_P1)
        if isinstance(level, str):
            level = level.upper().strip()
        
        # 构建 @ 逻辑
        at_dict = {"atMobiles": [], "isAtAll": False}
        at_text = ""
        
        if level == self.LEVEL_P0:
            # P0 级：@所有人
            at_dict["isAtAll"] = True
            at_text = "\n\n@所有人"
        elif level in [self.LEVEL_P1, self.LEVEL_P2] and self.on_duty_mobiles:
            # P1/P2 级：使用手机号触发强提醒
            at_dict["atMobiles"] = self.on_duty_mobiles
            # 在 Markdown 文本中拼接 @手机号 触发蓝色显示效果
            at_text = "\n\n" + " ".join([f"@{m}" for m in self.on_duty_mobiles])
        
        # P3 及其他级别：不设置 at_text 和 atMobiles，不触发任何 @ 提醒

        # 判断是否是诊断报告、AI健康报告或堆栈报告
        if alert.get('exception_type') in ['DiagnosisReport', 'AIHealthReport', 'StackTraceReport']:
            message_content = alert.get('exception_message', '')
            
            # 报告类型处理
            if alert.get('exception_type') == 'StackTraceReport':
                title = f"[{level}][堆栈错误] {alert.get('device_id', 'unknown')}"
            elif alert.get('exception_type') == 'AIHealthReport':
                title = f"🔍 [{level}] 系统健康诊断报告"
            else:
                optimized_content = NotificationManager._optimize_diagnosis_report(message_content)
                message_content = optimized_content
                title = f"[{level}][AI诊断] 业务告警"
            
            return {
                "msgtype": "actionCard",
                "actionCard": {
                    "title": title,
                    "text": message_content + at_text,
                    "buttons": [
                        {
                            "title": "查看日志详情",
                            "actionURL": "https://your-log-platform.com/logs?device={}".format(alert.get('device_id', 'unknown'))
                        },
                        {
                            "title": "处理完成",
                            "actionURL": "https://your-notification-system.com/ack/{}".format(alert.get('id', 'unknown'))
                        }
                    ]
                },
                "at": at_dict
            }
        else:
            # 普通告警
            count = alert.get('count', 1)
            return {
                "msgtype": "markdown",
                "markdown": {
                    "title": f"[{level}] {alert.get('exception_type', 'Exception')}",
                    "text": f"### [{level}] 异常告警\n\n- **类型**: {alert.get('exception_type', 'N/A')}\n- **消息**: {alert.get('exception_message', 'N/A')}\n- **位置**: {alert.get('location', 'N/A')}\n- **次数**: {count}\n- **根因**: {alert.get('root_cause', 'N/A')}{at_text}"
                },
                "at": at_dict
            }
    
    @staticmethod
    def _optimize_diagnosis_report(report: str) -> str:
        """优化诊断报告格式 - 为运维消息服务"""
        lines = report.split('\n')
        result = []
        in_long_term = False
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # 跳过「长期架构」部分
            if '长期架构' in line or '长期优化' in line:
                in_long_term = True
                i += 1
                continue
            
            if in_long_term:
                # 跳过整个长期部分
                if not line or '诊断' in line or '检查' in line:
                    in_long_term = False
                else:
                    i += 1
                    continue
            
            # 跳过空行
            if not line:
                i += 1
                continue
            
            # 保留「诊断摘要」部分
            if '诊断摘要' in line or '诊断一览' in line:
                result.append('\n[CORE] \u6838\u5fc3\u8bca\u65ad')
                i += 1
                while i < len(lines):
                    next_line = lines[i].strip()
                    if '根本原因' in next_line or not next_line:
                        break
                    if next_line:
                        result.append(next_line.replace('\u2022', '-'))
                    i += 1
                continue
            
            # 保留「根本原因」部分
            if '根本原因' in line or '原因分析' in line:
                result.append('\n[ANALYSIS] \u539f\u56e0\u5206\u6790')
                i += 1
                reason_count = 0
                while i < len(lines):
                    next_line = lines[i].strip()
                    if '上会\u7b80议' in next_line or '修\u590d建\u8bae' in next_line or '长\u671f\u67b6\u6784' in next_line or not next_line:
                        break
                    if next_line and reason_count < 2:  # 仅保\u7559前两个原因
                        result.append(next_line.replace('\u2022', '-'))
                        if next_line.startswith('1') or next_line.startswith('2') or next_line.startswith('3'):
                            reason_count += 1
                    i += 1
                continue
            
            # 保\u7559「上会简议」或「修\u590d建\u8bae」部分
            if '上会\u7b80\u8bae' in line or '修\u590d建\u8bae' in line or '修\u590d\u65b9\u6848' in line:
                result.append('\n[SUGGEST] AI\u5efa\u8bae')
                i += 1
                while i < len(lines):
                    next_line = lines[i].strip()
                    if '立\u5373\u884c\u52a8' in next_line:
                        i += 1
                        # \u53ea\u6536\u96c6\u300c\u7acb\u5373\u884c\u52a8\u300d\u90e8分
                        while i < len(lines):
                            action_line = lines[i].strip()
                            if not action_line or '短\u671f' in action_line or '长\u671f' in action_line:
                                break
                            if action_line and action_line.startswith('\u2022'):
                                result.append(action_line.replace('\u2022', '-'))
                            i += 1
                        break
                    if '短\u671f' in next_line or '长\u671f' in next_line or not next_line:
                        break
                    i += 1
                continue
            
            result.append(line)
            i += 1
        
        # \u7ec4\u5408\u6700\u7ec8\u62a5\u544a
        final_report = '\n'.join(result)
        
        # \u52a0\u7c97\u8bbe\u5907ID
        if 'YJP' in final_report:
            final_report = final_report.replace('YJP00000000321', '**YJP00000000321**')
        
        return final_report if final_report.strip() else "\u8bca\u65ad\u62a5\u544a"
    

    def get_statistics(self) -> Dict:
        """获取通知统计信息"""
        return {
            'sent': self.notification_stats['sent'],
            'failed': self.notification_stats['failed'],
            'total': self.notification_stats['sent'] + self.notification_stats['failed'],
        }


# 示例用法
if __name__ == "__main__":
    # 创建钉钉通知管理器
    notif = NotificationManager()
    
    print("=== 钉钉通知管理器演示 ===")
    print()
    
    # 创建诊断报告
    diagnosis_report = {
        'exception_type': 'AIHealthReport',
        'exception_message': '# 系统诊断\n## 核心问题\n数据库连接断开',
        'level': 'FATAL',
        'device_id': 'PROD_SYSTEM',
    }
    
    # 发送到钉钉
    print("1. 发送诊断报告到钉钉")
    result = notif.handle_alert(diagnosis_report)
    print(f"   结果: {'成功' if result else '失败'}")
    
    print()
    print("2. 通知统计:")
    print(notif.get_statistics())
