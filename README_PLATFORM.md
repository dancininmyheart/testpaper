# 平台运行说明（Flask Fullstack）

## 1. 安装依赖

```bash
pip install -r backend/requirements.txt
```

## 2. 一键启动（前后端都由 Flask 提供）

```bash
python run_fullstack_dev.py
```

默认访问地址：

- 页面与 API：`http://127.0.0.1:8020`

## 3. 单独启动（等价）

```bash
python run_platform_server.py --host 0.0.0.0 --port 8020
```

## 4. 健康检查

```bash
curl http://127.0.0.1:8020/health
```
