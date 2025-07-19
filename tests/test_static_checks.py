"""测试静态检查功能"""
import pytest
import sys
from pathlib import Path
import tempfile
import subprocess

# 添加项目根目录到 Python 路径
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from conftest import static_check


def test_syntax_error_detection():
    """测试语法错误检测"""
    bad_code = """
def foo():
    print("missing closing paren"
    """
    
    with pytest.raises(Exception) as exc_info:
        static_check(bad_code, Path("test.py"))
    
    assert "Syntax error" in str(exc_info.value)


def test_duplicate_function_detection():
    """测试重复函数定义检测"""
    duplicate_code = """
def hello():
    print("hello 1")

def hello():
    print("hello 2")
    """
    
    with pytest.raises(Exception) as exc_info:
        static_check(duplicate_code, Path("test.py"))
    
    assert "Duplicate top-level symbols" in str(exc_info.value)
    assert "hello" in str(exc_info.value)


def test_duplicate_class_detection():
    """测试重复类定义检测"""
    duplicate_code = """
class MyClass:
    pass

class MyClass:
    pass
    """
    
    with pytest.raises(Exception) as exc_info:
        static_check(duplicate_code, Path("test.py"))
    
    assert "Duplicate top-level symbols" in str(exc_info.value)
    assert "MyClass" in str(exc_info.value)


def test_duplicate_import_detection():
    """测试重复导入检测"""
    duplicate_code = """
import os
import os
from pathlib import Path
from pathlib import Path
    """
    
    with pytest.raises(Exception) as exc_info:
        static_check(duplicate_code, Path("test.py"))
    
    assert "Duplicate top-level symbols" in str(exc_info.value)


def test_valid_code_passes():
    """测试有效代码应该通过检查"""
    valid_code = """
import os
from pathlib import Path

def hello():
    print("hello")
    # 使用导入的模块
    print(os.getcwd())
    print(Path.cwd())

class MyClass:
    def method(self):
        pass

async def async_function():
    pass
    """
    
    # 不应该抛出异常
    static_check(valid_code, Path("test.py"))


def test_flake8_undefined_name():
    """测试 flake8 检测未定义的名称"""
    # 先检查 flake8 是否安装
    try:
        subprocess.run([sys.executable, "-m", "flake8", "--version"], 
                      capture_output=True, check=True)
    except subprocess.CalledProcessError:
        pytest.skip("flake8 not installed")
    
    bad_code = """
def foo():
    return undefined_variable
    """
    
    with pytest.raises(Exception) as exc_info:
        static_check(bad_code, Path("test.py"))
    
    assert "[flake8]" in str(exc_info.value)
    assert "undefined name" in str(exc_info.value).lower()


def test_flake8_unused_import():
    """测试 flake8 检测未使用的导入"""
    # 先检查 flake8 是否安装
    try:
        subprocess.run([sys.executable, "-m", "flake8", "--version"], 
                      capture_output=True, check=True)
    except subprocess.CalledProcessError:
        pytest.skip("flake8 not installed")
    
    bad_code = """
import os
import sys

def foo():
    print("not using imports")
    """
    
    with pytest.raises(Exception) as exc_info:
        static_check(bad_code, Path("test.py"))
    
    assert "[flake8]" in str(exc_info.value)


def test_integration_with_advanced_merge(tmp_path):
    """测试与 advanced_merge.py 的集成 - 验证正常合并的代码能通过静态检查"""
    # 创建一个正常的测试场景
    test_dir = tmp_path / "test_project"
    test_dir.mkdir()
    
    # 创建主脚本
    main_script = test_dir / "main.py"
    main_script.write_text("""
from module1 import func1
from module2 import func2

func1()
func2()
""")
    
    # 创建模块1
    module1 = test_dir / "module1.py"
    module1.write_text("""
def func1():
    print("module1 func")
""")
    
    # 创建模块2
    module2 = test_dir / "module2.py"
    module2.write_text("""
def func2():
    print("module2 func")
""")
    
    # 运行 advanced_merge.py
    merge_script = ROOT / "scripts" / "advanced_merge.py"
    cmd = [sys.executable, str(merge_script), str(main_script), str(test_dir)]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    # 检查合并后的文件
    merged_file = test_dir / "main_advanced_merged.py"
    assert merged_file.exists()
    
    merged_code = merged_file.read_text()
    
    # 正常合并的代码应该通过静态检查
    static_check(merged_code, merged_file)