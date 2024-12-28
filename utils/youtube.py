import os
import yt_dlp
from typing import Dict, List, Optional, Tuple
import hashlib

import config

class YouTubeDownloader:
    def __init__(self, cookie_path: Optional[str] = None):
        self.cookie_path = cookie_path
        self.ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'cookiefile': cookie_path,
            'noplaylist': True,
            'progress_hooks': [],
            'outtmpl': os.path.join(config.TEMP_PATH, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }

    def _get_video_id(self, url: str) -> str:
        """Generate a short hash for the video URL."""
        return hashlib.md5(url.encode()).hexdigest()[:10]

    def get_video_info(self, url: str) -> Dict:
        """Get video information including available formats."""
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                video_id = self._get_video_id(url)
                return {
                    'title': info.get('title', 'Unknown Title'),
                    'duration': info.get('duration', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'formats': self._parse_formats(info.get('formats', [])),
                    'video_id': video_id
                }
            except Exception as e:
                raise Exception(f"Error getting video info: {str(e)}")

    def _parse_formats(self, formats: List[Dict]) -> Dict[str, List[Dict]]:
        """Parse and categorize available formats."""
        video_formats = {}
        audio_formats = {'mp3': [], 'wav': []}

        for f in formats:
            if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                height = f.get('height', 0)
                if height:
                    quality = f"{height}p"
                    if quality in config.SUPPORTED_VIDEO_QUALITIES:
                        if quality not in video_formats:
                            video_formats[quality] = []
                        video_formats[quality].append({
                            'format_id': f['format_id'],
                            'ext': f['ext'],
                            'filesize': f.get('filesize', 0),
                            'tbr': f.get('tbr', 0)
                        })

            elif f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                for audio_format in config.SUPPORTED_AUDIO_FORMATS:
                    audio_formats[audio_format].append({
                        'format_id': f['format_id'],
                        'ext': f['ext'],
                        'filesize': f.get('filesize', 0),
                        'abr': f.get('abr', 0)
                    })

        # Sort formats by quality
        for quality in video_formats:
            video_formats[quality].sort(key=lambda x: x.get('tbr', 0), reverse=True)
        for format_type in audio_formats:
            audio_formats[format_type].sort(key=lambda x: x.get('abr', 0), reverse=True)

        return {
            'video': video_formats,
            'audio': audio_formats
        }

    def download(self, url: str, format_id: str, progress_hook=None) -> Tuple[str, str]:
        """Download video in specified format."""
        if progress_hook:
            self.ydl_opts['progress_hooks'] = [progress_hook]

        self.ydl_opts['format'] = format_id
        
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url)
                filename = ydl.prepare_filename(info)
                return filename, info.get('title', 'Unknown Title')
            except Exception as e:
                raise Exception(f"Error downloading video: {str(e)}")

    def convert_to_audio(self, input_file: str, output_format: str, progress_hook=None) -> str:
        """Convert video to audio format."""
        output_file = os.path.splitext(input_file)[0] + f".{output_format}"
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': output_format,
                'preferredquality': '192',
            }],
            'outtmpl': os.path.splitext(input_file)[0],
            'quiet': True,
            'no_warnings': True,
        }

        if progress_hook:
            ydl_opts['progress_hooks'] = [progress_hook]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                ydl.download([input_file])
                return output_file
            except Exception as e:
                raise Exception(f"Error converting to audio: {str(e)}") 