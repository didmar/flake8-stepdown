RETRIES = 3
"""Number of retries before giving up."""


TIMEOUT = 30
"""Request timeout in seconds."""


def helper():
    pass


def fetch():
    for i in range(RETRIES):
        helper()


def main():
    fetch()
