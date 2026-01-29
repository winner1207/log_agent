"""
IoT 诊断 Agent 类 - 基于 LangChain 框架封装

实现了一个能自动分析 BMS 异常日志的 Agent，采用 ReAct (Reason+Act) 模式。
包含两个自定义工具：
  1. LogRetriever: 从日志文件读取设备报错信息
  2. CodeInterpreter: 使用 Python 执行统计分析

当前实现：AgentExecutor (Legacy)
未来升级路径：LangGraph
"""
import os
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import PromptTemplate
from langchain_core.tools import BaseTool

from tools.code_interpreter import execute_analysis_code, calculate_frequency_analysis
from tools.stack_trace_cleaner import clean_java_stacktrace, format_for_llm
from tools.log_reader import read_recent_logs, analyze_log_patterns, get_log_summary_stats
from tools.log_cleaner import clean_app_logs
from tools.device_anomaly_analyzer import analyze_device_anomalies
from tools.system_monitor import check_system_status, check_service_status
from tools.alert_buffer import AlertBuffer
from tools.notification_manager import NotificationManager


class IotDiagnosisAgent:
    """
    IoT 诊断 Agent 类
    
    能够：
    - 从日志文件查询设备错误信息
    - 执行 Python 代码进行统计分析
    - 生成诊断报告
    
    使用 ReAct 框架进行多步骤推理和规划
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_id: Optional[str] = None,
        temperature: float = 0,
        max_iterations: int = 10,
        verbose: bool = True,
        enable_alert_buffer: bool = True,
        enable_notifications: bool = False
    ):
        """
        初始化 IoT 诊断 Agent
        
        Args:
            api_key: DeepSeek API 密钥，如果不提供则从环境变量读取
            base_url: API 基础 URL，如果不提供则从环境变量读取
            model_id: 模型 ID，如果不提供则从环境变量读取
            temperature: 温度参数，控制输出随机性
            max_iterations: Agent 最大迭代次数
            verbose: 是否输出详细日志
            enable_alert_buffer: 是否启用告警缓冲池
            enable_notifications: 是否启用分级通知
        """
        # 加载环境变量
        load_dotenv()
        
        # 配置 API 参数
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model_id = model_id or os.getenv("DEEPSEEK_MODEL_ID", "deepseek-chat")
        self.temperature = temperature
        self.max_iterations = max_iterations
        self.verbose = verbose
        
        # 初始化告警缓冲池
        self.alert_buffer = AlertBuffer() if enable_alert_buffer else None
        
        # 初始化通知管理器
        if enable_notifications:
            self.notification_manager = NotificationManager(
                dingtalk_access_token=os.getenv("DINGTALK_ACCESS_TOKEN"),
                dingtalk_secret=os.getenv("DINGTALK_SECRET"),
                smtp_server=os.getenv("SMTP_SERVER"),
                smtp_port=int(os.getenv("SMTP_PORT", "587")),
                email_account=os.getenv("EMAIL_ACCOUNT"),
                email_password=os.getenv("EMAIL_PASSWORD")
            )
        else:
            self.notification_manager = None
        
        # 初始化 LLM
        self.llm = self._initialize_llm()
        
        # 初始化工具
        self.tools = self._initialize_tools()
        
        # 创建 Prompt
        self.prompt = self._create_prompt()
        
        # 创建 Agent 执行器
        self.agent_executor = self._create_agent_executor()
    
    def _initialize_llm(self) -> ChatOpenAI:
        """初始化大语言模型"""
        return ChatOpenAI(
            model=self.model_id,
            openai_api_key=self.api_key,
            openai_api_base=self.base_url,
            temperature=self.temperature,
            verbose=self.verbose
        )
    
    def _initialize_tools(self) -> List[BaseTool]:
        """初始化工具列表"""
        return [
            # 新增：业务服务存活检测工具
            check_service_status,
            # 新增：系统状态监控工具
            check_system_status,
            # 新增：日志读取工具（Agent 自主分析日志）
            read_recent_logs,
            analyze_log_patterns,
            get_log_summary_stats,
            # 新增：日志清理工具
            clean_app_logs,
            # 新增：设备上报异常监控工具
            analyze_device_anomalies,
            # 原有工具
            execute_analysis_code,
            calculate_frequency_analysis
        ]
    
    def _create_prompt(self) -> PromptTemplate:
        """
        创建 ReAct 风格的 Prompt 模板
        
        针对日报场景优化的 Prompt，支持级联故障识别
        """
        template = """你是一位资深 Java 系统架构师和 DevOps 专家，专门诊断和分析微服务系统的日志异常和故障。

