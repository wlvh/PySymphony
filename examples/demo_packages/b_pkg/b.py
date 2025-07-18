from ..a_pkg.a import hello2
from ..a_pkg.a import global_same as global_same_a


def global_same():
    print("Global same in b")


def b_hello():
    hello2()
    global_same()
    global_same_a()
