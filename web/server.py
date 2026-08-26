# web/server.py — CUSTOS Optimised with RBAC
import cv2, time, os, sys, functools, json
from datetime import datetime

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from flask import Flask, Response, render_template_string, jsonify, session, redirect, request, abort
from flask_socketio import SocketIO
from authlib.integrations.flask_client import OAuth
from flask_login import LoginManager, login_user, logout_user, login_required, current_user

from config import settings as config
from engine.logger import app_logger
from engine.camera_manager import CameraManager
from database import (
    db, db_manager, User, UserRole, LoginHistory, AuditLog, Incident, Subject, Evidence, BehaviorLog,
    PersonClassification, PersonProfile, PersonFace, PersonCluster, PersonAppearance
)
from database.database_manager import parse_events
from engine.storage_queue import storage_queue
from engine.face_engine import face_engine


# Suppress OpenCV's verbose MSMF/DSHOW warning spam in the terminal
os.environ['OPENCV_VIDEOIO_PRIORITY_MSMF'] = '0'
os.environ['OPENCV_LOG_LEVEL'] = 'ERROR'

app = Flask(__name__)
app.secret_key = os.getenv('CUSTOS_SECRET', 'custos_production_secret_key_fixed_2026')
app.config['SECRET_KEY'] = app.secret_key
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Database Setup
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('CUSTOS_DATABASE_URI', 'sqlite:///custos.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# Login Manager Setup
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@login_manager.unauthorized_handler
def unauthorized_callback():
    if request.path.startswith('/api/') or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': False, 'error': {'code': 'UNAUTHORIZED', 'message': 'Authentication required. Please log in.'}}), 401
    return redirect('/login?next=' + request.path)

# Initialize DB and create default admin via DatabaseManager
db_manager.init_db(app)

# SocketIO Setup
socket = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=10, ping_interval=5)

# Initialize Storage Queue Worker
storage_queue.set_app(app)
storage_queue.set_socket_emitter(socket.emit)
storage_queue.start()

# Google OAuth Setup
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID', 'dummy'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET', 'dummy'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

camera_manager = CameraManager(socket_emitter=socket.emit, flask_app=app)


# RBAC Decorator
def role_required(role):
    def decorator(f):
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or not current_user.has_role(role):
                return jsonify({'success': False, 'error': {'code': 'FORBIDDEN', 'message': 'Insufficient permissions to perform this action.'}}), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def log_audit(action, target, details=""):
    if current_user.is_authenticated:
        log = AuditLog(user_id=current_user.id, action=action, target=target, details=details)
        db.session.add(log)
        db.session.commit()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect('/')
        
    error = ''
    if request.method == 'POST':
        req_data = request.get_json(silent=True) or request.form
        username = req_data.get('username')
        password = req_data.get('password')
        user = User.query.filter_by(username=username).first()
        
        success = False
        if user and user.check_password(password):
            if user.is_active:
                login_user(user, remember=True)
                user.last_login = db.func.now()
                success = True
                db.session.commit()
                if request.is_json:
                    return jsonify({'success': True, 'user': user.to_dict()})
                next_page = request.args.get('next')
                if not next_page or not next_page.startswith('/'):
                    next_page = '/'
                return redirect(next_page)
            else:
                error = 'Account is disabled.'
        else:
            error = 'Invalid credentials.'

        if request.is_json:
            return jsonify({'success': False, 'error': error}), 401

            
        # Log login attempt
        hist = LoginHistory(
            user_id=user.id if user else None,
            ip_address=request.remote_addr,
            success=success,
            user_agent=request.user_agent.string
        )
        db.session.add(hist)
        db.session.commit()
        
    return render_template_string(LOGIN_HTML, error=error)

@app.route('/login/google')
def login_google():
    redirect_uri = request.url_root.rstrip('/') + '/auth/callback'
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/callback')
def auth_callback():
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')
        if user_info:
            email = user_info.get('email')
            user = User.query.filter_by(email=email).first()
            if not user:
                # Auto-register Google users as viewers
                user = User(
                    username=email.split('@')[0], 
                    email=email, 
                    role=UserRole.VIEWER,
                    google_id=user_info.get('sub'),
                    is_email_verified=True
                )
                db.session.add(user)
                db.session.commit()
                
            if user.is_active:
                login_user(user)
                user.last_login = db.func.now()
                
                # Log success
                hist = LoginHistory(user_id=user.id, ip_address=request.remote_addr, success=True, user_agent=request.user_agent.string)
                db.session.add(hist)
                db.session.commit()
                
                app_logger.info(f"Google Login Successful: {email}")
                return redirect('/')
            else:
                return render_template_string(LOGIN_HTML, error='Account disabled.')
                
    except Exception as e:
        app_logger.error(f"Auth Error: {e}")
    return render_template_string(LOGIN_HTML, error='Google Sign-In failed.')

@app.route('/logout')
@login_required
def logout():
    log_audit('Logout', 'System')
    logout_user()
    return redirect('/login')

