import os
import logging
import warnings
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
from dotenv import load_dotenv
import urllib3

# Suppress the OpenSSL warning
warnings.filterwarnings("ignore", category=urllib3.exceptions.NotOpenSSLWarning)

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
socketio = SocketIO(app)

# Import video-related functions
try:
    from video import upload_video, process_video, read_prompt_from_file, save_to_csv
except ImportError as e:
    logger.error(f"Error importing video functions: {e}")
    raise

import threading

@app.route('/', methods=['GET', 'POST'])
def index():
    logger.debug("Index route accessed")
    if request.method == 'POST':
        logger.debug("POST request received")
        video_url = request.form['video_url']
        title = request.form['title']
        genres = request.form.getlist('genre')
        duration = int(request.form['duration'])
        
        # Handle "Other" genre
        if 'Other' in genres:
            genres.remove('Other')
            other_genre = request.form.get('otherGenre')
            if other_genre:
                genres.append(other_genre)
        
        video = upload_video(video_url)
        if video is None:
            error_message = "Error uploading video. Please check the URL and try again."
            logger.error(f"Failed to upload video from URL: {video_url}")
            return jsonify({"error": error_message}), 400
        
        base_prompt = read_prompt_from_file()
        user_prompt = f"Create a {duration//60}-minute and {duration%60}-second summary for a {', '.join(genres)} video titled '{title}'."
        full_prompt = f"{base_prompt}\n\nSpecific instructions: {user_prompt}"
        
        # Start processing in a separate thread
        thread = threading.Thread(target=process_video_with_progress, args=(video, full_prompt, video_url))
        thread.start()
        
        return jsonify({"message": "Video uploaded successfully. Processing started."}), 202
    
    return render_template('index.html')

def process_video_with_progress(video, full_prompt, video_url):
    def progress_callback(progress):
        socketio.emit('progress_update', {'progress': progress})

    stream_url = process_video(video, full_prompt, progress_callback)
    if stream_url:
        save_to_csv(video_url, full_prompt, stream_url)
        socketio.emit('processing_complete', {'stream_url': stream_url})
    else:
        logger.error("Video processing failed or returned no stream URL")
        socketio.emit('processing_error')

@app.route('/result')
def result():
    stream_url = request.args.get('stream_url', '')
    return render_template('result.html', stream_url=stream_url)

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    logger.info("Starting the application")
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=True, host='0.0.0.0', port=port)