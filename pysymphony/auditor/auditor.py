"""
AST Auditor - 工业级多阶段 AST 审计系统

这是 PySymphony 项目的核心质量保证组件，负责对合并后的 Python 代码进行全面的静态分析。
采用多阶段架构设计，确保能够捕获所有潜在的代码缺陷。
"""

import ast
from typing import Dict, Set, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict
import sys


@dataclass
class SymbolInfo:
    """符号信息记录"""
    name: str
    node: ast.AST
    lineno: int
    col_offset: int
    scope: str  # 'global', 'local', 'function', 'class'
    type: str   # 'function', 'class', 'variable', 'import', 'alias'


@dataclass
class ScopeInfo:
    """作用域信息"""
    name: str
    type: str  # 'module', 'function', 'class'
    parent: Optional['ScopeInfo'] = None
    symbols: Dict[str, SymbolInfo] = field(default_factory=dict)
    children: List['ScopeInfo'] = field(default_factory=list)


class SymbolTableBuilder(ast.NodeVisitor):
    """
    阶段一：符号表构建器
    遍历 AST，记录所有符号定义及其作用域信息
    """
    
    def __init__(self):
        self.current_scope: ScopeInfo = ScopeInfo(name='<module>', type='module')
        self.module_scope: ScopeInfo = self.current_scope
        self.duplicate_definitions: List[Tuple[str, List[int]]] = []
        self.in_try_import_error: bool = False  # 标记是否在 try...except ImportError 块中
        self.try_except_symbols: Set[str] = set()  # 记录在 try...except ImportError 块中定义的符号
        
    def enter_scope(self, name: str, scope_type: str):
        """进入新的作用域"""
        new_scope = ScopeInfo(name=name, type=scope_type, parent=self.current_scope)
        self.current_scope.children.append(new_scope)
        self.current_scope = new_scope
        
    def exit_scope(self):
        """退出当前作用域"""
        if self.current_scope.parent:
            self.current_scope = self.current_scope.parent
            
    def add_symbol(self, name: str, node: ast.AST, symbol_type: str):
        """添加符号到当前作用域"""
        # 如果在 try...except ImportError 块中，记录符号
        if self.in_try_import_error and self.current_scope.type == 'module':
            self.try_except_symbols.add(name)
        
        # 检查重复定义
        if name in self.current_scope.symbols:
            existing = self.current_scope.symbols[name]
            # 如果两个定义都在 try...except ImportError 块中，这是预期行为，不报错
            if name in self.try_except_symbols:
                pass  # 跳过错误报告
            # 如果是变量的重新赋值，这在 Python 中是允许的
            elif existing.type == 'variable' and symbol_type == 'variable':
                pass  # 变量重新赋值是正常的，不报错
            else:
                # 其他情况（如函数或类的重复定义）才报错
                self.duplicate_definitions.append((
                    name,
                    [existing.lineno, node.lineno]
                ))
        
        self.current_scope.symbols[name] = SymbolInfo(
            name=name,
            node=node,
            lineno=node.lineno,
            col_offset=node.col_offset,
            scope=self.current_scope.type,
            type=symbol_type
        )
        
    def visit_FunctionDef(self, node: ast.FunctionDef):
        """访问函数定义"""
        self.add_symbol(node.name, node, 'function')
        self.enter_scope(node.name, 'function')
        # 添加参数到函数作用域
        for arg in node.args.args:
            self.add_symbol(arg.arg, arg, 'variable')
        self.generic_visit(node)
        self.exit_scope()
        
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """访问异步函数定义"""
        self.add_symbol(node.name, node, 'function')
        self.enter_scope(node.name, 'function')
        for arg in node.args.args:
            self.add_symbol(arg.arg, arg, 'variable')
        self.generic_visit(node)
        self.exit_scope()
        
    def visit_ClassDef(self, node: ast.ClassDef):
        """访问类定义"""
        self.add_symbol(node.name, node, 'class')
        self.enter_scope(node.name, 'class')
        self.generic_visit(node)
        self.exit_scope()
        
    def _is_try_import_error(self, node: ast.Try) -> bool:
        """检查是否是 try...except ImportError 模式"""
        for handler in node.handlers:
            if handler.type:
                # 检查是否捕获 ImportError
                if isinstance(handler.type, ast.Name) and handler.type.id == 'ImportError':
                    return True
                # 也可能是 except (ImportError, ModuleNotFoundError)
                elif isinstance(handler.type, ast.Tuple):
                    for exc in handler.type.elts:
                        if isinstance(exc, ast.Name) and exc.id in ('ImportError', 'ModuleNotFoundError'):
                            return True
        return False
        
    def visit_Try(self, node: ast.Try):
        """访问 try 语句"""
        # 保存进入此节点前的状态
        original_state = self.in_try_import_error
        
        if self._is_try_import_error(node):
            self.in_try_import_error = True
        
        # 递归访问所有子节点
        self.generic_visit(node)
        
        # 离开此节点时，恢复原始状态
        self.in_try_import_error = original_state
        
    def visit_Import(self, node: ast.Import):
        """访问导入语句"""
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            self.add_symbol(name, node, 'import')
            
    def visit_ImportFrom(self, node: ast.ImportFrom):
        """访问 from...import 语句"""
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            self.add_symbol(name, node, 'import')
            
    def visit_Assign(self, node: ast.Assign):
        """访问赋值语句"""
        # 使用通用的目标注册函数处理所有类型的赋值
        for target in node.targets:
            self._register_targets(target)
        self.generic_visit(node)
        
    def visit_AnnAssign(self, node: ast.AnnAssign):
        """访问带类型注解的赋值语句"""
        if isinstance(node.target, ast.Name):
            self.add_symbol(node.target.id, node, 'variable')
        self.generic_visit(node)
        
    def _register_targets(self, target: ast.AST):
        """
        通用的目标注册助手函数
        递归处理各种 target 节点，支持元组/列表解包
        """
        if isinstance(target, ast.Name):
            # 简单名称赋值
            self.add_symbol(target.id, target, 'variable')
        elif isinstance(target, (ast.Tuple, ast.List)):
            # 元组或列表解包
            for elt in target.elts:
                self._register_targets(elt)
        elif isinstance(target, ast.Starred):
            # 星号表达式 (*args)
            self._register_targets(target.value)
        # 其他情况（如属性赋值、下标赋值等）不创建新的局部变量
        
    def visit_For(self, node: ast.For):
        """访问 for 循环"""
        # 注册循环变量
        self._register_targets(node.target)
        self.generic_visit(node)
        
    def visit_AsyncFor(self, node: ast.AsyncFor):
        """访问异步 for 循环"""
        # 注册循环变量
        self._register_targets(node.target)
        self.generic_visit(node)
        
    def visit_With(self, node: ast.With):
        """访问 with 语句"""
        for item in node.items:
            if item.optional_vars:
                self._register_targets(item.optional_vars)
        self.generic_visit(node)
        
    def visit_AsyncWith(self, node: ast.AsyncWith):
        """访问异步 with 语句"""
        for item in node.items:
            if item.optional_vars:
                self._register_targets(item.optional_vars)
        self.generic_visit(node)
        
    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        """访问异常处理器"""
        if node.name:
            # Python 3.8+ 中 name 是字符串
            if isinstance(node.name, str):
                # 创建一个虚拟的 Name 节点用于记录位置信息
                name_node = ast.Name(id=node.name, ctx=ast.Store())
                name_node.lineno = node.lineno
                name_node.col_offset = node.col_offset
                self.add_symbol(node.name, name_node, 'variable')
            # Python 3.7 及以下版本中 name 是 Name 节点
            elif isinstance(node.name, ast.Name):
                self.add_symbol(node.name.id, node.name, 'variable')
        self.generic_visit(node)
        
    def visit_ListComp(self, node: ast.ListComp):
        """访问列表推导式"""
        # 推导式创建新的作用域
        self.enter_scope('<listcomp>', 'comprehension')
        # 按顺序处理每个生成器：先注册目标，再访问迭代器和条件
        for generator in node.generators:
            # 访问生成器的迭代器部分（可能引用外部或前面生成器的变量）
            self.visit(generator.iter)
            # 注册当前生成器的目标变量
            self._register_targets(generator.target)
            # 访问生成器的条件部分（可能引用当前或前面生成器的变量）
            for if_clause in generator.ifs:
                self.visit(if_clause)
        # 最后访问推导式的主体部分
        self.visit(node.elt)
        self.exit_scope()
        
    def visit_SetComp(self, node: ast.SetComp):
        """访问集合推导式"""
        self.enter_scope('<setcomp>', 'comprehension')
        for generator in node.generators:
            self.visit(generator.iter)
            self._register_targets(generator.target)
            for if_clause in generator.ifs:
                self.visit(if_clause)
        self.visit(node.elt)
        self.exit_scope()
        
    def visit_DictComp(self, node: ast.DictComp):
        """访问字典推导式"""
        self.enter_scope('<dictcomp>', 'comprehension')
        for generator in node.generators:
            self.visit(generator.iter)
            self._register_targets(generator.target)
            for if_clause in generator.ifs:
                self.visit(if_clause)
        self.visit(node.key)
        self.visit(node.value)
        self.exit_scope()
        
    def visit_GeneratorExp(self, node: ast.GeneratorExp):
        """访问生成器表达式"""
        self.enter_scope('<genexpr>', 'comprehension')
        for generator in node.generators:
            self.visit(generator.iter)
            self._register_targets(generator.target)
            for if_clause in generator.ifs:
                self.visit(if_clause)
        self.visit(node.elt)
        self.exit_scope()
        
    def visit_NamedExpr(self, node: ast.NamedExpr):
        """访问海象运算符 (:=)"""
        # 先访问值表达式
        self.visit(node.value)
        # 然后注册目标变量
        if isinstance(node.target, ast.Name):
            self.add_symbol(node.target.id, node, 'variable')


