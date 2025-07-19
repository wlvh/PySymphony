#!/usr/bin/env python3
"""
Debug script to test __builtins__ behavior in exec context
"""

import ast

def test_builtin_detection():
    """Test different ways of getting builtin names"""
    
    print("=== Testing Builtin Detection Methods ===\n")
    
    # Method 1: Direct dir(__builtins__)
    print("1. Direct dir(__builtins__):")
    try:
        builtin_names_1 = set(dir(__builtins__))
        print(f"   Success: {len(builtin_names_1)} names")
        print(f"   Has 'len': {'len' in builtin_names_1}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Method 2: Using builtins module
    print("\n2. Using builtins module:")
    try:
        import builtins
        builtin_names_2 = set(dir(builtins))
        print(f"   Success: {len(builtin_names_2)} names")
        print(f"   Has 'len': {'len' in builtin_names_2}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Method 3: Check if __builtins__ is dict or module
    print("\n3. Smart detection based on type:")
    try:
        if isinstance(__builtins__, dict):
            builtin_names_3 = set(__builtins__.keys())
        else:
            builtin_names_3 = set(dir(__builtins__))
        print(f"   Success: {len(builtin_names_3)} names")
        print(f"   Has 'len': {'len' in builtin_names_3}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Method 4: Try to get from globals
    print("\n4. From globals()['__builtins__']:")
    try:
        gb = globals()['__builtins__']
        if isinstance(gb, dict):
            builtin_names_4 = set(gb.keys())
        else:
            builtin_names_4 = set(dir(gb))
        print(f"   Success: {len(builtin_names_4)} names")
        print(f"   Has 'len': {'len' in builtin_names_4}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Test in exec context
    print("\n5. Testing in exec context:")
    code = """
if isinstance(__builtins__, dict):
    builtin_names = set(__builtins__.keys())
else:
    builtin_names = set(dir(__builtins__))
print(f"   In exec - type: {type(__builtins__)}")
print(f"   In exec - count: {len(builtin_names)}")
print(f"   In exec - has 'len': {'len' in builtin_names}")
"""
    exec(code)
    
    # Most robust method
    print("\n6. Most robust method (use builtins module):")
    import builtins
    builtin_names_robust = set(dir(builtins))
    print(f"   Count: {len(builtin_names_robust)}")
    print(f"   Sample names: {sorted(list(builtin_names_robust))[:10]}")
    
    # Test the logic that would work in _static_verify
    print("\n7. Testing fixed logic for _static_verify:")
    test_code = """
def test():
    x = len([1, 2, 3])
    print(x)
"""
    
    tree = ast.parse(test_code)
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    defined = {'test', 'x'}
    
    # Use the robust method
    import builtins
    builtin_names = set(dir(builtins))
    undefined = sorted((used - defined) - builtin_names)
    
    print(f"   Used: {used}")
    print(f"   Defined: {defined}")
    print(f"   Undefined (with fix): {undefined}")

if __name__ == "__main__":
    test_builtin_detection()