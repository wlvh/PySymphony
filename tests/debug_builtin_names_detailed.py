#!/usr/bin/env python3
"""
More detailed debug script to investigate the builtin names issue
"""

import ast
import sys
from pathlib import Path

# Test the exact code that's in _static_verify
def test_static_verify_logic():
    """Test the exact logic used in _static_verify"""
    
    test_code = """
def test_function():
    x = len([1, 2, 3])
    print(x)
    return x
"""
    
    print("=== Testing Static Verify Logic ===\n")
    
    # Parse the code
    tree = ast.parse(test_code)
    
    # Collect all defined names (same logic as _static_verify)
    defined = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            defined.add(n.name)
        elif isinstance(n, ast.Assign):
            # Using simplified logic for now
            for target in n.targets:
                if isinstance(target, ast.Name):
                    defined.add(target.id)
    
    print(f"1. Defined names: {defined}")
    
    # Collect all used names
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    print(f"2. Used names: {used}")
    
    # Check builtin names
    print("\n3. Checking builtin names:")
    builtin_names = set(dir(__builtins__))
    print(f"   Type of __builtins__: {type(__builtins__)}")
    print(f"   Number of builtin names: {len(builtin_names)}")
    print(f"   'len' in builtin_names: {'len' in builtin_names}")
    print(f"   'print' in builtin_names: {'print' in builtin_names}")
    
    # Calculate undefined
    undefined = (used - defined) - builtin_names
    print(f"\n4. Calculation:")
    print(f"   used - defined = {used - defined}")
    print(f"   (used - defined) - builtin_names = {undefined}")
    
    # Let's also check what happens inside a method
    print("\n5. Testing inside a class method (simulating _static_verify):")
    
    class TestClass:
        def method(self):
            # Same logic
            builtin_names_in_method = set(dir(__builtins__))
            print(f"   In method - type of __builtins__: {type(__builtins__)}")
            print(f"   In method - number of names: {len(builtin_names_in_method)}")
            print(f"   In method - 'len' present: {'len' in builtin_names_in_method}")
            
            # Try the calculation
            undefined_in_method = (used - defined) - builtin_names_in_method
            print(f"   In method - undefined: {undefined_in_method}")
            
            return builtin_names_in_method
    
    tc = TestClass()
    method_builtins = tc.method()
    
    # Compare the sets
    print(f"\n6. Comparing builtin sets:")
    print(f"   Same sets? {builtin_names == method_builtins}")
    print(f"   Difference: {builtin_names - method_builtins}")

def check_builtins_in_different_contexts():
    """Check how __builtins__ behaves in different contexts"""
    
    print("\n\n=== Checking __builtins__ in Different Contexts ===\n")
    
    # Global context
    print("1. Global context:")
    print(f"   Type: {type(__builtins__)}")
    if hasattr(__builtins__, '__dict__'):
        print(f"   Has __dict__: True")
        print(f"   Keys in __dict__: {len(__builtins__.__dict__)}")
    
    # Inside a function
    def inside_function():
        print("\n2. Inside a function:")
        print(f"   Type: {type(__builtins__)}")
        return __builtins__
    
    func_builtins = inside_function()
    
    # Inside exec
    print("\n3. Inside exec:")
    exec_globals = {}
    exec("print(f'   Type: {type(__builtins__)}')", exec_globals)
    exec("print(f'   Dir length: {len(dir(__builtins__))}')", exec_globals)

if __name__ == "__main__":
    test_static_verify_logic()
    check_builtins_in_different_contexts()