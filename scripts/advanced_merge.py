#!/usr/bin/env python3
"""
高级Python代码合并工具 - 基于统一符号模型和作用域分析

核心架构：
1. 作用域栈 (Scope Stack) - 模拟Python的词法作用域
2. 统一符号模型 (Unified Symbol Model) - 表示所有类型的名称
3. 上下文感知分析器 (Context Aware Visitor) - 递归分析整个项目
4. 智能代码生成器 - 处理重命名、重写和所有边缘情况

使用方法:
    python advanced_merge.py <脚本路径> <项目根目录>
"""

import ast
import copy
import os
import sys
import argparse
from pathlib import Path
from typing import Set, Dict, List, Tuple, Optional, Union, Any
from dataclasses import dataclass, field
from collections import defaultdict, deque
import importlib.util

# 添加项目根目录到 sys.path 以便导入 pysymphony
_script_dir = Path(__file__).parent
_project_root = _script_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from pysymphony.auditor import ASTAuditor


class CircularDependencyError(Exception):
    """循环依赖错误"""
    pass


class UnsupportedFeatureError(Exception):
    """不支持的特性错误"""
    pass


@dataclass
class Scope:
    """作用域定义"""
    scope_type: str  # 'module', 'class', 'function'
    node: ast.AST    # 定义该作用域的AST节点
    symbols: Dict[str, 'Symbol'] = field(default_factory=dict)  # 在此作用域内直接定义的符号
    parent: Optional['Scope'] = None  # 指向父作用域
    module_path: Optional[Path] = None  # 仅用于模块作用域
    nonlocal_vars: Set[str] = field(default_factory=set)  # nonlocal声明的变量
    global_vars: Set[str] = field(default_factory=set)  # global声明的变量
    used_symbols: Set[str] = field(default_factory=set)  # 在此作用域内使用的所有符号名称


@dataclass
class Symbol:
    """统一的符号模型"""
    name: str                 # 原始名称, e.g., 'hello'
    qname: str                # 全局限定名, e.g., 'a_pkg.a.hello'
    symbol_type: str          # 'function', 'class', 'variable', 'import_alias', 'parameter', 'loop_var', 'local_var'
    def_node: ast.AST         # 定义此符号的AST节点
    scope: Scope              # 定义此符号的作用域
    dependencies: Set['Symbol'] = field(default_factory=set)  # 此符号依赖的其他符号
    references: List[ast.AST] = field(default_factory=list)   # 所有引用此符号的AST节点
    is_nested: bool = False   # 是否是嵌套函数/类
    decorators: List['Symbol'] = field(default_factory=list)  # 装饰器符号
    init_statements: List[ast.AST] = field(default_factory=list)  # 模块级初始化语句
    export_list: List[str] = field(default_factory=list)  # __all__ 的导出列表
    is_runtime_import: bool = False  # 是否是在 try...except ImportError 块中的导入

    def __hash__(self):
        return hash((self.qname, id(self.scope)))
    
    def __eq__(self, other):
        if not isinstance(other, Symbol):
            return False
        return self.qname == other.qname and self.scope == other.scope


