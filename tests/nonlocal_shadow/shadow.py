"""nonlocal_shadow测试用例 - 验证nonlocal名不能被注册为局部变量或被重命名"""

def outer():
    x = 1
    
    def inner():
        nonlocal x
        x += 1
        return x
    
    return inner()

if __name__ == "__main__":
    result = outer()
    print(result)