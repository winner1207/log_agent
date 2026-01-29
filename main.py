"""
日志诊断主程序 - AI Agent 每日系统健康检查

支持：
1. 从 .env 读取配置（日志路径、环境、Agent 参数）
2. 调用 IotDiagnosisAgent 进行智能诊断
3. 识别级联故障（根本原因 + 衆生故障）
4. 生成 JSON 格式的钉钉消息
"""
import os
from agent.iot_diagnosis_agent import IotDiagnosisAgent
from tools.notification_manager import NotificationManager
from tools.log_cleaner import APP_LIST
from pathlib import Path
import json
from datetime import datetime
from dotenv import load_dotenv

# 加载 .env 配置
load_dotenv()


def generate_ai_health_report(log_directory: str, environment: str = "prod", agent_temperature: float = 0.3, agent_max_iterations: int = 15, agent_enable_alert_buffer: bool = True):
    """
    使用 AI Agent 生成系统健康诊断日报
    
    Agent 会自主：
    1. 读取日志文件
    2. 识别故障模式
    3. 识别级联故障（关联问题）
    4. 生成 JSON 格式的钉钉消息
    
    Args:
        log_directory: 日志文件所在目录
        environment: 环境标识（dev/test/prod）
    
    Returns:
        JSON 格式的钉钉消息（可直接发送），或 None 如果失败
    """
    print(f"\n{'='*80}")
    print(f"AI Agent 日报生成 - {environment.upper()} 环境")
    print(f"日志目录: {log_directory}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}\n")
    
    # 验证目录存在
    if not Path(log_directory).exists():
        print(f"错误: 日志目录不存在 - {log_directory}")
        return None
    
    # [1] 初始化 Agent
    print("[1/3] 初始化 AI Agent...")
    try:
        agent = IotDiagnosisAgent(
            temperature=agent_temperature,
            max_iterations=agent_max_iterations,
            verbose=True,
            enable_alert_buffer=agent_enable_alert_buffer,
            enable_notifications=False
        )
        print("  ✓ Agent 初始化完成\n")
    except Exception as e:
        print(f"  ✗ Agent 初始化失败: {e}\n")
        return None
    
    # [2] 调用 Agent 进行分析
    print("[2/3] Agent 分析日志中...")
    print("-" * 80)
    
    query = f"""
请分析 {log_directory} 所在的服务器状态以及日志文件，生成一份系统健康诊断日报。

要求：
1. **检查服务器状态**：使用工具检查 CPU、内存、磁盘等资源使用情况，确认是否存在资源瓶颈（特别是磁盘空间）。
2. 读取所有可用的日志文件（如 bms-server.log, devices-server.log, rocketmq.log 等）。
3. 识别其中的错误和异常。
4. **关键：识别级联故障**，分析各服务之间的依赖关系。例如，分析 RocketMQ 挂掉或数据库报错是否由磁盘空间满等系统资源问题引起。
5. 分析各服务之间的依赖关系，找出根本原因。
6. 最终输出必须是严格的 JSON 格式，包含 msgtype="markdown" 和完整的 markdown 报告。

环境：{environment}
时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """.strip()
    
    try:
        result = agent.diagnose(query)
        print("-" * 80)
        print("  ✓ 分析完成\n")
    except Exception as e:
        print(f"\n  ✗ Agent 分析失败: {e}\n")
        import traceback
        traceback.print_exc()
        return None
    
    # [3] 解析和验证 JSON 输出
    print("[3/3] 验证和处理输出...")
    
    output_text = result.get('output', '')
    
    # 清理 LLM 可能生成的非法转义字符（如 \-）
    # 重点修复：LLM 在 JSON 中误将 Markdown 列表符转义为 \- 的问题
    if isinstance(output_text, str):
        output_text = output_text.replace('\\-', '-')
        # 处理其他可能的非法转义，如 \# 或 \*
        output_text = output_text.replace('\\#', '#').replace('\\*', '*')
    
    # 尝试从 Agent 输出中提取 JSON
    parsed_json = None
    try:
        # 尝试直接解析
        parsed_json = json.loads(output_text)
    except json.JSONDecodeError:
        # 如果失败，尝试多种提取策略
        import re
        
        # 策略 1：提取 markdown 代码块中的 JSON (```json ... ```)
        json_code_block = re.search(r'```json\s*\n(.*?)\n```', output_text, re.DOTALL)
        if json_code_block:
            try:
                parsed_json = json.loads(json_code_block.group(1))
                print("  ✓ 从 markdown 代码块中提取 JSON 成功")
            except:
                pass
        
        # 策略 2：提取 Final Answer 后的 JSON
        if not parsed_json:
            final_answer_match = re.search(r'Final Answer:\s*```json\s*\n(.*?)\n```', output_text, re.DOTALL | re.IGNORECASE)
            if final_answer_match:
                try:
                    parsed_json = json.loads(final_answer_match.group(1))
                    print("  ✓ 从 Final Answer 中提取 JSON 成功")
                except:
                    pass
        
        # 策略 3：直接提取最外层的 JSON 对象
        if not parsed_json:
            json_match = re.search(r'\{.*\}', output_text, re.DOTALL)
            if json_match:
                try:
                    parsed_json = json.loads(json_match.group())
                    print("  ✓ 使用正则提取 JSON 成功")
                except:
                    pass
    
    # 检查是否解析成功且没有异常中断
    if not parsed_json or "Agent stopped" in str(output_text):
        # 如果无法解析，或者 Agent 异常中止，构建基础体检报告
        print("  ⚠️ Agent 诊断异常中断，自动构建基础体检报告...")
        
        # 调试：打印原始输出，以便分析为什么中断
        print("\n[DEBUG] Agent 原始输出内容片段:")
        print(f"{'-'*40}\n{output_text[:1000]}\n{'-'*40}\n")
        from tools.system_monitor import check_system_status, check_service_status
        
        try:
            sys_stat = check_system_status.invoke("")
            svc_stat = check_service_status.invoke("")
        except:
            sys_stat = "无法获取系统状态"
            svc_stat = "无法获取服务状态"

        parsed_json = {
            "level": "P0", # Agent 异常中断视为高风险
            "msgtype": "markdown",
            "markdown": {
                "title": f"🔍 [{environment.upper()}] 系统诊断基础报告",
                "text": f"# 系统基础诊断报告 (Agent 异常中断恢复)\n\n"
                        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                        f"⚠️ **警告**: AI Agent 在深度日志分析过程中异常中断。以下是自动获取的基础状态数据：\n\n"
                        f"## 🖥️ 系统状态\n\n{sys_stat}\n\n"
                        f"{svc_stat}\n\n"
                        f"## 🚨 核心问题\n\nAI Agent 无法完成深度日志分析，请人工检查上述服务状态。故障原因可能是：\n"
                        f"1. 日志量过大导致分析超时\n"
                        f"2. 诊断逻辑复杂度超出限制\n"
                        f"3. JSON 解析失败（请检查 Agent 输出格式）\n\n"
                        f"## 📊 系统整体评估\n\n"
                        f"- **健康状态**: ⚠️ 待核实 (Agent 中断)\n"
                        f"- **业务影响**: ⚠️ 待核实\n"
                        f"- **风险等级**: P0 - 极高风险 (诊断流程异常中断) "
            }
        }
    
    # 验证 JSON 格式
    try:
        json.dumps(parsed_json)
        print("  ✓ JSON 格式验证通过\n")
    except:
        print("  ⚠ JSON 格式验证失败，但仍将尝试发送\n")
    
    return parsed_json



