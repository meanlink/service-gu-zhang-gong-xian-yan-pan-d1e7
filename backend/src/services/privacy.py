"""外协差分隐私服务。

口径与不变量：
- 外协仅能查询负责人圈定批次的「各服务告警数」加噪计数，接触不到事件明细、
  原分析、归档下载与审计日志（路由层另做拒绝）。
- 计数为事件级统计，单条事件至多贡献 1，故敏感度 Δ=1，采用 Laplace 机制，
  噪声 scale = 1/epsilon。
- 预算账本以批次「内容指纹」为主键：改名、换账号上传、行重排都得到同一指纹，
  共用同一账本，无法绕过累计预算。
- 相同查询（客户端提供 query_key）重试直接返回已发布结果，不重复扣费、不重新加噪。
- 并发查询通过 SELECT ... FOR UPDATE 串行化账本扣费，余额不足直接拒绝，绝不透支。
- 扣费（reserved）与结果发布（published）分开：仅发布成功才真正占用预算；
  中断后按 query_key 恢复原结果；预留后未发布的记录可退还预算。
"""
import hashlib
import json
import math
import os
import time

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.models import BudgetLedger, DatasetGrant, DpQuery, Dataset

# 事件级计数：一个事件在单个服务计数中最多贡献 1
SENSITIVITY = 1.0
# 单次可选隐私预算范围（负责人锁定总预算后，外协在范围内自选 epsilon）
EPSILON_MIN = 0.05
EPSILON_MAX = 5.0
# 预留后超过该秒数仍未发布，视为中断，可安全退还
RESERVE_TTL_SECONDS = 120


def content_fingerprint(records):
    """对事件内容做规范化哈希。

    仅取业务字段并按 event_id 排序后序列化，行顺序变化不影响结果；
    event_id 去重校验在调用前完成。改名、换上传账号均不参与哈希。
    """
    canonical = sorted(
        (
            {
                'event_id': str(r['event_id']).strip(),
                'service': str(r['service']).strip(),
                'occurred_min': float(r['occurred_min']),
                'severity': int(r['severity']),
            }
            for r in records
        ),
        key=lambda r: r['event_id'],
    )
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def service_counts(records):
    """真实各服务事件数（仅在服务端内部使用，绝不直接返回外协）。"""
    counts = {}
    seen = set()
    for r in records:
        event_id = str(r['event_id']).strip()
        if event_id in seen:
            raise HTTPException(422, '批次内 event_id 重复，请先去重')
        seen.add(event_id)
        service = str(r['service']).strip()
        counts[service] = counts.get(service, 0) + 1
    return dict(sorted(counts.items()))


def semantic_fingerprint(fp, query_key):
    """查询语义指纹：内容指纹 + 幂等键。同一批次同一 query_key 即同一查询。"""
    return hashlib.sha256(f'{fp}|{query_key}'.encode('utf-8')).hexdigest()


def _laplace_noise(scale):
    # 使用系统熵的 Laplace 抽样：u~U(-0.5,0.5) -> -scale*sgn(u)*ln(1-2|u|)
    u = os.urandom(8)
    uniform = (int.from_bytes(u, 'big') / (1 << 64)) - 0.5
    if uniform == 0:
        uniform = 1e-12
    return -scale * math.copysign(math.log(1 - 2 * abs(uniform)), uniform)


def add_laplace_counts(counts, epsilon):
    """对每个服务计数独立加噪并四舍五入为非负整数。"""
    scale = SENSITIVITY / epsilon
    noisy = {}
    for service, true_count in counts.items():
        value = true_count + _laplace_noise(scale)
        noisy[service] = max(0, int(round(value)))
    return noisy, scale


def get_or_create_ledger(db, fp):
    ledger = db.scalar(select(BudgetLedger).where(BudgetLedger.fingerprint == fp))
    if ledger is None:
        ledger = BudgetLedger(
            fingerprint=fp, total_epsilon=0.0, spent_epsilon=0.0,
            locked=False, created_at=time.time(),
        )
        db.add(ledger)
        db.flush()
    return ledger