@app.route('/')
@login_required
def index():
    p = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend', 'index.html')
    with open(p, 'r', encoding='utf-8') as f: 
        return f.read()

@app.route('/video_feed')
@app.route('/video_feed/<int:camera_id>')
@login_required
def video_feed(camera_id=0):
    pipeline = camera_manager.get_pipeline(camera_id)
    if not pipeline:
        return "Camera not found", 404
        
    def generate():
        while True:
            frame = pipeline.get_latest_frame_bytes()
            if frame: yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n'
            time.sleep(0.033)
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/state')
@app.route('/state/<int:camera_id>')
@login_required
def get_state(camera_id=0):
    pipeline = camera_manager.get_pipeline(camera_id)
    if not pipeline:
        return jsonify({'error': 'Camera not found'}), 404
    s = pipeline.get_state()
    s['uptime'] = int(time.time() - s['uptime_start'])
    return jsonify(s)

@app.route('/snapshots/<path:filename>')
@login_required
def serve_snapshot(filename):
    from flask import send_from_directory
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), config.SNAPSHOT_DIR)
    return send_from_directory(d, filename, conditional=True)

@app.route('/ping')
def ping():
    return jsonify({'status': 'ok', 'ts': time.time()})

@app.route('/api/health')
@login_required
def api_health():
    from engine.health_monitor import system_health
    status = system_health.get_status()
    pipeline = camera_manager.get_pipeline(0)
    if pipeline and hasattr(pipeline, 'camera_health'):
        status['camera'] = pipeline.camera_health.get_status()
    return jsonify(status)


# ═══════════════════════════════════════════════════════
# CUSTOS 2.7 — ALERT CENTER REST APIS
# ═══════════════════════════════════════════════════════

@app.route('/api/alerts', methods=['GET'])
@login_required
def get_alerts():
    filters = {
        'severity': request.args.get('severity'),
        'status': request.args.get('status'),
        'type': request.args.get('type') or request.args.get('incident_type'),
        'camera_id': request.args.get('camera_id'),
        'zone': request.args.get('zone'),
        'subject_id': request.args.get('subject_id'),
        'date_range': request.args.get('date_range'),
        'start_date': request.args.get('start_date'),
        'end_date': request.args.get('end_date'),
        'q': request.args.get('q'),
        'page': request.args.get('page', 1, type=int),
        'limit': request.args.get('limit', 20, type=int)
    }
    result = db_manager.query_alerts(app, filters)
    return jsonify({
        'success': True,
        'data': result
    })

@app.route('/api/alerts/<int:alert_id>', methods=['GET'])
@login_required
def get_single_alert(alert_id):
    alert = db_manager.get_alert_by_id(app, alert_id)
    if not alert:
        return jsonify({
            'success': False,
            'error': {'code': 'ALERT_NOT_FOUND', 'message': f'Alert #{alert_id} not found.'}
        }), 404
    return jsonify({
        'success': True,
        'data': alert
    })

@app.route('/api/alerts/<int:alert_id>', methods=['PATCH'])
@app.route('/api/alerts/<int:alert_id>/resolve', methods=['POST'])
@login_required
@role_required(UserRole.OPERATOR)
def resolve_alert_endpoint(alert_id):
    data = request.json or {}
    notes = data.get('notes', '')
    user_id = current_user.id if current_user.is_authenticated else None
    
    updated_alert = db_manager.resolve_alert(app, alert_id, user_id=user_id, notes=notes)
    if not updated_alert:
        return jsonify({
            'success': False,
            'error': {'code': 'ALERT_NOT_FOUND', 'message': f'Alert #{alert_id} not found.'}
        }), 404

    log_audit('Resolve Alert', f'Alert #{alert_id}')
    
    # Broadcast realtime resolution update to all clients
    socket.emit('alert_updated', updated_alert)
    socket.emit('alert_resolved', {'alert_id': alert_id, 'camera_id': updated_alert.get('camera_id', 0)})

    return jsonify({
        'success': True,
        'data': updated_alert
    })

@app.route('/api/alerts/stats', methods=['GET'])
@login_required
def get_alerts_stats():
    stats = db_manager.get_alerts_stats(app)
    return jsonify({
        'success': True,
        'data': stats
    })


# ═══════════════════════════════════════════════════════
# CUSTOS 2.7 — EVIDENCE CENTER REST APIS
# ═══════════════════════════════════════════════════════

@app.route('/api/evidence', methods=['GET'])
@login_required
def get_evidence_list():
    filters = {
        'type': request.args.get('type'),
        'severity': request.args.get('severity'),
        'camera_id': request.args.get('camera_id'),
        'zone': request.args.get('zone'),
        'date_range': request.args.get('date_range'),
        'start_date': request.args.get('start_date'),
        'end_date': request.args.get('end_date'),
        'q': request.args.get('q'),
        'page': request.args.get('page', 1, type=int),
        'limit': request.args.get('limit', 20, type=int)
    }
    result = db_manager.query_evidence(app, filters)
    return jsonify({
        'success': True,
        'data': result
    })

