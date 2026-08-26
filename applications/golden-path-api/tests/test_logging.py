import json
import logging

from golden_path_api.logging_config import JsonFormatter, configure_logging


def test_application_and_uvicorn_logs_use_json() -> None:
    configure_logging("INFO")
    formatter = logging.getLogger("uvicorn.error").handlers[0].formatter
    assert isinstance(formatter, JsonFormatter)
    record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, "ready", (), None)
    assert json.loads(formatter.format(record))["message"] == "ready"
