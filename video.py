import os
import json
import concurrent.futures
import csv
from dotenv import load_dotenv
import videodb
from IPython.display import display, HTML
from videodb import SearchType
from videodb.timeline import Timeline, VideoAsset
from llm_agent import LLM, LLMType, Models

load_dotenv()

# Set up VideoDB connection
conn = videodb.connect()

# Set up LLM
llm = LLM(llm_type=LLMType.OPENAI, model=Models.GPT4)

def read_prompt_from_file(filename="spoiler_prompt.txt"):
    """
    Read the prompt from a file.
    """
    try:
        with open(filename, 'r') as file:
            return file.read().strip()
    except FileNotFoundError:
        print(f"Warning: {filename} not found. Using default prompt.")
        return "Analyze the following content and create a concise summary."

# ... (keep all the previous functions: get_video, chunk_transcript, send_msg_to_llm, text_prompter, upload_video) ...

def process_video(video, user_prompt):
    """
    Process the video using text_prompter and create a timeline
    """
    try:
        # Read the base prompt from file
        base_prompt = read_prompt_from_file()
        
        # Combine the base prompt with the user's specific prompt
        full_prompt = f"{base_prompt}\n\nSpecific instructions: {user_prompt}"
        
        # Use text_prompter to find relevant sentences
        result = text_prompter(video.get_transcript_text(), full_prompt)
        print(f"Text prompter found: {result['type']}")

        # Create a timeline
        timeline = Timeline(conn)

        assets_added = 0
        for clip_sentence in result:
            search_res = video.search(clip_sentence, search_type=SearchType.keyword)
            matched_segments = search_res.get_shots()

            if len(matched_segments) == 0:
                continue

            video_shot = matched_segments[0]
            timeline.add_inline(VideoAsset(asset_id=video.id, start=video_shot.start, end=video_shot.end))
            assets_added += 1
            print(f"Added asset for sentence: {clip_sentence[:50]}...")

        if assets_added == 0:
            print("No VideoAssets were added to the timeline. The processed video might be empty.")
            return None

        print(f"Added {assets_added} VideoAssets to the timeline.")

        # Generate the stream
        stream = timeline.generate_stream()
        return stream
    except Exception as e:
        print(f"Error processing video: {str(e)}")
        return None

def save_to_csv(video_url, prompt, stream_link):
    """
    Save the video processing results to a CSV file and display them.
    """
    filename = "video_processing_results.csv"
    file_exists = os.path.isfile(filename)
    
    with open(filename, mode='a', newline='') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(["Video URL", "Prompt", "Stream Link"])
        writer.writerow([video_url, prompt, stream_link])
    
    print("\nResults saved to video_processing_results.csv")
    print("\nCurrent results:")
    print(f"Video URL: {video_url}")
    print(f"Prompt: {prompt}")
    print(f"Stream Link: {stream_link}")

def main():
    while True:
        video_source = input("Enter video URL or local file path (or 'q' to quit): ")
        if video_source.lower() == 'q':
            break
        
        video = upload_video(video_source)
        if video is None:
            continue
        
        prompt = input("Enter your prompt (e.g., 'find sentences where a deal is discussed' or 'create a summary'): ")
        
        stream_url = process_video(video, prompt)
        if stream_url is None:
            print("Failed to create a video stream. Please try a different prompt or video.")
            continue
        
        print("Processed video stream ready. Here's the stream URL:")
        print(stream_url)
        
        # Save and display results
        save_to_csv(video_source, prompt, stream_url)
        
        display(HTML(f'<video width="640" height="480" controls><source src="{stream_url}" type="video/mp4"></video>'))
        
        play_choice = input("Would you like to play the processed video? (y/n): ")
        if play_choice.lower() == 'y':
            videodb.play_stream(stream_url)
        
        print("\nVideo processing complete. You can use the stream URL to view the processed video.")

if __name__ == "__main__":
    main()