
def global_same():
    print("Global same in a")

def hello():
    print("Hello World")
    global_same()

def hello2():
    print("Hello World2")
    global_same()