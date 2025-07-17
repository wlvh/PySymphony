"""all_list测试用例 - 验证__all__列表内名称随重命名同步"""

__all__ = ['exported_func', 'ExportedClass']

def exported_func():
    return "exported"

def private_func():
    return "private"

class ExportedClass:
    def method(self):
        return "class method"

if __name__ == "__main__":
    print(exported_func())
    print(ExportedClass().method())