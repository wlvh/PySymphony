# From a_pkg/a.py
def a_pkg_a_global_same():
    print('Global same in a')

# From b_pkg/b.py
def b_pkg_b_global_same():
    print('Global same in b')

# From a_pkg/a.py
def hello2():
    print('Hello World2')
    a_pkg_a_global_same()

# From a_pkg/a.py
def hello():
    print('Hello World')
    a_pkg_a_global_same()

# From b_pkg/b.py
def b_hello():
    hello2()
    b_pkg_b_global_same()
    a_pkg_a_global_same()

if __name__ == '__main__':
    hello()
    b_hello()