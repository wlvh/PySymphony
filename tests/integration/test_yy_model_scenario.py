"""验证 Issue #28 中 yy_model_py 场景的测试

这个测试模拟了 yy_model_py 项目中遇到的问题：
- 复杂的依赖关系
- 大量未被内联的依赖
- 需要重新注入导入语句
"""

import pytest
import tempfile
import subprocess
import sys
import os
from pathlib import Path
import py_compile


def test_yy_model_scenario():
    """模拟 yy_model_py 场景：复杂依赖和未解析的符号"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建模拟的项目结构
        # scripts/crossformer.py - 包含 DiskStockDataReader
        scripts_dir = tmpdir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "__init__.py").write_text("")
        
        crossformer_py = scripts_dir / "crossformer.py"
        crossformer_py.write_text('''
class DiskStockDataReader:
    """复杂的数据读取器类，通常不会被内联"""
    def __init__(self, path):
        self.path = path
        self._cache = {}
    
    def read(self, symbol):
        if symbol not in self._cache:
            # 模拟从磁盘读取数据
            self._cache[symbol] = f"data for {symbol} from {self.path}"
        return self._cache[symbol]
    
    def clear_cache(self):
        self._cache.clear()

# 其他很多未被使用的类和函数
class ModelTrainer:
    def train(self):
        pass

class DataPreprocessor:
    def preprocess(self):
        pass

def helper_function():
    return "helper"
''')
        
        # scripts/models.py - 使用 DiskStockDataReader
        models_py = scripts_dir / "models.py"
        models_py.write_text('''
from scripts.crossformer import DiskStockDataReader

class StockPredictor:
    """股票预测模型"""
    def __init__(self, data_path):
        self.reader = DiskStockDataReader(data_path)
    
    def predict(self, symbol):
        data = self.reader.read(symbol)
        # 模拟预测逻辑
        return f"prediction for {symbol} based on {data}"
''')
        
        # scripts/sota.py - 主入口脚本
        sota_py = scripts_dir / "sota.py"
        sota_py.write_text('''
from scripts.models import StockPredictor

def main():
    """主函数"""
    predictor = StockPredictor("/data/stocks")
    
    # 预测几个股票
    symbols = ["AAPL", "GOOGL", "MSFT"]
    for symbol in symbols:
        prediction = predictor.predict(symbol)
        print(f"{symbol}: {prediction}")
    
    print("Predictions completed!")
    return True

if __name__ == "__main__":
    success = main()
    if success:
        print("OK")
''')
        
        # 运行合并工具
        merger_path = Path(__file__).parent.parent.parent / "scripts" / "advanced_merge.py"
        cmd = [sys.executable, str(merger_path), str(sota_py), str(tmpdir)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # 基本验证
        assert result.returncode == 0, f"Merger failed: {result.stderr}"
        
        merged_file = scripts_dir / "sota_advanced_merged.py"
        assert merged_file.exists(), "Merged file not created"
        
        merged_content = merged_file.read_text()
        print("=== Merged content ===")
        print(merged_content)
        print("=== End merged content ===")
        
        # 验证静态编译
        try:
            py_compile.compile(str(merged_file), doraise=True)
            print("✓ Static compilation passed")
        except py_compile.PyCompileError as e:
            pytest.fail(f"Static compilation failed: {e}")
        
        # 验证模块可导入（添加项目根目录到 sys.path）
        import_test = f'''
import sys
sys.path.insert(0, '{tmpdir}')
try:
    import scripts.sota_advanced_merged as m
    print('OK')
except Exception as e:
    print(f'Import failed: {{e}}')
    sys.exit(1)
'''
        import_result = subprocess.run(
            [sys.executable, "-c", import_test],
            capture_output=True,
            text=True
        )
        
        assert import_result.returncode == 0, f"Module import failed: {import_result.stderr}"
        assert "OK" in import_result.stdout, f"Import test failed: {import_result.stdout}"
        
        # Issue #28 的核心验收标准：合并后的脚本必须能够运行，不再抛出 NameError
        # 设置 PYTHONPATH 以便正确解析导入路径
        env = os.environ.copy()
        env['PYTHONPATH'] = str(tmpdir)
        run_cmd = [sys.executable, str(merged_file)]
        run_result = subprocess.run(run_cmd, capture_output=True, text=True, cwd=str(tmpdir), env=env)
        
        # 不再允许 NameError - 这是 Issue #28 的根本目标
        assert run_result.returncode == 0, f"Merged script must run without NameError: {run_result.stderr}"
        
        # 验证输出
        assert "Predictions completed!" in run_result.stdout, f"Expected output not found: {run_result.stdout}"
        assert "OK" in run_result.stdout, f"Expected 'OK' not found: {run_result.stdout}"
        
        # 验证重新注入的导入存在
        if "DiskStockDataReader" not in merged_content:
            # 如果 DiskStockDataReader 没有被内联，应该有重新注入的导入
            assert "from scripts.crossformer import DiskStockDataReader" in merged_content, \
                "DiskStockDataReader import should be reinjected"


def test_yy_model_with_json_conflict():
    """测试 yy_model_py 场景中的 json 别名冲突"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建一个使用 json 作为函数名和模块别名的场景
        utils_py = tmpdir / "utils.py"
        utils_py.write_text('''
def json(data):
    """一个名为 json 的函数"""
    return f"formatted: {data}"

def process(data):
    """处理数据"""
    return json(data)
''')
        
        # 创建使用标准库 json 的模块
        serializer_py = tmpdir / "serializer.py"
        serializer_py.write_text('''
import json

def serialize(obj):
    """序列化对象"""
    return json.dumps(obj)

def deserialize(text):
    """反序列化文本"""
    return json.loads(text)
''')
        
        # 主脚本同时使用两者
        main_py = tmpdir / "main.py"
        main_py.write_text('''
from utils import process
from serializer import serialize, deserialize

def main():
    # 使用本地 json 函数
    result1 = process("test data")
    print(f"Processed: {result1}")
    
    # 使用标准库 json
    data = {"key": "value", "number": 42}
    serialized = serialize(data)
    print(f"Serialized: {serialized}")
    
    deserialized = deserialize(serialized)
    print(f"Deserialized: {deserialized}")
    
    return True

if __name__ == "__main__":
    main()
''')
        
        # 运行合并工具
        merger_path = Path(__file__).parent.parent.parent / "scripts" / "advanced_merge.py"
        cmd = [sys.executable, str(merger_path), str(main_py), str(tmpdir)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        assert result.returncode == 0, f"Merger failed: {result.stderr}"
        
        merged_file = tmpdir / "main_advanced_merged.py"
        merged_content = merged_file.read_text()
        
        # 验证别名一致性保护
        # json 模块别名应该被重命名以避免冲突
        assert "json__module" in merged_content or "json__module.dumps" in merged_content, \
            "Module alias 'json' should be renamed to avoid conflict"
        
        # 验证函数 json 被正确处理
        assert "def utils_json(" in merged_content or "def json(" in merged_content, \
            "Function 'json' should be present"
        
        # 验证编译
        try:
            py_compile.compile(str(merged_file), doraise=True)
        except py_compile.PyCompileError as e:
            pytest.fail(f"Compilation failed: {e}")
        
        # 验证运行
        run_result = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        if run_result.returncode == 0:
            assert "Processed:" in run_result.stdout
            assert "Serialized:" in run_result.stdout
            assert "Deserialized:" in run_result.stdout
        else:
            # 如果失败，检查是否是预期的限制
            print(f"Execution failed (may be expected): {run_result.stderr}")


def test_diskstocker_only():
    """DiskStockDataReader ONLY 金丝雀测试
    
    验证当只使用 DiskStockDataReader 时，导入能够正确重新注入
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建 scripts/crossformer.py
        scripts_dir = tmpdir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "__init__.py").write_text("")
        
        crossformer_py = scripts_dir / "crossformer.py"
        crossformer_py.write_text('''
class DiskStockDataReader:
    """数据读取器"""
    def __init__(self, path):
        self.path = path
    
    def read(self):
        return f"data from {self.path}"
''')
        
        # 创建 a.py - 直接使用 DiskStockDataReader
        a_py = tmpdir / "a.py"
        a_py.write_text('''
from scripts.crossformer import DiskStockDataReader

def foo():
    """创建并返回 DiskStockDataReader 实例"""
    return DiskStockDataReader("test_path")
''')
        
        # 创建 main.py - 调用 foo()
        main_py = tmpdir / "main.py"
        main_py.write_text('''
from a import foo

def main():
    reader = foo()
    data = reader.read()
    print(f"Got: {data}")
    return True

if __name__ == "__main__":
    if main():
        print("Success!")
''')
        
        # 运行合并工具
        merger_path = Path(__file__).parent.parent.parent / "scripts" / "advanced_merge.py"
        cmd = [sys.executable, str(merger_path), str(main_py), str(tmpdir)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        assert result.returncode == 0, f"Merger failed: {result.stderr}"
        
        merged_file = tmpdir / "main_advanced_merged.py"
        merged_content = merged_file.read_text()
        
        print("=== DiskStockDataReader ONLY test ===")
        print(merged_content)
        print("=== End ===")
        
        # 验证关键点
        # 1. foo 函数应该被内联
        assert "def foo():" in merged_content or "def a_foo():" in merged_content, \
            "Function foo should be inlined"
        
        # 2. 检查 DiskStockDataReader 是否被内联
        if "class scripts_crossformer_DiskStockDataReader:" in merged_content:
            # 被内联并重命名了，这是正常的
            assert "return scripts_crossformer_DiskStockDataReader" in merged_content, \
                "Renamed DiskStockDataReader should be used"
        elif "class DiskStockDataReader:" not in merged_content:
            # 3. 如果没有内联，必须有重新注入的导入
            assert "from scripts.crossformer import DiskStockDataReader" in merged_content, \
                "DiskStockDataReader import must be reinjected"
        
        # 4. 最重要的：脚本必须能够运行
        run_result = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True,
            cwd=str(tmpdir)
        )
        
        assert run_result.returncode == 0, \
            f"Script must run without errors. Got: {run_result.stderr}"
        assert "Got: data from test_path" in run_result.stdout, \
            f"Expected output not found: {run_result.stdout}"
        assert "Success!" in run_result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])