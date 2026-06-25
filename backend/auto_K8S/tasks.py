from celery import shared_task

from .services import execute_installation


@shared_task
def run_installation_task(installation_id):
    return execute_installation(installation_id)


@shared_task
def debug_task():
    print("debug task executed")
    return "ok"
