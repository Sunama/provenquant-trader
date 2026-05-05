from celery import Celery

celery_app = Celery("trader")
celery_app.config_from_object("app.core.celery_config")

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Bangkok",
    enable_utc=True,
)
