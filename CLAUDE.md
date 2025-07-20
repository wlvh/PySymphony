# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python code merging tool project that implements utilities for flattening Python projects with dependencies into single files. The main purpose is to merge a Python script and all its local project dependencies into one standalone file, while preserving external library imports.

## Architecture

```
PySymphony/
├── pysymphony/              # 🎵 Main package
│   ├── __init__.py          # Package initialization
│   └── auditor/             # 🔍 AST auditor module
│       ├── __init__.py      # Auditor package exports
│       └── auditor.py       # Industrial-grade AST auditor implementation
├── scripts/                 # Main scripts directory
│   ├── __init__.py          # Package marker (empty)
│   └── advanced_merge.py    # 🚀 The code merger with comprehensive AST analysis
├── examples/                # Example scripts and demo packages
│   ├── __init__.py          # Package marker (empty)
│   ├── demo_packages/       # Demo packages for examples
│   │   ├── __init__.py      # Package marker (empty)
│   │   ├── a_pkg/           # Demo package A
│   │   │   ├── __init__.py  # (empty)
│   │   │   └── a.py         # Contains global_same(), hello(), hello2() functions
│   │   └── b_pkg/           # Demo package B
│   │       ├── __init__.py  # (empty)
│   │       └── b.py         # Contains global_same(), b_hello() functions, imports from a_pkg
│   ├── my_scripts.py        # Main demo script that imports from demo_packages
│   ├── example_complex_deps.py  # Example showing complex dependency handling
│   └── example_smart_rename.py  # Example showing smart renaming and ordering
├── tests/                   # 🧪 Test files (pytest tests)
│   ├── __init__.py          # Package marker (empty)
│   ├── unit/                # Unit tests
│   │   ├── __init__.py      # Package marker
│   │   └── test_ast_auditor.py  # AST auditor component tests
│   ├── integration/         # Integration tests
│   │   ├── __init__.py      # Package marker
│   │   └── test_auditor_catches_bad_merge.py  # Antagonistic tests
│   ├── e2e/                 # End-to-end tests
│   │   ├── __init__.py      # Package marker
│   │   └── test_full_merge_workflow.py  # Full workflow tests
│   ├── fixtures/            # Test fixtures
│   │   ├── __init__.py      # Package marker (empty)
│   │   └── test_pkg/        # Test packages for advanced features
│   │       ├── __init__.py  # (empty)
│   │       ├── unique_func.py    # Test cases for smart renaming
│   │       ├── order_test.py     # Test cases for dependency ordering
│   │       └── complex_deps.py   # Complex multi-layer dependency tests
│   ├── test_regression.py   # Regression tests
│   └── test_advanced_merger_fixes.py  # Tests for advanced merger fixes
├── conftest.py              # Pytest configuration with AST auditor integration
├── pytest.ini               # Pytest settings
├── requirements-dev.txt     # Development dependencies
└── STATIC_ANALYSIS_IMPLEMENTATION.md  # Static analysis documentation
```

## Key Components

### 🔍 AST Auditor System
- **`pysymphony/auditor/auditor.py`**: Industrial-grade multi-stage AST analysis system:
  - **SymbolTableBuilder**: Builds comprehensive symbol tables with scope tracking
  - **ReferenceValidator**: Validates all symbol references with LEGB scope resolution
  - **PatternChecker**: Detects specific patterns (e.g., multiple main blocks)
  - **ASTAuditor**: Coordinates all analysis stages and provides detailed error reports

### 🚀 Code Merger Tool
- **`scripts/advanced_merge.py`**: The comprehensive implementation with advanced AST analysis:
  - **Advanced scope analysis**: Full LEGB (Local, Enclosing, Global, Built-in) scope resolution
  - **Symbol tracking**: Comprehensive tracking of all Python symbols (functions, classes, variables)
  - **Enhanced attribute resolution**: Supports nested attribute chains (e.g., `a.b.c.d`)
  - **Correct nonlocal/global handling**: Properly tracks and preserves scope declarations
  - **Import alias mapping**: Complete support for all import patterns and aliases
  - **Main block deduplication**: Correctly handles module initialization statements

### Example Code
- **`examples/demo_packages/a_pkg/a.py`**: Contains `global_same()`, `hello()`, `hello2()` - demonstrates internal dependencies
- **`examples/demo_packages/b_pkg/b.py`**: Contains `global_same()`, `b_hello()` - demonstrates cross-module imports with aliases
- **`examples/my_scripts.py`**: Main demo script importing from both demo packages
- **`examples/example_complex_deps.py`**: Example showing how the merger handles complex dependencies
- **`examples/example_smart_rename.py`**: Example demonstrating smart renaming and ordering features

