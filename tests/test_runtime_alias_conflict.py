"""
测试 B2 修复：运行时别名冲突
验证 import_alias 添加 __mod 后缀后不会与本地函数冲突
"""
import pytest
import tempfile
import subprocess
import sys
from pathlib import Path
from scripts.advanced_merge import AdvancedCodeMerger


def test_import_alias_function_conflict():
    """测试导入别名与本地函数同名的情况"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建主脚本，同时有 import json 和 def json()
        main_script = tmpdir / "main.py"
        main_script.write_text("""
try:
    import orjson as json
except ImportError:
    import json

def json():
    return "I am a function, not a module"

if __name__ == '__main__':
    # 使用模块的 dumps 方法
    print(json.dumps({"key": "value"}))
    # 调用本地函数
    print(json())
""")
        
        # 执行合并
        merger = AdvancedCodeMerger(tmpdir)
        result = merger.merge_script(main_script)
        
        # 验证结果
        assert result is not None
        
        # 验证 import_alias 被重命名为 __mod 后缀
        assert "json__mod" in result
        assert "json__mod.dumps" in result
        
        # 验证本地函数保持原名
        assert "def json():" in result
        assert 'return "I am a function, not a module"' in result
        
        # 保存合并后的文件
        merged_file = tmpdir / "main_merged.py"
        merged_file.write_text(result)
        
        # 运行合并后的代码，验证没有 TypeError
        proc = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert proc.returncode == 0, f"运行失败：{proc.stderr}"
        assert '{"key": "value"}' in proc.stdout
        assert "I am a function, not a module" in proc.stdout


def test_multiple_import_aliases():
    """测试多个导入别名的情况"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建主脚本，有多个导入别名
        main_script = tmpdir / "main.py"
        main_script.write_text("""
import os
import sys as system
from pathlib import Path as PathLib

def os():
    return "local os function"

def system():
    return "local system function"

def PathLib():
    return "local PathLib function"

if __name__ == '__main__':
    # 使用导入的模块
    print(os.path.join('a', 'b'))
    print(system.version)
    print(str(PathLib('.')))
    
    # 使用本地函数
    print(os())
    print(system())
    print(PathLib())
""")
        
        # 执行合并
        merger = AdvancedCodeMerger(tmpdir)
        result = merger.merge_script(main_script)
        
        # 验证所有 import_alias 都被重命名
        assert "os__mod" in result
        assert "system__mod" in result
        assert "PathLib__mod" in result
        
        # 验证使用处也被正确替换
        assert "os__mod.path.join" in result
        assert "system__mod.version" in result
        assert "PathLib__mod(" in result
        
        # 验证本地函数保持原名
        assert "def os():" in result
        assert "def system():" in result
        assert "def PathLib():" in result
        
        # 保存并运行
        merged_file = tmpdir / "main_merged.py"
        merged_file.write_text(result)
        
        proc = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert proc.returncode == 0, f"运行失败：{proc.stderr}"
        assert "local os function" in proc.stdout
        assert "local system function" in proc.stdout
        assert "local PathLib function" in proc.stdout


def test_nested_import_with_conflict():
    """测试嵌套导入和冲突的情况"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建一个模块
        module_dir = tmpdir / "mymodule"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")
        (module_dir / "utils.py").write_text("""
import json

def process_data(data):
    return json.dumps(data)

def json():
    # 这个函数与导入的 json 模块同名
    return "utils.json function"
""")
        
        # 创建主脚本
        main_script = tmpdir / "main.py"
        main_script.write_text("""
from mymodule.utils import process_data, json

if __name__ == '__main__':
    print(process_data({"test": "data"}))
    print(json())
""")
        
        # 执行合并
        merger = AdvancedCodeMerger(tmpdir)
        result = merger.merge_script(main_script)
        
        # 验证结果
        assert result is not None
        assert "json__mod" in result
        assert "json__mod.dumps" in result
        
        # 保存并运行
        merged_file = tmpdir / "main_merged.py"
        merged_file.write_text(result)
        
        proc = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert proc.returncode == 0, f"运行失败：{proc.stderr}"
        assert '{"test": "data"}' in proc.stdout
        assert "utils.json function" in proc.stdout


if __name__ == "__main__":
    # 直接运行测试
    test_import_alias_function_conflict()
    test_multiple_import_aliases()
    test_nested_import_with_conflict()
    print("✅ 所有运行时别名冲突测试通过")