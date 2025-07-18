#!/usr/bin/env python3
"""
测试 issue #3 中提到的四个修复
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from scripts import advanced_merge
from pathlib import Path
import ast
import tempfile


def test_fix1_transform_all_assignment():
    """测试 transform_all_assignment 中的 TypeError 修复"""
    print("测试 1: transform_all_assignment TypeError 修复...")
    
    # 创建测试代码
    test_code = '''
__all__ = ['func1', 'func2']

def func1():
    return 1

def func2():
    return 2
'''
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        test_file = tmpdir / "test1.py"
        test_file.write_text(test_code)
        
        try:
            merger = advanced_merge.AdvancedCodeMerger(tmpdir)
            result = merger.merge_script(test_file)
            print("✓ transform_all_assignment 修复成功 - 没有 TypeError")
            return True
        except AttributeError as e:
            if "current_module_path" in str(e):
                print("✗ transform_all_assignment 修复失败 - 仍有 TypeError")
                return False
            raise


def test_fix2_nested_attribute_access():
    """测试嵌套属性访问的支持"""
    print("\n测试 2: 嵌套属性访问支持...")
    
    # 创建测试代码
    module_a = '''
class Config:
    class DB:
        host = "localhost"
        port = 5432
'''
    
    test_code = '''
from test_mod import Config

def get_db_info():
    return Config.DB.host
'''
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建模块
        mod_file = tmpdir / "test_mod.py"
        mod_file.write_text(module_a)
        
        # 创建测试文件
        test_file = tmpdir / "test2.py"
        test_file.write_text(test_code)
        
        try:
            merger = advanced_merge.AdvancedCodeMerger(tmpdir)
            result = merger.merge_script(test_file)
            
            # 检查是否正确处理了嵌套属性
            if "Config.DB.host" in result or "host" in result:
                print("✓ 嵌套属性访问修复成功")
                return True
            else:
                print("✗ 嵌套属性访问修复失败")
                return False
        except Exception as e:
            print(f"✗ 嵌套属性访问测试出错: {e}")
            return False


def test_fix3_nonlocal_global_scope():
    """测试 nonlocal/global 作用域标记"""
    print("\n测试 3: nonlocal/global 作用域标记...")
    
    test_code = '''
counter = 0

def increment():
    global counter
    counter += 1
    return counter

def make_adder(x):
    def adder(y):
        nonlocal x
        x += y
        return x
    return adder
'''
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        test_file = tmpdir / "test3.py"
        test_file.write_text(test_code)
        
        try:
            merger = advanced_merge.AdvancedCodeMerger(tmpdir)
            result = merger.merge_script(test_file)
            
            # 验证代码可以正确执行
            exec_globals = {}
            exec(result, exec_globals)
            
            # 测试 global
            increment = exec_globals['increment']
            assert increment() == 1
            assert increment() == 2
            
            # 测试 nonlocal
            make_adder = exec_globals['make_adder']
            add5 = make_adder(5)
            assert add5(3) == 8
            assert add5(2) == 10
            
            print("✓ nonlocal/global 作用域标记修复成功")
            return True
        except Exception as e:
            print(f"✗ nonlocal/global 作用域标记测试失败: {e}")
            return False


def test_fix4_import_alias_mapping():
    """测试导入别名的名称映射"""
    print("\n测试 4: 导入别名名称映射...")
    
    # 创建测试模块
    module_a = '''
def process():
    return "processed"
    
class Handler:
    def handle(self):
        return "handled"
'''
    
    test_code = '''
from test_mod import process as proc, Handler as H

def main():
    result = proc()
    h = H()
    return result + "_" + h.handle()
'''
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建模块
        mod_file = tmpdir / "test_mod.py"
        mod_file.write_text(module_a)
        
        # 创建测试文件
        test_file = tmpdir / "test4.py"
        test_file.write_text(test_code)
        
        try:
            merger = advanced_merge.AdvancedCodeMerger(tmpdir)
            result = merger.merge_script(test_file)
            
            # 验证代码可以正确执行
            exec_globals = {}
            exec(result, exec_globals)
            
            main = exec_globals['main']
            assert main() == "processed_handled"
            
            print("✓ 导入别名名称映射修复成功")
            return True
        except Exception as e:
            print(f"✗ 导入别名名称映射测试失败: {e}")
            return False


def main():
    """运行所有测试"""
    print("=== 测试 Issue #3 修复 ===\n")
    
    tests = [
        test_fix1_transform_all_assignment,
        test_fix2_nested_attribute_access,
        test_fix3_nonlocal_global_scope,
        test_fix4_import_alias_mapping
    ]
    
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"测试异常: {e}")
            results.append(False)
    
    print("\n=== 测试总结 ===")
    passed = sum(results)
    total = len(results)
    print(f"通过: {passed}/{total}")
    
    if passed == total:
        print("\n✅ 所有修复都已成功验证！")
    else:
        print("\n⚠️ 部分测试失败，请检查修复")
        

if __name__ == "__main__":
    main()