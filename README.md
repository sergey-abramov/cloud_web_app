## Cloud Web App — демо аутентификации в Yandex Cloud

Этот репозиторий — **демонстрационный backend на FastAPI**, который обычно разворачивается в **Yandex Cloud Serverless Containers** и вызывается через **API Gateway** с **JWT authorizer** (Identity Hub / OIDC). Для демо/разработки сервис можно запускать локально через Docker.

Ниже — **пошаговая инструкция** как развернуть проект в своём облаке Yandex Cloud (через CLI `yc` + немного действий в консоли там, где это пока удобнее/быстрее). Исходный черновик с пояснениями лежит в `cloud_web_app.md`, а набор “быстрых” команд — в `comands.txt`.

### Архитектура (как задумано)

```
Пользователь (браузер)
    ↓
[Object Storage static site] → index.html + login.html
    ↓ (JS fetch с Bearer token)
API Gateway (JWT authorizer)
    ↓ (проксирует авторизованные запросы)
Serverless Container (FastAPI)
```

### Что есть в приложении

- **Backend**: `app/main.py` (FastAPI), порт `8080`.
- **Роуты пользователей**: `app/routers/users.py` (подключён с префиксом `/users`).
- **Ключевая идея**: для защищённых эндпойнтов **JWT валидируется на уровне API Gateway**, а backend получает распарсенный контекст пользователя из заголовка:
  - `X-Yc-Apigateway-Authorizer-Context` (JSON, формируется API Gateway после успешной проверки токена).

### Эндпойнты

- **GET `/`** — базовая проверка, что сервис отвечает.
- **GET `/health`** — health-check (в облаке обычно делают публичным).
- **GET `/users/`** — демо-ответ со списком пользователей.
- **GET `/users/api/user`** — защищённый эндпойнт: возвращает информацию о пользователе из `X-Yc-Apigateway-Authorizer-Context`.
- **GET `/users/debug/headers`** — отладка: показывает все заголовки запроса и authorizer context.

### Локальный запуск (Docker)

Требования: установленный Docker / Docker Compose.

```bash
docker compose up --build
```

После старта:
- `http://localhost:8080/` — корневой эндпойнт
- `http://localhost:8080/health` — health-check
- `http://localhost:8080/docs` — Swagger UI

Переменные окружения берутся из `.env` (сейчас используется `PORT=8080`).

### Развертывание в Yandex Cloud (пошагово)

#### 0) Предварительные требования

- У вас есть аккаунт в Yandex Cloud, подключён биллинг.
- Вы знаете:
  - **Folder ID** (куда создаём ресурсы)
  - **Cloud ID** (не обязательно, но удобно)
  - **Organization** (для Identity Hub приложений)
- Локально установлен Docker (для сборки образа).
- Утилита `jq` (используется в командах ниже для извлечения ID из JSON).

Установка `jq` (Ubuntu/WSL):

```bash
sudo apt-get update && sudo apt-get install -y jq
```

Дальше для удобства заведём переменные (подставьте свои значения):

```bash
export YC_CLOUD_ID="<your-cloud-id>"
export YC_FOLDER_ID="<your-folder-id>"
export YC_ORG_ID="<your-organization-id>"

export APP_NAME="cloud-web-app"
export IMAGE_NAME="cloud_web_app"
export IMAGE_TAG="latest"
```

#### 1) Установка и инициализация Yandex Cloud CLI (`yc`) от имени обычного пользователя

Установка (Linux/WSL):

```bash
curl -sSL https://storage.yandexcloud.net/yandexcloud-yc/install.sh | bash
exec -l $SHELL
yc version
```

Инициализация профиля (интерактивно):

```bash
yc init
```

Дальше укажите:
- аккаунт (OAuth),
- cloud,
- folder,
- зону по умолчанию (если спросит).

Если вы уже завели переменные выше — можно явно выставить cloud/folder:

```bash
yc config set cloud-id "$YC_CLOUD_ID"
yc config set folder-id "$YC_FOLDER_ID"
yc config list
```

#### 2) Создать OIDC приложение в Identity Hub (JWT для API Gateway)

На практике этот шаг обычно делают через консоль (быстрее и нагляднее).

В консоли Yandex Cloud:
- **Organization → Applications → Create**
- **Тип**: OIDC
- **Redirect URI**: укажите `https://<your-bucket>.website.yandexcloud.net/callback.html`
  - если bucket ещё не создан, можно временно поставить заглушку и вернуться позже
- **Scopes**: `openid`, `email`, `profile`

Сохраните значения (они понадобятся в `api-gateway.yaml` и фронту):
- **Client ID**
- **Application ID (app-id)**
- **OpenID Connect configuration URL** вида  
  `https://iam.api.cloud.yandex.net/iam/v2/applications/<app-id>/.well-known/openid-configuration`

