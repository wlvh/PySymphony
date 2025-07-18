"""
测试独特函数名不应该被重命名的情况
"""

def unique_function():
    """这个函数名在整个项目中是独特的，不应该被重命名"""
    print("I am unique function")
    return "unique_result"

def another_unique():
    """另一个独特的函数"""
    result = unique_function()
    print(f"Got result: {result}")
    return result