from ingest.handler import handler


def test_stub_handler_returns_ok() -> None:
    assert handler({}, object())["status"] == "ok"
