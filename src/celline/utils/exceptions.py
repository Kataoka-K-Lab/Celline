class NullPointException(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(f"Null point exception\n{message}")


class RSessionNotFoundException(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(f"Target R session could not found: {message}")


class RException(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)
