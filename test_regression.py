"""回归测试套件 - 验证所有测试用例在原始和合并后都能正确运行"""
import pytest
from pathlib import Path

class TestRegression:
    """回归测试类"""
    
    def test_alias_chain(self, run_script):
        """测试alias链式调用的正确处理"""
        output = run_script("tests/alias_chain/main.py")
        assert output.strip() == "OK"
    
    def test_deep_relative_import(self, run_script):
        """测试深层相对导入的解析"""
        output = run_script("tests/deep_relative_import/entry.py")
        assert output.strip() == "42"
    
    def test_nonlocal_shadow(self, run_script):
        """测试nonlocal变量不被错误重命名"""
        output = run_script("tests/nonlocal_shadow/shadow.py")
        assert output.strip() == "2"
    
    def test_global_after_use(self, run_script):
        """测试global声明和后定义变量的处理"""
        output = run_script("tests/global_after_use/order.py")
        assert output.strip() == "works"
    
    def test_all_list(self, run_script):
        """测试__all__列表的正确处理"""
        output = run_script("tests/all_list/mod.py")
        lines = output.strip().split('\n')
        assert lines[0] == "exported"
        assert lines[1] == "class method"
    
    def test_comprehension_scope(self, run_script):
        """测试推导式作用域的正确处理"""
        output = run_script("tests/comprehension_scope/comp.py")
        # 验证输出是一个字典格式
        assert output.strip().startswith("{")
        assert output.strip().endswith("}")
        # 验证没有NameError
        assert "NameError" not in output
    
    def test_async_await(self, run_script):
        """测试async/await的依赖追踪"""
        output = run_script("tests/async_await/coro.py")
        assert output.strip() == "3"
    
    def test_decorator_dependency(self, run_script):
        """测试装饰器依赖的正确顺序"""
        output = run_script("tests/decorator_dependency/deco.py")
        assert output.strip() == "decorated: original"
    
    def test_type_annotation_str(self, run_script):
        """测试字符串类型注解的解析和重写"""
        output = run_script("tests/type_annotation_str/anno.py")
        lines = output.strip().split('\n')
        assert lines[0] == "42"
        assert lines[1] == "forward reference works"