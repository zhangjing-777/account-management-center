# Account Management Center

## 项目概述

这是一个基于 FastAPI 构建的用户账户管理中心，专门为 ReceiptDrop 项目提供用户管理、订阅管理、支付处理和联系表单等核心功能。系统采用加密存储敏感信息，符合欧盟 GDPR 数据保护规范。

## 主要功能

### 1. 用户管理
- **新用户同步**: 自动同步新注册用户到系统
- **账户状态检查**: 查询用户订阅状态、虚拟盒子状态和使用配额信息
- **加密存储**: 用户邮箱等敏感信息采用 Fernet 加密算法存储

### 2. 支付管理 (Stripe 集成)
- **支付处理**: 处理 Stripe 支付成功回调，自动升级用户为 Pro 会员
- **订阅管理**: 创建 Stripe Customer Portal 会话，用户可自主管理订阅
- **Webhook 处理**: 处理 Stripe 支付相关的 webhook 事件
- **配额管理**: 根据订阅状态自动调整用户的使用配额

### 3. 联系表单管理
- **企业联系**: 处理企业级用户的联系表单提交
- **个人联系**: 处理个人用户的联系表单提交
- **数据加密**: 联系信息中的敏感字段（邮箱、姓名、消息等）进行加密存储

### 4. 配额系统
- **收据配额**: 管理用户每月收据处理配额
- **请求配额**: 管理用户每月 API 请求配额
- **使用统计**: 实时跟踪用户配额使用情况

## 技术架构

- **框架**: FastAPI
- **数据库**: PostgreSQL (通过 asyncpg 连接)
- **支付**: Stripe API
- **存储**: Supabase
- **加密**: Cryptography (Fernet)
- **调度**: APScheduler
- **容器化**: Docker

## API 端点

### 用户管理
- `POST /users/sync-new-users` - 同步新用户
- `POST /users/account-check` - 检查用户账户状态

### 支付管理
- `POST /stripe/paid-manager` - 处理支付成功回调
- `POST /stripe/subscript-manager` - 创建客户门户会话
- `POST /stripe/webhook-handler` - 处理 Stripe webhook

### 联系表单
- `POST /contact/enterprise-insert-update` - 企业联系表单
- `POST /contact/individual-insert-update` - 个人联系表单

### 系统监控
- `GET /health` - 健康检查

## 环境配置

创建 `.env` 文件并配置以下环境变量：

```env
# 数据库配置
DB_HOST=localhost
DB_PORT=5432
DB_NAME=your_database_name
DB_USER=your_username
DB_PASSWORD=your_password

# Supabase 配置
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key

# Stripe 配置
STRIPE_API_KEY=your_stripe_api_key
STRIPE_WEBHOOK_SECRET=your_stripe_webhook_secret

# 加密密钥
ENCRYPTION_KEY=your_encryption_key
```

## 部署方式

### Docker 部署
```bash
# 构建并启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f account-management-center
```

### 本地开发
```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

## 安全特性

- **数据加密**: 所有敏感字段（邮箱、姓名、消息等）在存储前进行加密
- **GDPR 合规**: 符合欧盟数据保护规范
- **日志记录**: 完整的操作日志记录，便于审计和调试
- **异常处理**: 全局异常处理器确保系统稳定性

## 监控和日志

- 日志文件存储在 `logs/` 目录下，按日期分割
- 支持健康检查端点监控服务状态
- 详细的错误日志记录便于问题排查

## 项目结构

```
account-management-center/
├── app.py                 # 主应用入口
├── config.py             # 配置管理
├── encryption.py         # 加密工具
├── auth_new_user/        # 新用户认证模块
├── account_check/        # 账户检查模块
├── contact_manager/      # 联系表单管理
├── stripe_manager/       # Stripe 支付管理
├── logs/                 # 日志目录
├── requirements.txt      # Python 依赖
├── Dockerfile           # Docker 配置
└── docker-compose.yml   # Docker Compose 配置
```

## 版本信息

- **版本**: 1.0.0
- **Python**: 3.11+
- **FastAPI**: 最新稳定版
- **端口**: 8011 (Docker) / 8000 (本地)
