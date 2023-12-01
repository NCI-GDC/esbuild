import logging
from typing import Optional

from logging import WARNING, ERROR, INFO, DEBUG, getLogger

import ddtrace

FORMAT = (
    "%(asctime)s %(levelname)s [%(name)s] [%(filename)s:%(lineno)d] "
    "[dd.service=%(dd.service)s dd.env=%(dd.env)s dd.version=%(dd.version)s dd.trace_id=%(dd.trace_id)s dd.span_id=%(dd.span_id)s] "
    "- %(message)s"
)

Level = int


def init_logging(
    level: Level = logging.WARNING, filename: Optional[str] = None
) -> logging.Logger:
    ddtrace.patch(logging=True)
    logging.basicConfig(format=FORMAT, level=level)

    logger = logging.getLogger()

    if filename:
        handler = logging.FileHandler(filename, mode="a+")

        logger.addHandler(handler)

    return logger
