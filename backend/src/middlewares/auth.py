from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from src.config.database import get_db
from src.models import User
from src.utils.security import decode_token
bearer = HTTPBearer(auto_error=False)
def current_user(token: HTTPAuthorizationCredentials | None = Depends(bearer), db=Depends(get_db)):
    try:
        user = db.get(User, decode_token(token.credentials))
        if user is None: raise ValueError('missing user')
        return user
    except Exception:
        raise HTTPException(401, '登录已过期，请重新登录')
def can_write(user=Depends(current_user)):
    if user.role not in ('admin','analyst'): raise HTTPException(403, '观察员只有读取权限')
    return user
def admin_only(user=Depends(current_user)):
    if user.role != 'admin': raise HTTPException(403, '需要业务负责人批准')
    return user
def external_only(user=Depends(current_user)):
    if user.role != 'external': raise HTTPException(403, '该接口仅对外协角色开放')
    return user
def deny_external(user=Depends(current_user)):
    """外协角色只能访问差分隐私查询面，业务明细/原分析/归档/审计一律拒绝。"""
    if user.role == 'external':
        raise HTTPException(403, '外协角色仅可查询授权批次的加噪计数，无权访问该资源')
    return user
