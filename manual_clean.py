"""
手动日志清理脚本
用于直接调用 tools/log_cleaner.py 中的功能，释放磁盘空间。
"""
import os
import argparse
from dotenv import load_dotenv
from tools.log_cleaner import clean_app_logs

def main():
    # 加载环境变量
    load_dotenv()
    
    # 默认从环境变量读取日志目录
    default_log_dir = os.getenv("LOG_DIRECTORY", "D:\\Python\\agent\\log_agent\\data")
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="手动清理应用历史日志文件")
    parser.add_argument("--dir", type=str, default=default_log_dir, help=f"指定要清理的日志目录 (默认: {default_log_dir})")
    parser.add_argument("--limit", type=int, default=100, help="单次清理的最大文件数 (默认: 100)")
    parser.add_argument("--yes", action="store_true", help="跳过确认直接执行")
    
    args = parser.parse_args()
    
    print("\n" + "="*50)
    print("🚀 手动日志清理工具启动")
    print(f"目标目录: {args.dir}")
    print(f"清理上限: {args.limit} 个文件")
    print("="*50 + "\n")
    
    if not os.path.exists(args.dir):
        print(f"❌ 错误: 目标目录不存在 -> {args.dir}")
        return

    if not args.yes:
        confirm = input(f"即将清理 {args.dir} 中的应用历史日志，是否继续? (y/n): ")
        if confirm.lower() != 'y':
            print("🚫 操作已取消")
            return

    print("\n开始执行清理...")
    # 注意：clean_app_logs 是一个被 @tool 装饰的 LangChain 工具
    # 对于多参数工具，必须使用 .invoke() 并传入字典格式的参数
    result = clean_app_logs.invoke({
        "log_directory": args.dir, 
        "max_files_to_delete": args.limit
    })
    
    print("\n" + "-"*50)
    print("📊 清理结果汇报:")
    print(result)
    print("-"*50 + "\n")
    print("✅ 操作完成")

if __name__ == "__main__":
    main()
