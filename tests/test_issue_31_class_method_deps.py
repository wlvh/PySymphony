"""
测试 Issue #31: Auto-fix Undefined Symbols & Imports
验证类方法内部的依赖是否被正确收集
"""
import ast
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest

def test_class_method_dependencies_collected():
    """测试类方法内的依赖被正确收集"""
    # 创建测试文件结构
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建项目结构
        project_dir = tmpdir / "test_project"
        project_dir.mkdir()
        
        # 创建 data_yy 包
        data_pkg = project_dir / "data_yy"
        data_pkg.mkdir()
        (data_pkg / "__init__.py").write_text("")
        
        # 创建 loader.py 文件，包含 DiskStockDataReader 类
        loader_code = '''
class DiskStockDataReader:
    """磁盘股票数据读取器"""
    def __init__(self, data_path):
        self.data_path = data_path
        
    def read_data(self):
        return f"Reading data from {self.data_path}"
'''
        (data_pkg / "loader.py").write_text(loader_code)
        
        # 创建 models_yy 包
        models_pkg = project_dir / "models_yy"
        models_pkg.mkdir()
        (models_pkg / "__init__.py").write_text("")
        
        # 创建 crossformer.py 文件，包含 CrossformerStockModel 类
        model_code = '''
class CrossformerStockModel:
    """Crossformer股票模型"""
    def __init__(self, config):
        self.config = config
        
    def predict(self, data):
        return f"Predicting with config: {self.config}"
'''
        (models_pkg / "crossformer.py").write_text(model_code)
        
        # 创建 scripts 包
        scripts_pkg = project_dir / "scripts"
        scripts_pkg.mkdir()
        (scripts_pkg / "__init__.py").write_text("")
        
        # 创建主脚本 sota.py
        sota_code = '''
from data_yy.loader import DiskStockDataReader
from models_yy.crossformer import CrossformerStockModel

class CrossformerSM_PM:
    """Crossformer股票市场预测管理器"""
    def __init__(self, data_path, config):
        # 这些依赖在类方法内部使用，需要被合并器捕获
        self.reader = DiskStockDataReader(data_path)
        self.model = CrossformerStockModel(config)
        
    def run_model_test(self):
        data = self.reader.read_data()
        result = self.model.predict(data)
        return result

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', default='model_test')
    args = parser.parse_args()
    
    if args.mode == 'model_test':
        manager = CrossformerSM_PM("/data/stocks", {"layers": 4})
        result = manager.run_model_test()
        print(f"Test result: {result}")

if __name__ == "__main__":
    main()
'''
        (scripts_pkg / "sota.py").write_text(sota_code)
        
        # 运行合并器
        merge_script = Path(__file__).parent.parent / "scripts" / "advanced_merge.py"
        input_script = scripts_pkg / "sota.py"
        
        result = subprocess.run(
            [sys.executable, str(merge_script), str(input_script), str(project_dir)],
            capture_output=True,
            text=True
        )
        
        # 验证合并成功
        assert result.returncode == 0, f"Merge failed: {result.stderr}"
        
        # 读取合并后的文件
        merged_file = scripts_pkg / "sota_advanced_merged.py"
        assert merged_file.exists(), "Merged file not created"
        
        merged_content = merged_file.read_text()
        
        # 验证关键点
        # 1. DiskStockDataReader 和 CrossformerStockModel 应该被内联
        assert "class data_yy_loader_DiskStockDataReader:" in merged_content or \
               "class DiskStockDataReader:" in merged_content, \
               "DiskStockDataReader class not inlined"
               
        assert "class models_yy_crossformer_CrossformerStockModel:" in merged_content or \
               "class CrossformerStockModel:" in merged_content, \
               "CrossformerStockModel class not inlined"
        
        # 2. 不应该包含项目内部的import语句
        assert "from data_yy.loader import" not in merged_content, \
               "Internal import from data_yy still present"
        assert "from models_yy.crossformer import" not in merged_content, \
               "Internal import from models_yy still present"
        
        # 3. 验证合并后的脚本可以独立运行
        # 将合并后的文件复制到新目录
        test_dir = tmpdir / "test_run"
        test_dir.mkdir()
        test_script = test_dir / "sota_merged.py"
        test_script.write_text(merged_content)
        
        # 尝试运行合并后的脚本
        run_result = subprocess.run(
            [sys.executable, str(test_script), "--mode", "model_test"],
            capture_output=True,
            text=True,
            cwd=str(test_dir)
        )
        
        # 验证运行成功
        assert run_result.returncode == 0, f"Merged script failed to run: {run_result.stderr}"
        assert "Test result:" in run_result.stdout, "Expected output not found"


def test_nested_class_method_dependencies():
    """测试嵌套类和更复杂的方法依赖"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建项目结构
        project_dir = tmpdir / "test_project"
        project_dir.mkdir()
        
        # 创建 utils 包
        utils_pkg = project_dir / "utils"
        utils_pkg.mkdir()
        (utils_pkg / "__init__.py").write_text("")
        
        # 创建 helpers.py
        helpers_code = '''
def format_data(data):
    """格式化数据"""
    return f"Formatted: {data}"

def validate_data(data):
    """验证数据"""
    return len(data) > 0
'''
        (utils_pkg / "helpers.py").write_text(helpers_code)
        
        # 创建主脚本
        main_code = '''
from utils.helpers import format_data, validate_data

class DataProcessor:
    """数据处理器"""
    def __init__(self):
        self.processed_count = 0
        
    def process(self, data):
        # 在方法内部使用导入的函数
        if validate_data(data):
            formatted = format_data(data)
            self.processed_count += 1
            return formatted
        return None
        
    class InnerProcessor:
        """内部处理器类"""
        def process_inner(self, data):
            # 嵌套类方法中的依赖也需要被捕获
            return format_data(f"Inner: {data}")

def main():
    processor = DataProcessor()
    result = processor.process("test data")
    print(result)
    
    inner = DataProcessor.InnerProcessor()
    inner_result = inner.process_inner("inner data")
    print(inner_result)

if __name__ == "__main__":
    main()
'''
        (project_dir / "main.py").write_text(main_code)
        
        # 运行合并器
        merge_script = Path(__file__).parent.parent / "scripts" / "advanced_merge.py"
        input_script = project_dir / "main.py"
        
        result = subprocess.run(
            [sys.executable, str(merge_script), str(input_script), str(project_dir)],
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0, f"Merge failed: {result.stderr}"
        
        # 读取合并后的文件
        merged_file = project_dir / "main_advanced_merged.py"
        merged_content = merged_file.read_text()
        
        # 验证 format_data 和 validate_data 被内联
        assert "def format_data(" in merged_content or "def utils_helpers_format_data(" in merged_content, \
               "format_data function not inlined"
        assert "def validate_data(" in merged_content or "def utils_helpers_validate_data(" in merged_content, \
               "validate_data function not inlined"
        
        # 验证没有内部import
        assert "from utils.helpers import" not in merged_content, \
               "Internal import still present"


if __name__ == "__main__":
    # 运行测试
    test_class_method_dependencies_collected()
    test_nested_class_method_dependencies()
    print("All tests passed!")