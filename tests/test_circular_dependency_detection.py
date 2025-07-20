"""测试循环依赖检测和诊断功能"""
import pytest
import tempfile
import shutil
from pathlib import Path
import sys

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.advanced_merge import CircularDependencyError, AdvancedCodeMerger


class TestCircularDependencyDetection:
    """测试循环依赖检测功能"""
    
    def setup_method(self):
        """设置测试环境"""
        self.test_dir = Path(tempfile.mkdtemp())
        
    def teardown_method(self):
        """清理测试环境"""
        shutil.rmtree(self.test_dir)
        
    def test_simple_circular_dependency(self):
        """测试简单的循环依赖检测"""
        # 创建测试文件
        module_a = self.test_dir / "module_a.py"
        module_a.write_text("""
from module_b import func_b

def func_a():
    return func_b()
""")
        
        module_b = self.test_dir / "module_b.py"
        module_b.write_text("""
from module_a import func_a

def func_b():
    return func_a()
""")
        
        main_script = self.test_dir / "main.py"
        main_script.write_text("""
from module_a import func_a

if __name__ == "__main__":
    print(func_a())
""")
        
        # 测试合并器应该检测到循环依赖
        merger = AdvancedCodeMerger(self.test_dir)
        with pytest.raises(CircularDependencyError) as exc_info:
            merger.merge_script(main_script)
            
        error_msg = str(exc_info.value)
        assert "Circular dependency detected" in error_msg
        # 应该包含循环路径信息
        assert "func_a" in error_msg and "func_b" in error_msg
        
    def test_class_method_circular_dependency(self):
        """测试类和方法之间的循环依赖"""
        # 创建测试文件
        class_a = self.test_dir / "class_a.py"
        class_a.write_text("""
from class_b import ClassB

class ClassA:
    def method_a(self):
        b = ClassB()
        return b.method_b()
""")
        
        class_b = self.test_dir / "class_b.py"
        class_b.write_text("""
from class_a import ClassA

class ClassB:
    def method_b(self):
        a = ClassA()
        return a.method_a()
""")
        
        main_script = self.test_dir / "main.py"
        main_script.write_text("""
from class_a import ClassA

if __name__ == "__main__":
    a = ClassA()
    print(a.method_a())
""")
        
        # 测试合并器应该检测到循环依赖
        merger = AdvancedCodeMerger(self.test_dir)
        with pytest.raises(CircularDependencyError) as exc_info:
            merger.merge_script(main_script)
            
        error_msg = str(exc_info.value)
        assert "Circular dependency detected" in error_msg
        
    def test_complex_circular_dependency(self):
        """测试复杂的多节点循环依赖"""
        # 创建测试文件
        module_a = self.test_dir / "module_a.py"
        module_a.write_text("""
from module_b import func_b

def func_a():
    return func_b()
""")
        
        module_b = self.test_dir / "module_b.py"
        module_b.write_text("""
from module_c import func_c

def func_b():
    return func_c()
""")
        
        module_c = self.test_dir / "module_c.py"
        module_c.write_text("""
from module_a import func_a

def func_c():
    return func_a()
""")
        
        main_script = self.test_dir / "main.py"
        main_script.write_text("""
from module_a import func_a

if __name__ == "__main__":
    print(func_a())
""")
        
        # 测试合并器应该检测到循环依赖
        merger = AdvancedCodeMerger(self.test_dir)
        with pytest.raises(CircularDependencyError) as exc_info:
            merger.merge_script(main_script)
            
        error_msg = str(exc_info.value)
        assert "Circular dependency detected" in error_msg
        # 应该显示完整的循环路径
        assert "func_a" in error_msg and "func_b" in error_msg and "func_c" in error_msg
        
    def test_no_circular_dependency(self):
        """测试没有循环依赖的情况"""
        # 创建测试文件
        module_a = self.test_dir / "module_a.py"
        module_a.write_text("""
def func_a():
    return "A"
""")
        
        module_b = self.test_dir / "module_b.py"
        module_b.write_text("""
from module_a import func_a

def func_b():
    return func_a() + "B"
""")
        
        main_script = self.test_dir / "main.py"
        main_script.write_text("""
from module_b import func_b

if __name__ == "__main__":
    print(func_b())
""")
        
        # 测试合并器应该成功
        merger = AdvancedCodeMerger(self.test_dir)
        merged_code = merger.merge_script(main_script)
        assert merged_code is not None
        assert "func_a" in merged_code
        assert "func_b" in merged_code


if __name__ == "__main__":
    pytest.main([__file__, "-v"])