def require_grant(db, user, dataset):
    grant = db.scalar(
        select(DatasetGrant).where(
            DatasetGrant.user_id == user.id,
            DatasetGrant.dataset_id == dataset.id,
            DatasetGrant.revoked == False,  # noqa: E712
        )
    )
    if grant is None:
        raise HTTPException(403, '该批次未对您授权，请联系业务负责人圈定批次')
    return grant


def validate_epsilon(epsilon):
    try:
        epsilon = float(epsilon)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, '隐私预算 epsilon 必须是数值') from exc
    if not math.isfinite(epsilon) or not (EPSILON_MIN <= epsilon <= EPSILON_MAX):
        raise HTTPException(422, f'单次隐私预算需在 {EPSILON_MIN} ~ {EPSILON_MAX} 之间')
    return epsilon


def reserve_query(db, user, dataset_id, epsilon, query_key):
    """第一阶段：校验授权与预算，锁定账本行后预留扣费并生成加噪结果。

    同一 query_key 的并发请求：已存在记录则复用（幂等），否则依赖唯一约束
    让落败方回滚后重试读取，保证同一查询只扣一次费、只生成一次噪声。
    """
    epsilon = validate_epsilon(epsilon)
    if not query_key or len(str(query_key).strip()) < 4:
        raise HTTPException(422, 'query_key 至少 4 个字符，用于查询重试的幂等标识')
    query_key = str(query_key).strip()[:80]

    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(404, '数据批次不存在')
    require_grant(db, user, dataset)

    fp = content_fingerprint(dataset.records)

    # 先定位内容账本（不锁定），用于把幂等作用域限定在同一内容账本内
    scoped_ledger = db.scalar(select(BudgetLedger).where(BudgetLedger.fingerprint == fp))

    # 幂等快查：同一内容账本下已存在同 query_key 的记录，直接恢复（不重复扣费/加噪）
    if scoped_ledger is not None:
        existing = db.scalar(
            select(DpQuery).where(
                DpQuery.query_key == query_key,
                DpQuery.ledger_id == scoped_ledger.id,
            )
        )
        if existing is not None:
            return _reuse_existing(db, existing, fp, dataset)

    # 锁定账本行：并发查询在此串行，余额检查与扣费原子完成，杜绝透支
    ledger = db.scalar(
        select(BudgetLedger).where(BudgetLedger.fingerprint == fp).with_for_update()
    )
    if ledger is None:
        raise HTTPException(409, '该内容批次的预算账本尚未由负责人初始化')
    if not ledger.locked:
        raise HTTPException(409, '总预算尚未由负责人锁定，暂不能查询')
    if ledger.total_epsilon - ledger.spent_epsilon < epsilon - 1e-12:
        raise HTTPException(
            402,
            f'预算不足：账本剩余 {ledger.total_epsilon - ledger.spent_epsilon:.4f}，'
            f'本次需要 {epsilon:.4f}',
        )

    true_counts = service_counts(dataset.records)
    noisy_counts, scale = add_laplace_counts(true_counts, epsilon)
    result = {
        'dataset_id': dataset.id,
        'service_alert_counts': noisy_counts,
        'mechanism': 'Laplace',
        'sensitivity': SENSITIVITY,
        'noise_scale': round(scale, 6),
        'epsilon': epsilon,
        'note': '计数为拉普拉斯加噪后的非负整数，每个事件最多贡献一次，非真实明细。',
    }
    query = DpQuery(
        query_key=query_key,
        ledger_id=ledger.id,
        dataset_id=dataset.id,
        requested_by=user.email,
        epsilon=epsilon,
        status='reserved',
        semantic_fingerprint=semantic_fingerprint(fp, query_key),
        noisy_result=json.dumps(result, ensure_ascii=False, allow_nan=False),
        created_at=time.time(),
        note='已预留预算，待发布',
    )
    db.add(query)
    # 预留即计入已用额度；若最终未发布会在 refund 中冲回
    ledger.spent_epsilon += epsilon
    # SAVEPOINT：并发同键插入撞唯一约束时仅回滚保存点，不中止外层事务
    # （Postgres 中直接 flush 失败会令整个事务进入 aborted，必须回滚后才能继续）
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        # 回滚到保存点，撤销本次预留的扣费与待插入行，再走幂等复用
        db.expire_all()
        raced = db.scalar(select(DpQuery).where(
            DpQuery.query_key == query_key,
            DpQuery.ledger_id == ledger.id,
        ))
        if raced is not None:
            return _reuse_existing(db, raced, fp, dataset)
        raise
    return query, ledger, result


