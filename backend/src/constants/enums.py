from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'
    external = 'external'
class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
# 外协差分隐私查询的两阶段状态：预留扣费 -> 发布；中断未发布可退还
class DpQueryStatus(str, Enum):
    reserved = 'reserved'
    published = 'published'
    refunded = 'refunded'
