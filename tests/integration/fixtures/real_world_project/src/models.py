from dataclasses import dataclass


@dataclass
class User:
    id: int
    name: str


class Admin(User):
    def can_manage(self) -> bool:
        return True
