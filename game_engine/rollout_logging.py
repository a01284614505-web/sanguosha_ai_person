"""Keep in-memory rollouts out of real logs without muting concurrent games."""
from contextvars import ContextVar
import logging

silent = ContextVar('silent_rollout', default=False)


class RolloutLogger:
    def __init__(self, name):
        self.logger = logging.getLogger(name)

    def info(self, *args, **kwargs):
        if not silent.get():
            self.logger.info(*args, **kwargs)

    def warning(self, *args, **kwargs):
        if not silent.get():
            self.logger.warning(*args, **kwargs)
