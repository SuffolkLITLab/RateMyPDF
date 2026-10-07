"""Exercise the web/RQ boundary without paid APIs or the ML model downloads."""
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
formfyxer = ModuleType("formfyxer")
formfyxer.lit_explorer = ModuleType("lit_explorer")
formfyxer.parse_form = Mock()
formfyxer.auto_add_fields = Mock()
sys.modules["formfyxer"] = formfyxer


@pytest.fixture
def web(monkeypatch, tmp_path):
    monkeypatch.chdir(ROOT / "app")
    import main
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(main.queue, "enqueue", Mock())
    return main, TestClient(main.app)