@app.route('/api/evidence/<int:evidence_id>', methods=['GET'])
@login_required
def get_single_evidence(evidence_id):
    ev = db_manager.get_evidence_by_id(app, evidence_id)
    if not ev:
        return jsonify({
            'success': False,
            'error': {'code': 'EVIDENCE_NOT_FOUND', 'message': f'Evidence record #{evidence_id} not found.'}
        }), 404
    return jsonify({
        'success': True,
        'data': ev
    })

@app.route('/api/evidence/<int:evidence_id>/media/<string:media_type>', methods=['GET'])
@login_required
def serve_evidence_media(evidence_id, media_type):
    from flask import send_file
    inc = db.session.get(Incident, evidence_id)
    if not inc:
        return jsonify({
            'success': False,
            'error': {'code': 'EVIDENCE_NOT_FOUND', 'message': 'Evidence record was not found.'}
        }), 404

    filename = ''
    if media_type in ('snapshot', 'image', 'thumb'):
        filename = inc.snapshot_path
    elif media_type in ('clip', 'video'):
        filename = inc.clip_path
    else:
        return jsonify({
            'success': False,
            'error': {'code': 'INVALID_MEDIA_TYPE', 'message': 'Media type must be snapshot or clip.'}
        }), 400

    if not filename:
        return jsonify({
            'success': False,
            'error': {'code': 'MEDIA_UNAVAILABLE', 'message': 'Evidence media file is unavailable.'}
        }), 404

    base_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), config.SNAPSHOT_DIR))
    safe_filename = os.path.basename(filename)
    target_path = os.path.abspath(os.path.join(base_dir, safe_filename))

    # Path traversal check
    if not target_path.startswith(base_dir) or not os.path.exists(target_path):
        return jsonify({
            'success': False,
            'error': {'code': 'MEDIA_NOT_FOUND', 'message': 'Requested media file not found on disk.'}
        }), 404

    mimetype = 'image/jpeg' if safe_filename.endswith(('.jpg', '.jpeg', '.png')) else 'video/mp4'
    return send_file(target_path, mimetype=mimetype, conditional=True)

@app.route('/api/evidence/stats', methods=['GET'])
@login_required
def get_evidence_stats():
    stats = db_manager.get_evidence_stats(app)
    return jsonify({
        'success': True,
        'data': stats
    })


# ═══════════════════════════════════════════════════════
# CUSTOS 2.8 — AI ANALYTICS / PEOPLE INTELLIGENCE APIS
# ═══════════════════════════════════════════════════════

@app.route('/api/people', methods=['GET'])
@login_required
def get_people_list():
    filters = {
        'classification': request.args.get('classification'),
        'status': request.args.get('status'),
        'include_inactive': request.args.get('include_inactive', '').lower() in ('1', 'true'),
        'q': request.args.get('q'),
        'page': request.args.get('page', 1, type=int),
        'limit': request.args.get('limit', 20, type=int)
    }
    result = db_manager.query_person_profiles(app, filters)
    return jsonify({
        'success': True,
        'data': result
    })

@app.route('/api/people/stats', methods=['GET'])
@login_required
def get_people_stats_endpoint():
    stats = db_manager.get_people_stats(app)
    return jsonify({
        'success': True,
        'data': stats
    })

@app.route('/api/people/suspicious', methods=['GET'])
@login_required
def get_suspicious_people_endpoint():
    results = db_manager.get_suspicious_profiles(app)
    return jsonify({
        'success': True,
        'data': results
    })

@app.route('/api/people/<string:person_id>', methods=['GET'])
@login_required
def get_single_person(person_id):
    profile = db_manager.get_person_profile(app, person_id, include_appearances=True)
    if not profile:
        return jsonify({
            'success': False,
            'error': {'code': 'PERSON_NOT_FOUND', 'message': f'Person {person_id} was not found.'}
        }), 404
    return jsonify({
        'success': True,
        'data': profile
    })

@app.route('/api/people', methods=['POST'])
@login_required
@role_required(UserRole.OPERATOR)
def create_person():
    data = request.json or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({
            'success': False,
            'error': {'code': 'VALIDATION_ERROR', 'message': 'Person name is required.'}
        }), 400

    classification = data.get('classification', PersonClassification.KNOWN)
    notes = data.get('notes', '')

    profile = db_manager.create_person_profile(
        app,
        name=name,
        classification=classification,
        notes=notes
    )
    if not profile:
        return jsonify({
            'success': False,
            'error': {'code': 'CREATE_FAILED', 'message': 'Could not create person profile.'}
        }), 500

    face_engine.refresh_cache(app)
    socket.emit('person_profile_created', profile)
    log_audit('Create Person', f"Created person {profile['id']} ({profile['name']})")

    return jsonify({
        'success': True,
        'data': profile
    }), 201

