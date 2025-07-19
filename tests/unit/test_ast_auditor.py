"""
AST 审计器的单元测试

测试各个组件的独立功能：
- SymbolTableBuilder: 符号表构建
- ReferenceValidator: 引用验证
- PatternChecker: 模式检查
- ASTAuditor: 主审计器
"""

import pytest
import ast
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.ast_auditor import (
    SymbolTableBuilder, 
    ReferenceValidator, 
    PatternChecker,
    ASTAuditor,
    SymbolInfo,
    ScopeInfo
)


class TestSymbolTableBuilder:
    """测试符号表构建器"""
    
    def test_simple_function_definition(self):
        """测试简单函数定义的符号记录"""
        code = """
def hello():
    pass
"""
        tree = ast.parse(code)
        builder = SymbolTableBuilder()
        builder.visit(tree)
        
        # 验证模块作用域包含 hello 函数
        assert 'hello' in builder.module_scope.symbols
        assert builder.module_scope.symbols['hello'].type == 'function'
        assert builder.module_scope.symbols['hello'].lineno == 2
        
    def test_class_definition(self):
        """测试类定义的符号记录"""
        code = """
class MyClass:
    def method(self):
        pass
"""
        tree = ast.parse(code)
        builder = SymbolTableBuilder()
        builder.visit(tree)
        
        # 验证模块作用域包含类
        assert 'MyClass' in builder.module_scope.symbols
        assert builder.module_scope.symbols['MyClass'].type == 'class'
        
        # 验证类作用域包含方法
        class_scope = builder.module_scope.children[0]
        assert class_scope.name == 'MyClass'
        assert 'method' in class_scope.symbols
        
    def test_duplicate_definitions_detection(self):
        """测试重复定义检测"""
        code = """
def func():
    pass
    
def func():  # 重复定义
    pass
"""
        tree = ast.parse(code)
        builder = SymbolTableBuilder()
        builder.visit(tree)
        
        # 验证检测到重复定义
        assert len(builder.duplicate_definitions) == 1
        assert builder.duplicate_definitions[0][0] == 'func'
        assert builder.duplicate_definitions[0][1] == [2, 5]
        
    def test_import_handling(self):
        """测试导入语句处理"""
        code = """
import os
from sys import path as sys_path
from typing import List, Dict
"""
        tree = ast.parse(code)
        builder = SymbolTableBuilder()
        builder.visit(tree)
        
        # 验证导入的符号
        assert 'os' in builder.module_scope.symbols
        assert 'sys_path' in builder.module_scope.symbols  # 使用别名
        assert 'List' in builder.module_scope.symbols
        assert 'Dict' in builder.module_scope.symbols
        
    def test_nested_scopes(self):
        """测试嵌套作用域"""
        code = """
def outer():
    x = 1
    def inner():
        y = 2
        return x + y
    return inner
"""
        tree = ast.parse(code)
        builder = SymbolTableBuilder()
        builder.visit(tree)
        
        # 验证作用域嵌套结构
        outer_scope = None
        for child in builder.module_scope.children:
            if child.name == 'outer':
                outer_scope = child
                break
                
        assert outer_scope is not None
        assert 'x' in outer_scope.symbols
        
        inner_scope = outer_scope.children[0]
        assert inner_scope.name == 'inner'
        assert 'y' in inner_scope.symbols


class TestReferenceValidator:
    """测试引用验证器"""
    
    def test_undefined_reference_detection(self):
        """测试未定义引用检测"""
        code = """
def func():
    return undefined_var
"""
        tree = ast.parse(code)
        
        # 先构建符号表
        builder = SymbolTableBuilder()
        builder.visit(tree)
        
        # 然后验证引用
        validator = ReferenceValidator(builder.module_scope)
        validator.visit(tree)
        
        # 验证检测到未定义的引用
        assert len(validator.undefined_names) == 1
        assert validator.undefined_names[0][0] == 'undefined_var'
        
    def test_builtin_names_not_reported(self):
        """测试内置名称不应被报告为未定义"""
        code = """
def func():
    return len([1, 2, 3])
"""
        tree = ast.parse(code)
        
        builder = SymbolTableBuilder()
        builder.visit(tree)
        
        validator = ReferenceValidator(builder.module_scope)
        validator.visit(tree)
        
        # len 是内置函数，不应被报告
        assert len(validator.undefined_names) == 0
        
    def test_scope_resolution(self):
        """测试作用域解析"""
        code = """
global_var = 1

def func():
    local_var = 2
    return global_var + local_var
"""
        tree = ast.parse(code)
        
        builder = SymbolTableBuilder()
        builder.visit(tree)
        
        validator = ReferenceValidator(builder.module_scope)
        validator.visit(tree)
        
        # 所有引用都应该被正确解析
        assert len(validator.undefined_names) == 0


class TestPatternChecker:
    """测试模式检查器"""
    
    def test_single_main_block_allowed(self):
        """测试单个主块是允许的"""
        code = """
def main():
    pass
    
if __name__ == "__main__":
    main()
"""
        tree = ast.parse(code)
        checker = PatternChecker()
        checker.visit(tree)
        
        assert len(checker.main_blocks) == 1
        
    def test_multiple_main_blocks_detected(self):
        """测试检测多个主块"""
        code = """
if __name__ == "__main__":
    print("First main")
    
def func():
    pass
    
if __name__ == "__main__":
    print("Second main")
"""
        tree = ast.parse(code)
        checker = PatternChecker()
        checker.visit(tree)
        
        assert len(checker.main_blocks) == 2
        assert checker.main_blocks == [2, 8]


class TestASTAuditor:
    """测试主审计器"""
    
    def test_syntax_error_handling(self):
        """测试语法错误处理"""
        code = "def func(:\n    pass"  # 语法错误
        
        auditor = ASTAuditor()
        result = auditor.audit(code)
        
        assert not result
        assert len(auditor.errors) == 1
        assert "语法错误" in auditor.errors[0]
        
    def test_clean_code_passes(self):
        """测试干净的代码应该通过审计"""
        code = """
import os

def calculate(x, y):
    return x + y
    
def main():
    result = calculate(1, 2)
    print(result)
    
if __name__ == "__main__":
    main()
"""
        auditor = ASTAuditor()
        result = auditor.audit(code)
        
        assert result
        assert len(auditor.errors) == 0
        assert "审计通过" in auditor.get_report()
        
    def test_comprehensive_error_detection(self):
        """测试综合错误检测"""
        code = """
def func():
    return func()
    
def func():  # 重复定义
    return undefined_var  # 未定义引用
    
if __name__ == "__main__":
    func()
    
if __name__ == "__main__":  # 多个主块
    func()
"""
        auditor = ASTAuditor()
        result = auditor.audit(code)
        
        assert not result
        # 应该检测到多种错误
        report = auditor.get_report()
        assert "重复定义" in report
        assert "未定义的名称" in report
        assert "多个 'if __name__" in report
        
    def test_report_formatting(self):
        """测试报告格式"""
        code = """
def func():
    return undefined
"""
        auditor = ASTAuditor()
        auditor.audit(code)
        
        report = auditor.get_report()
        assert "=== 错误 ===" in report
        assert "✗" in report  # 错误标记
        assert "undefined" in report