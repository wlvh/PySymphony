"""type_annotation_str测试用例 - 验证字符串注解解析与重写"""

class Cls:
    value: int = 42

def func_with_str_annotation(param: 'Cls | None') -> 'Cls':
    if param is None:
        return Cls()
    return param

def forward_ref_function() -> 'ForwardRef':
    return ForwardRef()

class ForwardRef:
    def method(self) -> str:
        return "forward reference works"

if __name__ == "__main__":
    obj = func_with_str_annotation(None)
    print(obj.value)
    
    ref = forward_ref_function()
    print(ref.method())