import os
import re
from logging.config import dictConfig
from logging import Filter, LogRecord


class IgnoreStaticFilter(Filter):
    """Filters out access log records for static files."""
    def filter(self, record: LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        # drop records that reference /static/ assets
        return '/static/' not in msg


class StripWerkzeugInnerTimestampFilter(Filter):
    """Strip embedded werkzeug access-log timestamps like '[09/Dec/2025 23:15:29]'."""
    _INNER_TS_RE = re.compile(r"\[\d{2}/[A-Za-z]{3}/\d{4} \d{2}:\d{2}:\d{2}\]")

    def filter(self, record: LogRecord) -> bool:
        try:
            # Mutate the message to remove embedded timestamps from werkzeug
            if isinstance(record.msg, str):
                record.msg = self._INNER_TS_RE.sub('', record.msg).strip()
        except Exception:
            pass
        return True




class StripAnsiColorsFilter(Filter):
    """Strip ANSI escape codes (colors) from log messages."""
    _ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

    def filter(self, record: LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = self._ANSI_RE.sub('', record.msg)
        except Exception:
            pass
        return True


DEFAULT_LOG_FILE = os.path.join('logs', 'openpath.log')

DEFAULT_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '[%(asctime)s] %(levelname)s: %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S'
        }
    },
    'handlers': {
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'level': 'INFO',
            'formatter': 'standard',
            'filename': DEFAULT_LOG_FILE,
            'mode': 'a',
            'maxBytes': 51200,
            'backupCount': 10,
            'encoding': 'utf8'
        },
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'INFO',
            'formatter': 'standard',
            'stream': 'ext://sys.stdout'
        }
    },
    'root': {
        'level': 'INFO',
        'handlers': ['file', 'console']
    },
    'loggers': {
        'werkzeug': {
            'level': 'INFO',
            'handlers': ['file', 'console'],
            'propagate': False
        }
    }
}


def ensure_log_dir(path: str):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def configure_logging(log_file: str | None = None, console: bool = True):
    """Configure logging for the project using a single canonical dictConfig.

    Args:
        log_file: optional path to log file. If not provided, uses DEFAULT_LOG_FILE.
        console: whether to attach a console handler.
    """
    lf = log_file or DEFAULT_LOG_FILE
    ensure_log_dir(lf)
    cfg = DEFAULT_CONFIG.copy()
    # update filenames in handlers
    cfg['handlers'] = {k: v.copy() for k, v in DEFAULT_CONFIG['handlers'].items()}
    cfg['handlers']['file']['filename'] = lf
    # add filters to handlers to strip inner werkzeug timestamps and ignore static
    cfg['filters'] = {
        'ignore_static': {
            '()': 'app.logging_config.IgnoreStaticFilter'
        },
        'strip_werkzeug_ts': {
            '()': 'app.logging_config.StripWerkzeugInnerTimestampFilter'
        },
        'strip_ansi': {
            '()': 'app.logging_config.StripAnsiColorsFilter'
        }
    }
    # attach filters to file and console handlers
    cfg['handlers']['file'].setdefault('filters', []).extend(['strip_werkzeug_ts', 'ignore_static', 'strip_ansi'])
    if 'console' in cfg['handlers']:
        cfg['handlers']['console'].setdefault('filters', []).extend(['strip_werkzeug_ts', 'ignore_static', 'strip_ansi'])
    if not console:
        # remove console handler from root and werkzeug
        cfg['handlers'].pop('console', None)
        cfg['root']['handlers'] = ['file']
        if 'werkzeug' in cfg['loggers']:
            cfg['loggers']['werkzeug']['handlers'] = ['file']
    dictConfig(cfg)
