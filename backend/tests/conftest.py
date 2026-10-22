import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import create_app
from app.services.loader import PacketIndex, load_packet
from app.services.refs import RefResolver


@pytest.fixture(scope="session")
def staged_dir(tmp_path_factory) -> object:
    return tmp_path_factory.mktemp("data")


@pytest.fixture(scope="session")
def idx(staged_dir) -> PacketIndex:
    return load_packet(config.PACKET_SOURCE, staged_dir)


@pytest.fixture(scope="session")
def resolver(idx) -> RefResolver:
    return RefResolver(idx)


@pytest.fixture(scope="session")
def client(idx, tmp_path_factory):
    no_frontend = tmp_path_factory.mktemp("nofrontend")
    db = tmp_path_factory.mktemp("events") / "events.sqlite"
    with TestClient(create_app(idx, frontend_dist=no_frontend, events_db=db)) as c:
        yield c


@pytest.fixture()
def fresh(idx, tmp_path):
    """An app with an empty event store, for tests that write review state."""
    db = tmp_path / "events.sqlite"
    with TestClient(create_app(idx, frontend_dist=tmp_path / "nofrontend", events_db=db)) as c:
        c.db_path = db
        yield c
