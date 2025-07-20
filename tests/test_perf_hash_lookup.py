"""
测试 B1 修复：O(N²) Scope Lookup 优化
生成大量函数和类，验证合并性能
"""
import pytest
import tempfile
import time
from pathlib import Path
from scripts.advanced_merge import AdvancedCodeMerger


def generate_large_codebase():
    """生成包含 5000 个函数和 100 个类（每类 50 个方法）的代码"""
    lines = []
    
    # 生成 5000 个独立函数
    for i in range(5000):
        lines.append(f"def func_{i}():")
        lines.append(f"    return 'func_{i}'")
        lines.append("")
    
    # 生成 100 个类，每个类有 50 个方法
    for c in range(100):
        lines.append(f"class Class_{c}:")
        for m in range(50):
            lines.append(f"    def method_{m}(self):")
            lines.append(f"        return 'class_{c}_method_{m}'")
            lines.append("")
        lines.append("")
    
    # 主脚本调用一些函数
    lines.append("if __name__ == '__main__':")
    lines.append("    print(func_0())")
    lines.append("    print(func_1())")
    lines.append("    obj = Class_0()")
    lines.append("    print(obj.method_0())")
    
    return "\n".join(lines)


@pytest.mark.timeout(6)  # 6秒超时（要求 < 5秒 @ Mac M1）
def test_large_codebase_performance():
    """测试大型代码库的合并性能"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 创建测试文件
        test_file = tmpdir / "large_module.py"
        test_file.write_text(generate_large_codebase())
        
        # 创建主脚本
        main_script = tmpdir / "main.py"
        main_script.write_text("""
from large_module import func_0, func_1, Class_0

if __name__ == '__main__':
    print(func_0())
    print(func_1())
    obj = Class_0()
    print(obj.method_0())
""")
        
        # 计时合并过程
        merger = AdvancedCodeMerger(tmpdir)
        start_time = time.time()
        
        # 执行合并
        result = merger.merge_script(main_script)
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        # 验证结果
        assert result is not None
        # 函数可能被重命名，检查函数内容
        assert "return 'func_0'" in result
        assert "return 'func_1'" in result
        # 类可能被重命名
        assert "return 'class_0_method_0'" in result
        
        # 验证性能（< 5秒）
        assert elapsed < 5.0, f"合并耗时 {elapsed:.2f} 秒，超过了 5 秒的限制"
        
        print(f"✅ 合并 5000 个函数 + 100 个类（5000 个方法）耗时：{elapsed:.2f} 秒")


@pytest.mark.timeout(10)
def test_extremely_large_codebase():
    """测试极大代码库的性能（可选，更严格的测试）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # 生成 10000 个函数
        lines = []
        for i in range(10000):
            lines.append(f"def func_{i}():")
            lines.append(f"    return {i}")
            lines.append("")
        
        # 创建测试文件
        test_file = tmpdir / "huge_module.py"
        test_file.write_text("\n".join(lines))
        
        # 创建主脚本
        main_script = tmpdir / "main.py"
        main_script.write_text("from huge_module import func_0\nprint(func_0())")
        
        merger = AdvancedCodeMerger(tmpdir)
        start_time = time.time()
        
        result = merger.merge_script(main_script)
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        assert result is not None
        assert elapsed < 10.0, f"合并耗时 {elapsed:.2f} 秒，性能不足"
        
        print(f"✅ 合并 10000 个函数耗时：{elapsed:.2f} 秒")


if __name__ == "__main__":
    # 直接运行测试
    test_large_codebase_performance()
    test_extremely_large_codebase()