class ContextAwareVisitor(ast.NodeVisitor):
    """上下文感知的分析器"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.scope_stack: List[Scope] = []
        self.current_module_path: Optional[Path] = None
        self.all_symbols: Dict[str, Symbol] = {}  # qname -> Symbol
        self.module_symbols: Dict[Path, Dict[str, Symbol]] = defaultdict(dict)  # 模块路径 -> 符号映射
        self.external_imports: Set[str] = set()
        self.future_imports: Set[str] = set()
        self.analyzed_modules: Set[Path] = set()
        self.in_try_import_error: bool = False  # 标记是否在 try...except ImportError 块中
        self.defnode_to_scope: Dict[ast.AST, Scope] = {}  # def_node -> Scope 映射，优化查找性能
        
    def push_scope(self, scope: Scope):
        """进入新作用域"""
        if self.scope_stack:
            scope.parent = self.scope_stack[-1]
        self.scope_stack.append(scope)
        
    def pop_scope(self):
        """退出当前作用域"""
        return self.scope_stack.pop()
        
    def current_scope(self) -> Optional[Scope]:
        """获取当前作用域"""
        return self.scope_stack[-1] if self.scope_stack else None
        
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
        
    def resolve_name(self, name: str, from_scope: Optional[Scope] = None) -> Optional[Symbol]:
        """从作用域栈解析名称（LEGB规则）"""
        scope = from_scope or self.current_scope()
        
        # 检查是否有 nonlocal 或 global 声明
        if scope:
            if name in scope.nonlocal_vars:
                # nonlocal 变量 - 跳过当前作用域，从父作用域开始查找
                scope = scope.parent
            elif name in scope.global_vars:
                # global 变量 - 直接跳到模块作用域
                while scope and scope.scope_type != 'module':
                    scope = scope.parent
        
        # 正常的LEGB查找
        while scope:
            if name in scope.symbols:
                return scope.symbols[name]
            scope = scope.parent
            
        return None
        
    def _is_dunder_main_block(self, node: ast.AST) -> bool:
        """检查是否是 if __name__ == '__main__' 块"""
        if isinstance(node, ast.If):
            # 检查条件是否是 __name__ == '__main__'
            test = node.test
            if isinstance(test, ast.Compare):
                if (isinstance(test.left, ast.Name) and test.left.id == '__name__' and
                    len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq) and
                    len(test.comparators) == 1 and isinstance(test.comparators[0], ast.Constant) and
                    test.comparators[0].value == '__main__'):
                    return True
        return False
    
    def get_module_qname(self, module_path: Path) -> str:
        """获取模块的限定名"""
        try:
            rel_path = module_path.relative_to(self.project_root)
            parts = list(rel_path.parts[:-1]) + [rel_path.stem]
            if parts[-1] == '__init__':
                parts = parts[:-1]
            return '.'.join(parts)
        except ValueError:
            return module_path.stem
            
    def resolve_relative_import(self, level: int, module: Optional[str], 
                              current_file: Path) -> Optional[Path]:
        """解析相对导入"""
        if level == 0:
            # 绝对导入
            return self.resolve_module_path(module if module else '')
            
        # 相对导入
        current_package = current_file.parent
        
        # 向上移动 level-1 次
        for _ in range(level - 1):
            current_package = current_package.parent
            if not current_package.is_relative_to(self.project_root):
                return None
                
        if module:
            # from ..module import something
            return self.resolve_module_path(module, current_package)
        else:
            # from .. import something
            return current_package / '__init__.py'
            
    def resolve_module_path(self, module_name: str, 
                          base_path: Optional[Path] = None) -> Optional[Path]:
        """解析模块路径"""
        if not module_name:
            return None
            
        base = base_path or self.project_root
        module_parts = module_name.split('.')
        current_path = base
        
        for part in module_parts:
            current_path = current_path / part
            
        # 尝试作为Python文件
        py_file = current_path.with_suffix('.py')
        if py_file.exists():
            return py_file
            
        # 尝试作为包
        init_file = current_path / '__init__.py'
        if init_file.exists():
            return init_file
            
        return None
        
    def is_internal_module(self, module_name: str, current_file: Path, level: int = 0) -> bool:
        """判断是否为内部模块"""
        if level > 0:
            # 相对导入总是内部的
            return True
            
        module_path = self.resolve_module_path(module_name)
        if module_path and module_path.is_relative_to(self.project_root):
            return True
            
        return False
        
    def analyze_module(self, module_path: Path):
        """分析单个模块"""
        if module_path in self.analyzed_modules:
            return
        
        # --- 保存现场（新增） ---
        _prev_module_path = getattr(self, "current_module_path", None)
        # -----------------------
        
        self.analyzed_modules.add(module_path)
        
        # 保存当前模块路径，以便递归调用后恢复
        old_module_path = self.current_module_path
        self.current_module_path = module_path
        
        try:
            with open(module_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            tree = ast.parse(content, filename=str(module_path))
            
            # 创建模块作用域
            module_scope = Scope(
                scope_type='module',
                node=tree,
                module_path=module_path
            )
            
            # 保存模块作用域以便后续查找
            self.module_symbols[module_path]['__scope__'] = module_scope
            
            self.push_scope(module_scope)
            self.visit(tree)
            self.pop_scope()
        finally:
            # 恢复原来的模块路径
            self.current_module_path = old_module_path
        
        # --- 恢复现场（新增） ---
        self.current_module_path = _prev_module_path
        # -----------------------
        
    def visit_Module(self, node: ast.Module):
        """访问模块节点"""
        # 收集模块级初始化语句
        module_qname = self.get_module_qname(self.current_module_path)
        init_statements = []
        
        # 创建模块符号
        module_symbol = Symbol(
            name=module_qname.split('.')[-1],
            qname=module_qname,
            symbol_type='module',
            def_node=node,
            scope=self.current_scope()
        )
        self.all_symbols[module_qname] = module_symbol
        self.defnode_to_scope[module_symbol.def_node] = module_symbol.scope
        
        for stmt in node.body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                # 处理导入
                self.visit(stmt)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # 函数和类定义
                self.visit(stmt)
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                # Issue #37 修复：赋值语句既是定义也是初始化
                # 需要访问以创建变量符号
                self.visit(stmt)
                # 同时也需要作为初始化语句保留
                init_statements.append(stmt)
            elif isinstance(stmt, ast.Try) and self._is_try_import_error(stmt):
                # 特殊处理 try...except ImportError 块
                # 不再将运行时导入块保留为初始化语句
                # 仅访问以分析内部的导入，这些导入会被转换为普通导入
                self.visit(stmt)
            else:
                # 其他顶层语句（副作用初始化）
                # 总是收集所有语句，包括 if __name__ == '__main__' 块
                init_statements.append(stmt)
                # 但仍然需要访问语句以分析依赖
                self.visit(stmt)
                
        # 存储初始化语句
        if init_statements:
            module_symbol.init_statements = init_statements
            
    def visit_Import(self, node: ast.Import):
        """处理 import 语句"""
        for alias in node.names:
            module_name = alias.name
            # 对于 import a.b.c，Python 实际上创建的是 'a' 作为可访问名称
            alias_name = alias.asname or module_name.split('.')[0]
            
            if self.is_internal_module(module_name, self.current_module_path):
                # 内部模块
                module_path = self.resolve_module_path(module_name)
                if module_path:
                    try:
                        # 递归分析
                        self.analyze_module(module_path)
                    except (FileNotFoundError, OSError):
                        # 如果在 try...except ImportError 块中，静默跳过文件不存在的错误
                        if not self.in_try_import_error:
                            # 如果不在 try...except ImportError 块中，重新抛出异常
                            raise
                        # 否则继续执行，仍然创建导入别名符号
                    
                    # 创建导入别名符号
                    symbol = Symbol(
                        name=alias_name,
                        qname=f"{self.get_module_qname(self.current_module_path)}.{alias_name}",
                        symbol_type='import_alias',
                        def_node=node,
                        scope=self.current_scope(),
                        is_runtime_import=self.in_try_import_error
                    )
                    
                    # 添加对模块符号的依赖
                    module_qname = self.get_module_qname(module_path)
                    if module_qname in self.all_symbols:
                        symbol.dependencies.add(self.all_symbols[module_qname])
                    
                    self.current_scope().symbols[alias_name] = symbol
                    self.all_symbols[symbol.qname] = symbol
                    self.defnode_to_scope[symbol.def_node] = symbol.scope
            else:
                # 外部导入
                # 创建导入别名符号（即使是外部导入）
                symbol = Symbol(
                    name=alias_name,
                    qname=f"{self.get_module_qname(self.current_module_path)}.{alias_name}",
                    symbol_type='import_alias',
                    def_node=node,
                    scope=self.current_scope(),
                    is_runtime_import=self.in_try_import_error
                )
                
                # Issue #37 修复：为外部导入创建模块符号依赖
                # 创建一个虚拟的模块符号作为依赖
                module_symbol = Symbol(
                    name=module_name,
                    qname=module_name,
                    symbol_type='module',
                    def_node=None,
                    scope=None
                )
                symbol.dependencies.add(module_symbol)
                
                self.current_scope().symbols[alias_name] = symbol
                self.all_symbols[symbol.qname] = symbol
                self.defnode_to_scope[symbol.def_node] = symbol.scope
                
                # 如果在 try...except ImportError 块中，不要添加到外部导入列表
                if not self.in_try_import_error:
                    if alias.asname:
                        self.external_imports.add(f"import {module_name} as {alias_name}")
                    else:
                        self.external_imports.add(f"import {module_name}")
                    
    def visit_ImportFrom(self, node: ast.ImportFrom):
        """处理 from ... import ... 语句"""
        # 检查是否是 __future__ 导入
        if node.module == '__future__':
            for alias in node.names:
                self.future_imports.add(f"from __future__ import {alias.name}")
            return
            
        # 检查通配符导入
        if any(alias.name == '*' for alias in node.names):
            raise UnsupportedFeatureError(
                f"Wildcard imports ('from ... import *') are not supported in {self.current_module_path}"
            )
            
        level = node.level or 0
        module_name = node.module or ''
        
        # 解析模块路径
        if level > 0:
            # 相对导入
            module_path = self.resolve_relative_import(level, module_name, self.current_module_path)
        else:
            # 绝对导入
            module_path = self.resolve_module_path(module_name)
            
        if module_path and self.is_internal_module(module_name, self.current_module_path, level):
            # 内部模块
            try:
                # 尝试分析内部模块
                self.analyze_module(module_path)
            except (FileNotFoundError, OSError):
                # 如果在 try...except ImportError 块中，静默跳过文件不存在的错误
                if not self.in_try_import_error:
                    # 如果不在 try...except ImportError 块中，重新抛出异常
                    raise
                # 否则继续执行，仍然创建导入别名符号
            
            for alias in node.names:
                symbol_name = alias.name
                alias_name = alias.asname or symbol_name
                
                # 创建导入别名符号
                symbol = Symbol(
                    name=alias_name,
                    qname=f"{self.get_module_qname(self.current_module_path)}.{alias_name}",
                    symbol_type='import_alias', 
                    def_node=node,
                    scope=self.current_scope(),
                    is_runtime_import=self.in_try_import_error  # 标记是否在 try...except ImportError 块中
                )
                
                # 找到被导入的原始符号
                target_qname = f"{self.get_module_qname(module_path)}.{symbol_name}"
                if target_qname in self.all_symbols:
                    symbol.dependencies.add(self.all_symbols[target_qname])
                    
                self.current_scope().symbols[alias_name] = symbol
                self.all_symbols[symbol.qname] = symbol
                self.defnode_to_scope[symbol.def_node] = symbol.scope
                self.module_symbols[self.current_module_path][alias_name] = symbol
        else:
            # 外部导入
            # 始终为导入创建符号，以便正确跟踪依赖关系
            for alias in node.names:
                symbol_name = alias.name
                alias_name = alias.asname or symbol_name
                
                # 创建导入别名符号（即使是外部导入）
                symbol = Symbol(
                    name=alias_name,
                    qname=f"{self.get_module_qname(self.current_module_path)}.{alias_name}",
                    symbol_type='import_alias',
                    def_node=node,
                    scope=self.current_scope(),
                    is_runtime_import=self.in_try_import_error
                )
                
                # Issue #37 修复：为外部导入创建模块符号依赖
                # 创建一个虚拟的模块符号作为依赖
                if module_name:  # from xxx import yyy 的情况
                    module_symbol = Symbol(
                        name=module_name,
                        qname=module_name,
                        symbol_type='module',
                        def_node=None,
                        scope=None
                    )
                    symbol.dependencies.add(module_symbol)
                
                self.current_scope().symbols[alias_name] = symbol
                self.all_symbols[symbol.qname] = symbol
                self.defnode_to_scope[symbol.def_node] = symbol.scope
                self.module_symbols[self.current_module_path][alias_name] = symbol
            
            # 如果在 try...except ImportError 块中，不要添加到外部导入列表
            if not self.in_try_import_error:
                for alias in node.names:
                    if alias.asname:
                        self.external_imports.add(
                            f"from {module_name} import {alias.name} as {alias.asname}"
                        )
                    else:
                        self.external_imports.add(
                            f"from {module_name} import {alias.name}"
                        )
                    
    def visit_FunctionDef(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]):
        """处理函数定义"""
        # 检查是否是嵌套函数
        is_nested = any(s.scope_type == 'function' for s in self.scope_stack)
        
        # 创建函数符号
        parent_qname = ""
        if self.current_scope().scope_type == 'module':
            parent_qname = self.get_module_qname(self.current_module_path)
        elif self.current_scope().scope_type == 'class':
            # 类方法
            class_symbol = next(
                (s for s in self.all_symbols.values() 
                 if s.def_node == self.current_scope().node), 
                None
            )
            if class_symbol:
                parent_qname = class_symbol.qname
        elif self.current_scope().scope_type == 'function':
            # 嵌套函数
            parent_func = next(
                (s for s in self.all_symbols.values()
                 if s.def_node == self.current_scope().node),
                None
            )
            if parent_func:
                parent_qname = parent_func.qname
                
        qname = f"{parent_qname}.{node.name}" if parent_qname else node.name
        
        symbol = Symbol(
            name=node.name,
            qname=qname,
            symbol_type='function',
            def_node=node,
            scope=self.current_scope(),
            is_nested=is_nested
        )
        
        # 处理装饰器
        for decorator in node.decorator_list:
            decorator_symbols = self.analyze_dependencies(decorator)
            symbol.decorators.extend(decorator_symbols)
            symbol.dependencies.update(decorator_symbols)
            
        # 注册符号（无论是否嵌套）
        # 如果作用域中已经有同名符号，我们需要记录这种冲突
        if node.name in self.current_scope().symbols:
            existing = self.current_scope().symbols[node.name]
            # 如果现有符号是导入别名，应该被函数覆盖（Python语义）
            # 但我们仍然需要在all_symbols中保留两者
        
        self.current_scope().symbols[node.name] = symbol
        
        # 在all_symbols中，如果有重名，添加类型后缀以区分
        if qname in self.all_symbols:
            # 给新符号一个唯一的内部标识
            unique_qname = f"{qname}#{symbol.symbol_type}"
            self.all_symbols[unique_qname] = symbol
            self.defnode_to_scope[symbol.def_node] = symbol.scope
        else:
            self.all_symbols[qname] = symbol
            self.defnode_to_scope[symbol.def_node] = symbol.scope
        
        # 创建函数作用域
        func_scope = Scope(
            scope_type='function',
            node=node,
            module_path=self.current_module_path
        )
        self.push_scope(func_scope)
        
        # 处理所有参数类型
        args = node.args
        # 位置参数
        for arg in args.args:
            param_symbol = Symbol(
                name=arg.arg,
                qname=f"{qname}.{arg.arg}",
                symbol_type='parameter',
                def_node=arg,
                scope=func_scope
            )
            func_scope.symbols[arg.arg] = param_symbol
        
        # 仅关键字参数
        for arg in args.kwonlyargs:
            param_symbol = Symbol(
                name=arg.arg,
                qname=f"{qname}.{arg.arg}",
                symbol_type='parameter',
                def_node=arg,
                scope=func_scope
            )
            func_scope.symbols[arg.arg] = param_symbol
            
        # *args
        if args.vararg:
            param_symbol = Symbol(
                name=args.vararg.arg,
                qname=f"{qname}.{args.vararg.arg}",
                symbol_type='parameter',
                def_node=args.vararg,
                scope=func_scope
            )
            func_scope.symbols[args.vararg.arg] = param_symbol
            
        # **kwargs
        if args.kwarg:
            param_symbol = Symbol(
                name=args.kwarg.arg,
                qname=f"{qname}.{args.kwarg.arg}",
                symbol_type='parameter',
                def_node=args.kwarg,
                scope=func_scope
            )
            func_scope.symbols[args.kwarg.arg] = param_symbol
            
        # 分析函数体
        for stmt in node.body:
            self.visit(stmt)
            
        # 收集函数依赖
        symbol.dependencies.update(self.collect_function_dependencies(node))
        
        # 将函数作用域的used_symbols复制到符号的scope属性
        symbol.scope = func_scope
        
        self.pop_scope()
        
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """处理异步函数定义"""
        self.visit_FunctionDef(node)
        
    def visit_ClassDef(self, node: ast.ClassDef):
        """处理类定义"""
        # 检查是否是嵌套类
        is_nested = any(s.scope_type in ('function', 'class') for s in self.scope_stack)
        
        # 创建类符号
        parent_qname = ""
        if self.current_scope().scope_type == 'module':
            parent_qname = self.get_module_qname(self.current_module_path)
            
        qname = f"{parent_qname}.{node.name}" if parent_qname else node.name
        
        symbol = Symbol(
            name=node.name,
            qname=qname,
            symbol_type='class',
            def_node=node,
            scope=self.current_scope(),
            is_nested=is_nested
        )
        
        # 处理装饰器
        for decorator in node.decorator_list:
            decorator_symbols = self.analyze_dependencies(decorator)
            symbol.decorators.extend(decorator_symbols)
            symbol.dependencies.update(decorator_symbols)
            
        # 处理基类
        for base in node.bases:
            base_symbols = self.analyze_dependencies(base)
            symbol.dependencies.update(base_symbols)
            
        # 注册符号
        self.current_scope().symbols[node.name] = symbol
        self.all_symbols[qname] = symbol
        self.defnode_to_scope[symbol.def_node] = symbol.scope
        
        # 创建类作用域
        class_scope = Scope(
            scope_type='class',
            node=node,
            module_path=self.current_module_path
        )
        self.push_scope(class_scope)
        
        # 分析类体，并收集类方法的依赖
        for stmt in node.body:
            self.visit(stmt)
            
            # 如果是方法定义（FunctionDef 或 AsyncFunctionDef），收集其依赖到类符号
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # 获取方法符号
                method_qname = f"{qname}.{stmt.name}"
                if method_qname in self.all_symbols:
                    method_symbol = self.all_symbols[method_qname]
                    # 将方法的依赖添加到类的依赖中
                    symbol.dependencies.update(method_symbol.dependencies)
            
        self.pop_scope()
        
    def visit_Assign(self, node: ast.Assign):
        """处理赋值语句"""
        # 只在模块级收集变量
        if self.current_scope().scope_type != 'module':
            # 在函数内部也要注册局部变量，以避免错误的依赖分析
            for target in node.targets:
                if isinstance(target, ast.Name):
                    # 检查是否是 nonlocal 或 global 变量
                    current = self.current_scope()
                    if target.id in current.nonlocal_vars or target.id in current.global_vars:
                        # 不要覆盖 nonlocal/global 变量
                        continue
                        
                    local_var = Symbol(
                        name=target.id,
                        qname=f"{self.get_current_qname()}.{target.id}",
                        symbol_type='local_var',
                        def_node=node,
                        scope=self.current_scope()
                    )
                    self.current_scope().symbols[target.id] = local_var
            return
            
        for target in node.targets:
            if isinstance(target, ast.Name):
                # 忽略特殊的内部变量
                if target.id.startswith('_') and target.id != '__all__':
                    continue
                
                # 跳过函数调用的赋值（通常是实例化或函数调用结果）
                if isinstance(node.value, ast.Call):
                    continue
                    
                qname = f"{self.get_module_qname(self.current_module_path)}.{target.id}"
                
                symbol = Symbol(
                    name=target.id,
                    qname=qname,
                    symbol_type='variable',
                    def_node=node,
                    scope=self.current_scope()
                )
                
                # 收集赋值表达式的依赖
                deps = self.analyze_dependencies(node.value)
                symbol.dependencies.update(deps)
                
                # 特殊处理 __all__
                if target.id == '__all__' and isinstance(node.value, (ast.List, ast.Tuple)):
                    # 记录原始的导出列表
                    export_list = []
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            export_list.append(elt.value)
                    # 将导出列表存储在符号的特殊属性中
                    symbol.export_list = export_list
                
                self.current_scope().symbols[target.id] = symbol
                self.all_symbols[qname] = symbol
                self.defnode_to_scope[symbol.def_node] = symbol.scope
                
    def visit_AnnAssign(self, node: ast.AnnAssign):
        """处理带类型注解的赋值"""
        if self.current_scope().scope_type != 'module':
            return
            
        if isinstance(node.target, ast.Name):
            qname = f"{self.get_module_qname(self.current_module_path)}.{node.target.id}"
            
            symbol = Symbol(
                name=node.target.id,
                qname=qname,
                symbol_type='variable',
                def_node=node,
                scope=self.current_scope()
            )
            
            if node.value:
                deps = self.analyze_dependencies(node.value)
                symbol.dependencies.update(deps)
                
            self.current_scope().symbols[node.target.id] = symbol
            self.all_symbols[qname] = symbol
            self.defnode_to_scope[symbol.def_node] = symbol.scope
            
    def visit_For(self, node: Union[ast.For, ast.AsyncFor]):
        """处理 for 循环"""
        # 注册循环变量
        if isinstance(node.target, ast.Name):
            loop_var = Symbol(
                name=node.target.id,
                qname=f"{self.get_current_qname()}.{node.target.id}",
                symbol_type='loop_var',
                def_node=node.target,
                scope=self.current_scope()
            )
            self.current_scope().symbols[node.target.id] = loop_var
        
        # 继续访问循环体
        self.generic_visit(node)
        
    def visit_AsyncFor(self, node: ast.AsyncFor):
        """处理异步 for 循环"""
        self.visit_For(node)
        
    def visit_With(self, node: Union[ast.With, ast.AsyncWith]):
        """处理 with 语句"""
        for item in node.items:
            if item.optional_vars and isinstance(item.optional_vars, ast.Name):
                with_var = Symbol(
                    name=item.optional_vars.id,
                    qname=f"{self.get_current_qname()}.{item.optional_vars.id}",
                    symbol_type='variable',
                    def_node=item.optional_vars,
                    scope=self.current_scope()
                )
                self.current_scope().symbols[item.optional_vars.id] = with_var
        
        self.generic_visit(node)
        
    def visit_AsyncWith(self, node: ast.AsyncWith):
        """处理异步 with 语句"""
        self.visit_With(node)
        
    def visit_ListComp(self, node: ast.ListComp):
        """处理列表推导式"""
        self._visit_comprehension(node)
        
    def visit_SetComp(self, node: ast.SetComp):
        """处理集合推导式"""
        self._visit_comprehension(node)
        
    def visit_DictComp(self, node: ast.DictComp):
        """处理字典推导式"""
        self._visit_comprehension(node)
        
    def visit_GeneratorExp(self, node: ast.GeneratorExp):
        """处理生成器表达式"""
        self._visit_comprehension(node)
        
    def _visit_comprehension(self, node):
        """处理所有推导式的通用逻辑"""
        # 创建推导式作用域
        comp_scope = Scope(
            scope_type='comprehension',
            node=node,
            module_path=self.current_module_path
        )
        self.push_scope(comp_scope)
        
        # 注册推导式中的目标变量
        for generator in node.generators:
            if isinstance(generator.target, ast.Name):
                comp_var = Symbol(
                    name=generator.target.id,
                    qname=f"{self.get_current_qname()}.{generator.target.id}",
                    symbol_type='loop_var',
                    def_node=generator.target,
                    scope=comp_scope
                )
                comp_scope.symbols[generator.target.id] = comp_var
        
        # 访问推导式内容
        self.generic_visit(node)
        
        self.pop_scope()
        
    def get_current_qname(self) -> str:
        """获取当前作用域的限定名"""
        if self.current_scope().scope_type == 'module':
            return self.get_module_qname(self.current_module_path)
        
        # 查找当前作用域对应的符号
        for symbol in self.all_symbols.values():
            if symbol.def_node == self.current_scope().node:
                return symbol.qname
                
        return ""
    
    def visit_Name(self, node: ast.Name):
        """处理名称节点，收集使用的符号"""
        if isinstance(node.ctx, ast.Load):
            # 记录在当前作用域中使用的符号
            self.current_scope().used_symbols.add(node.id)
    
    def visit_Try(self, node: ast.Try):
        """正确管理 try...except 块的访问状态"""
        # 保存进入此节点前的状态
        original_state = self.in_try_import_error
        
        if self._is_try_import_error(node):
            # 访问 try 块中的语句，设置运行时导入标志
            self.in_try_import_error = True
            for stmt in node.body:
                self.visit(stmt)
            
            # 访问 except 块中的语句
            for handler in node.handlers:
                for stmt in handler.body:
                    self.visit(stmt)
            
            # 恢复原始状态
            self.in_try_import_error = original_state
            
            # 访问 else 和 finally 块（如果有）
            for stmt in node.orelse:
                self.visit(stmt)
            for stmt in node.finalbody:
                self.visit(stmt)
        else:
            # 不是 try...except ImportError，正常访问
            self.generic_visit(node)
        
        return node
    
    def analyze_dependencies(self, node: ast.AST, parent_scope: Optional[Scope] = None) -> Set[Symbol]:
        """分析AST节点的依赖，使用作用域栈"""
        if parent_scope:
            # 临时推入父作用域以便正确解析名称
            original_stack_size = len(self.scope_stack)
            self.push_scope(parent_scope)
        
        dependencies = set()
        
        # 使用一个访问器来正确处理作用域
        class LocalDependencyAnalyzer(ast.NodeVisitor):
            def __init__(self, outer):
                self.outer = outer
                self.deps = set()
                
            def visit_Name(self, node):
                if isinstance(node.ctx, ast.Load):
                    symbol = self.outer.resolve_name(node.id)
                    if symbol:
                        # 包含所有非参数、非循环变量的符号
                        # 特别是要包含函数和类符号
                        if symbol.symbol_type in ('function', 'class', 'variable', 'import_alias'):
                            self.deps.add(symbol)
                            # 如果是导入别名，也添加其目标符号
                            if symbol.symbol_type == 'import_alias' and symbol.dependencies:
                                self.deps.update(symbol.dependencies)
                        
            def visit_Attribute(self, node):
                # 改进：递归向右解析属性链
                base = node
                names = []
                
                # 收集整个属性链
                while isinstance(base, ast.Attribute):
                    names.append(base.attr)
                    base = base.value
                    
                if isinstance(base, ast.Name):
                    names.append(base.id)
                    names.reverse()  # 反转以获得正确顺序
                    
                    # 解析根符号
                    root_symbol = self.outer.resolve_name(names[0])
                    if root_symbol and root_symbol.symbol_type == "import_alias":
                        # 如果是导入别名，尝试解析完整的属性链
                        if root_symbol.dependencies:
                            # 获取导入指向的目标模块/符号
                            target = next(iter(root_symbol.dependencies))
                            if len(names) > 1:
                                # 对于 import mypkg.submod，当访问 mypkg.submod.MyClass 时
                                # names = ['mypkg', 'submod', 'MyClass']
                                # target.qname = 'mypkg.submod'
                                # 需要特殊处理：检查 target.qname 是否已经包含了部分路径
                                target_parts = target.qname.split('.')
                                remaining_parts = names[1:]
                                
                                # 如果目标已经包含了一些路径部分，需要去重
                                while remaining_parts and target_parts and target_parts[-1] == remaining_parts[0]:
                                    remaining_parts = remaining_parts[1:]
                                
                                if remaining_parts:
                                    full_qname = target.qname + "." + ".".join(remaining_parts)
                                else:
                                    full_qname = target.qname
                                    
                                if full_qname in self.outer.all_symbols:
                                    # 找到了完整的符号，添加为依赖
                                    self.deps.add(self.outer.all_symbols[full_qname])
                                    return  # 不需要继续遍历
                    elif root_symbol and root_symbol.symbol_type not in ('parameter', 'loop_var', 'local_var'):
                        self.deps.add(root_symbol)
                        
                # 继续遍历子节点
                self.generic_visit(node)
                
            def visit_FunctionDef(self, node):
                # 不进入嵌套函数定义
                pass
                
            def visit_AsyncFunctionDef(self, node):
                # 不进入嵌套异步函数定义
                pass
                
            def visit_ClassDef(self, node):
                # 不进入嵌套类定义
                pass
                
        analyzer = LocalDependencyAnalyzer(self)
        
        # 特殊处理 try...except ImportError 块
        if isinstance(node, ast.Try) and self._is_try_import_error(node):
            # 对于 try...except ImportError 块，我们需要收集所有可能的依赖
            # 包括 try 块和 except 块中的所有导入
            for stmt in node.body:
                analyzer.visit(stmt)
            for handler in node.handlers:
                for stmt in handler.body:
                    analyzer.visit(stmt)
            # 注意：我们还需要确保所有被导入的模块中的符号都被包含
            # 这将在后续的依赖收集中处理
        else:
            analyzer.visit(node)
        
        dependencies = analyzer.deps
                        
        if parent_scope:
            # 恢复原始作用域栈
            while len(self.scope_stack) > original_stack_size:
                self.pop_scope()
                
        return dependencies
        
    def collect_function_dependencies(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> Set[Symbol]:
        """收集函数的所有依赖"""
        dependencies = set()
        
        # 收集函数体的依赖
        for stmt in node.body:
            deps = self.analyze_dependencies(stmt)
            dependencies.update(deps)
            
        return dependencies
    
    def visit_Nonlocal(self, node: ast.Nonlocal):
        """处理nonlocal声明"""
        current = self.current_scope()
        if current and current.scope_type == 'function':
            for name in node.names:
                current.nonlocal_vars.add(name)
        return node
    
    def visit_Global(self, node: ast.Global):
        """处理global声明"""
        current = self.current_scope()
        if current:
            for name in node.names:
                current.global_vars.add(name)
        return node


class AdvancedCodeMerger:
    """高级代码合并器"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.visitor = ContextAwareVisitor(project_root)
        self.needed_symbols: Set[Symbol] = set()
        self.name_mappings: Dict[str, str] = {}  # qname -> new_name
        self.enable_verify = False  # 是否启用验证模式
        self.written_names: Set[str] = set()  # 解决 #1: 已写入的名称集合
        self.import_registry: Set[Tuple[str, str]] = set()  # 解决 #2: (module, alias)
        self.entry_module_qname: Optional[str] = None  # 解决 #3: 入口脚本的模块名
        
    def _fix_import_alias_dependencies(self):
        """修复 import_alias 符号的依赖关系
        
        在所有模块都被分析后，重新建立 import_alias 到实际符号的依赖关系。
        这解决了循环导入时依赖关系缺失的问题。
        """
        for symbol in list(self.visitor.all_symbols.values()):
            if symbol.symbol_type != 'import_alias':
                continue
                
            # 检查是否是 from ... import ... 类型的导入
            if isinstance(symbol.def_node, ast.ImportFrom):
                node = symbol.def_node
                module_name = node.module or ''
                level = node.level or 0
                
                # 解析模块路径
                if level > 0:
                    # 相对导入
                    from_module = self.visitor.get_absolute_module_name(
                        module_name, symbol.scope.module_path, level
                    )
                else:
                    from_module = module_name
                    
                # 尝试找到模块路径
                module_path = self.visitor.resolve_module_path(from_module)
                if not module_path:
                    continue
                    
                # 查找具体的导入项
                for alias in node.names:
                    if alias.asname == symbol.name or (not alias.asname and alias.name == symbol.name):
                        # 找到对应的符号
                        target_qname = f"{self.visitor.get_module_qname(module_path)}.{alias.name}"
                        if target_qname in self.visitor.all_symbols:
                            target_symbol = self.visitor.all_symbols[target_qname]
                            # 建立依赖关系
                            symbol.dependencies.add(target_symbol)
        
    def analyze_entry_script(self, script_path: Path) -> Tuple[Set[Symbol], List[ast.AST]]:
        """
        分析入口脚本，返回初始符号集和主代码。
        [修正] 依赖 visitor 的单次遍历结果，而不是进行二次的无上下文分析。
        """
        # 1. 执行唯一且完整的分析过程，此过程会填充 visitor 的所有状态
        self.visitor.analyze_module(script_path)
        self.entry_module_qname = self.visitor.get_module_qname(script_path)  # 记录入口模块名
        
        # 修复 import_alias 的依赖关系
        self._fix_import_alias_dependencies()

        initial_symbols = set()
        main_code = []

        # 2. 从已经分析完成的 visitor 中获取入口模块的信息
        module_qname = self.visitor.get_module_qname(script_path)
        if module_qname not in self.visitor.all_symbols:
            return initial_symbols, main_code

        module_symbol = self.visitor.all_symbols[module_qname]
        module_scope = module_symbol.scope

        # 3. 获取主代码（即模块的初始化语句，包括 __main__ 块）
        main_code = module_symbol.init_statements

        # 4. 在正确的模块作用域下，分析主代码中使用的依赖项
        for node in main_code:
            # 关键修复：调用 analyze_dependencies 时，传入正确的父作用域 (parent_scope)
            deps = self.visitor.analyze_dependencies(node, parent_scope=module_scope)
            initial_symbols.update(deps)

        # 5. 收集在入口脚本中定义的所有符号（包括导入别名、函数、类等）
        for symbol in module_scope.symbols.values():
            if symbol.symbol_type in ('import_alias', 'function', 'class', 'variable'):
                initial_symbols.add(symbol)
            
        return initial_symbols, main_code
        
    def _index_class_children(self):
        """解决 #4: 建立类-方法索引以避免 O(N²) 复杂度"""
        self.class_children = defaultdict(list)
        for sym in self.visitor.all_symbols.values():
            if sym.symbol_type == 'function' and '.' in sym.qname:
                # 找到父类的 qname
                class_qname = sym.qname.rsplit('.', 1)[0]
                self.class_children[class_qname].append(sym)
    
    def _collect_runtime_import_dependencies(self, needed_symbols: Set[Symbol]) -> Set[Symbol]:
        """收集实际使用的运行时导入依赖（按需）
        
        使用更精确的 used_symbols 集合来判断函数是否依赖运行时导入
        """
        runtime_deps = set()
        
        # 步骤3优化：构建运行时别名索引以提高查找性能
        runtime_alias_index = {}  # name -> Symbol 的映射
        for symbol in self.visitor.all_symbols.values():
            if symbol.is_runtime_import and symbol.symbol_type == 'import_alias':
                runtime_alias_index[symbol.name] = symbol
        
        # 如果没有运行时导入，直接返回
        if not runtime_alias_index:
            return runtime_deps
        
        # 检查每个需要的符号是否使用了运行时导入
        for symbol in needed_symbols:
            # 检查符号的直接依赖
            for dep in symbol.dependencies:
                if dep.is_runtime_import:
                    runtime_deps.add(dep)
            
            # 步骤2改进：对于函数和类，使用 used_symbols 集合判断
            if symbol.symbol_type in ('function', 'class') and symbol.scope:
                # 检查该符号作用域中使用的所有名称
                for used_name in symbol.scope.used_symbols:
                    # O(1) 查找而不是 O(N) 遍历
                    if used_name in runtime_alias_index:
                        runtime_deps.add(runtime_alias_index[used_name])
        
        if not runtime_deps:
            return runtime_deps
        
        # 收集完整的 try...except ImportError 块
        for module_symbol in self.visitor.all_symbols.values():
            if module_symbol.symbol_type == 'module' and module_symbol.init_statements:
                for stmt in module_symbol.init_statements:
                    if isinstance(stmt, ast.Try) and self.visitor._is_try_import_error(stmt):
                        # 收集 try 块中的导入
                        for try_stmt in stmt.body:
                            if isinstance(try_stmt, ast.Import):
                                # 处理 import orjson as json 形式
                                for alias in try_stmt.names:
                                    # 计算实际的别名
                                    actual_alias = alias.asname or alias.name.split('.')[0]
                                    # 使用索引进行 O(1) 查找
                                    if actual_alias in runtime_alias_index:
                                        sym = runtime_alias_index[actual_alias]
                                        # 验证符号来自同一模块
                                        if sym.scope.module_path == module_symbol.scope.module_path:
                                            runtime_deps.add(sym)
                            elif isinstance(try_stmt, ast.ImportFrom):
                                # 获取导入的符号
                                module_name = try_stmt.module or ''
                                level = try_stmt.level or 0
                                
                                # 解析模块路径
                                if level > 0:
                                    module_path = self.visitor.resolve_relative_import(level, module_name, module_symbol.scope.module_path)
                                else:
                                    module_path = self.visitor.resolve_module_path(module_name)
                                
                                if module_path:
                                    module_qname = self.visitor.get_module_qname(module_path)
                                    # 添加被导入的特定符号
                                    for alias in try_stmt.names:
                                        symbol_qname = f"{module_qname}.{alias.name}"
                                        if symbol_qname in self.visitor.all_symbols:
                                            runtime_deps.add(self.visitor.all_symbols[symbol_qname])
                        
                        # 同样处理 except 块
                        for handler in stmt.handlers:
                            for except_stmt in handler.body:
                                if isinstance(except_stmt, ast.Import):
                                    # 处理 import json 形式
                                    for alias in except_stmt.names:
                                        # 计算实际的别名
                                        actual_alias = alias.asname or alias.name.split('.')[0]
                                        # 使用索引进行 O(1) 查找
                                        if actual_alias in runtime_alias_index:
                                            sym = runtime_alias_index[actual_alias]
                                            # 验证符号来自同一模块
                                            if sym.scope.module_path == module_symbol.scope.module_path:
                                                runtime_deps.add(sym)
                                elif isinstance(except_stmt, ast.ImportFrom):
                                    module_name = except_stmt.module or ''
                                    level = except_stmt.level or 0
                                    
                                    if level > 0:
                                        module_path = self.visitor.resolve_relative_import(level, module_name, module_symbol.scope.module_path)
                                    else:
                                        module_path = self.visitor.resolve_module_path(module_name)
                                    
                                    if module_path:
                                        module_qname = self.visitor.get_module_qname(module_path)
                                        for alias in except_stmt.names:
                                            symbol_qname = f"{module_qname}.{alias.name}"
                                            if symbol_qname in self.visitor.all_symbols:
                                                runtime_deps.add(self.visitor.all_symbols[symbol_qname])
        
        return runtime_deps
    
    def collect_all_dependencies(self, initial_symbols: Set[Symbol]) -> Set[Symbol]:
        """递归收集所有依赖（两阶段解析）"""
        # 首先建立类-方法索引
        self._index_class_children()
        
        # 阶段一：常规依赖收集（不包括运行时导入的内部）
        needed = set()
        to_process = deque(initial_symbols)
        
        while to_process:
            symbol = to_process.popleft()
            if symbol in needed:
                continue
                
            needed.add(symbol)
            
            # 添加符号的所有依赖
            for dep in symbol.dependencies:
                if dep not in needed:
                    to_process.append(dep)
                    
            # 如果是导入别名，添加目标符号
            if symbol.symbol_type == 'import_alias' and symbol.dependencies:
                for dep in symbol.dependencies:
                    if dep not in needed:
                        to_process.append(dep)
                        
            # 如果是类，使用 O(1) 索引收集方法依赖
            if symbol.symbol_type == 'class':
                # 从索引中获取该类的所有方法
                for method_sym in self.class_children.get(symbol.qname, []):
                    # 添加方法的所有依赖
                    for method_dep in method_sym.dependencies:
                        if method_dep not in needed and method_dep != symbol:
                            to_process.append(method_dep)
        
        # 阶段二：收集实际使用的运行时导入依赖
        runtime_deps = self._collect_runtime_import_dependencies(needed)
        if runtime_deps:
            # 将运行时依赖加入处理队列，继续常规依赖分析
            to_process.extend(runtime_deps)
            while to_process:
                symbol = to_process.popleft()
                if symbol in needed:
                    continue
                    
                needed.add(symbol)
                
                # 添加符号的所有依赖
                for dep in symbol.dependencies:
                    if dep not in needed:
                        to_process.append(dep)
                        
                # 如果是导入别名，添加目标符号
                if symbol.symbol_type == 'import_alias' and symbol.dependencies:
                    for dep in symbol.dependencies:
                        if dep not in needed:
                            to_process.append(dep)
            
                # 如果是类，使用 O(1) 索引收集方法依赖
                if symbol.symbol_type == 'class':
                    # 从索引中获取该类的所有方法
                    for method_sym in self.class_children.get(symbol.qname, []):
                        # 添加方法的所有依赖
                        for method_dep in method_sym.dependencies:
                            if method_dep not in needed and method_dep != symbol:
                                to_process.append(method_dep)
                        
        return needed
        
    def topological_sort(self, symbols: Set[Symbol]) -> List[Symbol]:
        """拓扑排序"""
        # 构建依赖图
        graph = defaultdict(set)
        in_degree = defaultdict(int)
        
        for symbol in symbols:
            in_degree[symbol] = 0
        
        # 解析传递依赖：如果符号依赖一个import_alias，需要找到该import_alias的实际目标
        def resolve_transitive_deps(symbol: Symbol) -> Set[Symbol]:
            """解析符号的传递依赖，展开import_alias"""
            resolved_deps = set()
            for dep in symbol.dependencies:
                if dep.symbol_type == 'import_alias' and dep.dependencies:
                    # 如果依赖是import_alias，找到它指向的实际符号
                    for target in dep.dependencies:
                        if target.symbol_type in ('function', 'class', 'variable'):
                            resolved_deps.add(target)
                        elif target.symbol_type == 'import_alias':
                            # 递归处理import_alias链
                            resolved_deps.update(resolve_transitive_deps(target))
                else:
                    resolved_deps.add(dep)
            return resolved_deps
            
        for symbol in symbols:
            # 获取解析后的依赖
            resolved_deps = resolve_transitive_deps(symbol)
            
            for dep in resolved_deps:
                if dep in symbols and dep != symbol:  # 忽略自引用
                    graph[dep].add(symbol)
                    in_degree[symbol] += 1
                    
        # B4 修复：添加类-方法的拓扑边，确保类先于其方法输出
        for symbol in symbols:
            if symbol.symbol_type == 'class':
                # 从索引中获取该类的所有方法
                for method_sym in self.class_children.get(symbol.qname, []):
                    if method_sym in symbols:
                        # 添加边：类 -> 方法（类必须在方法之前）
                        graph[symbol].add(method_sym)
                        in_degree[method_sym] += 1
                    
        # 拓扑排序
        queue = deque([s for s in symbols if in_degree[s] == 0])
        sorted_symbols = []
        
        while queue:
            current = queue.popleft()
            sorted_symbols.append(current)
            
            for dependent in graph[current]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
                    
        # 检查循环依赖
        if len(sorted_symbols) != len(symbols):
            remaining = symbols - set(sorted_symbols)
            # 找出循环依赖的详细路径
            cycles = self._find_cycles_in_graph(graph, remaining)
            error_msg = "Circular dependency detected:\n"
            if cycles:
                for i, cycle in enumerate(cycles, 1):
                    cycle_str = " -> ".join(s.qname for s in cycle)
                    error_msg += f"  Cycle {i}: {cycle_str}\n"
            else:
                # 如果找不到明确的循环，列出所有剩余符号
                error_msg += f"  Involved symbols: {', '.join(s.qname for s in remaining)}\n"
                
            # 添加更详细的调试信息
            error_msg += "\nDetailed dependency information:\n"
            for sym in sorted(remaining, key=lambda s: s.qname):  # 显示所有剩余符号
                # 显示所有依赖，不只是在remaining中的
                all_deps = [d.qname for d in sym.dependencies]
                deps_in_remaining = [d.qname for d in sym.dependencies if d in remaining]
                deps_in_output = [d.qname for d in sym.dependencies if d in symbols and d not in remaining]
                
                if all_deps:
                    error_msg += f"  {sym.qname}:\n"
                    error_msg += f"    All dependencies: {', '.join(all_deps)}\n"
                    if deps_in_remaining:
                        error_msg += f"    Dependencies in cycle: {', '.join(deps_in_remaining)}\n"
                    if deps_in_output:
                        error_msg += f"    Dependencies already processed: {', '.join(deps_in_output)}\n"
            
            raise CircularDependencyError(error_msg)
            
        return sorted_symbols
        
    def _find_cycles_in_graph(self, graph: Dict[Symbol, Set[Symbol]], candidates: Set[Symbol]) -> List[List[Symbol]]:
        """在图中查找循环依赖的路径
        
        使用DFS算法查找所有循环路径
        """
        cycles = []
        
        # 构建反向图（用于查找谁依赖于某个符号）
        reverse_graph = defaultdict(set)
        for node, deps in graph.items():
            for dep in deps:
                reverse_graph[dep].add(node)
        
        # Tarjan算法查找强连通分量
        index_counter = [0]
        stack = []
        lowlinks = {}
        index = {}
        on_stack = defaultdict(bool)
        
        def strongconnect(node: Symbol):
            """Tarjan算法的核心函数"""
            index[node] = index_counter[0]
            lowlinks[node] = index_counter[0]
            index_counter[0] += 1
            stack.append(node)
            on_stack[node] = True
            
            # 考虑后继节点
            for successor in graph.get(node, []):
                if successor in candidates:
                    if successor not in index:
                        strongconnect(successor)
                        lowlinks[node] = min(lowlinks[node], lowlinks[successor])
                    elif on_stack[successor]:
                        lowlinks[node] = min(lowlinks[node], index[successor])
            
            # 如果node是强连通分量的根
            if lowlinks[node] == index[node]:
                component = []
                while True:
                    w = stack.pop()
                    on_stack[w] = False
                    component.append(w)
                    if w == node:
                        break
                # 只添加包含多个节点的强连通分量（即循环）
                if len(component) > 1:
                    component.reverse()  # 恢复正确的顺序
                    cycles.append(component)
        
        # 对每个候选节点运行Tarjan算法
        for symbol in candidates:
            if symbol not in index:
                strongconnect(symbol)
                
        return cycles
        
    def _ast_equal(self, node1: ast.AST, node2: ast.AST) -> bool:
        """检查两个 AST 节点是否相等"""
        return ast.dump(node1) == ast.dump(node2)
    
    def _needs_reinject(self, symbol: Symbol, output_symbols: Set[Symbol], visited: Set[Symbol] = None) -> bool:
        """递归检查符号是否需要重新注入
        
        通过递归向上回溯别名链，检查是否有任何依赖不在输出符号集合中
        """
        if visited is None:
            visited = set()
            
        if symbol in visited:
            return False
        visited.add(symbol)
        
        # 如果符号本身不在输出集合中，需要重新注入
        if symbol not in output_symbols and symbol.symbol_type in ('function', 'class', 'variable'):
            return True
            
        # 递归检查所有依赖
        if symbol.dependencies:
            for dep in symbol.dependencies:
                if self._needs_reinject(dep, output_symbols, visited):
                    return True
                    
        return False
    
    def _collect_and_reinject_imports(self, output_symbols: Set[Symbol]) -> List[str]:
        """收集并重新注入必要的导入别名
        
        Issue #37 修复：避免重复注入已经在 external_imports 中的导入
        
        返回需要添加的导入语句列表
        """
        imports_to_reinject = []
        import_set = set()  # 用于去重
        processed_symbols = set()  # 跟踪已处理的符号
        
        # Issue #37 修复：记录已经处理过的外部导入模块
        external_modules = set()
        for imp in self.visitor.external_imports:
            if imp.startswith('import '):
                parts = imp.split()
                module = parts[1]
                external_modules.add(module)
            elif imp.startswith('from '):
                parts = imp.split()
                module = parts[1]
                external_modules.add(module)
        
        # 收集所有相关模块中的导入别名
        # 不仅仅是 needed_symbols，还包括所有被访问过的模块中的导入
        all_import_aliases = []
        
        # 1. 从 needed_symbols 中收集
        for symbol in self.needed_symbols:
            if symbol.symbol_type == 'import_alias':
                all_import_aliases.append(symbol)
                
        # 2. 从所有被分析的模块中收集导入别名
        # 这样可以捕获那些在类内部使用但没有被正确追踪的导入
        for module_path in self.visitor.module_symbols:
            module_qname = self.visitor.get_module_qname(module_path)
            # 查找该模块中的所有导入别名
            for qname, symbol in self.visitor.all_symbols.items():
                if (symbol.symbol_type == 'import_alias' and 
                    qname.startswith(module_qname + '.') and
                    symbol not in all_import_aliases):
                    # 只添加那些属于已处理模块的导入别名
                    if any(s.scope and s.scope.module_path == module_path for s in self.needed_symbols):
                        all_import_aliases.append(symbol)
        
        # 遍历所有收集到的导入别名
        for symbol in all_import_aliases:
            if symbol.qname in processed_symbols:
                continue
            processed_symbols.add(symbol.qname)
            
            # 对于 import_alias，我们需要检查它依赖的符号是否被内联
            # 如果依赖的符号没有被内联，就需要重新注入导入语句
            
            # 检查符号是否需要重新注入
            should_reinject = False
            
            # 1. 如果符号在 name_mappings 中且被重命名了，可能需要重新注入
            if symbol.qname in self.name_mappings and self.name_mappings[symbol.qname] != symbol.name:
                # 如果是外部导入的别名被重命名了（如 json -> json__module），需要重新注入
                if not symbol.dependencies or (symbol.dependencies and 
                                              all(d.symbol_type == 'module' for d in symbol.dependencies)):
                    should_reinject = True
            
            # 2. 递归检查依赖链，看是否有未被内联的符号
            if not should_reinject and symbol.dependencies:
                # 使用递归方法检查整个依赖链
                for dep in symbol.dependencies:
                    if self._needs_reinject(dep, output_symbols):
                        should_reinject = True
                        break
            
            if not should_reinject:
                continue
            
            # 获取导入节点信息
            node = symbol.def_node
            
            if isinstance(node, ast.Import):
                # 处理 import xxx as yyy 格式
                for alias in node.names:
                    module_name = alias.name
                    alias_name = alias.asname if alias.asname else alias.name
                    
                    # Issue #37 修复：跳过已经在 external_imports 中的模块
                    if module_name in external_modules:
                        continue
                    
                    # 检查当前别名对应的符号
                    if symbol.name != alias_name:
                        continue
                    
                    # 检查是否需要重命名
                    new_name = None
                    if symbol.qname in self.name_mappings:
                        new_name = self.name_mappings[symbol.qname]
                    else:
                        # 也检查带类型后缀的版本
                        type_qname = f"{symbol.qname}#import_alias"
                        if type_qname in self.name_mappings:
                            new_name = self.name_mappings[type_qname]
                    
                    # 生成导入语句
                    if new_name and new_name != alias_name:
                        import_stmt = f"import {module_name} as {new_name}"
                    elif alias.asname:
                        import_stmt = f"import {module_name} as {alias_name}"
                    else:
                        import_stmt = f"import {module_name}"
                        
                    if import_stmt not in import_set:
                        import_set.add(import_stmt)
                        imports_to_reinject.append(import_stmt)
                        
            elif isinstance(node, ast.ImportFrom):
                # 处理 from xxx import yyy as zzz 格式
                module = node.module if node.module else ""
                level = node.level
                
                # 跳过相对导入
                if level > 0:
                    continue
                
                # Issue #37 修复：跳过已经在 external_imports 中的模块
                if module in external_modules:
                    continue
                    
                for alias in node.names:
                    name = alias.name
                    alias_name = alias.asname if alias.asname else alias.name
                    
                    # 检查当前别名对应的符号
                    if symbol.name != alias_name:
                        continue
                    
                    # 检查是否需要重命名
                    new_name = None
                    if symbol.qname in self.name_mappings:
                        new_name = self.name_mappings[symbol.qname]
                    else:
                        # 也检查带类型后缀的版本
                        type_qname = f"{symbol.qname}#import_alias"
                        if type_qname in self.name_mappings:
                            new_name = self.name_mappings[type_qname]
                    
                    # 生成导入语句
                    if new_name and new_name != alias_name:
                        import_stmt = f"from {module} import {name} as {new_name}"
                    elif alias.asname:
                        import_stmt = f"from {module} import {name} as {alias_name}"
                    else:
                        import_stmt = f"from {module} import {name}"
                        
                    if import_stmt not in import_set:
                        import_set.add(import_stmt)
                        imports_to_reinject.append(import_stmt)
        
        # 排序以保证输出的确定性
        return sorted(imports_to_reinject)
    
    def _is_dunder_main(self, node: ast.AST) -> bool:
        """检查是否是 if __name__ == '__main__' 块"""
        if isinstance(node, ast.If):
            # 检查条件是否是 __name__ == '__main__'
            test = node.test
            if isinstance(test, ast.Compare):
                if (isinstance(test.left, ast.Name) and test.left.id == '__name__' and
                    len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq) and
                    len(test.comparators) == 1 and isinstance(test.comparators[0], ast.Constant) and
                    test.comparators[0].value == '__main__'):
                    return True
        return False
    
    def generate_name_mappings(self, symbols: Set[Symbol]):
        """生成名称映射"""
        # 统计名称冲突（包括导入别名）
        name_counts = defaultdict(int)
        name_to_symbols = defaultdict(list)  # name -> list of symbols
        
        # 收集所有符号的名称，包括运行时导入
        all_symbols_to_consider = set(symbols)
        
        # 添加所有符号，包括那些有类型后缀的
        # 但是导入别名需要特殊处理
        for qname, symbol in self.visitor.all_symbols.items():
            # 对于带类型后缀的符号，提取原始符号
            if '#' not in qname:  # 只处理原始qname
                # 对于需要的导入别名，也要加入考虑
                if symbol in self.needed_symbols or symbol.symbol_type != 'import_alias':
                    all_symbols_to_consider.add(symbol)
            
        # 统计所有符号的名称
        for symbol in all_symbols_to_consider:
            name_counts[symbol.name] += 1
            name_to_symbols[symbol.name].append(symbol)
                
        # 生成映射
        for symbol in all_symbols_to_consider:
            # 对于 import_alias 符号，总是添加后缀（__mod 或 __rt）
            if symbol.symbol_type == 'import_alias':
                if symbol.is_runtime_import:
                    new_name = f"{symbol.name}__rt"
                else:
                    new_name = f"{symbol.name}__mod"
                self.name_mappings[symbol.qname] = new_name
            elif name_counts[symbol.name] > 1:
                # 对于其他符号，只在有冲突时重命名
                if symbol.scope and symbol.scope.module_path:
                    module_key = self.visitor.get_module_qname(symbol.scope.module_path)
                    module_key = module_key.replace('.', '_').replace('__init__', 'pkg')
                else:
                    # 如果没有 scope，使用符号的 qname 前缀
                    module_key = symbol.qname.rsplit('.', 1)[0] if '.' in symbol.qname else 'unknown'
                new_name = f"{module_key}_{symbol.name}"
                self.name_mappings[symbol.qname] = new_name
                
                # 同时为带类型后缀的版本添加映射
                type_qname = f"{symbol.qname}#{symbol.symbol_type}"
                if type_qname in self.visitor.all_symbols:
                    self.name_mappings[type_qname] = new_name
            else:
                # 无冲突的非导入符号，保持原名
                self.name_mappings[symbol.qname] = symbol.name
                
                # 同时为带类型后缀的版本添加映射
                type_qname = f"{symbol.qname}#{symbol.symbol_type}"
                if type_qname in self.visitor.all_symbols:
                    self.name_mappings[type_qname] = symbol.name
                    
        # Issue #37 修复：为外部导入的别名添加正确的映射
        # 检查 import_registry 中的映射，并更新 name_mappings
        module_alias_map = {}  # module -> alias 的映射
        for key in self.import_registry:
            if key[0] == 'import' and len(key) == 3:
                # ('import', 'json', 'json__mod')
                module = key[1]
                alias = key[2]
                module_alias_map[module] = alias
        
        # 更新所有 import_alias 符号的映射
        for qname, symbol in self.visitor.all_symbols.items():
            if symbol.symbol_type == 'import_alias' and symbol.dependencies:
                # 检查依赖的模块
                for dep in symbol.dependencies:
                    if dep.symbol_type == 'module' and dep.name in module_alias_map:
                        # 更新映射到新的别名
                        self.name_mappings[symbol.qname] = module_alias_map[dep.name]
                        # 同时更新带类型后缀的版本
                        type_qname = f"{symbol.qname}#{symbol.symbol_type}"
                        if type_qname in self.visitor.all_symbols:
                            self.name_mappings[type_qname] = module_alias_map[dep.name]
                
    def _write_symbol(self, symbol: Symbol, transformer: 'AdvancedNodeTransformer', result_lines: List[str]):
        """解决 #1: 写入符号时进行冲突检测"""
        # 获取目标名称
        target_name = self.name_mappings.get(symbol.qname, symbol.name)
        
        # 检查是否已经存在
        if target_name in self.written_names:
            # 获取节点并检查是否完全相同
            transformed = transformer.transform_symbol(symbol)
            if transformed is None:
                return
                
            # 检查是否是完全重复的定义
            # 简化处理：如果名称已存在，则重命名
            if symbol.scope and symbol.scope.module_path:
                module_qname = self.visitor.get_module_qname(symbol.scope.module_path)
                module_alias = module_qname.replace('.', '_')
            else:
                module_alias = 'unknown'
            new_name = f"{target_name}__from_{module_alias}"
            self.name_mappings[symbol.qname] = new_name
            target_name = new_name
            
            # 重新转换符号
            transformed = transformer.transform_symbol(symbol)
        else:
            # 转换符号
            transformed = transformer.transform_symbol(symbol)
            
        # 记录已写入的名称
        self.written_names.add(target_name)
        
        # 写入结果
        if transformed is not None:
            if symbol.scope and symbol.scope.module_path:
                rel_path = symbol.scope.module_path.relative_to(self.project_root)
                result_lines.append(f"# From {rel_path}")
            result_lines.append(ast.unparse(transformed))
            result_lines.append("")
    
    def _process_imports(self, imports: Set[str]) -> List[str]:
        """解决 #2: 处理导入去重和 alias 冲突
        
        修复：使用更精确的去重键，包含导入样式信息
        """
        result = []
        # 添加别名去重集合，避免相同的别名被多次定义
        seen_aliases = set()
        
        for imp in sorted(imports):
            # 解析导入语句
            new_alias = None  # 初始化变量
            
            if imp.startswith('from '):
                # from X import Y as Z 或 from X import Y
                parts = imp.split()
                if 'as' in parts:
                    # from X import Y as Z
                    as_idx = parts.index('as')
                    module = parts[1]
                    name = parts[3]
                    alias = parts[as_idx + 1]
                    # B2 修复：为别名添加 __mod 后缀
                    new_alias = f"{alias}__mod"
                    new_imp = f"from {module} import {name} as {new_alias}"
                    # Issue #37 修复：包含导入样式在去重键中
                    key = ('from', module, name, new_alias)
                else:
                    # from X import Y
                    module = parts[1]
                    name = parts[3]
                    # B2 修复：即使没有别名，也要添加 __mod 后缀
                    new_alias = f"{name}__mod"
                    new_imp = f"from {module} import {name} as {new_alias}"
                    # Issue #37 修复：包含导入样式在去重键中
                    key = ('from', module, name, new_alias)
            else:
                # import X as Y 或 import X
                parts = imp.split()
                if 'as' in parts:
                    # import X as Y
                    as_idx = parts.index('as')
                    module = parts[1]
                    alias = parts[as_idx + 1]
                    # B2 修复：为别名添加 __mod 后缀
                    new_alias = f"{alias}__mod"
                    new_imp = f"import {module} as {new_alias}"
                    # Issue #37 修复：包含导入样式在去重键中
                    key = ('import', module, new_alias)
                else:
                    # import X
                    module = parts[1]
                    # B2 修复：对于没有别名的导入，也添加别名以避免冲突
                    alias = module.split('.')[0]
                    new_alias = f"{alias}__mod"
                    new_imp = f"import {module} as {new_alias}"
                    # Issue #37 修复：包含导入样式在去重键中
                    key = ('import', module, new_alias)
            
            # 检查是否已存在（包括别名去重）
            if key not in self.import_registry and new_alias not in seen_aliases:
                seen_aliases.add(new_alias)
                self.import_registry.add(key)
                result.append(new_imp)
        
        return result
    

    def merge_script(self, script_path: Path) -> str:
        """合并脚本"""
        script_path = script_path.resolve()
        
        # 1. 分析入口脚本
        initial_symbols, main_code = self.analyze_entry_script(script_path)
        
        # 2. 收集所有依赖
        self.needed_symbols = self.collect_all_dependencies(initial_symbols)
        
        # 3. 过滤掉导入别名、嵌套定义和模块符号
        # 但是，如果嵌套定义被其他符号依赖，应该保留它
        output_symbols = set()
        for s in self.needed_symbols:
            if s.symbol_type in ('import_alias', 'module', 'parameter'):
                continue
                
            # Issue #37 修复：过滤掉入口模块中的变量定义
            # 这些变量会作为主代码的一部分输出，不需要单独输出
            if (s.symbol_type == 'variable' and 
                s.scope and s.scope.module_path == script_path):
                continue
                
            # 检查是否是类的方法（通过判断qname中是否包含类名）
            is_class_method = False
            if s.symbol_type == 'function' and '.' in s.qname:
                # 检查是否有对应的类符号
                parts = s.qname.rsplit('.', 1)
                if len(parts) == 2:
                    potential_class_qname = parts[0]
                    # 查找是否有对应的类
                    for other_s in self.needed_symbols:
                        if other_s.symbol_type == 'class' and other_s.qname == potential_class_qname:
                            is_class_method = True
                            break
                            
            if is_class_method:
                # 类的方法不需要单独输出，它们会随类一起输出
                continue
                
            if s.is_nested:
                # 检查是否有其他符号依赖这个嵌套符号
                # 暂时保留所有嵌套类，因为它们可能被属性访问使用
                if s.symbol_type == 'class':
                    output_symbols.add(s)
            else:
                output_symbols.add(s)
        
        # 4. 拓扑排序
        sorted_symbols = self.topological_sort(output_symbols)
        
        # Issue #37 修复：在生成名称映射之前，先处理外部导入
        # 这样import_registry会被填充，供generate_name_mappings使用
        processed_imports = []
        if self.visitor.external_imports:
            processed_imports = self._process_imports(self.visitor.external_imports)
        
        # 5. 生成名称映射
        self.generate_name_mappings(output_symbols)
        
        # B2 修复：为所有 import_alias 符号添加后缀映射
        # 这包括那些被过滤掉不输出的外部导入
        for symbol in self.visitor.all_symbols.values():
            if symbol.symbol_type == 'import_alias' and symbol.qname not in self.name_mappings:
                # 根据是否是运行时导入选择不同的后缀
                if symbol.is_runtime_import:
                    new_name = f"{symbol.name}__rt"
                else:
                    new_name = f"{symbol.name}__mod"
                self.name_mappings[symbol.qname] = new_name
        
        # 6. 生成代码
        transformer = AdvancedNodeTransformer(self.name_mappings, self.visitor, self.visitor.all_symbols)
        
        result_lines = []
        
        # __future__ 导入必须在最前面
        if self.visitor.future_imports:
            result_lines.extend(sorted(self.visitor.future_imports))
            result_lines.append("")
            
        # 外部导入（使用之前已经处理好的）
        if processed_imports:
            result_lines.extend(processed_imports)
            result_lines.append("")
            
        # 处理运行时导入（带 __rt 后缀）
        runtime_imports = []
        for symbol in self.visitor.all_symbols.values():
            if symbol.symbol_type == 'import_alias' and symbol.is_runtime_import:
                # 获取重命名后的名称
                new_name = self.name_mappings.get(symbol.qname, symbol.name)
                
                # 根据导入类型生成导入语句
                if isinstance(symbol.def_node, ast.Import):
                    # import xxx as yyy 形式
                    for alias in symbol.def_node.names:
                        if alias.asname == symbol.name or (not alias.asname and alias.name.split('.')[0] == symbol.name):
                            # 如果原本没有别名且新名称不同，或者有别名但需要改名
                            if new_name != alias.name.split('.')[0]:
                                runtime_imports.append(f"import {alias.name} as {new_name}")
                            else:
                                runtime_imports.append(f"import {alias.name}")
                            break
                elif isinstance(symbol.def_node, ast.ImportFrom):
                    # from xxx import yyy as zzz 形式
                    module = symbol.def_node.module or ''
                    for alias in symbol.def_node.names:
                        if alias.asname == symbol.name or (not alias.asname and alias.name == symbol.name):
                            runtime_imports.append(f"from {module} import {alias.name} as {new_name}")
                            break
                            
        if runtime_imports:
            result_lines.append("# Runtime imports (originally in try...except ImportError blocks)")
            result_lines.extend(sorted(set(runtime_imports)))
            result_lines.append("")
            
        # 收集并重新注入必要的导入别名
        reinjected_imports = self._collect_and_reinject_imports(output_symbols)
        if reinjected_imports:
            result_lines.append("# Re-injected import aliases for unresolved dependencies")
            result_lines.extend(reinjected_imports)
            result_lines.append("")
            
        # 合并的符号定义
        module_inits = {}  # 收集每个模块的初始化语句
        
        for symbol in sorted_symbols:
            # 使用新的写入方法（包含冲突检测）
            self._write_symbol(symbol, transformer, result_lines)
            
            # 收集模块初始化语句
            if symbol.scope and symbol.scope.module_path:
                module_qname = self.visitor.get_module_qname(symbol.scope.module_path)
            else:
                continue
                
            if module_qname in self.visitor.all_symbols:
                module_symbol = self.visitor.all_symbols[module_qname]
                # 不要收集入口模块的初始化语句，因为它们已经在 main_code 中处理了
                if (module_symbol.init_statements and 
                    module_qname not in module_inits and 
                    module_qname != self.entry_module_qname):
                    module_inits[module_qname] = module_symbol.init_statements
                    
        # 输出所有模块的初始化语句
        if module_inits:
            result_lines.append("# Module initialization statements")
            for module_qname, init_stmts in module_inits.items():
                # 解决 #3: 过滤非入口模块的 __main__ 块
                should_skip_main = (module_qname != self.entry_module_qname)
                
                result_lines.append(f"# From module: {module_qname}")
                
                # 设置正确的模块作用域
                module_symbol = self.visitor.all_symbols.get(module_qname)
                if module_symbol and module_symbol.scope and module_symbol.scope.module_path:
                    module_path = module_symbol.scope.module_path
                    if module_path in self.visitor.module_symbols:
                        module_scope = self.visitor.module_symbols[module_path].get('__scope__')
                        if module_scope:
                            transformer.current_scope_stack = [module_scope]
                
                for stmt in init_stmts:
                    # 跳过模块文档字符串
                    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                        continue
                    
                    # 解决 #3: 跳过非入口模块的 __main__ 块
                    if should_skip_main and self._is_dunder_main(stmt):
                        continue
                    
                    # Issue #37 修复：跳过已经作为符号输出的赋值语句
                    # 只跳过简单的变量赋值，保留其他语句
                    if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                        # 检查是否是简单的变量定义（没有函数调用等副作用）
                        skip = False
                        if isinstance(stmt, ast.Assign):
                            # 检查是否是简单赋值
                            if len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                                var_name = stmt.targets[0].id
                                # 检查这个变量是否已经被输出为符号
                                var_qname = f"{module_qname}.{var_name}"
                                if var_qname in self.name_mappings:
                                    # 检查赋值的值是否是常量
                                    if isinstance(stmt.value, (ast.Constant, ast.Name, ast.UnaryOp, ast.BinOp)):
                                        skip = True
                        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                            var_name = stmt.target.id
                            var_qname = f"{module_qname}.{var_name}"
                            if var_qname in self.name_mappings and stmt.value:
                                if isinstance(stmt.value, (ast.Constant, ast.Name, ast.UnaryOp, ast.BinOp)):
                                    skip = True
                        
                        if skip:
                            continue
                        
                    transformed_stmt = transformer.visit(copy.deepcopy(stmt))
                    result_lines.append(ast.unparse(transformed_stmt))
            result_lines.append("")
            
        # 主代码
        if main_code:
            result_lines.append("# Main script code")
            # 设置正确的作用域
            if script_path in self.visitor.module_symbols:
                module_scope = self.visitor.module_symbols[script_path].get('__scope__')
                if module_scope:
                    transformer.current_scope_stack = [module_scope]
            
            for node in main_code:
                # 深拷贝节点以避免修改原始 AST
                node_copy = copy.deepcopy(node)
                # 应用转换
                transformed = transformer.visit(node_copy)
                # 如果是 None，跳过
                if transformed is not None:
                    result_lines.append(ast.unparse(transformed))
                
        final_code = "\n".join(result_lines)

        if getattr(self, "enable_verify", False):
            print("\n--- 🚀 Running post-merge static audit with ASTAuditor ---")
            auditor = ASTAuditor()
            if not auditor.audit(final_code, "merged_script.py"):
                print("--- ⚠️  ASTAuditor found potential issues ---")
                report = auditor.get_report()  # 获取格式化好的报告
                print(report)
                print("-------------------------------------------\n")
            else:
                print("--- ✅ ASTAuditor audit passed successfully ---")

        return final_code