Также добавьте пользователей/группы в приложение (иначе токены получать не смогут):
- **Organization → Users and groups** (пригласить пользователей)
- **Organization → Applications → <ваше OIDC приложение> → Users and groups → Assign**

#### 3) Создать service account для контейнера и выдать права

Создать service account:

```bash
yc iam service-account create \
  --name "${APP_NAME}-sa" \
  --description "SA for ${APP_NAME} (serverless container runtime)"

export SA_ID="$(yc iam service-account get "${APP_NAME}-sa" --format json | jq -r .id)"
echo "$SA_ID"
```

Выдать роли на folder (минимально полезный набор для демо):

```bash
# Логи в Cloud Logging
yc resource-manager folder add-access-binding "$YC_FOLDER_ID" \
  --role logging.writer \
  --subject "serviceAccount:${SA_ID}"

# Доступ к YDB (если используете из backend)
yc resource-manager folder add-access-binding "$YC_FOLDER_ID" \
  --role ydb.editor \
  --subject "serviceAccount:${SA_ID}"

# Доступ к Object Storage (если backend будет читать/писать в бакеты)
yc resource-manager folder add-access-binding "$YC_FOLDER_ID" \
  --role storage.editor \
  --subject "serviceAccount:${SA_ID}"
```

> Примечание: роли можно сузить под ваш реальный use-case. Для простого демо без YDB/S3 — оставьте только `logging.writer`.

#### 4) Container Registry: создать реестр, настроить Docker и права на pull образов

Создать Container Registry:

```bash
yc container registry create --name "${APP_NAME}-registry"
export REGISTRY_ID="$(yc container registry get "${APP_NAME}-registry" --format json | jq -r .id)"
echo "$REGISTRY_ID"
```

Настроить Docker на работу с реестром:

```bash
yc container registry configure-docker
```

Дать service account право **скачивать** образы из реестра (иначе Serverless Container не сможет подтянуть приватный image):

```bash
yc container registry add-access-binding "$REGISTRY_ID" \
  --role container-registry.images.puller \
  --subject "serviceAccount:${SA_ID}"
```

#### 5) Собрать и запушить Docker-образ

Сборка (рекомендуется `linux/amd64`, если собираете не на amd64):

```bash
docker build --platform=linux/amd64 --pull --rm -f "Dockerfile" -t "${IMAGE_NAME}:${IMAGE_TAG}" "."
```

Тег + push в Yandex Container Registry:

```bash
export REMOTE_IMAGE="cr.yandex/${REGISTRY_ID}/${IMAGE_NAME}:${IMAGE_TAG}"
docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "${REMOTE_IMAGE}"
docker push "${REMOTE_IMAGE}"
```

#### 6) Serverless Containers: создать контейнер и задеплоить ревизию

```bash
yc serverless container create --name "${APP_NAME}-container"

yc serverless container revision deploy \
  --container-name "${APP_NAME}-container" \
  --image "${REMOTE_IMAGE}" \
  --service-account-id "${SA_ID}" \
  --memory 512M \
  --execution-timeout 30s \
  --concurrency 4

export CONTAINER_ID="$(yc serverless container get "${APP_NAME}-container" --format json | jq -r .id)"
echo "$CONTAINER_ID"
```

#### 7) API Gateway: подготовить `api-gateway.yaml` (JWT authorizer + интеграция)

В репозитории есть `api-gateway.yaml`. В нём нужно заменить плейсхолдеры:
- `<app-id>` — из Identity Hub (шаг 2)
- `<client-id>` — из Identity Hub (шаг 2)
- `<container-id>` — переменная `$CONTAINER_ID` (шаг 6)
- `<sa-id>` — переменная `$SA_ID` (шаг 3)

#### 8) API Gateway: создать gateway из спеки

```bash
yc serverless api-gateway create \
  --name "${APP_NAME}-apigw" \
  --spec api-gateway.yaml

export API_GW_DOMAIN="$(yc serverless api-gateway get "${APP_NAME}-apigw" --format json | jq -r .domain)"
echo "https://${API_GW_DOMAIN}"
```

#### 9) Проверка

Публичный health-check (должен отвечать без токена):

```bash
curl "https://${API_GW_DOMAIN}/health"
```

Защищённые эндпойнты без токена должны отдавать 401 (если вы включили security на gateway):

```bash
curl -i "https://${API_GW_DOMAIN}/users/api/user"
```

#### 10) (Опционально) Статический фронт в Object Storage

Полный пример фронта (страницы `index.html`, `callback.html`, `app.js`) и общий flow логина описаны в `cloud_web_app.md`.

Коротко:
- создайте bucket со включённым website hosting,
- пропишите правильный Redirect URI в OIDC приложении,
- загрузите статические файлы в bucket,
- в `app.js` укажите ваш `<client-id>`, `<app-id>`, и домен API Gateway.
