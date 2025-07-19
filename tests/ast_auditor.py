"""
多阶段 AST 审计器 - 用于对合并后的代码进行全面的静态分析

这是一个零容忍的静态安全网实现，包含：
1. 符号表构建
2. 引用完整性验证
3. 特定模式检测
"""
import ast
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict
import hashlib


@dataclass
class Symbol:
    """符号定义信息"""
    name: str
    node_type: type  # ast.FunctionDef, ast.ClassDef, etc.
    lineno: int
    col_offset: int
    scope: str = "module"  # module, class, function
    
    def __hash__(self):
        return hash((self.name, self.node_type, self.lineno))


@dataclass
class ImportSymbol:
    """导入符号信息 - 使用元组作为唯一键"""
    module: Optional[str]  # None for 'import x'
    name: str
    alias: Optional[str]
    lineno: int
    
    @property
    def key(self) -> Tuple[Optional[str], str, Optional[str]]:
        """返回唯一标识符元组"""
        return (self.module, self.name, self.alias)
    
    def __hash__(self):
        return hash(self.key)


@dataclass
class AuditResult:
    """审计结果"""
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    symbol_table: Dict[str, List[Symbol]] = field(default_factory=lambda: defaultdict(list))
    import_table: Dict[Tuple, ImportSymbol] = field(default_factory=dict)
    
    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0
    
    def add_error(self, message: str):
        self.errors.append(message)
    
    def add_warning(self, message: str):
        self.warnings.append(message)


class SymbolTableBuilder(ast.NodeVisitor):
    """阶段一：构建符号表"""
    
    def __init__(self, result: AuditResult):
        self.result = result
        self.current_scope = "module"
        self.scope_stack = ["module"]
    
    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._register_symbol(node)
        # 进入新作用域
        self.scope_stack.append(f"function:{node.name}")
        self.current_scope = self.scope_stack[-1]
        self.generic_visit(node)
        # 退出作用域
        self.scope_stack.pop()
        self.current_scope = self.scope_stack[-1] if self.scope_stack else "module"
    
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._register_symbol(node)
        self.scope_stack.append(f"function:{node.name}")
        self.current_scope = self.scope_stack[-1]
        self.generic_visit(node)
        self.scope_stack.pop()
        self.current_scope = self.scope_stack[-1] if self.scope_stack else "module"
    
    def visit_ClassDef(self, node: ast.ClassDef):
        self._register_symbol(node)
        self.scope_stack.append(f"class:{node.name}")
        self.current_scope = self.scope_stack[-1]
        self.generic_visit(node)
        self.scope_stack.pop()
        self.current_scope = self.scope_stack[-1] if self.scope_stack else "module"
    
    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            import_sym = ImportSymbol(
                module=None,
                name=alias.name,
                alias=alias.asname,
                lineno=node.lineno
            )
            if import_sym.key in self.result.import_table:
                existing = self.result.import_table[import_sym.key]
                self.result.add_error(
                    f"Duplicate import at line {node.lineno}: '{ast.unparse(node)}' "
                    f"(previously defined at line {existing.lineno})"
                )
            else:
                self.result.import_table[import_sym.key] = import_sym
    
    def visit_ImportFrom(self, node: ast.ImportFrom):
        for alias in node.names:
            import_sym = ImportSymbol(
                module=node.module,
                name=alias.name,
                alias=alias.asname,
                lineno=node.lineno
            )
            if import_sym.key in self.result.import_table:
                existing = self.result.import_table[import_sym.key]
                self.result.add_error(
                    f"Duplicate import at line {node.lineno}: '{ast.unparse(node)}' "
                    f"(previously defined at line {existing.lineno})"
                )
            else:
                self.result.import_table[import_sym.key] = import_sym
    
    def _register_symbol(self, node):
        """注册符号到符号表"""
        symbol = Symbol(
            name=node.name,
            node_type=type(node),
            lineno=node.lineno,
            col_offset=node.col_offset,
            scope=self.current_scope
        )
        
        # 检查是否在同一作用域内重复定义
        if self.current_scope == "module":  # 只在模块级别检查重复
            existing_symbols = self.result.symbol_table[node.name]
            for existing in existing_symbols:
                if existing.scope == "module":
                    self.result.add_error(
                        f"Duplicate definition of '{node.name}' at line {node.lineno} "
                        f"(previously defined at line {existing.lineno})"
                    )
        
        self.result.symbol_table[node.name].append(symbol)


