from typing import Optional, Dict
import os
from gofile2 import Gofile
import config

class GoFileUploader:
    def __init__(self):
        self._client = None

    async def _ensure_client(self):
        """Ensure Gofile client is initialized."""
        if not self._client:
            self._client = await Gofile.initialize(token=config.GOFILE_API_KEY if config.GOFILE_API_KEY else None)

    async def upload_file(self, file_path: str, progress_callback=None) -> Dict:
        """Upload file to Gofile and return the download link."""
        try:
            if progress_callback:
                await progress_callback("📤 Preparing Gofile upload...")

            # Initialize client
            await self._ensure_client()

            if progress_callback:
                await progress_callback("📤 Uploading to Gofile... This might take a while.")

            # Upload file
            result = await self._client.upload(file_path)

            if progress_callback:
                await progress_callback("✅ Upload complete! Generating link...")

            # Close client
            await self._client.done()

            return {
                "download_link": result.get("downloadPage", ""),
                "direct_link": result.get("directLink", ""),
                "file_id": result.get("fileId", "")
            }

        except Exception as e:
            if self._client:
                await self._client.done()
            raise Exception(f"❌ Gofile upload failed: {str(e)}")

    async def close(self):
        """Close the Gofile client."""
        if self._client:
            await self._client.done()
            self._client = None 