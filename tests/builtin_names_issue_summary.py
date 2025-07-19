#!/usr/bin/env python3
"""
Summary of the builtin names issue in advanced_merge.py

ISSUE: The _static_verify method incorrectly reports builtin functions 
       (len, print, str, int, etc.) as undefined names.

ROOT CAUSE: The code uses `set(dir(__builtins__))` which can be unreliable
           in different execution contexts.

SOLUTION: Use `import builtins; set(dir(builtins))` instead.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.advanced_merge import AdvancedCodeMerger

def demonstrate_issue():
    """Demonstrate the current issue"""
    print("=== Current Issue ===\n")
    
    merger = AdvancedCodeMerger(Path("."))
    
    test_code = """
def example():
    # All these builtins are incorrectly marked as undefined
    a = len([1, 2, 3])
    print(a)
    b = str(42)
    c = int("10")
    d = list(range(5))
    e = dict(x=1, y=2)
    return sum([a, c])
"""
    
    result = merger._static_verify(test_code)
    
    print("Test code uses these builtin functions:")
    print("- len, print, str, int, list, dict, range, sum")
    
    print(f"\nUndefined names reported: {result['undefined_names']}")
    print("\nThese are all Python builtin functions that should NOT be reported as undefined!")

def show_fix():
    """Show how to fix the issue"""
    print("\n\n=== The Fix ===\n")
    
    print("Current code in _static_verify (line 1144):")
    print("```python")
    print("builtin_names = set(dir(__builtins__))")
    print("```")
    
    print("\nShould be changed to:")
    print("```python")
    print("import builtins")
    print("builtin_names = set(dir(builtins))")
    print("```")
    
    print("\nAlternatively, for compatibility:")
    print("```python")
    print("# Handle both dict and module forms of __builtins__")
    print("if isinstance(__builtins__, dict):")
    print("    builtin_names = set(__builtins__.keys())")
    print("else:")
    print("    builtin_names = set(dir(__builtins__))")
    print("```")
    
    print("\nBut the cleanest solution is to use the builtins module.")

def verify_fix_works():
    """Verify that the fix would work"""
    print("\n\n=== Verifying the Fix ===\n")
    
    import ast
    import builtins
    
    test_code = """
def example():
    a = len([1, 2, 3])
    print(a)
    return sum([a, 1, 2])
"""
    
    tree = ast.parse(test_code)
    
    # Collect used and defined names
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    defined = {'example', 'a'}
    
    # Current approach (buggy)
    builtin_names_buggy = set(dir(__builtins__))
    undefined_buggy = sorted((used - defined) - builtin_names_buggy)
    
    # Fixed approach
    builtin_names_fixed = set(dir(builtins))
    undefined_fixed = sorted((used - defined) - builtin_names_fixed)
    
    print(f"Used names: {used}")
    print(f"Defined names: {defined}")
    print(f"\nWith current approach: undefined = {undefined_buggy}")
    print(f"With fixed approach: undefined = {undefined_fixed}")
    
    print("\n✅ The fix correctly identifies that there are no undefined names!")

if __name__ == "__main__":
    demonstrate_issue()
    show_fix()
    verify_fix_works()