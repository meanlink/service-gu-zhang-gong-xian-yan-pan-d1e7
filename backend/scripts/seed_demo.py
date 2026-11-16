import time, json
from sqlalchemy import select, func
from src.config.database import Session
from migrations.initial import migrate
from src.models import User, Dataset, Job, Report, Delivery, Audit, BudgetLedger, DatasetGrant
from src.services.business import metadata, seed_records, analyze
from src.services.reports import deliver
from src.services.privacy import content_fingerprint
from src.utils.security import hash_password
from src.utils.serialization import checksum
def seed():
    migrate()
    with Session() as db:
        for role,name in [('admin','林知 · 业务负责人'),('analyst','陈舟 · 分析员'),('viewer','周禾 · 观察员'),('external','秦越 · 外协协作方')]:
            email=role+'@demo.local'
            if not db.scalar(select(User).where(User.email==email)):
                db.add(User(email=email,name=name,role=role,password=hash_password('Demo123!')))
        db.flush()
        m=metadata()
        d=db.scalar(select(Dataset).where(Dataset.name==m['dataset_name']))
        if not d:
            rows=seed_records()
            d=Dataset(name=m['dataset_name'],source=m['short']+'-202611.csv',records=rows,checksum=checksum(rows),created_at=time.time())
            db.add(d); db.flush()
        if not db.scalar(select(Job).where(Job.name=='基线复核 · '+m['name'])):
            params={p['key']:p['default'] for p in m.get('parameters',[])}
            result=analyze(d.records,params)
            json.dumps(result,ensure_ascii=False,allow_nan=False)
            admin=db.scalar(select(User).where(User.role=='admin'))
            j=Job(name='基线复核 · '+m['name'],dataset_id=d.id,params=params,status='completed',result=result,created_by=admin.id,created_at=time.time()-3600,finished_at=time.time()-3595,approved=True)
            db.add(j);db.flush()
            r=Report(name='每日业务复核简报',job_id=j.id,destination='业务复核组 · 本地收件箱',interval_seconds=86400,next_run=time.time()+86400,enabled=True)
            db.add(r);db.flush();deliver(db,r)
            db.add(Audit(actor='seed',action='demo.baseline',detail={'dataset':d.id},at=time.time()))
        # 外协演示：按内容指纹建立并锁定总预算账本，圈定基线批次给外协账号
        fp=content_fingerprint(d.records)
        ledger=db.scalar(select(BudgetLedger).where(BudgetLedger.fingerprint==fp))
        if ledger is None:
            ledger=BudgetLedger(fingerprint=fp,total_epsilon=10.0,spent_epsilon=0.0,locked=True,created_at=time.time(),locked_at=time.time())
            db.add(ledger);db.flush()
            db.add(Audit(actor='seed',action='privacy.budget.lock',detail={'ledger_id':ledger.id,'total_epsilon':10.0},at=time.time()))
        ext=db.scalar(select(User).where(User.email=='external@demo.local'))
        if ext and not db.scalar(select(DatasetGrant).where(DatasetGrant.user_id==ext.id,DatasetGrant.dataset_id==d.id)):
            db.add(DatasetGrant(user_id=ext.id,dataset_id=d.id,granted_by='seed',created_at=time.time()))
            db.add(Audit(actor='seed',action='privacy.grant.create',detail={'user':ext.email,'dataset_id':d.id},at=time.time()))
        db.commit()
        counts={model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in [User,Dataset,Job,Report,Delivery,Audit,BudgetLedger,DatasetGrant]}
        print(json.dumps(counts,ensure_ascii=False))
        return counts
if __name__=='__main__':seed()
