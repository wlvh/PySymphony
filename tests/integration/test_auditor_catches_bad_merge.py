"""
对抗性测试用例 - 验证 AST 审计器能够捕获 advanced_merge.py 可能产生的缺陷

这些测试用例故意构造会导致合并工具出错的场景，
然后验证我们的审计系统能够正确识别这些错误。
"""

import pytest
import sys
import tempfile
from pathlib import Path
import subprocess
import ast

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pysymphony.auditor import ASTAuditor


class TestAuditorCatchesBadMerge:
    """测试审计器捕获错误合并的能力"""
    
    def setup_method(self):
        """测试前准备"""
        self.auditor = ASTAuditor()
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        
    def teardown_method(self):
        """测试后清理"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_auditor_fails_on_duplicate_definitions(self):
        """测试：审计器应该捕获重复定义错误"""
        # 构造：创建一个会导致重复定义的项目结构
        # module_a.py
        module_a = self.temp_path / "module_a.py"
        module_a.write_text("""
def shared_function():
    return "from module A"
    
def unique_a():
    return shared_function()
""")
        
        # module_b.py
        module_b = self.temp_path / "module_b.py"
        module_b.write_text("""
def shared_function():
    return "from module B"
    
def unique_b():
    return shared_function()
""")
        
        # main.py
        main_script = self.temp_path / "main.py"
        main_script.write_text("""
from module_a import unique_a
from module_b import unique_b

if __name__ == "__main__":
    print(unique_a())
    print(unique_b())
""")
        
        # 行动：调用 advanced_merge.py 生成合并文件
        merge_script = Path(__file__).parent.parent.parent / "scripts" / "advanced_merge.py"
        output_file = self.temp_path / "main_advanced_merged.py"
        
        result = subprocess.run(
            [sys.executable, str(merge_script), str(main_script), str(self.temp_path)],
            capture_output=True,
            text=True
        )
        
        # 验证合并工具执行成功
        assert result.returncode == 0, f"Merge failed: {result.stderr}"
        assert output_file.exists()
        
        # 读取合并后的代码
        merged_code = output_file.read_text()
        
        # 断言：审计器应该检测到重复定义
        # 注意：如果 advanced_merge.py 正确处理了重命名，这个测试可能会失败
        # 这里我们构造一个故意有问题的合并结果来测试审计器
        bad_merged_code = """
def shared_function():
    return "from module A"
    
def unique_a():
    return shared_function()
    
def shared_function():  # 故意的重复定义
    return "from module B"
    
def unique_b():
    return shared_function()

if __name__ == "__main__":
    print(unique_a())
    print(unique_b())
"""
        
        # 审计这个有问题的代码
        audit_result = self.auditor.audit(bad_merged_code, "bad_merged.py")
        
        # 断言审计失败
        assert not audit_result, "审计器应该检测到重复定义"
        
        # 验证错误信息
        errors = self.auditor.get_report()
        assert "重复定义" in errors
        assert "shared_function" in errors
        
    def test_auditor_fails_on_broken_references(self):
        """测试：审计器应该捕获破坏的引用"""
        # 构造一个有破坏引用的代码
        broken_code = """
# 假设 advanced_merge.py 重命名了函数但遗漏了某些引用
def module_a_helper():
    return "helper"
    
def main_function():
    # 这里应该调用 module_a_helper，但引用了错误的名称
    return helper()  # 未定义的引用！

if __name__ == "__main__":
    print(main_function())
"""
        
        # 审计这个代码
        audit_result = self.auditor.audit(broken_code, "broken_references.py")
        
        # 断言审计失败
        assert not audit_result, "审计器应该检测到未定义的引用"
        
        # 验证错误信息
        errors = self.auditor.get_report()
        assert "未定义的名称" in errors
        assert "helper" in errors
        
    def test_auditor_fails_on_multiple_main_blocks(self):
        """测试：审计器应该捕获多个主块"""
        # 构造包含多个主块的代码
        multiple_mains = """
def function_from_module_a():
    return "A"

# 来自 module_a.py 的主块
if __name__ == "__main__":
    print("Module A main")
    
def function_from_module_b():
    return "B"

# 来自 module_b.py 的主块
if __name__ == "__main__":
    print("Module B main")
    
# 原始脚本的主块
if __name__ == "__main__":
    print("Script main")
    print(function_from_module_a())
    print(function_from_module_b())
"""
        
        # 审计这个代码
        audit_result = self.auditor.audit(multiple_mains, "multiple_mains.py")
        
        # 断言审计失败
        assert not audit_result, "审计器应该检测到多个主块"
        
        # 验证错误信息
        errors = self.auditor.get_report()
        assert "多个 'if __name__" in errors
        
    def test_auditor_passes_on_correct_merge(self):
        """测试：审计器应该通过正确的合并代码"""
        # 构造一个正确的合并代码
        correct_code = """
import os
import sys

# From module_a.py
def module_a_shared_function():
    return "from module A"
    
def unique_a():
    return module_a_shared_function()
    
# From module_b.py  
def module_b_shared_function():
    return "from module B"
    
def unique_b():
    return module_b_shared_function()

if __name__ == "__main__":
    print(unique_a())
    print(unique_b())
"""
        
        # 审计这个代码
        audit_result = self.auditor.audit(correct_code, "correct_merge.py")
        
        # 断言审计通过
        assert audit_result, f"审计器不应该在正确的代码上失败: {self.auditor.get_report()}"
        
        # 验证报告
        report = self.auditor.get_report()
        assert "审计通过" in report
        
    def test_auditor_detects_complex_scope_issues(self):
        """测试：审计器应该正确处理复杂的作用域问题"""
        complex_scope_code = """
global_var = "global"

def outer_function():
    outer_var = "outer"
    
    def inner_function():
        # 这里引用了不存在的变量
        return nonexistent_var
        
    return inner_function()
    
class MyClass:
    class_var = "class"
    
    def method(self):
        # 引用未定义的实例变量
        return self.undefined_attr

if __name__ == "__main__":
    outer_function()
"""
        
        # 审计这个代码
        audit_result = self.auditor.audit(complex_scope_code, "complex_scope.py")
        
        # 断言审计失败
        assert not audit_result, "审计器应该检测到未定义的变量"
        
        # 验证错误信息
        errors = self.auditor.get_report()
        assert "nonexistent_var" in errors