import os
from dotenv import load_dotenv

load_dotenv()

broker_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
result_backend = os.getenv("REDIS_URL", "redis://localhost:6379/0")

task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]
timezone = "UTC"
enable_utc = True

# Schedule Celery Beat tasks
beat_schedule = {
    "run-market-update-every-15-min": {
        "task": "market.tasks.run_market_update",
        "schedule": 900.0,  # 15 minutes in seconds
    },
}
