import pytest

MOD = "qibo_client.config_logging"


def logging_wrap_function(logger_object):
    logger_object.debug("A debug log")
    logger_object.info("An info log")
    logger_object.error("An error log")


@pytest.mark.parametrize(
    "loglevel,expected_messages",
    [
        ("DEBUG", ["A debug log", "An info log", "An error log"]),
        ("INFO", ["An info log", "An error log"]),
        ("ERROR", ["An error log"]),
    ],
)
def test_logger_levels(monkeypatch, caplog, loglevel, expected_messages):
    monkeypatch.setenv("QIBO_CLIENT_LOGGER_LEVEL", loglevel)
    caplog.set_level(loglevel)

    from qibo_client.config_logging import logger

    logging_wrap_function(logger)

    assert caplog.messages == expected_messages
