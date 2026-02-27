from functools import lru_cache

from .models import User
from .repository import UserRepository


def audit(event: str) -> None:
    print(event)


class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self.repo = repo

    @lru_cache(maxsize=128)
    def get_user(self, user_id: int) -> User | None:
        return self.repo.get(user_id)

    @staticmethod
    def normalize_name(name: str) -> str:
        return name.strip().lower()