@app.route('/api/people/<string:person_id>', methods=['PATCH'])
@login_required
@role_required(UserRole.OPERATOR)
def update_person(person_id):
    data = request.json or {}
    name = data.get('name')
    classification = data.get('classification')
    status = data.get('status')
    notes = data.get('notes')

    updated = db_manager.update_person_profile(
        app,
        person_id=person_id,
        name=name,
        classification=classification,
        status=status,
        notes=notes
    )
    if not updated:
        return jsonify({
            'success': False,
            'error': {'code': 'PERSON_NOT_FOUND', 'message': f'Person {person_id} was not found.'}
        }), 404

    face_engine.refresh_cache(app)
    socket.emit('person_profile_updated', updated)
    log_audit('Update Person', f"Updated profile {person_id}")

    return jsonify({
        'success': True,
        'data': updated
    })

@app.route('/api/people/<string:person_id>', methods=['DELETE'])
@login_required
@role_required(UserRole.OPERATOR)
def deactivate_person(person_id):
    success = db_manager.deactivate_person_profile(app, person_id)
    if not success:
        return jsonify({
            'success': False,
            'error': {'code': 'PERSON_NOT_FOUND', 'message': f'Person {person_id} was not found.'}
        }), 404

    face_engine.refresh_cache(app)
    socket.emit('person_profile_deactivated', {'person_id': person_id})
    log_audit('Deactivate Person', f"Deactivated profile {person_id}")

    return jsonify({
        'success': True,
        'data': {'person_id': person_id, 'status': 'INACTIVE'}
    })

@app.route('/api/people/enroll', methods=['POST'])
@login_required
@role_required(UserRole.OPERATOR)
def enroll_person_photo():
    if 'photo' not in request.files:
        return jsonify({
            'success': False,
            'error': {'code': 'NO_FILE', 'message': 'Please upload a photo file.'}
        }), 400

    file = request.files['photo']
    if not file or file.filename == '':
        return jsonify({
            'success': False,
            'error': {'code': 'EMPTY_FILE', 'message': 'Uploaded file is empty.'}
        }), 400

    name = request.form.get('name', '').strip()
    if not name:
        return jsonify({
            'success': False,
            'error': {'code': 'VALIDATION_ERROR', 'message': 'Person name is required.'}
        }), 400

    classification = request.form.get('classification', PersonClassification.KNOWN)
    notes = request.form.get('notes', '')

    # Read image bytes using OpenCV
    file_bytes = np.frombuffer(file.read(), np.uint8)
    img_bgr = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)

    if img_bgr is None:
        return jsonify({
            'success': False,
            'error': {'code': 'DECODE_ERROR', 'message': 'Unable to decode image. Please upload a valid JPG or PNG.'}
        }), 400

    # Validate uploaded photo (face detection, single face, quality, embedding)
    valid, embedding, aligned_face, quality_score, msg = face_engine.validate_uploaded_image(img_bgr)
    if not valid:
        return jsonify({
            'success': False,
            'error': {'code': 'FACE_VALIDATION_FAILED', 'message': msg}
        }), 422

    # 1. Create Person Profile record
    profile_data = db_manager.create_person_profile(
        app,
        name=name,
        classification=classification,
        notes=notes
    )
    if not profile_data:
        return jsonify({
            'success': False,
            'error': {'code': 'ENROLL_FAILED', 'message': 'Failed to save person profile in database.'}
        }), 500

    pid = profile_data['id']

    # 2. Save reference face image to protected disk directory
    profile_dir = os.path.join(getattr(config, 'PEOPLE_PROFILES_DIR', 'data/people/profiles'), pid)
    os.makedirs(profile_dir, exist_ok=True)
    ref_filename = f"ref_{int(time.time())}.jpg"
    ref_path = os.path.join(profile_dir, ref_filename)
    cv2.imwrite(ref_path, aligned_face if aligned_face is not None else img_bgr)

    # 3. Add PersonFace with binary embedding
    db_manager.add_reference_face(
        app,
        person_id=pid,
        image_path=ref_path,
        embedding_bytes=embedding.tobytes(),
        quality_score=quality_score,
        is_profile_display=True
    )

    # 4. Refresh recognition engine cache so person is IMMEDIATELY recognized
    face_engine.refresh_cache(app)

    full_profile = db_manager.get_person_profile(app, pid, include_appearances=True)
    socket.emit('person_profile_created', full_profile)
    log_audit('Enroll Person', f"Enrolled {pid} ({name}) with quality {quality_score}")

    return jsonify({
        'success': True,
        'data': full_profile
    }), 201

