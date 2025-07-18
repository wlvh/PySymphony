"""alias_chain测试用例 - 验证三级链alias.sub.func()的重写"""

class sub:
    @staticmethod
    def func():
        return "OK"