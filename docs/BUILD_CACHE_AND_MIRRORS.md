# 构建缓存与国内源

项目已默认配置国内依赖源，减少阿里云 ECS 构建时的超时和下载慢问题。

## Python 后端

默认 PyPI 源：

```text
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
```

`backend/Dockerfile` 中先复制 `requirements.txt`，再执行依赖安装：

```dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip -i "${PIP_INDEX_URL}" \
    && pip install --no-cache-dir -r requirements.txt -i "${PIP_INDEX_URL}"
```

只要 `backend/requirements.txt` 没变化，Docker 会复用这一层缓存；修改业务代码后重新构建 backend，不会重新安装 Python 依赖。

## React 前端

默认 npm 源：

```text
NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
```

同样地，只要 `frontend/package-lock.json` 没变化，`npm ci` 这一层会被 Docker 缓存复用。

## 推荐部署命令

日常更新代码时，不要使用 `--no-cache`：

```bash
cd /opt/sip-fastapi-react-postgresql-asterisk-docker
git pull origin main
docker compose up -d --pull never asterisk postgres
docker compose up -d --build backend frontend nginx
docker compose ps
```

如果只更新后端代码：

```bash
docker compose up -d --no-deps --build backend
docker compose restart nginx
```

只有在依赖文件变化或镜像缓存损坏时，才需要清理缓存后重建。
