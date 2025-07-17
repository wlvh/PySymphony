# From test_pkg/order_test.py
def level_3_func():
    """第三层函数，不依赖其他函数"""
    print('Level 3 function')
    return 'level3'

# From test_pkg/unique_func.py
def unique_function():
    """这个函数名在整个项目中是独特的，不应该被重命名"""
    print('I am unique function')
    return 'unique_result'

# From test_pkg/order_test.py
def level_2_func():
    """第二层函数，依赖level_3_func"""
    print('Level 2 function')
    result = level_3_func()
    return f'level2_{result}'

# From test_pkg/unique_func.py
def another_unique():
    """另一个独特的函数"""
    result = unique_function()
    print(f'Got result: {result}')
    return result

# From test_pkg/order_test.py
def level_1_func():
    """第一层函数，依赖level_2_func"""
    print('Level 1 function')
    result = level_2_func()
    return f'level1_{result}'

# Module initialization statements
# From module: test_pkg.order_test
# From module: test_pkg.unique_func

# Main script code
'\n测试脚本：展示当前合并工具的问题\n1. 不必要的重命名问题\n2. 函数定义顺序问题\n'
if __name__ == '__main__':
    print('=== 测试独特函数 ===')
    unique_function()
    another_unique()
    print('\n=== 测试函数调用顺序 ===')
    result = level_1_func()
    print(f'最终结果: {result}')