#!/usr/bin/env python3
"""
Debug script to investigate builtin names recognition issue in advanced_merge.py
"""

import sys
from pathlib import Path

# Add the parent directory to the path so we can import from scripts
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.advanced_merge import AdvancedCodeMerger

def debug_builtin_names():
    """Debug the builtin names recognition"""
    
    print("=== Debugging Builtin Names ===\n")
    
    # Check what's in __builtins__
    print("1. Checking __builtins__ directly:")
    builtin_names = set(dir(__builtins__))
    print(f"   Total builtin names: {len(builtin_names)}")
    print(f"   'len' in builtins: {'len' in builtin_names}")
    print(f"   'print' in builtins: {'print' in builtin_names}")
    print(f"   'str' in builtins: {'str' in builtin_names}")
    print(f"   'int' in builtins: {'int' in builtin_names}")
    
    # Show first 10 builtin names
    print(f"\n   First 10 builtin names: {sorted(builtin_names)[:10]}")
    
    # Test with a simple code snippet
    print("\n2. Testing _static_verify method:")
    merger = AdvancedCodeMerger(Path("."))
    
    test_code = """
def test_function():
    # Using builtin functions
    x = len([1, 2, 3])
    print(x)
    y = str(42)
    z = int("10")
    return x + z
"""
    
    result = merger._static_verify(test_code)
    
    print(f"\n   Undefined names found: {result['undefined_names']}")
    print(f"   Duplicate imports: {result['duplicate_imports']}")
    print(f"   Syntax errors: {result['syntax_error']}")
    
    # Test with undefined names
    print("\n3. Testing with actual undefined names:")
    test_code_with_undefined = """
def test_function():
    x = len([1, 2, 3])
    y = undefined_variable  # This should be caught
    z = another_undefined   # This too
    return x + y + z
"""
    
    result2 = merger._static_verify(test_code_with_undefined)
    print(f"\n   Undefined names found: {result2['undefined_names']}")
    
    # Check if __builtins__ behaves differently in different contexts
    print("\n4. Checking __builtins__ type:")
    print(f"   Type of __builtins__: {type(__builtins__)}")
    if hasattr(__builtins__, '__dict__'):
        print("   __builtins__ is a module")
        builtin_names_from_module = set(dir(__builtins__))
        print(f"   Names from module: {len(builtin_names_from_module)}")
    else:
        print("   __builtins__ is a dict")
        builtin_names_from_dict = set(__builtins__.keys())
        print(f"   Names from dict: {len(builtin_names_from_dict)}")

if __name__ == "__main__":
    debug_builtin_names()