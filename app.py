import os
import logging
from flask import Flask, render_template, request, jsonify, send_file
from dotenv import load_dotenv
import requests
import io
import threading

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)

# Import video-related functions
try:
    from video import upload_video, process_video, read_prompt_from_file, save_to_csv
except ImportError as e:
    logger.error(f"Error importing video functions: {e}")
    raise

# Dictionary to store processing tasks
processing_tasks = {}

@app.route('/', methods=['GET'])
def index():
    logger.debug("Index route accessed")
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process():
    logger.debug("Process route accessed")
    video_url = request.form['video_url']
    title = request.form['title']
    genres = request.form.getlist('genre')
    duration = int(request.form['duration'])
    duration_type = request.form.get('durationType', 'seconds')  # 'seconds' or 'percentage'
    
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
    if duration_type == 'percentage':
        user_prompt = f"Create a summary that is {duration}% of the original video length for a {', '.join(genres)} video titled '{title}'."
    else:
        user_prompt = f"Create a {duration//60}-minute and {duration%60}-second summary for a {', '.join(genres)} video titled '{title}'."
    full_prompt = f"{base_prompt}\n\nSpecific instructions: {user_prompt}"
    
    # Start processing in a separate thread
    task_id = video.id
    processing_tasks[task_id] = {'status': 'processing', 'progress': 0}
    thread = threading.Thread(target=process_video_thread, args=(video, full_prompt, video_url, duration, duration_type, task_id))
    thread.start()
    
    return jsonify({"message": "Video uploaded successfully. Processing started.", "task_id": task_id}), 202

@app.route('/status/<task_id>')
def status(task_id):
    task = processing_tasks.get(task_id, {'status': 'not_found'})
    return jsonify(task)

def process_video_thread(video, full_prompt, video_url, duration, duration_type, task_id):
    def progress_callback(progress):
        processing_tasks[task_id]['progress'] = progress

    try:
        stream_url = process_video(video, full_prompt, progress_callback, target_duration=duration, duration_type=duration_type)
        if stream_url:
            save_to_csv(video_url, full_prompt, stream_url)
            processing_tasks[task_id] = {'status': 'completed', 'stream_url': stream_url}
        else:
            logger.error("Video processing failed or returned no stream URL")
            processing_tasks[task_id] = {'status': 'error'}
    except Exception as e:
        logger.error(f"Error processing video: {str(e)}")
        processing_tasks[task_id] = {'status': 'error', 'message': str(e)}

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
        logger.error(f"Error downloading video: {str(e)}")
        return jsonify({"error": "Failed to download video"}), 500

@app.route('/result')
def result():
    stream_url = request.args.get('stream_url', '')
    return render_template('result.html', stream_url=stream_url)

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    logger.info("Starting the application")
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)