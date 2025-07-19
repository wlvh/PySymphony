"""简化测试展示运行时导入符号收集的问题"""

# 模拟 _collect_runtime_import_dependencies 的逻辑问题

# 假设我们有以下 try-except 块：
# try:
#     import orjson as json
# except ImportError:
#     import json

# 现在 all_symbols 中有两个符号：
# 1. "module.json" (来自 import orjson as json)
# 2. "module.json" (来自 import json) - 同名冲突！

# 当前的逻辑是：
def current_logic():
    """当前第 1049-1053 行的逻辑"""
    # 对于每个 try 块中的导入语句
    for alias_name in ["json"]:  # import orjson as json
        print(f"处理导入: import orjson as {alias_name}")
        
        # 查找所有运行时导入符号
        for sym_name in ["json", "json"]:  # 两个同名符号
            if True:  # is_runtime_import and same module
                print(f"  - 添加符号: {sym_name}")
                
    print("\n问题：没有检查符号是否真的对应当前的导入语句！")
    print("结果：所有运行时导入符号都被错误地添加了")

# 正确的逻辑应该是：
def correct_logic():
    """修复后的逻辑"""
    # 对于每个 try 块中的导入语句
    for stmt_info in [("orjson", "json"), ("json", None)]:
        module_name, alias_name = stmt_info
        actual_alias = alias_name or module_name.split('.')[0]
        print(f"处理导入: import {module_name}" + (f" as {alias_name}" if alias_name else ""))
        
        # 查找对应的符号
        # 应该根据 actual_alias 来匹配符号
        print(f"  - 查找别名为 '{actual_alias}' 的符号")
        
        # 只添加真正匹配的符号
        if actual_alias == "json":
            print(f"  - 找到匹配的符号: {actual_alias}")

if __name__ == "__main__":
    print("=== 当前的错误逻辑 ===")
    current_logic()
    
    print("\n\n=== 正确的逻辑 ===")
    correct_logic()