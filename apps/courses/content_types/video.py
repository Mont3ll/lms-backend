import json
import logging
import os
import subprocess
import tempfile
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def get_video_duration(file_path_or_url: str) -> Optional[float]:
    """
    Get the duration of a video file using ffprobe.
    
    Args:
        file_path_or_url: Local file path or URL to the video
    
    Returns:
        Duration in seconds as a float, or None if unable to determine
    """
    if not file_path_or_url:
        logger.warning("No file path or URL provided for video duration")
        return None
    
    try:
        # Use ffprobe to get video duration
        # ffprobe is part of ffmpeg and can handle both local files and URLs
        cmd = [
            'ffprobe',
            '-v', 'quiet',  # Suppress verbose output
            '-print_format', 'json',  # Output as JSON
            '-show_format',  # Show format info (includes duration)
            '-show_streams',  # Show stream info
            file_path_or_url
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30  # Timeout after 30 seconds
        )
        
        if result.returncode != 0:
            logger.error(f"ffprobe failed for {file_path_or_url}: {result.stderr}")
            return None
        
        # Parse JSON output
        probe_data = json.loads(result.stdout)
        
        # Try to get duration from format info first
        if 'format' in probe_data and 'duration' in probe_data['format']:
            duration = float(probe_data['format']['duration'])
            logger.info(f"Video duration for {file_path_or_url}: {duration:.2f}s")
            return duration
        
        # Fallback: try to get duration from video stream
        if 'streams' in probe_data:
            for stream in probe_data['streams']:
                if stream.get('codec_type') == 'video' and 'duration' in stream:
                    duration = float(stream['duration'])
                    logger.info(f"Video duration (from stream) for {file_path_or_url}: {duration:.2f}s")
                    return duration
        
        logger.warning(f"Could not find duration in ffprobe output for {file_path_or_url}")
        return None
        
    except subprocess.TimeoutExpired:
        logger.error(f"ffprobe timed out for {file_path_or_url}")
        return None
    except FileNotFoundError:
        logger.error("ffprobe not found. Please ensure ffmpeg is installed and in PATH.")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse ffprobe output: {e}")
        return None
    except Exception as e:
        logger.error(f"Error getting video duration for {file_path_or_url}: {e}")
        return None


