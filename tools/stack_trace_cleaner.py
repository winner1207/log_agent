"""
堆栈跟踪清洗器 (Stack Trace Cleaner)

目标：优化 Java 异常堆栈，减少 Token 消耗，突出根因
清洗策略：
1. 提取 Caused by：通常最底层的 Caused by 才是根因
2. 业务包名过滤：过滤 org.springframework, org.apache 等框架堆栈，保留 cn.iocoder 等业务代码
3. 简化输出：只保留关键堆栈行
"""
import re
from typing import List, Dict, Optional, Tuple


class StackTraceAnalyzer:
    """Java 异常堆栈分析器"""
    
    # 框架包过滤列表（这些包中的堆栈行会被忽略）
    FRAMEWORK_PACKAGES = [
        'org.springframework',
        'org.apache',
        'java.lang',
        'java.util',
        'java.io',
        'com.sun',
        'sun.',
        'org.junit',
        'org.mockito',
    ]
    
    # 业务包名（保留这些包中的堆栈）
    BUSINESS_PACKAGES = [
        'cn.',
        'com.iocoder',
        'application',
    ]
    
    def __init__(self, raw_stacktrace: str):
        """
        初始化堆栈分析器
        
        Args:
            raw_stacktrace: 原始堆栈跟踪字符串
        """
        self.raw_stacktrace = raw_stacktrace
        self.lines = raw_stacktrace.split('\n')
    
    def extract_caused_by_chain(self) -> List[str]:
        """
        提取 Caused by 链
        
        通常最底层的 Caused by 才是根因
        """
        caused_by_lines = []
        
        for i, line in enumerate(self.lines):
            if 'Caused by:' in line:
                # 找到 Caused by 行及其后续的堆栈行
                caused_by_lines.append(line)
                
                # 收集该 Caused by 后面的堆栈行（直到下一个 Caused by 或其他关键行）
                j = i + 1
                while j < len(self.lines):
                    next_line = self.lines[j]
                    if 'Caused by:' in next_line:
                        break
                    if next_line.strip() and not next_line.startswith(' '):
                        break
                    if 'at ' in next_line or next_line.startswith('\t'):
                        caused_by_lines.append(next_line)
                    j += 1
        
        return caused_by_lines
    
    def is_business_package(self, line: str) -> bool:
        """判断堆栈行是否来自业务包"""
        for pkg in self.BUSINESS_PACKAGES:
            if pkg in line:
                return True
        return False
    
    def is_framework_package(self, line: str) -> bool:
        """判断堆栈行是否来自框架包"""
        for pkg in self.FRAMEWORK_PACKAGES:
            if pkg in line:
                return True
        return False
    
    def filter_stacktrace_lines(self, stacktrace_lines: List[str], 
                               keep_framework: bool = False) -> List[str]:
        """
        过滤堆栈行，保留业务代码堆栈
        
        Args:
            stacktrace_lines: 堆栈行列表
            keep_framework: 是否保留前几行框架堆栈（用于上下文）
            
        Returns:
            过滤后的堆栈行
        """
        filtered = []
        framework_lines = []
        
        for line in stacktrace_lines:
            if not line.strip():
                continue
            
            # 保留 Caused by 行
            if 'Caused by:' in line:
                filtered.append(line)
                framework_lines = []  # 重置框架行缓冲
                continue
            
            # 检查是否是业务包
            if self.is_business_package(line):
                filtered.extend(framework_lines[-2:])  # 保留最近两行框架堆栈作为上下文
                filtered.append(line)
                framework_lines = []
            elif not self.is_framework_package(line):
                # 既不是业务包也不是框架包的行（可能是其他信息）
                filtered.append(line)
            else:
                # 缓存框架行
                framework_lines.append(line)
        
        return filtered
    
    def clean_stacktrace(self) -> Dict[str, any]:
        """
        清洁堆栈跟踪
        
        Returns:
            包含清洁后堆栈信息的字典
        """
        # 提取异常类型和消息
        first_line = self.lines[0] if self.lines else ""
        exception_match = re.match(r'([\w.]+):\s*(.*)', first_line)
        
        exception_type = exception_match.group(1) if exception_match else "Unknown"
        exception_message = exception_match.group(2) if exception_match else first_line
        
        # 提取 Caused by 链
        caused_by_chain = self.extract_caused_by_chain()
        
        if caused_by_chain:
            # 提取最底层的根因
            root_cause = self._extract_root_cause(caused_by_chain)
            filtered_cause = self.filter_stacktrace_lines(caused_by_chain)
        else:
            # 如果没有 Caused by，过滤主异常堆栈
            root_cause = exception_type
            filtered_cause = self.filter_stacktrace_lines(self.lines[1:])
        
        return {
            'exception_type': exception_type,
            'exception_message': exception_message,
            'root_cause': root_cause,
            'filtered_stacktrace': '\n'.join(filtered_cause),
            'cleaned_stacktrace_lines': filtered_cause,
        }
    
    def _extract_root_cause(self, caused_by_lines: List[str]) -> str:
        """从 Caused by 链中提取根因"""
        # 最后一个 Caused by 通常是根因
        for line in reversed(caused_by_lines):
            if 'Caused by:' in line:
                return line.replace('Caused by:', '').strip()
        
        return caused_by_lines[-1] if caused_by_lines else "Unknown"


