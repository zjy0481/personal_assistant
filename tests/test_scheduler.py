from assistant.config import Settings
from assistant.scheduler import create_scheduler


def test_scheduler_can_start_and_shutdown_cleanly() -> None:
    scheduler = create_scheduler(
        Settings(location="上海", timezone="Asia/Shanghai")
    )

    scheduler.start()

    assert scheduler.running

    scheduler.shutdown(wait=False)

    assert not scheduler.running
