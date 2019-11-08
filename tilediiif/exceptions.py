import sys


class CommandError(SystemExit):
    def __init__(self, message=None, code=1, prefix="Error: "):
        super().__init__(code)
        self.prefix = prefix
        self.message = message

    def has_message(self):
        return bool(self.message)

    def __str__(self):
        if self.has_message():
            return f"{self.prefix}{self.message}"

    def do_exit(self):
        if self.has_message():
            print(self, file=sys.stderr)
        sys.exit(self.code)
