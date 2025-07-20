"""
Issue #39 测试 - 验证 ASTAuditor 正确处理所有变量绑定场景

测试确保 ASTAuditor 不会对以下合法 Python 语法结构产生误报：
- 循环变量 (for, async for)
- 推导式目标变量
- 上下文管理器别名 (with, async with)
- 异常捕获别名 (except ... as ...)
- 海象运算符 (:=)
"""

import ast
import pytest
from pysymphony.auditor.auditor import ASTAuditor


class TestIssue39ScopeBinding:
    """测试所有变量绑定场景的正确处理"""
    
    def test_for_loop_simple(self):
        """测试简单 for 循环变量绑定"""
        code = '''
def test_func():
    for i in range(5):
        print(i)
'''
        tree = ast.parse(code)
        auditor = ASTAuditor()
        result = auditor.audit(tree)
        assert result, f"Expected audit to pass, but got errors: {auditor.get_report()}"
        
    def test_for_loop_unpacking(self):
        """测试 for 循环中的元组解包"""
        code = '''
def test_func(items):
    result = []
    for i, item in enumerate(items):
        result.append((i, item))
    return result
'''
        tree = ast.parse(code)
        auditor = ASTAuditor()
        result = auditor.audit(tree)
        assert result, f"Expected audit to pass, but got errors: {auditor.get_report()}"
        
    def test_for_loop_nested_unpacking(self):
        """测试 for 循环中的嵌套解包"""
        code = '''
def test_func():
    data = [((1, 2), ('a', 'b')), ((3, 4), ('c', 'd'))]
    for (x, y), (a, b) in data:
        print(x, y, a, b)
'''
        tree = ast.parse(code)
        auditor = ASTAuditor()
        result = auditor.audit(tree)
        assert result, f"Expected audit to pass, but got errors: {auditor.get_report()}"
        
    def test_list_comprehension(self):
        """测试列表推导式中的变量绑定"""
        code = '''
def test_func():
    squares = [x**2 for x in range(10)]
    return squares
'''
        tree = ast.parse(code)
        auditor = ASTAuditor()
        result = auditor.audit(tree)
        assert result, f"Expected audit to pass, but got errors: {auditor.get_report()}"
        
    def test_nested_comprehensions(self):
        """测试嵌套推导式"""
        code = '''
def test_func():
    matrix = [[i*j for j in range(3)] for i in range(3)]
    # 字典推导式与条件
    even_squares = {i: i**2 for i in range(10) if i % 2 == 0}
    # 嵌套的复杂推导式
    result = {(i, j): i*j for i in range(3) for j in range(i) if j % 2 == 0}
    return matrix, even_squares, result
'''
        tree = ast.parse(code)
        auditor = ASTAuditor()
        result = auditor.audit(tree)
        assert result, f"Expected audit to pass, but got errors: {auditor.get_report()}"
        
    def test_set_and_dict_comprehensions(self):
        """测试集合和字典推导式"""
        code = '''
def test_func():
    # 集合推导式
    unique_squares = {x**2 for x in range(-5, 6)}
    # 字典推导式
    word_lengths = {word: len(word) for word in ['hello', 'world', 'python']}
    return unique_squares, word_lengths
'''
        tree = ast.parse(code)
        auditor = ASTAuditor()
        result = auditor.audit(tree)
        assert result, f"Expected audit to pass, but got errors: {auditor.get_report()}"
        
    def test_generator_expression(self):
        """测试生成器表达式"""
        code = '''
def test_func():
    # 生成器表达式
    sum_of_squares = sum(x**2 for x in range(10))
    # 带条件的生成器表达式
    even_nums = list(n for n in range(20) if n % 2 == 0)
    return sum_of_squares, even_nums
'''
        tree = ast.parse(code)
        auditor = ASTAuditor()
        result = auditor.audit(tree)
        assert result, f"Expected audit to pass, but got errors: {auditor.get_report()}"
        
    def test_with_statement(self):
        """测试 with 语句的别名绑定"""
        code = '''
def test_func(path):
    content = ""
    with open(path) as f:
        content = f.read()
    return content
'''
        tree = ast.parse(code)
        auditor = ASTAuditor()
        result = auditor.audit(tree)
        assert result, f"Expected audit to pass, but got errors: {auditor.get_report()}"
        
    def test_with_multiple_items(self):
        """测试 with 语句的多个上下文管理器"""
        code = '''
def test_func(path1, path2):
    with open(path1) as f1, open(path2) as f2:
        content1 = f1.read()
        content2 = f2.read()
    return content1, content2
'''
        tree = ast.parse(code)
        auditor = ASTAuditor()
        result = auditor.audit(tree)
        assert result, f"Expected audit to pass, but got errors: {auditor.get_report()}"
        
    def test_except_handler(self):
        """测试异常处理器的别名绑定"""
        code = '''
def test_func(path):
    try:
        with open(path) as f:
            return f.read()
    except IOError as e:
        print(f"Error reading file: {e}")
        return None
    except ValueError as ve:
        print(f"Value error: {ve}")
        return None
'''
        tree = ast.parse(code)
        auditor = ASTAuditor()
        result = auditor.audit(tree)
        assert result, f"Expected audit to pass, but got errors: {auditor.get_report()}"
        
    def test_walrus_operator(self):
        """测试海象运算符（:=）"""
        code = '''
def test_func(items):
    # 在 if 语句中使用
    if (n := len(items)) > 0:
        print(f"Processing {n} items")
        
    # 在 while 循环中使用
    data = iter(items)
    while (item := next(data, None)) is not None:
        print(item)
        
    # 在列表推导式中使用
    results = [y for x in items if (y := x * 2) > 10]
    return results
'''
        tree = ast.parse(code)
        auditor = ASTAuditor()
        result = auditor.audit(tree)
        assert result, f"Expected audit to pass, but got errors: {auditor.get_report()}"
        
    def test_complex_scenario(self):
        """测试 issue #39 中的完整示例"""
        code = '''
def demo(items, path):
    result = []
    # 场景1: for 循环解包
    for i, item in enumerate(items):
        result.append((i, item))

    # 场景2: 列表推导式
    squares = [x**2 for x in range(5)]

    # 场景3: with...as... 别名
    content = ""
    try:
        with open(path) as f:
            content = f.read()
    # 场景4: except...as... 别名
    except IOError as e:
        print(f"Error reading file: {e}")
        
    # 场景5: 海象运算符
    if (n := len(items)) > 0:
        print(f"Processing {n} items")
        
    return result, squares, content
'''
        tree = ast.parse(code)
        auditor = ASTAuditor()
        result = auditor.audit(tree)
        assert result, f"Expected audit to pass, but got errors: {auditor.get_report()}"
        
    def test_async_scenarios(self):
        """测试异步场景的变量绑定"""
        code = '''
async def test_async(cursor, session_factory):
    # 异步 for 循环
    async for row in cursor:
        print(row)
        
    # 异步 with 语句
    async with session_factory() as session:
        result = await session.fetch_data()
        
    # 异步推导式
    results = [x async for x in cursor]
    return results
'''
        tree = ast.parse(code)
        auditor = ASTAuditor()
        result = auditor.audit(tree)
        assert result, f"Expected audit to pass, but got errors: {auditor.get_report()}"
        
    def test_starred_unpacking(self):
        """测试带星号的解包"""
        code = '''
def test_func():
    data = [1, 2, 3, 4, 5]
    first, *middle, last = data
    print(first, middle, last)
    
    # 在 for 循环中使用
    items = [(1, 2, 3), (4, 5, 6, 7), (8, 9)]
    for x, *rest in items:
        print(x, rest)
'''
        tree = ast.parse(code)
        auditor = ASTAuditor()
        result = auditor.audit(tree)
        assert result, f"Expected audit to pass, but got errors: {auditor.get_report()}"
        
    def test_comprehension_scope_isolation(self):
        """测试推导式的作用域隔离"""
        code = '''
def test_func():
    x = 10  # 外部变量
    # 推导式中的 x 不应该影响外部的 x
    squares = [x**2 for x in range(5)]
    # 外部的 x 仍然可用
    print(x)  # 应该打印 10
    return squares
'''
        tree = ast.parse(code)
        auditor = ASTAuditor()
        result = auditor.audit(tree)
        assert result, f"Expected audit to pass, but got errors: {auditor.get_report()}"
        
    def test_nested_with_statements(self):
        """测试嵌套的 with 语句"""
        code = '''
def test_func(db_path, log_path):
    with open(db_path) as db:
        db_content = db.read()
        with open(log_path, 'w') as log:
            log.write(f"Read {len(db_content)} bytes from database")
            return db_content
'''
        tree = ast.parse(code)
        auditor = ASTAuditor()
        result = auditor.audit(tree)
        assert result, f"Expected audit to pass, but got errors: {auditor.get_report()}"