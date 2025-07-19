"""测试运行时导入符号的冲突检测问题"""

import ast
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent))

from scripts.advanced_merge import ContextAwareVisitor, AdvancedCodeMerger

def test_runtime_import_collection():
    """测试 _collect_runtime_import_dependencies 的符号收集逻辑"""
    
    # 创建测试代码
    test_code = '''
try:
    import orjson as json
except ImportError:
    import json

def process_data(data):
    return json.dumps(data)
'''
    
    # 解析AST
    tree = ast.parse(test_code)
    
    # 创建访问器并分析
    visitor = ContextAwareVisitor(Path("/tmp"), Path("/tmp"))
    visitor.current_module_path = Path("test_module.py")
    visitor.analyze_module_ast(tree, Path("test_module.py"))
    
    # 输出所有符号信息
    print("=== 所有符号 ===")
    for qname, symbol in visitor.all_symbols.items():
        print(f"{qname}: type={symbol.symbol_type}, is_runtime={symbol.is_runtime_import}, "
              f"scope_module={symbol.scope.module_path if symbol.scope else 'None'}")
    
    # 创建合并器并收集运行时导入依赖
    merger = AdvancedCodeMerger(visitor)
    
    # 获取 process_data 函数符号
    process_data_symbol = visitor.all_symbols.get("test_module.process_data")
    if process_data_symbol:
        runtime_deps = merger._collect_runtime_import_dependencies([process_data_symbol])
        print("\n=== 运行时导入依赖 ===")
        for dep in runtime_deps:
            print(f"{dep.qname}: type={dep.symbol_type}, is_runtime={dep.is_runtime_import}")
    
    # 分析问题：条件判断是否正确匹配了符号
    print("\n=== 分析第 1049-1053 行的条件 ===")
    for module_symbol in visitor.all_symbols.values():
        if module_symbol.symbol_type == 'module' and module_symbol.init_statements:
            print(f"\n检查模块: {module_symbol.qname}")
            for stmt in module_symbol.init_statements:
                if isinstance(stmt, ast.Try) and visitor._is_try_import_error(stmt):
                    print("  找到 try...except ImportError 块")
                    for try_stmt in stmt.body:
                        if isinstance(try_stmt, ast.Import):
                            for alias in try_stmt.names:
                                alias_name = alias.asname or alias.name.split('.')[0]
                                print(f"    Import 语句: import {alias.name}" + 
                                      (f" as {alias.asname}" if alias.asname else ""))
                                print(f"    期望找到的别名: {alias_name}")
                                
                                # 查找匹配的符号
                                found = False
                                for sym in visitor.all_symbols.values():
                                    if (sym.symbol_type == 'import_alias' and 
                                        sym.is_runtime_import and
                                        sym.scope.module_path == module_symbol.scope.module_path):
                                        print(f"      找到运行时导入符号: {sym.qname}, name={sym.name}")
                                        if sym.name == alias_name:
                                            print(f"        ✓ 匹配!")
                                            found = True
                                        else:
                                            print(f"        ✗ 不匹配 (期望 {alias_name}, 实际 {sym.name})")
                                
                                if not found:
                                    print(f"      ✗ 没有找到匹配的符号!")

if __name__ == "__main__":
    test_runtime_import_collection()