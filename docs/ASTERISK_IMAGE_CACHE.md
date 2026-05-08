# Asterisk 镜像缓存部署说明

为避免阿里云 ECS 在每次部署时反复访问 Docker Hub 并触发 `Too Many Requests`，`docker-compose.yml` 中的 `asterisk` 服务默认不再执行 Dockerfile 构建，而是直接使用本机镜像：

```text
ASTERISK_IMAGE=asterisk/asterisk:20
```

并设置：

```yaml
pull_policy: missing
```

含义是：本机已有该镜像时直接复用；只有镜像不存在时才尝试拉取。

## 推荐更新部署命令

日常更新代码时，只重建业务服务：

```bash
cd /opt/sip-fastapi-react-postgresql-asterisk-docker
git pull origin main
docker compose up -d --build backend frontend nginx
docker compose up -d postgres asterisk
docker compose ps
```

如果确实需要完整启动，也可以执行：

```bash
docker compose up -d --build
```

此时 Asterisk 不会被构建，只会复用本机已有的 `asterisk/asterisk:20` 镜像。

## 如果 ECS 上已有镜像

确认本机镜像：

```bash
docker images | grep 'asterisk'
```

看到 `asterisk/asterisk 20` 即可。

## 如果 ECS 上没有镜像

可以先单独拉一次，避开整套部署反复重试：

```bash
docker pull asterisk/asterisk:20
```

如果 Docker Hub 仍限流，可以改用你自己的镜像仓库，例如阿里云 ACR：

```bash
docker tag asterisk/asterisk:20 registry.cn-guangzhou.aliyuncs.com/<命名空间>/asterisk:20
docker push registry.cn-guangzhou.aliyuncs.com/<命名空间>/asterisk:20
```

然后在 `.env` 里改：

```text
ASTERISK_IMAGE=registry.cn-guangzhou.aliyuncs.com/<命名空间>/asterisk:20
```

再启动：

```bash
docker compose up -d asterisk
```
