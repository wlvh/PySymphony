# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python code merging tool project that implements utilities for flattening Python projects with dependencies into single files. The main purpose is to merge a Python script and all its local project dependencies into one standalone file, while preserving external library imports.

## Architecture

```
/Demo/
├── scripts/                 # Main scripts directory
│   ├── __init__.py          # Package marker (empty)
│   ├── my_scripts.py        # Main demo script that imports from test fixtures
│   └── advanced_merge.py    # 🚀 The code merger with comprehensive AST analysis
├── tests/                   # All test files
│   ├── fixtures/            # Test fixtures (demo packages)
│   │   ├── a_pkg/           # Demo package A
│   │   │   ├── __init__.py  # (empty)
│   │   │   └── a.py         # Contains global_same(), hello(), hello2() functions
│   │   ├── b_pkg/           # Demo package B
│   │   │   ├── __init__.py  # (empty)
│   │   │   └── b.py         # Contains global_same(), b_hello() functions, imports from a_pkg
│   │   └── test_pkg/        # Test packages for advanced features
│   │       ├── __init__.py  # (empty)
│   │       ├── unique_func.py    # Test cases for smart renaming
│   │       ├── order_test.py     # Test cases for dependency ordering
│   │       └── complex_deps.py   # Complex multi-layer dependency tests
│   ├── test_complex.py      # Test script for complex dependencies
│   ├── test_issues.py       # Test script for smart renaming and ordering
│   ├── test_regression.py   # Regression tests
│   └── test_advanced_merger_fixes.py  # Tests for advanced merger fixes
├── conftest.py              # Pytest configuration
└── pytest.ini               # Pytest settings
```

## Key Components

### 🚀 Code Merger Tool
- **`scripts/advanced_merge.py`**: The comprehensive implementation with advanced AST analysis:
  - **Advanced scope analysis**: Full LEGB (Local, Enclosing, Global, Built-in) scope resolution
  - **Symbol tracking**: Comprehensive tracking of all Python symbols (functions, classes, variables)
  - **Enhanced attribute resolution**: Supports nested attribute chains (e.g., `a.b.c.d`)
  - **Correct nonlocal/global handling**: Properly tracks and preserves scope declarations
  - **Import alias mapping**: Complete support for all import patterns and aliases

### Demo Code
- **`tests/fixtures/a_pkg/a.py`**: Contains `global_same()`, `hello()`, `hello2()` - demonstrates internal dependencies
- **`tests/fixtures/b_pkg/b.py`**: Contains `global_same()`, `b_hello()` - demonstrates cross-module imports with aliases
- **`scripts/my_scripts.py`**: Main demo script importing from both packages

### Test Code
- **`tests/fixtures/test_pkg/unique_func.py`**: Functions with unique names that shouldn't be renamed
- **`tests/fixtures/test_pkg/order_test.py`**: Multi-level dependencies to test correct ordering
- **`tests/fixtures/test_pkg/complex_deps.py`**: Complex dependency chains for advanced testing
- **`tests/test_advanced_merger_fixes.py`**: Comprehensive tests for advanced merger fixes
- **`tests/test_regression.py`**: Regression tests to ensure stability
- **`tests/test_complex.py`**: Tests for complex dependency scenarios
- **`tests/test_issues.py`**: Tests for specific issue resolutions

## Development Commands

This project lacks standard Python configuration files (no requirements.txt, setup.py, pyproject.toml). To work with the code:

```bash
# Run the main demo script (requires PYTHONPATH)
PYTHONPATH=. python scripts/my_scripts.py

# Run the code merger tool
python scripts/advanced_merge.py scripts/my_scripts.py .
```

## 🚀 Advanced Merge Tool Features

### Core Features
- **✅ Complete dependency resolution**: Recursively finds all required functions across modules
- **✅ Perfect import alias handling**: Correctly processes `import a as b` and `from a import b as c`  
- **✅ External library preservation**: Keeps `import os`, `import sys` etc. at the top
- **✅ Minimal code inclusion**: Only includes functions that are actually used
- **✅ Cross-module dependency tracking**: Handles complex dependency chains between modules
- **✅ Correct output**: Merged script produces identical output to original

### Advanced Features
- **✅ Smart renaming**: Only renames functions when there are actual naming conflicts
  - Functions with unique names keep their original names
  - Only conflicting functions get module prefixes (`a_pkg_a_global_same` vs `b_pkg_b_global_same`)
- **✅ Dependency ordering**: Uses topological sort to ensure correct function definition order
  - Dependencies are always defined before the functions that use them
  - Handles complex multi-layer dependency chains
  - Detects and handles circular dependencies gracefully
- **✅ Source tracking**: Each function includes a comment showing its source file
  - Example: `# From a_pkg/a.py`
  - Helps trace code origin in merged files
- **✅ Advanced scope analysis**: Full LEGB (Local, Enclosing, Global, Built-in) scope resolution
- **✅ Comprehensive symbol tracking**: Tracks all Python symbols (functions, classes, variables)
- **✅ Enhanced attribute resolution**: Supports nested attribute chains (e.g., `a.b.c.d`)
- **✅ Proper scope declarations**: Correctly tracks and preserves nonlocal/global declarations

### Usage
```bash
python scripts/advanced_merge.py <script_path> <project_root>
```

### Examples
```bash
# Merge the demo script
python scripts/advanced_merge.py scripts/my_scripts.py .
# Output: scripts/my_scripts_advanced_merged.py

# Test smart renaming and dependency ordering
python scripts/advanced_merge.py tests/test_issues.py .
# Output: tests/test_issues_advanced_merged.py

# Test complex dependency chains
python scripts/advanced_merge.py tests/test_complex.py .
# Output: tests/test_complex_advanced_merged.py
```

