import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const privacy={
  // 负责人面
  ledgers:()=>api('/privacy/ledgers'),
  lockBudget:(datasetId,total_epsilon)=>api('/privacy/datasets/'+datasetId+'/lock-budget',{method:'POST',body:JSON.stringify({total_epsilon})}),
  grants:()=>api('/privacy/grants'),
  createGrant:(user_email,dataset_id)=>api('/privacy/grants',{method:'POST',body:JSON.stringify({user_email,dataset_id})}),
  revokeGrant:id=>api('/privacy/grants/'+id+'/revoke',{method:'POST'}),
  allQueries:()=>api('/privacy/queries'),
  // 外协面
  myDatasets:()=>api('/privacy/my/datasets'),
  myLedger:datasetId=>api('/privacy/my/ledger/'+datasetId),
  query:data=>api('/privacy/queries',{method:'POST',body:JSON.stringify(data)}),
  myQueries:()=>api('/privacy/my/queries'),
};
