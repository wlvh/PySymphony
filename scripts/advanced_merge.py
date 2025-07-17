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


@dataclass
class Symbol:
    """统一的符号模型"""
    name: str                 # 原始名称, e.g., 'hello'
    qname: str                # 全局限定名, e.g., 'a_pkg.a.hello'
    symbol_type: str          # 'function', 'class', 'variable', 'import_alias', 'parameter'
    def_node: ast.AST         # 定义此符号的AST节点
    scope: Scope              # 定义此符号的作用域
    dependencies: Set['Symbol'] = field(default_factory=set)  # 此符号依赖的其他符号
    references: List[ast.AST] = field(default_factory=list)   # 所有引用此符号的AST节点
    is_nested: bool = False   # 是否是嵌套函数/类
    decorators: List['Symbol'] = field(default_factory=list)  # 装饰器符号
    init_statements: List[ast.AST] = field(default_factory=list)  # 模块级初始化语句

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
        
        # 如果是嵌套函数，不需要创建符号（会在父函数中处理）
        if is_nested:
            return
        
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
            decorator_symbols = self.collect_dependencies_from_node(decorator)
            symbol.decorators.extend(decorator_symbols)
            symbol.dependencies.update(decorator_symbols)
            
        # 注册符号
        self.current_scope().symbols[node.name] = symbol
        self.all_symbols[qname] = symbol
        
        # 创建函数作用域
        func_scope = Scope(
            scope_type='function',
            node=node,
            module_path=self.current_module_path
        )
        self.push_scope(func_scope)
        
        # 处理参数
        for arg in node.args.args:
            param_symbol = Symbol(
                name=arg.arg,
                qname=f"{qname}.{arg.arg}",
                symbol_type='parameter',
                def_node=arg,
                scope=func_scope
            )
            func_scope.symbols[arg.arg] = param_symbol
            
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
            decorator_symbols = self.collect_dependencies_from_node(decorator)
            symbol.decorators.extend(decorator_symbols)
            symbol.dependencies.update(decorator_symbols)
            
        # 处理基类
        for base in node.bases:
            base_symbols = self.collect_dependencies_from_node(base)
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
                deps = self.collect_dependencies_from_node(node.value)
                symbol.dependencies.update(deps)
                
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
                deps = self.collect_dependencies_from_node(node.value)
                symbol.dependencies.update(deps)
                
            self.current_scope().symbols[node.target.id] = symbol
            self.all_symbols[qname] = symbol
            
    def collect_dependencies_from_node(self, node: ast.AST) -> Set[Symbol]:
        """从AST节点收集依赖符号"""
        dependencies = set()
        
        class DependencyCollector(ast.NodeVisitor):
            def __init__(self, resolver):
                self.resolver = resolver
                self.deps = set()
                self.local_vars = set()  # 局部变量
                
            def visit_FunctionDef(self, node):
                # 不进入嵌套函数
                pass
                
            def visit_AsyncFunctionDef(self, node):
                # 不进入嵌套异步函数
                pass
                
            def visit_ClassDef(self, node):
                # 不进入嵌套类
                pass
                
            def visit_Name(self, node):
                if isinstance(node.ctx, ast.Store):
                    # 局部赋值
                    self.local_vars.add(node.id)
                elif isinstance(node.ctx, ast.Load) and node.id not in self.local_vars:
                    # 引用外部符号
                    symbol = self.resolver.resolve_name(node.id)
                    if symbol:
                        self.deps.add(symbol)
                        
            def visit_Attribute(self, node):
                # 处理属性访问
                if isinstance(node.value, ast.Name):
                    symbol = self.resolver.resolve_name(node.value.id)
                    if symbol:
                        self.deps.add(symbol)
                self.generic_visit(node)
                
            def visit_Call(self, node):
                # 处理函数调用
                if isinstance(node.func, ast.Name):
                    symbol = self.resolver.resolve_name(node.func.id)
                    if symbol:
                        self.deps.add(symbol)
                elif isinstance(node.func, ast.Attribute):
                    self.visit_Attribute(node.func)
                self.generic_visit(node)
                
            def visit_Global(self, node):
                # global声明的变量不是局部变量
                for name in node.names:
                    self.local_vars.discard(name)
                    
            def visit_Nonlocal(self, node):
                # nonlocal声明的变量不是局部变量
                for name in node.names:
                    self.local_vars.discard(name)
                    
        collector = DependencyCollector(self)
        collector.visit(node)
        return collector.deps
        
    def collect_function_dependencies(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> Set[Symbol]:
        """收集函数的所有依赖"""
        dependencies = set()
        
        # 收集函数体的依赖
        for stmt in node.body:
            deps = self.collect_dependencies_from_node(stmt)
            dependencies.update(deps)
            
        return dependencies


class AdvancedCodeMerger:
    """高级代码合并器"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.visitor = ContextAwareVisitor(project_root)
        self.needed_symbols: Set[Symbol] = set()
        self.name_mappings: Dict[str, str] = {}  # qname -> new_name
        
    def analyze_entry_script(self, script_path: Path) -> Tuple[Set[Symbol], List[ast.AST]]:
        """分析入口脚本，返回初始符号集和主代码"""
        self.visitor.analyze_module(script_path)
        
        initial_symbols = set()
        main_code = []
        
        with open(script_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        tree = ast.parse(content, filename=str(script_path))
        
        # 分析入口脚本的每个语句
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                # 导入语句 - 收集导入的符号
                if isinstance(node, ast.ImportFrom) and node.module == '__future__':
                    continue  # __future__ 导入已经被收集
                    
                # 直接从作用域中查找导入创建的符号
                module_qname = self.visitor.get_module_qname(script_path)
                module_scope = None
                for scope in self.visitor.scope_stack:
                    if scope.module_path == script_path:
                        module_scope = scope
                        break
                        
                if not module_scope:
                    # 从保存的模块作用域中查找
                    if script_path in self.visitor.module_symbols:
                        module_scope = self.visitor.module_symbols[script_path].get('__scope__')
                            
                if module_scope:
                    # 查找导入创建的别名符号
                    if isinstance(node, ast.ImportFrom):
                        for alias in node.names:
                            alias_name = alias.asname or alias.name
                            if alias_name in module_scope.symbols:
                                initial_symbols.add(module_scope.symbols[alias_name])
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            alias_name = alias.asname or alias.name.split('.')[-1]
                            if alias_name in module_scope.symbols:
                                initial_symbols.add(module_scope.symbols[alias_name])
            else:
                # 其他语句 - 分析其中使用的符号
                main_code.append(node)
                
                # 收集主代码中引用的符号
                deps = self.visitor.collect_dependencies_from_node(node)
                initial_symbols.update(deps)
                        
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
        transformer = AdvancedNodeTransformer(self.name_mappings, self.visitor)
        
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
                
        return "\n".join(result_lines)


class AdvancedNodeTransformer(ast.NodeTransformer):
    """高级代码转换器"""
    
    def __init__(self, name_mappings: Dict[str, str], visitor: ContextAwareVisitor):
        self.name_mappings = name_mappings
        self.visitor = visitor
        self.current_scope_mappings: Dict[str, str] = {}
        
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
            
        # 设置当前作用域映射
        self.current_scope_mappings = self.build_scope_mappings(symbol)
        
        # 转换节点
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return self.transform_function(node, symbol)
        elif isinstance(node, ast.ClassDef):
            return self.transform_class(node, symbol)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            return self.visit(node)
        else:
            # 其他类型的符号，跳过
            return None
            
    def build_scope_mappings(self, symbol: Symbol) -> Dict[str, str]:
        """构建作用域内的名称映射"""
        mappings = {}
        
        # 收集当前符号所在模块的所有导入别名
        module_path = symbol.scope.module_path
        if module_path and module_path in self.visitor.module_symbols:
            module_syms = self.visitor.module_symbols[module_path]
            for sym_name, sym in module_syms.items():
                if sym_name == '__scope__':
                    continue
                if isinstance(sym, Symbol) and sym.symbol_type == 'import_alias':
                    # 这是一个导入别名
                    if sym.dependencies:
                        # 找到它指向的真实符号
                        for target_sym in sym.dependencies:
                            if target_sym.qname in self.name_mappings:
                                mappings[sym.name] = self.name_mappings[target_sym.qname]
                                break
        
        # 收集所有可能被引用的符号
        for dep in symbol.dependencies:
            if dep.qname in self.name_mappings:
                # 直接依赖的映射
                if dep.symbol_type != 'import_alias':
                    mappings[dep.name] = self.name_mappings[dep.qname]
                    
        return mappings
        
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
        
        # 转换函数体
        node.body = [self.visit(stmt) for stmt in node.body]
        
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
        if node.id in self.current_scope_mappings:
            node.id = self.current_scope_mappings[node.id]
        return node
        
    def visit_Attribute(self, node: ast.Attribute):
        """转换属性访问"""
        # 处理模块别名的属性访问
        if isinstance(node.value, ast.Name):
            if node.value.id in self.current_scope_mappings:
                # 这是一个模块别名
                # 需要检查是否应该直接替换为函数名
                full_name = f"{node.value.id}.{node.attr}"
                if full_name in self.current_scope_mappings:
                    # 直接替换为映射后的名称
                    return ast.Name(
                        id=self.current_scope_mappings[full_name],
                        ctx=node.ctx
                    )
                    
        return self.generic_visit(node)
        
    def visit_Global(self, node: ast.Global):
        """转换global声明"""
        new_names = []
        for name in node.names:
            if name in self.current_scope_mappings:
                new_names.append(self.current_scope_mappings[name])
            else:
                new_names.append(name)
        node.names = new_names
        return node
        
    def visit_Nonlocal(self, node: ast.Nonlocal):
        """转换nonlocal声明"""
        new_names = []
        for name in node.names:
            if name in self.current_scope_mappings:
                new_names.append(self.current_scope_mappings[name])
            else:
                new_names.append(name)
        node.names = new_names
        return node
        
    def visit_Constant(self, node: ast.Constant):
        """处理字符串常量中的类型注解"""
        if isinstance(node.value, str):
            # 简单处理：如果字符串恰好是一个需要重命名的符号名
            if node.value in self.current_scope_mappings:
                node.value = self.current_scope_mappings[node.value]
        return node


def main():
    """主函数"""
    if len(sys.argv) < 3:
        print("Usage: python advanced_merge.py <script_path> <project_root>")
        sys.exit(1)
        
    script_path = Path(sys.argv[1])
    project_root = Path(sys.argv[2])
    
    if not script_path.exists():
        print(f"Error: Script {script_path} not found")
        sys.exit(1)
        
    if not project_root.exists():
        print(f"Error: Project root {project_root} not found")
        sys.exit(1)
        
    try:
        merger = AdvancedCodeMerger(project_root)
        merged_code = merger.merge_script(script_path)
        
        # 输出到文件
        output_path = script_path.parent / f"{script_path.stem}_advanced_merged.py"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(merged_code)
            
        print(f"Merged code written to: {output_path}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()