@app.route('/api/people/<string:person_id>/faces', methods=['POST'])
@login_required
@role_required(UserRole.OPERATOR)
def add_person_reference_photo(person_id):
    profile = db_manager.get_person_profile(app, person_id)
    if not profile:
        return jsonify({
            'success': False,
            'error': {'code': 'PERSON_NOT_FOUND', 'message': f'Person {person_id} not found.'}
        }), 404

    if 'photo' not in request.files:
        return jsonify({
            'success': False,
            'error': {'code': 'NO_FILE', 'message': 'Please upload a photo file.'}
        }), 400

    file = request.files['photo']
    file_bytes = np.frombuffer(file.read(), np.uint8)
    img_bgr = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)

    if img_bgr is None:
        return jsonify({
            'success': False,
            'error': {'code': 'DECODE_ERROR', 'message': 'Unable to decode image file.'}
        }), 400

    valid, embedding, aligned_face, quality_score, msg = face_engine.validate_uploaded_image(img_bgr)
    if not valid:
        return jsonify({
            'success': False,
            'error': {'code': 'FACE_VALIDATION_FAILED', 'message': msg}
        }), 422

    profile_dir = os.path.join(getattr(config, 'PEOPLE_PROFILES_DIR', 'data/people/profiles'), person_id)
    os.makedirs(profile_dir, exist_ok=True)
    ref_filename = f"ref_{int(time.time())}.jpg"
    ref_path = os.path.join(profile_dir, ref_filename)
    cv2.imwrite(ref_path, aligned_face if aligned_face is not None else img_bgr)

    face_dict = db_manager.add_reference_face(
        app,
        person_id=person_id,
        image_path=ref_path,
        embedding_bytes=embedding.tobytes(),
        quality_score=quality_score
    )

    face_engine.refresh_cache(app)
    socket.emit('person_profile_updated', db_manager.get_person_profile(app, person_id, include_appearances=True))
    log_audit('Add Reference Face', f"Added reference photo to {person_id}")

    return jsonify({
        'success': True,
        'data': face_dict
    }), 201

@app.route('/api/people/<string:person_id>/faces/<int:face_id>', methods=['DELETE'])
@login_required
@role_required(UserRole.OPERATOR)
def remove_person_reference_photo(person_id, face_id):
    success = db_manager.remove_reference_face(app, face_id)
    if not success:
        return jsonify({
            'success': False,
            'error': {'code': 'FACE_NOT_FOUND', 'message': f'Face record #{face_id} was not found.'}
        }), 404

    face_engine.refresh_cache(app)
    socket.emit('person_profile_updated', db_manager.get_person_profile(app, person_id, include_appearances=True))
    log_audit('Remove Reference Face', f"Removed face #{face_id} from {person_id}")

    return jsonify({
        'success': True,
        'data': {'face_id': face_id, 'person_id': person_id}
    })

@app.route('/api/people/<string:person_id>/appearances', methods=['GET'])
@login_required
def get_person_appearances(person_id):
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 20, type=int)
    result = db_manager.query_person_appearances(app, person_id=person_id, page=page, limit=limit)
    return jsonify({
        'success': True,
        'data': result
    })

@app.route('/api/faces/clusters', methods=['GET'])
@login_required
def get_clusters_list():
    status = request.args.get('status', 'ACTIVE')
    clusters = db_manager.query_clusters(app, status=status)
    return jsonify({
        'success': True,
        'data': clusters
    })

@app.route('/api/faces/clusters/<string:cluster_id>', methods=['GET'])
@login_required
def get_single_cluster(cluster_id):
    data = db_manager.get_cluster_by_id(app, cluster_id)
    if not data:
        return jsonify({
            'success': False,
            'error': {'code': 'CLUSTER_NOT_FOUND', 'message': f'Cluster {cluster_id} not found.'}
        }), 404
    return jsonify({
        'success': True,
        'data': data
    })

@app.route('/api/faces/clusters/<string:cluster_id>/profile', methods=['POST'])
@login_required
@role_required(UserRole.OPERATOR)
def convert_cluster_to_person(cluster_id):
    data = request.json or {}
    name = data.get('name', '').strip()
    classification = data.get('classification', PersonClassification.KNOWN)
    notes = data.get('notes', '')
    target_person_id = data.get('target_person_id')

    profile = db_manager.convert_cluster_to_profile(
        app,
        cluster_id=cluster_id,
        name=name,
        classification=classification,
        notes=notes,
        target_person_id=target_person_id
    )

    if not profile:
        return jsonify({
            'success': False,
            'error': {'code': 'CONVERT_FAILED', 'message': f'Could not link cluster {cluster_id} to profile.'}
        }), 500

    face_engine.refresh_cache(app)
    socket.emit('person_profile_created', profile)
    socket.emit('cluster_updated', {'cluster_id': cluster_id, 'status': 'LINKED', 'person_id': profile['id']})
    log_audit('Convert Cluster', f"Linked cluster {cluster_id} to {profile['id']} ({profile['name']})")

    return jsonify({
        'success': True,
        'data': profile
    }), 201

# ═══════════════════════════════════════════════════════
# PROTECTED MEDIA SERVING FOR PEOPLE & APPEARANCES
# ═══════════════════════════════════════════════════════

