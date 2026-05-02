import sys
import os
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, 'frozen', False)


def _internal_dir() -> Path:
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def get_app_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_bundled_resource(relative_path: str) -> Path:
    return _internal_dir() / relative_path


def get_app_data_path() -> Path:
    if is_frozen():
        app_data = Path(os.environ.get('APPDATA', os.path.expanduser('~')))
        app_dir = app_data / "PersonalWindowGLM"
        app_dir.mkdir(parents=True, exist_ok=True)
        return app_dir
    return Path(__file__).resolve().parent
