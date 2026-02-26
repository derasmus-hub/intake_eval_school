import os
import logging
import uvicorn

logging.basicConfig(level=logging.DEBUG, format="%(levelname)-5s [%(name)s] %(message)s")

if __name__ == "__main__":
    reload = os.environ.get("DEV_RELOAD", "0") == "1"
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app.server:app", host=host, port=port, reload=reload)
