"""
端到端测试 - 测试从项目合并到最终执行的完整流程

这些测试验证整个系统的工作流程，包括：
1. 使用 advanced_merge.py 合并项目
2. 使用 AST 审计器进行静态检查
3. 执行合并后的代码并验证结果
"""

import pytest
import sys
import tempfile
from pathlib import Path
import subprocess
import shutil

# 添加项目根目录到 Python 路径
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))


class TestFullMergeWorkflow:
    """测试完整的合并工作流程"""
    
    def setup_method(self):
        """测试前准备"""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        
    def teardown_method(self):
        """测试后清理"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_simple_project_merge_and_execution(self):
        """测试：简单项目的合并和执行"""
        # 创建一个简单的项目结构
        # utils.py
        utils_file = self.temp_path / "utils.py"
        utils_file.write_text("""
def add(a, b):
    \"\"\"加法函数\"\"\"
    return a + b
    
def multiply(a, b):
    \"\"\"乘法函数\"\"\"
    return a * b
""")
        
        # main.py
        main_file = self.temp_path / "main.py"
        main_file.write_text("""
from utils import add, multiply

def calculate():
    result1 = add(2, 3)
    result2 = multiply(4, 5)
    return result1, result2

if __name__ == "__main__":
    r1, r2 = calculate()
    print(f"Add: {r1}")
    print(f"Multiply: {r2}")
""")
        
        # 执行合并
        merge_script = ROOT / "scripts" / "advanced_merge.py"
        merge_cmd = [
            sys.executable, 
            str(merge_script), 
            str(main_file), 
            str(self.temp_path)
        ]
        
        result = subprocess.run(merge_cmd, capture_output=True, text=True)
        assert result.returncode == 0, f"Merge failed: {result.stderr}"
        
        # 验证合并文件生成
        merged_file = self.temp_path / "main_advanced_merged.py"
        assert merged_file.exists()
        
        # 执行合并后的文件
        exec_result = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert exec_result.returncode == 0
        assert "Add: 5" in exec_result.stdout
        assert "Multiply: 20" in exec_result.stdout
        
    def test_complex_dependency_project(self):
        """测试：复杂依赖项目的合并"""
        # 创建多层依赖结构
        # base.py
        (self.temp_path / "base.py").write_text("""
BASE_VALUE = 100

def get_base():
    return BASE_VALUE
""")
        
        # middleware.py
        (self.temp_path / "middleware.py").write_text("""
from base import get_base

def process_value(x):
    base = get_base()
    return x + base
""")
        
        # service.py
        (self.temp_path / "service.py").write_text("""
from middleware import process_value

class Service:
    def __init__(self):
        self.name = "MyService"
        
    def compute(self, value):
        return process_value(value) * 2
""")
        
        # main.py
        (self.temp_path / "main.py").write_text("""
from service import Service

def main():
    svc = Service()
    result = svc.compute(50)
    print(f"Service result: {result}")
    return result

if __name__ == "__main__":
    main()
""")
        
        # 执行合并
        merge_script = ROOT / "scripts" / "advanced_merge.py"
        result = subprocess.run(
            [sys.executable, str(merge_script), 
             str(self.temp_path / "main.py"), 
             str(self.temp_path)],
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0
        
        # 执行合并后的文件
        merged_file = self.temp_path / "main_advanced_merged.py"
        exec_result = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert exec_result.returncode == 0
        assert "Service result: 300" in exec_result.stdout  # (50 + 100) * 2
        
    def test_merge_with_external_imports(self):
        """测试：保留外部库导入的合并"""
        # script.py
        script_file = self.temp_path / "script.py"
        script_file.write_text("""
import os
import sys
from pathlib import Path
import json

def get_python_info():
    info = {
        "version": sys.version,
        "platform": sys.platform,
        "cwd": os.getcwd()
    }
    return json.dumps(info, indent=2)

if __name__ == "__main__":
    print(get_python_info())
""")
        
        # 执行合并
        merge_script = ROOT / "scripts" / "advanced_merge.py"
        result = subprocess.run(
            [sys.executable, str(merge_script), 
             str(script_file), 
             str(self.temp_path)],
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0
        
        # 验证合并文件保留了外部导入
        merged_file = self.temp_path / "script_advanced_merged.py"
        merged_content = merged_file.read_text()
        
        assert "import os" in merged_content
        assert "import sys" in merged_content
        assert "from pathlib import Path" in merged_content
        assert "import json" in merged_content
        
        # 执行验证
        exec_result = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert exec_result.returncode == 0
        # 验证 JSON 输出
        import json
        output_data = json.loads(exec_result.stdout)
        assert "version" in output_data
        assert "platform" in output_data
        assert "cwd" in output_data
        
    def test_pytest_integration(self, run_script):
        """测试：与 pytest 的集成"""
        # 创建一个简单的测试项目
        # helper.py
        (self.temp_path / "helper.py").write_text("""
def double(x):
    return x * 2
""")
        
        # test_script.py
        test_script = self.temp_path / "test_script.py"
        test_script.write_text("""
from helper import double

def test_double():
    assert double(5) == 10
    print("Test passed!")

if __name__ == "__main__":
    test_double()
""")
        
        # 通过 run_script fixture 运行（会自动应用合并和静态检查）
        output = run_script(test_script)
        assert "Test passed!" in output