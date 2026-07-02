"""postgres_memory_operations — 生产环境记忆数据库部署与运维手册

所属层：docs
依赖：PostgreSQL, pg_dump, pg_restore, LangGraph PostgresSaver/PostgresStore
对接算法层：N/A
"""

# PostgreSQL 记忆数据库部署与运维

## 1. 生产配置

L1 checkpoint 与 L2 store 共用一个 PostgreSQL 数据库、使用不同表。应用环境变量：

```env
MEMORY_ENABLED=true
MEMORY_USE_POSTGRES_STORE=true
MEMORY_DEMO_FILE_STORE_ENABLED=false
MEMORY_POSTGRES_DSN=postgresql://energraph_app:***@postgres:5432/energraph
MEMORY_POSTGRES_POOL_MIN_SIZE=1
MEMORY_POSTGRES_POOL_MAX_SIZE=10
MEMORY_POSTGRES_SETUP_ENABLED=false
MEMORY_AUTO_EXTRACT_ENABLED=true
```

连接池上限应乘以应用进程数计算。例如 4 个 worker、每个 `max_size=10`，数据库需承受至少 40 个 L2 连接；L1 checkpoint 连接另计。

## 2. 首次初始化

创建数据库和迁移账号：

```sql
CREATE USER energraph_migrator WITH PASSWORD 'replace_me';
CREATE USER energraph_app WITH PASSWORD 'replace_me';
CREATE DATABASE energraph OWNER energraph_migrator;
```

首次启动使用迁移账号，并临时设置：

```env
MEMORY_POSTGRES_DSN=postgresql://energraph_migrator:***@postgres:5432/energraph
MEMORY_POSTGRES_SETUP_ENABLED=true
```

服务启动会分别调用 `PostgresSaver.setup()` 与 `PostgresStore.setup()`。L2 会创建/迁移 `store`、`store_migrations`；配置向量索引后还会使用 `store_vectors`、`vector_migrations`。当前 L2 使用确定性 JSON 检索，不要求 pgvector。

初始化后授予应用账号读写权限，并切换为 `MEMORY_POSTGRES_SETUP_ENABLED=false`：

```sql
GRANT CONNECT ON DATABASE energraph TO energraph_app;
GRANT USAGE ON SCHEMA public TO energraph_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO energraph_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO energraph_app;
ALTER DEFAULT PRIVILEGES FOR USER energraph_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO energraph_app;
```

## 3. 升级与回滚

1. 升级前执行逻辑备份并记录当前应用版本、LangGraph 依赖版本。
2. 只启动一个迁移实例，使用迁移账号和 `MEMORY_POSTGRES_SETUP_ENABLED=true`。
3. 迁移成功后关闭迁移实例，再启动普通应用实例。
4. 执行写入、检索、同 `memory_key` 更新、跨进程读取冒烟测试。
5. 回滚应用前确认新 migration 是否向后兼容；不兼容时先停写，再恢复升级前备份。

禁止多个应用 worker 同时承担首次迁移职责。

## 4. 备份与恢复

每日自定义格式备份：

```bash
pg_dump --format=custom --no-owner --file=energraph_YYYYMMDD.dump "$MEMORY_POSTGRES_DSN"
```

恢复演练必须在独立数据库进行：

```bash
createdb energraph_restore_test
pg_restore --clean --if-exists --no-owner --dbname=energraph_restore_test energraph_YYYYMMDD.dump
```

恢复后验证：

- checkpoint 能按 `thread_id` 恢复；
- L2 能按 `env/site_id/agent_id/scope/entity_id` 检索；
- 同一 `memory_key` 更新后只有一条记录；
- 过期 `device_state` 不会进入回答。

生产数据库建议同时启用云盘/数据库服务的时间点恢复（PITR），并定期验证备份可恢复，而不只是验证备份文件存在。

## 5. 多进程一致性

用户偏好使用 `namespace + memory_key` 派生的确定性 UUID 作为 PostgresStore key。不同 worker 写同一偏好时落在同一行，由 PostgreSQL UPSERT 原子覆盖，不依赖单机锁。普通记忆使用独立 UUID。

应用进程不得启用 `MEMORY_DEMO_FILE_STORE_ENABLED`；JSON 文件既不支持跨进程锁，也不属于生产数据源。

## 6. 上线验收

- `MEMORY_DEMO_FILE_STORE_ENABLED=false`
- `MEMORY_USE_POSTGRES_STORE=true`
- 普通应用账号无法执行 DDL，但可读写记忆表
- 两个应用进程之间可立即读取对方写入的偏好
- 服务重启后偏好和 checkpoint 均可恢复
- 数据库不可用时 Agent 主流程降级，不因记忆异常崩溃
- 已配置备份保留周期、恢复演练和数据库监控告警

## 7. 本地真实验收记录

2026-07-01 使用 Homebrew PostgreSQL 17.10 完成真实链路验证：

- L2 `PostgresStore.setup()` 成功，无初始化错误；
- 相同 `memory_key` 连续更新返回相同 ID；
- 关闭连接池、重建 `MemoryStore` 后仍能检索更新值；
- 清理测试 namespace 后 `store` 表记录数为 0；
- L1/L2 共库生成 `checkpoint_blobs`、`checkpoint_migrations`、`checkpoint_writes`、`checkpoints`、`store`、`store_migrations`。

该记录只证明本机单实例链路可用；服务器仍需复验网络、权限、多 worker 并发、备份恢复和监控告警。
