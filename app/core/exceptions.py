class SafeError(Exception):
    def __init__(self, code="OFFLINE", http_status=None):
        self.code = code
        self.http_status = http_status
        super().__init__(code)
