RETRIES = 3
"""Number of retries before giving up."""


TIMEOUT = 30
"""Request timeout in seconds."""


def main():
    fetch()


def fetch():
    for i in range(RETRIES):
        helper()


def helper():
    pass
