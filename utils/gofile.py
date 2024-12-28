from typing import Optional, Dict, Callable
import os
import time
from gofile2 import Gofile
import asyncio
import config

class GoFileUploader:
    def __init__(self):
        self._client = None
        self._start_time = 0
        self._last_update = 0

    async def _ensure_client(self):
        """Ensure Gofile client is initialized."""
        if not self._client:
            self._client = await Gofile.initialize(token=config.GOFILE_API_KEY if config.GOFILE_API_KEY else None)

    def _format_size(self, bytes: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes < 1024:
                return f"{bytes:.1f} {unit}"
            bytes /= 1024
        return f"{bytes:.1f} TB"

    async def upload_file(self, file_path: str, progress_callback: Optional[Callable] = None) -> Dict:
        """Upload file to Gofile and return the download link."""
        try:
            if not os.path.exists(file_path):
                raise Exception("File not found")

            file_size = os.path.getsize(file_path)
            if file_size == 0:
                raise Exception("File is empty")

            if progress_callback:
                await progress_callback(
                    "📤 *Uploading to Gofile*\n"
                    "├ Status: Initializing connection\n"
                    f"└ Size: {self._format_size(file_size)}"
                )

            await self._ensure_client()

            if progress_callback:
                await progress_callback(
                    "📤 *Uploading to Gofile*\n"
                    "├ Status: Starting upload\n"
                    f"└ Size: {self._format_size(file_size)}"
                )

            self._start_time = time.time()
            self._last_update = 0

            async def _progress():
                while True:
                    current_time = time.time()
                    if current_time - self._last_update >= 1:
                        self._last_update = current_time
                        elapsed = current_time - self._start_time
                        if elapsed > 0:
                            speed = file_size / elapsed
                            await progress_callback(
                                "📤 *Uploading to Gofile*\n"
                                f"├ Speed: {self._format_size(speed)}/s\n"
                                f"└ Size: {self._format_size(file_size)}"
                            )
                    await asyncio.sleep(1)

            if progress_callback:
                progress_task = asyncio.create_task(_progress())

            try:
                result = await self._client.upload(file_path)
            finally:
                if progress_callback:
                    progress_task.cancel()

            if progress_callback:
                await progress_callback(
                    "📤 *Uploading to Gofile*\n"
                    "├ Status: Upload complete\n"
                    "└ Generating link..."
                )

            await self._client.done()

            if not result or not result.get("downloadPage"):
                raise Exception("Upload failed - no download link received")

            return {
                "download_link": result.get("downloadPage", ""),
                "direct_link": result.get("directLink", ""),
                "file_id": result.get("fileId", "")
            }

        except asyncio.CancelledError:
            if self._client:
                await self._client.done()
            raise

        except Exception as e:
            if self._client:
                await self._client.done()
            raise Exception(f"Upload failed: {str(e)}")

    async def close(self):
        """Close the Gofile client."""
        if self._client:
            await self._client.done()
            self._client = None 