def main():
    """主函数 - AI Agent 每日系统健康诊断"""
    
    # 从环境变量读取配置
    environment = os.getenv("LOG_ENVIRONMENT", "prod").lower()
    log_directory = os.getenv("LOG_DIRECTORY", "D:\\Python\\agent\\log_agent\\data")
    agent_temperature = float(os.getenv("AGENT_TEMPERATURE", "0.3"))
    agent_max_iterations = int(os.getenv("AGENT_MAX_ITERATIONS", "15"))
    agent_enable_alert_buffer = os.getenv("AGENT_ENABLE_ALERT_BUFFER", "true").lower() == "true"
    agent_enable_notifications = os.getenv("AGENT_ENABLE_NOTIFICATIONS", "true").lower() == "true"
    
    # 调试信息：打印实际读取的环境变量
    print("\n【配置诊断】")
    print(f"LOG_DIRECTORY (from .env): {log_directory}")
    print(f"LOG_ENVIRONMENT (from .env): {environment}")
    print(f"AGENT_TEMPERATURE (from .env): {agent_temperature}")
    print(f"AGENT_MAX_ITERATIONS (from .env): {agent_max_iterations}")
    
    # 验证配置
    log_dir_path = Path(log_directory)
    print(f"\n【路径验证】")
    print(f"日志目录绝对路径: {log_dir_path.absolute()}")
    print(f"日志目录是否存在: {log_dir_path.exists()}")
    
    if log_dir_path.exists():
        # 列出目录中的日志文件
        log_files = list(log_dir_path.glob("*.log"))
        print(f"找到的日志文件数: {len(log_files)}")
        
        # 打印需要分析的日志文件列表
        default_log_files = [f"{app}.log" for app in APP_LIST]
        print(f"\n需要分析的日志文件列表:")
        for i, log_file in enumerate(default_log_files, 1):
            found_status = "[找到]" if (log_dir_path / log_file).exists() else "[未找到]"
            print(f"  {i}. {log_file} {found_status}")
    else:
        print(f"\n错误: 日志目录不存在 - {log_directory}")
        print(f"请检查 .env 文件中的 LOG_DIRECTORY 配置")
        print(f"\n尝试检查当前工作目录:")
        print(f"  当前目录: {os.getcwd()}")
        print(f"  .env 文件位置: {Path('.env').absolute()}")
        print(f"  .env 是否存在: {Path('.env').exists()}")
        if Path('.env').exists():
            print(f"\n.env 文件内容 (前 20 行):")
            try:
                with open('.env', 'r') as f:
                    lines = f.readlines()[:20]
                    for line in lines:
                        if not line.startswith('#'):
                            print(f"  {line.rstrip()}")
            except:
                pass
        return
    
    try:
        # 使用 AI Agent 生成日报
        print("\n【每日系统健康诊断】")
        print("正在启动 AI Agent 对系统进行深度分析...\n")
        
        message = generate_ai_health_report(
            log_directory=log_directory,
            environment=environment,
            agent_temperature=agent_temperature,
            agent_max_iterations=agent_max_iterations,
            agent_enable_alert_buffer=agent_enable_alert_buffer
        )
        
        if message:
            # 显示生成的 JSON 报告
            print(f"\n{'='*80}")
            print("✓ AI Agent 生成的诊断报告（JSON 格式）:")
            print(f"{'='*80}\n")
            print(json.dumps(message, indent=2, ensure_ascii=False))
            
            # 增强报告：统一头部格式并自动补充服务状态
            # 兼容性处理：处理 Agent 可能输出的扁平化 JSON (如 {"markdown.text": "..."})
            if 'markdown.text' in message and 'markdown' not in message:
                message['markdown'] = {'text': message.pop('markdown.text')}
            
            if 'markdown' in message and 'text' in message.get('markdown', {}):
                report_text = message['markdown']['text']
                
                # 1. 确保头部标题和时间存在
                if "系统健康诊断报告" not in report_text:
                    import socket
                    hostname = socket.gethostname()
                    username = os.getenv("USER", os.getenv("USERNAME", "unknown"))
                    
                    # 如果非生产环境，添加测试标记
                    title_suffix = " (此为测试，请忽略)" if environment.lower() != "prod" else ""
                    header = f"# 系统健康诊断报告{title_suffix}\n\n"
                    header += f"**环境**: {environment.upper()} | **主机**: {hostname} | **用户**: {username}\n\n"
                    header += f"**分析时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    report_text = header + report_text
                
                from tools.system_monitor import check_system_status, check_service_status
                
                # 2. 自动补充系统状态信息（如果不存在）
                if "## 🖥️ 系统状态" not in report_text:
                    try:
                        system_status = check_system_status("")
                        # 注入到分析时间之后
                        if "**分析时间**:" in report_text:
                            parts = report_text.split("**分析时间**:")
                            sub_parts = parts[1].split("\n", 1)
                            after_time = sub_parts[1] if len(sub_parts) > 1 else ""
                            report_text = parts[0] + "**分析时间**:" + sub_parts[0] + "\n\n" + system_status + "\n\n" + after_time
                        else:
                            report_text = report_text + "\n\n" + system_status
                    except:
                        pass

                # 3. 自动补充业务服务监控（如果不存在）
                if "业务服务监控" not in report_text:
                    try:
                        service_status = check_service_status("")
                        # 注入到系统状态之后
                        if "## 🖥️ 系统状态" in report_text:
                            parts = report_text.split("## 🖥️ 系统状态")
                            # 找到系统状态这一节的结尾
                            next_section_idx = parts[1].find("## ")
                            if next_section_idx != -1:
                                report_text = parts[0] + "## 🖥️ 系统状态" + parts[1][:next_section_idx] + "\n" + service_status + "\n\n" + parts[1][next_section_idx:]
                            else:
                                report_text = report_text.rstrip() + "\n\n" + service_status
                    except:
                        pass
                
                message['markdown']['text'] = report_text
            
            # 调用钉钉盘管理器发送
            if agent_enable_notifications:
                print(f"\n{'='*80}")
                print("发送到钉钉...")
                print(f"{'='*80}\n")
                
                try:
                    notif = NotificationManager(auto_load_from_env=True)
                    
                    if not notif.dingtalk_access_token or not notif.dingtalk_secret:
                        print("[提示] 钉钉未配置，报告已生成但未发送")
                        print("       请在 .env 文件配置 DINGTALK_ACCESS_TOKEN 和 DINGTALK_SECRET")
                    else:
                        # 提取通知级别：优先从顶级获取，其次尝试从 markdown 内部获取
                        level = message.get('level') or message.get('markdown', {}).get('level', 'P3')
                        
                        # 安全提取报告正文：兼容嵌套、扁平化及降级到最长字符串
                        report_content = ""
                        if 'markdown' in message and isinstance(message['markdown'], dict):
                            report_content = message['markdown'].get('text', "")
                        elif 'markdown.text' in message:
                            report_content = message['markdown.text']
                        
                        if not report_content and isinstance(message, dict):
                            # 最后的兜底：找最长的字符串值
                            strings = [v for v in message.values() if isinstance(v, str)]
                            if strings:
                                report_content = max(strings, key=len)

                        # 发送到钉钉
                        success = notif.handle_alert({
                            'exception_type': 'AIHealthReport',
                            'exception_message': report_content or "未能提取报告正文",
                            'level': level,
                            'location': log_directory,
                            'device_id': f'{environment.upper()}',
                            'root_cause': 'Daily health check report generated by AI Agent'
                        })
                        
                        if success:
                            print("✓ 报告已发送到钉钉\n")
                        else:
                            print("✗ 发送到钉钉失败\n")
                except Exception as e:
                    print(f"✗ 钉钉发送异常: {e}\n")
                    import traceback
                    traceback.print_exc() # 打印详细堆栈到日志
        else:
            print("✗ 未能生成报告\n")
    
    except KeyboardInterrupt:
        print("\n程序已中断")
        return
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
