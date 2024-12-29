import aiohttp
import os
import asyncio
import logging
import config
from typing import Optional, Dict, Any, Callable
from aiohttp import FormData, TCPConnector
from datetime import datetime
import time

logger = logging.getLogger(__name__)

class UploadProgress:
    def __init__(self, callback: Callable[[str], Any], total_size: int):
        self.callback = callback
        self.total_size = total_size
        self.start_time = time.time()
        self.last_update = 0
        self.last_progress = 0
        self.uploaded = 0
        self.update_interval = 2.0
        self.min_progress_change = 2.0

    def _format_size(self, size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def _format_time(self, seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        minutes = seconds / 60
        if minutes < 60:
            return f"{minutes:.0f}m {seconds % 60:.0f}s"
        hours = minutes / 60
        return f"{hours:.0f}h {minutes % 60:.0f}m"

    def _get_progress_bar(self, progress: float) -> str:
        filled = int(progress / 10)
        empty = 10 - filled
        return f"[{'█' * filled}{'░' * empty}]"

    async def update(self, chunk_size: int):
        self.uploaded += chunk_size
        current_time = time.time()
        
        if current_time - self.last_update < self.update_interval:
            return

        progress = (self.uploaded / self.total_size) * 100
        if abs(progress - self.last_progress) < self.min_progress_change:
            return

        self.last_progress = progress
        self.last_update = current_time

        elapsed = current_time - self.start_time
        speed = self.uploaded / elapsed if elapsed > 0 else 0
        eta = (self.total_size - self.uploaded) / speed if speed > 0 else 0

        progress_bar = self._get_progress_bar(progress)
        status = (
            f"📤 *Uploading*\n"
            f"{progress_bar} `{progress:.1f}%`\n"
            f"├ Size: {self._format_size(self.uploaded)}/{self._format_size(self.total_size)}\n"
            f"├ Speed: {self._format_size(speed)}/s\n"
            f"└ ETA: {self._format_time(eta)}"
        )

        await self.callback(status)

class GoFileUploader:
    def __init__(self, api_token: Optional[str] = None):
        """
        Initialize GoFile uploader with optional API token.
        
        Args:
            api_token: Optional GoFile API token for authenticated uploads
        """
        self._api_token = api_token or config.GOFILE_API_KEY
        self._base_url = "https://api.gofile.io"
        self._session: Optional[aiohttp.ClientSession] = None
        self._max_retries = 3
        self._retry_delays = [1, 2, 4]  # Exponential backoff
        self._default_servers = ["store1", "store2", "store3", "store4", "store5"]

        if self._api_token:
            logger.info("Initialized GoFile uploader with API token")
        else:
            logger.info("Initialized GoFile uploader for anonymous uploads")

    async def __aenter__(self):
        """Support async context manager."""
        await self.init_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup when using async context manager."""
        await self.close()

    async def init_session(self):
        """Initialize aiohttp session if not already created."""
        if not self._session:
            # Configure for DNS resolution and longer timeouts
            connector = TCPConnector(
                force_close=True,
                enable_cleanup_closed=True,
                ttl_dns_cache=300,
                verify_ssl=False  # Some Gofile servers have SSL issues
            )
            timeout = aiohttp.ClientTimeout(
                total=3600,     # 1 hour total timeout
                connect=60,     # 60 seconds connection timeout
                sock_read=60    # 60 seconds socket read timeout
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout
            )

    async def _get_server(self) -> str:
        """
        Get best server for upload from GoFile API with fallback options.
        Tests all servers in parallel for faster selection.
        
        Returns:
            str: Server hostname for upload
            
        Raises:
            Exception: If unable to get server after retries
        """
        await self.init_session()
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        }

        async def test_server(server: str) -> Optional[str]:
            try:
                async with self._session.get(
                    f"https://{server}.gofile.io/",
                    headers=headers,
                    timeout=10
                ) as response:
                    if response.status in [200, 404]:
                        logger.info(f"Server {server} is available")
                        return server
            except Exception as e:
                logger.warning(f"Failed to connect to {server}: {str(e)}")
            return None

        # Try all servers in parallel
        tasks = [test_server(server) for server in self._default_servers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions and None results
        available_servers = [
            server for server, result in zip(self._default_servers, results)
            if isinstance(result, str) and result is not None
        ]
        
        if available_servers:
            selected_server = available_servers[0]
            logger.info(f"Selected server: {selected_server}")
            return selected_server
            
        # If all servers failed, use first default server
        logger.warning("All servers failed, using first default server")
        return self._default_servers[0]

    async def upload_file(
        self, 
        file_path: str, 
        progress_callback: Optional[Callable[[str], Any]] = None,
        chunk_size: int = 8192
    ) -> Dict[str, str]:
        """
        Upload file to GoFile with proper chunking and progress tracking.
        
        Args:
            file_path: Path to file to upload
            progress_callback: Optional callback for progress updates
            chunk_size: Size of chunks for reading file
            
        Returns:
            dict: Upload result with download_link, file_id, and file_name
            
        Raises:
            Exception: If upload fails after retries
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        await self.init_session()
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)

        for attempt, delay in enumerate(self._retry_delays):
            file = None
            try:
                # Get fresh server for each attempt
                server = await self._get_server()
                
                if progress_callback:
                    await progress_callback(f"📤 Connected to server: {server}")

                # Create progress tracker
                progress = UploadProgress(progress_callback, file_size) if progress_callback else None

                # Custom file reader with progress tracking
                async def file_sender():
                    with open(file_path, 'rb') as f:
                        while True:
                            chunk = f.read(chunk_size)
                            if not chunk:
                                break
                            if progress:
                                await progress.update(len(chunk))
                            yield chunk

                # Prepare form data with custom file sender
                form = FormData()
                form.add_field('file',
                    file_sender(),
                    filename=file_name,
                    content_type='application/octet-stream'
                )

                if self._api_token:
                    form.add_field('token', self._api_token)

                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'application/json'
                }

                # Upload with progress tracking
                async with self._session.post(
                    f"https://{server}.gofile.io/uploadFile",
                    data=form,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=3600)  # 1 hour timeout for upload
                ) as response:
                    logger.info(f"Upload response status: {response.status}")
                    text = await response.text()
                    logger.info(f"Upload response: {text[:200]}...")

                    if response.status != 200:
                        raise Exception(f"Upload failed with status {response.status}: {text}")

                    result = await response.json()
                    
                    if result.get("status") != "ok":
                        raise Exception(f"Upload failed with error: {result}")

                    data = result.get("data", {})
                    if not data:
                        raise Exception(f"No data in response: {result}")

                    return {
                        "download_link": data.get("downloadPage", ""),
                        "file_id": data.get("fileId", ""),
                        "file_name": file_name,
                        "direct_link": data.get("directLink", "")
                    }

            except asyncio.TimeoutError:
                logger.error(f"Timeout uploading {file_name} - file may be too large")
                if attempt == len(self._retry_delays) - 1:
                    raise Exception("Upload timed out - file may be too large")
                continue

            except Exception as e:
                logger.error(f"Upload attempt {attempt + 1} failed: {str(e)}")
                if attempt == len(self._retry_delays) - 1:
                    raise Exception(f"Upload failed after {len(self._retry_delays)} attempts: {str(e)}")
                if progress_callback:
                    await progress_callback(f"📤 Upload attempt {attempt + 1} failed, retrying in {delay}s...")
                await asyncio.sleep(delay)

    async def close(self):
        """Close the aiohttp session."""
        if self._session:
            await self._session.close()
            self._session = None 