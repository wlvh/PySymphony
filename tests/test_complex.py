"""
复杂依赖关系测试脚本
"""

from .fixtures.test_pkg.complex_deps import main_handler

if __name__ == '__main__':
    result = main_handler("test_data")
    print(f"复杂依赖测试结果: {result}")