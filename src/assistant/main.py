"""Application entry point."""

from assistant.app import create_app
from assistant.config import load_settings

app = create_app(load_settings())
