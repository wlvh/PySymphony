# PySymphony 测试套件

## 概述

本测试套件包含了对 PySymphony 代码合并工具的全面测试，包括运行时行为验证和静态代码质量检查。测试采用分层架构，提供从单元测试到端到端测试的全覆盖。

## 测试架构

### 分层测试结构

```
tests/
├── ast_auditor.py               # 🚀 工业级 AST 审计器核心模块
├── unit/                        # 单元测试
│   └── test_ast_auditor.py      # 审计器组件的独立测试
├── integration/                 # 集成测试
│   └── test_auditor_catches_bad_merge.py  # 对抗性测试
├── e2e/                         # 端到端测试
│   └── test_full_merge_workflow.py  # 完整工作流程测试
├── fixtures/                    # 测试固件
│   └── test_pkg/               # 用于测试的包
├── test_static_checks.py       # 静态检查功能测试
├── test_regression.py          # 回归测试
└── test_advanced_merger_fixes.py # 高级合并功能测试
```

### 测试理念

1. **测试即产品**：测试套件是产品交付的核心部分，具备同样高的代码质量
2. **零容忍安全网**：静态检查是阻止缺陷的最后防线，必须是强制的、无条件的
3. **对抗性测试**：主动构造会导致合并工具出错的场景，验证审计系统能够捕获

## 工业级 AST 审计系统

### 多阶段静态分析

系统采用专业的多阶段 AST 审计架构，通过 `ASTAuditor` 类协调三个独立的分析阶段：

#### 阶段一：符号表构建 (SymbolTableBuilder)
- 遍历 AST，记录所有顶层定义（函数、类、变量、导入别名）
- 维护完整的作用域层次结构
- 精确检测同名符号的重复定义

#### 阶段二：引用完整性验证 (ReferenceValidator)
- 验证每个符号引用都能链接到唯一、正确的定义
- 支持 LEGB（Local, Enclosing, Global, Built-in）作用域解析
- 智能排除 Python 内置名称

#### 阶段三：特定模式检查 (PatternChecker)
- 检测合并场景特有的问题（如多个 `if __name__ == "__main__"` 块）
- 可扩展的模式检查框架

### 补充检查

除了 AST 审计器，系统还使用：
- **pyflakes API**：提供额外的静态分析（性能优于子进程调用）
- **flake8**（备用）：当 pyflakes 不可用时的后备方案

所有检查都是强制性的，任何失败都会阻止代码执行。

## 如何调试静态检查失败

审计器提供详细的错误报告，格式清晰易读：

### 错误报告示例

```
静态分析错误 in /path/to/merged.py:
=== 错误 ===
✗ 符号 'shared_function' 重复定义于第 [2, 8] 行
✗ 未定义的名称 'undefined_var' 在第 5 行
✗ 发现多个 'if __name__ == "__main__"' 块在第 [10, 20] 行
```

### 常见错误类型及解决方法

#### 1. 语法错误
**错误信息**：`语法错误: invalid syntax at line X`

**解决方法**：
- 检查指定行的语法
- 常见问题：缺少括号、冒号或引号

#### 2. 重复定义
**错误信息**：`符号 'function_name' 重复定义于第 [10, 25] 行`

**解决方法**：
- 检查 `advanced_merge.py` 的重命名逻辑
- 确保正确处理了命名冲突
- 验证智能重命名功能是否启用

#### 3. 未定义的引用
**错误信息**：`未定义的名称 'variable_name' 在第 X 行`

**解决方法**：
- 确保所有依赖都被正确包含
- 检查符号重命名是否更新了所有引用
- 验证导入语句是否完整

#### 4. 多个主块
**错误信息**：`发现多个 'if __name__ == "__main__"' 块`

**解决方法**：
- 确保合并工具只保留主脚本的主块
- 移除依赖模块中的主块

### 调试步骤

1. **查看生成的合并文件**
   ```bash
   # 运行测试时保留合并文件
   pytest test_name.py -k specific_test --pdb
   ```

2. **单独测试静态检查**
   ```python
   from conftest import static_check
   from pathlib import Path
   
   # 读取有问题的文件
   code = Path("problematic_file.py").read_text()
   static_check(code, Path("test.py"))
   ```

3. **手动运行 flake8**
   ```bash
   flake8 --select=F merged_file.py
   ```

## 运行测试

### 运行所有测试
```bash
pytest
```

### 使用合并后的脚本运行测试
```bash
pytest --merged
```

### 运行特定类型的测试

```bash
# 单元测试
pytest tests/unit/

# 集成测试（包括对抗性测试）
pytest tests/integration/

# 端到端测试
pytest tests/e2e/

# 特定的测试文件
pytest tests/integration/test_auditor_catches_bad_merge.py
```

### 查看详细的测试输出
```bash
pytest -v --tb=short
```

## 依赖安装

确保安装了开发依赖：
```bash
pip install -r requirements-dev.txt
```

主要依赖：
- `pytest` - 测试框架
- `pyflakes` - 高性能静态分析（推荐）
- `flake8` - 备用静态分析工具

## 测试类型说明

### 单元测试
- 测试 AST 审计器的各个组件
- 快速、独立、易于调试
- 位置：`tests/unit/`

### 集成测试
- 包含对抗性测试，验证审计器能捕获实际错误
- 测试组件间的交互
- 位置：`tests/integration/`

### 端到端测试
- 测试完整的工作流程
- 从代码合并到执行的全流程验证
- 位置：`tests/e2e/`

## 持续集成

GitHub Actions 会自动运行所有测试，包括静态检查。确保在提交前本地测试通过。