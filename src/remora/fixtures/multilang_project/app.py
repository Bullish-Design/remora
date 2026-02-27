from dataclasses import dataclass


@dataclass
class Settings:
    retries: int
    endpoint: str


class Client:
    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def ping(self) -> bool:
        return True


def load_settings(path: str) -> Settings:
    return Settings(retries=3, endpoint=path)
