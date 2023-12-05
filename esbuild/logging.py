import logging
import os
import platform
from logging import handlers
from typing import Any

from pythonjsonlogger import jsonlogger

DEBUG = logging.DEBUG
INFO = logging.INFO


class DatadogLogFormatter(jsonlogger.JsonFormatter):
    def __init__(self) -> None:
        super().__init__(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={
                "levelname": "level",
                "asctime": "timestamp",
                "name": "logger.name",
            },
        )

    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)

        if record.exc_info:
            exc_type, exception, _ = record.exc_info
            log_record["error.stack"] = log_record.pop("exc_info", None)

            if exc_type:
                log_record[
                    "error.kind"
                ] = f"{exc_type.__module__}.{exc_type.__qualname__}"
            if exception:
                log_record["error.message"] = f"{exception}"

        log_record["host"] = platform.node()


def init_logging(level: int) -> logging.Logger:
    log_handler = handlers.WatchedFileHandler(os.environ["DD_LOG_FILE"], mode="a+")

    log_handler.setFormatter(DatadogLogFormatter())
    logging.basicConfig(handlers=(log_handler,), level=level, force=True)

    return logging.getLogger()