def generate_video_thumbnail(
    file_path: str, 
    output_path: str, 
    timestamp: Optional[float] = None,
    width: int = 640,
    height: int = 360
) -> bool:
    """
    Generate a thumbnail image from a video file using ffmpeg.
    
    Args:
        file_path: Path to the video file
        output_path: Path where the thumbnail should be saved (supports .jpg, .png)
        timestamp: Time in seconds to capture the thumbnail (default: 10% into video or 1s)
        width: Thumbnail width in pixels (default 640)
        height: Thumbnail height in pixels (default 360, use -1 to maintain aspect ratio)
    
    Returns:
        True if thumbnail was generated successfully, False otherwise
    """
    if not file_path:
        logger.warning("No file path provided for thumbnail generation")
        return False
    
    if not output_path:
        logger.warning("No output path provided for thumbnail generation")
        return False
    
    # Ensure output directory exists
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir)
        except OSError as e:
            logger.error(f"Failed to create output directory {output_dir}: {e}")
            return False
    
    try:
        # If no timestamp provided, try to get duration and use 10% mark
        if timestamp is None:
            duration = get_video_duration(file_path)
            if duration and duration > 10:
                timestamp = duration * 0.1  # 10% into the video
            else:
                timestamp = 1.0  # Default to 1 second
        
        # Build scale filter (use -1 to maintain aspect ratio)
        scale_filter = f"scale={width}:{height}"
        if height == -1:
            scale_filter = f"scale={width}:-1"
        elif width == -1:
            scale_filter = f"scale=-1:{height}"
        
        # Use ffmpeg to generate thumbnail
        cmd = [
            'ffmpeg',
            '-y',  # Overwrite output file if exists
            '-ss', str(timestamp),  # Seek to timestamp
            '-i', file_path,  # Input file
            '-vframes', '1',  # Extract only one frame
            '-vf', scale_filter,  # Scale filter
            '-q:v', '2',  # Quality (1-31, lower is better for JPEG)
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30  # Timeout after 30 seconds
        )
        
        if result.returncode != 0:
            logger.error(f"ffmpeg thumbnail generation failed for {file_path}: {result.stderr}")
            return False
        
        # Verify the output file was created
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logger.info(f"Generated thumbnail for {file_path} at {output_path}")
            return True
        else:
            logger.error(f"Thumbnail file was not created or is empty: {output_path}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"ffmpeg timed out generating thumbnail for {file_path}")
        return False
    except FileNotFoundError:
        logger.error("ffmpeg not found. Please ensure ffmpeg is installed and in PATH.")
        return False
    except Exception as e:
        logger.error(f"Error generating thumbnail for {file_path}: {e}")
        return False


def get_video_info(file_path_or_url: str) -> Optional[dict]:
    """
    Get detailed information about a video file.
    
    Args:
        file_path_or_url: Local file path or URL to the video
    
    Returns:
        Dict with video info (duration, width, height, codec, bitrate, etc.) or None
    """
    if not file_path_or_url:
        return None
    
    try:
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            file_path_or_url
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            logger.error(f"ffprobe failed for {file_path_or_url}: {result.stderr}")
            return None
        
        probe_data = json.loads(result.stdout)
        
        info = {
            'duration': None,
            'width': None,
            'height': None,
            'video_codec': None,
            'audio_codec': None,
            'bitrate': None,
            'size': None,
            'format': None,
        }
        
        # Extract format info
        if 'format' in probe_data:
            fmt = probe_data['format']
            info['duration'] = float(fmt.get('duration', 0)) if fmt.get('duration') else None
            info['bitrate'] = int(fmt.get('bit_rate', 0)) if fmt.get('bit_rate') else None
            info['size'] = int(fmt.get('size', 0)) if fmt.get('size') else None
            info['format'] = fmt.get('format_name')
        
        # Extract stream info
        if 'streams' in probe_data:
            for stream in probe_data['streams']:
                if stream.get('codec_type') == 'video':
                    info['width'] = stream.get('width')
                    info['height'] = stream.get('height')
                    info['video_codec'] = stream.get('codec_name')
                    if not info['duration'] and stream.get('duration'):
                        info['duration'] = float(stream['duration'])
                elif stream.get('codec_type') == 'audio':
                    info['audio_codec'] = stream.get('codec_name')
        
        return info
        
    except Exception as e:
        logger.error(f"Error getting video info for {file_path_or_url}: {e}")
        return None


def extract_audio(video_path: str, output_path: str, audio_format: str = 'mp3') -> bool:
    """
    Extract audio track from a video file.
    
    Args:
        video_path: Path to the video file
        output_path: Path where the audio should be saved
        audio_format: Output audio format (mp3, aac, wav, etc.)
    
    Returns:
        True if audio was extracted successfully, False otherwise
    """
    if not video_path or not output_path:
        return False
    
    # Ensure output directory exists
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir)
        except OSError as e:
            logger.error(f"Failed to create output directory {output_dir}: {e}")
            return False
    
    try:
        # Audio codec mapping
        codec_map = {
            'mp3': 'libmp3lame',
            'aac': 'aac',
            'wav': 'pcm_s16le',
            'ogg': 'libvorbis',
            'flac': 'flac',
        }
        
        codec = codec_map.get(audio_format.lower(), 'libmp3lame')
        
        cmd = [
            'ffmpeg',
            '-y',
            '-i', video_path,
            '-vn',  # No video
            '-acodec', codec,
            '-q:a', '2',  # Quality
            output_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120  # Longer timeout for audio extraction
        )
        
        if result.returncode != 0:
            logger.error(f"Audio extraction failed for {video_path}: {result.stderr}")
            return False
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logger.info(f"Extracted audio from {video_path} to {output_path}")
            return True
        
        return False
        
    except subprocess.TimeoutExpired:
        logger.error(f"ffmpeg timed out extracting audio from {video_path}")
        return False
    except FileNotFoundError:
        logger.error("ffmpeg not found. Please ensure ffmpeg is installed and in PATH.")
        return False
    except Exception as e:
        logger.error(f"Error extracting audio from {video_path}: {e}")
        return False
