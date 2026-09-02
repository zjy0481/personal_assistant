"""Application entry point."""

from pathlib import Path

from assistant.app import create_app
from assistant.config import load_settings
from assistant.storage import SnapshotStore

app = create_app(
    load_settings(),
    store=SnapshotStore(Path("data/assistant.db")),
    frontend_dir=Path(__file__).resolve().parents[2] / "web" / "dist",
)