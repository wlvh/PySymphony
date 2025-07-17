"""
复杂依赖关系测试：多层嵌套依赖
"""

def base_util():
    """基础工具函数"""
    return "base"

def formatter(value):
    """格式化函数，依赖base_util"""
    base = base_util()
    return f"formatted_{base}_{value}"

def validator(data):
    """验证函数，依赖formatter"""
    formatted = formatter(data)
    return f"validated_{formatted}"

def processor(input_data):
    """处理函数，依赖validator和base_util"""
    valid = validator(input_data)
    base = base_util()
    return f"processed_{valid}_{base}"

def main_handler(data):
    """主处理函数，依赖processor和formatter"""
    processed = processor(data)
    formatted = formatter("final")
    return f"handled_{processed}_{formatted}"