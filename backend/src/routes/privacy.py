"""外协差分隐私路由。

负责人面（admin_only）：批次授权/撤销、按内容锁定总预算、查看账本与扣费依据。
外协面（external_only）：仅查询授权批次的加噪计数、查看自己可用的剩余预算。
明细、原分析、归档下载、审计日志在各自路由通过 deny_external 统一拒绝。
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from src.config.database import get_db
from src.models import BudgetLedger, DatasetGrant, DpQuery, Dataset, User
from src.middlewares.auth import admin_only, external_only
from src.schemas.privacy import LockBudgetInput, GrantInput, DpQueryInput
from src.services import privacy
from src.services.audit import record
from src.utils.serialization import dataset_dict

router = APIRouter(prefix='/privacy')


# ----------------------------- 负责人：预算账本 -----------------------------

@router.get('/ledgers')
def list_ledgers(db=Depends(get_db), u=Depends(admin_only)):
    """账本与数据集关联视图：同内容指纹的批次共用一个账本。"""
    ledgers = db.scalars(select(BudgetLedger).order_by(BudgetLedger.id)).all()
    datasets = db.scalars(select(Dataset)).all()
    fp_to_datasets = {}
    for d in datasets:
        fp_to_datasets.setdefault(privacy.content_fingerprint(d.records), []).append(d)
    out = []
    for ledger in ledgers:
        view = privacy.ledger_view(ledger)
        view['datasets'] = [
            {'id': d.id, 'name': d.name, 'rows': len(d.records)}
            for d in fp_to_datasets.get(ledger.fingerprint, [])
        ]
        out.append(view)
    return out


@router.post('/datasets/{dataset_id}/lock-budget')
def lock_budget(dataset_id: int, data: LockBudgetInput, db=Depends(get_db), u=Depends(admin_only)):
    """按批次内容锁定总预算；同内容批次共用账本，锁定即对全部同名内容生效。"""
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(404, '数据批次不存在')
    fp = privacy.content_fingerprint(dataset.records)
    ledger = db.scalar(
        select(BudgetLedger).where(BudgetLedger.fingerprint == fp).with_for_update()
    )
    if ledger is None:
        ledger = privacy.get_or_create_ledger(db, fp)
    if ledger.locked:
        raise HTTPException(409, '总预算已锁定，不能调整；如需新口径请建立新内容批次')
    ledger.total_epsilon = float(data.total_epsilon)
    ledger.locked = True
    ledger.locked_at = time.time()
    record(db, u.email, 'privacy.budget.lock', {
        'ledger_id': ledger.id, 'fingerprint': fp[:16], 'total_epsilon': ledger.total_epsilon,
        'dataset_id': dataset_id,
    })
    db.commit()
    return privacy.ledger_view(ledger)


# ----------------------------- 负责人：批次授权 -----------------------------

@router.get('/grants')
def list_grants(db=Depends(get_db), u=Depends(admin_only)):
    rows = db.scalars(select(DatasetGrant).order_by(DatasetGrant.id.desc())).all()
    out = []
    for g in rows:
        user = db.get(User, g.user_id)
        dataset = db.get(Dataset, g.dataset_id)
        out.append({
            'id': g.id, 'user_id': g.user_id,
            'user_email': user.email if user else '',
            'user_name': user.name if user else '',
            'dataset_id': g.dataset_id,
            'dataset_name': dataset.name if dataset else '',
            'granted_by': g.granted_by, 'created_at': g.created_at, 'revoked': g.revoked,
        })
    return out


@router.post('/grants', status_code=201)
def create_grant(data: GrantInput, db=Depends(get_db), u=Depends(admin_only)):
    target = db.scalar(select(User).where(User.email == data.user_email))
    if target is None:
        raise HTTPException(404, '账号不存在')
    if target.role != 'external':
        raise HTTPException(422, '仅可对外协(external)账号授权批次')
    dataset = db.get(Dataset, data.dataset_id)
    if dataset is None:
        raise HTTPException(404, '数据批次不存在')
    existing = db.scalar(select(DatasetGrant).where(
        DatasetGrant.user_id == target.id, DatasetGrant.dataset_id == dataset.id))
    if existing is not None:
        if existing.revoked:
            existing.revoked = False
            existing.granted_by = u.email
            existing.created_at = time.time()
            grant = existing
        else:
            raise HTTPException(409, '该授权已存在，无需重复圈定')
    else:
        grant = DatasetGrant(
            user_id=target.id, dataset_id=dataset.id,
            granted_by=u.email, created_at=time.time(),
        )
        db.add(grant)
    record(db, u.email, 'privacy.grant.create', {
        'user': target.email, 'dataset_id': dataset.id,
    })
    db.commit()
    return {'id': grant.id, 'user_email': target.email, 'dataset_id': dataset.id, 'revoked': False}


@router.post('/grants/{grant_id}/revoke')
def revoke_grant(grant_id: int, db=Depends(get_db), u=Depends(admin_only)):
    grant = db.get(DatasetGrant, grant_id)
    if grant is None:
        raise HTTPException(404, '授权不存在')
    grant.revoked = True
    record(db, u.email, 'privacy.grant.revoke', {'id': grant_id})
    db.commit()
    return {'id': grant_id, 'revoked': True}


# ----------------------------- 外协：授权批次与预算 -----------------------------

@router.get('/my/datasets')
def my_datasets(db=Depends(get_db), u=Depends(external_only)):
    """外协可见的被圈定批次（只返回元信息，不含任何事件记录）。"""
    grants = db.scalars(select(DatasetGrant).where(
        DatasetGrant.user_id == u.id, DatasetGrant.revoked == False  # noqa: E712
    )).all()
    out = []
    for g in grants:
        dataset = db.get(Dataset, g.dataset_id)
        if dataset is None:
            continue
        fp = privacy.content_fingerprint(dataset.records)
        ledger = db.scalar(select(BudgetLedger).where(BudgetLedger.fingerprint == fp))
        item = {k: dataset_dict(dataset)[k] for k in ('id', 'name', 'source', 'rows', 'checksum')}
        item['budget'] = privacy.ledger_view(ledger) if ledger else None
        out.append(item)
    return out


@router.get('/my/ledger/{dataset_id}')
def my_ledger(dataset_id: int, db=Depends(get_db), u=Depends(external_only)):
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(404, '数据批次不存在')
    privacy.require_grant(db, u, dataset)
    fp = privacy.content_fingerprint(dataset.records)
    ledger = db.scalar(select(BudgetLedger).where(BudgetLedger.fingerprint == fp))
    if ledger is None:
        raise HTTPException(404, '该批次预算账本尚未初始化')
    return privacy.ledger_view(ledger)


# ----------------------------- 外协：加噪计数查询 -----------------------------

@router.post('/queries', status_code=201)
def run_query(data: DpQueryInput, db=Depends(get_db), u=Depends(external_only)):
    """两阶段查询：预留扣费与结果发布在同一事务内共同生效。

    相同 query_key 重试直接返回历史结果（不重复扣费、不重新加噪）；
    并发由账本行锁串行化，余额不足返回 402，绝不透支。
    """
    query, ledger, result = privacy.reserve_query(
        db, u, data.dataset_id, data.epsilon, data.query_key
    )
    if query.status == 'reserved':
        privacy.publish_query(db, query)
        record(db, u.email, 'privacy.query.publish', {
            'query_id': query.id, 'query_key': query.query_key,
            'ledger_id': ledger.id, 'epsilon': query.epsilon,
            'remaining': round(ledger.total_epsilon - ledger.spent_epsilon, 6),
        })
        reused = False
    else:
        # 幂等重试：原结果原样返回，仅留访问痕迹，不扣费、不加噪
        record(db, u.email, 'privacy.query.reuse', {
            'query_id': query.id, 'query_key': query.query_key,
        })
        reused = True
    db.commit()
    view = privacy.query_view(query)
    view['reused'] = reused
    view['remaining_epsilon'] = round(ledger.total_epsilon - ledger.spent_epsilon, 6)
    return view


@router.get('/my/queries')
def my_queries(db=Depends(get_db), u=Depends(external_only)):
    rows = db.scalars(
        select(DpQuery).where(DpQuery.requested_by == u.email).order_by(DpQuery.id.desc()).limit(100)
    )
    return [privacy.query_view(q) for q in rows]


@router.get('/queries')
def all_queries(db=Depends(get_db), u=Depends(admin_only)):
    """负责人查看全部扣费依据与查询留痕（外协无权访问审计与本接口）。"""
    rows = db.scalars(select(DpQuery).order_by(DpQuery.id.desc()).limit(200))
    return [privacy.query_view(q) for q in rows]
