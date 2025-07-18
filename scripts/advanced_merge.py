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
            
        self.analyzed_modules.add(module_path)
        self.current_module_path = module_path
        
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
        
        for stmt in node.body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                # 处理导入
                self.visit(stmt)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, 
                                 ast.ClassDef, ast.Assign, ast.AnnAssign)):
                # 定义语句
                self.visit(stmt)
            else:
                # 其他顶层语句（副作用初始化）
                init_statements.append(stmt)
                
        # 存储初始化语句
        if init_statements:
            module_symbol.init_statements = init_statements
            
    def visit_Import(self, node: ast.Import):
        """处理 import 语句"""
        for alias in node.names:
            module_name = alias.name
            alias_name = alias.asname or module_name.split('.')[-1]
            
            if self.is_internal_module(module_name, self.current_module_path):
                # 内部模块
                module_path = self.resolve_module_path(module_name)
                if module_path:
                    # 递归分析
                    self.analyze_module(module_path)
                    
                    # 创建导入别名符号
                    symbol = Symbol(
                        name=alias_name,
                        qname=f"{self.get_module_qname(self.current_module_path)}.{alias_name}",
                        symbol_type='import_alias',
                        def_node=node,
                        scope=self.current_scope()
                    )
                    
                    self.current_scope().symbols[alias_name] = symbol
                    self.all_symbols[symbol.qname] = symbol
            else:
                # 外部导入
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
            self.analyze_module(module_path)
            
            for alias in node.names:
                symbol_name = alias.name
                alias_name = alias.asname or symbol_name
                
                # 创建导入别名符号
                symbol = Symbol(
                    name=alias_name,
                    qname=f"{self.get_module_qname(self.current_module_path)}.{alias_name}",
                    symbol_type='import_alias', 
                    def_node=node,
                    scope=self.current_scope()
                )
                
                # 找到被导入的原始符号
                target_qname = f"{self.get_module_qname(module_path)}.{symbol_name}"
                if target_qname in self.all_symbols:
                    symbol.dependencies.add(self.all_symbols[target_qname])
                    
                self.current_scope().symbols[alias_name] = symbol
                self.all_symbols[symbol.qname] = symbol
                self.module_symbols[self.current_module_path][alias_name] = symbol
        else:
            # 外部导入
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
        self.current_scope().symbols[node.name] = symbol
        self.all_symbols[qname] = symbol
        
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
        
        # 创建类作用域
        class_scope = Scope(
            scope_type='class',
            node=node,
            module_path=self.current_module_path
        )
        self.push_scope(class_scope)
        
        # 分析类体
        for stmt in node.body:
            self.visit(stmt)
            
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
                    if symbol and symbol.symbol_type not in ('parameter', 'loop_var', 'local_var'):
                        self.deps.add(symbol)
                        
            def visit_Attribute(self, node):
                # 处理属性访问
                if isinstance(node.value, ast.Name):
                    symbol = self.outer.resolve_name(node.value.id)
                    if symbol and symbol.symbol_type not in ('parameter', 'loop_var', 'local_var'):
                        self.deps.add(symbol)
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
        
    def analyze_entry_script(self, script_path: Path) -> Tuple[Set[Symbol], List[ast.AST]]:
        """
        分析入口脚本，返回初始符号集和主代码。
        [修正] 依赖 visitor 的单次遍历结果，而不是进行二次的无上下文分析。
        """
        # 1. 执行唯一且完整的分析过程，此过程会填充 visitor 的所有状态
        self.visitor.analyze_module(script_path)

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
        
    def collect_all_dependencies(self, initial_symbols: Set[Symbol]) -> Set[Symbol]:
        """递归收集所有依赖"""
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
                        
        return needed
        
    def topological_sort(self, symbols: Set[Symbol]) -> List[Symbol]:
        """拓扑排序"""
        # 构建依赖图
        graph = defaultdict(set)
        in_degree = defaultdict(int)
        
        for symbol in symbols:
            in_degree[symbol] = 0
            
        for symbol in symbols:
            for dep in symbol.dependencies:
                if dep in symbols:
                    graph[dep].add(symbol)
                    in_degree[symbol] += 1
                    
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
            raise CircularDependencyError(
                f"Circular dependency detected among symbols: "
                f"{', '.join(s.qname for s in remaining)}"
            )
            
        return sorted_symbols
        
    def generate_name_mappings(self, symbols: Set[Symbol]):
        """生成名称映射"""
        # 统计名称冲突
        name_counts = defaultdict(int)
        for symbol in symbols:
            if symbol.symbol_type != 'import_alias':
                name_counts[symbol.name] += 1
                
        # 生成映射
        for symbol in symbols:
            if symbol.symbol_type == 'import_alias':
                # 导入别名保持不变
                continue
                
            if name_counts[symbol.name] > 1:
                # 有冲突，需要重命名
                module_key = self.visitor.get_module_qname(symbol.scope.module_path)
                module_key = module_key.replace('.', '_').replace('__init__', 'pkg')
                new_name = f"{module_key}_{symbol.name}"
                self.name_mappings[symbol.qname] = new_name
            else:
                # 无冲突，保持原名
                self.name_mappings[symbol.qname] = symbol.name
                
    def _static_verify(self, merged_code: str) -> Dict[str, List[str]]:
        """
        对合并结果做静态扫描，返回问题字典。
        """
        try:
            tree = ast.parse(merged_code)
        except SyntaxError as e:
            return {'syntax_error': [str(e)], 'undefined_names': [], 'duplicate_imports': []}

        # 辅助函数：递归提取赋值目标中的所有名称
        def _extract_defined_names(target_node):
            names = set()
            if isinstance(target_node, ast.Name):
                names.add(target_node.id)
            elif isinstance(target_node, (ast.Tuple, ast.List)):
                for element in target_node.elts:
                    names.update(_extract_defined_names(element))
            return names

        defined = set()
        # 收集所有定义
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                defined.add(n.name)
            elif isinstance(n, ast.Assign):
                # 处理所有赋值目标，包括链式赋值和元组解包
                for target in n.targets:
                    defined.update(_extract_defined_names(target))
            elif isinstance(n, ast.Import):
                for alias in n.names:
                    defined.add(alias.asname or alias.name.split('.')[-1])
            elif isinstance(n, ast.ImportFrom):
                for alias in n.names:
                    defined.add(alias.asname or alias.name)
        
        # 收集所有使用
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        
        # Python 内置函数和关键字不应被视为未定义
        builtin_names = set(dir(__builtins__))
        undefined = sorted((used - defined) - builtin_names)

        # 文本级查找重复导入
        imports_seen, duplicates = set(), []
        for line in merged_code.splitlines():
            stripped_line = line.strip()
            if stripped_line.startswith(('import ', 'from ')):
                if stripped_line in imports_seen:
                    duplicates.append(stripped_line)
                imports_seen.add(stripped_line)

        return {'undefined_names': undefined, 'duplicate_imports': duplicates, 'syntax_error': []}

    def merge_script(self, script_path: Path) -> str:
        """合并脚本"""
        script_path = script_path.resolve()
        
        # 1. 分析入口脚本
        initial_symbols, main_code = self.analyze_entry_script(script_path)
        
        # 2. 收集所有依赖
        self.needed_symbols = self.collect_all_dependencies(initial_symbols)
        
        # 3. 过滤掉导入别名、嵌套定义和模块符号
        output_symbols = {
            s for s in self.needed_symbols 
            if s.symbol_type not in ('import_alias', 'module', 'parameter') and not s.is_nested
        }
        
        # 4. 拓扑排序
        sorted_symbols = self.topological_sort(output_symbols)
        
        # 5. 生成名称映射
        self.generate_name_mappings(output_symbols)
        
        # 6. 生成代码
        transformer = AdvancedNodeTransformer(self.name_mappings, self.visitor, self.visitor.all_symbols)
        
        result_lines = []
        
        # __future__ 导入必须在最前面
        if self.visitor.future_imports:
            result_lines.extend(sorted(self.visitor.future_imports))
            result_lines.append("")
            
        # 外部导入
        if self.visitor.external_imports:
            result_lines.extend(sorted(self.visitor.external_imports))
            result_lines.append("")
            
        # 合并的符号定义
        module_inits = {}  # 收集每个模块的初始化语句
        
        for symbol in sorted_symbols:
            # 添加源文件注释
            if symbol.scope.module_path:
                rel_path = symbol.scope.module_path.relative_to(self.project_root)
                result_lines.append(f"# From {rel_path}")
            
            # 转换并输出符号定义
            transformed = transformer.transform_symbol(symbol)
            if transformed is not None:
                result_lines.append(ast.unparse(transformed))
                result_lines.append("")
            
            # 收集模块初始化语句
            module_qname = self.visitor.get_module_qname(symbol.scope.module_path)
            if module_qname in self.visitor.all_symbols:
                module_symbol = self.visitor.all_symbols[module_qname]
                if module_symbol.init_statements and module_qname not in module_inits:
                    module_inits[module_qname] = module_symbol.init_statements
                    
        # 输出所有模块的初始化语句
        if module_inits:
            result_lines.append("# Module initialization statements")
            for module_qname, init_stmts in module_inits.items():
                result_lines.append(f"# From module: {module_qname}")
                for stmt in init_stmts:
                    # 跳过模块文档字符串
                    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                        continue
                    transformed_stmt = transformer.visit(copy.deepcopy(stmt))
                    result_lines.append(ast.unparse(transformed_stmt))
            result_lines.append("")
            
        # 主代码
        if main_code:
            result_lines.append("# Main script code")
            for node in main_code:
                transformed = transformer.visit(copy.deepcopy(node))
                result_lines.append(ast.unparse(transformed))
                
        final_code = "\n".join(result_lines)

        if getattr(self, "enable_verify", False):
            problems = self._static_verify(final_code)
            if any(problems.values()):
                print("\n--- ⚠️  静态自检发现问题 ---")
                if problems.get('syntax_error'):
                    print(f"  致命语法错误: {problems['syntax_error'][0]}")
                if problems.get('undefined_names'):
                    print(f"  可能未定义的符号: {problems['undefined_names']}")
                if problems.get('duplicate_imports'):
                    print("  重复的导入语句 (将自动修复):")
                    for line in sorted(list(set(problems['duplicate_imports']))):
                        print(f"    {line}")
                    
                    # 自动修复：去除重复的导入
                    lines = final_code.splitlines()
                    seen_imports = set()
                    cleaned_lines = []
                    
                    for line in lines:
                        stripped = line.strip()
                        if stripped.startswith(('import ', 'from ')):
                            if stripped not in seen_imports:
                                seen_imports.add(stripped)
                                cleaned_lines.append(line)
                            # 如果是重复的导入，跳过这一行
                        else:
                            cleaned_lines.append(line)
                    
                    final_code = "\n".join(cleaned_lines)
                    print("  ✅ 已自动去除重复的导入语句")
                    
                print("---------------------------\n")

        return final_code