class ReferenceValidator(ast.NodeVisitor):
    """阶段二：验证引用完整性"""
    
    def __init__(self, result: AuditResult):
        self.result = result
        self.current_scope = "module"
        self.scope_stack = ["module"]
        self.local_vars = [set()]  # 栈：每个作用域的局部变量
        # 获取内置名称，处理 __builtins__ 可能是字典的情况
        import builtins
        self.builtin_names = set(dir(builtins))
        # 添加一些特殊的内置名称
        self.builtin_names.update(['__name__', '__file__', '__doc__', '__package__', '__loader__', '__spec__', '__cached__'])
    
    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load):
            self._validate_reference(node.id, node.lineno)
        elif isinstance(node.ctx, ast.Store) and self.local_vars:
            # 添加赋值的变量到当前作用域
            self.local_vars[-1].add(node.id)
        self.generic_visit(node)
    
    def visit_Attribute(self, node: ast.Attribute):
        # 对于属性访问，我们只验证基础对象
        if isinstance(node.value, ast.Name) and isinstance(node.value.ctx, ast.Load):
            self._validate_reference(node.value.id, node.lineno)
        self.generic_visit(node)
    
    def visit_FunctionDef(self, node):
        self.scope_stack.append(f"function:{node.name}")
        self.current_scope = self.scope_stack[-1]
        
        # 收集函数参数作为局部变量
        local_names = set()
        for arg in node.args.args:
            local_names.add(arg.arg)
        for arg in node.args.posonlyargs:
            local_names.add(arg.arg)
        for arg in node.args.kwonlyargs:
            local_names.add(arg.arg)
        if node.args.vararg:
            local_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            local_names.add(node.args.kwarg.arg)
        
        self.local_vars.append(local_names)
        self.generic_visit(node)
        self.local_vars.pop()
        
        self.scope_stack.pop()
        self.current_scope = self.scope_stack[-1] if self.scope_stack else "module"
    
    def visit_AsyncFunctionDef(self, node):
        self.scope_stack.append(f"function:{node.name}")
        self.current_scope = self.scope_stack[-1]
        
        # 收集函数参数作为局部变量
        local_names = set()
        for arg in node.args.args:
            local_names.add(arg.arg)
        for arg in node.args.posonlyargs:
            local_names.add(arg.arg)
        for arg in node.args.kwonlyargs:
            local_names.add(arg.arg)
        if node.args.vararg:
            local_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            local_names.add(node.args.kwarg.arg)
        
        self.local_vars.append(local_names)
        self.generic_visit(node)
        self.local_vars.pop()
        
        self.scope_stack.pop()
        self.current_scope = self.scope_stack[-1] if self.scope_stack else "module"
    
    def visit_ClassDef(self, node):
        self.scope_stack.append(f"class:{node.name}")
        self.current_scope = self.scope_stack[-1]
        self.local_vars.append(set())
        self.generic_visit(node)
        self.local_vars.pop()
        self.scope_stack.pop()
        self.current_scope = self.scope_stack[-1] if self.scope_stack else "module"
    
    def _validate_reference(self, name: str, lineno: int):
        """验证名称引用是否有效"""
        # 跳过内置名称
        if name in self.builtin_names:
            return
        
        # 检查局部变量（包括函数参数）
        for local_scope in self.local_vars:
            if name in local_scope:
                return
        
        # 检查符号表
        if name not in self.result.symbol_table:
            # 检查是否是导入的名称
            imported = False
            for import_sym in self.result.import_table.values():
                # 检查别名
                if import_sym.alias and import_sym.alias == name:
                    imported = True
                    break
                # 检查模块名（对于 import os）
                elif not import_sym.module and not import_sym.alias and import_sym.name == name:
                    imported = True
                    break
                # 检查导入的具体项（对于 from x import y）
                elif import_sym.module and not import_sym.alias and import_sym.name == name:
                    imported = True
                    break
            
            if not imported:
                self.result.add_error(
                    f"Undefined name '{name}' at line {lineno}"
                )


