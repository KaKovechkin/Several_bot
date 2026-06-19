import logging
import sys


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure root logging once and return the app logger."""
    logging.basicConfig(
        level=level,
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    # aiogram is chatty on INFO for every update; keep it at WARNING
    logging.getLogger('aiogram.event').setLevel(logging.WARNING)
    return logging.getLogger('dialogspy')


logger = logging.getLogger('dialogspy')
