# 个人助手网页端

React + Vite + Tailwind 前端，用于展示日报、中文摘要并支持日报问答。

## 开发

```powershell
npm install
npm run dev
```

Vite 开发服务默认运行在 `http://127.0.0.1:5173/`，并将 `/api` 代理到 `http://127.0.0.1:8000`。

## 构建

```powershell
npm run build
```

构建产物位于 `web/dist/`，由 FastAPI 在 `/app` 路径提供。

## 校验

```powershell
npm run lint
npm run build
```