class ReferenceValidator(ast.NodeVisitor):
    """
    阶段二：引用完整性验证器
    验证所有符号引用都能链接到正确的定义
    """
    
    def __init__(self, module_scope: ScopeInfo):
        self.module_scope = module_scope
        self.current_scope = module_scope
        self.undefined_names: List[Tuple[str, int]] = []
        # 获取内置名称集合，使用更可靠的方法
        import builtins
        self.builtin_names = set(dir(builtins))
        # 添加常见的内置变量
        self.builtin_names.update(['__name__', '__file__', '__doc__', '__package__', 
                                  '__loader__', '__spec__', '__cached__', '__annotations__'])
        # 使用栈来跟踪作用域路径
        self.scope_stack = [module_scope]
        # 是否在推导式中
        self.in_comprehension = False
        
    def find_symbol(self, name: str) -> Optional[SymbolInfo]:
        """在当前作用域链中查找符号"""
        scope = self.current_scope
        while scope:
            if name in scope.symbols:
                return scope.symbols[name]
            scope = scope.parent
        return None
        
    def _push_scope(self, scope: ScopeInfo):
        """压入新的作用域"""
        self.scope_stack.append(scope)
        self.current_scope = scope
        
    def _pop_scope(self):
        """弹出当前作用域"""
        if len(self.scope_stack) > 1:
            self.scope_stack.pop()
            self.current_scope = self.scope_stack[-1]
            
    def visit_Name(self, node: ast.Name):
        """访问名称引用"""
        if isinstance(node.ctx, ast.Load):
            # 检查是否是内置名称
            if node.id not in self.builtin_names:
                # 查找符号定义
                symbol = self.find_symbol(node.id)
                if not symbol:
                    self.undefined_names.append((node.id, node.lineno))
                    
    def visit_Attribute(self, node: ast.Attribute):
        """访问属性引用"""
        # B3 修复：实现属性引用验证
        # 首先检查基础对象
        self.visit(node.value)
        
        # 递归解析属性链，获取根符号
        root_obj = node.value
        attr_chain = [node.attr]
        
        while isinstance(root_obj, ast.Attribute):
            attr_chain.insert(0, root_obj.attr)
            root_obj = root_obj.value
            
        # 如果根对象是名称，尝试解析它
        if isinstance(root_obj, ast.Name):
            root_symbol = self.find_symbol(root_obj.id)
            
            if root_symbol:
                # 检查是否是外部模块（如 os, sys 等）
                # 对于外部模块，我们不检查属性
                if root_symbol.type == 'import' and root_obj.id in ['os', 'sys', 'json', 're', 
                                                                           'math', 'datetime', 'pathlib',
                                                                           'collections', 'itertools']:
                    return
                    
                # 对于本地符号，检查第一层属性是否存在
                # 注意：这里只做基础检查，不做深层次的属性验证
                first_attr = attr_chain[0]
                
                # 如果是类符号，检查类的成员
                if root_symbol.type == 'class':
                    # 查找类中定义的方法和属性
                    class_members = set()
                    for child_scope in self.current_scope.children:
                        if child_scope.parent == root_symbol.scope:
                            class_members.update(child_scope.symbols.keys())
                    
                    # 如果属性不在类成员中，记录未定义引用
                    if first_attr not in class_members and first_attr not in ['__init__', '__call__', 
                                                                               '__str__', '__repr__']:
                        self.undefined_names.append((f"{root_obj.id}.{first_attr}", node.lineno))
        
    def visit_FunctionDef(self, node: ast.FunctionDef):
        """访问函数定义"""
        # 查找对应的作用域
        for child in self.current_scope.children:
            if child.name == node.name and child.type == 'function':
                self._push_scope(child)
                self.generic_visit(node)
                self._pop_scope()
                return
        # 如果找不到作用域，仍然访问子节点
        self.generic_visit(node)
        
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """访问异步函数定义"""
        for child in self.current_scope.children:
            if child.name == node.name and child.type == 'function':
                self._push_scope(child)
                self.generic_visit(node)
                self._pop_scope()
                return
        self.generic_visit(node)
        
    def visit_ClassDef(self, node: ast.ClassDef):
        """访问类定义"""
        for child in self.current_scope.children:
            if child.name == node.name and child.type == 'class':
                self._push_scope(child)
                self.generic_visit(node)
                self._pop_scope()
                return
        self.generic_visit(node)
        
    def visit_ListComp(self, node: ast.ListComp):
        """访问列表推导式"""
        # 创建一个临时作用域来模拟推导式的作用域
        comp_scope = ScopeInfo(name='<listcomp>', type='comprehension', parent=self.current_scope)
        
        # 保存当前状态
        saved_scope = self.current_scope
        saved_in_comp = self.in_comprehension
        self.current_scope = comp_scope
        self.in_comprehension = True
        
        # 按照 SymbolTableBuilder 的顺序处理
        for generator in node.generators:
            self.visit(generator.iter)
            # 注册生成器目标变量到临时作用域
            self._register_comp_targets(generator.target, comp_scope)
            for if_clause in generator.ifs:
                self.visit(if_clause)
        self.visit(node.elt)
        
        # 恢复作用域
        self.current_scope = saved_scope
        self.in_comprehension = saved_in_comp
        
    def visit_SetComp(self, node: ast.SetComp):
        """访问集合推导式"""
        comp_scope = ScopeInfo(name='<setcomp>', type='comprehension', parent=self.current_scope)
        saved_scope = self.current_scope
        saved_in_comp = self.in_comprehension
        self.current_scope = comp_scope
        self.in_comprehension = True
        
        for generator in node.generators:
            self.visit(generator.iter)
            self._register_comp_targets(generator.target, comp_scope)
            for if_clause in generator.ifs:
                self.visit(if_clause)
        self.visit(node.elt)
        
        self.current_scope = saved_scope
        self.in_comprehension = saved_in_comp
        
    def visit_DictComp(self, node: ast.DictComp):
        """访问字典推导式"""
        comp_scope = ScopeInfo(name='<dictcomp>', type='comprehension', parent=self.current_scope)
        saved_scope = self.current_scope
        saved_in_comp = self.in_comprehension
        self.current_scope = comp_scope
        self.in_comprehension = True
        
        for generator in node.generators:
            self.visit(generator.iter)
            self._register_comp_targets(generator.target, comp_scope)
            for if_clause in generator.ifs:
                self.visit(if_clause)
        self.visit(node.key)
        self.visit(node.value)
        
        self.current_scope = saved_scope
        self.in_comprehension = saved_in_comp
        
    def visit_GeneratorExp(self, node: ast.GeneratorExp):
        """访问生成器表达式"""
        comp_scope = ScopeInfo(name='<genexpr>', type='comprehension', parent=self.current_scope)
        saved_scope = self.current_scope
        saved_in_comp = self.in_comprehension
        self.current_scope = comp_scope
        self.in_comprehension = True
        
        for generator in node.generators:
            self.visit(generator.iter)
            self._register_comp_targets(generator.target, comp_scope)
            for if_clause in generator.ifs:
                self.visit(if_clause)
        self.visit(node.elt)
        
        self.current_scope = saved_scope
        self.in_comprehension = saved_in_comp
        
    def _register_comp_targets(self, target: ast.AST, scope: ScopeInfo):
        """在推导式作用域中注册目标变量"""
        if isinstance(target, ast.Name):
            # 在临时作用域中注册变量
            scope.symbols[target.id] = SymbolInfo(
                name=target.id,
                node=target,
                lineno=target.lineno,
                col_offset=target.col_offset,
                scope=scope.type,
                type='variable'
            )
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._register_comp_targets(elt, scope)
        elif isinstance(target, ast.Starred):
            self._register_comp_targets(target.value, scope)
            
    def visit_NamedExpr(self, node: ast.NamedExpr):
        """访问海象运算符 (:=)"""
        # 先访问值表达式
        self.visit(node.value)
        # 如果在推导式中，注册变量到当前推导式作用域
        if self.in_comprehension and isinstance(node.target, ast.Name):
            self.current_scope.symbols[node.target.id] = SymbolInfo(
                name=node.target.id,
                node=node.target,
                lineno=node.target.lineno,
                col_offset=node.target.col_offset,
                scope=self.current_scope.type,
                type='variable'
            )


