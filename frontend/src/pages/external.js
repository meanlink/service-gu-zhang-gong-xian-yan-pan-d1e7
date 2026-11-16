import {privacy} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {heading} from '../components/common/shell.js';
import {esc,fmt,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';

const EPS_MIN=0.05, EPS_MAX=5.0;

export async function externalPage(){
 const [datasets,queries]=await Promise.all([privacy.myDatasets(),privacy.myQueries()]);
 workspace.extDatasets=datasets; workspace.extQueries=queries;
 workspace.extSelectedId=datasets[0]?.id??null;
 return heading('EXTERNAL / PRIVATE COUNT','外协加噪计数查询','仅可查询负责人圈定批次的各服务告警数。结果经拉普拉斯机制加噪，每个事件最多贡献一次；事件明细、原分析、归档与审计对你不可见。')
  +'<div class="dataset-grid">'
  +'<section class="panel"><div class="section-title"><h2>已授权批次</h2><span>'+datasets.length+' 批</span></div><div class="batch-list">'
  +(datasets.length?datasets.map(d=>'<button class="batch-item" data-pick="'+d.id+'"><strong>'+esc(d.name)+'</strong><span>'+d.rows+' 条 · 批次校验值 '+esc(d.checksum.slice(0,18))+'…</span><small>'+budgetHint(d.budget)+'</small></button>').join(''):'<p class="empty">负责人尚未为你圈定任何批次。</p>')
  +'</div><div class="method-sheet compact"><p class="eyebrow">PRIVACY MECHANISM</p><h3>拉普拉斯机制口径</h3><p style="font-size:11px;line-height:2">敏感度 Δ=1（单事件至多贡献一次）；噪声尺度 scale = 1/ε。单次 ε 可选 '+EPS_MIN+' ~ '+EPS_MAX+'，总 ε 由负责人锁定，同内容批次（改名/换账号/重排均不改变内容指纹）共用同一预算账本。</p><p style="font-size:11px;color:var(--muted)">相同 query_key 重试返回同一份结果，不重复扣费、不重新加噪。</p></div></section>'
  +'<section class="panel"><div class="section-title"><h2 id="dp-title">'+(datasets[0]?esc(datasets[0].name):'发起查询')+'</h2><span id="dp-budget">'+(datasets[0]?budgetText(datasets[0].budget):'')+'</span></div>'
  +(datasets.length?'<form id="dp-query-form"><label>查询批次<select name="dataset_id">'+datasets.map(d=>'<option value="'+d.id+'">'+esc(d.name)+'（剩余 ε '+(d.budget?fmt(d.budget.remaining_epsilon):'—')+'）</option>').join('')+'</select></label><label>本次隐私预算 ε（'+EPS_MIN+'~'+EPS_MAX+'）<input type="number" step="0.05" min="'+EPS_MIN+'" max="'+EPS_MAX+'" name="epsilon" value="1" required></label><label>查询幂等键 query_key（同键重试不重复扣费）<input name="query_key" minlength="4" maxlength="80" required placeholder="例如 weekly-alert-001"></label><button id="dp-submit" type="submit" class="primary" '+(locked(datasets[0].budget)?'':'disabled')+'>查询加噪告警数 ↗</button><p id="dp-lock-hint" class="hint" style="'+(locked(datasets[0].budget)?'display:none':'')+'">该批次预算账本尚未锁定，暂不能查询，请联系负责人。</p></form>':'<p class="empty">选择左侧已授权批次后即可发起查询。</p>')
  +'<div id="dp-result" class="dp-result"></div>'
  +'</section></div>'
  +'<section class="panel"><div class="section-title"><h2>我的查询与扣费依据</h2><span>'+queries.length+' 条</span></div>'+queryTable(queries)+'</section>';
}

function locked(budget){return !!(budget&&budget.locked);}
function budgetHint(budget){
 if(!budget)return '账本尚未初始化';
 return budget.locked?('预算已锁定 · 剩余 ε '+fmt(budget.remaining_epsilon)):'预算待负责人锁定';
}
function budgetText(budget){
 if(!budget)return '';
 return '总 ε '+fmt(budget.total_epsilon)+' · 已用 '+fmt(budget.spent_epsilon)+' · 剩余 '+fmt(budget.remaining_epsilon);
}

function queryTable(queries){
 if(!queries.length)return '<div class="empty">尚无查询记录。发起查询后，扣费依据与加噪结果会在此留痕。</div>';
 const cols=[{key:'query_key',label:'幂等键'},{key:'dataset_id',label:'批次'},{key:'epsilon',label:'本次 ε'},{key:'status',label:'状态'},{key:'counts',label:'加噪各服务告警数'},{key:'at',label:'时间'}];
 const rows=queries.map(q=>({query_key:q.query_key,dataset_id:q.dataset_id,epsilon:fmt(q.epsilon),status:statusText(q.status),counts:Object.entries(q.result.service_alert_counts||{}).map(([k,v])=>esc(k)+'='+v).join('，'),at:date(q.created_at)}));
 return '<div class="table-wrap"><table><thead><tr>'+cols.map(c=>'<th>'+esc(c.label)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+cols.map(c=>'<td>'+esc(r[c.key])+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
}

function statusText(s){return {reserved:'已预留',published:'已发布',refunded:'已退还'}[s]||s;}

export function bindExternal(refresh){
 const sync=(id)=>{
   const d=workspace.extDatasets.find(x=>x.id===Number(id));
   if(!d)return;
   workspace.extSelectedId=d.id;
   const title=document.querySelector('#dp-title');if(title)title.textContent=d.name;
   const budget=document.querySelector('#dp-budget');if(budget)budget.textContent=budgetText(d.budget);
   const btn=document.querySelector('#dp-submit');if(btn)btn.disabled=!locked(d.budget);
   const hint=document.querySelector('#dp-lock-hint');if(hint)hint.style.display=locked(d.budget)?'none':'';
 };
 document.querySelectorAll('[data-pick]').forEach(b=>b.onclick=()=>{sync(b.dataset.pick);const form=document.querySelector('#dp-query-form');if(form)form.querySelector('[name=dataset_id]').value=b.dataset.pick;});
 const form=document.querySelector('#dp-query-form');
 if(form){
   form.querySelector('[name=dataset_id]').addEventListener('change',e=>sync(e.target.value));
   submit(form,async f=>{
   const payload={dataset_id:Number(f.get('dataset_id')),epsilon:Number(f.get('epsilon')),query_key:f.get('query_key')};
   const res=await privacy.query(payload);
   const counts=res.result.service_alert_counts||{};
   document.querySelector('#dp-result').innerHTML='<div class="method-sheet compact"><p class="eyebrow">'+(res.reused?'IDEMPOTENT REUSE / 复用结果':'PUBLISHED / 已发布')+'</p><h3>各服务加噪告警数</h3><div class="metrics">'+Object.entries(counts).map(([k,v])=>'<div><span>'+esc(k)+'</span><strong>'+fmt(v)+'</strong><small>次</small></div>').join('')+'</div><p style="font-size:11px;margin-top:14px">机制 '+esc(res.result.mechanism)+' · 敏感度 '+fmt(res.result.sensitivity)+' · 噪声尺度 scale='+fmt(res.result.noise_scale)+' · 本次 ε='+fmt(res.epsilon)+(res.reused?' · 本次为同键重试，未重复扣费、未重新加噪':' · 扣费与发布共同生效')+'</p><p style="font-size:11px;color:var(--muted)">查询后剩余预算 ε='+fmt(res.remaining_epsilon)+'。返回值为加噪计数，非真实明细。</p></div>';
   notify(res.reused?'相同查询，返回原结果且未重复扣费':'加噪结果已发布，预算已扣 ε='+res.epsilon);
   await refresh();
   });
 }
}