### Test Architecture
The project implements a professional layered testing architecture:

#### Unit Tests (`tests/unit/`)
- **`test_ast_auditor.py`**: Tests individual AST auditor components in isolation

#### Integration Tests (`tests/integration/`)
- **`test_auditor_catches_bad_merge.py`**: Antagonistic tests that verify the auditor catches actual merge errors

#### End-to-End Tests (`tests/e2e/`)
- **`test_full_merge_workflow.py`**: Tests complete workflows from merging to execution

#### Test Fixtures (`tests/fixtures/test_pkg/`)
- **`unique_func.py`**: Functions with unique names that shouldn't be renamed
- **`order_test.py`**: Multi-level dependencies to test correct ordering
- **`complex_deps.py`**: Complex dependency chains for advanced testing

#### Other Tests
- **`tests/test_advanced_merger_fixes.py`**: Comprehensive tests for advanced merger fixes
- **`tests/test_regression.py`**: Regression tests to ensure stability
- **`tests/test_static_checks.py`**: Tests for static analysis functionality

## Development Commands

### Setup
```bash
# Install development dependencies
pip install -r requirements-dev.txt
```

### Running Examples
```bash
# Run example scripts (requires PYTHONPATH)
PYTHONPATH=examples python examples/my_scripts.py
PYTHONPATH=. python examples/example_complex_deps.py
PYTHONPATH=. python examples/example_smart_rename.py

# Run the code merger tool on examples
python scripts/advanced_merge.py examples/my_scripts.py examples
python scripts/advanced_merge.py examples/example_complex_deps.py .
```

### Testing
```bash
# Run all tests
pytest

# Run tests with merged scripts (tests the merger output)
pytest --merged

# Run specific test categories
pytest tests/unit/              # Unit tests only
pytest tests/integration/       # Integration tests only
pytest tests/e2e/              # End-to-end tests only

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=pysymphony --cov=scripts
```

### Import Structure
- Example scripts use absolute imports appropriate to their location
- Demo packages use relative imports within the package structure
- Test files are properly isolated in the `tests/` directory
- The `conftest.py` automatically sets up PYTHONPATH for pytest

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
# Output: The merged file will be created in the same directory as the source script,
# with '_advanced_merged.py' appended to the filename.
```

### Examples
```bash
# Merge the demo script
python scripts/advanced_merge.py examples/my_scripts.py examples
# Output: examples/my_scripts_advanced_merged.py

# Merge example showing smart renaming
python scripts/advanced_merge.py examples/example_smart_rename.py .
# Output: examples/example_smart_rename_advanced_merged.py

# Merge example with complex dependencies
python scripts/advanced_merge.py examples/example_complex_deps.py .
# Output: examples/example_complex_deps_advanced_merged.py
```

### Technical Implementation
- **AST-based parsing**: Uses Python's `ast` module for accurate code analysis
- **Global dependency graph**: Builds complete dependency relationships before merging
- **Symbol tracking**: Tracks all function definitions and their dependencies
- **Smart name mapping**: Creates unique names only when conflicts exist
- **Topological sorting**: Ensures correct function definition order using graph algorithms
  - Fixed algorithm to properly handle dependency chains
  - Reverses final order to ensure dependencies are defined first
  - **B4 Fix**: Ensures classes are always defined before their methods
- **Conflict detection**: Analyzes symbol frequency to determine renaming necessity
- **Import alias resolution**: Correctly handles `import X as Y` patterns
  - Maps aliases to their corresponding renamed functions
  - Preserves original alias relationships in merged code
  - **B2 Fix**: Adds `__mod` suffix to all import aliases to prevent runtime conflicts
- **Performance optimizations**:
  - **B1 Fix**: O(1) scope lookup using `defnode_to_scope` hash mapping
  - Efficient symbol resolution avoiding O(N²) complexity

## Demo Dependency Patterns

The demo packages showcase complex dependency scenarios that the merger tool handles:

### Cross-package Dependencies
```python
# examples/demo_packages/a_pkg/a.py
def global_same():     # Function with same name as in b_pkg
def hello():           # Calls global_same() internally  
def hello2():          # Also calls global_same() internally

