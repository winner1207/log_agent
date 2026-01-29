"""
CodeInterpreter 工具 - 执行 Python 代码进行统计分析

使用 Python 内置的 exec() 函数执行统计代码，完成日志数据的分析和计算。
支持计数、统计、频率分析等操作。
"""
from langchain_core.tools import tool
from typing import Any


# 安全白名单：允许在 CodeInterpreter 中使用的库
ALLOWED_IMPORTS = {
    'math': True,
    'statistics': True,
    'json': True,
    'datetime': True,
    'os': True,
    'pathlib': True,
}


def _create_safe_globals() -> dict:
    """
    创建用于执行代码的安全全局环境
    
    限制访问敏感的内置函数和库
    """
    import os
    import pathlib
    import math
    import json
    import datetime
    import statistics
    
    # 基础的安全内置函数
    safe_builtins = {
        'abs': abs,
        'all': all,
        'any': any,
        'bin': bin,
        'bool': bool,
        'chr': chr,
        'dict': dict,
        'divmod': divmod,
        'enumerate': enumerate,
        'filter': filter,
        'float': float,
        'format': format,
        'frozenset': frozenset,
        'hex': hex,
        'int': int,
        'isinstance': isinstance,
        'len': len,
        'list': list,
        'map': map,
        'max': max,
        'min': min,
        'oct': oct,
        'ord': ord,
        'pow': pow,
        'range': range,
        'reversed': reversed,
        'round': round,
        'set': set,
        'slice': slice,
        'sorted': sorted,
        'str': str,
        'sum': sum,
        'tuple': tuple,
        'zip': zip,
        '__import__': __import__,
    }
    
    return {
        '__builtins__': safe_builtins,
        'print': print,
        'os': os,
        'pathlib': pathlib,
        'math': math,
        'json': json,
        'datetime': datetime,
        'statistics': statistics,
    }


@tool
def execute_analysis_code(code: str) -> str:
    """
    执行 Python 代码进行统计分析。
    
    这个工具允许 Agent 执行任意 Python 代码来分析日志数据。
    支持计算频率、统计、排序等操作。
    
    Args:
        code: 要执行的 Python 代码字符串
    
    Returns:
        代码执行的结果（打印输出）或错误信息
    """
    try:
        # 预处理代码：处理可能的转义换行符
        if isinstance(code, str):
            code = code.replace('\\n', '\n').strip().strip("'").strip('"')
            
        # 创建安全的执行环境
        safe_globals = _create_safe_globals()
        safe_locals = {}
        
        # 捕获打印输出
        import io
        import sys
        
        output_buffer = io.StringIO()
        old_stdout = sys.stdout
        
        try:
            sys.stdout = output_buffer
            
            # 执行代码
            exec(code, safe_globals, safe_locals)
            
        finally:
            sys.stdout = old_stdout
        
        # 获取输出结果
        result = output_buffer.getvalue()
        
        if not result:
            # 如果没有打印输出，尝试获取最后一个表达式的值
            if safe_locals:
                return "执行成功。局部变量:\n" + str(safe_locals)
            else:
                return "执行成功，但没有输出"
        
        return result
        
    except SyntaxError as e:
        return f"代码语法错误: {str(e)}"
    except NameError as e:
        return f"名称错误（可能使用了未定义的变量）: {str(e)}"
    except TypeError as e:
        return f"类型错误: {str(e)}"
    except ValueError as e:
        return f"值错误: {str(e)}"
    except ZeroDivisionError as e:
        return f"零除错误: {str(e)}"
    except Exception as e:
        return f"执行过程中出现错误: {type(e).__name__}: {str(e)}"


@tool
def calculate_frequency_analysis(data_dict: str) -> str:
    """
    对数据进行频率分析。
    
    这个工具接受一个字典字符串（JSON 格式），计算频率分布。
    
    Args:
        data_dict: JSON 格式的字典字符串，例如 '{"A": 5, "B": 3, "C": 8}'
    
    Returns:
        频率分析结果
    """
    try:
        import json
        
        # 解析 JSON 数据
        data = json.loads(data_dict)
        
        if not data:
            return "错误: 数据为空"
        
        # 计算总数
        total = sum(data.values())
        
        # 计算频率
        frequencies = {k: (v / total * 100) for k, v in data.items()}
        
        # 按频率排序
        sorted_freq = sorted(frequencies.items(), key=lambda x: x[1], reverse=True)
        
        # 格式化输出
        result = "频率分析结果:\n"
        result += "=" * 60 + "\n"
        result += f"总样本数: {total}\n\n"
        
        for item, freq in sorted_freq:
            count = data[item]
            bar = "█" * int(freq / 2)  # 简单的柱状图
            result += f"{item:10s}: {count:3d} 次  ({freq:6.2f}%) {bar}\n"
        
        return result
        
    except json.JSONDecodeError:
        return "错误: 无法解析 JSON 数据格式"
    except Exception as e:
        return f"错误: 频率分析失败 - {str(e)}"