def _serve_safe_file(file_path, default_mime='image/jpeg'):
    from flask import send_file
    if not file_path:
        return jsonify({'success': False, 'error': {'code': 'MEDIA_UNAVAILABLE', 'message': 'Media not found.'}}), 404

    base_project_dir = os.path.abspath(_PROJECT_ROOT)
    target_path = os.path.abspath(file_path)

    # Path traversal check
    if not target_path.startswith(base_project_dir) or not os.path.exists(target_path):
        return jsonify({'success': False, 'error': {'code': 'FILE_NOT_FOUND', 'message': 'Media file missing on disk.'}}), 404

    return send_file(target_path, mimetype=default_mime, conditional=True)

@app.route('/api/people/<string:person_id>/media/<string:media_type>', methods=['GET'])
@login_required
def serve_person_media(person_id, media_type):
    profile = PersonProfile.query.filter_by(id=person_id).first()
    if not profile:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Profile not found.'}}), 404

    target_file = None
    if media_type == 'profile':
        target_file = profile.profile_image_path
        if not target_file and profile.faces:
            target_file = profile.faces[0].image_path
    elif media_type.startswith('face_'):
        try:
            face_id = int(media_type.replace('face_', ''))
            face = PersonFace.query.filter_by(id=face_id, person_id=person_id).first()
            if face:
                target_file = face.image_path
        except ValueError:
            pass

    return _serve_safe_file(target_file)

@app.route('/api/faces/clusters/<string:cluster_id>/media', methods=['GET'])
@login_required
def serve_cluster_media(cluster_id):
    cluster = PersonCluster.query.filter_by(id=cluster_id).first()
    if not cluster or not cluster.representative_image:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Cluster image not found.'}}), 404
    return _serve_safe_file(cluster.representative_image)

@app.route('/api/people/appearances/<int:appearance_id>/media', methods=['GET'])
@login_required
def serve_appearance_media(appearance_id):
    app_rec = PersonAppearance.query.filter_by(id=appearance_id).first()
    if not app_rec or not app_rec.snapshot_path:
        return jsonify({'success': False, 'error': {'code': 'NOT_FOUND', 'message': 'Appearance snapshot not found.'}}), 404
    return _serve_safe_file(app_rec.snapshot_path)


# ═══════════════════════════════════════════════════════

# BACKWARD COMPATIBILITY ENDPOINTS
# ═══════════════════════════════════════════════════════

@app.route('/api/incidents')
@login_required
def api_incidents():
    query = Incident.query

    # 1. Mode Filtering
    mode = request.args.get('mode', '').lower()
    if mode == 'user':
        query = query.filter(db.or_(Incident.score < 60.0, Incident.status == 'Resolved'))
    elif mode == 'security':
        query = query.filter(db.or_(
            Incident.score >= 60.0,
            Incident.events.ilike('%HIGH%'),
            Incident.events.ilike('%TAMPER%'),
            Incident.events.ilike('%BREACH%'),
            Incident.events.ilike('%INTRUSION%')
        ))

    # 2. Specific Field Filters
    status = request.args.get('status')
    if status:
        query = query.filter(Incident.status == status)

    min_score = request.args.get('min_score', type=float)
    if min_score is not None:
        query = query.filter(Incident.score >= min_score)

    min_rel = request.args.get('min_reliability', type=float)
    if min_rel is not None:
        query = query.filter(Incident.reliability_score >= min_rel)

    cam_id = request.args.get('camera_id')
    if cam_id is not None and cam_id != '':
        try:
            query = query.filter(Incident.camera_id == int(cam_id))
        except ValueError:
            pass

    zone = request.args.get('zone')
    if zone:
        query = query.filter(Incident.zone_name.ilike(f'%{zone}%'))

    subj = request.args.get('subject_id')
    if subj:
        query = query.filter(Incident.subject_id.ilike(f'%{subj}%'))

    incident_type = request.args.get('incident_type')
    if incident_type:
        query = query.filter(Incident.events.ilike(f'%{incident_type}%'))

    start_date = request.args.get('start_date')
    if start_date:
        try:
            dt_start = datetime.fromisoformat(start_date)
            query = query.filter(Incident.timestamp >= dt_start)
        except Exception:
            pass

    end_date = request.args.get('end_date')
    if end_date:
        try:
            dt_end = datetime.fromisoformat(end_date)
            query = query.filter(Incident.timestamp <= dt_end)
        except Exception:
            pass

    # 3. Full-Text Search (q)
    search = request.args.get('q')
    if search:
        s_pattern = f'%{search}%'
        search_conditions = [
            Incident.events.ilike(s_pattern),
            Incident.ai_summary.ilike(s_pattern),
            Incident.recommended_action.ilike(s_pattern),
            Incident.subject_id.ilike(s_pattern),
            Incident.zone_name.ilike(s_pattern)
        ]
        try:
            cam_val = int(search)
            search_conditions.append(Incident.camera_id == cam_val)
        except ValueError:
            pass
        query = query.filter(db.or_(*search_conditions))

    incidents = query.order_by(Incident.timestamp.desc()).limit(100).all()
    results = []
    for inc in incidents:
        parsed_events = parse_events(inc.events)
        results.append({
            'id': inc.id,
            'camera_id': getattr(inc, 'camera_id', 0),
            'zone_name': getattr(inc, 'zone_name', 'Observation Area'),
            'score': inc.score,
            'threat_score': inc.score,
            'reliability_score': getattr(inc, 'reliability_score', 100.0),
            'subject_id': getattr(inc, 'subject_id', 'Person-01'),
            'subject_dwell_time': getattr(inc, 'subject_dwell_time', 0.0),
            'events': parsed_events,
            'ai_summary': getattr(inc, 'ai_summary', ''),
            'recommended_action': getattr(inc, 'recommended_action', ''),
            'timeline_json': getattr(inc, 'timeline_json', '[]'),
            'snapshot_path': inc.snapshot_path,
            'clip_path': inc.clip_path,
            'timestamp': inc.timestamp.isoformat() if inc.timestamp else None,
            'status': inc.status,
        })

    return jsonify(results)


