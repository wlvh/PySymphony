"""deep_relative_import测试用例 - 验证多级相对导入"""
from .a.b.c import val

if __name__ == "__main__":
    print(val)