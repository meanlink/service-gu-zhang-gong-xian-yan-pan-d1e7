import {api} from './api/client.js';
import {session} from './stores/session.js';
import {workspace} from './stores/workspace.js';
import {shell} from './components/common/shell.js';
import {route} from './router/index.js';
import {login} from './pages/login.js';
import {overview} from './pages/overview.js';
import {dataPage,bindData} from './pages/datasets.js';
import {workbench,bindWorkbench} from './pages/workbench.js';
import {results,bindResults} from './pages/results.js';
import {reportPage,bindReports} from './pages/reports.js';
import {externalPage,bindExternal} from './pages/external.js';
import {collabPage,bindCollab} from './pages/collaboration.js';
import {esc} from './utils/dom.js';
async function render(){
 const app=document.querySelector('#app');
 try{
   if(!workspace.meta){workspace.meta=await api('/meta');document.title=workspace.meta.name;document.documentElement.style.setProperty('--accent',workspace.meta.accent||'oklch(48% 0.13 145)');document.body.dataset.style=workspace.meta.style||'ledger';}
   const {page,id}=route();
   if(!session.token||page==='login'){login();return;}
   // 外协角色：单一差分隐私查询面，任何内部业务页都被收敛到该面
   if(session.user.role==='external'){
     if(page!=='external'){location.hash='#/external';return;}
     const content=await externalPage();
     app.innerHTML=shell('external',content,{external:true});
     bindExternal(render);
     document.querySelector('#logout').onclick=()=>{session.clear();location.hash='#/login';render();};
     return;
   }
   const pages={overview,datasets:dataPage,workbench,results:()=>results(id),reports:reportPage,collaboration:collabPage};
   // 外协治理页仅负责人可进入，其他角色直接收敛到总览
   if(page==='collaboration'&&session.user.role!=='admin'){location.hash='#/overview';return;}
   const content=await (pages[page]||overview)();app.innerHTML=shell(page,content);
   document.querySelector('#logout').onclick=()=>{session.clear();location.hash='#/login';render();};
   if(page==='datasets')bindData(render);if(page==='workbench')bindWorkbench();if(page==='results')bindResults(render);if(page==='reports')bindReports(render);if(page==='collaboration')bindCollab(render);
 }catch(e){app.innerHTML='<div class="fatal"><h1>暂时无法打开工作室</h1><p>'+esc(e.message)+'</p><button onclick="location.reload()">重新连接</button></div>';}
}
addEventListener('hashchange',render);render();
