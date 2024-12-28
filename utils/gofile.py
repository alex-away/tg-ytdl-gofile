import aiohttp
import os
import time
import config

class GoFileUploader:
    def __init__(self):
        self._api_token = config.GOFILE_API_KEY
        self._base_url = "https://api.gofile.io"
        self._start_time = 0
        self._last_update = 0

    def _format_size(self, bytes: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes < 1024:
                return f"{bytes:.1f} {unit}"
            bytes /= 1024
        return f"{bytes:.1f} TB"

    async def _get_server(self) -> str:
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {self._api_token}"} if self._api_token else {}
            async with session.get(f"{self._base_url}/servers", headers=headers) as response:
                if response.status != 200:
                    raise Exception(f"Failed to get server: {response.status}")
                data = await response.json()
                if not data.get("data", {}).get("server"):
                    raise Exception("No server available")
                return data["data"]["server"]

    async def upload_file(self, file_path: str, progress_callback=None) -> dict:
        try:
            server = await self._get_server()
            file_size = os.path.getsize(file_path)
            self._start_time = time.time()
            self._last_update = 0

            if progress_callback:
                await progress_callback("📤 Connecting to Gofile server...")

            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bearer {self._api_token}"} if self._api_token else {}
                
                data = aiohttp.FormData()
                data.add_field('file', 
                    open(file_path, 'rb'),
                    filename=os.path.basename(file_path)
                )

                async with session.post(
                    f"https://{server}.gofile.io/contents/uploadfile",
                    data=data,
                    headers=headers
                ) as response:
                    if response.status != 200:
                        raise Exception(f"Upload failed: {response.status}")
                    
                    result = await response.json()
                    if not result.get("status") == "ok":
                        raise Exception(f"Upload failed: {result.get('status')}")

                    data = result.get("data", {})
                    return {
                        "download_link": data.get("downloadPage", ""),
                        "file_id": data.get("fileId", ""),
                        "file_name": data.get("fileName", "")
                    }

        except Exception as e:
            raise Exception(f"Upload failed: {str(e)}")

    async def close(self):
        pass 