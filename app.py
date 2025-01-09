import os
from flask import Flask, redirect, request, url_for, session, render_template, jsonify, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, login_required, current_user, logout_user
from flask_cors import CORS
import requests
from dotenv import load_dotenv
import subprocess
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime, timedelta
import threading
import uuid
import re
import json
import configparser
from version import VERSION
import logging

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def get_latest_commit_message():
    try:
        result = subprocess.run(['git', 'log', '-1', '--pretty=format:%s'], 
                              capture_output=True, text=True, check=True)
        return result.stdout
    except:
        return "Development build"

COMMIT_MESSAGE = get_latest_commit_message()

# Get progress settings from environment variables
PROGRESS_CONFIG = {
    'upload_percent': float(os.getenv('PROGRESS_UPLOAD_PERCENT', 50.0)),
    'process_percent': float(os.getenv('PROGRESS_PROCESS_PERCENT', 45.0)),
    'post_percent': float(os.getenv('PROGRESS_POST_PERCENT', 5.0)),
    'chart_size': int(os.getenv('PROGRESS_CHART_SIZE', 200)),
    'cutout': int(os.getenv('PROGRESS_CHART_CUTOUT', 15)),
    'opacity': float(os.getenv('PROGRESS_CHART_OPACITY', 0.9))
}

# Global dictionary to store task progress
tasks = {}

class FFmpegProgress:
    def __init__(self, duration):
        self.duration = duration
        self.current_time = 0
        self.status = 'processing'
        self.stage = 'processing'  # uploading, processing, posting, complete, failed
        self.percent = 0
        self.error = None
        self.message_link = None

    def update(self, time):
        self.current_time = time
        self.percent = min((time / self.duration) * 100, 100)

    def set_stage(self, stage, percent=None):
        self.stage = stage
        if percent is not None:
            self.percent = percent

    def complete(self, message_link=None):
        self.status = 'completed'
        self.percent = 100
        self.stage = 'complete'
        self.message_link = message_link

    def fail(self, error):
        self.status = 'failed'
        self.error = error
        self.stage = 'failed'

app = Flask(__name__)  # Reset to default
app.static_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
app.static_url_path = '/static'

# Static URL from environment variable
app.config['STATIC_URL'] = os.getenv('STATIC_URL', 'https://stuff.introvrtlounge.com/images')

# Log static folder configuration
logger.info(f"Static folder: {app.static_folder}")
logger.info(f"Static URL path: {app.static_url_path}")
logger.info(f"Static URL: {app.config['STATIC_URL']}")
logger.info(f"Static folder exists: {os.path.exists(app.static_folder)}")
logger.info(f"Static folder contents: {os.listdir(app.static_folder)}")

@app.route('/upvrt/static/<path:filename>')
def serve_static(filename):
    """Serve static files."""
    logger.info(f"Serving static file: {filename}")
    try:
        if filename.startswith('images/'):
            logger.info(f"Static folder path: {app.static_folder}")
            logger.info(f"Full file path: {os.path.join(app.static_folder, filename)}")
            logger.info(f"File exists: {os.path.exists(os.path.join(app.static_folder, filename))}")
            response = send_from_directory(app.static_folder, filename)
            logger.info(f"Successfully served static file: {filename}")
            return response
        else:
            logger.error(f"Invalid path for static file: {filename}")
            return "Invalid path", 404
    except Exception as e:
        logger.error(f"Error serving static file {filename}: {str(e)}")
        return str(e), 404

CORS(app, resources={
    r"/upvrt/*": {
        "origins": ["https://www.introvrtlounge.com"],
        "supports_credentials": True
    }
})
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = os.urandom(24)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
app.config['APPLICATION_ROOT'] = '/'
app.config['SESSION_COOKIE_NAME'] = 'upvrt_session'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_PATH'] = '/upvrt/'
app.config['REMEMBER_COOKIE_SECURE'] = True
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(hours=24)
app.config['REMEMBER_COOKIE_PATH'] = '/upvrt/'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, name, discriminator, avatar):
        self.id = id
        self.name = name
        self.discriminator = discriminator
        self.avatar = avatar
        
    def get_id(self):
        return str(self.id)  # Convert to string for Flask-Login
        
    def is_authenticated(self):
        return True
        
    def is_active(self):
        return True

@login_manager.user_loader
def load_user(user_id):
    if 'user_data' not in session:
        return None
    data = session['user_data']
    return User(data['id'], data['username'], data['discriminator'], data['avatar'])

@app.route('/upvrt/')
def index():
    return render_template('index.html', version=VERSION, commit_message=COMMIT_MESSAGE)

