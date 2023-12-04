from typing import Optional

import ddtrace

ddtrace.patch(logging=True)

import logging
from logging import DEBUG, ERROR, INFO, WARNING, getLogger


FORMAT = (
    "%(asctime)s %(levelname)s [%(name)s] [%(filename)s:%(lineno)d] "
    "[dd.service=%(dd.service)s dd.env=%(dd.env)s dd.version=%(dd.version)s dd.trace_id=%(dd.trace_id)s dd.span_id=%(dd.span_id)s] "
    "- %(message)s"
)

Level = int


def init_logging(
    level: Level = logging.WARNING, filename: Optional[str] = None
) -> logging.Logger:
    logging.basicConfig(format=FORMAT, level=level)

    logger = logging.getLogger()

    if filename:
        handler = logging.FileHandler(filename, mode="a+")

        logger.addHandler(handler)

    return logger
