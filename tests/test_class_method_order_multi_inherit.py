"""
测试 B4 修复：类-方法拓扑顺序
验证多继承和混入场景下，类总是在其方法之前定义
"""
import pytest
import tempfile
import subprocess
import sys
from pathlib import Path
from scripts.advanced_merge import AdvancedCodeMerger


def test_single_class_with_methods():
    """测试单个类的方法顺序"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建一个模块，方法定义在类之前（故意的错误顺序）
        module = tmpdir / "myclass.py"
        module.write_text("""
# 注意：这里故意把方法写在前面，测试拓扑排序是否能纠正
def method1(self):
    return "method1"

def method2(self):
    return self.method1() + " and method2"

class MyClass:
    method1 = method1
    method2 = method2
""")
        
        # 创建主脚本
        main_script = tmpdir / "main.py"
        main_script.write_text("""
from myclass import MyClass

obj = MyClass()
print(obj.method1())
print(obj.method2())
""")
        
        # 执行合并
        merger = AdvancedCodeMerger(tmpdir)
        result = merger.merge_script(main_script)
        
        # 验证类定义在方法之前
        class_pos = result.find("class MyClass:")
        method1_pos = result.find("def method1(")
        method2_pos = result.find("def method2(")
        
        assert class_pos < method1_pos, "类应该在 method1 之前定义"
        assert class_pos < method2_pos, "类应该在 method2 之前定义"
        
        # 保存并运行
        merged_file = tmpdir / "main_merged.py"
        merged_file.write_text(result)
        
        proc = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert proc.returncode == 0, f"运行失败：{proc.stderr}"
        assert "method1" in proc.stdout
        assert "method1 and method2" in proc.stdout


def test_multiple_inheritance_with_mixins():
    """测试多继承和混入的场景"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建基类
        base_module = tmpdir / "base.py"
        base_module.write_text("""
class BaseClass:
    def base_method(self):
        return "base"
""")
        
        # 创建第一个混入
        mixin1 = tmpdir / "mixin1.py"
        mixin1.write_text("""
class LoggerMixin:
    def log(self, msg):
        return f"[LOG] {msg}"
""")
        
        # 创建第二个混入
        mixin2 = tmpdir / "mixin2.py"
        mixin2.write_text("""
class CacheMixin:
    def __init__(self):
        super().__init__()
        self._cache = {}
    
    def get_cached(self, key):
        return self._cache.get(key, "not cached")
    
    def set_cache(self, key, value):
        self._cache[key] = value
""")
        
        # 创建子类，继承多个类
        child_module = tmpdir / "child.py"
        child_module.write_text("""
from base import BaseClass
from mixin1 import LoggerMixin
from mixin2 import CacheMixin

class ChildClass(LoggerMixin, CacheMixin, BaseClass):
    def child_method(self):
        # 使用所有父类的方法
        base_result = self.base_method()
        log_result = self.log("child method called")
        self.set_cache("result", base_result)
        cached = self.get_cached("result")
        return f"{log_result}, base={base_result}, cached={cached}"
""")
        
        # 创建主脚本
        main_script = tmpdir / "main.py"
        main_script.write_text("""
from child import ChildClass

obj = ChildClass()
print(obj.child_method())
""")
        
        # 执行合并
        merger = AdvancedCodeMerger(tmpdir)
        result = merger.merge_script(main_script)
        
        # 验证所有类都在其方法之前定义
        base_class_pos = result.find("class BaseClass:")
        logger_mixin_pos = result.find("class LoggerMixin:")
        cache_mixin_pos = result.find("class CacheMixin:")
        child_class_pos = result.find("class ChildClass(")
        
        # 查找各个方法的位置
        base_method_pos = result.find("def base_method(")
        log_method_pos = result.find("def log(")
        get_cached_pos = result.find("def get_cached(")
        set_cache_pos = result.find("def set_cache(")
        child_method_pos = result.find("def child_method(")
        
        # 验证每个类都在其方法之前
        assert base_class_pos < base_method_pos
        assert logger_mixin_pos < log_method_pos
        assert cache_mixin_pos < get_cached_pos
        assert cache_mixin_pos < set_cache_pos
        assert child_class_pos < child_method_pos
        
        # 验证子类在所有父类之后（因为它依赖父类）
        assert base_class_pos < child_class_pos
        assert logger_mixin_pos < child_class_pos
        assert cache_mixin_pos < child_class_pos
        
        # 保存并运行
        merged_file = tmpdir / "main_merged.py"
        merged_file.write_text(result)
        
        proc = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert proc.returncode == 0, f"运行失败：{proc.stderr}"
        assert "[LOG] child method called" in proc.stdout
        assert "base=base" in proc.stdout
        assert "cached=base" in proc.stdout


def test_complex_class_hierarchy():
    """测试复杂的类层次结构"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建一个包含多层继承的复杂结构
        complex_module = tmpdir / "complex.py"
        complex_module.write_text("""
class A:
    def method_a(self):
        return "A"

class B(A):
    def method_b(self):
        return self.method_a() + "B"

class C(A):
    def method_c(self):
        return self.method_a() + "C"

class D(B, C):
    def method_d(self):
        return self.method_b() + self.method_c() + "D"

class E:
    def method_e(self):
        return "E"

class F(D, E):
    def method_f(self):
        return self.method_d() + self.method_e() + "F"
""")
        
        # 创建主脚本
        main_script = tmpdir / "main.py"
        main_script.write_text("""
from complex import F

obj = F()
print(obj.method_f())
""")
        
        # 执行合并
        merger = AdvancedCodeMerger(tmpdir)
        result = merger.merge_script(main_script)
        
        # 验证类的顺序（父类应该在子类之前）
        class_positions = {
            'A': result.find("class A:"),
            'B': result.find("class B(A):"),
            'C': result.find("class C(A):"),
            'D': result.find("class D(B, C):"),
            'E': result.find("class E:"),
            'F': result.find("class F(D, E):")
        }
        
        # 验证继承顺序
        assert class_positions['A'] < class_positions['B']
        assert class_positions['A'] < class_positions['C']
        assert class_positions['B'] < class_positions['D']
        assert class_positions['C'] < class_positions['D']
        assert class_positions['D'] < class_positions['F']
        assert class_positions['E'] < class_positions['F']
        
        # 保存并运行
        merged_file = tmpdir / "main_merged.py"
        merged_file.write_text(result)
        
        proc = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert proc.returncode == 0, f"运行失败：{proc.stderr}"
        # 预期输出：ABACDEF
        assert "ABACDEF" in proc.stdout


if __name__ == "__main__":
    # 直接运行测试
    test_single_class_with_methods()
    test_multiple_inheritance_with_mixins()
    test_complex_class_hierarchy()
    print("✅ 所有类方法顺序测试通过")