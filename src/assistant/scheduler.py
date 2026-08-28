"""Background scheduler factory."""

from apscheduler.schedulers.background import BackgroundScheduler

from assistant.config import Settings


def create_scheduler(settings: Settings) -> BackgroundScheduler:
    """Create a scheduler configured for the selected timezone."""

    return BackgroundScheduler(timezone=settings.timezone)
