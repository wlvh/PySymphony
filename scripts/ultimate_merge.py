#!/usr/bin/env python3
"""
终极Python代码合并工具 - 完全解决所有依赖问题

核心设计原则：
1. 全局依赖图构建
2. 正确的符号重命名
3. 完整的跨模块依赖追踪
4. 准确的别名映射

使用方法:
    python ultimate_merge.py <脚本路径> <项目根目录>
"""

import ast
import os
import sys
from pathlib import Path
from typing import Set, Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class Symbol:
    """符号信息"""
    name: str
    module_path: Path
    ast_node: ast.AST
    dependencies: Set[str]  # 这个符号依赖的其他符号名称


@dataclass 
class ImportInfo:
    """导入信息"""
    import_type: str  # 'import' or 'from'
    module_name: str
    symbol_name: Optional[str]
    alias_name: str


class UltimateCodeMerger:
    """终极代码合并器"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.all_symbols = {}  # {(module_path, symbol_name): Symbol}
        self.module_imports = {}  # {module_path: [ImportInfo]}
        self.external_imports = set()
        self.dependency_graph = {}  # {symbol_id: set(dependent_symbol_ids)}
        self.final_symbols = {}  # 最终需要包含的符号
        self.name_mappings = {}  # 全局名称映射 {original_name: new_name}
        
    def is_internal_module(self, module_name: str) -> bool:
        """判断是否为项目内部模块"""
        if not module_name:
            return False
            
        module_parts = module_name.split('.')
        current_path = self.project_root
        
        for part in module_parts:
            current_path = current_path / part
            
        return (current_path.with_suffix('.py').exists() or 
                (current_path / '__init__.py').exists())
    
    def resolve_module_path(self, module_name: str) -> Optional[Path]:
        """解析模块路径"""
        if not self.is_internal_module(module_name):
            return None
            
        module_parts = module_name.split('.')
        current_path = self.project_root
        
        for part in module_parts:
            current_path = current_path / part
            
        py_file = current_path.with_suffix('.py')
        if py_file.exists():
            return py_file
            
        init_file = current_path / '__init__.py'
        if init_file.exists():
            return init_file
            
        return None
    
    def get_module_key(self, module_path: Path) -> str:
        """获取模块唯一标识"""
        try:
            rel_path = module_path.relative_to(self.project_root)
            return str(rel_path).replace('/', '_').replace('\\', '_').replace('.py', '').replace('__init__', 'pkg')
        except ValueError:
            return module_path.stem
    
    def analyze_module(self, module_path: Path):
        """分析单个模块，收集所有符号和导入信息"""
        if module_path in self.module_imports:
            return  # 已经分析过
            
        with open(module_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        tree = ast.parse(content)
        
        # 收集所有符号定义
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # 分析这个符号的依赖
                dependencies = set()
                for child in ast.walk(node):
                    if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                        dependencies.add(child.id)
                
                symbol = Symbol(
                    name=node.name,
                    module_path=module_path,
                    ast_node=node,
                    dependencies=dependencies
                )
                
                symbol_id = (module_path, node.name)
                self.all_symbols[symbol_id] = symbol
        
        # 收集导入信息
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name
                    alias_name = alias.asname or alias.name.split('.')[-1]
                    imports.append(ImportInfo('import', module_name, None, alias_name))
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ''
                for alias in node.names:
                    symbol_name = alias.name
                    alias_name = alias.asname or alias.name
                    imports.append(ImportInfo('from', module_name, symbol_name, alias_name))
        
        self.module_imports[module_path] = imports
        
        # 递归分析依赖的内部模块
        for import_info in imports:
            if self.is_internal_module(import_info.module_name):
                dep_module_path = self.resolve_module_path(import_info.module_name)
                if dep_module_path:
                    self.analyze_module(dep_module_path)
    
    def build_dependency_graph(self):
        """构建完整的依赖图"""
        # 为每个符号建立依赖关系
        for symbol_id, symbol in self.all_symbols.items():
            module_path = symbol.module_path
            imports = self.module_imports[module_path]
            
            # 解析符号的每个依赖
            for dep_name in symbol.dependencies:
                # 检查是否是导入的符号
                for import_info in imports:
                    if import_info.alias_name == dep_name:
                        if self.is_internal_module(import_info.module_name):
                            dep_module_path = self.resolve_module_path(import_info.module_name)
                            if dep_module_path and import_info.symbol_name:
                                dep_symbol_id = (dep_module_path, import_info.symbol_name)
                                if dep_symbol_id in self.all_symbols:
                                    if symbol_id not in self.dependency_graph:
                                        self.dependency_graph[symbol_id] = set()
                                    self.dependency_graph[symbol_id].add(dep_symbol_id)
                        break
                else:
                    # 检查是否是同模块的其他符号
                    local_symbol_id = (module_path, dep_name)
                    if local_symbol_id in self.all_symbols:
                        if symbol_id not in self.dependency_graph:
                            self.dependency_graph[symbol_id] = set()
                        self.dependency_graph[symbol_id].add(local_symbol_id)
    
    def collect_needed_symbols(self, initial_symbols: Set[Tuple[Path, str]]) -> Set[Tuple[Path, str]]:
        """递归收集所有需要的符号"""
        needed = set()
        to_process = list(initial_symbols)
        
        while to_process:
            symbol_id = to_process.pop()
            if symbol_id in needed or symbol_id not in self.all_symbols:
                continue
                
            needed.add(symbol_id)
            
            # 添加这个符号的所有依赖
            if symbol_id in self.dependency_graph:
                for dep_symbol_id in self.dependency_graph[symbol_id]:
                    if dep_symbol_id not in needed:
                        to_process.append(dep_symbol_id)
        
        return needed
    
    def topological_sort(self, symbols: Set[Tuple[Path, str]]) -> List[Tuple[Path, str]]:
        """对符号进行拓扑排序，确保依赖的函数先定义"""
        # 构建正向依赖图和入度表
        in_degree = {symbol: 0 for symbol in symbols}
        forward_graph = {symbol: set() for symbol in symbols}
        
        # 构建正向依赖图：如果A依赖B，那么A->B有边，B的入度+1
        for symbol in symbols:
            if symbol in self.dependency_graph:
                for dep in self.dependency_graph[symbol]:
                    if dep in symbols:
                        forward_graph[symbol].add(dep)
                        in_degree[dep] += 1
        
        # 拓扑排序：从入度为0的节点开始（这些是没有被其他函数依赖的）
        queue = [symbol for symbol in symbols if in_degree[symbol] == 0]
        sorted_symbols = []
        
        while queue:
            current = queue.pop(0)
            sorted_symbols.append(current)
            
            # 处理当前节点的所有依赖
            for dep in forward_graph[current]:
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)
        
        # 如果有循环依赖，返回原始顺序
        if len(sorted_symbols) != len(symbols):
            return list(symbols)
        
        # 反转结果，使得被依赖的函数先定义
        return sorted_symbols[::-1]
    
    def generate_name_mappings(self, needed_symbols: Set[Tuple[Path, str]]):
        """生成名称映射 - 只在有冲突时才重命名"""
        # 统计所有符号名称出现次数
        symbol_counts = {}
        for module_path, symbol_name in needed_symbols:
            symbol_counts[symbol_name] = symbol_counts.get(symbol_name, 0) + 1
        
        # 只为有冲突的符号生成带前缀的名称
        for module_path, symbol_name in needed_symbols:
            if symbol_counts[symbol_name] > 1:
                # 有冲突，需要加前缀
                module_key = self.get_module_key(module_path)
                new_name = f"{module_key}_{symbol_name}"
                self.name_mappings[(module_path, symbol_name)] = new_name
            else:
                # 无冲突，保持原名
                self.name_mappings[(module_path, symbol_name)] = symbol_name
        
        # 为每个模块的导入建立别名映射
        for module_path, imports in self.module_imports.items():
            for import_info in imports:
                if self.is_internal_module(import_info.module_name):
                    dep_module_path = self.resolve_module_path(import_info.module_name)
                    if dep_module_path and import_info.symbol_name:
                        dep_symbol_id = (dep_module_path, import_info.symbol_name)
                        if dep_symbol_id in self.name_mappings:
                            # 建立别名到新名称的映射
                            alias_key = (module_path, import_info.alias_name)
                            self.name_mappings[alias_key] = self.name_mappings[dep_symbol_id]
                else:
                    # 外部导入
                    if import_info.import_type == 'import':
                        if import_info.alias_name != import_info.module_name.split('.')[-1]:
                            self.external_imports.add(f"import {import_info.module_name} as {import_info.alias_name}")
                        else:
                            self.external_imports.add(f"import {import_info.module_name}")
                    else:
                        if import_info.alias_name != import_info.symbol_name:
                            self.external_imports.add(f"from {import_info.module_name} import {import_info.symbol_name} as {import_info.alias_name}")
                        else:
                            self.external_imports.add(f"from {import_info.module_name} import {import_info.symbol_name}")
    
    def merge_script(self, script_path: Path) -> str:
        """合并脚本"""
        script_path = script_path.resolve()
        
        # 1. 分析脚本本身
        self.analyze_module(script_path)
        
        # 2. 构建全局依赖图
        self.build_dependency_graph()
        
        # 3. 找出脚本直接需要的符号
        with open(script_path, 'r', encoding='utf-8') as f:
            script_content = f.read()
            
        script_tree = ast.parse(script_content)
        initial_symbols = set()
        script_main_code = []
        
        for node in script_tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name
                    alias_name = alias.asname or alias.name.split('.')[-1]
                    if not self.is_internal_module(module_name):
                        if alias_name != module_name.split('.')[-1]:
                            self.external_imports.add(f"import {module_name} as {alias_name}")
                        else:
                            self.external_imports.add(f"import {module_name}")
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ''
                for alias in node.names:
                    symbol_name = alias.name
                    alias_name = alias.asname or alias.name
                    
                    if self.is_internal_module(module_name):
                        module_path = self.resolve_module_path(module_name)
                        if module_path:
                            initial_symbols.add((module_path, symbol_name))
                    else:
                        if alias_name != symbol_name:
                            self.external_imports.add(f"from {module_name} import {symbol_name} as {alias_name}")
                        else:
                            self.external_imports.add(f"from {module_name} import {symbol_name}")
            else:
                script_main_code.append(node)
        
        # 4. 收集所有需要的符号（递归）
        needed_symbols = self.collect_needed_symbols(initial_symbols)
        
        # 5. 生成名称映射
        self.generate_name_mappings(needed_symbols)
        
        # 6. 按依赖顺序排序符号
        sorted_symbols = self.topological_sort(needed_symbols)
        
        # 7. 生成重命名后的函数
        final_functions = []
        for symbol_id in sorted_symbols:
            symbol = self.all_symbols[symbol_id]
            new_name = self.name_mappings[symbol_id]
            
            # 添加源文件注释
            module_path = symbol.module_path
            rel_path = module_path.relative_to(self.project_root)
            comment = f"# From {rel_path}"
            
            # 复制AST节点
            new_node = ast.copy_location(
                ast.parse(ast.unparse(symbol.ast_node)).body[0], 
                symbol.ast_node
            )
            
            # 重命名函数本身
            new_node.name = new_name
            
            # 创建这个模块的局部映射
            local_mapping = {}
            module_path = symbol.module_path
            
            # 添加同模块符号的映射
            for dep_name in symbol.dependencies:
                dep_symbol_id = (module_path, dep_name)
                if dep_symbol_id in self.name_mappings:
                    local_mapping[dep_name] = self.name_mappings[dep_symbol_id]
                
                # 添加导入别名的映射
                alias_key = (module_path, dep_name)
                if alias_key in self.name_mappings:
                    local_mapping[dep_name] = self.name_mappings[alias_key]
            
            # 应用名称转换
            transformer = NameTransformer(local_mapping)
            transformed_node = transformer.visit(new_node)
            
            final_functions.append(transformed_node)
        
        # 8. 处理主脚本代码
        script_mapping = {}
        script_imports = self.module_imports[script_path]
        for import_info in script_imports:
            if self.is_internal_module(import_info.module_name):
                module_path = self.resolve_module_path(import_info.module_name)
                if module_path and import_info.symbol_name:
                    symbol_id = (module_path, import_info.symbol_name)
                    if symbol_id in self.name_mappings:
                        script_mapping[import_info.alias_name] = self.name_mappings[symbol_id]
        
        final_main_code = []
        for node in script_main_code:
            transformer = NameTransformer(script_mapping)
            transformed_node = transformer.visit(node)
            final_main_code.append(transformed_node)
        
        # 9. 生成最终代码
        result_lines = []
        
        # 外部imports
        if self.external_imports:
            result_lines.extend(sorted(self.external_imports))
            result_lines.append("")
        
        # 合并的函数
        for i, (symbol_id, func_node) in enumerate(zip(sorted_symbols, final_functions)):
            # 添加源文件注释
            module_path = self.all_symbols[symbol_id].module_path
            rel_path = module_path.relative_to(self.project_root)
            result_lines.append(f"# From {rel_path}")
            result_lines.append(ast.unparse(func_node))
            result_lines.append("")
        
        # 主代码
        for node in final_main_code:
            result_lines.append(ast.unparse(node))
        
        return "\n".join(result_lines)


class NameTransformer(ast.NodeTransformer):
    """名称转换器"""
    
    def __init__(self, name_mapping: Dict[str, str]):
        self.name_mapping = name_mapping
    
    def visit_Name(self, node):
        if node.id in self.name_mapping:
            node.id = self.name_mapping[node.id]
        return node


def main():
    if len(sys.argv) < 3:
        print("Usage: python ultimate_merge.py <script_path> <project_root>")
        sys.exit(1)
    
    script_path = Path(sys.argv[1])
    project_root = Path(sys.argv[2])
    
    if not script_path.exists():
        print(f"Error: Script {script_path} not found")
        sys.exit(1)
    
    if not project_root.exists():
        print(f"Error: Project root {project_root} not found")
        sys.exit(1)
    
    merger = UltimateCodeMerger(project_root)
    merged_code = merger.merge_script(script_path)
    
    # 输出到文件
    output_path = script_path.parent / f"{script_path.stem}_ultimate_merged.py"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(merged_code)
    
    print(f"Merged code written to: {output_path}")


if __name__ == "__main__":
    main()