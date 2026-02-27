Ниже пошаговый план развертывания рабочего окружения с Yandex Cloud для демонстрации аутентификации через Identity Hub + API Gateway + Serverless Container (Python backend) + фронт в Object Storage. [youtube](https://www.youtube.com/watch?v=BmvTF6JJTAU)

***

## Архитектурное устройство

```
Пользователь (браузер)
    ↓
[Object Storage static site] → index.html + login.html
    ↓ (JS fetch с Bearer token)
API Gateway (JWT authorizer)
    ↓ (проксирует авторизованные запросы)
Serverless Container (Python Flask/FastAPI)

```

**Компоненты:**
1. **Identity Hub OIDC app** — выдает JWT токены сотрудникам/партнерам.  
2. **Object Storage bucket** — хостит статический фронт (index.html, login.html, app.js).  
3. **API Gateway** — единая точка входа, валидирует JWT и проксирует в контейнер.  
4. **Serverless Container** — Python backend (Flask/FastAPI) обрабатывает бизнес-логику.  
5. **Service Account** — для доступов контейнера к YDB/S3.  

**Поток авторизации:**
- Пользователь открывает `login.html` → редирект на OIDC Authorization endpoint.  
- После логина получает `id_token` (JWT) и сохраняет в `localStorage`.  
- JS-код отправляет запросы к API Gateway с заголовком `Authorization: Bearer <id_token>`.  
- API Gateway валидирует токен по JWKS и прокидывает запрос в контейнер.  

***

## Шаг 1: Создать Organization и OIDC приложение в Identity Hub

**1.1 Создать Organization (если нет):**
```bash
# В консоли Yandex Cloud → Organization → Создать организацию
# Запишите organization-id
```

**1.2 Создать OIDC приложение:**
```bash
# Консоль → Organization → Applications → Create
# Тип: OIDC
# Имя: demo-auth-app
# Redirect URIs: https://<ваш-bucket-name>.website.yandexcloud.net/callback.html
#               (пока placeholder, обновим после создания bucket)
# Scopes: openid, email, profile
# → Создать
# Запишите:
#   - Client ID
#   - OpenID Connect Configuration URL (например, https://iam.api.cloud.yandex.net/iam/v2/applications/{app-id}/.well-known/openid-configuration)
```


**1.3 Добавить пользователей в приложение (use case):**
```bash
# Консоль → Organization → Users and groups
# → Добавить пользователя (Invite user) → email партнера/сотрудника
# → Organization → Applications → demo-auth-app → Users and groups → Assign users/groups
# → выбрать нужных пользователей → Save
```
Теперь только добавленные пользователи смогут получить токен через OIDC flow. [yandex](https://yandex.cloud/en/docs/tutorials/serverless/jwt-authorizer-firebase)

***

## Шаг 2: Создать Service Account и настроить права

**2.1 Создать SA:**
```bash
yc iam service-account create \
  --name demo-backend-sa \
  --description "SA for serverless container"
  
# Запишите service-account-id
SA_ID=$(yc iam service-account get demo-backend-sa --format json | jq -r .id)
```

**2.2 Назначить роли:**
```bash
# Для доступа к YDB
yc resource-manager folder add-access-binding <folder-id> \
  --role ydb.editor \
  --subject serviceAccount:$SA_ID

# Для доступа к Object Storage (если нужно из backend)
yc resource-manager folder add-access-binding <folder-id> \
  --role storage.editor \
  --subject serviceAccount:$SA_ID

# Для логов в Cloud Logging
yc resource-manager folder add-access-binding <folder-id> \
  --role logging.writer \
  --subject serviceAccount:$SA_ID
```


***

## Шаг 3: Подготовить Python backend и контейнер

**3.1 Структура проекта:**
```
backend/
├── app.py
├── requirements.txt
└── Dockerfile
```

**3.2 `app.py` (FastAPI пример):**
```python
from fastapi import FastAPI, Header
import uvicorn

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/user")
def get_user(authorization: str = Header(None)):
    # JWT уже провалидирован API Gateway
    # Можно извлечь claims из заголовков, которые пробросил gateway
    return {"message": "Authorized user", "token_present": bool(authorization)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

**3.3 `requirements.txt`:**
```
fastapi==0.115.0
uvicorn[standard]==0.30.0
```

**3.4 `Dockerfile`:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
```


**3.5 Собрать и запушить образ:**
```bash
# Создать Container Registry
yc container registry create --name demo-registry
REGISTRY_ID=$(yc container registry get demo-registry --format json | jq -r .id)

# Аутентификация Docker
yc container registry configure-docker

# Собрать образ (для linux/amd64)
docker build --platform linux/amd64 -t cr.yandex/${REGISTRY_ID}/demo-backend:v1 .

# Запушить
docker push cr.yandex/${REGISTRY_ID}/demo-backend:v1
```


***

## Шаг 4: Создать Serverless Container

```bash
# Создать контейнер
yc serverless container create --name demo-backend-container

# Деплой ревизии
yc serverless container revision deploy \
  --container-name demo-backend-container \
  --image cr.yandex/${REGISTRY_ID}/demo-backend:v1 \
  --service-account-id $SA_ID \
  --memory 512M \
  --execution-timeout 30s \
  --concurrency 4

# Запишите container-id
CONTAINER_ID=$(yc serverless container get demo-backend-container --format json | jq -r .id)
```


***

## Шаг 5: Создать API Gateway с JWT authorizer

**5.1 `api-gateway.yaml`:**
```yaml
openapi: 3.0.0
info:
  title: Demo Auth API
  version: 1.0.0

# Определение security scheme с JWT authorizer
components:
  securitySchemes:
    jwtAuth:
      type: openIdConnect
      openIdConnectUrl: https://iam.api.cloud.yandex.net/iam/v2/applications/<app-id>/.well-known/openid-configuration
      x-yc-apigateway-authorizer:
        type: jwt
        jwksUri: https://iam.api.cloud.yandex.net/iam/v2/applications/<app-id>/.well-known/jwks.json
        issuers:
          - https://iam.api.cloud.yandex.net/iam/v2/applications/<app-id>
        audiences:
          - <client-id>
        identitySource:
          in: header
          name: Authorization
          prefix: "Bearer "
        authorizer_result_ttl_in_seconds: 300

# Применить авторизацию ко всем эндпойнтам
security:
  - jwtAuth: []

paths:
  /api/user:
    get:
      summary: Get user info
      operationId: getUser
      x-yc-apigateway-integration:
        type: serverless_containers
        container_id: <container-id>
        service_account_id: <sa-id>
      responses:
        '200':
          description: OK

  /health:
    get:
      summary: Health check (без авторизации для мониторинга)
      security: []  # Переопределить, чтобы был публичный
      x-yc-apigateway-integration:
        type: serverless_containers
        container_id: <container-id>
        service_account_id: <sa-id>
      responses:
        '200':
          description: OK
```


**5.2 Подставить параметры:**
- `<app-id>` — из шага 1.2 (из OpenID Connect Configuration URL).
- `<client-id>` — Client ID из шага 1.2.
- `<container-id>` — `$CONTAINER_ID` из шага 4.
- `<sa-id>` — `$SA_ID` из шага 2.

**5.3 Создать API Gateway:**
```bash
yc serverless api-gateway create \
  --name demo-api-gateway \
  --spec api-gateway.yaml

# Запишите default domain (например, https://d5d123abc.apigw.yandexcloud.net)
API_GW_DOMAIN=$(yc serverless api-gateway get demo-api-gateway --format json | jq -r .domain)
```


***

## Шаг 6: Создать Object Storage bucket для фронта

**6.1 Создать bucket:**
```bash
# Консоль → Object Storage → Create bucket
# Имя: demo-static-site (должно быть уникальным)
# ACL: Public read objects + Public read object list
# Website → Enable
#   Homepage: index.html
#   Error: error.html
```


**6.2 Обновить Redirect URI в OIDC приложении:**
```bash
# Консоль → Organization → Applications → demo-auth-app → Edit
# Redirect URIs: https://demo-static-site.website.yandexcloud.net/callback.html
# → Save
```

***

## Шаг 7: Подготовить статические страницы

**7.1 `index.html`:**
```html
<!DOCTYPE html>
<html>
<head>
    <title>Demo Auth App</title>
</head>
<body>
    <h1>Welcome to Demo Auth App</h1>
    <div id="status">Checking auth...</div>
    <button id="loginBtn" style="display:none">Login</button>
    <button id="logoutBtn" style="display:none">Logout</button>
    <div id="userData" style="display:none"></div>
    <script src="app.js"></script>
</body>
</html>
```

**7.2 `callback.html`:**
```html
<!DOCTYPE html>
<html>
<head><title>Callback</title></head>
<body>
    <p>Processing login...</p>
    <script>
        // Извлечь id_token из hash fragment (#id_token=...)
        const hash = window.location.hash.substring(1);
        const params = new URLSearchParams(hash);
        const idToken = params.get('id_token');
        if (idToken) {
            localStorage.setItem('id_token', idToken);
            window.location.href = '/index.html';
        } else {
            document.body.innerHTML = '<p>Login failed</p>';
        }
    </script>
</body>
</html>
```

**7.3 `app.js`:**
```javascript
const CLIENT_ID = '<client-id>';
const AUTH_URL = 'https://iam.api.cloud.yandex.net/iam/v2/applications/<app-id>/oauth/authorize';
const API_BASE = 'https://<api-gateway-domain>';

const loginBtn = document.getElementById('loginBtn');
const logoutBtn = document.getElementById('logoutBtn');
const statusDiv = document.getElementById('status');
const userDataDiv = document.getElementById('userData');

function login() {
    const redirectUri = window.location.origin + '/callback.html';
    const authUrl = `${AUTH_URL}?client_id=${CLIENT_ID}&response_type=id_token&scope=openid email profile&redirect_uri=${encodeURIComponent(redirectUri)}&nonce=random123`;
    window.location.href = authUrl;
}

function logout() {
    localStorage.removeItem('id_token');
    location.reload();
}

async function fetchUser() {
    const token = localStorage.getItem('id_token');
    if (!token) {
        statusDiv.textContent = 'Not authenticated';
        loginBtn.style.display = 'block';
        return;
    }
    
    try {
        const res = await fetch(`${API_BASE}/api/user`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (res.ok) {
            const data = await res.json();
            statusDiv.textContent = 'Authenticated';
            userDataDiv.textContent = JSON.stringify(data, null, 2);
            userDataDiv.style.display = 'block';
            logoutBtn.style.display = 'block';
        } else {
            throw new Error('Unauthorized');
        }
    } catch (err) {
        statusDiv.textContent = 'Auth failed';
        localStorage.removeItem('id_token');
        loginBtn.style.display = 'block';
    }
}

loginBtn.addEventListener('click', login);
logoutBtn.addEventListener('click', logout);
fetchUser();
```


**7.4 Подставить параметры:**
- `<client-id>`, `<app-id>` — из шага 1.2.
- `<api-gateway-domain>` — из шага 5.3.

**7.5 Загрузить в bucket:**
```bash
# Через консоль → Object Storage → demo-static-site → Upload
# Загрузить index.html, callback.html, app.js, error.html (опционально)
```


***

## Шаг 8: Проверка работы

**8.1 Открыть сайт:**
```
https://demo-static-site.website.yandexcloud.net/index.html
```

**8.2 Сценарий:**
1. Страница показывает "Checking auth..." и кнопку "Login".  
2. Нажать "Login" → редирект на OIDC Authorization endpoint Identity Hub.  
3. Ввести credentials пользователя, добавленного в шаге 1.3.  
4. После успешного логина → редирект на `callback.html` → токен сохранен → возврат на `index.html`.  
5. JS делает запрос к `/api/user` с токеном → API Gateway валидирует JWT → проксирует в контейнер → ответ отображается.  
6. Кнопка "Logout" очищает токен.

**8.3 Проверка неавторизованного доступа:**
```bash
# Без токена
curl https://<api-gateway-domain>/api/user
# Ожидается: 401 Unauthorized

# С невалидным токеном
curl -H "Authorization: Bearer fake123" https://<api-gateway-domain>/api/user
# Ожидается: 401 Unauthorized
```


***

## Use Case: Добавление нового пользователя

**Задача:** Партнер Иван (ivan@partner.com) просит доступ к приложению.

**Шаги администратора:**
1. Консоль → Organization → Users and groups → Invite user → ввести `ivan@partner.com` → Send invitation.  
2. Иван получает e-mail, подтверждает и создает Yandex ID аккаунт (если нет).  
3. Консоль → Organization → Applications → demo-auth-app → Users and groups → Assign → выбрать Ivan → Save.  
4. Иван открывает `https://demo-static-site.website.yandexcloud.net` → Login → вводит credentials → получает доступ.  

**Результат:** только пользователи, явно назначенные в OIDC приложении, могут логиниться. [yandex](https://yandex.cloud/en/docs/tutorials/serverless/jwt-authorizer-firebase)

***

## Итоговая схема компонентов

| Компонент | Назначение | Стоимость |
|-----------|-----------|-----------|
| Identity Hub OIDC app | Аутентификация сотрудников/партнеров | Бесплатно  [yandex](https://yandex.cloud/en/docs/organization/concepts/limits) |
| Object Storage bucket | Хостинг статического фронта | ~0 USD (5 GB free)  [yandex](https://yandex.cloud/en/prices) |
| API Gateway | JWT валидация + роутинг | ~0 USD (100k запросов free)  [yandex](https://yandex.cloud/en/docs/api-gateway/pricing) |
| Serverless Container | Python backend | ~0-1 USD/месяц  [yandex](https://yandex.cloud/en/prices) |
| Container Registry | Хранение Docker образов | ~0.05 USD/месяц  [yandex](https://yandex.cloud/en/prices) |
| Service Account | Права доступа | Бесплатно |

