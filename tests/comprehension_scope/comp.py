"""comprehension_scope测试用例 - 验证推导式loop变量不计为外部依赖"""

def process_data():
    # 推导式中的i不应该被认为是外部依赖
    result = [i * 2 for i in range(5)]
    
    # 生成器表达式中的x也不应该被认为是外部依赖
    gen = (x ** 2 for x in result)
    
    # 字典推导式中的k, v不应该被认为是外部依赖
    dict_result = {k: v for k, v in enumerate(gen)}
    
    return dict_result

if __name__ == "__main__":
    output = process_data()
    print(output)