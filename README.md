# 服务故障共现研判

时序共现关联的真实业务分析小型项目。完整模拟客户、痛点、上下游、算法公式与一天工作剧本见 [BUSINESS.md](BUSINESS.md)。

## 模块与业务流程
数据接入（JSON/CSV、字段验证、批次指纹）→ 参数化分析（异步 Python worker）→ 结果复核（指标、图形、明细、解释、批准）→ 定时分发（本地收件箱、CSV/JSON、SHA256）；另有业务总览和审计轨迹。
三个贯穿全栈的实体：Dataset 数据批次、Job 分析任务、Report 分发计划；辅助 User、Audit、Delivery。

## 快速启动
```bash
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18212；后端文档 http://localhost:19212/docs；数据库宿主端口 17712。
`SEED_DEMO=true` 自动幂等 seed；不覆盖用户修改。手动 seed 命令可重复执行。

## 演示账号与权限
|账号|密码|真实权限|
|---|---|---|
|admin@demo.local|Demo123!|接入、执行、批准、分发、暂停、读取与下载、外协授权与隐私预算锁定|
|analyst@demo.local|Demo123!|接入、执行、读取与下载；不能批准或安排分发|
|viewer@demo.local|Demo123!|只读与下载|
|external@demo.local|Demo123!|外协：仅查询被圈定批次的拉普拉斯加噪计数，无权访问事件明细、原分析、归档下载与审计|

### 外协差分隐私（DP）协作面
外协只读账号原本可下载事件明细，现通过独立 `external` 角色收敛为「加噪计数」单一面：
- 负责人按批次**内容指纹**锁定总隐私预算 ε（锁定后不可调整），并把批次圈定给外协账号。
- 外协仅能查询授权批次的各服务告警数：事件级计数敏感度 Δ=1，采用 Laplace 机制，噪声尺度 `scale=1/ε`；单次 ε 可选 0.05~5。
- **同内容批次共用预算账本**：内容指纹只取决于事件字段（按 event_id 规范化哈希），批次改名、换账号上传、行重排都得到同一指纹，无法绕过累计预算。
- 每个事件最多贡献一次；相同 `query_key` 重试返回同一份加噪结果，**不重复扣费、不重新加噪**。
- 并发查询经 `SELECT … FOR UPDATE` 账本行锁串行化，余额不足返回 402，绝不透支；扣费（reserved）与结果发布（published）在同一事务内共同生效，中断未发布由 worker 超时退还（refunded）。
- 外协页面与接口仅暴露加噪计数与剩余预算；`/datasets`、`/jobs`、`/reports`、`/deliveries`、`/audits`、`/overview` 对该角色统一 403。
- 后端接口前缀 `/privacy`：负责人面 `ledgers`、`grants`、`datasets/{id}/lock-budget`、`queries`；外协面 `my/datasets`、`my/ledger/{id}`、`my/queries`、`queries`（POST 加噪查询）。

## 技术与本地开发
Python 3.12 / FastAPI / SQLAlchemy / NumPy / SciPy / scikit-learn；PostgreSQL 16；Redis 7；Nginx；原生 HTML CSS JavaScript ES modules（用户指定）。后端所有校验、持久化和算法在服务端。无前端打包步骤。
后端：安装 backend/requirements.txt，设置 DATABASE_URL、REDIS_URL、JWT_SECRET、ARTIFACT_DIR 后在 backend/ 执行 `python -m migrations.initial`、`python -m scripts.seed_demo`、`uvicorn src.main:app`，另开 `python -m src.worker`。前端使用带 /api 反向代理的 Nginx，直接打开 index.html 不支持 API。

## 目录与工程约定
backend/src/{models,schemas,services,routes,controllers,middlewares,constants,config,utils}；backend/scripts/seed_demo.py；backend/migrations/initial.py。
frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}。
Role 枚举：admin/analyst/viewer/external；JobStatus：queued/running/completed/failed；DpQueryStatus：reserved/published/refunded。后端 backend/src/constants/enums.py，前端 frontend/src/constants/enums.js；路由权限在 middlewares/auth.py（含 deny_external 与 external_only 守卫）；页面按相同角色控制操作入口。

## 环境变量与 Docker
COMPOSE_PROJECT_NAME=incident-links；FRONTEND_PORT=18212；BACKEND_PORT=19212；DB_PORT=17712；DB_PASSWORD、JWT_SECRET 见 .env.example；SEED_DEMO 默认 true。共享命名产物卷供后端下载与 worker 写入，数据库/Redis 各持久卷。
恰好五服务均有健康检查。Redis 队列加 SQL 排队状态兜底；worker 按 next_run 生成本地收件箱文件。周期 60 秒至 30 天。分发结果为批准分析的固定快照；若需新数据重新计算并建立新计划。当前不连接邮件或企业聊天。
错误响应、请求编号、Redis 每 IP 每分钟 240 次限流、JWT 和数据库操作审计。演示密钥与密码仅供本机模拟；生产部署前配置独立密钥与账号。

## 数据与验收
所有数据为固定随机种子生成的模拟业务数据，不能作为实际生产决策证据。项目独立算法、输入边界及业务局限详见 BUSINESS.md。测试与截图统一存放 ../../test-artifacts/gb-1013/，源码不含日志/截图/测试报告。
清理本项目演示数据：`docker compose down -v --remove-orphans`（会删除本项目命名卷）。

## License
MIT，见 LICENSE。
