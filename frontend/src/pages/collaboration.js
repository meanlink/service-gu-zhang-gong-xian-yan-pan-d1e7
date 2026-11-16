import {privacy,datasets} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,fmt,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';

export async function collabPage(){
 const [allDatasets,ledgers,grants,queries]=await Promise.all([
   datasets.list(),privacy.ledgers(),privacy.grants(),privacy.allQueries()]);
 workspace.ledgers=ledgers; workspace.grants=grants; workspace.collabQueries=queries;
 const isAdmin=session.user.role==='admin';
 return heading('06 / PRIVACY GOVERNANCE','外协协作与隐私预算','按批次内容锁定总隐私预算，并把批次圈定给外协账号。外协只能取得拉普拉斯加噪计数；同内容批次（改名、换账号、行重排指纹不变）共用同一账本，无法绕过累计预算。')
 +'<div class="report-grid">'
 // 左列：锁预算 + 授权
 +'<section><section class="panel"><div class="section-title"><h2>锁定批次总预算</h2><span>按内容指纹</span></div>'
 +'<form id="lock-form"><label>选择批次<select name="dataset_id">'+allDatasets.map(d=>'<option value="'+d.id+'">'+esc(d.name)+' · '+d.rows+' 条</option>').join('')+'</select></label><label>总隐私预算 ε（锁定后不可调整）<input type="number" step="0.5" min="0.05" name="total_epsilon" value="10" required></label><button type="submit" class="primary" '+(isAdmin?'':'disabled')+'>锁定总预算 ↗</button><p class="hint">锁定后外协才能查询；同内容批次自动共用该账本。需要新口径请建立新内容批次。</p></form></section>'
 +'<section class="panel"><div class="section-title"><h2>圈定批次给外协</h2></div>'
 +'<form id="grant-form"><label>外协账号邮箱<input name="user_email" required placeholder="external@demo.local"></label><label>授权批次<select name="dataset_id">'+allDatasets.map(d=>'<option value="'+d.id+'">'+esc(d.name)+'</option>').join('')+'</select></label><button type="submit" class="primary" '+(isAdmin?'':'disabled')+'>授权该批次 ↗</button></form></section></section>'
 // 右列：账本、授权、扣费依据
 +'<section><section class="panel"><div class="section-title"><h2>预算账本</h2><span>'+ledgers.length+' 个内容账本</span></div>'
 +(ledgers.length?'<div class="table-wrap"><table><thead><tr><th>内容指纹</th><th>关联批次</th><th>总 ε</th><th>已用</th><th>剩余</th><th>状态</th></tr></thead><tbody>'+ledgers.map(l=>'<tr><td>'+esc(l.fingerprint.slice(0,16))+'…</td><td>'+l.datasets.map(d=>esc(d.name)).join('、')+'</td><td>'+fmt(l.total_epsilon)+'</td><td>'+fmt(l.spent_epsilon)+'</td><td><strong>'+fmt(l.remaining_epsilon)+'</strong></td><td>'+(l.locked?'已锁定':'待锁定')+'</td></tr>').join('')+'</tbody></table></div>':'<div class="empty">尚无账本，锁定批次预算后生成。</div>')+'</section>'
 +'<section class="panel"><div class="section-title"><h2>批次授权</h2><span>'+grants.length+' 条</span></div>'
 +(grants.length?'<div class="table-wrap"><table><thead><tr><th>外协账号</th><th>批次</th><th>授权人</th><th>时间</th><th>状态</th><th></th></tr></thead><tbody>'+grants.map(g=>'<tr><td>'+esc(g.user_email)+'</td><td>'+esc(g.dataset_name)+'</td><td>'+esc(g.granted_by)+'</td><td>'+date(g.created_at)+'</td><td>'+(g.revoked?'已撤销':'生效中')+'</td><td>'+(isAdmin&&!g.revoked?'<button class="text-button" data-revoke="'+g.id+'">撤销</button>':'')+'</td></tr>').join('')+'</tbody></table></div>':'<div class="empty">尚未授权外协账号。</div>')+'</section></section>'
 +'</div>'
 +'<section class="panel"><div class="section-title"><h2>外协查询扣费依据</h2><span>'+queries.length+' 条留痕</span></div>'+queryEvidence(queries)+'</section>';
}

function queryEvidence(queries){
 if(!queries.length)return '<div class="empty">外协发起查询后，这里记录每次扣费的 ε、幂等键、状态与加噪结果，供负责人复查。</div>';
 const cols=[{key:'at',label:'时间'},{key:'who',label:'外协账号'},{key:'key',label:'幂等键'},{key:'ds',label:'批次'},{key:'eps',label:'扣 ε'},{key:'status',label:'状态'},{key:'counts',label:'加噪计数（不含明细）'}];
 const rows=queries.map(q=>({at:date(q.created_at),who:q.requested_by,key:q.query_key,ds:q.dataset_id,eps:fmt(q.epsilon),status:{reserved:'已预留',published:'已发布',refunded:'已退还'}[q.status]||q.status,counts:Object.entries(q.result.service_alert_counts||{}).map(([k,v])=>esc(k)+'='+v).join('，')}));
 return '<div class="table-wrap"><table><thead><tr>'+cols.map(c=>'<th>'+esc(c.label)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+cols.map(c=>'<td>'+esc(r[c.key])+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
}

export function bindCollab(refresh){
 if(session.user.role!=='admin')return;
 submit(document.querySelector('#lock-form'),async f=>{
   await privacy.lockBudget(Number(f.get('dataset_id')),Number(f.get('total_epsilon')));
   notify('总预算已按内容锁定，同内容批次共用该账本');await refresh();
 });
 submit(document.querySelector('#grant-form'),async f=>{
   await privacy.createGrant(f.get('user_email').trim(),Number(f.get('dataset_id')));
   notify('已为外协账号圈定该批次');await refresh();
 });
 document.querySelectorAll('[data-revoke]').forEach(b=>b.onclick=async()=>{
   try{await privacy.revokeGrant(Number(b.dataset.revoke));notify('授权已撤销');await refresh();}
   catch(e){notify(e.message,true);}
 });
}
