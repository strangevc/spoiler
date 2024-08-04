import os
import logging
import uuid
import time
import threading
from flask import Flask, render_template, request, jsonify, send_file, current_app
from dotenv import load_dotenv
import requests
import io

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
    from video import upload_video, process_video, read_prompt_from_file, save_to_csv
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
        
        end_time = time.time()
        app.logger.info(f"Process route completed in {end_time - start_time:.2f} seconds")
        
        return jsonify({
            "message": "Request received. Processing queued.",
            "task_id": task_id
        }), 202
    
    except Exception as e:
        app.logger.exception(f"Error in process route: {str(e)}")
        return jsonify({"error": "An unexpected error occurred. Please try again."}), 500

def process_video_async(task_id, video_url, title, genres, duration, duration_type):
    app.logger.info(f"Starting async processing for task {task_id}")
    try:
        processing_tasks[task_id]['status'] = 'uploading'
        video = upload_video(video_url)
        if video is None:
            processing_tasks[task_id] = {'status': 'error', 'message': 'Failed to upload video'}
            app.logger.error(f"Failed to upload video from URL: {video_url}")
            return

        processing_tasks[task_id]['status'] = 'processing'
        base_prompt = read_prompt_from_file()
        if duration_type == 'percentage':
            user_prompt = f"Create a summary that is {duration}% of the original video length for a {', '.join(genres)} video titled '{title}'."
        else:
            user_prompt = f"Create a {duration//60}-minute and {duration%60}-second summary for a {', '.join(genres)} video titled '{title}'."
        full_prompt = f"{base_prompt}\n\nSpecific instructions: {user_prompt}"

        def progress_callback(progress):
            processing_tasks[task_id]['progress'] = progress
            app.logger.debug(f"Task {task_id} progress: {progress}%")

stream_url = process_video(video, full_prompt, progress_callback, target_duration=duration, duration_type=duration_type)
           if stream_url:
               save_to_csv(video_url, full_prompt, stream_url)
               processing_tasks[task_id] = {'status': 'completed', 'stream_url': stream_url}
               app.logger.info(f"Video processing completed for task {task_id}. Stream URL: {stream_url}")
           else:
               processing_tasks[task_id] = {'status': 'error', 'message': 'Processing failed to generate a stream URL'}
               app.logger.error(f"Video processing failed or returned no stream URL for task {task_id}")
       except Exception as e:
           processing_tasks[task_id] = {'status': 'error', 'message': str(e)}
           app.logger.exception(f"Error processing video for task {task_id}: {str(e)}")
       
       app.logger.info(f"Final task status for {task_id}: {processing_tasks.get(task_id)}")


@app.route('/status/<task_id>')
   def status(task_id):
       task = processing_tasks.get(task_id, {'status': 'not_found'})
       app.logger.info(f"Status request for task {task_id}. Current status: {task}")
       return jsonify(task)

@app.route('/download/<path:stream_url>')
def download_video(stream_url):
    try:
        # Download the video content
        response = requests.get(stream_url)
        response.raise_for_status()

        # Create an in-memory file-like object
        video_file = io.BytesIO(response.content)

        # Generate a filename (you might want to use a more meaningful name)
        filename = "spoiler_video.mp4"

        # Send the file
        return send_file(
            video_file,
            as_attachment=True,
            download_name=filename,
            mimetype='video/mp4'
        )
    except Exception as e:
        app.logger.error(f"Error downloading video: {str(e)}")
        return jsonify({"error": "Failed to download video"}), 500

@app.route('/result')
def result():
    stream_url = request.args.get('stream_url', '')
    return render_template('result.html', stream_url=stream_url)

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok"}), 200

@app.route('/test', methods=['GET'])
def test():
    app.logger.info("Test route accessed")
    return jsonify({"message": "Test successful", "env": app.config['ENV']}), 200

if __name__ == '__main__':
    app.logger.info("Starting the application in development mode")
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)