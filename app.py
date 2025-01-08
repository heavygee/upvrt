import os
from flask import Flask, redirect, request, url_for, session, render_template, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, current_user, logout_user
from flask_cors import CORS
import requests
from dotenv import load_dotenv
import subprocess
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime, timedelta

load_dotenv()

app = Flask(__name__)
CORS(app, resources={
    r"/upvrt/*": {
        "origins": ["https://www.introvrtlounge.com"],
        "supports_credentials": True
    }
})
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = os.urandom(24)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
app.config['STATIC_FOLDER'] = 'static'
app.config['STATIC_URL_PATH'] = '/upvrt/static'
app.config['SESSION_COOKIE_NAME'] = 'upvrt_session'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_PATH'] = '/upvrt/'
app.config['REMEMBER_COOKIE_SECURE'] = True
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(hours=24)
app.config['REMEMBER_COOKIE_PATH'] = '/upvrt/'

@app.before_request
def before_request():
    session.permanent = True  # Set session to use PERMANENT_SESSION_LIFETIME
    if 'user_data' not in session and request.endpoint not in ['login', 'callback', 'index', 'tos', 'privacy', 'static']:
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

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')
DISCORD_REDIRECT_URI = os.getenv('DISCORD_REDIRECT_URI')
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
GUILD_ID = os.getenv('GUILD_ID')
UPLOAD_FOLDER = 'uploads'
TARGET_SIZE_BYTES = 10 * 1000 * 950  # Discord upload size limit (slightly under 10MB)

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def process_video(input_path, output_path):
    """Process video using advanced FFmpeg settings."""
    try:
        watermark = "/app/assets/watermark.png"
        # Get video duration and size
        probe = subprocess.run([
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,duration:format=duration',
            '-of', 'json',
            input_path
        ], capture_output=True, text=True, check=True)
        
        import json
        video_info = json.loads(probe.stdout)
        duration = float(video_info.get('format', {}).get('duration', 0))
        stream_info = video_info.get('streams', [{}])[0]
        video_width = stream_info.get('width', 1280)
        video_height = stream_info.get('height', 720)
        
        # Calculate bitrate based on target size
        file_size = os.path.getsize(input_path)
        audio_bitrate_bps = 96 * 1024  # 96kbps for audio
        total_bitrate_bps = int((TARGET_SIZE_BYTES * 8) / duration)
        video_bitrate_bps = total_bitrate_bps - audio_bitrate_bps
        
        # Set minimum video bitrate
        min_video_bitrate_bps = 300 * 1024  # 300kbps minimum
        if video_bitrate_bps < min_video_bitrate_bps:
            video_bitrate_bps = min_video_bitrate_bps
            
        # Determine if video is portrait or landscape
        is_portrait = video_height > video_width
        scale_dimensions = "720:1280" if is_portrait else "1280:720"
        
        # Calculate watermark dimensions (20% of width)
        watermark_width = int(1280 * 0.2) if not is_portrait else int(720 * 0.2)
        watermark_height = int(watermark_width * 9 / 16)  # Maintain 16:9 aspect ratio
        
        # Process video with FFmpeg
        subprocess.run([
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
            output_path
        ], check=True)
        
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error processing video: {e}")
        return False

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
    return render_template('index.html')

@app.route('/upvrt/login')
def login():
    # Store the original URL the user was trying to access
    next_url = request.args.get('next', url_for('dashboard'))
    session['next_url'] = next_url
    
    oauth_url = f'https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={DISCORD_REDIRECT_URI}&response_type=code&scope=identify%20guilds%20guilds.members.read'
    return render_template('login.html', oauth_url=oauth_url)

@app.route('/upvrt/callback')
def callback():
    error = request.args.get('error')
    if error:
        return render_template('callback.html', success=False, error=error)
        
    code = request.args.get('code')
    if not code:
        return render_template('callback.html', success=False, error='No authorization code received')
        
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
                                error="You must be a member of the IntroVRT Lounge Discord server to use this application.")
        
        session['user_data'] = user_data
        session['discord_token'] = access_token
        
        user = User(user_data['id'], user_data['username'], user_data.get('discriminator', '0'), user_data.get('avatar'))
        login_user(user, remember=True, duration=timedelta(hours=24))
        
        return render_template('callback.html', success=True)
        
    except requests.exceptions.RequestException as e:
        print(f"OAuth error: {str(e)}")
        return render_template('callback.html', 
                            success=False, 
                            error="Failed to authenticate with Discord. Please try again.")

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
    
    return render_template('dashboard.html', channels=text_channels)

@app.route('/upvrt/upload', methods=['POST'])
@login_required
def upload_video():
    if 'video' not in request.files:
        return 'No video file uploaded', 400
        
    file = request.files['video']
    channel_id = request.form.get('channel_id')
    
    if not file or not channel_id:
        return 'Missing required fields', 400
        
    if not file.filename.endswith('.mp4'):
        return 'Only MP4 files are allowed', 400
        
    filename = secure_filename(file.filename)
    input_path = os.path.join(UPLOAD_FOLDER, filename)
    output_path = os.path.join(UPLOAD_FOLDER, f'compressed_{filename}')
    
    file.save(input_path)
    
    # Check file size (100MB limit)
    if os.path.getsize(input_path) > 100 * 1024 * 1024:
        os.remove(input_path)
        return 'File too large (max 100MB)', 400
    
    # Process video using our enhanced function
    if not process_video(input_path, output_path):
        os.remove(input_path)
        if os.path.exists(output_path):
            os.remove(output_path)
        return 'Error processing video', 500
    
    # Check if compressed file is under target size
    if os.path.getsize(output_path) > TARGET_SIZE_BYTES:
        os.remove(input_path)
        os.remove(output_path)
        return 'Could not compress video under 10MB', 400
    
    # Upload to Discord
    headers = {
        'Authorization': f'Bot {DISCORD_BOT_TOKEN}'
    }
    
    try:
        with open(output_path, 'rb') as f:
            files = {
                'file': (filename, f)
            }
            message = f"Here's your compressed video! <@{current_user.id}>"
            response = requests.post(
                f'https://discord.com/api/channels/{channel_id}/messages',
                headers=headers,
                data={'content': message},
                files=files
            )
            
            print(f"Discord API Response: Status={response.status_code}, Content={response.text}")
            
            if response.status_code != 200:
                print(f"Error uploading to Discord: {response.text}")
                return f'Error uploading to Discord: {response.text}', 500
    except Exception as e:
        print(f"Exception during upload: {str(e)}")
        return f'Error during upload: {str(e)}', 500
    finally:
        # Clean up files
        if os.path.exists(input_path):
            os.remove(input_path)
        if os.path.exists(output_path):
            os.remove(output_path)
    
    if response.status_code == 200:
        return 'Video uploaded successfully'
    else:
        return 'Error uploading to Discord', 500

@app.route('/upvrt/tos')
def tos():
    return render_template('tos.html', current_date=datetime.now().strftime('%B %d, %Y'))

@app.route('/upvrt/privacy')
def privacy():
    return render_template('privacy.html', current_date=datetime.now().strftime('%B %d, %Y'))

@app.route('/upvrt/health')
def health_check():
    """Health check endpoint"""
    return 'ok'

if __name__ == '__main__':
    app.run(debug=True) 