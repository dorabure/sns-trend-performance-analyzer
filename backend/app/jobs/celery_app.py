import os
from celery import Celery

app = Celery('sns_jobs', broker=os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0'), include=['app.jobs.tasks'])
app.conf.update(
    task_ignore_result=True, result_backend=None,
    task_serializer='json', result_serializer='json', accept_content=['json'],
    task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
    worker_cancel_long_running_tasks_on_connection_loss=True,
    broker_connection_retry_on_startup=True, broker_connection_timeout=3,
    broker_transport_options={'visibility_timeout': 3600, 'socket_connect_timeout': 3, 'socket_timeout': 3},
    task_publish_retry=False, task_send_sent_event=False, worker_send_task_events=False,
    worker_log_color=False, worker_redirect_stdouts=False,
    beat_schedule={'scheduler-tick': {'task': 'sns.scheduler_tick',
                                     'schedule': max(1, int(os.getenv('SCHEDULER_TICK_SECONDS', '30')))}},
)
