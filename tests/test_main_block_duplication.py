"""测试主块重复问题的修复"""

import pytest
import sys
import tempfile
from pathlib import Path
import subprocess
import shutil

# 添加项目根目录到 Python 路径
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


class TestMainBlockDuplication:
    """测试主块不会重复的问题"""
    
    def setup_method(self):
        """测试前准备"""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        
    def teardown_method(self):
        """测试后清理"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
    def test_main_block_not_duplicated(self):
        """测试：主块只出现一次"""
        # 创建一个带有主块的脚本
        main_file = self.temp_path / "main.py"
        main_file.write_text("""
def hello():
    print("Hello from function")

if __name__ == "__main__":
    print("Start")
    hello()
    print("End")
""")
        
        # 执行合并
        merge_script = ROOT / "scripts" / "advanced_merge.py"
        result = subprocess.run(
            [sys.executable, str(merge_script), 
             str(main_file), 
             str(self.temp_path)],
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0, f"Merge failed: {result.stderr}"
        
        # 验证合并文件
        merged_file = self.temp_path / "main_advanced_merged.py"
        merged_content = merged_file.read_text()
        
        # 计算主块出现次数
        main_count = merged_content.count("if __name__ == '__main__':")
        assert main_count == 1, f"Expected 1 main block but found {main_count}"
        
        # 执行合并后的文件并验证输出
        exec_result = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert exec_result.returncode == 0
        
        # 验证输出只出现一次
        output_lines = exec_result.stdout.strip().split('\n')
        assert output_lines == ["Start", "Hello from function", "End"], \
            f"Unexpected output: {output_lines}"
            
    def test_main_block_with_module_inits(self):
        """测试：带有模块初始化语句的主块不重复"""
        # 创建模块 utils.py
        utils_file = self.temp_path / "utils.py"
        utils_file.write_text("""
# 模块级初始化
CONSTANT = 42

def get_constant():
    return CONSTANT
""")
        
        # 创建主脚本
        main_file = self.temp_path / "main.py"
        main_file.write_text("""
from utils import get_constant

# 主脚本的模块级初始化
MAIN_VALUE = 100

def process():
    return get_constant() + MAIN_VALUE

if __name__ == "__main__":
    result = process()
    print(f"Result: {result}")
""")
        
        # 执行合并
        merge_script = ROOT / "scripts" / "advanced_merge.py"
        result = subprocess.run(
            [sys.executable, str(merge_script), 
             str(main_file), 
             str(self.temp_path)],
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0
        
        # 验证合并文件
        merged_file = self.temp_path / "main_advanced_merged.py"
        merged_content = merged_file.read_text()
        
        # 主块只出现一次
        main_count = merged_content.count("if __name__ == '__main__':")
        assert main_count == 1, f"Expected 1 main block but found {main_count}"
        
        # 执行验证
        exec_result = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert exec_result.returncode == 0
        assert exec_result.stdout.strip() == "Result: 142"