import logging
from logstash_async import handler

HOST = "logstash7.service.consul"
PORT = 5044

logger = logging.getLogger("esbuild")

logger.setLevel(logging.INFO)
logger.addHandler(handler.AsynchronousLogstashHandler(HOST, PORT))
