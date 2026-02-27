from doctest import debug
import uvicorn
import os
from fastapi import FastAPI

from app.routers import users

app = FastAPI(title="My Architecture App")

# Подключаем роутер к главному приложению.
# Это похоже на подключение плагина.
app.include_router(users.router)

@app.get("/")
def root():
    return {"message": "Приложение работает!"}

@app.get("/health")
async def health_check():
    """
    Публичный эндпоинт для проверки работоспособности сервиса.
    Доступен без аутентификации (настраивается через security: [] в OpenAPI).
    """
    return {
        "status": "ok",
        "service": "demo-auth-api",
        "environment": "production"
    }


if __name__ == "__main__":
    uvicorn.run(app, debug=True, host="0.0.0.0", port=os.environ['PORT'])
