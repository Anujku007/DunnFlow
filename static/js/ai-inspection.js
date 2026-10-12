(function(){
 "use strict";
 const $=id=>document.getElementById(id);
 const esc=value=>String(value??"—").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
 const obj=v=>v&&typeof v==="object"&&!Array.isArray(v)?v:{};
 const arr=v=>Array.isArray(v)?v:[];
 const first=(...values)=>values.find(v=>v!==undefined&&v!==null&&v!=="");
 const money=(amount,currency="INR")=>{const n=Number(amount);if(!Number.isFinite(n))return "—";try{return new Intl.NumberFormat("en-IN",{style:"currency",currency,maximumFractionDigits:2}).format(n/100);}catch{return `₹${(n/100).toFixed(2)}`;}};
 const date=v=>{if(!v)return "Not recorded";const d=new Date(v);return Number.isNaN(d.getTime())?esc(v):d.toLocaleString("en-IN",{dateStyle:"medium",timeStyle:"short"});};
 const setHTML=(id,html)=>{const e=$(id);if(e)e.innerHTML=html;};
 const empty=(label="No records returned by the current API.")=>`<div class="dfr-empty">${esc(label)}</div>`;
  const humanError=value=>{
    const s=String(value??"").trim();
    if(!s)return "No additional explanation was returned.";
    if(/RESOURCE_EXHAUSTED|quota exceeded|429|rate.limit/i.test(s))return "AI advice is temporarily unavailable because the provider quota or rate limit was reached. The deterministic policy remains authoritative.";
    if(/503|UNAVAILABLE|high demand/i.test(s))return "AI advice is temporarily unavailable because the provider is experiencing high demand. The deterministic policy remains authoritative.";
    if(/API.?key|authentication|permission denied|401|403/i.test(s))return "AI advice is unavailable because the provider rejected the request. Check the AI provider configuration.";
    if(s.length>260)return s.slice(0,257)+"…";
    return s;
  };
  const displayAction=value=>String(value??"").trim()||"AI unavailable";
  const evidenceLabel=value=>({
    historically_favorable:"Favorable history",
    historically_unfavorable:"Unfavorable history",
    recently_favorable:"Recently favorable",
    recently_unfavorable:"Recently unfavorable",
    aligned:"Aligned",
    mixed:"Mixed evidence",
    insufficient_history:"Insufficient history",
    unavailable:"Unavailable",
    high:"High evidence quality",
    moderate:"Moderate evidence quality",
    limited:"Limited evidence quality",
    strong:"Strong evidence quality"
  }[String(value??"").toLowerCase()]||String(value??"Not available").replaceAll("_"," "));
 function openModal(){const m=$("decisionIntelligenceModal");if(!m)return;m.classList.add("is-open");m.setAttribute("aria-hidden","false");document.body.classList.add("decision-modal-open");document.body.classList.remove("dfr-printing");}
 function closeModal(){const m=$("decisionIntelligenceModal");if(!m)return;m.classList.remove("is-open");m.setAttribute("aria-hidden","true");document.body.classList.remove("decision-modal-open","dfr-printing");const b=$("inspectDecisionBtn");if(b)b.focus();}
 function statusBadge(value){const s=String(value??"unknown").toLowerCase();const cls=["success","recovered","paid","captured","aligned","agreement"].some(x=>s.includes(x))?"":(["disagree","blocked","failed","exhausted","conflict"].some(x=>s.includes(x))?" warn":" neutral");return `<span class="dfr-result${cls}">${esc(value??"Unavailable")}</span>`;}
 function render(data,audit){const invoice=obj(data.invoice),diagnosis=obj(data.diagnosis),decision=obj(data.decision),recon=obj(data.ai_reconciliation),hist=obj(data.historical_context),ai=obj(first(recon.ai_recommendation,recon.recommendation,{})),learning=obj(first(ai.learning_influence,recon.learning_influence,{})),signal=obj(hist.learning_signal),summary=obj(hist.historical_evidence_summary),consistency=obj(hist.historical_evidence_consistency),attempts=arr(first(data.payment_attempts,audit.payment_attempts,[])),events=arr(first(audit.events,audit.timeline,[]));
 const invoiceId=first(invoice.invoice_id, data.invoice_id, window.DunnFlowState?.invoiceId,"Selected invoice"),subscription=first(invoice.subscription_id,"—"),amount=first(invoice.amount),currency=first(invoice.currency,"INR"),category=first(diagnosis.category,diagnosis.failure_category,invoice.failure_category,"Unknown"),aiAction=first(recon.ai_action,ai.recommended_action,"AI unavailable"),policyAction=first(recon.deterministic_action,decision.action_type,decision.action,decision.decision,decision.recommended_action,"Not available"),result=first(recon.result,"Not evaluated"),reason=humanError(first(ai.reason,recon.detail,"No AI rationale returned.")),invoiceStatus=first(invoice.status,"Unknown"),outcome=first(invoice.recovery_outcome,invoice.outcome,"Not available"),recovered=first(invoice.recovered_amount,invoice.amount_recovered);
 setHTML("dfrSummary",[
 `<div class="dfr-summary-item"><span class="dfr-label">Invoice ID</span><div class="dfr-value">${esc(invoiceId)} ${`<span class="dfr-pill">${esc(invoiceStatus)}</span>`}</div><div class="dfr-meta">Amount: ${amount===undefined?"—":money(amount,currency)} · Failure: ${esc(category)}</div></div>`,
 `<div class="dfr-summary-item"><span class="dfr-label">Subscription ID</span><div class="dfr-value">${esc(subscription)}</div><div class="dfr-meta">Customer: ${esc(first(invoice.customer_name,invoice.customer_id,"Not recorded"))}<br>Batch: ${esc(first(invoice.batch_id,"Not recorded"))}</div></div>`,
 `<div class="dfr-summary-item"><span class="dfr-label">Last Updated</span><div class="dfr-value">${esc(date(first(invoice.updated_at,invoice.created_at)))}</div><div class="dfr-meta">Based on the invoice record timestamp returned by the API.</div></div></div>`,
 `<div class="dfr-summary-item"><span class="dfr-label">Current Status</span><div class="dfr-value">${esc(invoiceStatus)}</div><div class="dfr-meta">Outcome: ${esc(outcome)}</div></div>`].join(""));
 const confidence=first(ai.confidence,learning.confidence),priority=first(ai.priority_score,decision.priority_score),recoveredAmount=first(recovered,0);
 const aiUnavailable=!recon.ai_available||String(recon.result||"").toLowerCase()==="ai_unavailable";
  const aiTitle=aiUnavailable?"AI unavailable":displayAction(aiAction);
  const policyTitle=displayAction(policyAction);
  const outcomeTitle=String(invoiceStatus).toLowerCase()==="paid"?"Payment recorded":displayAction(result);
  const confirmedRecovery=first(invoice.recovered_amount,invoice.amount_recovered,data.recovered_amount);
  const amountTitle=confirmedRecovery===undefined?"Not supplied":money(confirmedRecovery,currency);
  setHTML("dfrKpis",[
  `<div class="dfr-kpi ai"><div class="dfr-kpi-icon">✧</div><div class="dfr-kpi-copy"><small>AI Recommendation</small><strong>${esc(aiTitle)}</strong><p>${esc(aiUnavailable?"Advisory service did not return a recommendation":confidence===undefined?"Confidence not supplied":"Confidence: "+confidence)}</p></div></div>`,
  `<div class="dfr-kpi policy"><div class="dfr-kpi-icon">⬡</div><div class="dfr-kpi-copy"><small>Policy Decision</small><strong>${esc(policyTitle)}</strong><p>Deterministic policy is authoritative</p></div></div>`,
  `<div class="dfr-kpi outcome"><div class="dfr-kpi-icon">◉</div><div class="dfr-kpi-copy"><small>Invoice Status</small><strong>${esc(outcomeTitle)}</strong><p>${esc(String(invoiceStatus).toLowerCase()==="paid"?"Backend reports this invoice as paid":humanError(first(recon.detail,"No execution outcome was supplied")))}</p></div></div>`,
  `<div class="dfr-kpi amount"><div class="dfr-kpi-icon">↗</div><div class="dfr-kpi-copy"><small>Confirmed Recovery</small><strong>${esc(amountTitle)}</strong><p>${confirmedRecovery===undefined?"No confirmed recovery amount was supplied":"Amount supplied by the backend"}</p></div></div>`].join(""));
 const rawError=first(diagnosis.raw_error_code,diagnosis.error_code,diagnosis.gateway_error_code,"Not recorded"),gateway=first(diagnosis.gateway_message,diagnosis.error_message,diagnosis.failure_reason,diagnosis.reason,"No diagnosis detail returned.");
 setHTML("dfrDiagnosis",`<span class="dfr-diagnosis-category">${esc(category)}</span><span class="dfr-diagnosis-type">${esc(first(diagnosis.failure_type,diagnosis.category_type,"Failure classification"))}</span><p class="dfr-description">${esc(gateway)}</p><div class="dfr-detail-box"><div class="dfr-detail-row"><span>Raw Error Code</span><span>${esc(rawError)}</span></div><div class="dfr-detail-row"><span>Failure Reason</span><span>${esc(first(diagnosis.failure_reason,diagnosis.reason,"Not recorded"))}</span></div><div class="dfr-detail-row"><span>AI Rationale</span><span>${esc(reason)}</span></div></div>`);
 const timingAI=first(ai.action_timing,ai.timing,decision.action_timing,"Not supplied"),timingPolicy=first(decision.action_timing,decision.scheduled_for,decision.retry_after,"Not supplied");
 const rows=[["Recommended Action",aiAction,policyAction,result],["Confidence",confidence===undefined?"Not supplied":String(confidence),"Not applicable","Not a probability of payment success"],["Action Timing",timingAI,timingPolicy,"Compare only if both sources provide timing"],["Reason",humanError(reason),humanError(first(decision.rationale,decision.reason,"No policy rationale returned")),result],["Authority","Advisory","Final (authoritative)","Deterministic policy"]];
 setHTML("dfrComparison",rows.map(r=>`<tr><td>${esc(r[0])}</td><td>${esc(r[1])}</td><td>${esc(r[2])}</td><td>${statusBadge(r[3])}</td></tr>`).join(""));
 const timeline=[];timeline.push({title:"Failure / invoice context",detail:`Category: ${category}`,time:first(invoice.updated_at,invoice.created_at)});timeline.push({title:"Diagnosis",detail:first(diagnosis.reason,diagnosis.failure_reason,"Diagnosis details returned by API"),time:first(diagnosis.created_at)});timeline.push({title:"AI recommendation",detail:`${aiAction} · ${String(first(reason,"No rationale returned"))}`,time:first(ai.created_at)});timeline.push({title:"Deterministic policy",detail:`${policyAction} · deterministic policy retains authority`,time:first(decision.created_at,decision.decided_at)});events.forEach(e=>timeline.push({title:first(e.stage,e.type,e.event_type,"Recorded event"),detail:first(e.detail,e.result,e.action_taken,"Recorded event"),time:first(e.timestamp,e.created_at,e.executed_at)}));
 setHTML("dfrTimeline",timeline.map((t,i)=>`<li><span class="dfr-step${/paid|captur|recover|success/i.test(t.detail)?" success":""}">${i+1}</span><strong>${esc(t.title)}</strong><small>${esc(date(t.time))}</small><p>${esc(t.detail)}</p></li>`).join(""));
 const sample=first(signal.sample_size,hist.similar_case_count,arr(hist.historical_cases).length),rate=first(signal.historical_recovery_rate,hist.historical_recovery_rate),quality=first(summary.overall_evidence_quality,summary.evidence_quality,summary.quality,signal.signal,"Not supplied"),caseRows=arr(first(hist.historical_cases,hist.comparable_cases,[]));
 setHTML("dfrEvidenceCards",[
 [sample===undefined?"—":sample,"Similar Cases","Sample size"],[rate===undefined?"—":`${Math.round(Number(rate)*100)}%`,"Historical Recovery Rate","Observed history, not prediction"],[first(hist.failure_category_learning?.learning_signal?.signal,hist.failure_category_learning?.signal,hist.failure_category_learning?.assessment,"Unavailable"),"Failure Category","Historical signal"],[first(hist.amount_band_learning?.learning_signal?.signal,hist.amount_band_learning?.signal,hist.amount_band_learning?.assessment,"Unavailable"),"Amount Band","Historical signal"],[first(hist.recency_learning?.recency_signal,hist.recency_learning?.signal,hist.recency_learning?.assessment,"Unavailable"),"Recency","Historical signal"],[evidenceLabel(first(consistency.consistency_signal,summary.confidence_signal,"Unavailable")),"Evidence Alignment","Historical evidence only"]].map(x=>`<div class="dfr-evidence-stat"><strong>${esc(evidenceLabel(x[0]))}</strong><span>${esc(x[1])}</span><small>${esc(x[2])}</small></div>`).join(""));
 const signals=[["Learning signal",first(signal.signal,"Not supplied")],["Evidence quality",quality],["Historical sample size",sample??"Not supplied"],["Observed recovery rate",rate===undefined?"Not supplied":`${(Number(rate)*100).toFixed(1)}%`],["AI learning used",learning.used===undefined?"Not supplied":String(learning.used)],["AI feedback cases",Object.values(obj(learning.ai_action_feedback?.actions)).reduce((n,v)=>n+Number(v.total_cases||0),0)]];
 setHTML("dfrSignals",signals.map(x=>`<div class="dfr-signal"><span>${esc(evidenceLabel(x[0]))}</span><strong>${esc(x[1])}</strong></div>`).join(""));
 setHTML("dfrConsistency",`<div class="dfr-evidence-stat"><strong>${esc(first(consistency.consistency_signal,summary.confidence_signal,"Not available"))}</strong><span>Evidence consistency</span><small>${esc(first(consistency.interpretation,consistency.detail,summary.interpretation,summary.detail,"No consistency explanation returned."))}</small></div><p class="dfr-description">Historical evidence labels describe evidence depth, not probability of financial success.</p>`);
 setHTML("dfrCases",caseRows.length?caseRows.slice(0,10).map(c=>`<tr><td>${esc(first(c.invoice_id,"—"))}</td><td>${c.amount===undefined?"—":money(c.amount,first(c.currency,"INR"))}</td><td>${statusBadge(first(c.outcome,c.deterministic_status,"Unknown"))}</td></tr>`).join(""):empty("No comparable case records were returned."));
 setHTML("dfrAttempts",attempts.length?attempts.map(a=>`<tr><td>${esc(first(a.attempt_id,a.attempt_number,"—"))}</td><td>${esc(date(first(a.executed_at,a.created_at,a.timestamp)))}</td><td>${esc(first(a.action_type,a.attempt_type,a.action_taken,"—"))}</td><td>${statusBadge(first(a.gateway_status,"Not recorded"))}</td><td>${statusBadge(first(a.result,"Not recorded"))}</td><td>${a.amount===undefined?"—":money(a.amount,first(a.currency,currency))}</td></tr>`).join(""):empty("The inspection endpoint does not include payment attempts; no execution records inferred."));
 setHTML("dfrAudit",events.length?events.slice(0,30).map(e=>`<tr><td>${esc(date(first(e.timestamp,e.created_at)))}</td><td>${esc(first(e.stage,e.type,e.event_type,"Event"))}</td><td>${esc(first(e.detail,e.result,e.action_taken,"—"))}</td></tr>`).join(""):empty("No audit events were returned for this invoice."));
 $("dfrDataNote").textContent="Data is limited to fields returned by the inspection and audit APIs. Missing execution data is not inferred.";
 }
 async function inspect(){const loading=$("dfrLoading"),error=$("dfrError"),report=$("dfrReport");loading.hidden=false;error.hidden=true;report.hidden=true;loading.textContent="Loading inspection data…";const invoiceId=window.DunnFlowState?.invoiceId;if(!invoiceId){loading.hidden=true;error.hidden=false;error.textContent="Missing invoice_id. Open this page as /ai-inspection?invoice_id=YOUR_INVOICE_ID";return;}try{let data;if(window.DunnFlowAPI?.inspectDemoCase){data=await window.DunnFlowAPI.inspectDemoCase(invoiceId);}else{const response=await fetch(`/api/demo/cases/${encodeURIComponent(invoiceId)}/inspect`,{headers:{Accept:"application/json"}});if(!response.ok)throw new Error(`Inspection API returned HTTP ${response.status}`);data=await response.json();}let audit={events:[]};try{if(window.DunnFlowAPI?.getAuditTrail){audit=await window.DunnFlowAPI.getAuditTrail({invoiceId:invoiceId});}else{const response=await fetch(`/api/audit?invoice_id=${encodeURIComponent(invoiceId)}`,{headers:{Accept:"application/json"}});if(response.ok)audit=await response.json();}}catch(e){console.warn("Audit trail unavailable:",e);}render(obj(data),obj(audit));loading.hidden=true;report.hidden=false;}catch(e){loading.hidden=true;error.hidden=false;error.textContent=`Unable to load inspection report: ${e?.message||e}. No payment action was triggered.`;}}
 function initSectionNavigation(){
    const sidebar=$("dfrSidebar");
    if(!sidebar)return;
    const buttons=[...sidebar.querySelectorAll("[data-dfr-view]")];
    const panels=[...document.querySelectorAll("#dfrReport [data-dfr-panel]")];
    function activate(view){
        const target=panels.find(panel=>panel.dataset.dfrPanel===view);
        if(!target)return;
        buttons.forEach(button=>{
            const active=button.dataset.dfrView===view;
            button.classList.toggle("is-active",active);
            if(active)button.setAttribute("aria-current","page");
            else button.removeAttribute("aria-current");
        });
        panels.forEach(panel=>{
            const active=panel.dataset.dfrPanel===view;
            panel.hidden=!active;
            panel.classList.toggle("is-active",active);
        });
    }
    buttons.forEach(button=>{
        button.addEventListener("click",()=>activate(button.dataset.dfrView));
    });
    activate("overview");
}
function init(){const close=$("closeDecisionModalBtn");const params=new URLSearchParams(window.location.search);const queryInvoice=params.get("invoice_id");if(queryInvoice){window.DunnFlowState=window.DunnFlowState||{};window.DunnFlowState.invoiceId=queryInvoice;}if(close)close.addEventListener("click",()=>{if(document.referrer && new URL(document.referrer).origin===window.location.origin)history.back();else window.location.href="/";});$("dfrPrintBtn")?.addEventListener("click",()=>{document.body.classList.add("dfr-printing");window.print();setTimeout(()=>document.body.classList.remove("dfr-printing"),500);});$("dfrExportBtn")?.addEventListener("click",async()=>{
const button=$("dfrExportBtn"),report=$("dfrReport");
if(!report||report.hidden){alert("The inspection report is not available yet.");return;}
const originalText=button.textContent;
button.disabled=true;
button.textContent="Preparing PDF...";
let printWindow=null;

try{
const logoResponse=await fetch("/static/images/dunnflow-logo.png");
if(!logoResponse.ok)throw new Error("Could not load the DunnFlow logo.");
const logoBlob=await logoResponse.blob();
const logoData=await new Promise((resolve,reject)=>{
const reader=new FileReader();
reader.onload=()=>resolve(reader.result);
reader.onerror=()=>reject(new Error("Could not read DunnFlow logo."));
reader.readAsDataURL(logoBlob);
});

const getText=(selector,fallback="Not available")=>{
const el=report.querySelector(selector);
const text=el?.innerText?.trim();
return text||fallback;
};
const getHtml=(selector)=>{
const el=report.querySelector(selector);
if(!el)return "";
const clone=el.cloneNode(true);
clone.querySelectorAll("button,.dfr-actions,.dfr-sidebar,.dfr-nav-btn,[hidden]").forEach(n=>n.remove());
return clone.innerHTML;
};
const getCard=(selector)=>{
const el=report.querySelector(selector)?.closest(".dfr-card");
if(!el)return "";
const clone=el.cloneNode(true);
clone.querySelectorAll("button,[hidden]").forEach(n=>n.remove());
return clone.innerHTML;
};
const invoiceId=String(window.DunnFlowState?.invoiceId||new URLSearchParams(location.search).get("invoice_id")||"inspection-report");
const safeId=invoiceId.replace(/[^a-zA-Z0-9_-]/g,"_");
const generatedAt=new Date().toLocaleString("en-IN",{dateStyle:"medium",timeStyle:"short"});

const summary=getHtml("#dfrSummary");
const kpis=getHtml("#dfrKpis");
const diagnosis=getCard("#dfrDiagnosis");
const comparison=getCard("#dfrComparison");
const evidenceCards=getHtml("#dfrEvidenceCards");
const signals=getHtml("#dfrSignals");
const consistency=getHtml("#dfrConsistency");
const cases=getCard("#dfrCases");
const attempts=getCard("#dfrAttempts");
const safety=getHtml(".dfr-safety");

const cleanTable=(html)=>html
.replace(/<table/g,'<table class="report-table"')
.replace(/<th/g,'<th')
.replace(/<td/g,'<td');

const template=`
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>DunnFlow Inspection - ${invoiceId}</title>
<style>
@page{size:A4;margin:14mm 13mm 16mm}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:#fff;color:#263449;font-family:Arial,Helvetica,sans-serif;font-size:10pt;line-height:1.45}
body{print-color-adjust:exact;-webkit-print-color-adjust:exact}
.page{position:relative;min-height:267mm;page-break-after:always;break-after:page;padding-bottom:12mm}
.page:last-child{page-break-after:auto;break-after:auto}
.header{display:flex;align-items:center;justify-content:space-between;gap:12px;padding-bottom:10px;border-bottom:2px solid #163b78;margin-bottom:18px}
.brand{display:flex;align-items:center;gap:10px}
.logo{width:48px;height:48px;object-fit:contain}
.brand-name{font-size:19pt;line-height:1.1;font-weight:800;color:#123678;letter-spacing:-.4px}
.brand-sub{font-size:8pt;color:#64748b;margin-top:4px}
.header-meta{text-align:right;font-size:8pt;color:#64748b;max-width:48%;overflow-wrap:anywhere}
h1{font-size:21pt;line-height:1.2;color:#123678;margin:0 0 5px}
.subtitle{font-size:10pt;color:#64748b;margin:0 0 17px}
h2{font-size:13pt;color:#123678;margin:16px 0 10px;padding-bottom:7px;border-bottom:1px solid #dce5f0}
h3{font-size:11pt;color:#163b78;margin:0 0 9px}
p{margin:5px 0}
.card{border:1px solid #d8e3ef;border-radius:9px;padding:12px;margin:0 0 12px;background:#fff;break-inside:avoid;page-break-inside:avoid}
.summary,.kpis,.evidence{display:grid;gap:9px}
.summary{grid-template-columns:1fr 1fr;background:#f8fbff}
.kpis{grid-template-columns:1fr 1fr}
.evidence{grid-template-columns:1fr 1fr}
.report-table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:9pt}
.report-table th{background:#eaf2fc;color:#17366b;text-align:left;font-weight:700}
.report-table th,.report-table td{padding:8px 7px;border-bottom:1px solid #e0e8f1;vertical-align:top;overflow-wrap:anywhere;word-break:normal;text-align:left}
.report-table tr{break-inside:avoid;page-break-inside:avoid}
table:not(.report-table){width:100%;border-collapse:collapse;table-layout:fixed;font-size:9pt}
table:not(.report-table) th{background:#eaf2fc;color:#17366b;text-align:left}
table:not(.report-table) th,table:not(.report-table) td{padding:8px 7px;border-bottom:1px solid #e0e8f1;vertical-align:top;overflow-wrap:anywhere}
.dfr-summary,.dfr-kpis,.dfr-evidence-cards{display:grid;grid-template-columns:1fr 1fr;gap:9px}
.dfr-summary-item,.dfr-kpi,.dfr-evidence-stat,.dfr-subcard{min-width:0;padding:10px;border:1px solid #dce5ef;border-radius:8px;background:#fff;break-inside:avoid}
.dfr-label,.dfr-kpi small{display:block;font-size:8pt;color:#64748b;margin-bottom:4px}
.dfr-value,.dfr-kpi strong{font-size:12pt;color:#123678;overflow-wrap:anywhere}
.dfr-card{color:#263449}
.dfr-card h3{font-size:11pt;color:#163b78;margin:0 0 10px;padding-bottom:7px;border-bottom:1px solid #e2eaf3}
.dfr-pill,.dfr-result{display:inline-block;background:#edf4ff;color:#234a82;border:1px solid #dbe7f8;border-radius:20px;padding:3px 7px;font-size:8pt;white-space:normal}
.dfr-icon{display:none}
.dfr-table-scroll{overflow:visible!important;width:100%!important}
.dfr-signal{padding:6px 0;border-bottom:1px solid #e4ebf3}
.dfr-safety{background:#f4f8ff;border:1px solid #dce8f8;border-radius:8px;padding:10px;color:#334155}
.footer{position:absolute;bottom:0;left:0;right:0;border-top:1px solid #dce5ef;padding-top:7px;display:flex;justify-content:space-between;color:#64748b;font-size:8pt}
.footer strong{color:#123678}
.notice{background:#effaf5;border:1px solid #cbeadd;color:#176448;border-radius:7px;padding:8px 10px;font-size:9pt}
@media screen{
body{background:#eef2f7;padding:24px}
.page{width:184mm;min-height:267mm;margin:0 auto 24px;background:#fff;padding:0 0 12mm;box-shadow:0 3px 18px #15223818}
}
</style>
</head>
<body>
<section class="page">
<header class="header"><div class="brand"><img class="logo" src="${logoData}"><div><div class="brand-name">DunnFlow</div><div class="brand-sub">Revenue Recovery Control Center</div></div></div><div class="header-meta">Invoice: ${invoiceId}<br>Generated ${generatedAt}</div></header>
<h1>AI Inspection Report</h1><p class="subtitle">Subscription overview and recovery diagnosis</p>
${summary?`<section class="card"><h3>Subscription & Invoice Overview</h3>${summary}</section>`:""}
${kpis?`<h2>Inspection Result</h2>${kpis}`:""}
${diagnosis?`<h2>Failure Diagnosis</h2><section class="card">${diagnosis}</section>`:""}
<div class="notice">Deterministic recovery policy remains authoritative. This report is read-only and does not execute payment actions.</div>
<footer class="footer"><span><strong>DunnFlow</strong> · AI Inspection Report</span><span>Page 1 of 4</span></footer>
</section>
<section class="page">
<header class="header"><div class="brand"><img class="logo" src="${logoData}"><div><div class="brand-name">DunnFlow</div><div class="brand-sub">Revenue Recovery Control Center</div></div></div><div class="header-meta">Invoice: ${invoiceId}<br>Decision comparison</div></header>
<h1>Decision Comparison</h1><p class="subtitle">AI advisory recommendation versus deterministic policy</p>
${comparison?`<section class="card">${comparison}</section>`:"<p>No comparison data was returned by the inspection API.</p>"}
${attempts?`<section class="card"><h2>Execution & Payment Details</h2>${attempts}</section>`:""}
<footer class="footer"><span><strong>DunnFlow</strong> · AI Inspection Report</span><span>Page 2 of 4</span></footer>
</section>
<section class="page">
<header class="header"><div class="brand"><img class="logo" src="${logoData}"><div><div class="brand-name">DunnFlow</div><div class="brand-sub">Revenue Recovery Control Center</div></div></div><div class="header-meta">Invoice: ${invoiceId}<br>Historical evidence</div></header>
<h1>Historical Evidence Analysis</h1><p class="subtitle">Recovery patterns and evidence alignment</p>
${evidenceCards?`<section class="card"><h2>Key Historical Metrics</h2>${evidenceCards}</section>`:""}
<div class="evidence">${signals?`<section class="card"><h3>Historical Signals</h3>${signals}</section>`:""}${consistency?`<section class="card"><h3>Evidence Consistency</h3>${consistency}</section>`:""}</div>
<footer class="footer"><span><strong>DunnFlow</strong> · AI Inspection Report</span><span>Page 3 of 4</span></footer>
</section>
<section class="page">
<header class="header"><div class="brand"><img class="logo" src="${logoData}"><div><div class="brand-name">DunnFlow</div><div class="brand-sub">Revenue Recovery Control Center</div></div></div><div class="header-meta">Invoice: ${invoiceId}<br>Related records</div></header>
<h1>Similar Cases & Payment Details</h1><p class="subtitle">Historical examples and available execution records</p>
${cases?`<section class="card"><h2>Recent Similar Cases</h2>${cases}</section>`:""}

${safety?`<section class="card">${safety}</section>`:""}
<footer class="footer"><span><strong>DunnFlow</strong> · AI Inspection Report</span><span>Page 4 of 4</span></footer>
</section>
</body>
</html>`;

printWindow=window.open("","_blank","width=1000,height=800");
if(!printWindow)throw new Error("The browser blocked the report window. Allow pop-ups for this site and retry.");
printWindow.document.open();
printWindow.document.write(template);
printWindow.document.close();
await new Promise((resolve,reject)=>{
const timeout=setTimeout(()=>reject(new Error("PDF report window did not finish loading.")),10000);
printWindow.onload=()=>{clearTimeout(timeout);resolve();};
if(printWindow.document.readyState==="complete"){clearTimeout(timeout);resolve();}
});
printWindow.focus();
const downloadButton=printWindow.document.createElement("button");
downloadButton.textContent="Download PDF";
downloadButton.style.cssText="position:fixed;top:12px;right:12px;z-index:999999;background:#123678;color:#fff;border:0;border-radius:8px;padding:12px 18px;font-weight:700;cursor:pointer;box-shadow:0 3px 12px #0002";
downloadButton.onclick=()=>{
downloadButton.remove();
printWindow.focus();
printWindow.print();
};
printWindow.document.body.appendChild(downloadButton);
alert("The clean report is ready in a new tab. Click Download PDF, then choose Save as PDF in the browser print window.");
}catch(error){
console.error("DunnFlow PDF report failed:",error);
alert("Could not prepare report: "+(error?.message||"Unknown error"));
if(printWindow&& !printWindow.closed)printWindow.close();
}finally{
button.disabled=false;
button.textContent=originalText;
}
});initSectionNavigation();inspect();}
 if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();window.DunnFlowDecisionIntelligence={open:openModal,close:closeModal,refresh:inspect};
})();