# examples/demo_packages/b_pkg/b.py  
from ..a_pkg.a import hello2                    # Relative import
from ..a_pkg.a import global_same as global_same_a  # Relative import with alias
def global_same():     # Same name as in a_pkg (conflict!)
def b_hello():         # Calls hello2(), global_same(), global_same_a()

# examples/my_scripts.py
from demo_packages.a_pkg.a import hello     # Import from first package
from demo_packages.b_pkg.b import b_hello   # Import from second package
```

### How Advanced Merger Resolves This
```python
# Output: examples/my_scripts_advanced_merged.py
# From examples/demo_packages/a_pkg/a.py
def a_pkg_a_global_same():    # Only renamed due to conflict with b_pkg version
    print('Global same in a')

# From examples/demo_packages/a_pkg/a.py
def hello2():
    print('Hello World2')
    a_pkg_a_global_same()

# From examples/demo_packages/b_pkg/b.py
def b_pkg_b_global_same():    # Only renamed due to conflict with a_pkg version
    print('Global same in b')

# From examples/demo_packages/b_pkg/b.py
def b_hello():
    hello2()
    b_pkg_b_global_same()     # Calls its own global_same
    a_pkg_a_global_same()     # Calls aliased function correctly

# From examples/demo_packages/a_pkg/a.py
def hello():
    print('Hello World')
    a_pkg_a_global_same()

if __name__ == '__main__':
    hello()
    b_hello()
```

### Smart Renaming Examples
```python
# Output: examples/example_smart_rename_advanced_merged.py
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
# Output: examples/example_complex_deps_advanced_merged.py (correct order)
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


## Quality Assurance

### Static Analysis
The project uses a multi-stage AST auditor (`pysymphony.auditor.ASTAuditor`) that performs:
1. **Symbol Table Building**: Tracks all definitions and their scopes
2. **Reference Validation**: Ensures all references resolve correctly
3. **Pattern Checking**: Detects problematic patterns (e.g., multiple main blocks)
4. **Top-level Conflict Detection**: Identifies duplicate imports and definitions

### Continuous Integration
- All tests run automatically on GitHub Actions
- Static checks are mandatory and run on every test execution
- Both original and merged scripts are validated

## Development Environment

- **Language**: Python 3.8+ (uses standard library only for core functionality)
- **IDE**: IntelliJ IDEA/PyCharm (`.idea/` directory present)
- **Git**: Git repository with GitHub integration
- **Core Dependencies**: Uses only Python standard library (`ast`, `pathlib`, `typing`)
- **Dev Dependencies**: 
  - `pytest>=7.0.0` - Testing framework
  - `pyflakes>=3.0.0` - Fast static analysis
  - `flake8>=6.0,<7.0` - Backup static analysis

## Recent Improvements

### Issue #34: Core Stability Sprint
1. **B1 - Performance Optimization**: Fixed O(N²) scope lookup by implementing `defnode_to_scope` hash mapping
2. **B2 - Runtime Alias Conflicts**: Added `__mod` suffix to all import aliases to prevent conflicts with local definitions
3. **B3 - Attribute Reference Validation**: Enhanced `ReferenceValidator` to check attribute existence on objects
4. **B4 - Class-Method Topology**: Fixed topological sorting to ensure classes are always defined before their methods

### Issue #18: Industrial-Grade Testing System
1. **AST Auditor**: Implemented multi-stage static analysis system
2. **Test Architecture**: Created layered test structure (unit/integration/e2e)
3. **Antagonistic Testing**: Added tests that verify error detection
4. **pyflakes Integration**: Enhanced static checks with pyflakes API

### Issue #3: Core Functionality Fixes
1. **TypeError Fix**: Corrected `current_module_path` method call
2. **Nested Attribute Access**: Full support for deep attribute chains
3. **Scope Preservation**: Proper handling of nonlocal/global variables
4. **Import Mapping**: Enhanced resolution of imported symbols

### Other Improvements
- **Main Block Deduplication**: Fixed duplicate main block issue
- **Built-in Names**: Corrected recognition of Python built-ins
- **Import Conflict Detection**: Enhanced duplicate import detection

## Project Purpose

This project demonstrates advanced Python code analysis and merging techniques, specifically solving the problem of:
- **Flattening project structure**: Converting multi-file Python projects into single files
- **Dependency resolution**: Finding and including all required code automatically  
- **Import alias handling**: Preserving complex import relationships
- **Conflict resolution**: Avoiding naming conflicts between modules
- **Code minimization**: Including only actually used functions
- **Maintainability**: Preserving source information for debugging