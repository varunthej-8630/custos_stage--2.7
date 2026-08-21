# main.py — CUSTOS standalone debug entry point
# Use this for local testing WITHOUT the web dashboard.
# For production / demos: use web_server.py instead.

import cv2, time, os
from config import settings as config
from engine.logger import app_logger
from engine.camera_manager import CameraManager
from engine.zone_selector import ZoneSelector
from web.alert_manager import AlertManager

# Suppress OpenCV's verbose MSMF/DSHOW warning spam in the terminal
os.environ['OPENCV_VIDEOIO_PRIORITY_MSMF'] = '0'
os.environ['OPENCV_LOG_LEVEL'] = 'ERROR'

def main():
    print('=' * 55)
    print('   CUSTOS — standalone debug mode')
    print('   For demos use: python web_server.py')
    print('=' * 55)

    source = config.CAMERA_SOURCES[0] if config.CAMERA_SOURCES else 0
    print(f'[CAMERA] Opening: {source}')
    
    # We open the camera temporarily just for drawing zones
    import platform
    backend = cv2.CAP_DSHOW if platform.system()=='Windows' else cv2.CAP_ANY
    cap = cv2.VideoCapture(source, backend)
    if not cap.isOpened(): cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print('[ERROR] Cannot open camera. Check CAMERA_SOURCES in config.py')
        return
        
    for _ in range(config.CAMERA_WARMUP_FRAMES): cap.read()
    
    print('[ZONES] Draw your protection zones...')
    selector = ZoneSelector()
    zones, zone_types = selector.select_zones(cap)
    
    if len(zones) == 0:
        print('[WARNING] No zones drawn — guarding entire frame.')
        ret, first_frame = cap.read()
        if ret:
            h, w = first_frame.shape[:2]
            zones = [[0, 0, w, h]]
            zone_types = [config.ZONE_TYPE_WATCH]
    
    cap.release()
    
    # Now start the pipeline
    camera_manager = CameraManager()
    camera_manager.start_cameras([source])
    camera_manager.set_zones(0, zones, zone_types, True)
    pipeline = camera_manager.get_pipeline(0)
    
    print('[SYSTEM] Guard is ACTIVE.')
    print('  Keys:  Q=quit')
    print('-' * 55)

    if config.SHOW_PREVIEW:
        cv2.namedWindow('SmartGuard', cv2.WINDOW_NORMAL)
        cv2.setWindowProperty('SmartGuard', cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    while True:
        frame_bytes = pipeline.get_latest_frame_bytes()
        if frame_bytes and config.SHOW_PREVIEW:
            import numpy as np
            frame_arr = np.frombuffer(frame_bytes, dtype=np.uint8)
            display = cv2.imdecode(frame_arr, cv2.IMREAD_COLOR)
            if display is not None:
                cv2.imshow('SmartGuard', display)
                
        key = cv2.waitKey(33) & 0xFF
        if key == ord('q') or key == ord('Q'):
            print('[SYSTEM] Quitting...')
            break

    camera_manager.stop_all()
    cv2.destroyAllWindows()
    print('[SYSTEM] Smart Guard stopped.')

if __name__ == '__main__':
    main()