"use strict";

const VIEW_TITLES={overview:"Tổng quan",access:"Danh bạ & Allowlist",history:"Hội thoại",system:"Hệ thống & Hoạt động"};
const state={csrf:null,view:"overview",draft:null,savedAccess:null,renderVersion:0,qrUrl:null,pendingOperation:null,memberRequestVersion:0};
const APP_USES_INNER_HTML=false;
async function api(path,options={}){const method=options.method||"GET";const headers={...(options.headers||{})};
if(options.body&&!headers["Content-Type"])headers["Content-Type"]="application/json";
if(state.csrf&&!['GET','HEAD'].includes(method))headers["X-CSRF-Token"]=state.csrf;
const response=await fetch(path,{credentials:"same-origin",...options,method,headers});
const data=await response.json().catch(()=>({code:"invalid_response",message:"Phản hồi không hợp lệ"}));
if(!response.ok)throw Object.assign(new Error(data.message||"Yêu cầu thất bại"),{status:response.status,data});return data;}
function el(tag,text,className){const node=document.createElement(tag);if(text!==undefined)node.textContent=String(text);if(className)node.className=className;return node;}
function clearApp(title){const app=document.querySelector("#app");app.replaceChildren(el("h1",title));const route=document.querySelector("#route-label");if(route)route.textContent=`~/admin/${state.view}`;return app;}
function card(title){const root=el("section",undefined,"card");if(title)root.append(el("h2",title));return root;}
function row(label,value){const p=el("p");p.append(el("strong",`${label}: `),document.createTextNode(value===undefined||value===null||value===""?"—":String(value)));return p;}
function button(label,action,tone=""){const item=el("button",label,tone?`button button-${tone}`:"button");item.type="button";item.addEventListener("click",action);return item;}
function entityId(item){return String(item?.id??item?.userId??item?.uid??item?.groupId??item?.threadId??"");}
function entityName(item){return String(item?.name??item?.displayName??item?.zaloName??item?.groupName??entityId(item));}
function friendStatus(item){const explicit=item?.friendStatus;if(explicit!==undefined&&explicit!==null&&explicit!=="")return String(explicit);const isFriend=item?.isFr;if(isFriend===true||isFriend===1||isFriend==="1")return "Bạn bè";if(isFriend===false||isFriend===0||isFriend==="0")return "Chưa kết bạn";const account=item?.accountStatus;return account===undefined||account===null||account===""?"":String(account);}
function setMember(values,id,enabled){const set=new Set((values||[]).map(String));enabled?set.add(String(id)):set.delete(String(id));return [...set].sort();}
function checkbox(label,checked,onChange){const wrap=el("label");const input=document.createElement("input");input.type="checkbox";input.checked=checked;input.addEventListener("change",()=>onChange(input.checked));wrap.append(input,document.createTextNode(` ${label} `));return wrap;}
function tableCell(label,nodeOrText){const cell=el("td");cell.dataset.label=label;if(nodeOrText&&typeof nodeOrText==="object"&&"tagName" in nodeOrText)cell.append(nodeOrText);else cell.append(document.createTextNode(String(nodeOrText??"—")));return cell;}
function dataTable(title,columns,rows){const section=card(title);const table=el("table",undefined,"data-table");const head=el("thead");const header=el("tr");for(const column of columns)header.append(el("th",column));head.append(header);const body=el("tbody");for(const values of rows){const row=el("tr");for(let index=0;index<columns.length;index+=1)row.append(tableCell(columns[index],values[index]));body.append(row);}table.append(head,body);section.append(table);return section;}
function terminalFrame(title){const frame=el("section",undefined,"terminal-frame");const head=el("header",undefined,"terminal-head");for(const color of ["red","amber","green"])head.append(el("i",undefined,`terminal-dot ${color}`));head.append(el("span",title,"terminal-title"));const body=el("div",undefined,"terminal-body");frame.append(head,body);return {frame,body};}
function statusCard(label,value,detail,tone="neutral"){const root=el("article",undefined,`status-card tone-${tone}`);root.append(el("span",label,"status-label"),el("strong",value,"status-value"),el("small",detail,"status-detail"));return root;}
function badge(text,tone="neutral"){return el("span",text,`badge badge-${tone}`);}
function showApp(){document.querySelector("#login-screen").classList.add("hidden");document.querySelector("#app-shell").classList.remove("hidden");}
function showLogin(message=""){document.querySelector("#login-screen").classList.remove("hidden");document.querySelector("#app-shell").classList.add("hidden");document.querySelector("#login-error").textContent=message;}
function beginRender(view){state.view=view;return ++state.renderVersion;}
function renderIsCurrent(token,view){return token===state.renderVersion&&state.view===view;}
function navigate(view){state.view=view;return renderCurrent();}
async function renderOverviewEnhanced(token){
  token=token??beginRender("overview");
  const data=await api("/admin/api/overview");
  if(!renderIsCurrent(token,"overview"))return false;
  const app=clearApp("Tổng quan");
  const adapterState=(data.adapter_active===true||data.connected===true)?"Đang hoạt động":((data.adapter_active===false||data.connected===false)?"Không hoạt động":"Không rõ");
  const zaloState=data.bridge?.loggedIn===true?"Đã đăng nhập":(data.bridge?.loggedIn===false?"Chưa đăng nhập":"Không rõ");
  const bridgeState=data.bridge?.error??(data.bridge?.ok===true?"Hoạt động":(data.bridge?.ok===false?"Không kết nối":"Không rõ"));
  const gatewayState=data.gateway?.status??adapterState;
  const {frame,body}=terminalFrame("TỔNG QUAN · LIVE STATUS");
  const stats=el("div",undefined,"status-grid");
  stats.append(
    statusCard("ZALO",zaloState,data.bridge?.loggedIn?"Đã đăng nhập":"Cần đăng nhập",data.bridge?.loggedIn?"success":"warning"),
    statusCard("HERMES GATEWAY",gatewayState,"Adapter Hermes",data.adapter_active===false?"danger":"success"),
    statusCard("HỘI THOẠI",data.history?.conversations??0,`${data.history?.messages??0} tin nhắn`),
    statusCard("ALLOWLIST",`${data.counts?.allowed_users??0} / ${data.counts?.allowed_groups??0}`,"Thành viên / nhóm")
  );
  const bot=card("Tài khoản bot");
  bot.append(row("Họ tên",data.bot?.name),row("Zalo ID",data.bot?.id),row("Zalo",zaloState),row("Hermes",adapterState));
const runtime=card("Trạng thái hệ thống");
runtime.append(row("Bridge",bridgeState),row("Hermes Gateway",gatewayState),row("Provider",data.provider??"unknown"),row("Model",data.model??"unknown"));
const counts=card("Số liệu");
for(const [label,key] of [["Bạn bè","friends"],["Nhóm","groups"],["Thành viên được phép","allowed_users"],["Quản trị viên","admin_users"],["Nhóm được phép","allowed_groups"]])counts.append(row(label,data.counts?.[key]??0));
counts.append(row("Hội thoại",data.history?.conversations??0),row("Tin nhắn",data.history?.messages??0),row("Tin gần nhất",data.latest_message_at));
const activity=card("Hoạt động gần đây");
const recentActivity=data.recent_activity||[];
if(!recentActivity.length)activity.append(el("p","Chưa có hoạt động gần đây."));
for(const item of recentActivity)activity.append(row(item.occurred_at,`${item.tool_name} — ${item.status}`));
  const actions=card("Thao tác nhanh");
  actions.append(button("Làm mới",()=>renderCurrent()),button("Mở allowlist",()=>navigate("access")),button("Mở QR",()=>navigate("system")),button("Mở hệ thống",()=>navigate("system")));
  const dashboard=el("div",undefined,"dashboard-grid");dashboard.append(bot,runtime,counts,activity,actions);
  body.append(stats,dashboard);frame.append(body);app.append(frame);
  return true;
}
async function loadQrWithRetry(image,attempts=[0,500,1000,2000,4000],token=state.renderVersion){
for(const delay of attempts){
if(!renderIsCurrent(token,"system")||image.isConnected===false)return false;
if(delay)await new Promise(resolve=>setTimeout(resolve,delay));
try{
const response=await fetch(`/admin/api/system/qr.png?t=${Date.now()}`,{credentials:"same-origin"});
if(response.status===401){expireSession();return false;}
if(!response.ok)continue;
const blob=await response.blob();
const nextUrl=URL.createObjectURL(blob);
if(!renderIsCurrent(token,"system")||image.isConnected===false){URL.revokeObjectURL(nextUrl);return false;}
releaseQrUrl();
state.qrUrl=nextUrl;image.src=nextUrl;image.alt="QR đăng nhập Zalo";return true;
}catch(error){if(error?.status===401)throw error;}
}
if(renderIsCurrent(token,"system")&&image.isConnected!==false){image.removeAttribute("src");image.alt="QR chưa sẵn sàng; thử lại sau";}
return false;
}
async function pollAfterRestart(target="gateway"){
const delays=[500,1000,2000,4000,8000];
for(const delay of delays){
await new Promise(resolve=>setTimeout(resolve,delay));
try{
if(target==="bridge"){
const data=await api("/admin/api/system");
if(data.bridge?.ok===true&&!data.bridge?.error){await navigate("system");return true;}
}else{
const data=await api("/admin/api/session");
state.csrf=data.csrf;await navigate("system");return true;
}
}catch(error){
if(error?.status===401){expireSession();return false;}
}
}
const label=target==="bridge"?"Bridge":"Gateway";
const hint=target==="bridge"?"systemctl restart hermes-zalo-company-bridge":"systemctl restart hermes-gateway";
document.querySelector("#app")?.append(el("p",`${label} chưa trở lại. Dùng SSH/CLI: ${hint}`,"error"));
return false;
}
function historyQuery(filters,limit,offset){const params=new URLSearchParams();for(const [key,value] of Object.entries(filters)){if(value)params.set(key,String(value));}params.set("limit",String(limit));params.set("offset",String(offset));return params.toString();}
function historyFilters(){const source=state.historyFilters||{};return {thread_type:source.thread_type||"",sender_id:source.sender_id||"",since:source.since||"",until:source.until||"",query:source.query||""};}
function miniTerminal(title,tone="neutral"){const root=el("section",undefined,`mini-terminal mini-${tone}`);const body=el("div",undefined,"mini-body");root.append(el("header",title,"mini-title"),body);return {root,body};}
async function renderConversationEnhanced(container,conversation,offset=0,onBack=undefined,viewToken=undefined){const requestVersion=(container.__conversationRequestVersion||0)+1;container.__conversationRequestVersion=requestVersion;const isCurrent=()=>container.__conversationRequestVersion===requestVersion&&(viewToken===undefined||renderIsCurrent(viewToken,"history"));const filters=historyFilters();const params=historyQuery({sender_id:filters.sender_id,since:filters.since,until:filters.until,query:filters.query},100,offset);const page=await api(`/admin/api/conversations/${conversation.id}?${params}`);if(!isCurrent())return false;container.replaceChildren();const heading=el("div",undefined,"conversation-heading");heading.append(el("h2",`${conversation.title??conversation.thread_id} (${conversation.thread_id})`));if(onBack)heading.append(button("Quay lại danh sách",onBack));container.append(heading);const messageList=el("div",undefined,"message-timeline");for(const message of page.items||[]){const item=el("article","",`card message-bubble ${message.is_bot?"message-bot":"message-user"}`);item.append(row("Người gửi",`${message.sender_name??message.sender_id} (${message.sender_id})`),row("Thời gian",message.sent_at),row("Nội dung",message.text));if(message.is_bot)item.append(badge("Bot","success"));if(message.mentioned_bot)item.append(badge("Mention bot","neutral"));if(message.recalled_at)item.append(badge("Đã thu hồi","warning"));for(const attachment of message.attachments||[]){const lineItem=el("p",`${attachment.filename??attachment.kind} — ${attachment.size_bytes??"—"} bytes — ${attachment.download_status??"unknown"}`);if(attachment.id){const link=el("a"," Tải file");link.href=`/admin/api/attachments/${encodeURIComponent(attachment.id)}`;lineItem.append(link);}item.append(lineItem);}messageList.append(item);}container.append(messageList);const pager=el("div");if(offset>0)pager.append(button("Tin mới hơn",()=>renderConversationEnhanced(container,conversation,Math.max(0,offset-100),onBack,viewToken)));if(page.next_offset!==null&&page.next_offset!==undefined)pager.append(button("Tin cũ hơn",()=>renderConversationEnhanced(container,conversation,page.next_offset,onBack,viewToken)));container.append(pager);const activity=await api(`/admin/api/activity?thread_type=${encodeURIComponent(conversation.thread_type)}&thread_id=${encodeURIComponent(conversation.thread_id)}&limit=20&offset=0`);if(!isCurrent())return false;const activityTerminal=miniTerminal("HOẠT ĐỘNG TOOL");for(const entry of activity.items||[])activityTerminal.body.append(row(entry.occurred_at,`${entry.tool_name} — ${entry.status}`));if(!(activity.items||[]).length)activityTerminal.body.append(el("p","Chưa có hoạt động."));container.append(activityTerminal.root);return true;}
async function renderHistoryEnhanced(token){
token=token??beginRender("history");
  const app=clearApp("Hội thoại");const {frame,body}=terminalFrame("HỘI THOẠI · COMPANY HISTORY");const controls=card("Bộ lọc hội thoại");const filters=historyFilters();
const type=document.createElement("select");type.name="thread_type";type.setAttribute("aria-label","Loại hội thoại");for(const option of [["","Tất cả"],["dm","Chat riêng"],["group","Nhóm"]]){const item=document.createElement("option");item.value=option[0];item.textContent=option[1];item.selected=filters.thread_type===option[0];type.append(item);}
const sender=document.createElement("input");sender.name="sender_id";sender.placeholder="sender_id";sender.setAttribute("aria-label","Zalo ID người gửi");sender.value=filters.sender_id;
const since=document.createElement("input");since.name="since";since.placeholder="since (ISO-8601)";since.setAttribute("aria-label","Từ thời điểm");since.value=filters.since;
const until=document.createElement("input");until.name="until";until.placeholder="until (ISO-8601)";until.setAttribute("aria-label","Đến thời điểm");until.value=filters.until;
const query=document.createElement("input");query.name="query";query.placeholder="Từ khóa nội dung hoặc thread ID";query.setAttribute("aria-label","Từ khóa lịch sử");query.value=filters.query;
const apply=button("Lọc",()=>{state.historyFilters={thread_type:type.value,sender_id:sender.value.trim(),since:since.value.trim(),until:until.value.trim(),query:query.value.trim()};void navigate("history");});
  const searchResults=el("section",undefined,"message-search-results");const searchButton=button("Tìm tin nhắn",async()=>{const result=await api(`/admin/api/history/search?query=${encodeURIComponent(query.value.trim())}`);searchResults.replaceChildren(el("h2","Kết quả tin nhắn"));if(!(result.items||[]).length)searchResults.append(el("p","Không có tin nhắn phù hợp."));for(const message of result.items||[])searchResults.append(row(`${message.sender_name??message.sender_id} (${message.sender_id})`,message.text));});
  controls.className="history-toolbar";controls.append(type,sender,since,until,query,apply,searchButton);const layout=el("div",undefined,"conversation-layout");const list=el("div",undefined,"conversation-list");const detail=el("section","Chọn một hội thoại để xem nội dung.","conversation-detail");layout.append(list,detail);body.append(controls,searchResults,layout);app.append(frame);
async function loadPage(offset=0){
const current=historyFilters();const result=await api(`/admin/api/conversations?${historyQuery(current,50,offset)}`);
if(!renderIsCurrent(token,"history"))return false;
list.replaceChildren();
if(!(result.items||[]).length)list.append(el("p","Chưa có hội thoại phù hợp."));
for(const conversation of result.items||[]){const item=card(`${conversation.title??conversation.thread_id} (${conversation.thread_id})`);item.append(row("Loại",conversation.thread_type),row("Tin nhắn",conversation.message_count),row("Tin gần nhất",conversation.last_message_at));const open=button("Mở hội thoại",()=>renderConversationEnhanced(detail,conversation,0,()=>{detail.__conversationRequestVersion=(detail.__conversationRequestVersion||0)+1;detail.replaceChildren(el("p","Chọn một hội thoại để xem nội dung."));},token));const remove=button("Xóa hội thoại",()=>confirmModal({title:"Xóa hội thoại",message:`Xóa lịch sử ${conversation.thread_id}. Không thể hoàn tác.`,confirmLabel:"Xóa hội thoại",tone:"danger",onConfirm:async()=>{await api("/admin/api/history/delete",{method:"POST",body:JSON.stringify({thread_type:conversation.thread_type,thread_id:conversation.thread_id,confirm:true})});await loadPage(offset);}}));item.append(open,remove);list.append(item);}
const pager=el("div");if(offset>0)pager.append(button("Trang trước",()=>loadPage(Math.max(0,offset-50))));if(result.next_offset!==null&&result.next_offset!==undefined)pager.append(button("Trang sau",()=>loadPage(result.next_offset)));list.append(pager);return true;
}
await loadPage(0);if(!renderIsCurrent(token,"history"))return false;
const actions=card("Dữ liệu");
actions.append(button("Xuất theo bộ lọc",()=>runAction(async()=>{const response=await fetch("/admin/api/history/export",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify(historyFilters())});if(response.status===401)throw Object.assign(new Error("Phiên đăng nhập đã hết hạn"),{status:401});if(!response.ok)throw new Error("Không thể xuất lịch sử");const blob=await response.blob();const link=document.createElement("a");const url=URL.createObjectURL(blob);link.href=url;link.download="history.jsonl";document.body.append(link);link.click();window.setTimeout(()=>{link.remove();URL.revokeObjectURL(url);},1000);showToast("Đã tạo file xuất lịch sử","success");},"Không thể xuất lịch sử",true)),button("Xóa theo bộ lọc",()=>confirmModal({title:"Xóa lịch sử theo bộ lọc",message:"Xóa toàn bộ phạm vi đang lọc. Không thể hoàn tác.",confirmLabel:"Xóa lịch sử",tone:"danger",onConfirm:async()=>{const deleted=await runAction(()=>api("/admin/api/history/delete",{method:"POST",body:JSON.stringify({...historyFilters(),confirm:true})}),"Không thể xóa lịch sử");if(deleted)await navigate("history");}})));
  body.append(actions);return true;
}
async function renderAccessEnhanced(token){
token=token??beginRender("access");
const access=await api("/admin/api/access");
let friends,groups,contactsStale=false;
try{[friends,groups]=await Promise.all([api("/admin/api/friends"),api("/admin/api/groups")]);}
catch(error){
if(error?.status===401||!state.accessSnapshot?.friends||!state.accessSnapshot?.groups)throw error;
friends=state.accessSnapshot.friends;groups=state.accessSnapshot.groups;contactsStale=true;
}
if(!renderIsCurrent(token,"access"))return false;
  state.accessSnapshot={access,friends,groups};
  if(!state.draft||!state.draft.fingerprint)state.draft={allowed_users:[...(access.allowed_users||[])],admin_users:[...(access.admin_users||[])],allowed_groups:[...(access.allowed_groups||[])],fingerprint:access.fingerprint};
  if(!state.savedAccess||state.savedAccess.fingerprint!==access.fingerprint)state.savedAccess={allowed_users:[...(access.allowed_users||[])],admin_users:[...(access.admin_users||[])],allowed_groups:[...(access.allowed_groups||[])],fingerprint:access.fingerprint};
  const app=clearApp("Danh bạ & Allowlist");
  const stale=staleNotice({stale:contactsStale||friends?.stale||groups?.stale,error:"Bridge tạm mất; đang hiển thị dữ liệu danh bạ gần nhất."});if(stale)app.append(stale);
const peopleRows=[];
const peopleItems=[...(friends?.items||[])];const seenPeople=new Set(peopleItems.map(entityId));
for(const id of new Set([...(state.draft.allowed_users||[]),...(state.draft.admin_users||[])]))if(id&&!seenPeople.has(String(id)))peopleItems.push({id:String(id),name:String(id),unlisted:true});
for(const person of peopleItems){
const id=entityId(person);if(!id)continue;const status=friendStatus(person);const member=checkbox("Thành viên",state.draft.allowed_users.includes(id),enabled=>{state.draft.allowed_users=setMember(state.draft.allowed_users,id,enabled);if(!enabled)state.draft.admin_users=setMember(state.draft.admin_users,id,false);refreshDraftBar();});const adminToggle=checkbox("Admin",state.draft.admin_users.includes(id),enabled=>{state.draft.admin_users=setMember(state.draft.admin_users,id,enabled);if(enabled)state.draft.allowed_users=setMember(state.draft.allowed_users,id,true);refreshDraftBar();});peopleRows.push([`${entityName(person)} (${id})`,id,person.unlisted?"Không còn trong danh bạ":(status||"—"),member,adminToggle]);
}
const people=dataTable("Cá nhân",["Tài khoản","Zalo ID","Trạng thái","Thành viên","Admin"],peopleRows);if(!peopleItems.length)people.append(el("p","Không có cá nhân nào."));
const userInput=document.createElement("input");userInput.placeholder="Nhập Zalo ID";userInput.setAttribute("aria-label","Thêm Zalo ID vào allowlist");people.append(userInput,button("Thêm thành viên",()=>{if(userInput.value.trim()){state.draft.allowed_users=setMember(state.draft.allowed_users,userInput.value.trim(),true);userInput.value="";refreshDraftBar();}}));
const groupRows=[];
const groupItems=[...(groups?.items||[])];const seenGroups=new Set(groupItems.map(entityId));
for(const id of state.draft.allowed_groups||[])if(id&&!seenGroups.has(String(id)))groupItems.push({id:String(id),name:String(id),unlisted:true});
for(const group of groupItems){
const id=entityId(group);if(!id)continue;const memberHost=el("div");const memberButton=button("Xem thành viên",async()=>{const requestVersion=++state.memberRequestVersion;const data=await api(`/admin/api/groups/${encodeURIComponent(id)}/members`);if(requestVersion!==state.memberRequestVersion||!renderIsCurrent(token,"access"))return;const list=el("ul");for(const member of data.items||[]){const lineItem=el("li");const memberId=entityId(member);const status=friendStatus(member);lineItem.append(document.createTextNode(`${entityName(member)} (${memberId}) `),checkbox("Được phép",state.draft.allowed_users.includes(memberId),enabled=>{state.draft.allowed_users=setMember(state.draft.allowed_users,memberId,enabled);if(!enabled)state.draft.admin_users=setMember(state.draft.admin_users,memberId,false);refreshDraftBar();}));if(status)lineItem.append(document.createTextNode(` — ${status}`));list.append(lineItem);}memberHost.replaceChildren(list);});const allow=checkbox("Cho phép",state.draft.allowed_groups.includes(id),enabled=>{state.draft.allowed_groups=setMember(state.draft.allowed_groups,id,enabled);refreshDraftBar();});const memberCell=el("div");memberCell.append(memberButton,memberHost);groupRows.push([entityName(group),id,group.unlisted?"Không còn trong danh sách nhóm":`${group.memberCount??"?"} thành viên`,allow,memberCell]);
}
const groupCard=dataTable("Nhóm công ty",["Nhóm","Group ID","Thành viên","Cho phép","Chi tiết"],groupRows);if(!groupItems.length)groupCard.append(el("p","Không có nhóm nào."));
const groupInput=document.createElement("input");groupInput.placeholder="Nhập Group ID";groupInput.setAttribute("aria-label","Thêm Group ID vào allowlist");groupCard.append(groupInput,button("Thêm nhóm",()=>{if(groupInput.value.trim()){state.draft.allowed_groups=setMember(state.draft.allowed_groups,groupInput.value.trim(),true);groupInput.value="";refreshDraftBar();}}));
  const actions=card();const conflict=el("div");
const reload=button("Tải lại cấu hình",()=>{state.draft=null;return navigate("access");});
const save=button("Lưu và áp dụng",async()=>{
save.disabled=true;for(const control of app.querySelectorAll?.("input,button")||[])control.disabled=true;
try{
const submitted=JSON.parse(JSON.stringify(state.draft));
const saved=await api("/admin/api/access/apply",{method:"POST",body:JSON.stringify(submitted)});
state.draft={...saved.config,fingerprint:saved.fingerprint};state.accessSnapshot.access={...saved.config,fingerprint:saved.fingerprint};await navigate("access");
}catch(error){
save.disabled=false;for(const control of app.querySelectorAll?.("input,button")||[])control.disabled=false;
if(error.status!==409)throw error;conflict.replaceChildren(el("p",error.message||"Cấu hình đã thay đổi; tải lại cấu hình hiện tại.","error"));
}
});
  const draftHost=el("div");
  function refreshDraftBar(){renderDraftBar(draftHost,()=>save.click(),()=>reload.click());}
  actions.append(save,reload,conflict);app.append(people,groupCard,actions,draftHost);refreshDraftBar();
  return true;
}
async function renderSystemEnhanced(token){
token=token??beginRender("system");
const data=await api("/admin/api/system");
if(!renderIsCurrent(token,"system"))return false;
const app=clearApp("Hệ thống & Hoạt động");const {frame,body}=terminalFrame("HỆ THỐNG · LIVE OPERATIONS");
const lastError=data.bridge?.error||data.bridge?.lastError||data.bridge_error||"";
const statusTerminal=miniTerminal("RUNTIME STATUS","success");const status=statusTerminal.body;
const zaloState=data.bridge?.loggedIn===true?"Đã đăng nhập":(data.bridge?.loggedIn===false?"Chưa đăng nhập":"Không rõ");
const bridgeState=lastError||(data.bridge?.ok===true?"Hoạt động":(data.bridge?.ok===false?"Không kết nối":"Không rõ"));
const gatewayState=data.gateway?.status??data.gateway_status??((data.adapter_active===true||data.connected===true)?"Hoạt động":((data.adapter_active===false||data.connected===false)?"Không hoạt động":"Không rõ"));
status.append(row("Họ tên",data.bot?.name),row("Zalo ID",data.bot?.id),row("Zalo",zaloState),row("Bridge",bridgeState),row("Hermes Gateway",gatewayState),row("Provider",data.provider),row("Model",data.model),row("QR",data.qr?.status),row("SSE client",data.bridge?.sseClients??data.sse_clients??"—"),row("Lỗi gần nhất",lastError||"Không có"));
const qr=document.createElement("img");qr.alt="QR đăng nhập Zalo";qr.width=220;
const qrTerminal=miniTerminal("QR LOGIN & ĐIỀU KHIỂN");const actions=qrTerminal.body;
 actions.append(button("Tạo QR mới",()=>runAction(async()=>{await api("/admin/api/system/qr",{method:"POST",body:"{}"});await loadQrWithRetry(qr,[0,500,1000,2000,4000],token);},"Không thể tạo QR mới",true)),button("Reconnect Zalo",()=>runAction(async()=>{await api("/admin/api/system/reconnect",{method:"POST",body:"{}"});await loadQrWithRetry(qr,[0,500,1000,2000,4000],token);},"Không thể kết nối lại Zalo",true)));
if(lastError)actions.append(button("Sao chép lỗi",()=>navigator.clipboard.writeText(lastError)));
actions.append(qr);body.append(statusTerminal.root,qrTerminal.root);void loadQrWithRetry(qr,[0,500,1000,2000,4000],token);
const logs=await api("/admin/api/system/logs?lines=50");
if(!renderIsCurrent(token,"system"))return false;
const logTerminal=miniTerminal("LIVE LOG");const logCard=logTerminal.body;if((logs.lines||[]).length)logCard.append(el("pre",logs.lines.join("\\n")));else logCard.append(el("p","Chưa có log."));body.append(logTerminal.root);
const savedFilters=state.activityFilters||{};const activityControls=card("Bộ lọc hoạt động");const activityInputs={};
for(const [name,placeholder] of [["requester_id","requester_id"],["tool_name","tool_name"],["status","status"],["thread_type","thread_type"],["thread_id","thread_id"],["since","since (ISO-8601)"],["until","until (ISO-8601)"]]){const input=document.createElement("input");input.name=name;input.placeholder=placeholder;input.value=savedFilters[name]||"";activityInputs[name]=input;activityControls.append(input);}
const activityTerminal=miniTerminal("ACTIVITY");const activityCard=activityTerminal.body;let activityRequestVersion=0;
async function loadActivity(offset=0){const requestVersion=++activityRequestVersion;const filters={};for(const [name,input] of Object.entries(activityInputs))filters[name]=input.value.trim();const activity=await api(`/admin/api/activity?${historyQuery(filters,50,offset)}`);if(!renderIsCurrent(token,"system")||requestVersion!==activityRequestVersion)return false;activityCard.replaceChildren(el("h2","Hoạt động"));if(!(activity.items||[]).length)activityCard.append(el("p","Chưa có hoạt động."));for(const item of activity.items||[])activityCard.append(row(item.occurred_at,`${item.tool_name} — ${item.status}`));const pager=el("div");if(offset>0)pager.append(button("Trang trước hoạt động",()=>loadActivity(Math.max(0,offset-50))));if(activity.next_offset!==null&&activity.next_offset!==undefined)pager.append(button("Trang sau hoạt động",()=>loadActivity(activity.next_offset)));activityCard.append(pager);return true;}
activityControls.append(button("Lọc hoạt động",()=>{state.activityFilters=Object.fromEntries(Object.entries(activityInputs).map(([name,input])=>[name,input.value.trim()]));return loadActivity(0);}));body.append(activityControls,activityTerminal.root);const dangerTerminal=miniTerminal("DANGER ZONE","danger");const danger=dangerTerminal.body;const pending=state.pendingOperation?` Đang chờ: ${state.pendingOperation}.`:"";danger.append(el("p","Restart Bridge hoặc Gateway sẽ tạm gián đoạn kết nối. Hệ thống không tự gửi lại lệnh."+pending,"error"),button("Restart Bridge",()=>restartConfirmation("bridge"),"danger"),button("Restart Gateway",()=>restartConfirmation("gateway"),"danger"));body.append(dangerTerminal.root);app.append(frame);await loadActivity(0);return true;
}
async function renderCurrent(){const view=state.view;updateNavigation();const token=++state.renderVersion;showLoading(view);try{if(view==="overview")await renderOverviewEnhanced(token);else if(view==="access")await renderAccessEnhanced(token);else if(view==="history")await renderHistoryEnhanced(token);else await renderSystemEnhanced(token);}catch(error){if(!renderIsCurrent(token,view))return;if(error.status===401){expireSession();return;}if(error.status===409){const app=clearApp("Xung đột cấu hình");app.append(row("Chi tiết",error.message),button("Tải lại cấu hình",()=>{state.draft=null;return navigate("access");}));return;}showViewError(error,renderCurrent);}}
async function handleLogin(event){event.preventDefault();try{const data=await api("/admin/api/login",{method:"POST",body:JSON.stringify({password:document.querySelector("#password").value})});state.csrf=data.csrf;showApp();await renderCurrent();}catch(error){document.querySelector("#login-error").textContent=error.message;}}
async function handleLogout(){await api("/admin/api/logout",{method:"POST",body:"{}"});releaseQrUrl();location.reload();}

