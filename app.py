import os
import logging
import uuid
import threading
import time
from flask import Flask, render_template, request, jsonify, redirect, url_for
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Create Flask app
app = Flask(__name__)

# Set up logging
if __name__ != '__main__':
    # When running with Gunicorn
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
else:
    # When running directly with Python (development)
    logging.basicConfig(level=logging.DEBUG)
    app.logger.setLevel(logging.DEBUG)

# Import video-related functions
try:
    from video import process_video
except ImportError as e:
    app.logger.error(f"Error importing video functions: {e}")
    raise

# Dictionary to store processing tasks
processing_tasks = {}

@app.route('/', methods=['GET'])
def index():
    app.logger.debug("Index route accessed")
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process():
    start_time = time.time()
    app.logger.debug("Process route accessed")
    
    try:
        video_url = request.form['video_url']
        title = request.form['title']
        genres = request.form.getlist('genre')
        duration = int(request.form['duration'])
        duration_type = request.form.get('durationType', 'seconds')
        
        app.logger.info(f"Received request for video: {video_url}, title: {title}, duration: {duration} {duration_type}")
        
        # Generate a task ID immediately
        task_id = str(uuid.uuid4())
        processing_tasks[task_id] = {'status': 'queued', 'progress': 0}
        
        # Start processing in a separate thread
        thread = threading.Thread(target=process_video_async, args=(task_id, video_url, title, genres, duration, duration_type))
        thread.start()
        
        app.logger.info(f"Task {task_id} created and processing started")
        return jsonify({'task_id': task_id})
    
    except Exception as e:
        app.logger.error(f"Error in process route: {e}")
        return jsonify({'error': 'Failed to start processing'}), 500

def process_video_async(task_id, video_url, title, genres, duration, duration_type):
    try:
        processing_tasks[task_id]['status'] = 'processing'
        
        # Process the video and get the stream URL
        stream_url = process_video(video_url, title, genres, duration, duration_type)
        
        processing_tasks[task_id] = {
            'status': 'completed',
            'progress': 100,
            'stream_url': stream_url
        }
        
        app.logger.info(f"Video processing completed for task {task_id}. Stream URL: {stream_url}")
    
    except Exception as e:
        app.logger.error(f"Error processing video for task {task_id}: {e}")
        processing_tasks[task_id] = {'status': 'error', 'message': str(e)}

@app.route('/status/<task_id>')
def status(task_id):
    task = processing_tasks.get(task_id, {'status': 'not_found'})
    app.logger.info(f"Status request for task {task_id}. Current status: {task}")
    response = jsonify(task)
    app.logger.info(f"Sending response for task {task_id}: {response.get_data(as_text=True)}")
    return response

@app.route('/result')
def result():
    stream_url = request.args.get('stream_url', '')
    app.logger.info(f"Result route accessed with stream_url: {stream_url}")
    if not stream_url:
        app.logger.warning("Result route accessed without stream_url")
        return redirect(url_for('index'))
    return render_template('result.html', stream_url=stream_url)

if __name__ == '__main__':
    app.logger.info("Starting the application in development mode")
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