@app.route('/api/incidents/<int:inc_id>', methods=['GET'])
@login_required
def get_single_incident(inc_id):
    inc = db.session.get(Incident, inc_id)
    if not inc:
        return jsonify({'error': 'Incident not found'}), 404
    
    parsed_events = parse_events(inc.events)
    timeline = []
    if inc.timeline_json:
        try:
            timeline = json.loads(inc.timeline_json)
        except Exception:
            pass

    return jsonify({
        'incident': {
            'id': inc.id,
            'timestamp': inc.timestamp.isoformat() if inc.timestamp else None,
            'camera_id': inc.camera_id,
            'zone_name': inc.zone_name,
            'score': inc.score,
            'threat_score': inc.score,
            'reliability_score': inc.reliability_score,
            'subject_id': inc.subject_id,
            'subject_dwell_time': inc.subject_dwell_time,
            'status': inc.status,
            'events': parsed_events
        },
        'snapshot': inc.snapshot_path or '',
        'clip': inc.clip_path or '',
        'timeline': timeline,
        'ai_summary': inc.ai_summary or '',
        'recommended_action': inc.recommended_action or ''
    })


@app.route('/api/incidents/<int:inc_id>/resolve', methods=['POST'])
@login_required
@role_required(UserRole.OPERATOR)
def resolve_incident(inc_id):
    inc = db.session.get(Incident, inc_id)
    if not inc:
        return jsonify({'error': 'Incident not found'}), 404
    data = request.json or {}
    inc.status = 'Resolved'
    inc.resolved_by_id = current_user.id
    inc.resolved_at = db.func.now()
    inc.notes = data.get('notes', '')
    db.session.commit()
    log_audit('Resolve Incident', f'Incident #{inc_id}')
    return jsonify({'success': True})

@app.route('/api/incidents/<int:inc_id>', methods=['DELETE'])
@login_required
@role_required(UserRole.OPERATOR)
def delete_incident(inc_id):
    inc = db.session.get(Incident, inc_id)
    if not inc:
        return jsonify({'error': 'Incident not found'}), 404
    db.session.delete(inc)
    db.session.commit()
    log_audit('Delete Incident', f'Incident #{inc_id}')
    return jsonify({'success': True})

@app.route('/api/evidence/<path:filename>', methods=['DELETE'])
@login_required
@role_required(UserRole.OPERATOR)
def delete_evidence(filename):
    # Prevent directory traversal
    safe_filename = os.path.basename(filename)
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), config.SNAPSHOT_DIR)
    target_path = os.path.join(d, safe_filename)
    if os.path.exists(target_path):
        os.remove(target_path)
        log_audit('Delete Evidence', safe_filename)
        return jsonify({'success': True})
    return jsonify({'error': 'File not found'}), 404

@app.route('/list_evidence')
@login_required
def list_legacy_evidence():
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), config.SNAPSHOT_DIR)
    files = []
    if os.path.exists(d):
        for f in sorted(os.listdir(d), reverse=True):
            if f.endswith(('.jpg', '.mp4')):
                files.append({'name': f, 'path': f'/snapshots/{f}'})
    return jsonify({'files': files, 'snapshots': files})

@app.route('/snapshots')
@login_required
def list_snapshots():
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), config.SNAPSHOT_DIR)
    files = []
    if os.path.exists(d):
        for f in sorted(os.listdir(d), reverse=True):
            if f.endswith(('.jpg', '.mp4')):
                files.append({'name': f, 'path': f'/snapshots/{f}'})
    return jsonify({'snapshots': files})

@app.route('/list_evidence')
@login_required
def list_evidence():
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), config.SNAPSHOT_DIR)
    files = []
    if os.path.exists(d):
        for f in sorted(os.listdir(d), reverse=True):
            if f.endswith(('.jpg', '.mp4')): files.append({'name': f})
    return jsonify({'files': files})


