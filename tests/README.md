# PySymphony 测试套件

## 概述

本测试套件包含了对 PySymphony 代码合并工具的全面测试，包括运行时行为验证和静态代码质量检查。

## 测试结构

```
tests/
├── fixtures/              # 测试固件
│   └── test_pkg/          # 用于测试的包
├── test_regression.py     # 回归测试
├── test_advanced_merger_fixes.py  # 高级合并功能测试
├── test_static_checks.py  # 静态检查测试
└── 各种测试场景目录/      # 特定场景的测试用例
```

## 静态检查功能

从最新版本开始，测试套件会在执行合并后的代码之前进行静态检查，以捕获以下问题：

1. **语法错误** - 无效的 Python 语法
2. **重复定义** - 重复的函数、类或导入语句
3. **未定义的名称** - 使用未定义的变量或函数
4. **未使用的导入** - 导入但未使用的模块
5. **其他静态错误** - flake8 F 系列错误

## 如何调试静态检查失败

当测试因静态检查失败时，错误信息会明确指出问题类型和位置：

### 1. 语法错误
```
Syntax error in /path/to/file.py: invalid syntax (line X)
```
**解决方法**：检查指定行的语法，常见问题包括缺少括号、冒号或引号。

### 2. 重复的顶级符号
```
Duplicate top-level symbols in /path/to/file.py:
    function_name: lines [10, 25]
    import os: lines [1, 15]
```
**解决方法**：
- 检查 `advanced_merge.py` 是否正确处理了命名冲突
- 确保合并逻辑不会重复包含相同的定义
- 验证导入语句去重逻辑是否正常工作

### 3. Flake8 错误
```
[flake8] static errors in /path/to/file.py:
file.py:10:5: F821 undefined name 'undefined_var'
file.py:1:1: F401 'os' imported but unused
```
**解决方法**：
- F821（未定义的名称）：确保所有使用的变量都已定义或导入
- F401（未使用的导入）：移除未使用的导入，或确保合并工具只包含必要的导入

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

### 运行特定的测试
```bash
pytest tests/test_static_checks.py
```

### 跳过静态检查（不推荐）
如果需要临时跳过静态检查进行调试，可以注释掉 `conftest.py` 中的 `static_check` 调用。

## 依赖安装

确保安装了开发依赖：
```bash
pip install -r requirements-dev.txt
```

主要依赖：
- `pytest` - 测试框架
- `flake8` - 静态代码分析

## 持续集成

GitHub Actions 会自动运行所有测试，包括静态检查。确保在提交前本地测试通过。