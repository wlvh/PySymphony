# 静态分析实现文档

## 概述

本文档详细说明了 PySymphony 项目的工业级静态分析系统的设计与实现。该系统采用多阶段 AST 审计架构，确保对合并后的 Python 代码进行全面、准确的质量检查。

## 设计理念

### 核心原则

1. **承认并驾驭复杂性**：Python 语言的静态分析本质上是复杂的，我们的解决方案必须具备相应的复杂度。
2. **测试即产品**：测试套件不是附属品，而是产品交付的核心部分。
3. **零容忍安全网**：静态检查是阻止缺陷的最后防线，必须是强制的、无条件的、健壮的。

## 架构设计

### 多阶段 AST 审计器

系统的核心是 `ASTAuditor` 类，它协调三个独立的分析阶段：

```
ASTAuditor
├── SymbolTableBuilder (阶段一)
├── ReferenceValidator (阶段二)
└── PatternChecker (阶段三)
```

### 阶段一：符号表构建 (SymbolTableBuilder)

**职责**：遍历 AST，记录所有符号定义及其作用域信息。

**功能**：
- 构建完整的符号表，包括函数、类、变量和导入
- 维护作用域层次结构（模块、函数、类）
- 检测并记录重复定义
- 支持嵌套作用域和参数处理

**数据结构**：
```python
@dataclass
class SymbolInfo:
    name: str          # 符号名称
    node: ast.AST      # AST 节点
    lineno: int        # 行号
    col_offset: int    # 列偏移
    scope: str         # 作用域类型
    type: str          # 符号类型

@dataclass  
class ScopeInfo:
    name: str          # 作用域名称
    type: str          # 作用域类型
    parent: Optional['ScopeInfo']  # 父作用域
    symbols: Dict[str, SymbolInfo]  # 符号表
    children: List['ScopeInfo']     # 子作用域
```

### 阶段二：引用完整性验证 (ReferenceValidator)

**职责**：验证所有符号引用都能链接到正确的定义。

**功能**：
- 遍历 AST，检查每个名称引用
- 在作用域链中查找符号定义
- 排除内置名称（如 `len`、`print` 等）
- 记录所有未定义的引用
- **B3 增强**：验证属性引用的有效性
  - 递归解析属性链（如 `a.b.c.d`）
  - 检查类成员的存在性
  - 排除外部模块属性（如 `os.path`）

**作用域解析算法**：
1. 从当前作用域开始查找
2. 逐级向上查找父作用域
3. 最终查找模块（全局）作用域
4. 排除 Python 内置名称

### 阶段三：特定模式检查 (PatternChecker)

**职责**：检查合并场景特有的问题模式。

**当前检查项**：
- 多个 `if __name__ == "__main__"` 块
- 可扩展以添加更多模式检查

## 集成方式

### 与 pytest 的集成

在 `conftest.py` 中，`static_check` 函数被重构为使用 `ASTAuditor`：

```python
def static_check(src: str, path: Path):
    """对生成的合并代码进行静态检查"""
    auditor = ASTAuditor()
    
    if not auditor.audit(src, str(path)):
        report = auditor.get_report()
        pytest.fail(f"静态分析错误 in {path}:\n{report}")
    
    # 补充使用 pyflakes 进行额外检查
    # ...
```

### 关键改进

1. **无条件检查**：无论是否使用 `--merged` 标志，都会进行静态检查
2. **详细报告**：提供清晰的错误位置和类型信息
3. **性能优化**：优先使用 `pyflakes.api`，避免子进程开销

## 测试架构

### 目录结构

```
tests/
├── unit/                    # 单元测试
│   └── test_ast_auditor.py # 测试审计器各组件
├── integration/             # 集成测试
│   └── test_auditor_catches_bad_merge.py  # 对抗性测试
├── e2e/                     # 端到端测试
│   └── test_full_merge_workflow.py  # 完整流程测试
└── ast_auditor.py          # 审计器实现
```

### 测试策略

1. **单元测试**：独立测试每个组件的功能
2. **对抗性测试**：故意构造错误场景，验证审计器能够捕获
3. **端到端测试**：测试从合并到执行的完整流程

## 错误报告格式

审计器生成的报告采用清晰的格式：

```
=== 错误 ===
✗ 符号 'shared_function' 重复定义于第 [2, 8] 行
✗ 未定义的名称 'undefined_var' 在第 5 行
✗ 发现多个 'if __name__ == "__main__"' 块在第 [10, 20] 行

=== 警告 ===
⚠ [未来可扩展的警告信息]
```

## 扩展性设计

系统设计为易于扩展：

1. **新增检查阶段**：创建新的 `NodeVisitor` 子类
2. **新增模式检查**：在 `PatternChecker` 中添加新方法
3. **自定义报告**：扩展 `get_report` 方法

## 性能考虑

1. **单次遍历**：每个阶段只遍历 AST 一次
2. **内存效率**：使用引用而非复制 AST 节点
3. **快速查找**：使用字典进行 O(1) 符号查找
4. **B1 优化**：引入 `defnode_to_scope` 哈希映射，避免 O(N²) 的作用域查找

## 未来改进方向

1. **类型检查集成**：集成 mypy 或 pytype
2. **增量分析**：只分析变更的部分
3. **并行处理**：对大型文件进行并行分析
4. **自定义规则**：支持用户定义的检查规则
5. **IDE 集成**：提供 LSP 支持
6. **B2 完善**：处理更复杂的动态导入场景（如条件导入链）
7. **更深层的属性验证**：支持多层属性链的完整验证

## 结论

这个多阶段 AST 审计系统为 PySymphony 提供了坚实的质量保证基础。通过清晰的架构设计、全面的测试覆盖和易于扩展的实现，它确保了代码合并工具产生的输出始终是正确、可靠的。