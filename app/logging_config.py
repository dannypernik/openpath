import os
from logging.config import dictConfig

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
    if not console:
        # remove console handler from root and werkzeug
        cfg['handlers'].pop('console', None)
        cfg['root']['handlers'] = ['file']
        if 'werkzeug' in cfg['loggers']:
            cfg['loggers']['werkzeug']['handlers'] = ['file']
    dictConfig(cfg)