@app.route('/upvrt/login')
def login():
    # Store the original URL the user was trying to access
    next_url = request.args.get('next', url_for('dashboard'))
    session['next_url'] = next_url
    
    oauth_url = f'https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={DISCORD_REDIRECT_URI}&response_type=code&scope=identify%20guilds%20guilds.members.read'
    return render_template('login.html', oauth_url=oauth_url, version=VERSION, commit_message=COMMIT_MESSAGE)

@app.route('/upvrt/callback')
def callback():
    error = request.args.get('error')
    if error:
        return render_template('callback.html', success=False, error=error, version=VERSION, commit_message=COMMIT_MESSAGE)
        
    code = request.args.get('code')
    if not code:
        return render_template('callback.html', success=False, error='No authorization code received', version=VERSION, commit_message=COMMIT_MESSAGE)
        
    try:
        data = {
            'client_id': DISCORD_CLIENT_ID,
            'client_secret': DISCORD_CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': DISCORD_REDIRECT_URI,
            'scope': 'identify guilds guilds.members.read'
        }
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        response = requests.post('https://discord.com/api/oauth2/token', data=data, headers=headers)
        response.raise_for_status()
        tokens = response.json()
        
        access_token = tokens.get('access_token')
        headers = {
            'Authorization': f'Bearer {access_token}'
        }
        
        user_response = requests.get('https://discord.com/api/users/@me', headers=headers)
        user_response.raise_for_status()
        user_data = user_response.json()
        
        # Check if user is in the specified guild
        guilds_response = requests.get('https://discord.com/api/users/@me/guilds', headers=headers)
        guilds_response.raise_for_status()
        guilds = guilds_response.json()
        
        if not any(g['id'] == GUILD_ID for g in guilds):
            return render_template('callback.html', 
                                success=False, 
                                error="You must be a member of the IntroVRT Lounge Discord server to use this application.",
                                version=VERSION,
                                commit_message=COMMIT_MESSAGE)
        
        session['user_data'] = user_data
        session['discord_token'] = access_token
        
        user = User(user_data['id'], user_data['username'], user_data.get('discriminator', '0'), user_data.get('avatar'))
        login_user(user, remember=True, duration=timedelta(hours=24))
        
        return render_template('callback.html', success=True, version=VERSION, commit_message=COMMIT_MESSAGE)
        
    except requests.exceptions.RequestException as e:
        print(f"OAuth error: {str(e)}")
        return render_template('callback.html', 
                            success=False, 
                            error="Failed to authenticate with Discord. Please try again.",
                            version=VERSION,
                            commit_message=COMMIT_MESSAGE)

@app.route('/upvrt/dashboard')
@login_required
def dashboard():
    # Get available channels
    headers = {
        'Authorization': f'Bot {DISCORD_BOT_TOKEN}'
    }
    channels_response = requests.get(
        f'https://discord.com/api/guilds/{GUILD_ID}/channels',
        headers=headers
    )
    channels = channels_response.json()
    text_channels = [c for c in channels if c['type'] == 0]  # 0 is text channel
    
    return render_template('dashboard.html', 
                         channels=text_channels,
                         progress_config=PROGRESS_CONFIG,
                         version=VERSION,
                         commit_message=COMMIT_MESSAGE)

@app.before_request
def before_request():
    session.permanent = True  # Set session to use PERMANENT_SESSION_LIFETIME
    # Log all requests
    logger.info(f"Request: {request.method} {request.path} from {request.remote_addr}")
    logger.info(f"Endpoint: {request.endpoint}")
    logger.info(f"URL: {request.url}")
    logger.info(f"Base URL: {request.base_url}")
    
    # Skip authentication for static files and certain endpoints
    if (request.path.startswith('/upvrt/static/') or 
        request.endpoint in ['login', 'callback', 'index', 'tos', 'privacy', 'static', 'health_check', 'debug_static', 'favicon', 'test_static']):
        logger.info("Skipping authentication for public endpoint")
        return None
        
    # Require authentication for all other endpoints
    if 'user_data' not in session:
        logger.info("No user_data in session, redirecting to login")
        return redirect(url_for('login'))

@app.route('/upvrt/check_auth')
def check_auth():
    if 'user_data' not in session:
        return jsonify({'authenticated': False}), 401
    return jsonify({'authenticated': True})

@app.route('/upvrt/logout')
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('index'))

DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')
DISCORD_REDIRECT_URI = os.getenv('DISCORD_REDIRECT_URI')
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
GUILD_ID = os.getenv('GUILD_ID')
UPLOAD_FOLDER = 'uploads'
MAX_DISCORD_SIZE = 10 * 1024 * 1024  # 10MB absolute limit for Discord
TARGET_SIZE_BYTES = 9.5 * 1024 * 1024  # Target 9.5MB for compression

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def get_video_duration(input_path):
    """Get video duration using ffprobe."""
    try:
        probe = subprocess.run([
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'json',
            input_path
        ], capture_output=True, text=True, check=True)
        
        duration = float(json.loads(probe.stdout)['format']['duration'])
        return duration
    except Exception as e:
        print(f"Error getting video duration: {e}")
        return None

