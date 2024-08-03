import os
import json
import concurrent.futures
import csv
from dotenv import load_dotenv
import videodb
from videodb import SearchType
from videodb.timeline import Timeline, VideoAsset
from llm_agent import LLM, LLMType, Models
import logging
from typing import List, Tuple
import random

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

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
        logger.warning(f"{filename} not found. Using default prompt.")
        return "Analyze the following content and create a concise summary."

def upload_video(url):
    """
    Upload a video to VideoDB
    """
    try:
        logger.info(f"Attempting to upload video from URL: {url}")
        video = conn.upload(url=url)
        logger.info(f"Video uploaded successfully. Video ID: {video.id}")
        logger.info("Indexing spoken words...")
        video.index_spoken_words()
        logger.info("Spoken words indexed successfully.")
        return video
    except Exception as e:
        logger.error(f"Error uploading video: {str(e)}")
        return None

def chunk_transcript(docs, chunk_size):
    """
    Chunk transcript to fit into context of your LLM
    """
    return [docs[i:i + chunk_size] for i in range(0, len(docs), chunk_size)]

def send_msg_to_llm(chunk_prompt):
    """
    Send a message to the LLM and parse the response
    """
    response = llm.chat(message=chunk_prompt)
    output = json.loads(response["choices"][0]["message"]["content"])
    return output.get('sentences', [])

def text_prompter(transcript_text, prompt):
    """
    Process the transcript text using the given prompt
    """
    chunk_size = llm.get_word_limit()
    chunks = chunk_transcript(transcript_text, chunk_size=chunk_size)

    matches = []
    prompts = []

    for chunk in chunks:
        chunk_prompt = f"""
        You are a video editor who uses AI. Given a user prompt and transcript of a video, analyze the text to identify sentences in the transcript relevant to the user prompt for making clips. 
        - Instructions: 
          - Evaluate the sentences for relevance to the specified user prompt.
          - Make sure that sentences start and end properly and meaningfully complete the discussion or topic. Choose the one with the greatest relevance and longest.
          - We'll use the sentences to make video clips in future, so optimize for great viewing experience for people watching the clip of these.
          - If the matched sentences are not too far, merge them into one sentence.
          - Strictly make each result minimum 20 words long. If the match is smaller, adjust the boundaries and add more context around the sentences.

        Transcript: {chunk}
        User Prompt: {prompt}

        Ensure the final output strictly adheres to the JSON format specified without including additional text or explanations. 
        If there is no match return empty list without additional text. Use the following structure for your response:
        {{
          "sentences": [
            "sentence 1",
            "sentence 2",
            ...
          ]
        }}
        """
        prompts.append(chunk_prompt)

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_to_index = {executor.submit(send_msg_to_llm, prompt): prompt for prompt in prompts}
        for future in concurrent.futures.as_completed(future_to_index):
            try:
                matches.extend(future.result())
            except Exception as e:
                logger.error(f"Chunk failed to work with LLM {str(e)}")
    
    return matches

def rank_segments_by_narrative_structure(segments: List[Tuple[float, float, str]], video_duration: float) -> List[Tuple[float, float, str]]:
    def position_score(start, end):
        mid = (start + end) / 2
        if mid < video_duration * 0.1:  # Introduction
            return 5
        elif mid > video_duration * 0.9:  # Resolution
            return 4
        elif video_duration * 0.4 < mid < video_duration * 0.6:  # Climax
            return 3
        elif video_duration * 0.1 <= mid <= video_duration * 0.4:  # Rising Action
            return 2
        else:  # Falling Action
            return 1

    return sorted(segments, key=lambda s: position_score(s[0], s[1]), reverse=True)

def process_video(video, user_prompt, progress_callback=None, target_duration=300, duration_type='seconds'):
    try:
        base_prompt = read_prompt_from_file()
        full_prompt = f"{base_prompt}\n\nSpecific instructions: {user_prompt}"
        
        transcript_text = video.get_transcript_text()
        logger.info(f"Transcript length: {len(transcript_text)} characters")
        
        result = text_prompter(transcript_text, full_prompt)
        logger.info(f"Text prompter found: {len(result)} relevant sentences")

        if not result:
            logger.warning("No relevant sentences found in the transcript.")
            return None

        # Get all relevant segments
        all_segments = []
        for clip_sentence in result:
            search_res = video.search(clip_sentence, search_type=SearchType.keyword)
            matched_segments = search_res.get_shots()
            for segment in matched_segments:
                all_segments.append((segment.start, segment.end, clip_sentence))

        # If we need the video duration for percentage calculations, we can estimate it
        # from the last end time of all segments
        if duration_type == 'percentage' and all_segments:
            estimated_duration = max(segment[1] for segment in all_segments)
            target_duration = (target_duration / 100) * estimated_duration

        # Sort segments based on start time
        sorted_segments = sorted(all_segments, key=lambda x: x[0])

        # Create a timeline
        timeline = Timeline(conn)

        total_duration = 0
        assets_added = 0

        for start, end, sentence in sorted_segments:
            segment_duration = end - start
            if total_duration + segment_duration > target_duration:
                # If adding this segment would exceed the target duration, skip it
                continue

            timeline.add_inline(VideoAsset(asset_id=video.id, start=start, end=end))
            total_duration += segment_duration
            assets_added += 1

            logger.info(f"Added asset for sentence: {sentence[:50]}...")

            # Report progress
            if progress_callback:
                progress = min(100, (total_duration / target_duration) * 100)
                progress_callback(progress)

            if total_duration >= target_duration:
                break

        if assets_added == 0:
            logger.warning("No VideoAssets were added to the timeline. The processed video might be empty.")
            return None

        logger.info(f"Added {assets_added} VideoAssets to the timeline. Total duration: {total_duration:.2f} seconds")

        # Generate the stream
        stream_url = timeline.generate_stream()
        logger.info(f"Generated stream URL: {stream_url}")
        return stream_url
    except Exception as e:
        logger.error(f"Error processing video: {str(e)}", exc_info=True)
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
    
    logger.info("\nResults saved to video_processing_results.csv")
    logger.info("\nCurrent results:")
    logger.info(f"Video URL: {video_url}")
    logger.info(f"Prompt: {prompt}")
    logger.info(f"Stream Link: {stream_link}")

def main():
    video_url = input("Enter the video URL: ")
    title = input("Enter the video title: ")
    genres = input("Enter genres (comma-separated): ").split(',')
    duration = int(input("Enter desired summary duration in seconds: "))

    video = upload_video(video_url)
    if video is None:
        logger.error("Error uploading video. Please try again.")
        return

    base_prompt = read_prompt_from_file()
    user_prompt = f"Create a {duration//60}-minute and {duration%60}-second summary for a {', '.join(genres)} video titled '{title}'."
    full_prompt = f"{base_prompt}\n\nSpecific instructions: {user_prompt}"

    stream_url = process_video(video, full_prompt)
    if stream_url:
        save_to_csv(video_url, full_prompt, stream_url)
        logger.info(f"Processed video stream URL: {stream_url}")
        videodb.play_stream(stream_url)  # Play the video stream for testing
    else:
        logger.error("Error processing video.")

if __name__ == "__main__":
    main()