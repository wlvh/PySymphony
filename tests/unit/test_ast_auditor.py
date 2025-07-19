"""ASTAuditor 的单元测试"""
import pytest
import sys
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from ast_auditor import ASTAuditor, audit_code, AuditResult


class TestSymbolTableBuilder:
    """测试符号表构建功能"""
    
    def test_detects_duplicate_functions(self):
        """测试检测重复的函数定义"""
        code = """
def hello():
    pass

def hello():
    pass
"""
        result = audit_code(code)
        assert result.has_errors
        assert any("Duplicate definition of 'hello'" in error for error in result.errors)
    
    def test_detects_duplicate_classes(self):
        """测试检测重复的类定义"""
        code = """
class MyClass:
    pass

class MyClass:
    pass
"""
        result = audit_code(code)
        assert result.has_errors
        assert any("Duplicate definition of 'MyClass'" in error for error in result.errors)
    
    def test_allows_functions_in_different_scopes(self):
        """测试允许不同作用域内的同名函数"""
        code = """
def outer():
    def inner():
        pass

def inner():
    pass
"""
        result = audit_code(code)
        assert not result.has_errors
    
    def test_detects_duplicate_imports(self):
        """测试检测重复的导入"""
        code = """
import os
import os
from pathlib import Path
from pathlib import Path
"""
        result = audit_code(code)
        assert result.has_errors
        assert any("Duplicate import" in error for error in result.errors)


class TestReferenceValidator:
    """测试引用完整性验证"""
    
    def test_detects_undefined_names(self):
        """测试检测未定义的名称"""
        code = """
def foo():
    return undefined_variable
"""
        result = audit_code(code)
        assert result.has_errors
        assert any("Undefined name 'undefined_variable'" in error for error in result.errors)
    
    def test_allows_defined_names(self):
        """测试允许已定义的名称"""
        code = """
x = 1
def foo():
    return x
"""
        result = audit_code(code)
        assert not result.has_errors
    
    def test_recognizes_imports(self):
        """测试识别导入的名称"""
        code = """
import os
from pathlib import Path

def foo():
    print(os.getcwd())
    return Path()
"""
        result = audit_code(code)
        if result.has_errors:
            print(f"Errors: {result.errors}")
            print(f"Builtins check: 'print' in builtins = {'print' in dir(__builtins__)}")
        assert not result.has_errors
    
    def test_recognizes_import_aliases(self):
        """测试识别导入别名"""
        code = """
import os as operating_system
from pathlib import Path as P

def foo():
    print(operating_system.getcwd())
    return P()
"""
        result = audit_code(code)
        assert not result.has_errors


class TestPatternChecker:
    """测试特定模式检查"""
    
    def test_detects_multiple_main_blocks(self):
        """测试检测多个主块"""
        code = """
if __name__ == "__main__":
    print("First")

if __name__ == "__main__":
    print("Second")
"""
        result = audit_code(code)
        assert result.has_errors
        assert any("Multiple 'if __name__" in error for error in result.errors)
    
    def test_warns_about_relative_imports(self):
        """测试相对导入警告"""
        code = """
from ..parent import something
from . import sibling
"""
        result = audit_code(code)
        assert len(result.warnings) >= 2
        assert any("Relative import" in warning for warning in result.warnings)
    
    def test_allows_single_main_block(self):
        """测试允许单个主块"""
        code = """
def main():
    print("Hello")

if __name__ == "__main__":
    main()
"""
        result = audit_code(code, is_main_script=True)
        assert not result.has_errors


class TestCaching:
    """测试缓存机制"""
    
    def test_cache_works(self):
        """测试缓存功能"""
        auditor = ASTAuditor()
        code = "x = 1"
        
        # 第一次调用
        result1 = auditor.audit(code, use_cache=True)
        
        # 第二次调用应该使用缓存
        result2 = auditor.audit(code, use_cache=True)
        
        # 结果应该相同
        assert result1 is result2
    
    def test_cache_disabled(self):
        """测试禁用缓存"""
        auditor = ASTAuditor()
        code = "x = 1"
        
        # 禁用缓存的调用
        result1 = auditor.audit(code, use_cache=False)
        result2 = auditor.audit(code, use_cache=False)
        
        # 结果应该不同（不同的对象）
        assert result1 is not result2
    
    def test_clear_cache(self):
        """测试清除缓存"""
        auditor = ASTAuditor()
        code = "x = 1"
        
        result1 = auditor.audit(code, use_cache=True)
        auditor.clear_cache()
        result2 = auditor.audit(code, use_cache=True)
        
        assert result1 is not result2


class TestComplexScenarios:
    """测试复杂场景"""
    
    def test_nested_functions_and_classes(self):
        """测试嵌套函数和类"""
        code = """
class Outer:
    def method(self):
        def inner():
            return self.value
        return inner()
    
    class Inner:
        pass

def function():
    class LocalClass:
        pass
    return LocalClass
"""
        result = audit_code(code)
        # 这个代码应该没有错误
        assert not result.has_errors
    
    def test_import_from_usage(self):
        """测试 from ... import 的使用"""
        code = """
from os.path import join, exists
from sys import argv

def main():
    if exists(argv[0]):
        return join(".", "file.txt")
"""
        result = audit_code(code)
        assert not result.has_errors