def clean_java_stacktrace(raw_stacktrace: str) -> Dict:
    """
    清洁 Java 异常堆栈
    
    Args:
        raw_stacktrace: 原始堆栈跟踪字符串
        
    Returns:
        包含清洁后堆栈的字典
    """
    analyzer = StackTraceAnalyzer(raw_stacktrace)
    return analyzer.clean_stacktrace()


def format_for_llm(cleaned_data: Dict) -> str:
    """
    将清洁后的堆栈格式化为 LLM 输入
    
    Args:
        cleaned_data: clean_stacktrace() 返回的字典
        
    Returns:
        格式化的堆栈信息字符串
    """
    result = f"""异常分析信息：

【异常类型】
{cleaned_data['exception_type']}

【异常消息】
{cleaned_data['exception_message']}

【根因】
{cleaned_data['root_cause']}

【关键堆栈跟踪】（已过滤框架代码，仅保留业务相关行）
{cleaned_data['filtered_stacktrace']}
"""
    return result.strip()


# 示例使用
if __name__ == "__main__":
    # 模拟一个 Java 异常堆栈
    sample_stacktrace = """java.lang.NullPointerException: Cannot invoke method 'save' on null object
	at org.springframework.web.servlet.DispatcherServlet.dispatch(DispatcherServlet.java:987)
	at org.springframework.web.servlet.DispatcherServlet.doDispatch(DispatcherServlet.java:945)
	at com.iocoder.bms.handler.BatteryStatusHandler.handleBatteryStatus(BatteryStatusHandler.java:156)
	at com.iocoder.bms.service.BatteryService.processBatteryData(BatteryService.java:234)
	at java.lang.Thread.run(Thread.java:745)
Caused by: java.lang.IllegalArgumentException: Battery voltage cannot be negative
	at com.iocoder.bms.validator.BatteryValidator.validateVoltage(BatteryValidator.java:45)
	at com.iocoder.bms.service.BatteryService.validateAndSave(BatteryService.java:89)
	at org.springframework.orm.jpa.JpaTransactionManager.doCommit(JpaTransactionManager.java:567)
	at org.springframework.transaction.support.AbstractPlatformTransactionManager.commit(AbstractPlatformTransactionManager.java:363)
	at com.iocoder.bms.repository.BatteryRepository.save(BatteryRepository.java:78)
Caused by: java.lang.NumberFormatException: For input string: "abc"
	at java.lang.Integer.parseInt(Integer.java:615)
	at com.iocoder.bms.parser.DataParser.parseVoltage(DataParser.java:123)
	at com.iocoder.bms.handler.BatteryStatusHandler.parseDeviceData(BatteryStatusHandler.java:89)"""
    
    result = clean_java_stacktrace(sample_stacktrace)
    print("=== 清洗结果 ===")
    print(f"异常类型: {result['exception_type']}")
    print(f"异常消息: {result['exception_message']}")
    print(f"根因: {result['root_cause']}")
    print("\n=== 过滤后的堆栈 ===")
    print(result['filtered_stacktrace'])
    print("\n=== LLM 格式化输入 ===")
    print(format_for_llm(result))
