import os
import time
from typing import Dict, List, Optional, Tuple, Callable
import hashlib
import yt_dlp
from urllib.parse import parse_qs, urlparse
import asyncio
from concurrent.futures import ThreadPoolExecutor

import config

class DownloadProgress:
    def __init__(self, callback: Callable[[str], None], loop: asyncio.AbstractEventLoop):
        self.callback = callback
        self.loop = loop
        self.start_time = time.time()
        self.last_update = 0

    def progress_hook(self, d: Dict):
        if d['status'] == 'downloading':
            # Limit updates to once per second to avoid flooding
            current_time = time.time()
            if current_time - self.last_update < 1:
                return
            
            self.last_update = current_time
            
            if d.get('total_bytes'):
                # Calculate progress and speed
                downloaded = d.get('downloaded_bytes', 0)
                total = d['total_bytes']
                speed = d.get('speed', 0)
                progress = (downloaded / total) * 100
                
                # Calculate ETA
                if speed:
                    eta = (total - downloaded) / speed
                else:
                    eta = 0

                status = (
                    f"⬇️ Downloading: {progress:.1f}%\n"
                    f"📦 Size: {self._format_size(downloaded)}/{self._format_size(total)}\n"
                    f"🚀 Speed: {self._format_size(speed)}/s\n"
                    f"⏱ ETA: {self._format_time(eta)}"
                )
            else:
                status = f"⬇️ Downloading... {self._format_size(d.get('downloaded_bytes', 0))}"
            
            asyncio.run_coroutine_threadsafe(self.callback(status), self.loop)
        elif d['status'] == 'finished':
            asyncio.run_coroutine_threadsafe(self.callback("✅ Download completed! Processing..."), self.loop)

    def _format_size(self, bytes: int) -> str:
        """Format bytes to human readable size."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes < 1024:
                return f"{bytes:.1f}{unit}"
            bytes /= 1024
        return f"{bytes:.1f}TB"

    def _format_time(self, seconds: float) -> str:
        """Format seconds to human readable time."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds/60:.0f}m {seconds%60:.0f}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours:.0f}h {minutes:.0f}m"

class YouTubeDownloader:
    def __init__(self, cookie_path: Optional[str] = None):
        self.cookie_path = cookie_path
        self.base_opts = {
            'cookiefile': cookie_path,
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        self._executor = ThreadPoolExecutor(max_workers=config.MAX_CONCURRENT_DOWNLOADS)

    def _get_video_id(self, url: str) -> str:
        """Extract video ID from URL."""
        try:
            parsed_url = urlparse(url)
            if parsed_url.hostname == 'youtu.be':
                return parsed_url.path[1:]
            if parsed_url.hostname in ('www.youtube.com', 'youtube.com'):
                if parsed_url.path == '/watch':
                    return parse_qs(parsed_url.query)['v'][0]
        except:
            pass
        return hashlib.md5(url.encode()).hexdigest()[:10]

    def get_video_info(self, url: str) -> Dict:
        """Get video information using yt-dlp."""
        ydl_opts = {
            **self.base_opts,
            'format': 'best'
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise Exception("Could not fetch video information")
                
                video_id = self._get_video_id(url)
                formats = self._parse_formats(info.get('formats', []))
                
                return {
                    'title': info.get('title', 'Unknown Title'),
                    'duration': info.get('duration', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'formats': formats,
                    'video_id': video_id,
                    'author': info.get('uploader', 'Unknown'),
                    'views': info.get('view_count', 0),
                    'description': info.get('description', '')
                }
        except Exception as e:
            raise Exception(f"Error getting video info: {str(e)}")

    def _parse_formats(self, formats: List[Dict]) -> Dict[str, List[Dict]]:
        """Parse and categorize available formats."""
        video_formats = {}
        
        # First pass: collect all formats
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
                            'ext': f.get('ext', 'mp4'),
                            'filesize': f.get('filesize', 0),
                            'tbr': f.get('tbr', 0),
                            'vcodec': f.get('vcodec', ''),
                            'acodec': f.get('acodec', '')
                        })

        # Sort formats by quality and bitrate
        for quality in video_formats:
            video_formats[quality].sort(key=lambda x: (x.get('tbr', 0), x.get('filesize', 0)), reverse=True)

        return {
            'video': video_formats,
            'audio': {
                'mp3': [{'format_id': 'bestaudio/best', 'ext': 'mp3'}],
                'wav': [{'format_id': 'bestaudio/best', 'ext': 'wav'}]
            }
        }

    async def download(self, url: str, format_type: str, format_quality: str, progress_callback: Callable[[str], None]) -> Tuple[str, str]:
        """Download video with progress tracking."""
        loop = asyncio.get_event_loop()
        progress = DownloadProgress(progress_callback, loop)
        
        ydl_opts = {
            **self.base_opts,
            'progress_hooks': [progress.progress_hook],
            'outtmpl': os.path.join(config.TEMP_PATH, '%(title)s.%(ext)s'),
        }

        try:
            if format_type == 'audio':
                # Configure for audio download
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': format_quality,
                        'preferredquality': '192',
                    }]
                })
            else:
                # Configure for video download with specific quality
                ydl_opts.update({
                    'format': f'bestvideo[height<={format_quality[:-1]}]+bestaudio/best[height<={format_quality[:-1]}]'
                })

            # Run download in thread pool
            result = await loop.run_in_executor(
                self._executor,
                self._download,
                url,
                ydl_opts
            )
            
            if not result:
                raise Exception("Download failed")
            
            filename, title = result
            return filename, title

        except Exception as e:
            raise Exception(f"Error downloading: {str(e)}")

    def _download(self, url: str, ydl_opts: Dict) -> Optional[Tuple[str, str]]:
        """Internal download function to run in thread pool."""
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url)
                if not info:
                    return None
                    
                filename = ydl.prepare_filename(info)
                
                # If it's audio, adjust the filename extension
                if 'postprocessors' in ydl_opts:
                    filename = os.path.splitext(filename)[0] + f".{ydl_opts['postprocessors'][0]['preferredcodec']}"
                
                return filename, info.get('title', 'Unknown Title')
            except Exception as e:
                print(f"Download error: {str(e)}")
                return None

    def get_file_size(self, file_path: str) -> int:
        """Get file size in bytes."""
        try:
            return os.path.getsize(file_path)
        except Exception:
            return 0

    def __del__(self):
        """Cleanup thread pool on deletion."""
        self._executor.shutdown(wait=False) 