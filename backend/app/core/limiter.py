from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.settings import settings

# Uses Redis as storage so limits survive process restarts and work across workers
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL,
)