def process_video_with_progress(input_path, output_path, task_id):
    """Process video using FFmpeg with progress tracking."""
    try:
        logger.info(f"Starting video processing for task {task_id}")
        logger.info(f"Input path: {input_path}")
        logger.info(f"Output path: {output_path}")
        
        duration = get_video_duration(input_path)
        if not duration:
            logger.error(f"Could not determine video duration for task {task_id}")
            tasks[task_id].fail("Could not determine video duration")
            return False

        progress = FFmpegProgress(duration)
        tasks[task_id] = progress
        logger.info(f"Video duration: {duration} seconds")

        watermark = "/app/assets/watermark.png"
        
        # Get video info for scaling
        probe = subprocess.run([
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'json',
            input_path
        ], capture_output=True, text=True, check=True)
        
        video_info = json.loads(probe.stdout)
        stream_info = video_info.get('streams', [{}])[0]
        video_width = stream_info.get('width', 1280)
        video_height = stream_info.get('height', 720)
        logger.info(f"Original video dimensions: {video_width}x{video_height}")
        
        # Calculate bitrate based on target size
        file_size = os.path.getsize(input_path)
        audio_bitrate_bps = 96 * 1024  # 96kbps for audio
        total_bitrate_bps = int((TARGET_SIZE_BYTES * 8) / duration)
        video_bitrate_bps = total_bitrate_bps - audio_bitrate_bps
        logger.info(f"Calculated bitrates - Total: {total_bitrate_bps/1024:.2f}kbps, Video: {video_bitrate_bps/1024:.2f}kbps, Audio: {audio_bitrate_bps/1024:.2f}kbps")
        
        # Set minimum video bitrate
        min_video_bitrate_bps = 300 * 1024  # 300kbps minimum
        if video_bitrate_bps < min_video_bitrate_bps:
            logger.info(f"Adjusting video bitrate to minimum: {min_video_bitrate_bps/1024:.2f}kbps")
            video_bitrate_bps = min_video_bitrate_bps
        
        # Determine if video is portrait or landscape
        is_portrait = video_height > video_width
        scale_dimensions = "720:1280" if is_portrait else "1280:720"
        
        # Calculate watermark dimensions (20% of width)
        watermark_width = int(1280 * 0.2) if not is_portrait else int(720 * 0.2)
        watermark_height = int(watermark_width * 9 / 16)  # Maintain 16:9 aspect ratio
        
        # Process video with FFmpeg and capture progress
        logger.info("Starting FFmpeg processing")
        process = subprocess.Popen([
            'ffmpeg', '-i', input_path, '-i', watermark,
            '-filter_complex', f'[0:v]scale={scale_dimensions}[v];[1:v]scale={watermark_width}:{watermark_height}[wm];[v][wm]overlay=W-w-10:H-h-10:format=auto:alpha=0.7',
            '-c:v', 'libx264',
            '-b:v', str(video_bitrate_bps),
            '-preset', 'fast',
            '-profile:v', 'baseline',
            '-level', '3.1',
            '-metadata:s:v:0', 'rotate=0',
            '-pix_fmt', 'yuv420p',
            '-r', '30',
            '-c:a', 'aac',
            '-b:a', '96k',
            '-progress', 'pipe:1',
            output_path
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)

        # Log FFmpeg stderr output in real-time
        def log_stderr():
            for line in process.stderr:
                logger.info(f"FFmpeg: {line.strip()}")
        stderr_thread = threading.Thread(target=log_stderr)
        stderr_thread.daemon = True
        stderr_thread.start()

        # Parse FFmpeg progress output
        time_pattern = re.compile(r'out_time_ms=(\d+)')
        while True:
            line = process.stdout.readline()
            if not line:
                break
            
            match = time_pattern.search(line)
            if match:
                time_ms = int(match.group(1)) / 1000000.0  # Convert microseconds to seconds
                progress.update(time_ms)
                if int(time_ms) % 5 == 0:  # Log progress every 5 seconds
                    logger.info(f"Processing progress: {progress.percent:.1f}% ({time_ms:.1f}s / {duration:.1f}s)")

        process.wait()
        
        if process.returncode == 0:
            # Check if output file exists
            if not os.path.exists(output_path):
                error = "Output file was not created"
                logger.error(f"Video processing failed for task {task_id}: {error}")
                progress.fail(error)
                return False
                
            # Check if compressed file is over Discord's limit
            output_size = os.path.getsize(output_path)
            logger.info(f"Output file size: {output_size/1024/1024:.2f}MB")
            if output_size > MAX_DISCORD_SIZE:
                error = f"File is over 10MB ({output_size/1024/1024:.2f}MB) and cannot be sent to Discord"
                logger.error(f"Video processing failed for task {task_id}: {error}")
                progress.fail(error)
                return False
                
            logger.info(f"Video processing completed successfully for task {task_id}")
            progress.complete()
            return True
        else:
            error = process.stderr.read() if process.stderr else "Unknown error"
            logger.error(f"Video processing failed for task {task_id}: {error}")
            progress.fail(error)
            return False
            
    except Exception as e:
        logger.error(f"Error processing video for task {task_id}: {str(e)}", exc_info=True)
        if task_id in tasks:
            tasks[task_id].fail(str(e))
        return False

@app.route('/upvrt/tos')
def tos():
    return render_template('tos.html', 
                         current_date=datetime.now().strftime('%B %d, %Y'),
                         version=VERSION,
                         commit_message=COMMIT_MESSAGE)

@app.route('/upvrt/privacy')
def privacy():
    return render_template('privacy.html', 
                         current_date=datetime.now().strftime('%B %d, %Y'),
                         version=VERSION,
                         commit_message=COMMIT_MESSAGE)

@app.route('/upvrt/health')
def health_check():
    """Health check endpoint"""
    return 'ok'

@app.route('/upvrt/upload', methods=['POST'])
@login_required
def upload_video():
    logger.info(f"Upload attempt from user {current_user.id} ({current_user.name})")
    if 'video' not in request.files:
        logger.error("No video file in request")
        return 'No video file uploaded', 400
        
    file = request.files['video']
    channel_id = request.form.get('channel_id')
    
    if not file or not channel_id:
        logger.error("Missing required fields")
        return 'Missing required fields', 400
        
    if not file.filename.endswith('.mp4'):
        logger.error(f"Invalid file type: {file.filename}")
        return 'Only MP4 files are allowed', 400
        
    filename = secure_filename(file.filename)
    input_path = os.path.join(UPLOAD_FOLDER, filename)
    output_path = os.path.join(UPLOAD_FOLDER, f'compressed_{filename}')
    
    logger.info(f"Saving uploaded file: {filename}")
    file.save(input_path)
    
    # Check file size (100MB limit)
    file_size = os.path.getsize(input_path)
    logger.info(f"File size: {file_size / (1024*1024):.2f}MB")
    if file_size > 100 * 1024 * 1024:
        logger.error(f"File too large: {file_size / (1024*1024):.2f}MB")
        os.remove(input_path)
        return 'Please upload videos under 100MB. Larger files may result in poor quality when compressed to a 10MB 720p file.', 400
    
    # Generate task ID and start processing in background
    task_id = str(uuid.uuid4())
    logger.info(f"Starting task {task_id} for file {filename}")
    
    # Capture user ID before starting background thread
    user_id = current_user.id
    
    def process_and_upload():
        try:
            # Process video
            if not process_video_with_progress(input_path, output_path, task_id):
                return
            
            # Upload to Discord
            tasks[task_id].set_stage('posting', 0)
            headers = {
                'Authorization': f'Bot {DISCORD_BOT_TOKEN}'
            }
            
            with open(output_path, 'rb') as f:
                files = {
                    'file': (filename, f)
                }
                message = f"Here's your compressed video! <@{user_id}>"
                response = requests.post(
                    f'https://discord.com/api/channels/{channel_id}/messages',
                    headers=headers,
                    data={'content': message},
                    files=files
                )
                
                if response.status_code != 200:
                    tasks[task_id].fail(f'Error uploading to Discord: {response.text}')
                    return
                
                # Get message link
                message_data = response.json()
                message_link = f"https://discord.com/channels/{GUILD_ID}/{channel_id}/{message_data['id']}"
                tasks[task_id].complete(message_link)
            
        except Exception as e:
            logger.error(f"Error in process_and_upload: {str(e)}", exc_info=True)
            tasks[task_id].fail(str(e))
        finally:
            # Clean up files
            if os.path.exists(input_path):
                os.remove(input_path)
            if os.path.exists(output_path):
                os.remove(output_path)
    
    # Start processing thread
    thread = threading.Thread(target=process_and_upload)
    thread.start()
    
    return jsonify({'task_id': task_id})

@app.route('/upvrt/progress/<task_id>')
@login_required
def get_progress(task_id):
    """Get the progress of a video processing task."""
    if task_id not in tasks:
        return jsonify({'error': 'Task not found'}), 404
    
    progress = tasks[task_id]
    return jsonify({
        'status': progress.status,
        'stage': progress.stage,
        'percent': progress.percent,
        'error': progress.error,
        'message_link': progress.message_link
    })

if __name__ == '__main__':
    app.run(debug=True) 