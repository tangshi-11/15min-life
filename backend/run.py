"""本地启动入口：python run.py（等价于 uvicorn app.main:app --port 8000）"""
import logging
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    filename=r"E:\上海\15min-life-circle\backend\server.log",
    filemode="a",
    encoding="utf-8",
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