class PatternChecker(ast.NodeVisitor):
    """
    阶段三：特定模式检查器
    检查合并场景特有的问题模式
    """
    
    def __init__(self):
        self.main_blocks: List[int] = []
        self.issues: List[str] = []
        
    def visit_If(self, node: ast.If):
        """检查 if __name__ == "__main__" 模式"""
        if (isinstance(node.test, ast.Compare) and
            len(node.test.ops) == 1 and
            isinstance(node.test.ops[0], ast.Eq) and
            isinstance(node.test.left, ast.Name) and
            node.test.left.id == '__name__' and
            len(node.test.comparators) == 1 and
            isinstance(node.test.comparators[0], ast.Constant) and
            node.test.comparators[0].value == '__main__'):
            self.main_blocks.append(node.lineno)
            
        self.generic_visit(node)


class ASTAuditor:
    """
    主审计器类，协调多个阶段的分析
    """
    
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        
    def _is_try_import_error(self, node: ast.Try) -> bool:
        """检查是否是 try...except ImportError 模式"""
        for handler in node.handlers:
            if handler.type:
                # 检查是否捕获 ImportError
                if isinstance(handler.type, ast.Name) and handler.type.id == 'ImportError':
                    return True
                # 也可能是 except (ImportError, ModuleNotFoundError)
                elif isinstance(handler.type, ast.Tuple):
                    for exc in handler.type.elts:
                        if isinstance(exc, ast.Name) and exc.id in ('ImportError', 'ModuleNotFoundError'):
                            return True
        return False
        
    def audit(self, source_code_or_tree, filename: str = '<unknown>') -> bool:
        """
        对源代码进行完整的多阶段审计
        
        Args:
            source_code_or_tree: 要审计的 Python 源代码字符串或 AST 树
            filename: 文件名（用于错误报告）
            
        Returns:
            bool: 如果没有发现错误返回 True，否则返回 False
        """
        self.errors.clear()
        self.warnings.clear()
        
        # 支持传入 AST 树或源代码字符串
        if isinstance(source_code_or_tree, str):
            try:
                tree = ast.parse(source_code_or_tree, filename)
            except SyntaxError as e:
                self.errors.append(f"语法错误: {e.msg} at line {e.lineno}")
                return False
        else:
            tree = source_code_or_tree
            
        # 阶段一：构建符号表
        symbol_builder = SymbolTableBuilder()
        symbol_builder.visit(tree)
        
        # 检查重复定义
        for name, lines in symbol_builder.duplicate_definitions:
            self.errors.append(
                f"符号 '{name}' 重复定义于第 {lines} 行"
            )
            
        # 阶段二：验证引用完整性
        ref_validator = ReferenceValidator(symbol_builder.module_scope)
        ref_validator.visit(tree)
        
        # 检查未定义的引用
        for name, line in ref_validator.undefined_names:
            self.errors.append(
                f"未定义的名称 '{name}' 在第 {line} 行"
            )
            
        # 阶段三：特定模式检查
        pattern_checker = PatternChecker()
        pattern_checker.visit(tree)
        
        # 检查多个主块
        if len(pattern_checker.main_blocks) > 1:
            self.errors.append(
                f"发现多个 'if __name__ == \"__main__\"' 块在第 {pattern_checker.main_blocks} 行"
            )
            
        # 添加其他模式检查的问题
        self.errors.extend(pattern_checker.issues)
        
        # 后处理：检查顶层符号冲突（包括导入）
        self._check_top_level_conflicts(tree)
        
        return len(self.errors) == 0
        
    def _check_top_level_conflicts(self, tree: ast.AST):
        """后处理：检查顶层符号冲突，包括导入"""
        top_level_symbols: Dict[str, List[int]] = {}
        # 记录在 try...except ImportError 块中的符号
        try_except_symbols: Set[str] = set()
        
        # 首先识别所有在 try...except ImportError 块中定义的符号
        for node in tree.body:
            if isinstance(node, ast.Try) and self._is_try_import_error(node):
                # 收集 try 块中的导入
                for stmt in node.body:
                    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                        if isinstance(stmt, ast.Import):
                            for alias in stmt.names:
                                imported_name = alias.asname if alias.asname else alias.name
                                try_except_symbols.add(imported_name)
                        elif isinstance(stmt, ast.ImportFrom):
                            for alias in stmt.names:
                                imported_name = alias.asname if alias.asname else alias.name
                                try_except_symbols.add(imported_name)
                # 收集 except 块中的导入
                for handler in node.handlers:
                    for stmt in handler.body:
                        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                            if isinstance(stmt, ast.Import):
                                for alias in stmt.names:
                                    imported_name = alias.asname if alias.asname else alias.name
                                    try_except_symbols.add(imported_name)
                            elif isinstance(stmt, ast.ImportFrom):
                                for alias in stmt.names:
                                    imported_name = alias.asname if alias.asname else alias.name
                                    try_except_symbols.add(imported_name)
        
        for node in tree.body:
            symbol_key = None
            
            # 函数和类定义
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbol_key = node.name
                
            # Import 语句
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported_name = alias.asname if alias.asname else alias.name
                    # 如果符号在 try...except ImportError 块中，跳过冲突检查
                    if imported_name in try_except_symbols:
                        continue
                    if imported_name in top_level_symbols:
                        self.errors.append(
                            f"顶层导入 '{imported_name}' 重复定义于第 {[top_level_symbols[imported_name][0], node.lineno]} 行"
                        )
                    else:
                        top_level_symbols[imported_name] = [node.lineno]
                        
            # ImportFrom 语句
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_name = alias.asname if alias.asname else alias.name
                    # 如果符号在 try...except ImportError 块中，跳过冲突检查
                    if imported_name in try_except_symbols:
                        continue
                    if imported_name in top_level_symbols:
                        self.errors.append(
                            f"顶层导入 '{imported_name}' 重复定义于第 {[top_level_symbols[imported_name][0], node.lineno]} 行"
                        )
                    else:
                        top_level_symbols[imported_name] = [node.lineno]
                        
            # 如果有符号键，检查冲突
            if symbol_key:
                if symbol_key in top_level_symbols:
                    # 已经在阶段一报告过，这里跳过
                    pass
                else:
                    top_level_symbols[symbol_key] = [node.lineno]
        
    def get_report(self) -> str:
        """获取详细的审计报告"""
        report = []
        
        if self.errors:
            report.append("=== 错误 ===")
            for error in self.errors:
                report.append(f"✗ {error}")
                
        if self.warnings:
            report.append("\n=== 警告 ===")
            for warning in self.warnings:
                report.append(f"⚠ {warning}")
                
        if not self.errors and not self.warnings:
            report.append("✓ 审计通过：未发现任何问题")
            
        return "\n".join(report)