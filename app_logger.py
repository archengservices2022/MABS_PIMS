"""Centralised logging configuration for PIMS / ArchInvoiceGenerator."""
import logging
import logging.handlers
from pathlib import Path


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configure root logger with rotating file + console handlers."""
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(exist_ok=True)

    level = getattr(logging, log_level.upper(), logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    if not root.handlers:
        # Rotating file: 5 MB per file, keep 3 backups
        fh = logging.handlers.RotatingFileHandler(
            log_dir / "pims.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        fh.delay = False  # open file immediately
        root.addHandler(fh)
        # Flush after every record so a hard crash never loses entries
        root.addHandler(type('FlushHandler', (logging.Handler,), {
            'emit': lambda self, record: [h.flush() for h in root.handlers]
        })())

        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        root.addHandler(ch)

    return logging.getLogger("pims")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"pims.{name}")
