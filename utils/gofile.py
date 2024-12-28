import aiohttp
import os
import asyncio
import logging
import config
from typing import Optional, Dict, Any, Callable
from aiohttp import FormData, TCPConnector
from datetime import datetime

logger = logging.getLogger(__name__)

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

        for attempt, delay in enumerate(self._retry_delays):
            try:
                # Try new API endpoint first
                async with self._session.get(
                    f"{self._base_url}/accounts/servers",
                    headers=headers,
                    timeout=10
                ) as response:
                    logger.info(f"Server response status: {response.status}")
                    text = await response.text()
                    logger.info(f"Server response: {text[:200]}...")  # Log first 200 chars

                    if response.status == 200:
                        data = await response.json()
                        if data.get("status") == "ok" and data.get("data"):
                            server = data["data"][0]
                            logger.info(f"Got upload server from API: {server}")
                            return server

                    # If API call fails, test each default server
                    for server in self._default_servers:
                        try:
                            # Test connection to server
                            async with self._session.get(
                                f"https://{server}.gofile.io/",
                                headers=headers,
                                timeout=5
                            ) as test_response:
                                if test_response.status in [200, 404]:
                                    logger.info(f"Using fallback server: {server}")
                                    return server
                        except Exception as e:
                            logger.warning(f"Failed to connect to {server}: {str(e)}")
                            continue

                    # If all servers fail, use first default server
                    logger.warning("All servers failed, using first default server")
                    return self._default_servers[0]

            except Exception as e:
                logger.error(f"Server fetch attempt {attempt + 1} failed: {str(e)}")
                if attempt == len(self._retry_delays) - 1:
                    logger.warning("All server fetch attempts failed, using first default server")
                    return self._default_servers[0]
                await asyncio.sleep(delay)

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

                # Prepare form data with fresh file handle
                file = open(file_path, 'rb')
                form = FormData()
                form.add_field('file',
                    file,
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
                    timeout=aiohttp.ClientTimeout(total=300)  # 5 minutes timeout for upload
                ) as response:
                    logger.info(f"Upload response status: {response.status}")
                    text = await response.text()
                    logger.info(f"Upload response: {text[:200]}...")  # Log first 200 chars

                    if response.status != 200:
                        raise Exception(f"Upload failed with status {response.status}: {text}")

                    result = await response.json()
                    
                    if result.get("status") != "ok":
                        raise Exception(f"Upload failed with error: {result}")

                    data = result.get("data", {})
                    if not data:
                        raise Exception(f"No data in response: {result}")

                    # Close file handle after successful upload
                    file.close()
                    file = None

                    return {
                        "download_link": data.get("downloadPage", ""),
                        "file_id": data.get("fileId", ""),
                        "file_name": file_name,
                        "direct_link": data.get("directLink", "")
                    }

            except asyncio.TimeoutError:
                logger.error(f"Timeout uploading {file_name} - file may be too large")
                if file:
                    file.close()
                if attempt == len(self._retry_delays) - 1:
                    raise Exception("Upload timed out - file may be too large")
                continue

            except Exception as e:
                logger.error(f"Upload attempt {attempt + 1} failed: {str(e)}")
                if file:
                    file.close()
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