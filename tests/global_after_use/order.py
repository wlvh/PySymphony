"""global_after_use测试用例 - 验证先使用后定义的模块级变量 + global声明"""

def use_before_define():
    global var_defined_later
    var_defined_later = "works"
    return var_defined_later

# 在函数后面定义
var_defined_later = None

if __name__ == "__main__":
    result = use_before_define()
    print(result)