【核心职责】
1. 通过阅读日志文件，了解当前系统状态
2. **监控系统资源**：检查 CPU、内存、磁盘及**线程总数**等资源状态，识别资源耗尽导致的故障。特别注意：系统线程数超过 20000 属于 P0 级严重异常。
3. **自主维护能力**：如果发现磁盘空间不足（如使用率超过 80%），应主动调用 `clean_app_logs` 工具清理应用历史日志。
4. **设备异常监控**（必须执行）：使用 `analyze_device_anomalies` 工具分析设备上报频率异常（特别是 tcp1801-server.log），识别超高频重发设备（阈值 >30次/分钟），这是设备侧异常的关键指标。
5. 识别系统中的异常和故障模式
6. **关键能力：识别级联故障**
   - 不要将相关的多个错误视为独立问题
   - 例如：devices-server 的报错可能是因为 mysql 连接断开导致的，而 mysql 断开可能是因为磁盘空间满导致的
   - 分析服务间的依赖关系，找出根本原因
7. 生成结构化的日报，包含根因分析和修复建议

【故障分析方法】（必须严格按顺序执行）
1. **第一步**：检查业务服务监控 (check_service_status) 和系统资源状态 (check_system_status)，这是必须完成的基础步骤。
2. **第二步**：调用 `analyze_device_anomalies` 工具分析设备异常，检查是否存在超高频上报设备（>30次/分钟）。这必须在日报中体现。
3. **第三步**：识别宕机服务后，优先读取对应的日志文件进行错误模式分析。
4. **特别注意 RocketMQ**: 如果在根日志目录找不到 `rocketmq.log` 或其内容为空，必须意识到 RocketMQ 日志可能存储在 `rocketmqlogs/rocketmq_client.log`。
5. 识别错误模式和异常堆栈。
6. 分析时间序列和级联关系。
7. **防错指南**: 如果诊断过程中发现信息量过大（如日志读取了数百行），不要尝试处理每一行，应立即总结核心错误（如 Timeout, Connection Refused, Exception）并给出 Final Answer。不要陷入无限循环或过度分析。

【输出格式要求】
Final Answer 必须是一个有效的 JSON 对象，必须包含：
- level: 根据故障严重程度选择 P0/P1/P2/P3。注意：P3 是常规日报级别，不触发 @ 提醒；P1/P2 触发值班人员提醒；P0 触发全员提醒。请务必准确判断并在 JSON 顶级包含此字段。
- markdown.text: 必须严格遵循以下 Markdown 结构，且各部分之间必须有清晰的空行。关键：在“风险等级”处必须带上 P0-3 标识。

## 🖥️ 系统状态

(此处展示 CPU、内存、线程总数、磁盘等硬件资源。如果线程数异常，必须详细列出高线程进程信息)

## 🛠️ 业务服务监控

(此处必须展示 check_service_status 的核心输出)

