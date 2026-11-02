import uvicorn

if __name__ == "__main__":
    uvicorn.run("caption.server:create_app", factory=True, host="127.0.0.1", port=8000,
                ws_max_size=65536)
