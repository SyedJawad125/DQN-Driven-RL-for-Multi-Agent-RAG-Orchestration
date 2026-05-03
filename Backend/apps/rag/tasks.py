"""
Celery tasks for async operations + n8n webhook integration.
"""
import logging
import requests
from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def notify_n8n(self, payload: dict) -> bool:
    """
    POST event data to n8n webhook.
    n8n then routes it: Slack alert / email / retrain trigger / dashboard update.
    """
    webhook_url = getattr(settings, "N8N_WEBHOOK_URL", None)
    if not webhook_url:
        return False

    try:
        headers = {
            "Content-Type": "application/json",
            "X-Secret": getattr(settings, "N8N_SECRET", ""),
        }
        response = requests.post(webhook_url, json=payload, headers=headers, timeout=5)
        response.raise_for_status()
        logger.info(f"[n8n] Event '{payload.get('event')}' sent ✓")
        return True

    except Exception as exc:
        logger.error(f"[n8n] Webhook failed: {exc}")
        raise self.retry(exc=exc)


@shared_task
def trigger_rl_retrain(batch_size: int = 64) -> dict:
    """
    Periodic RL replay training triggered by Celery Beat or n8n.
    """
    from apps.rag.services.agents.rl_agent import RLDecisionAgent
    agent = RLDecisionAgent()
    result = agent.run_replay(batch_size=batch_size)
    logger.info(f"[RL Retrain] Completed: {result}")
    notify_n8n.delay({
        "event": "rl_retrained",
        "batch_size": batch_size,
        **result,
    })
    return result


@shared_task
def send_daily_report() -> None:
    """
    Send daily stats report to n8n → Slack/Email.
    Schedule in Celery Beat.
    """
    from apps.rag.models import Query, Document
    from django.utils import timezone
    from datetime import timedelta
    from django.db.models import Avg, Count

    yesterday = timezone.now() - timedelta(days=1)
    stats = Query.objects.filter(created_at__gte=yesterday).aggregate(
        total=Count("id"),
        avg_confidence=Avg("confidence_score"),
        avg_time=Avg("processing_time"),
    )

    notify_n8n.delay({
        "event": "daily_report",
        "date": yesterday.strftime("%Y-%m-%d"),
        "total_queries": stats["total"] or 0,
        "avg_confidence": round(stats["avg_confidence"] or 0, 3),
        "avg_processing_time": round(stats["avg_time"] or 0, 2),
        "total_documents": Document.objects.count(),
    })