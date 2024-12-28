import os
import time
from typing import Dict, List, Optional, Tuple, Callable
import hashlib
import yt_dlp
from urllib.parse import parse_qs, urlparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import config

class DownloadProgress:
    def __init__(self, callback: Callable[[str], None], loop: asyncio.AbstractEventLoop):
        self.callback = callback
        self.loop = loop
        self.start_time = time.time()
        self.last_update = 0
        self.last_progress = 0
        self.last_size = 0
        self.update_interval = 2.0
        self.min_progress_change = 2.0

    async def _safe_callback(self, text: str):
        try:
            await self.callback(text)
        except Exception:
            pass

    def progress_hook(self, d: Dict):
        try:
            current_time = time.time()
            if current_time - self.last_update < self.update_interval:
                return
            
            if d['status'] == 'downloading':
                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                
                if total:
                    progress = (downloaded / total) * 100
                    size_change = abs(downloaded - self.last_size) / (1024 * 1024)  # MB
                    
                    if (abs(progress - self.last_progress) >= self.min_progress_change or size_change >= 2):
                        self.last_progress = progress
                        self.last_size = downloaded
                        
                        speed = d.get('speed', 0)
                        eta = (total - downloaded) / speed if speed else 0

                        progress_bar = self._get_progress_bar(progress)
                        status = (
                            f"📥 *Downloading*\n"
                            f"{progress_bar} `{progress:.1f}%`\n"
                            f"├ Size: {self._format_size(downloaded)}/{self._format_size(total)}\n"
                            f"├ Speed: {self._format_size(speed)}/s\n"
                            f"└ ETA: {self._format_time(eta)}"
                        )
                else:
                    if downloaded - self.last_size >= 2 * 1024 * 1024:  # 2MB change
                        self.last_size = downloaded
                        status = (
                            f"📥 *Downloading*\n"
                            f"└ Downloaded: {self._format_size(downloaded)}"
                        )
                    else:
                        return
                
                self.last_update = current_time
                future = asyncio.run_coroutine_threadsafe(
                    self._safe_callback(status), 
                    self.loop
                )
                future.result(timeout=0.5)
                
            elif d['status'] == 'finished':
                if current_time - self.last_update >= self.update_interval:
                    self.last_update = current_time
                    future = asyncio.run_coroutine_threadsafe(
                        self._safe_callback("⚙️ Processing download..."), 
                        self.loop
                    )
                    future.result(timeout=0.5)
                
        except (asyncio.TimeoutError, Exception):
            pass

    def _get_progress_bar(self, percentage: float, length: int = 15) -> str:
        filled = int(length * percentage / 100)
        return f"{'█' * filled}{'░' * (length - filled)}"

    def _format_size(self, bytes: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes < 1024:
                return f"{bytes:.1f} {unit}"
            bytes /= 1024
        return f"{bytes:.1f} TB"

    def _format_time(self, seconds: float) -> str:
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
            'format': 'bestvideo*+bestaudio/best',
            'merge_output_format': 'mp4',
            'check_formats': True,
            'youtube_include_dash_manifest': True,
            'youtube_include_hls_manifest': True,
            'format_sort': ['res', 'ext:mp4:m4a', 'codec:h264:m4a', 'size', 'br', 'asr']
        }
        self._executor = ThreadPoolExecutor(max_workers=config.MAX_CONCURRENT_DOWNLOADS)
        self._info_executor = ThreadPoolExecutor(max_workers=10)

    @lru_cache(maxsize=128)
    async def _get_video_info_cached(self, url: str) -> Dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._info_executor, self._get_video_info, url)

    def _get_video_info(self, url: str) -> Dict:
        ydl_opts = {
            **self.base_opts,
            'format': 'best',
            'youtube_include_dash_manifest': True,
            'youtube_include_hls_manifest': True,
            'check_formats': True
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise Exception("Could not fetch video information")
                
                video_id = self._get_video_id(url)
                formats = self._parse_formats(info.get('formats', []))
                
                if not formats['video'] and not formats['audio']:
                    raise Exception("No supported formats found")
                
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

    async def get_video_info(self, url: str) -> Dict:
        return await self._get_video_info_cached(url)

    def _get_video_id(self, url: str) -> str:
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

    def _parse_formats(self, formats: List[Dict]) -> Dict:
        video_formats = {}
        
        for f in formats:
            if not f:
                continue
                
            height = f.get('height', 0)
            ext = f.get('ext', '')
            vcodec = f.get('vcodec', '')
            acodec = f.get('acodec', '')
            filesize = f.get('filesize', 0) or f.get('filesize_approx', 0)
            tbr = f.get('tbr', 0)
            
            if not height or not ext or vcodec == 'none':
                continue
            
            if vcodec != 'none':
                quality = f"{height}p"
                if quality in config.SUPPORTED_VIDEO_QUALITIES:
                    if ext not in ['mp4', 'webm', 'mkv']:
                        continue
                        
                    if quality not in video_formats:
                        video_formats[quality] = {}
                    if ext not in video_formats[quality]:
                        video_formats[quality][ext] = []
                        
                    video_formats[quality][ext].append({  # noqa: Pylance
                        'format_id': f['format_id'],
                        'ext': ext,
                        'filesize': filesize,
                        'tbr': tbr,
                        'vcodec': vcodec,
                        'acodec': acodec,
                        'width': f.get('width', 0),
                        'height': height,
                        'fps': f.get('fps', 0),
                        'format_note': f.get('format_note', '')
                    })

        for quality in video_formats:
            for ext in video_formats[quality]:
                video_formats[quality][ext].sort(
                    key=lambda x: (
                        float(x.get('tbr', 0) or 0),
                        float(x.get('filesize', 0) or 0),
                        float(x.get('fps', 0) or 0),
                        x.get('vcodec', '').startswith('avc1'),
                        x.get('acodec', '').startswith('mp4a')
                    ),
                    reverse=True
                )

        audio_formats = {'mp3': [], 'wav': []}
        audio_only = [f for f in formats if f and f.get('vcodec') == 'none' and f.get('acodec') != 'none']
        
        if audio_only:
            best_audio = max(
                audio_only,
                key=lambda x: (
                    float(x.get('abr', 0) or 0),
                    float(x.get('filesize', 0) or 0),
                    x.get('acodec', '').startswith('mp4a')
                )
            )
            
            for fmt in ['mp3', 'wav']:
                audio_formats[fmt].append({
                    'format_id': best_audio['format_id'],
                    'ext': fmt,
                    'filesize': best_audio.get('filesize', 0),
                    'abr': best_audio.get('abr', 0)
                })

        return {
            'audio': audio_formats,
            'video': {k: video_formats[k] for k in sorted(video_formats.keys(), key=lambda x: int(x[:-1]))}
        }

    async def download(self, url: str, format_type: str, format_quality: str, format_ext: str, progress_callback: Callable[[str], None]) -> Tuple[str, str]:
        loop = asyncio.get_event_loop()
        progress = DownloadProgress(progress_callback, loop)
        
        try:
            await progress_callback("🔍 Preparing download...")
            
            ydl_opts = {
                **self.base_opts,
                'progress_hooks': [progress.progress_hook],
                'outtmpl': os.path.join(config.TEMP_PATH, '%(title)s.%(ext)s'),
                'retries': 3,
                'fragment_retries': 10,
                'http_chunk_size': 10485760
            }

            if format_type == 'audio':
                ydl_opts.update({
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': format_quality,
                        'preferredquality': '192',
                    }]
                })
            else:
                format_str = (
                    f'bestvideo[height={format_quality[:-1]}][ext={format_ext}]'
                    f'+bestaudio[ext={format_ext}]'
                    f'/best[height<={format_quality[:-1]}][ext={format_ext}]'
                )
                ydl_opts.update({
                    'format': format_str,
                    'merge_output_format': format_ext
                })

            result = await loop.run_in_executor(
                self._executor,
                self._download,
                url,
                ydl_opts
            )
            
            if not result:
                raise Exception("Download failed - please try again")
            
            filename, title = result
            if not os.path.exists(filename):
                raise Exception("Download completed but file not found")
                
            return filename, title

        except Exception as e:
            raise Exception(f"Download error: {str(e)}")

    def _download(self, url: str, ydl_opts: Dict) -> Optional[Tuple[str, str]]:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url)
                if not info:
                    return None
                    
                filename = ydl.prepare_filename(info)
                
                if 'postprocessors' in ydl_opts:
                    filename = os.path.splitext(filename)[0] + f".{ydl_opts['postprocessors'][0]['preferredcodec']}"
                
                return filename, info.get('title', 'Unknown Title')
            except Exception as e:
                print(f"Download error: {str(e)}")
                return None

    def get_file_size(self, file_path: str) -> int:
        try:
            return os.path.getsize(file_path)
        except Exception:
            return 0

    def __del__(self):
        self._executor.shutdown(wait=False) 
        self._info_executor.shutdown(wait=False)