#!/usr/bin/env python3
"""
测试基类定义顺序问题
"""
import pytest
import tempfile
import shutil
from pathlib import Path
import sys
import subprocess

def test_base_class_dependency_order():
    """测试基类定义必须在派生类之前"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建测试包结构
        pkg_dir = tmpdir / "test_pkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        
        # base.py - 定义基类
        (pkg_dir / "base.py").write_text("""
class BaseClass:
    def base_method(self):
        return "base"
""")
        
        # derived.py - 定义派生类
        (pkg_dir / "derived.py").write_text("""
from .base import BaseClass

class DerivedClass(BaseClass):
    def derived_method(self):
        return "derived"
""")
        
        # main.py - 使用派生类
        main_py = tmpdir / "main.py"
        main_py.write_text("""
from test_pkg.derived import DerivedClass

if __name__ == "__main__":
    obj = DerivedClass()
    print(obj.base_method())
    print(obj.derived_method())
""")
        
        # 运行合并工具
        cmd = [
            sys.executable,
            "scripts/advanced_merge.py",
            str(main_py),
            str(tmpdir)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # 检查合并是否成功
        assert result.returncode == 0, f"Merge failed: {result.stderr}"
        
        # 检查生成的文件
        merged_file = tmpdir / "main_advanced_merged.py"
        assert merged_file.exists()
        
        merged_content = merged_file.read_text()
        
        # 验证基类在派生类之前定义
        base_class_pos = merged_content.find("class BaseClass:")
        derived_class_pos = merged_content.find("class DerivedClass(BaseClass):")
        
        assert base_class_pos != -1, "BaseClass not found in merged file"
        assert derived_class_pos != -1, "DerivedClass not found in merged file"
        assert base_class_pos < derived_class_pos, "BaseClass must be defined before DerivedClass"
        
        # 验证合并后的文件可以执行
        exec_result = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert exec_result.returncode == 0, f"Execution failed: {exec_result.stderr}"
        assert "base\nderived\n" in exec_result.stdout


def test_multiple_inheritance_order():
    """测试多重继承的顺序依赖"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建测试包结构
        pkg_dir = tmpdir / "test_pkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        
        # mixin1.py
        (pkg_dir / "mixin1.py").write_text("""
class Mixin1:
    def mixin1_method(self):
        return "mixin1"
""")
        
        # mixin2.py
        (pkg_dir / "mixin2.py").write_text("""
class Mixin2:
    def mixin2_method(self):
        return "mixin2"
""")
        
        # base.py - 使用 mixin
        (pkg_dir / "base.py").write_text("""
from .mixin1 import Mixin1
from .mixin2 import Mixin2

class BaseWithMixins(Mixin1, Mixin2):
    def base_method(self):
        return "base"
""")
        
        # main.py
        main_py = tmpdir / "main.py"
        main_py.write_text("""
from test_pkg.base import BaseWithMixins

if __name__ == "__main__":
    obj = BaseWithMixins()
    print(obj.mixin1_method())
    print(obj.mixin2_method())
    print(obj.base_method())
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
        
        # 验证合并后的文件
        merged_file = tmpdir / "main_advanced_merged.py"
        merged_content = merged_file.read_text()
        
        # 验证顺序：Mixin1和Mixin2必须在BaseWithMixins之前
        mixin1_pos = merged_content.find("class Mixin1:")
        mixin2_pos = merged_content.find("class Mixin2:")
        base_pos = merged_content.find("class BaseWithMixins(Mixin1, Mixin2):")
        
        assert mixin1_pos < base_pos, "Mixin1 must be defined before BaseWithMixins"
        assert mixin2_pos < base_pos, "Mixin2 must be defined before BaseWithMixins"
        
        # 验证执行
        exec_result = subprocess.run(
            [sys.executable, str(merged_file)],
            capture_output=True,
            text=True
        )
        
        assert exec_result.returncode == 0, f"Execution failed: {exec_result.stderr}"
        assert "mixin1\nmixin2\nbase\n" in exec_result.stdout


if __name__ == "__main__":
    test_base_class_dependency_order()
    test_multiple_inheritance_order()
    print("All tests passed!")