### Technical Implementation
- **AST-based parsing**: Uses Python's `ast` module for accurate code analysis
- **Global dependency graph**: Builds complete dependency relationships before merging
- **Symbol tracking**: Tracks all function definitions and their dependencies
- **Smart name mapping**: Creates unique names only when conflicts exist
- **Topological sorting**: Ensures correct function definition order using graph algorithms
  - Fixed algorithm to properly handle dependency chains
  - Reverses final order to ensure dependencies are defined first
- **Conflict detection**: Analyzes symbol frequency to determine renaming necessity
- **Import alias resolution**: Correctly handles `import X as Y` patterns
  - Maps aliases to their corresponding renamed functions
  - Preserves original alias relationships in merged code

## Demo Dependency Patterns

The demo packages showcase complex dependency scenarios that the merger tool handles:

### Cross-package Dependencies
```python
# tests/fixtures/a_pkg/a.py
def global_same():     # Function with same name as in b_pkg
def hello():           # Calls global_same() internally  
def hello2():          # Also calls global_same() internally

# tests/fixtures/b_pkg/b.py  
from tests.fixtures.a_pkg.a import hello2                    # Direct import
from tests.fixtures.a_pkg.a import global_same as global_same_a  # Import with alias
def global_same():     # Same name as in a_pkg (conflict!)
def b_hello():         # Calls hello2(), global_same(), global_same_a()

# scripts/my_scripts.py
from tests.fixtures.a_pkg.a import hello     # Import from first package
from tests.fixtures.b_pkg.b import b_hello   # Import from second package
```

### How Advanced Merger Resolves This
```python
# Output: scripts/my_scripts_advanced_merged.py
# From tests/fixtures/a_pkg/a.py
def a_pkg_a_global_same():    # Only renamed due to conflict with b_pkg version
    print('Global same in a')

# From tests/fixtures/a_pkg/a.py
def hello2():
    print('Hello World2')
    a_pkg_a_global_same()

# From tests/fixtures/b_pkg/b.py
def b_pkg_b_global_same():    # Only renamed due to conflict with a_pkg version
    print('Global same in b')

# From tests/fixtures/b_pkg/b.py
def b_hello():
    hello2()
    b_pkg_b_global_same()     # Calls its own global_same
    a_pkg_a_global_same()     # Calls aliased function correctly

# From tests/fixtures/a_pkg/a.py
def hello():
    print('Hello World')
    a_pkg_a_global_same()

if __name__ == '__main__':
    hello()
    b_hello()
```

### Smart Renaming Examples
```python
# Output: tests/test_issues_advanced_merged.py
# From tests/fixtures/test_pkg/order_test.py
def level_3_func():                         # Keeps original name (no conflict)
    """第三层函数，不依赖其他函数"""
    print('Level 3 function')
    return 'level3'

# From tests/fixtures/test_pkg/order_test.py
def level_2_func():                         # Keeps original name (no conflict)
    """第二层函数，依赖level_3_func"""
    print('Level 2 function')
    result = level_3_func()
    return f'level2_{result}'

# From tests/fixtures/test_pkg/unique_func.py
def unique_function():                      # Keeps original name (no conflict)
    """这个函数名在整个项目中是独特的，不应该被重命名"""
    print('I am unique function')
    return 'unique_result'
```

### Dependency Ordering Examples
```python
# Output: tests/test_complex_advanced_merged.py (correct order)
# From tests/fixtures/test_pkg/complex_deps.py
def base_util():              # Level 0: No dependencies
    return 'base'

# From tests/fixtures/test_pkg/complex_deps.py
def formatter(value):         # Level 1: Depends on base_util
    base = base_util()
    return f'{base}:{value}'

# From tests/fixtures/test_pkg/complex_deps.py
def validator(data):          # Level 2: Depends on formatter
    formatted = formatter(data)
    return f'valid[{formatted}]'

# From tests/fixtures/test_pkg/complex_deps.py
def processor(input_data):    # Level 3: Depends on validator & base_util
    validated = validator(input_data)
    base = base_util()
    return f'process({validated}, {base})'

# From tests/fixtures/test_pkg/complex_deps.py
def main_handler(data):       # Level 4: Depends on processor & formatter
    processed = processor(data)
    formatted = formatter('final')
    return f'main[{processed}, {formatted}]'
```


## Development Environment

- **Language**: Python 3 (no external dependencies required)
- **IDE**: IntelliJ IDEA/PyCharm (`.idea/` directory present)
- **Git**: Git repository with GitHub integration
- **Dependencies**: Uses only Python standard library (`ast`, `pathlib`, `typing`)

## Recent Fixes (Issue #3)
1. **TypeError Fix**: Corrected `current_module_path` method call
2. **Nested Attribute Access**: Full support for deep attribute chains
3. **Scope Preservation**: Proper handling of nonlocal/global variables
4. **Import Mapping**: Enhanced resolution of imported symbols

## Project Purpose

This project demonstrates advanced Python code analysis and merging techniques, specifically solving the problem of:
- **Flattening project structure**: Converting multi-file Python projects into single files
- **Dependency resolution**: Finding and including all required code automatically  
- **Import alias handling**: Preserving complex import relationships
- **Conflict resolution**: Avoiding naming conflicts between modules
- **Code minimization**: Including only actually used functions
- **Maintainability**: Preserving source information for debugging