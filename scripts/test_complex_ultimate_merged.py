# From test_pkg/complex_deps.py
def base_util():
    """基础工具函数"""
    return 'base'

# From test_pkg/complex_deps.py
def formatter(value):
    """格式化函数，依赖base_util"""
    base = base_util()
    return f'formatted_{base}_{value}'

# From test_pkg/complex_deps.py
def validator(data):
    """验证函数，依赖formatter"""
    formatted = formatter(data)
    return f'validated_{formatted}'

# From test_pkg/complex_deps.py
def processor(input_data):
    """处理函数，依赖validator和base_util"""
    valid = validator(input_data)
    base = base_util()
    return f'processed_{valid}_{base}'

# From test_pkg/complex_deps.py
def main_handler(data):
    """主处理函数，依赖processor和formatter"""
    processed = processor(data)
    formatted = formatter('final')
    return f'handled_{processed}_{formatted}'

'\n复杂依赖关系测试脚本\n'
if __name__ == '__main__':
    result = main_handler('test_data')
    print(f'复杂依赖测试结果: {result}')