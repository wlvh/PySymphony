"""decorator_dependency测试用例 - 验证装饰器先于被装饰函数输出 & 被重命名"""

def my_decorator(func):
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        return f"decorated: {result}"
    return wrapper

@my_decorator
def decorated_function():
    return "original"

if __name__ == "__main__":
    result = decorated_function()
    print(result)