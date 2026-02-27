from fastapi import APIRouter,  Depends, HTTPException, Request, status
from typing import Optional, Dict
import json

# prefix="/users" — это пространство имен. Все маршруты в этом файле 
# автоматически получат этот префикс.
# tags=["Users"] — нужно для группировки в автоматической документации (Swagger UI).
router = APIRouter(
    prefix="/users",
    tags=["Users"]
)

# ВАЖНО: Мы используем декоратор @router, а не @app.
# Переменной app здесь не существует, мы находимся в изолированном модуле.

async def get_current_user(request: Request) -> Dict:
    """
    Извлекает информацию о пользователе из заголовков, добавленных Yandex Cloud API Gateway
    после успешной проверки JWT токена.
    
    Yandex Cloud API Gateway добавляет заголовок X-Yc-Apigateway-Authorizer-Context
    с информацией из JWT токена в формате JSON.
    """
    authorizer_context = request.headers.get("X-Yc-Apigateway-Authorizer-Context")
    
    if not authorizer_context:
        # В реальном приложении этот случай не должен происходить,
        # так как API Gateway уже проверил токен для защищенных эндпоинтов
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Отсутствует контекст авторизации"
        )
    
    try:
        return json.loads(authorizer_context)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Некорректный формат контекста авторизации"
        )

@router.get("/api/user")
async def get_user_info(user: Dict = Depends(get_current_user)):
    """
    Защищенный эндпоинт для получения информации о пользователе.
    Доступен только с валидным JWT токеном (проверка выполняется на уровне API Gateway).
    
    Информация о пользователе извлекается из заголовка, добавленного API Gateway.
    """
    # Пример извлечения данных из контекста авторизации
    user_id = user.get("sub", "unknown")
    email = user.get("email", "unknown@example.com")
    
    return {
        "user_id": user_id,
        "email": email,
        "name": user.get("name", "Unknown User"),
        "scopes": user.get("scope", "").split(),
        "token_issuer": user.get("iss", ""),
        "raw_context": user  # Полный контекст для отладки
    }

# Дополнительный эндпоинт для отладки - показывает все полученные заголовки
@router.get("/debug/headers")
async def debug_headers(request: Request):
    """Эндпоинт для отладки - показывает все полученные заголовки"""
    return {
        "headers": dict(request.headers),
        "authorizer_context": request.headers.get("X-Yc-Apigateway-Authorizer-Context")
    }

@router.get("/")
def get_users() -> list[dict]:
    # Итоговый путь будет: GET /users/
    # Нам не нужно писать "/users" руками, префикс подставится сам.
    return [{"username": "Rick"}, {"username": "Morty"}]

@router.get("/me")
def get_current_user() -> dict: 
    return {"username": "Rick", "role": "admin"}