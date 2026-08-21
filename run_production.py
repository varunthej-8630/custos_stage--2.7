# run_production.py — CUSTOS Production Server for Windows
import os

from web.server import app, socket, camera_manager
from config import settings as config
from engine.logger import app_logger

def main():
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 5000))
    
    os.makedirs(os.path.join(os.path.dirname(__file__), 'frontend'), exist_ok=True)
    os.makedirs(config.SNAPSHOT_DIR, exist_ok=True)
    os.makedirs(config.RECORDING_DIR, exist_ok=True)
    
    camera_manager.start_cameras(config.CAMERA_SOURCES)
    app_logger.info(f'Starting CUSTOS Command Center at http://localhost:{port}')
    print('\n' + '=' * 60)
    print(f'   CUSTOS COMMAND CENTER IS READY AT: http://localhost:{port}')
    print(f'   ACCESS LINK:                       http://127.0.0.1:{port}')
    print(f'   DEFAULT CREDENTIALS:               admin / admin123')
    print('=' * 60 + '\n')
    socket.run(app, host=host, port=port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    main()
