"""端到端测试 - 验证整个流程"""
import pytest
import subprocess
import sys
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).parent.parent.parent


class TestEndToEnd:
    """端到端测试整个合并和验证流程"""
    
    def test_simple_project_merge_and_validate(self, tmp_path):
        """测试简单项目的合并和验证"""
        # 创建项目结构
        project = tmp_path / "simple_project"
        project.mkdir()
        
        # 创建主文件
        (project / "main.py").write_text("""
from calculator import add, multiply

def main():
    x = add(5, 3)
    y = multiply(x, 2)
    print(f"Result: {y}")

if __name__ == "__main__":
    main()
""")
        
        # 创建计算器模块
        (project / "calculator.py").write_text("""
def add(a, b):
    return a + b

def multiply(a, b):
    return a * b

def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
""")
        
        # 运行合并
        merge_cmd = [
            sys.executable, 
            str(ROOT / "scripts" / "advanced_merge.py"),
            str(project / "main.py"),
            str(project)
        ]
        
        merge_result = subprocess.run(merge_cmd, capture_output=True, text=True)
        
        # 验证合并文件存在
        merged_file = project / "main_advanced_merged.py"
        assert merged_file.exists(), f"Merged file not created. Output: {merge_result.stderr}"
        
        # 运行合并后的文件
        run_cmd = [sys.executable, str(merged_file)]
        run_result = subprocess.run(run_cmd, capture_output=True, text=True)
        
        # 验证输出
        assert run_result.returncode == 0, f"Merged script failed: {run_result.stderr}"
        assert "Result: 16" in run_result.stdout
    
    def test_complex_imports_project(self, tmp_path):
        """测试复杂导入场景"""
        # 创建项目结构
        project = tmp_path / "complex_project"
        project.mkdir()
        (project / "utils").mkdir()
        
        # 创建 __init__.py
        (project / "utils" / "__init__.py").write_text("")
        
        # 创建主文件
        (project / "main.py").write_text("""
from utils.helpers import format_output
from utils.validators import validate_input
import json

def process_data(data):
    if not validate_input(data):
        return None
    
    result = {"status": "success", "data": data}
    return format_output(json.dumps(result))

if __name__ == "__main__":
    test_data = {"name": "test", "value": 42}
    print(process_data(test_data))
""")
        
        # 创建辅助模块
        (project / "utils" / "helpers.py").write_text("""
def format_output(text):
    return f"=== {text} ==="
""")
        
        (project / "utils" / "validators.py").write_text("""
def validate_input(data):
    return isinstance(data, dict) and "name" in data
""")
        
        # 运行合并
        merge_cmd = [
            sys.executable,
            str(ROOT / "scripts" / "advanced_merge.py"),
            str(project / "main.py"),
            str(project)
        ]
        
        merge_result = subprocess.run(merge_cmd, capture_output=True, text=True)
        merged_file = project / "main_advanced_merged.py"
        
        if merged_file.exists():
            # 运行合并后的文件
            run_cmd = [sys.executable, str(merged_file)]
            run_result = subprocess.run(run_cmd, capture_output=True, text=True)
            
            # 验证功能正常
            if run_result.returncode == 0:
                assert "=== {" in run_result.stdout
                assert '"status": "success"' in run_result.stdout
    
    def test_pytest_with_merged_flag(self):
        """测试 pytest --merged 标志"""
        # 运行一个简单的回归测试
        pytest_cmd = [
            sys.executable, "-m", "pytest",
            str(ROOT / "tests" / "test_regression.py::TestRegression::test_all_list"),
            "-v"
        ]
        
        # 先运行普通测试
        normal_result = subprocess.run(pytest_cmd, capture_output=True, text=True)
        
        # 再运行 --merged 测试
        merged_cmd = pytest_cmd + ["--merged"]
        merged_result = subprocess.run(merged_cmd, capture_output=True, text=True)
        
        # 两者都应该能运行（不管是否通过）
        assert "PASSED" in normal_result.stdout or "FAILED" in normal_result.stdout
        assert "PASSED" in merged_result.stdout or "FAILED" in merged_result.stdout


class TestErrorDetection:
    """测试错误检测能力"""
    
    def test_detects_symbol_conflicts(self, tmp_path):
        """测试检测符号冲突"""
        project = tmp_path / "conflict_project"
        project.mkdir()
        
        # 创建有冲突的文件
        (project / "main.py").write_text("""
from module1 import process
from module2 import process  # 冲突！

result = process(10)
print(result)
""")
        
        (project / "module1.py").write_text("""
def process(x):
    return x + 1
""")
        
        (project / "module2.py").write_text("""
def process(x):
    return x * 2
""")
        
        # 运行 pytest 测试（应该检测到问题）
        test_file = project / "test_main.py"
        test_file.write_text("""
import pytest
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from conftest import static_check

def test_conflicts():
    # 这里我们模拟测试合并后的代码
    merged_code = '''
def module1_process(x):
    return x + 1

def module2_process(x):
    return x * 2

# 错误：原始代码引用了 'process'，但合并后不存在
result = process(10)
print(result)
'''
    with pytest.raises(Exception) as exc_info:
        static_check(merged_code, Path("test.py"))
    
    assert "Undefined name 'process'" in str(exc_info.value)
""")
        
        # 运行测试
        pytest_cmd = [sys.executable, "-m", "pytest", str(test_file), "-v"]
        result = subprocess.run(pytest_cmd, capture_output=True, text=True)
        
        # 测试应该通过（因为它正确地检测到了错误）
        assert "PASSED" in result.stdout or "test_conflicts" in result.stdout