const THEME_KEY="hz-admin-theme-v1";
const SIDEBAR_KEY="hz-admin-sidebar-v1";
const THEMES=new Set(["system","dark","light"]);
const SIDEBARS=new Set(["expanded","collapsed"]);
function storedChoice(key,allowed,fallback){const value=localStorage.getItem(key);return allowed.has(value)?value:fallback;}
function updateThemeLabel(theme){for(const selector of ["#theme-toggle","#login-theme-toggle"]){const control=document.querySelector(selector);if(control)control.setAttribute("aria-label",`Giao diện hiện tại: ${theme}; bấm để đổi`);}}
function updateSidebarLabel(sidebar){const control=document.querySelector("#sidebar-toggle");if(control)control.setAttribute("aria-label",sidebar==="collapsed"?"Mở rộng thanh điều hướng":"Thu gọn thanh điều hướng");}
function setTheme(value){const theme=THEMES.has(value)?value:"system";document.documentElement.dataset.theme=theme;localStorage.setItem(THEME_KEY,theme);updateThemeLabel(theme);}
function setSidebar(value){const sidebar=SIDEBARS.has(value)?value:"expanded";document.documentElement.dataset.sidebar=sidebar;localStorage.setItem(SIDEBAR_KEY,sidebar);updateSidebarLabel(sidebar);}
function applyInitialPreferences(){const theme=storedChoice(THEME_KEY,THEMES,"system");const sidebar=storedChoice(SIDEBAR_KEY,SIDEBARS,"expanded");document.documentElement.dataset.theme=theme;document.documentElement.dataset.sidebar=sidebar;updateThemeLabel(theme);updateSidebarLabel(sidebar);}
function nextTheme(){const current=document.documentElement.dataset.theme||"system";const themes=["system","dark","light"];setTheme(themes[(themes.indexOf(current)+1)%themes.length]);}
function toggleSidebar(){setSidebar((document.documentElement.dataset.sidebar||"expanded")==="expanded"?"collapsed":"expanded");}
function updateNavigation(){for(const item of document.querySelectorAll("[data-view]")){const active=item.dataset.view===state.view;item.setAttribute("aria-current",active?"page":"false");}}
function accessShape(value){return {allowed_users:[...(value?.allowed_users||[])].map(String).sort(),admin_users:[...(value?.admin_users||[])].map(String).sort(),allowed_groups:[...(value?.allowed_groups||[])].map(String).sort()};}
function hasUnsavedAccessChanges(){return JSON.stringify(accessShape(state.draft))!==JSON.stringify(accessShape(state.savedAccess));}
function handleBeforeUnload(event){if(!hasUnsavedAccessChanges())return;event.preventDefault();event.returnValue="";}
function staleNotice(data){if(!data?.stale)return null;const root=el("div",undefined,"stale-notice");root.append(badge("Dữ liệu cũ","warning"),el("span",data.error||"Bridge không sẵn sàng"));return root;}
function draftBar(onSave,onReload){const bar=el("aside",undefined,"draft-bar");bar.append(el("span","Có thay đổi chưa áp dụng"),button("Tải lại",onReload),button("Lưu và áp dụng",onSave,"primary"));return bar;}
function renderDraftBar(host,onSave,onReload){host.replaceChildren();if(hasUnsavedAccessChanges())host.append(draftBar(onSave,onReload));}
async function guardedNavigate(view){if(state.view==="access"&&view!=="access"&&hasUnsavedAccessChanges()&&!window.confirm("Bỏ các thay đổi allowlist chưa lưu?"))return false;return navigate(view);}
function confirmModal(options){const previous=document.activeElement;const dialog=el("section",undefined,"modal modal-"+(options.tone||"neutral"));dialog.setAttribute("role","dialog");dialog.setAttribute("aria-modal","true");dialog.tabIndex=-1;const cancelButton=button("Hủy",cancel);const confirmButton=button(options.confirmLabel,confirm,options.tone==="danger"?"danger":"primary");dialog.append(el("h2",options.title),el("p",options.message),cancelButton,confirmButton);const root=document.querySelector("#modal-root");root.replaceChildren(dialog);const onKeyDown=event=>{if(event.key==="Escape"){event.preventDefault();cancel();return;}if(event.key!=="Tab")return;if(event.shiftKey&&event.target===cancelButton){event.preventDefault();confirmButton.focus?.();}else if(!event.shiftKey&&event.target===confirmButton){event.preventDefault();cancelButton.focus?.();}};document.addEventListener("keydown",onKeyDown);cancelButton.focus?.();function close(){document.removeEventListener("keydown",onKeyDown);root.replaceChildren();previous?.focus?.();}function cancel(){close();}async function confirm(){confirmButton.disabled=true;try{await (options.onConfirm||(async()=>{}))();close();}finally{confirmButton.disabled=false;}}return {dialog,cancel,confirm};}
function showToast(message,tone="neutral"){const root=document.querySelector("#toast-root");const toast=el("div",message,"toast toast-"+tone);root.replaceChildren(toast);window.setTimeout(()=>{if(root.children?.[0]===toast)root.replaceChildren();},4000);}
async function runAction(action,fallback,preferFallback=false){try{await action();return true;}catch(error){if(error?.status===401){expireSession();return false;}showToast(preferFallback?fallback:(error?.message||fallback),"danger");return false;}}
function restartConfirmation(target){const modal=confirmModal({title:`Restart ${target}`,message:`Kết nối ${target} sẽ tạm gián đoạn. Hệ thống không tự gửi lại lệnh.`,confirmLabel:`Restart ${target}`,tone:"danger",onConfirm:async()=>{state.pendingOperation=`restart:${target}`;await api("/admin/api/system/restart",{method:"POST",body:JSON.stringify({target})});await pollAfterRestart(target);}});return {cancel:modal.cancel,confirm:modal.confirm};}
function releaseQrUrl(){if(state.qrUrl){URL.revokeObjectURL(state.qrUrl);state.qrUrl=null;}}
function expireSession(){releaseQrUrl();state.renderVersion+=1;state.memberRequestVersion+=1;state.csrf=null;state.draft=null;state.savedAccess=null;state.accessSnapshot=null;state.historyFilters=null;state.activityFilters=null;state.pendingOperation=null;document.querySelector("#modal-root")?.replaceChildren();document.querySelector("#toast-root")?.replaceChildren();const password=document.querySelector("#password");if(password)password.value="";showLogin("Phiên đã hết hạn, vui lòng đăng nhập lại");}
function skeleton(count=4){const root=el("div",undefined,"skeleton-grid");for(let index=0;index<count;index+=1)root.append(el("span",undefined,"skeleton"));return root;}
function emptyState(title,message,action){const root=el("section",undefined,"empty-state");root.append(el("h2",title),el("p",message));if(action)root.append(action);return root;}
function showViewError(error,retry){const app=clearApp("Có lỗi");const panel=el("section",undefined,"error-panel");panel.append(el("h2","Không thể tải dữ liệu"),el("p",error.message||"Yêu cầu thất bại"),button("Thử lại",retry));app.append(panel);}
function showLoading(view){const app=clearApp(VIEW_TITLES[view]||"Đang tải");app.append(el("p","Đang tải…","loading-label"),skeleton(view==="overview"?4:6));}

// BOOTSTRAP
applyInitialPreferences();
document.querySelector("#login").addEventListener("submit",handleLogin);
document.querySelector("#logout").addEventListener("click",handleLogout);
document.querySelector("#theme-toggle").addEventListener("click",nextTheme);
document.querySelector("#login-theme-toggle").addEventListener("click",nextTheme);
document.querySelector("#sidebar-toggle").addEventListener("click",toggleSidebar);
for(const item of document.querySelectorAll("[data-view]"))item.addEventListener("click",()=>guardedNavigate(item.dataset.view));
window.addEventListener("beforeunload",handleBeforeUnload);
window.addEventListener("pagehide",releaseQrUrl);
api("/admin/api/session").then(data=>{state.csrf=data.csrf;showApp();return renderCurrent();}).catch(()=>showLogin());
