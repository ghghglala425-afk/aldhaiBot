# -*- coding: utf-8 -*-
"""تطبيق Mini App — صفحة ويب مستقلة تعمل داخل تلجرام وتستخدم نفس الـAPI."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["miniapp"])

PAGE = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>أكاديمية الأمن السيبراني</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--bg:#0f1424;--card:#1a2138;--acc:#3fd0c9;--acc2:#7c5cff;--txt:#e8ecff;--mut:#93a0c0;--ok:#39d98a;--bad:#ff6b6b}
*{box-sizing:border-box}
body{margin:0;background:linear-gradient(160deg,#0f1424,#141a30);color:var(--txt);
font-family:system-ui,'Segoe UI',Tahoma,sans-serif;padding:12px;padding-bottom:80px}
h1{font-size:20px;margin:8px 0}
.header{display:flex;justify-content:space-between;align-items:center;gap:8px}
.pill{background:var(--card);padding:6px 12px;border-radius:999px;font-size:13px;border:1px solid #2a3355}
.card{background:var(--card);border:1px solid #2a3355;border-radius:16px;padding:14px;margin:10px 0;cursor:pointer;transition:.15s}
.card:hover{border-color:var(--acc);transform:translateY(-2px)}
.card.locked{opacity:.45;cursor:not-allowed}
.title{font-weight:700;font-size:16px}
.meta{color:var(--mut);font-size:13px;margin-top:4px}
.badge{display:inline-block;font-size:12px;padding:2px 8px;border-radius:999px;background:#242e4d;color:var(--mut);margin-inline-start:6px}
.badge.ok{background:#12351f;color:var(--ok)}
button{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#08101f;border:0;border-radius:12px;
padding:11px 16px;font-weight:700;font-size:15px;cursor:pointer;width:100%;margin:6px 0}
button.ghost{background:transparent;border:1px solid #2a3355;color:var(--txt)}
pre{background:#0b1020;border:1px solid #222c4a;border-radius:12px;padding:12px;overflow:auto;direction:ltr;text-align:left;font-size:13px}
.muted{color:var(--mut);font-size:13px}
input,textarea,select{width:100%;background:#0b1020;border:1px solid #222c4a;border-radius:12px;color:var(--txt);padding:10px;margin:6px 0;font-family:inherit}
.nav{position:fixed;bottom:0;right:0;left:0;display:flex;background:#0b1020;border-top:1px solid #222c4a;padding:8px}
.nav button{margin:0 4px;font-size:14px}
q{cursor:pointer}
.opt{background:#141b30;border:1px solid #222c4a;border-radius:12px;padding:10px;margin:6px 0;display:block}
.opt.sel{border-color:var(--acc);background:#12303a}
.q{margin:14px 0}
.res{font-size:18px;font-weight:800;margin:10px 0}
.bar{background:#0b1020;border:1px solid #222c4a;border-radius:20px;height:10px;overflow:hidden;margin:6px 0}
.bar span{display:block;height:100%;background:linear-gradient(90deg,var(--acc),#4da3ff)}
.codecard summary{cursor:pointer;font-size:15px}
.sec{margin:10px 0;border-top:1px dashed #2a3355;padding-top:8px}
.line{display:flex;gap:8px;align-items:baseline;margin:3px 0;direction:ltr;text-align:left}
.line .ln{color:var(--acc);min-width:24px;font-size:12px}
.line code{font-size:13px}
.use{background:#111830;border:1px solid #222c4a;border-radius:10px;padding:8px;margin:6px 0}
</style>
</head>
<body>
<div class="header">
  <h1>🎓 أكاديمية الأمن السيبراني</h1>
  <span class="pill" id="me">—</span>
</div>
<div id="view"><p class="muted">جار التحميل…</p></div>
<div class="nav">
  <button class="ghost" onclick="go('courses')">📚 الكورسات</button>
  <button class="ghost" onclick="go('paths')">🛤️ المسارات</button>
  <button class="ghost" onclick="go('rank')">🏆 الصدارة</button>
  <button class="ghost" onclick="go('tools')">🕵️ أدوات</button>
  <button class="ghost" onclick="go('profile')">👤 حسابي</button>
</div>
<script>
const tg = window.Telegram ? window.Telegram.WebApp : null;
if (tg){ tg.ready(); tg.expand(); }
let TOKEN = localStorage.getItem('token') || '';
const $ = s => document.querySelector(s);
const view = $('#view');
const esc = s => (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

async function api(path, opts={}){
  opts.headers = Object.assign({'Content-Type':'application/json'}, opts.headers||{});
  if (TOKEN) opts.headers['Authorization'] = 'Bearer ' + TOKEN;
  const r = await fetch(path, opts);
  if (!r.ok){ throw new Error((await r.json()).detail || 'خطأ'); }
  return r.json();
}

async function boot(){
  try{
    if (tg && tg.initData){
      const r = await api('/api/auth/telegram', {method:'POST', body: JSON.stringify({init_data: tg.initData})});
      TOKEN = r.token; localStorage.setItem('token', TOKEN);
    }
  }catch(e){ console.warn(e); }
  if (!TOKEN){ return loginForm(); }
  await refreshMe(); go('courses');
}

function loginForm(){
  view.innerHTML = `<div class="card" style="cursor:default">
    <div class="title">دخول</div>
    <input id="email" placeholder="البريد الإلكتروني">
    <input id="pass" type="password" placeholder="كلمة المرور">
    <button onclick="doLogin()">دخول</button>
    <button class="ghost" onclick="doRegister()">إنشاء حساب</button>
    <p class="muted" id="err"></p></div>`;
}
async function doLogin(){
  try{
    const r = await api('/api/auth/login',{method:'POST',body:JSON.stringify({email:$('#email').value,password:$('#pass').value})});
    TOKEN=r.token; localStorage.setItem('token',TOKEN); await refreshMe(); go('courses');
  }catch(e){ $('#err').textContent=e.message; }
}
async function doRegister(){
  try{
    const r = await api('/api/auth/register',{method:'POST',body:JSON.stringify({email:$('#email').value,password:$('#pass').value})});
    TOKEN=r.token; localStorage.setItem('token',TOKEN); await refreshMe(); go('courses');
  }catch(e){ $('#err').textContent=e.message; }
}

async function refreshMe(){
  try{ const m = await api('/api/auth/me'); $('#me').textContent = `⭐ ${m.xp} · Lv${m.level} · 🔥${m.streak}`; }
  catch(e){}
}

async function go(page){
  view.innerHTML = '<p class="muted">جار التحميل…</p>';
  try{
    if (page==='courses') return renderCourses();
    if (page==='paths') return renderPaths();
    if (page==='rank') return renderRank();
    if (page==='tools') return renderTools();
    if (page==='profile') return renderProfile();
  }catch(e){ view.innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
}

async function renderPaths(){
  const list = await api('/api/paths');
  view.innerHTML = '<h1>🛤️ المسارات التعلّمية</h1>' + (list.length? '' : '<p class="muted">لا توجد مسارات.</p>');
  list.forEach(p=>{
    const d=document.createElement('div'); d.className='card';
    d.innerHTML = `<div class="title">${p.icon||'•'} ${esc(p.title)}</div>
      <div class="meta">${esc(p.description||'')}</div>
      <div class="meta">التقدّم: ${p.passed}/${p.total} (${p.percent}%) ${p.certificate?'🎓 '+esc(p.certificate):''}</div>
      <div class="bar"><span style="width:${p.percent}%"></span></div>`;
    d.onclick = ()=>openPath(p.slug);
    view.appendChild(d);
  });
}
async function openPath(slug){
  const p = await api(`/api/paths/${slug}`);
  view.innerHTML = `<h1>${p.icon||'•'} ${esc(p.title)}</h1>
    <button class="ghost" onclick="go('paths')">← رجوع</button>
    <div class="card" style="cursor:default"><div class="meta">${esc(p.description||'')}</div>
    <div class="meta">الكورسات: ${p.courses.map(esc).join('، ')}</div>
    <div class="meta">التقدّم: ${p.passed}/${p.total} (${p.percent}%)</div>
    ${p.certificate?`<div class="res">🎓 شهادة المسار: ${esc(p.certificate)}</div>`:''}</div>`;
  for (const c of p.courses){
    const d=document.createElement('div'); d.className='card';
    d.innerHTML = `<div class="title">📘 ${esc(c)}</div>`;
    d.onclick = ()=>renderLessons(c, c);
    view.appendChild(d);
  }
}

async function renderCourses(){
  const list = await api('/api/courses');
  view.innerHTML = '<h1>الكورسات</h1>' + (list.length? '' : '<p class="muted">لا توجد كورسات منشورة.</p>');
  list.forEach(c=>{
    const d=document.createElement('div'); d.className='card';
    d.innerHTML = `<div class="title">${c.icon||'📘'} ${esc(c.title)}</div><div class="meta">${esc(c.track)} · ${esc(c.difficulty)}</div>`;
    d.onclick = ()=>renderLessons(c.slug, c.title);
    view.appendChild(d);
  });
}

function codeCard(c, i){
  const lang = `<span class="badge">${esc(c.language)}</span>`;
  const anatomy = (c.anatomy||[]).length ? `<div class="sec"><b>🔬 تشريح سطري</b>` +
      (c.anatomy||[]).map(a=>`<div class="line"><span class="ln">${a.line||''}</span><code>${esc(a.code||'')}</code><span class="muted"> ${esc(a.explain||'')}</span></div>`).join('') + `</div>` : '';
  const usages = (c.usages||[]).length ? `<div class="sec"><b>🧰 الاستخدامات (${c.usages.length})</b>` +
      (c.usages||[]).map(u=>`<div class="use"><div class="title" style="font-size:14px">${esc(u.name)}</div>
        ${u.signature?`<pre style="margin:4px 0">${esc(u.signature)}</pre>`:''}
        <div class="muted">${esc(u.description||'')}</div>
        ${u.example?`<pre style="margin:4px 0">${esc(u.example)}</pre>`:''}
        ${u.output?`<div class="muted">الخرج: ${esc(u.output)}</div>`:''}</div>`).join('') + `</div>` : '';
  const params = (c.parameters||[]).length ? `<div class="sec"><b>⚙️ المعاملات</b>` +
      c.parameters.map(p=>`<div class="muted">• <code>${esc(p.name)}</code>${p.type?` (${esc(p.type)})`:''}: ${esc(p.description||'')}${p.default?` — الافتراضي ${esc(p.default)}`:''}${p.required?' <b>[إلزامي]</b>':''}</div>`).join('') + `</div>` : '';
  const ret = c.returns ? `<div class="sec"><b>↩️ القيمة المُرجعة</b><div class="muted">${esc(c.returns)}</div></div>` : '';
  const gotchas = (c.gotchas||[]).length ? `<div class="sec"><b>⚠️ أخطاء شائعة</b>${c.gotchas.map(g=>`<div class="muted">• ${esc(g)}</div>`).join('')}</div>` : '';
  const sec = (c.security_notes||[]).length ? `<div class="sec"><b>🛡️ ملاحظات أمنية</b>${c.security_notes.map(g=>`<div class="muted">• ${esc(g)}</div>`).join('')}</div>` : '';
  const meta = ((c.related||[]).length || (c.tags||[]).length) ? `<div class="muted" style="margin-top:6px">${
      (c.tags||[]).map(t=>`<span class="badge">${esc(t)}</span>`).join(' ')} ${
      (c.related||[]).length?('مرتبط: '+c.related.map(esc).join('، ')):''}</div>` : '';
  return `<details class="card codecard"><summary><b>${i+1}. ${esc(c.title)}</b> ${lang}</summary>
    <pre>${esc(c.code)}</pre>
    <div class="muted">${esc(c.explanation||'')}</div>
    ${anatomy}${usages}${params}${ret}${gotchas}${sec}${meta}</details>`;
}

async function renderLessons(slug, title){
  view.innerHTML = `<h1>${esc(title)}</h1><button class="ghost" onclick="go('courses')">← رجوع</button>`;
  const list = await api(`/api/courses/${slug}/lessons`);
  const icon = {passed:'✅', available:'▶️', locked:'🔒', in_progress:'⏳'};
  list.forEach(l=>{
    const d=document.createElement('div');
    d.className = 'card' + (l.status==='locked'?' locked':'');
    d.innerHTML = `<div class="title">${icon[l.status]||'•'} ${esc(l.title)}<span class="badge ${l.status==='passed'?'ok':''}">${l.status==='passed'?'مكتمل '+l.best_score+'%':l.status}</span></div>
    <div class="meta">${esc(l.difficulty)} · ${l.est_minutes} دقيقة</div>`;
    if (l.status!=='locked') d.onclick = ()=>renderLesson(l.id);
    view.appendChild(d);
  });
}

async function renderLesson(id){
  view.innerHTML = '<p class="muted">جار التحميل…</p>';
  const l = await api(`/api/lessons/${id}`);
  const quiz = await api(`/api/lessons/${id}/quiz`);
  const labs = await api(`/api/lessons/${id}/labs`);
  let html = `<h1>📖 ${esc(l.title)}</h1>
  <div class="card" style="cursor:default"><div class="meta">${esc(l.summary||'')}</div></div>
  <div class="card" style="cursor:default"><div class="title">الشرح</div><div class="meta">${esc(l.content_md||'').replace(/\n/g,'<br>')}</div></div>`;
  html += `<div class="card" style="cursor:default"><div class="title">💻 الأكواد</div>`;
  html += '<div id="codes"></div></div>';
  if (quiz.questions && quiz.questions.length){
    html += `<div class="card" style="cursor:default"><div class="title">🧠 الاختبار</div><div id="quiz"></div>
    <button onclick="submitQuiz(${id})">إرسال الاختبار</button><div class="res" id="qres"></div></div>`;
  }
  if (labs.length){
    html += `<div class="card" style="cursor:default"><div class="title">🧪 المختبرات</div><div id="labs"></div></div>`;
  }
  html += '<button class="ghost" onclick="go(\'courses\')">← رجوع</button>';
  view.innerHTML = html;

  const codeList = l.code_samples || [];
  const box = document.getElementById('codes');
  if (!codeList.length){ box.innerHTML = '<p class="muted">لا توجد أكواد لهذا الدرس.</p>'; }
  else { box.innerHTML = codeList.map((c,i)=>codeCard(c,i)).join(''); }

  window.__quiz = quiz.questions || [];
  const qbox = document.getElementById('quiz');
  if (qbox){
    qbox.innerHTML = window.__quiz.map((q,i)=>`<div class="q"><b>${i+1}. ${esc(q.text)}</b>
      ${q.options.map(o=>`<label class="opt"><input type="${q.kind==='multi'?'checkbox':'radio'}" name="q${q.id}" value="${o.id}"> ${esc(o.text)}</label>`).join('')}</div>`).join('');
  }
  const lbox = document.getElementById('labs');
  if (lbox){
    lbox.innerHTML = labs.map(lab=>{
      if (lab.kind === 'target'){
        return `<div style="margin:10px 0"><b>🎯 ${esc(lab.title)}</b>
          <div class="meta">${esc(lab.description||'')} · ${lab.points} نقطة</div>
          <button class="ghost" onclick="openTarget(${lab.id})">فتح بيئة الهدف</button>
          <div id="target${lab.id}"></div></div>`;
      }
      return `<div style="margin:10px 0"><b>🧪 ${esc(lab.title)}</b>
        <div class="meta">${esc(lab.description||'')} · ${lab.points} نقطة</div>
        <input id="flag${lab.id}" placeholder="أرسل العلم">
        <button class="ghost" onclick="submitFlag(${lab.id})">تحقق</button>
        <span id="fres${lab.id}" class="muted"></span></div>`;
    }).join('');
  }
}

async function openTarget(labId){
  const box = document.getElementById('target'+labId);
  box.innerHTML = '<p class="muted">جار التحميل…</p>';
  try{
    const t = await api(`/api/labs/${labId}/target`);
    let statusTxt = '🔴 متوقفة';
    if (t.mode === 'external') statusTxt = '🌐 هدف خارجي (جاهز)';
    else if (t.mode === 'guided') statusTxt = '📖 نمط موجّه (بدون حاوية)';
    else if (t.status === 'running') statusTxt = '🟢 تعمل';

    let actions = '';
    if (t.mode === 'external'){
      actions = `<div class="meta">🔗 <a href="${esc(t.url)}" target="_blank">فتح الهدف الخارجي</a></div>`;
    } else if (t.mode === 'guided'){
      actions = `<div class="meta">ℹ️ شغّل الهدف بنفسك عبر Docker أو اضبط <code>TARGET_EXTERNAL_URLS</code>. يمكنك حل المهام أدناه بلا حاوية.</div>`;
    } else if (t.status === 'running'){
      actions = `<button class="ghost" onclick="stopTarget(${labId})">⏹️ إيقاف البيئة</button>`;
    } else {
      actions = `<button onclick="startTarget(${labId})">▶️ تشغيل البيئة</button>`;
    }

    let html = `<div class="card" style="cursor:default">
      <div class="meta">${t.image?('الصورة: <code>'+esc(t.image)+'</code> · '):''}الحالة: ${statusTxt}</div>
      ${(t.url && t.mode!=='external')?`<div class="meta">🔗 <a href="${esc(t.url)}" target="_blank">${esc(t.url)}</a></div>`:''}
      <div class="meta">✅ ${t.earned}/${t.total_points} نقطة (${t.percent}%)</div>
      ${actions}
    </div>`;
    html += (t.tasks||[]).map(x=>`<div class="use"><b>${x.solved?'✅':'🔲'} ${esc(x.title)} (${x.points})</b>
      <div class="muted">${esc(x.prompt)}</div>
      ${x.solved?'<div class="muted">تم الحل</div>':`<input id="ans${labId}_${x.order}" placeholder="إجابتك">
      <button class="ghost" onclick="submitTask(${labId},${x.order})">تسليم</button>
      <span id="tres${labId}_${x.order}" class="muted"></span>`}</div>`).join('');
    box.innerHTML = html;
  }catch(e){ box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
}

async function startTarget(labId){
  try{ await api(`/api/labs/${labId}/target/start`, {method:'POST'}); }
  catch(e){ alert(e.message); }
  openTarget(labId);
}
async function stopTarget(labId){
  try{ await api(`/api/labs/${labId}/target/stop`, {method:'POST'}); }catch(e){}
  openTarget(labId);
}
async function submitTask(labId, order){
  const val = document.getElementById(`ans${labId}_${order}`).value;
  try{
    const r = await api(`/api/labs/${labId}/target/tasks/${order}`, {method:'POST', body: JSON.stringify({answer: val})});
    document.getElementById(`tres${labId}_${order}`).textContent = r.correct ? '✅ صحيح' : '❌ غير صحيح';
    await refreshMe();
    if (r.correct) openTarget(labId);
  }catch(e){ document.getElementById(`tres${labId}_${order}`).textContent = e.message; }
}

async function submitQuiz(lessonId){
  const responses = {};
  window.__quiz.forEach(q=>{
    const sel = [...document.querySelectorAll(`input[name="q${q.id}"]:checked`)].map(x=>parseInt(x.value));
    responses[q.id] = sel;
  });
  try{
    const r = await api(`/api/lessons/${lessonId}/attempt`, {method:'POST', body: JSON.stringify({responses})});
    document.getElementById('qres').textContent = (r.passed?'🎉 نجحت ':'😅 رسبت ')+r.score+'%';
    await refreshMe();
  }catch(e){ document.getElementById('qres').textContent = e.message; }
}

async function submitFlag(labId){
  const flag = document.getElementById('flag'+labId).value;
  try{
    const r = await api(`/api/labs/${labId}/submit`, {method:'POST', body: JSON.stringify({flag})});
    document.getElementById('fres'+labId).textContent = r.correct ? '✅ صحيح!' : '❌ غير صحيح';
    await refreshMe();
  }catch(e){ document.getElementById('fres'+labId).textContent = e.message; }
}

async function renderRank(){
  const list = await api('/api/leaderboard');
  view.innerHTML = '<h1>🏆 لوحة الصدارة</h1>';
  list.forEach(r=>{
    const d=document.createElement('div'); d.className='card'; d.style.cursor='default';
    d.innerHTML = `<div class="title">${r.rank}. ${esc(r.name)}</div><div class="meta">${r.xp} نقطة</div>`;
    view.appendChild(d);
  });
}

async function renderTools(){
  view.innerHTML = `<h1>🕵️ أدوات اختبار الويب</h1>
  <div class="card" style="cursor:default"><div class="title">🔁 Repeater — إعادة إرسال طلب</div>
    <select id="rp_method" class="inp"><option>GET</option><option>POST</option><option>PUT</option><option>DELETE</option><option>PATCH</option></select>
    <input id="rp_url" placeholder="https://localhost:3000/api/...">
    <textarea id="rp_headers" placeholder='{"Content-Type":"application/json"}' rows="2"></textarea>
    <textarea id="rp_body" placeholder="request body (اختياري)" rows="3"></textarea>
    <button onclick="doRepeater()">إرسال</button>
    <div id="rp_out" class="muted"></div></div>

  <div class="card" style="cursor:default"><div class="title">💥 Fuzzer-lite — اختبار معامل</div>
    <input id="fz_url" placeholder="http://localhost:3000/?q=FUZZ">
    <textarea id="fz_payloads" placeholder="payload لكل سطر" rows="3"></textarea>
    <button onclick="doFuzz()">تشغيل</button>
    <div id="fz_out"></div></div>

  <div class="card" style="cursor:default"><div class="title">🔐 Decoder</div>
    <select id="dc_op" class="inp">
      <option value="b64e">Base64 تشفير</option><option value="b64d">Base64 فك</option>
      <option value="urle">URL تشفير</option><option value="urld">URL فك</option>
      <option value="hexe">Hex تشفير</option><option value="hexd">Hex فك</option>
      <option value="htmle">HTML تشفير</option><option value="htmld">HTML فك</option>
      <option value="md5">MD5</option><option value="sha1">SHA1</option><option value="sha256">SHA256</option>
    </select>
    <textarea id="dc_val" placeholder="القيمة" rows="2"></textarea>
    <button onclick="doDecode()">تنفيذ</button>
    <pre id="dc_out"></pre></div>`;
}

async function doRepeater(){
  const out = document.getElementById('rp_out');
  out.textContent = '…';
  try{
    const headers = document.getElementById('rp_headers').value.trim();
    const r = await api('/api/proxy/request', {method:'POST', body: JSON.stringify({
      method: document.getElementById('rp_method').value,
      url: document.getElementById('rp_url').value,
      headers: headers ? JSON.parse(headers) : {},
      body: document.getElementById('rp_body').value || null,
    })});
    out.innerHTML = `<div class="res">${r.status} · ${r.length} بايت · ${r.duration_ms}ms</div>
      <pre>${esc(JSON.stringify(r.headers, null, 1))}</pre><pre>${esc(r.body)}</pre>`;
  }catch(e){ out.textContent = e.message; }
}

async function doFuzz(){
  const out = document.getElementById('fz_out');
  try{
    const payloads = document.getElementById('fz_payloads').value.split('\n').map(s=>s.trim()).filter(Boolean);
    const r = await api('/api/proxy/fuzz', {method:'POST', body: JSON.stringify({
      url: document.getElementById('fz_url').value, payloads})});
    out.innerHTML = `<table style="width:100%;font-size:13px"><tr><th>payload</th><th>status</th><th>len</th></tr>` +
      r.results.map(x=>`<tr><td>${esc(x.payload)}</td><td>${x.status}</td><td>${x.length||'-'}</td></tr>`).join('') + `</table>`;
  }catch(e){ out.textContent = e.message; }
}

async function doDecode(){
  const out = document.getElementById('dc_out');
  try{
    const r = await api('/api/proxy/decode', {method:'POST', body: JSON.stringify({
      op: document.getElementById('dc_op').value, value: document.getElementById('dc_val').value})});
    out.textContent = r.ok ? r.result : ('⚠️ ' + r.error);
  }catch(e){ out.textContent = e.message; }
}

async function renderProfile(){
  const m = await api('/api/auth/me');
  const bm = await api('/api/bookmarks');
  const nt = await api('/api/notes');
  const certs = await api('/api/certificates');
  view.innerHTML = `<h1>👤 حسابي</h1>
  <div class="card" style="cursor:default">
    <div class="title">${esc(m.username||m.email||'طالب')}</div>
    <div class="meta">النقاط: ${m.xp} · المستوى: ${m.level} · السلسلة: ${m.streak} 🔥</div></div>
  <div class="card" style="cursor:default"><div class="title">🔖 المرجعيات (${bm.length})</div></div>
  <div class="card" style="cursor:default"><div class="title">📝 الملاحظات (${nt.length})</div></div>
  <div class="card" style="cursor:default"><div class="title">🎓 الشهادات (${certs.length})</div>
    ${certs.map(c=>`<div class="meta">${esc(c.code)}</div>`).join('')}</div>`;
}

boot();
</script>
</body>
</html>
"""


@router.get("/app", response_class=HTMLResponse)
async def miniapp() -> HTMLResponse:
    return HTMLResponse(PAGE)
