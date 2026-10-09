import logging
import sys
from config import LOG_DIR


def setup_logging(level: int = logging.INFO):
    fmt = "%(asctime)s | %(name)-12s | %(levelname)-7s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(fmt, datefmt))
    root.addHandler(console)

    fh = logging.FileHandler(LOG_DIR / "bot.log")
    fh.setFormatter(logging.Formatter(fmt, datefmt))
    root.addHandler(fh)

    th = logging.FileHandler(LOG_DIR / "trades.log")
    th.setFormatter(logging.Formatter(fmt, datefmt))
    logging.getLogger("trades").addHandler(th)

    logging.info("Logging initialized → %s", LOG_DIR / "bot.log")
