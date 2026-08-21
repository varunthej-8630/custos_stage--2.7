import logging
import logging.handlers
import os
import sys

# Force UTF-8 encoding on Windows standard output to eliminate UnicodeEncodeError
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')

def setup_logger(name, log_file, level=logging.INFO):
    """Configures thread-safe, UTF-8 structured loggers with rotating file handlers."""
    os.makedirs(LOG_DIR, exist_ok=True)
    file_path = os.path.join(LOG_DIR, log_file)
    
    formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-7s | %(name)-10s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # UTF-8 Rotating File Handler (10MB max, 30 backups)
    handler = logging.handlers.RotatingFileHandler(
        file_path, maxBytes=10*1024*1024, backupCount=30, encoding='utf-8'
    )
    handler.setFormatter(formatter)

    # UTF-8 Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    if not logger.handlers:
        logger.addHandler(handler)
        logger.addHandler(console_handler)
        
    return logger

# Global Application Loggers
app_logger = setup_logger('App', 'app.log')
alert_logger = setup_logger('Alerts', 'alerts.log')
detector_logger = setup_logger('Detector', 'detector.log')
tracker_logger = setup_logger('Tracker', 'tracker.log')
error_logger = setup_logger('Error', 'errors.log', level=logging.ERROR)

def get_camera_logger(camera_index):
    return setup_logger(f'Camera-{camera_index}', 'app.log')
