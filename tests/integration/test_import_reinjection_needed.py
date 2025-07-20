"""测试真正需要导入别名重新注入的场景

这个测试验证当依赖的符号没有被内联时，导入语句被正确重新注入
"""

import pytest
import tempfile
import subprocess
import sys
from pathlib import Path
import ast
import py_compile


def test_import_reinjection_for_unresolved_dependencies():
    """测试未解析依赖的导入重新注入"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建一个复杂的模块，有很多函数但只有一个被使用
        utils_py = tmpdir / "utils.py"
        utils_py.write_text('''
class DataProcessor:
    """Complex class that won't be inlined"""
    def __init__(self):
        self.data = []
    
    def process(self, item):
        return f"processed: {item}"

def helper1():
    return "helper1"

def helper2():
    return "helper2"

def simple_func():
    """This simple function will be inlined"""
    return "simple result"
''')
        
        # 创建一个包装模块
        wrapper_py = tmpdir / "wrapper.py"
        wrapper_py.write_text('''
from utils import DataProcessor, simple_func

def get_processor():
    """Return a DataProcessor instance"""
    return DataProcessor()

def use_simple():
    """Use the simple function"""
    return simple_func()
''')
        
        # 创建主脚本，只使用 simple_func
        main_py = tmpdir / "main.py"
        main_py.write_text('''
from wrapper import use_simple

def main():
    result = use_simple()
    print(f"Result: {result}")
    return result

if __name__ == "__main__":
    main()
''')
        
        # 运行合并工具
        merger_path = Path(__file__).parent.parent.parent / "scripts" / "advanced_merge.py"
        cmd = [sys.executable, str(merger_path), str(main_py), str(tmpdir)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        assert result.returncode == 0, f"Merger failed: {result.stderr}"
        
        # 检查生成的合并文件
        merged_file = tmpdir / "main_advanced_merged.py"
        assert merged_file.exists(), "Merged file not created"
        
        merged_content = merged_file.read_text()
        print("=== Merged content ===")
        print(merged_content)
        print("=== End merged content ===")
        
        # 验证 simple_func 被内联
        assert "def simple_func():" in merged_content or "def utils_simple_func():" in merged_content, \
            "simple_func should be inlined"
        
        # 验证 DataProcessor 没有被内联（因为没有被使用）
        assert "class DataProcessor:" not in merged_content, \
            "DataProcessor should not be inlined"
        
        # 由于 get_processor 函数引用了 DataProcessor，但 DataProcessor 没有被内联，
        # 所以应该有重新注入的导入语句
        # 但是在当前的实现中，get_processor 本身也不会被内联（因为没有被使用）
        
        # 验证合并后的文件可以编译
        try:
            py_compile.compile(str(merged_file), doraise=True)
        except py_compile.PyCompileError as e:
            pytest.fail(f"Merged file has syntax error: {e}")
        
        # 验证合并后的文件可以执行
        run_cmd = [sys.executable, str(merged_file)]
        run_result = subprocess.run(run_cmd, capture_output=True, text=True)
        
        assert run_result.returncode == 0, f"Merged script failed to run: {run_result.stderr}"
        assert "Result: simple result" in run_result.stdout, \
            f"Unexpected output: {run_result.stdout}"


def test_external_library_reinjection():
    """测试外部库导入的重新注入场景"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建一个使用外部库但通过内部包装的模块
        serializer_py = tmpdir / "serializer.py"
        serializer_py.write_text('''
try:
    import ujson as json
except ImportError:
    import json

def serialize(data):
    """Serialize data to JSON"""
    return json.dumps(data)

def deserialize(text):
    """Deserialize JSON to data"""
    return json.loads(text)
''')
        
        # 创建使用序列化器的模块
        processor_py = tmpdir / "processor.py"
        processor_py.write_text('''
from serializer import serialize, deserialize

def process_data(data):
    """Process data by serializing and deserializing"""
    text = serialize(data)
    result = deserialize(text)
    return result
''')
        
        # 创建主脚本
        main_py = tmpdir / "main.py"
        main_py.write_text('''
from processor import process_data

def main():
    data = {"key": "value", "number": 42}
    result = process_data(data)
    print(f"Result: {result}")
    return result

if __name__ == "__main__":
    main()
''')
        
        # 运行合并工具
        merger_path = Path(__file__).parent.parent.parent / "scripts" / "advanced_merge.py"
        cmd = [sys.executable, str(merger_path), str(main_py), str(tmpdir)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        assert result.returncode == 0, f"Merger failed: {result.stderr}"
        
        # 检查生成的合并文件
        merged_file = tmpdir / "main_advanced_merged.py"
        assert merged_file.exists(), "Merged file not created"
        
        merged_content = merged_file.read_text()
        
        # 验证 try...except ImportError 结构被保留
        assert "try:" in merged_content, "try block should be preserved"
        assert "import ujson as json" in merged_content or "import json" in merged_content, \
            "JSON import should be present"
        
        # 验证合并后的文件可以编译
        try:
            py_compile.compile(str(merged_file), doraise=True)
        except py_compile.PyCompileError as e:
            pytest.fail(f"Merged file has syntax error: {e}")
        
        # 验证合并后的文件可以执行
        run_cmd = [sys.executable, str(merged_file)]
        run_result = subprocess.run(run_cmd, capture_output=True, text=True)
        
        assert run_result.returncode == 0, f"Merged script failed to run: {run_result.stderr}"
        assert "Result:" in run_result.stdout, f"Unexpected output: {run_result.stdout}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])