(此处必须直接插入 analyze_device_anomalies 工具生成的设备异常分析列表，包括其标题“#### 🚩 高频上报设备 Top X”)

## 🚨 核心问题

(此处详细分析故障原因和关联关系，包括对高频上报设备的业务影响分析。特别注意：如果 CPU 使用率高于 60% 且 `analyze_device_anomalies` 发现了超高频设备，请在此处尝试计算 Top 3 设备上报量对系统压力的贡献度，说明它们是否为 CPU 波动的主要诱因)

## 📊 系统整体评估

- **健康状态**: ...
- **业务影响**: ...
- **风险等级**: Px (此处必须包含 P0/P1/P2/P3 标识，并附带文字说明)

建议后续行动：
1. ...
2. ...

关键要求：
- **禁止在 Thought 中直接输出 JSON 结果**，JSON 只能出现在 Final Answer 之后。
- **不要在 Final Answer 中输出无关文字**，只保留 JSON。
- **如果达到迭代限制，请确保已包含已发现的所有关键异常信息。**

你可以使用以下工具：

{tools}

使用以下格式（严格遵守）：

Question: 你必须回答的输入问题
Thought: 你应该总是思考该做什么
Action: 要采取的行动，应该是 [{tool_names}] 中的一个
Action Input: 行动的输入，如果没有特定输入，请传入空字符串 ""
Observation: 行动的结果
... (这个 Thought/Action/Action Input/Observation 可以重复 N 次)
Thought: 我现在已经通过工具获得了所有必要的真实信息，可以给出最终答案了。
Final Answer: 对原始输入问题的最终答案，必须是有效的 JSON 格式

重要提示：
- 必须在得到所有必要信息后，使用 "Final Answer:" 给出最终答案
- 最终答案必须是可解析的 JSON，直接可用于发送到钉钉
- 如果发现故障，务必分析其根本原因和级联关系

开始！

Question: {input}
Thought: {agent_scratchpad}
"""
        return PromptTemplate.from_template(template)
    
    def _create_agent_executor(self) -> AgentExecutor:
        """创建 Agent 执行器"""
        # 创建 ReAct Agent
        agent = create_react_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=self.prompt
        )
        
        # 创建 Agent 执行器（增强错误处理）
        return AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=self.verbose,
            max_iterations=self.max_iterations,
            handle_parsing_errors=True,
            return_intermediate_steps=True,  # 返回中间步骤，便调试
            early_stopping_method="force"  # 强制停止需要的错误
        )
    
    def diagnose(self, query: str) -> Dict[str, Any]:
        """
        运行诊断流程
        
        Args:
            query: 诊断请求，例如 "分析设备 YJP-BMS-001 的故障频率"
            
        Returns:
            包含诊断结果的字典，包括 'input' 和 'output' 字段
        """
        try:
            result = self.agent_executor.invoke({"input": query})
            # 确保 output 字段存在
            if "output" not in result:
                result["output"] = str(result)
            return result
        except KeyError as e:
            # 配置错误或环境变量缺失
            error_output = f"配置错误: {str(e)}"
            self._handle_diagnosis_error(query, "KeyError", str(e))
            return {
                "input": query,
                "output": error_output
            }
        except ValueError as e:
            # 参数验证错误
            error_output = f"参数错误: {str(e)}"
            self._handle_diagnosis_error(query, "ValueError", str(e))
            return {
                "input": query,
                "output": error_output
            }
        except Exception as e:
            # 其他未预期的错误
            error_output = f"诊断过程中发生错误: {str(e)}"
            self._handle_diagnosis_error(query, type(e).__name__, str(e))
            import traceback
            if self.verbose:
                traceback.print_exc()
            return {
                "input": query,
                "output": error_output
            }
    
    def get_diagnosis_report(self, query: str) -> str:
        """
        获取诊断报告文本
        
        Args:
            query: 诊断请求
            
        Returns:
            诊断报告文本
        """
        result = self.diagnose(query)
        return result.get("output", "抱歉，我无法完成诊断。")
    
    def clean_and_analyze_stacktrace(self, stacktrace: str) -> str:
        """
        清洗并分析 Java 堆栈跟踪
        
        Args:
            stacktrace: 原始 Java 堆栈跟踪字符串
            
        Returns:
            LLM 格式化的堆栈信息
        """
        cleaned = clean_java_stacktrace(stacktrace)
        return format_for_llm(cleaned)
    
    def process_alert(self, 
                      exception_type: str,
                      exception_message: str,
                      level: str = "ERROR",
                      location: Optional[str] = None,
                      root_cause: Optional[str] = None,
                      stacktrace: Optional[str] = None,
                      device_id: Optional[str] = None) -> Dict[str, Any]:
        """
        处理告警（含缓冲和通知）
        
        Args:
            exception_type: 异常类型
            exception_message: 异常消息
            level: 告警级别 (FATAL, ERROR, WARN)
            location: 报错位置
            root_cause: 根因
            stacktrace: 堆栈跟踪
            device_id: 设备 ID
            
        Returns:
            包含处理结果的字典
        """
        result = {
            'buffered': False,
            'should_send': False,
            'alert': None,
        }
        
        # 如果启用了告警缓冲，先进行缓冲处理
        if self.alert_buffer:
            should_send, alert = self.alert_buffer.add_alert(
                exception_type=exception_type,
                exception_message=exception_message,
                location=location,
                level=level,
                root_cause=root_cause,
                stacktrace=stacktrace,
                device_id=device_id
            )
            result['buffered'] = True
            result['should_send'] = should_send
            result['alert'] = alert
            
            # 如果应该发送，则通过通知管理器发送
            if should_send and self.notification_manager and alert:
                self.notification_manager.handle_alert(alert)
        else:
            # 未启用缓冲，直接通知
            result['should_send'] = True
            result['buffered'] = False
        
        return result
    
    def _handle_diagnosis_error(self, query: str, error_type: str, error_msg: str):
        """
        处理诊断过程中的错误
        
        Args:
            query: 诊断查询
            error_type: 错误类型
            error_msg: 错误消息
        """
        if self.alert_buffer:
            self.alert_buffer.add_alert(
                exception_type=error_type,
                exception_message=error_msg,
                level="ERROR",
                location=f"IotDiagnosisAgent.diagnose",
                root_cause=f"Query processing failed: {query[:50]}..."
            )
    
    def get_alert_buffer_stats(self) -> Dict[str, Any]:
        """
        获取告警缓冲池统计信息
        
        Returns:
            缓冲池统计数据
        """
        if self.alert_buffer:
            return self.alert_buffer.get_statistics()
        return {}
    
    def get_notification_stats(self) -> Dict[str, Any]:
        """
        获取通知统计信息
        
        Returns:
            通知统计数据
        """
        if self.notification_manager:
            return self.notification_manager.get_statistics()
        return {}
