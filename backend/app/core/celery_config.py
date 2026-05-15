from app.core.settings import settings
from celery.schedules import crontab
from kombu import Queue

broker_url = settings.CELERY_BROKER_URL
result_backend = settings.REDIS_URL

beat_schedule = {
    # Flush Redis tick buffers → Postgres every minute
    "trader.data_collector_polling": {
        "task": "trader.data_collector_polling",
        "schedule": crontab(minute="*"),
    },
}

imports = [
    "app.tasks.data_collector",
    "app.tasks.strategy",
]

task_default_queue = "trader_default"
task_queues = (
    Queue("trader_default", queue_arguments={"x-max-priority": 0}),
    Queue("trader_strategy", queue_arguments={"x-max-priority": 3}),
)

task_routes = {
    "app.tasks.strategy.*": {"queue": "trader_strategy"},
    "app.tasks.data_collector.*": {"queue": "trader_default"},
}
