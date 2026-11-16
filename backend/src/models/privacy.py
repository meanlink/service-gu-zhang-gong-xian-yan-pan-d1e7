from sqlalchemy import String, Double, ForeignKey, Boolean, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class BudgetLedger(Base):
    """按批次内容指纹建立的隐私预算账本。

    指纹只取决于事件内容（排序、去标识后哈希），因此同内容批次即使改名、
    换账号上传或打乱行顺序，也共用同一账本，无法绕过累计预算。
    """
    __tablename__ = 'budget_ledgers'
    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    total_epsilon: Mapped[float] = mapped_column(Double, default=0.0)
    spent_epsilon: Mapped[float] = mapped_column(Double, default=0.0)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Double)
    locked_at: Mapped[float | None] = mapped_column(Double, nullable=True)


class DatasetGrant(Base):
    """负责人对外协账号的批次级授权。外协只能查询被圈定批次的加噪计数。"""
    __tablename__ = 'dataset_grants'
    __table_args__ = (UniqueConstraint('user_id', 'dataset_id', name='uq_grant_user_dataset'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    granted_by: Mapped[str] = mapped_column(String(150))
    created_at: Mapped[float] = mapped_column(Double)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class DpQuery(Base):
    """外协加噪计数查询记录：扣费依据、幂等键与发布结果都留痕。"""
    __tablename__ = 'dp_queries'
    # 幂等作用域为「内容账本 + query_key」：不同内容批次允许使用相同的 key
    __table_args__ = (UniqueConstraint('query_key', 'ledger_id', name='uq_dp_query_key_ledger'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    query_key: Mapped[str] = mapped_column(String(80), index=True)
    ledger_id: Mapped[int] = mapped_column(ForeignKey('budget_ledgers.id'))
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    requested_by: Mapped[str] = mapped_column(String(150))
    epsilon: Mapped[float] = mapped_column(Double)
    status: Mapped[str] = mapped_column(String(20), default='reserved')
    # 查询语义指纹：相同内容批次 + 相同口径 + 相同幂等键视为同一查询
    semantic_fingerprint: Mapped[str] = mapped_column(String(64))
    noisy_result: Mapped[dict] = mapped_column(Text, default='')
    created_at: Mapped[float] = mapped_column(Double)
    published_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    refunded_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    note: Mapped[str] = mapped_column(String(300), default='')
