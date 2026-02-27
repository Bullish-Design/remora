from .models import User


class BaseRepository:
    def save(self, user: User) -> None:
        raise NotImplementedError


class UserRepository(BaseRepository):
    def __init__(self) -> None:
        self._cache: dict[int, User] = {}

    def save(self, user: User) -> None:
        self._cache[user.id] = user

    def get(self, user_id: int) -> User | None:
        return self._cache.get(user_id)