class AdvancedNodeTransformer(ast.NodeTransformer):
    """高级代码转换器"""
    
    def __init__(self, name_mappings: Dict[str, str], visitor: ContextAwareVisitor, 
                 all_symbols: Dict[str, Symbol]):
        self.name_mappings = name_mappings  # qname -> new_name
        self.visitor = visitor
        self.all_symbols = all_symbols
        self.current_scope_stack = []  # 当前的作用域栈
        
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
        self.current_scope_stack = [symbol.scope]
        
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
        current_module = self.get_current_module_path()
        
        # 首先查找当前模块中的符号
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
        # 查找函数对应的作用域
        func_scope = None
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
            # 查找符号的限定名
            qname = self.find_symbol_qname(node.id)
            if qname and qname in self.name_mappings:
                node.id = self.name_mappings[qname]
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
        base_symbol = self.resolve_name_to_symbol(base_name)
        
        if not base_symbol:
            # 基名无法解析，保持原样
            return self.generic_visit(node)
            
        # 处理别名 - 检查别名本身是否有映射
        if base_symbol.symbol_type == 'import_alias':
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
            
        # 尝试解析完整的属性链
        # 对于 a.b.c，我们需要先解析 a.b，再解析 (a.b).c
        current_symbol = target_symbol
        
        for i, attr in enumerate(attrs):
            if current_symbol.scope and attr in current_symbol.scope.symbols:
                current_symbol = current_symbol.scope.symbols[attr]
                
                # 检查是否需要转换为简单名称
                if i == len(attrs) - 1:  # 最后一个属性
                    if current_symbol.qname in self.name_mappings:
                        new_name = self.name_mappings[current_symbol.qname]
                        return ast.Name(id=new_name, ctx=node.ctx)
            else:
                # 无法继续解析，保持原样
                break
                
        # 如果无法完全解析，递归处理子节点
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
        
    def visit_Constant(self, node: ast.Constant):
        """处理字符串常量中的类型注解"""
        # 暂时不处理字符串类型注解
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