class PatternChecker(ast.NodeVisitor):
    """阶段三：检查特定模式"""
    
    def __init__(self, result: AuditResult, is_main_script: bool = False):
        self.result = result
        self.is_main_script = is_main_script
        self.in_main_block = False
        self.main_block_count = 0
    
    def visit_If(self, node: ast.If):
        # 检测 if __name__ == '__main__': 模式
        if (isinstance(node.test, ast.Compare) and
            isinstance(node.test.left, ast.Name) and
            node.test.left.id == '__name__' and
            len(node.test.ops) == 1 and
            isinstance(node.test.ops[0], ast.Eq) and
            len(node.test.comparators) == 1 and
            isinstance(node.test.comparators[0], ast.Constant) and
            node.test.comparators[0].value == '__main__'):
            
            self.main_block_count += 1
            if self.main_block_count > 1:
                self.result.add_error(
                    f"Multiple 'if __name__ == \"__main__\":' blocks found. "
                    f"Block at line {node.lineno} is duplicate."
                )
            
            self.in_main_block = True
            self.generic_visit(node)
            self.in_main_block = False
        else:
            self.generic_visit(node)
    
    def visit_ImportFrom(self, node: ast.ImportFrom):
        # 检查相对导入
        if node.level > 0:
            self.result.add_warning(
                f"Relative import at line {node.lineno}: '{ast.unparse(node)}'. "
                f"This may not work correctly in merged code."
            )
        self.generic_visit(node)


class ASTAuditor:
    """多阶段 AST 审计器主类"""
    
    def __init__(self):
        self._cache = {}  # 缓存审计结果
    
    def audit(self, source_code: str, filename: str = "<unknown>", 
              is_main_script: bool = True, use_cache: bool = True) -> AuditResult:
        """
        对源代码进行全面的静态审计
        
        Args:
            source_code: 要审计的 Python 源代码
            filename: 文件名（用于错误报告）
            is_main_script: 是否是主脚本（影响某些检查规则）
            use_cache: 是否使用缓存
        
        Returns:
            AuditResult 对象，包含所有发现的问题
        """
        # 计算代码哈希用于缓存
        code_hash = hashlib.sha256(source_code.encode()).hexdigest()
        
        if use_cache and code_hash in self._cache:
            return self._cache[code_hash]
        
        result = AuditResult()
        
        try:
            # 解析 AST
            tree = ast.parse(source_code, filename=filename)
        except SyntaxError as e:
            result.add_error(f"Syntax error: {e}")
            return result
        
        # 阶段一：构建符号表
        symbol_builder = SymbolTableBuilder(result)
        symbol_builder.visit(tree)
        
        # 阶段二：验证引用完整性
        ref_validator = ReferenceValidator(result)
        ref_validator.visit(tree)
        
        # 阶段三：检查特定模式
        pattern_checker = PatternChecker(result, is_main_script)
        pattern_checker.visit(tree)
        
        # 缓存结果
        if use_cache:
            self._cache[code_hash] = result
        
        return result
    
    def clear_cache(self):
        """清除缓存"""
        self._cache.clear()


# 导出便捷函数
def audit_code(source_code: str, filename: str = "<unknown>", 
               is_main_script: bool = True) -> AuditResult:
    """便捷函数：审计代码并返回结果"""
    auditor = ASTAuditor()
    return auditor.audit(source_code, filename, is_main_script)