import uvicorn
import os

if __name__ == "__main__":
    uvicorn.run("caption.server:create_app", factory=True, host="127.0.0.1", port=int(os.getenv("CAPTION_PORT", "8000")),
                ws_max_size=65536)
