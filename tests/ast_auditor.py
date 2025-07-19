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
        # 检查重复定义
        if name in self.current_scope.symbols:
            existing = self.current_scope.symbols[name]
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
        # 只处理简单的名称赋值
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.add_symbol(target.id, node, 'variable')
        self.generic_visit(node)
        
    def visit_AnnAssign(self, node: ast.AnnAssign):
        """访问带类型注解的赋值语句"""
        if isinstance(node.target, ast.Name):
            self.add_symbol(node.target.id, node, 'variable')
        self.generic_visit(node)


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
        
    def find_symbol(self, name: str) -> Optional[SymbolInfo]:
        """在当前作用域链中查找符号"""
        scope = self.current_scope
        while scope:
            if name in scope.symbols:
                return scope.symbols[name]
            scope = scope.parent
        return None
        
    def enter_scope(self, name: str):
        """进入指定名称的作用域"""
        for child in self.current_scope.children:
            if child.name == name:
                self.current_scope = child
                return
                
    def exit_scope(self):
        """退出当前作用域"""
        if self.current_scope.parent:
            self.current_scope = self.current_scope.parent
            
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
        # 只检查基础对象，不检查属性名
        self.visit(node.value)
        
    def visit_FunctionDef(self, node: ast.FunctionDef):
        """访问函数定义"""
        self.enter_scope(node.name)
        self.generic_visit(node)
        self.exit_scope()
        
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """访问异步函数定义"""
        self.enter_scope(node.name)
        self.generic_visit(node)
        self.exit_scope()
        
    def visit_ClassDef(self, node: ast.ClassDef):
        """访问类定义"""
        self.enter_scope(node.name)
        self.generic_visit(node)
        self.exit_scope()


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
        
    def audit(self, source_code: str, filename: str = '<unknown>') -> bool:
        """
        对源代码进行完整的多阶段审计
        
        Args:
            source_code: 要审计的 Python 源代码
            filename: 文件名（用于错误报告）
            
        Returns:
            bool: 如果没有发现错误返回 True，否则返回 False
        """
        self.errors.clear()
        self.warnings.clear()
        
        try:
            tree = ast.parse(source_code, filename)
        except SyntaxError as e:
            self.errors.append(f"语法错误: {e.msg} at line {e.lineno}")
            return False
            
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
        
        return len(self.errors) == 0
        
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