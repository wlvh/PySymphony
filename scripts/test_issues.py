"""
测试脚本：展示当前合并工具的问题
1. 不必要的重命名问题
2. 函数定义顺序问题
"""

from test_pkg.unique_func import unique_function, another_unique
from test_pkg.order_test import level_1_func

if __name__ == '__main__':
    print("=== 测试独特函数 ===")
    unique_function()
    another_unique()
    
    print("\n=== 测试函数调用顺序 ===") 
    result = level_1_func()
    print(f"最终结果: {result}")