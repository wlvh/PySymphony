"""测试 Issue #41 中提到的四个核心修复"""
import pytest
import tempfile
import shutil
from pathlib import Path
import subprocess
import sys

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.advanced_merge import CircularDependencyError, AdvancedCodeMerger


class TestIssue41Fixes:
    """测试 Issue #41 的四个核心修复"""
    
    def setup_method(self):
        """设置测试环境"""
        self.test_dir = Path(tempfile.mkdtemp())
        
    def teardown_method(self):
        """清理测试环境"""
        shutil.rmtree(self.test_dir)
        
    def test_circular_dependency_detection(self):
        """测试1: 循环依赖检测必须准确"""
        # 创建循环依赖的模块
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
        
        # 必须抛出 CircularDependencyError
        merger = AdvancedCodeMerger(self.test_dir)
        with pytest.raises(CircularDependencyError) as exc_info:
            merger.merge_script(main_script)
            
        error_msg = str(exc_info.value)
        assert "Circular dependency detected" in error_msg
        assert "func_a" in error_msg and "func_b" in error_msg
        
    def test_attribute_chain_integrity(self):
        """测试2: 属性调用链必须保持完整"""
        # 创建具有属性链的模块
        utils_module = self.test_dir / "utils.py"
        utils_module.write_text("""
class Config:
    class Database:
        def get_connection(self):
            return "DB Connection"
    
    @property
    def db(self):
        return self.Database()
""")
        
        main_script = self.test_dir / "main.py"
        main_script.write_text("""
from utils import Config

config = Config()
# 测试属性链
print(config.db.get_connection())

# 测试 super()
class MyConfig(Config):
    def __init__(self):
        super().__init__()
        print("MyConfig initialized")

mc = MyConfig()
""")
        
        merger = AdvancedCodeMerger(self.test_dir)
        result = merger.merge_script(main_script)
        
        # 属性链必须保持完整
        assert "config.db.get_connection()" in result
        assert "super().__init__()" in result
        
        # 运行验证
        merged_file = self.test_dir / "main_merged.py"
        merged_file.write_text(result)
        
        proc = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert proc.returncode == 0
        assert "DB Connection" in proc.stdout
        assert "MyConfig initialized" in proc.stdout
        
    def test_naming_conflict_strategy(self):
        """测试3: 优先重命名导入别名，保持用户符号不变"""
        main_script = self.test_dir / "main.py"
        main_script.write_text("""
import json

def json_processor():
    '''用户定义的处理函数'''
    return "user processor"

# 两者都使用，验证没有冲突
data = json.dumps({"test": "value"})
result = json_processor()
print(data)
print(result)
""")
        
        merger = AdvancedCodeMerger(self.test_dir)
        result = merger.merge_script(main_script)
        
        # 导入别名应该被重命名
        assert "json__mod" in result
        # 用户定义的函数保持原名
        assert "def json_processor():" in result
        # 使用处应该正确替换
        assert "json__mod.dumps" in result
        
        # 运行验证
        merged_file = self.test_dir / "main_merged.py"
        merged_file.write_text(result)
        
        proc = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert proc.returncode == 0
        assert '"test": "value"' in proc.stdout
        assert "user processor" in proc.stdout
        
    def test_alias_renaming_rules(self):
        """测试4: 别名重命名规则（静态 __mod，运行时 __rt）"""
        main_script = self.test_dir / "main.py"
        main_script.write_text("""
# 静态导入
import os
import sys as system

# 运行时导入
try:
    import ujson as json
except ImportError:
    import json

# 使用所有导入
print(os.path.exists('.'))
print(system.version_info[0])
print(json.dumps({"runtime": "import"}))
""")
        
        merger = AdvancedCodeMerger(self.test_dir)
        result = merger.merge_script(main_script)
        
        # 静态导入使用 __mod 后缀
        assert "os__mod" in result
        assert "system__mod" in result
        
        # 运行时导入使用 __rt 后缀
        assert "json__rt" in result or "json as json__rt" in result
        
        # 使用处应该正确替换
        assert "os__mod.path.exists" in result
        assert "system__mod.version_info" in result
        assert "json__rt.dumps" in result
        
    def test_complex_scenario(self):
        """测试复杂场景：多个问题组合"""
        # 创建一个有属性链的模块
        helper_module = self.test_dir / "helper.py"
        helper_module.write_text("""
class Helper:
    class Inner:
        def process(self):
            return "processed"
    
    def get_inner(self):
        return self.Inner()
""")
        
        # 创建主脚本，包含多种情况
        main_script = self.test_dir / "main.py"
        main_script.write_text("""
import sys
from helper import Helper

# 运行时导入
try:
    import ujson as json
except ImportError:
    import json

def sys_info():
    '''用户定义的系统信息函数'''
    return "user sys info"

# 使用属性链
h = Helper()
print(h.get_inner().process())

# 使用导入和用户函数
print(sys.version_info[0])
print(sys_info())
print(json.dumps({"test": True}))
""")
        
        merger = AdvancedCodeMerger(self.test_dir)
        result = merger.merge_script(main_script)
        
        # 验证所有修复都正确应用
        assert "h.get_inner().process()" in result  # 属性链完整
        assert "sys__mod" in result  # 静态导入重命名
        assert "json__rt" in result or "json as json__rt" in result  # 运行时导入重命名
        assert "def sys_info():" in result  # 用户函数保持原名
        
        # 运行验证
        merged_file = self.test_dir / "main_merged.py"
        merged_file.write_text(result)
        
        proc = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert proc.returncode == 0
        assert "processed" in proc.stdout
        assert "user sys info" in proc.stdout
        assert '"test": true' in proc.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])