def _reuse_existing(db, existing, fp, dataset):
    """恢复同 query_key 的历史查询：发布过返回原结果，未发布沿用原预留。"""
    if existing.semantic_fingerprint != semantic_fingerprint(fp, existing.query_key):
        raise HTTPException(409, 'query_key 已用于其他内容批次的查询，请更换标识')
    if existing.dataset_id != dataset.id:
        # 同内容的另一个批次（改名/换账号）：账本相同，结果语义一致，允许复用
        pass
    ledger = db.get(BudgetLedger, existing.ledger_id)
    result = json.loads(existing.noisy_result) if existing.noisy_result else {}
    return existing, ledger, result


def publish_query(db, query):
    """第二阶段：结果对外发布。预留与发布在同一请求事务内共同提交生效。"""
    if query.status == 'published':
        return query
    if query.status == 'refunded':
        raise HTTPException(409, '该查询已中断并退还预算，请使用新的 query_key 重新查询')
    query.status = 'published'
    query.published_at = time.time()
    query.note = '预算扣费与结果发布共同生效'
    db.flush()
    return query


def refund_reserved(db, query, reason='中断未发布，退还预留预算'):
    """预留后未成功发布：冲回预算，记录留痕。"""
    if query.status != 'reserved':
        return query
    ledger = db.scalar(
        select(BudgetLedger).where(BudgetLedger.id == query.ledger_id).with_for_update()
    )
    ledger.spent_epsilon = max(0.0, ledger.spent_epsilon - query.epsilon)
    query.status = 'refunded'
    query.refunded_at = time.time()
    query.note = reason
    db.flush()
    return query


def sweep_stale_reservations(db):
    """恢复机制：清理超时仍未发布的预留，退还预算（worker 周期调用）。"""
    cutoff = time.time() - RESERVE_TTL_SECONDS
    stale = list(db.scalars(
        select(DpQuery).where(DpQuery.status == 'reserved', DpQuery.created_at <= cutoff)
    ))
    for query in stale:
        refund_reserved(db, query, reason='预留超时未发布，自动退还')
    return len(stale)


def ledger_view(ledger):
    return {
        'ledger_id': ledger.id,
        'fingerprint': ledger.fingerprint,
        'total_epsilon': ledger.total_epsilon,
        'spent_epsilon': round(ledger.spent_epsilon, 6),
        'remaining_epsilon': round(ledger.total_epsilon - ledger.spent_epsilon, 6),
        'locked': ledger.locked,
        'locked_at': ledger.locked_at,
        'created_at': ledger.created_at,
    }


def query_view(query):
    return {
        'id': query.id,
        'query_key': query.query_key,
        'ledger_id': query.ledger_id,
        'dataset_id': query.dataset_id,
        'requested_by': query.requested_by,
        'epsilon': query.epsilon,
        'status': query.status,
        'result': json.loads(query.noisy_result) if query.noisy_result else {},
        'created_at': query.created_at,
        'published_at': query.published_at,
        'refunded_at': query.refunded_at,
        'note': query.note,
    }
