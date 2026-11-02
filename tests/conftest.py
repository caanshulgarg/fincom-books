"""Shared test resources; product data is never used by pytest fixtures."""
from pathlib import Path

import pytest


@pytest.fixture
def books_db(tmp_path):
    from books import Books

    db = Books(str(tmp_path / 'books.sqlite3'))
    try:
        yield db
    finally:
        db.connection.close()


@pytest.fixture
def application_root():
    return Path(__file__).parents[1]


@pytest.fixture(autouse=True)
def no_network_update_check(monkeypatch):
    """Tests never reach the internet; a live update check pops a dialog that steals keyboard focus."""
    import app_server
    monkeypatch.setattr(app_server, '_fetch_remote_version', lambda: None)