@app.route('/list_cameras')
@login_required
def list_cameras():
    cameras = []
    for pid, pipeline in camera_manager.pipelines.items():
        name = 'Built-in Camera' if pid == 0 else f'Camera {pid}'
        cameras.append({'index': pid, 'name': name, 'sub': f'Source {pipeline.camera_source}', 'icon': '📷'})
    return jsonify({'cameras': cameras})

@socket.on('connect')
def on_connect():
    if not current_user.is_authenticated:
        return False # Reject socket connection if not logged in
    if not camera_manager.pipelines:
        camera_manager.start_cameras(config.CAMERA_SOURCES)

@socket.on('set_zones')
def on_set_zones(data):
    if not current_user.is_authenticated or not current_user.has_role(UserRole.OPERATOR):
        return
    camera_id = data.get('camera_id', 0)
    zones = data.get('zones', [])
    types = data.get('types', [])
    monitoring = data.get('monitoring', False)
    camera_manager.set_zones(camera_id, zones, types, monitoring)
    log_audit('Update Zones', f'Camera {camera_id}')

@socket.on('set_camera')
def on_set_camera(data):
    if not current_user.is_authenticated or not current_user.has_role(UserRole.OPERATOR):
        return
    idx = data.get('index', 0)
    if idx in camera_manager.pipelines:
        log_audit('Set Camera', f'Switched to camera index {idx}')
        socket.emit('camera_changed', {'index': idx, 'status': 'ok'})

@app.errorhandler(400)
def bad_request(e):
    return jsonify({'error': 'Bad Request', 'message': str(e)}), 400

@app.errorhandler(401)
def unauthorized(e):
    return jsonify({'error': 'Unauthorized', 'message': 'Authentication required'}), 401

@app.errorhandler(403)
def forbidden(e):
    return jsonify({'error': 'Forbidden', 'message': 'Insufficient permissions'}), 403

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/') or request.path in ['/list_evidence', '/list_cameras', '/state']:
        return jsonify({'error': 'Not Found', 'message': 'Resource not found'}), 404
    return "Page Not Found", 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Internal Server Error', 'message': 'An unexpected error occurred'}), 500

LOGIN_HTML='''<!DOCTYPE html><html><head><title>CUSTOS Login</title>

<style>*{margin:0;padding:0;box-sizing:border-box;}body{background:#09090c;display:flex;align-items:center;justify-content:center;height:100vh;font-family:'Segoe UI',sans-serif;}
.box{background:#111116;border:1px solid #1f1f28;border-radius:8px;padding:40px;width:340px;}
h2{color:#f4f4f8;font-size:22px;margin-bottom:6px;text-align:center;}
p{color:#6b6b7a;font-size:13px;margin-bottom:24px;text-align:center;}
label{display:block;color:#9494a8;font-size:12px;margin-bottom:6px;}
input{width:100%;background:#16161d;border:1px solid #27272f;border-radius:6px;padding:10px 12px;color:#e8e8f0;font-size:14px;margin-bottom:16px;outline:none;}
input:focus{border-color:#3b82f6;}
button{width:100%;background:#3b82f6;color:#fff;border:none;border-radius:6px;padding:12px;font-size:14px;font-weight:600;cursor:pointer;transition:0.2s;}
button:hover{background:#2563eb;}
.err{background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);color:#ef4444;border-radius:6px;padding:10px;font-size:12px;margin-bottom:16px;text-align:center;}
.google-btn{background:#db4437;margin-top:4px;text-align:center;text-decoration:none;display:block;color:#fff;border-radius:6px;padding:12px;font-size:14px;font-weight:600;cursor:pointer;}
.google-btn:hover{background:#c53929;}
.divider{text-align:center;color:#6b6b7a;font-size:12px;margin:20px 0;position:relative;}
.divider::before,.divider::after{content:'';position:absolute;top:50%;width:35%;height:1px;background:#27272f;}
.divider::before{left:0;}.divider::after{right:0;}
</style>
</head><body><div class="box"><h2>CUSTOS Command Center</h2><p>Secure authentication required</p>
{% if error %}<div class="err">{{ error }}</div>{% endif %}
<form method="POST"><label>Username</label><input type="text" name="username" autofocus>
<label>Password</label><input type="password" name="password"><button type="submit">Log In</button></form>
<div class="divider">OR</div>
<a href="/login/google" class="google-btn">Continue with Google</a>
</div></body></html>'''

def start(host='0.0.0.0', port=5000, debug=False):
    os.makedirs(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend'), exist_ok=True)
    camera_manager.start_cameras(config.CAMERA_SOURCES)
    app_logger.info(f'CUSTOS Server at http://localhost:{port}')
    socket.run(app, host=host, port=port, debug=debug, use_reloader=False, allow_unsafe_werkzeug=True)

if __name__=='__main__': start()