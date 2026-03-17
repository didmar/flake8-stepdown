RETRIES = 3


def main():
    fetch()


def fetch():
    for i in range(RETRIES):
        helper()


def helper():
    pass
