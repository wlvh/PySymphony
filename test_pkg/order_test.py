"""
测试函数定义顺序问题
"""

def level_3_func():
    """第三层函数，不依赖其他函数"""
    print("Level 3 function")
    return "level3"

def level_2_func():
    """第二层函数，依赖level_3_func"""
    print("Level 2 function")
    result = level_3_func()
    return f"level2_{result}"

def level_1_func():
    """第一层函数，依赖level_2_func"""
    print("Level 1 function")
    result = level_2_func()
    return f"level1_{result}"