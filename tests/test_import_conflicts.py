#!/usr/bin/env python3
"""
测试导入冲突问题
"""
import pytest
import tempfile
import shutil
from pathlib import Path
import sys
import subprocess
import ast

def test_same_alias_different_imports():
    """测试同名别名的不同导入（from torch import nn vs import torch.nn as nn）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建测试包结构
        pkg_dir = tmpdir / "test_pkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        
        # module1.py - 使用 from torch import nn
        (pkg_dir / "module1.py").write_text("""
# 模拟 torch.nn (实际上是一个假的模块)
class nn:
    @staticmethod
    def Linear(in_features, out_features):
        return f"Linear({in_features}, {out_features})"

def create_layer():
    return nn.Linear(10, 20)
""")
        
        # module2.py - 使用 import torch.nn as nn
        (pkg_dir / "module2.py").write_text("""
# 模拟 import torch.nn as nn
class torch:
    class nn:
        @staticmethod
        def Conv2d(in_channels, out_channels):
            return f"Conv2d({in_channels}, {out_channels})"

nn = torch.nn

def create_conv():
    return nn.Conv2d(3, 16)
""")
        
        # main.py - 使用两个模块
        main_py = tmpdir / "main.py"
        main_py.write_text("""
from test_pkg.module1 import create_layer
from test_pkg.module2 import create_conv

if __name__ == "__main__":
    print(create_layer())
    print(create_conv())
""")
        
        # 运行合并工具
        cmd = [
            sys.executable,
            "scripts/advanced_merge.py",
            str(main_py),
            str(tmpdir)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, f"Merge failed: {result.stderr}"
        
        # 检查生成的文件
        merged_file = tmpdir / "main_advanced_merged.py"
        assert merged_file.exists()
        
        merged_content = merged_file.read_text()
        
        # 验证没有同名冲突
        # 应该有不同的名称来区分两个 nn
        assert merged_content.count("class nn:") <= 1, "Should not have duplicate 'class nn:' definitions"
        
        # 验证合并后的文件可以执行
        exec_result = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert exec_result.returncode == 0, f"Execution failed: {exec_result.stderr}"
        assert "Linear(10, 20)" in exec_result.stdout
        assert "Conv2d(3, 16)" in exec_result.stdout


def test_function_alias_vs_module_alias():
    """测试函数别名与模块别名冲突（from torch.utils.checkpoint import checkpoint as cp vs import torch.utils.checkpoint as cp）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建测试包结构
        pkg_dir = tmpdir / "test_pkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        
        # checkpoint_func.py - 定义 checkpoint 函数
        (pkg_dir / "checkpoint_func.py").write_text("""
def checkpoint(func, *args):
    print(f"Checkpointing function {func.__name__}")
    return func(*args)
""")
        
        # module1.py - 导入函数作为 cp
        (pkg_dir / "module1.py").write_text("""
from .checkpoint_func import checkpoint as cp

def use_checkpoint_func():
    def dummy():
        return "checkpoint_result"
    return cp(dummy)
""")
        
        # checkpoint_module.py - 模拟 checkpoint 模块
        (pkg_dir / "checkpoint_module.py").write_text("""
def save_checkpoint(data):
    return f"Saved: {data}"

def load_checkpoint(path):
    return f"Loaded from: {path}"
""")
        
        # module2.py - 导入模块作为 cp
        (pkg_dir / "module2.py").write_text("""
from . import checkpoint_module as cp

def use_checkpoint_module():
    return cp.save_checkpoint("model_state")
""")
        
        # main.py
        main_py = tmpdir / "main.py"
        main_py.write_text("""
from test_pkg.module1 import use_checkpoint_func
from test_pkg.module2 import use_checkpoint_module

if __name__ == "__main__":
    print(use_checkpoint_func())
    print(use_checkpoint_module())
""")
        
        # 运行合并工具
        cmd = [
            sys.executable,
            "scripts/advanced_merge.py",
            str(main_py),
            str(tmpdir)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, f"Merge failed: {result.stderr}"
        
        # 读取合并后的文件
        merged_file = tmpdir / "main_advanced_merged.py"
        merged_content = merged_file.read_text()
        
        # 解析合并后的代码
        tree = ast.parse(merged_content)
        
        # 收集所有顶层赋值的名称
        top_level_names = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in top_level_names:
                    top_level_names[name] += 1
                else:
                    top_level_names[name] = 1
        
        # cp 不应该被重复定义
        assert top_level_names.get('cp', 0) <= 1, "Variable 'cp' should not be assigned multiple times"
        
        # 验证执行
        exec_result = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert exec_result.returncode == 0, f"Execution failed: {exec_result.stderr}"
        assert "checkpoint_result" in exec_result.stdout
        assert "Saved: model_state" in exec_result.stdout


def test_duplicate_function_definitions():
    """测试重复函数定义"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建测试包结构
        pkg_dir = tmpdir / "test_pkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        
        # module1.py - 定义 parse_date
        (pkg_dir / "module1.py").write_text("""
def parse_date(date_str):
    # 第一个版本，简单解析
    return f"v1: {date_str}"

def process_data():
    return parse_date("2024-01-01")
""")
        
        # module2.py - 也定义 parse_date
        (pkg_dir / "module2.py").write_text("""
def parse_date(date_str, format=None):
    # 第二个版本，支持格式参数
    return f"v2: {date_str} (format={format})"

def format_data():
    return parse_date("2024-01-01", format="%Y-%m-%d")
""")
        
        # main.py
        main_py = tmpdir / "main.py"
        main_py.write_text("""
from test_pkg.module1 import process_data
from test_pkg.module2 import format_data

if __name__ == "__main__":
    print(process_data())
    print(format_data())
""")
        
        # 运行合并工具
        cmd = [
            sys.executable,
            "scripts/advanced_merge.py",
            str(main_py),
            str(tmpdir)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, f"Merge failed: {result.stderr}"
        
        # 检查生成的文件
        merged_file = tmpdir / "main_advanced_merged.py"
        merged_content = merged_file.read_text()
        
        # 两个 parse_date 应该被重命名
        assert "test_pkg_module1_parse_date" in merged_content or "parse_date__from_" in merged_content
        assert "test_pkg_module2_parse_date" in merged_content or merged_content.count("def parse_date") == 2
        
        # 验证执行
        exec_result = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert exec_result.returncode == 0, f"Execution failed: {exec_result.stderr}"
        assert "v1: 2024-01-01" in exec_result.stdout
        assert "v2: 2024-01-01 (format=%Y-%m-%d)" in exec_result.stdout


if __name__ == "__main__":
    test_same_alias_different_imports()
    print("✅ test_same_alias_different_imports passed")
    
    test_function_alias_vs_module_alias()
    print("✅ test_function_alias_vs_module_alias passed")
    
    test_duplicate_function_definitions()
    print("✅ test_duplicate_function_definitions passed")
    
    print("\nAll tests passed!")