class AdvancedNodeTransformer(ast.NodeTransformer):
    """高级代码转换器"""
    
    def __init__(self, name_mappings: Dict[str, str], visitor: ContextAwareVisitor, 
                 all_symbols: Dict[str, Symbol]):
        self.name_mappings = name_mappings  # qname -> new_name
        self.visitor = visitor
        self.all_symbols = all_symbols
        self.current_scope_stack = []  # 当前的作用域栈
        self.defnode_to_scope = visitor.defnode_to_scope  # 直接使用 visitor 的映射
        
    def transform_symbol(self, symbol: Symbol) -> ast.AST:
        """转换符号定义"""
        node = copy.deepcopy(symbol.def_node)
        
        # 跳过模块文档字符串
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return None
            
        # 跳过参数节点（不应该作为独立符号）
        if isinstance(node, ast.arg):
            return None
            
        # 跳过单独的名称节点
        if isinstance(node, ast.Name):
            return None
            
        # 设置当前作用域栈
        if symbol.scope:
            self.current_scope_stack = [symbol.scope]
        else:
            # 如果没有 scope，使用默认的模块作用域
            self.current_scope_stack = []
        
        # 转换节点
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return self.transform_function(node, symbol)
        elif isinstance(node, ast.ClassDef):
            return self.transform_class(node, symbol)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            # 特殊处理 __all__
            if isinstance(node, ast.Assign) and symbol.export_list:
                return self.transform_all_assignment(node, symbol)
            return self.visit(node)
        else:
            # 其他类型的符号，跳过
            return None
            
    def get_current_module_path(self) -> Optional[Path]:
        """获取当前模块路径"""
        if self.current_scope_stack:
            return self.current_scope_stack[0].module_path
        return None
    
    def current_module_path(self) -> Optional[Path]:
        """获取当前模块路径 - 兼容原始代码"""
        return self.get_current_module_path()
        
    def resolve_name_to_symbol(self, name: str) -> Optional[Symbol]:
        """解析名称到符号对象"""
        # 检查当前作用域栈
        if self.current_scope_stack:
            # 从当前作用域开始向上查找
            for scope in reversed(self.current_scope_stack):
                if name in scope.symbols:
                    symbol = scope.symbols[name]
                    # 如果是符号对象，返回它
                    if isinstance(symbol, Symbol):
                        return symbol
                    # 如果是字符串（qname），查找对应的符号
                    elif isinstance(symbol, str) and symbol in self.all_symbols:
                        return self.all_symbols[symbol]
        
        # 如果作用域栈中没有找到，尝试从模块路径查找
        current_module = self.get_current_module_path()
        if current_module:
            # 查找模块级符号
            module_qname = self.visitor.get_module_qname(current_module)
            
            # 1. 检查是否是模块内定义的符号
            test_qname = f"{module_qname}.{name}"
            if test_qname in self.all_symbols:
                return self.all_symbols[test_qname]
                
            # 2. 检查是否是导入的别名
            if current_module in self.visitor.module_symbols:
                module_syms = self.visitor.module_symbols[current_module]
                if name in module_syms and isinstance(module_syms[name], Symbol):
                    return module_syms[name]
                    
        return None
        
    def find_symbol_qname(self, name: str) -> Optional[str]:
        """查找符号的限定名 - 保留用于向后兼容"""
        symbol = self.resolve_name_to_symbol(name)
        if symbol:
            if symbol.symbol_type == 'import_alias' and symbol.dependencies:
                # 返回导入指向的真实符号的qname
                for dep in symbol.dependencies:
                    # 检查依赖的符号是否有映射的新名称
                    if dep.qname in self.name_mappings:
                        return dep.qname  # 返回原始 qname，让调用者处理映射
                    return dep.qname
            return symbol.qname
        return None
        
    def transform_all_assignment(self, node: ast.Assign, symbol: Symbol) -> ast.AST:
        """转换 __all__ 赋值，更新导出列表中的名称"""
        # 深拷贝节点
        new_node = copy.deepcopy(node)
        
        # 如果值是列表或元组，更新其中的字符串
        if isinstance(new_node.value, (ast.List, ast.Tuple)):
            new_elts = []
            for elt in new_node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    old_name = elt.value
                    # 查找这个名称对应的符号
                    for sym in self.all_symbols.values():
                        if sym.name == old_name and sym.scope.module_path == self.current_module_path():
                            if sym.qname in self.name_mappings:
                                # 使用新名称
                                new_elt = ast.Constant(value=self.name_mappings[sym.qname])
                                new_elts.append(new_elt)
                                break
                    else:
                        # 保持原名称
                        new_elts.append(elt)
                else:
                    new_elts.append(elt)
            new_node.value.elts = new_elts
            
        return new_node
        
    def transform_function(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef], 
                         symbol: Symbol) -> ast.AST:
        """转换函数定义"""
        # 重命名函数
        if symbol.qname in self.name_mappings:
            node.name = self.name_mappings[symbol.qname]
            
        # 转换装饰器
        new_decorators = []
        for decorator in node.decorator_list:
            new_decorators.append(self.visit(decorator))
        node.decorator_list = new_decorators
        
        # 为函数体创建新的作用域
        # 优先使用哈希映射查找函数对应的作用域
        func_scope = None
        
        # 首先尝试从 defnode_to_scope 映射中获取
        if node in self.defnode_to_scope:
            func_scope = self.defnode_to_scope[node]
        else:
            # 如果映射中没有，则回退到旧的查找逻辑（保证兼容性）
            for sym_qname, sym in self.all_symbols.items():
                if sym.def_node == symbol.def_node and sym.symbol_type == 'function':
                    # 找到函数符号后，查找其对应的作用域
                    for scope_sym in self.all_symbols.values():
                        if scope_sym.scope.node == node:
                            func_scope = scope_sym.scope
                            break
                    break
                    
        if not func_scope:
            # 创建临时作用域
            func_scope = Scope(
                scope_type='function',
                node=node,
                module_path=self.current_scope_stack[0].module_path if self.current_scope_stack else None
            )
            
        # 推入函数作用域
        self.current_scope_stack.append(func_scope)
        
        # 转换函数体
        node.body = [self.visit(stmt) for stmt in node.body]
        
        # 弹出函数作用域
        self.current_scope_stack.pop()
        
        return node
        
    def transform_class(self, node: ast.ClassDef, symbol: Symbol) -> ast.AST:
        """转换类定义"""
        # 重命名类
        if symbol.qname in self.name_mappings:
            node.name = self.name_mappings[symbol.qname]
            
        # 转换装饰器
        new_decorators = []
        for decorator in node.decorator_list:
            new_decorators.append(self.visit(decorator))
        node.decorator_list = new_decorators
        
        # 转换基类
        node.bases = [self.visit(base) for base in node.bases]
        
        # 转换类体
        node.body = [self.visit(stmt) for stmt in node.body]
        
        return node
        
    def visit_Name(self, node: ast.Name):
        """转换名称引用"""
        if isinstance(node.ctx, ast.Load):
            symbol = self.resolve_name_to_symbol(node.id)
            
            if symbol:
                # 如果是导入别名，检查它的依赖是否已经被内联
                if symbol.symbol_type == 'import_alias' and symbol.dependencies:
                    # 获取依赖的符号
                    dep = next(iter(symbol.dependencies))
                    # 如果依赖有映射（说明被内联了），使用依赖的映射名称
                    if dep.qname in self.name_mappings:
                        node.id = self.name_mappings[dep.qname]
                        return node
                
                # 首先检查是否有类型后缀的映射
                type_qname = f"{symbol.qname}#{symbol.symbol_type}"
                if type_qname in self.name_mappings:
                    node.id = self.name_mappings[type_qname]
                elif symbol.qname in self.name_mappings:
                    node.id = self.name_mappings[symbol.qname]
                    
                # 如果是运行时导入，立即返回
                if symbol.is_runtime_import:
                    return node
                    
        return node
        
    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        """转换属性访问，支持嵌套属性链"""
        # 递归解析属性链，例如 a.b.c.d
        # 首先收集整个属性链
        attrs = []
        current = node
        
        # 从右到左收集属性名
        while isinstance(current, ast.Attribute):
            attrs.append(current.attr)
            current = current.value
            
        # 如果最左侧不是简单的名称，则保持原样
        if not isinstance(current, ast.Name):
            return self.generic_visit(node)
            
        # attrs 现在是反序的，例如 ['d', 'c', 'b']，需要反转
        attrs.reverse()
        
        # 获取根名称
        base_name = current.id
        
        # 对于属性访问，优先查找导入符号
        base_symbol = None
        
        # 首先尝试查找导入别名符号
        current_module = self.get_current_module_path()
        if current_module:
            module_qname = self.visitor.get_module_qname(current_module)
            
            # 查找所有可能的符号
            possible_symbols = []
            
            # 1. 查找模块级的导入别名
            import_qname = f"{module_qname}.{base_name}"
            if import_qname in self.all_symbols:
                sym = self.all_symbols[import_qname]
                if sym.symbol_type == 'import_alias':
                    possible_symbols.append(sym)
            
            # 2. 查找带类型后缀的版本
            import_type_qname = f"{import_qname}#import_alias"
            if import_type_qname in self.all_symbols:
                possible_symbols.append(self.all_symbols[import_type_qname])
            
            # 选择导入符号（如果有）
            for sym in possible_symbols:
                if sym.symbol_type == 'import_alias':
                    base_symbol = sym
                    break
        
        # 如果没找到导入符号，使用默认的解析方法
        if not base_symbol:
            base_symbol = self.resolve_name_to_symbol(base_name)
        
        if not base_symbol:
            # 基名无法解析，保持原样
            return self.generic_visit(node)
            
        # 对于模块导入，需要特殊处理
        # 例如 layers_yy.representation.Representation 应该变成 Representation
        if base_symbol.symbol_type == 'import_alias' and base_symbol.dependencies:
            # 获取完整的属性链名称
            full_attr_chain = [base_name] + attrs
            
            # 查找对应的符号
            # 对于 import layers_yy.representation，访问 layers_yy.representation.Representation
            # 需要查找 layers_yy.representation.Representation
            target_module = next(iter(base_symbol.dependencies))
            if target_module.symbol_type == 'module':
                # 构建要查找的完整限定名
                # 需要处理重复的模块路径部分
                target_parts = target_module.qname.split('.')
                remaining_parts = full_attr_chain[1:]  # 跳过别名部分
                
                # 去重处理
                while remaining_parts and target_parts and target_parts[-1] == remaining_parts[0]:
                    remaining_parts = remaining_parts[1:]
                
                if remaining_parts:
                    full_qname = target_module.qname + "." + ".".join(remaining_parts)
                else:
                    full_qname = target_module.qname
                
                # 查找这个符号是否有映射
                if full_qname in self.name_mappings:
                    # 直接替换为新名称
                    return ast.Name(id=self.name_mappings[full_qname], ctx=node.ctx)
                elif full_qname in self.all_symbols:
                    # 如果没有映射但符号存在，使用原始名称
                    symbol = self.all_symbols[full_qname]
                    if symbol.symbol_type in ('class', 'function'):
                        return ast.Name(id=symbol.name, ctx=node.ctx)
        
        # 其他情况的处理
        target_symbol = None
        
        if base_symbol.symbol_type == 'import_alias':
            # 如果是运行时导入，直接使用映射的名称
            if base_symbol.is_runtime_import:
                # 检查映射
                if base_symbol.qname in self.name_mappings:
                    current.id = self.name_mappings[base_symbol.qname]
                else:
                    # 也检查带类型后缀的版本
                    type_qname = f"{base_symbol.qname}#import_alias"
                    if type_qname in self.name_mappings:
                        current.id = self.name_mappings[type_qname]
                return self.generic_visit(node)
            
            # 如果导入别名本身在映射中（例如模块别名），使用映射后的名称
            if base_symbol.qname in self.name_mappings:
                current.id = self.name_mappings[base_symbol.qname]
                
            # 继续处理依赖
            if base_symbol.dependencies:
                target_symbol = next(iter(base_symbol.dependencies))
            else:
                return self.generic_visit(node)
        else:
            target_symbol = base_symbol
            
        if not target_symbol:
            return self.generic_visit(node)
            
        # 处理属性链
        # 如果基础符号在名称映射中，更新基础名称
        if target_symbol.qname in self.name_mappings:
            current.id = self.name_mappings[target_symbol.qname]
        
        # 对于类的嵌套属性（如 torch.nn），保持属性访问的结构
        # 不尝试解析为单独的符号，因为嵌套类通常应该保持为属性访问
        return self.generic_visit(node)
        
    def visit_Global(self, node: ast.Global):
        """转换global声明"""
        # Global声明的名称通常不需要转换，因为它们引用的是模块级名称
        # 但我们仍然需要检查是否有映射
        new_names = []
        current_module = self.get_current_module_path()
        if current_module:
            for name in node.names:
                # 查找模块级符号
                module_qname = self.visitor.get_module_qname(current_module)
                symbol_qname = f"{module_qname}.{name}"
                if symbol_qname in self.name_mappings:
                    new_names.append(self.name_mappings[symbol_qname])
                else:
                    new_names.append(name)
        else:
            new_names = node.names
        node.names = new_names
        return node
        
    def visit_Nonlocal(self, node: ast.Nonlocal):
        """转换nonlocal声明"""
        # Nonlocal声明需要特殊处理
        return node
        
    def visit_Assign(self, node: ast.Assign):
        """转换赋值语句"""
        # 转换赋值语句的右侧表达式
        node.value = self.visit(node.value)
        
        # 转换所有的目标
        new_targets = []
        for target in node.targets:
            if isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store):
                # 查找这个变量名对应的符号
                symbol = self.resolve_name_to_symbol(target.id)
                if symbol and symbol.symbol_type == 'variable' and symbol.qname in self.name_mappings:
                    # 使用映射的新名称
                    new_target = ast.Name(id=self.name_mappings[symbol.qname], ctx=ast.Store())
                    new_targets.append(new_target)
                else:
                    new_targets.append(self.visit(target))
            else:
                new_targets.append(self.visit(target))
        
        node.targets = new_targets
        return node
        
    def visit_Constant(self, node: ast.Constant):
        """处理字符串常量中的类型注解"""
        # 暂时不处理字符串类型注解
        return node
        
    def visit_Import(self, node: ast.Import):
        """处理 import 语句，确保别名正确重命名"""
        # 深拷贝节点以避免修改原始节点
        new_node = copy.deepcopy(node)
        
        for alias in new_node.names:
            # 计算实际的别名
            actual_alias = alias.asname if alias.asname else alias.name.split('.')[0]
            
            # 查找是否需要重命名
            # 首先查找对应的符号
            symbol = self.resolve_name_to_symbol(actual_alias)
            if symbol and symbol.qname in self.name_mappings:
                # 需要重命名
                new_name = self.name_mappings[symbol.qname]
                alias.asname = new_name
            else:
                # B2 修复：如果没有找到符号或映射，为导入添加 __mod 后缀
                # 这处理了外部导入和 try...except ImportError 块中的导入
                new_name = f"{actual_alias}__mod"
                alias.asname = new_name
        
        return new_node
    
    def visit_ImportFrom(self, node: ast.ImportFrom):
        """处理 from ... import ... 语句，确保别名正确重命名"""
        # 如果是相对导入，保持原样
        if node.level > 0:
            return node
            
        for alias in node.names:
            # 计算实际的别名
            actual_alias = alias.asname if alias.asname else alias.name
            
            # 查找是否需要重命名
            symbol = self.resolve_name_to_symbol(actual_alias)
            if symbol and symbol.qname in self.name_mappings:
                # 需要重命名
                new_name = self.name_mappings[symbol.qname]
                if alias.asname:
                    # 如果原来有别名，更新别名
                    alias.asname = new_name
                else:
                    # 如果原来没有别名，添加别名
                    alias.asname = new_name
        
        return node
    
    def visit_Try(self, node: ast.Try):
        """处理 try...except 语句
        
        对于 AdvancedNodeTransformer，我们需要正确处理内部的作用域
        """
        # 转换 try 块中的所有语句
        node.body = [self.visit(stmt) for stmt in node.body]
        
        # 转换所有的 except 处理器
        for handler in node.handlers:
            if handler.type:
                handler.type = self.visit(handler.type)
            handler.body = [self.visit(stmt) for stmt in handler.body]
        
        # 转换 else 块（如果存在）
        if node.orelse:
            node.orelse = [self.visit(stmt) for stmt in node.orelse]
        
        # 转换 finally 块（如果存在）
        if node.finalbody:
            node.finalbody = [self.visit(stmt) for stmt in node.finalbody]
        
        return node


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="高级Python代码合并工具")
    parser.add_argument('script_path', type=Path, help='入口脚本路径')
    parser.add_argument('project_root', type=Path, help='项目根目录')
    
    # 使用互斥组来处理 verify 选项
    verify_group = parser.add_mutually_exclusive_group()
    verify_group.add_argument('--verify', action='store_true', help='启用静态检查')
    verify_group.add_argument('--no-verify', action='store_false', dest='verify', help='禁用静态检查')
    parser.set_defaults(verify=True)  # 默认启用验证
    
    args = parser.parse_args()
    
    script_path = args.script_path
    project_root = args.project_root
    
    
    if not script_path.exists():
        print(f"Error: Script {script_path} not found")
        sys.exit(1)
        
    if not project_root.exists():
        print(f"Error: Project root {project_root} not found")
        sys.exit(1)
        
    try:
        merger = AdvancedCodeMerger(project_root)
        # 将命令行参数传递给实例
        merger.enable_verify = args.verify
        merged_code = merger.merge_script(script_path)
        
        # 输出到文件
        output_path = script_path.parent / f"{script_path.stem}_advanced_merged.py"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(merged_code)
            
        print(f"Merged code written to: {output_path}")
        
    except KeyboardInterrupt:
        print("\n操作已被用户中断 (Ctrl+C)。")
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()