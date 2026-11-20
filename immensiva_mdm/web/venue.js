document.addEventListener('DOMContentLoaded',()=>{
 const id=n=>document.getElementById(n),command=n=>document.querySelector(`[data-cmd="${n}"]`);
 let state={devices:[],selected:[],groups:{}},task='launch',pending=null,bypass=false;
 let recordingAvailable=false,recordingBusy=false;
 const recordingStates=new Map();
 let recordingLoading=0,recordingRevision=0;
 let browserAvailable=false,browserBusy=false;
 const deviceId=d=>d.device_id||d.serial_number||'',online=d=>d.status==='online';
 const commands={launch:['launch'],install:['install'],files:['push'],browser:[],recording:[],maintenance:['updateClient','sync','uninstall','startup','verifyApk','verifyDir','power','retire']};
 const hints={launch:'Choose an app, check your headsets, then open it.',install:'Choose the app file (.apk) supplied by your technician.',files:'Copy files to the selected headsets. Files with the same name are replaced.',browser:'Open a website in the selected headsets’ browsers.',recording:'Control the built-in PICO recorders on the selected headsets.',maintenance:'For trained staff. Updates, deletion and power controls can interrupt a session.'};
 function showTask(name){task=name;document.body.dataset.operatorTask=name;
 document.querySelectorAll('[data-task]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.task===name)));
 document.querySelectorAll('[data-cmd]').forEach(s=>{s.hidden=!commands[name].includes(s.dataset.cmd);});
 id('operatorTaskHelp').textContent=hints[name];id('operatorAppPicker').hidden=name!=='launch';
 id('operatorRecording').hidden=name!=='recording';
 id('operatorBrowser').hidden=name!=='browser';
 if(name!=='maintenance'&&commands[name].length)command(commands[name][0]).classList.remove('collapsed');
 id('stepAction').querySelector('strong').textContent={launch:'Open',install:'Install',files:'Send',browser:'Browse',recording:'Record',maintenance:'Maintain'}[name];queueMicrotask(refresh);}
 document.querySelectorAll('[data-task]').forEach(b=>b.addEventListener('click',()=>showTask(b.dataset.task)));
 id('venueDevices').addEventListener('click',()=>id('tabDevices').click());
 id('venueRooms').addEventListener('click',()=>id('btnManageGroups').click());
 function useJeru(){document.body.dataset.customApp='false';showTask('launch');id('operatorApp').value='com.fifthyang.lordlyrical.offline';id('launchPkg').value=id('operatorApp').value;id('launchPkg').dispatchEvent(new Event('input',{bubbles:true}));}
 id('venueJeru').addEventListener('click',useJeru);
 id('operatorApp').addEventListener('change',()=>{document.body.dataset.customApp=String(!id('operatorApp').value);id('launchPkg').value=id('operatorApp').value;id('launchPkg').dispatchEvent(new Event('input',{bubbles:true}));if(!id('operatorApp').value)id('launchPkg').focus();});
 id('stepConnect').addEventListener('click',()=>{id('connectionHelp').open=!id('connectionHelp').open;});
 id('stepSelect').addEventListener('click',()=>{id('tabDevices').click();id('devSearch').focus();});
 id('stepAction').addEventListener('click',()=>(task==='recording'?id('operatorRecording'):task==='browser'?id('operatorBrowser'):command(commands[task][0])).scrollIntoView({block:'nearest',behavior:'smooth'}));
 if(!['127.0.0.1','localhost','::1'].includes(location.hostname))id('venueShow').hidden=true;
 const labels={launchPkg:'Android app package',launchExtra:'Optional app launch parameters',apkFile:'Android app file (.apk)',pushDest:'Destination folder on headsets',devSearch:'Find a headset'};
 Object.entries(labels).forEach(([key,label])=>id(key)?.setAttribute('aria-label',label));
 const label=document.createElement('label');label.htmlFor='launchPkg';label.className='input-label';label.textContent='Android app package';command('launch').querySelector('.cmd-body').prepend(label);
 const note=document.createElement('p');note.className='operator-inline-note';note.textContent='The app must already be installed. Ask your technician for the package name of another app.';id('launchPkg').after(note);
 const advanced=document.createElement('details');advanced.className='launch-advanced';const summary=document.createElement('summary');summary.textContent='Advanced app parameters';advanced.append(summary,id('launchExtra'));id('btnLaunch').before(advanced);
 id('launchPkg').addEventListener('input',()=>{
  const pkg=id('launchPkg').value, picker=id('operatorApp');
  const preset=Boolean(pkg)&&Array.from(picker.options).some(option=>option.value===pkg);
  picker.value=preset?pkg:'';
  document.body.dataset.customApp=String(!preset);
 });
 document.querySelectorAll('.cmd-head').forEach(head=>{head.setAttribute('role','button');head.tabIndex=0;head.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();head.click();}});});
 const expanded=()=>document.querySelectorAll('.cmd-head').forEach(head=>head.setAttribute('aria-expanded',String(!head.parentElement.classList.contains('collapsed'))));
 new MutationObserver(expanded).observe(document.querySelector('.commands'),{subtree:true,attributes:true,attributeFilter:['class']});expanded();
 function refresh(){
 const live=state.devices.filter(online),off=state.devices.length-live.length,low=live.filter(d=>d.battery&&Number.isFinite(d.battery.level)&&d.battery.level<20);
 const connected=id('connText').textContent==='Connected';
 id('fleetOnline').textContent=connected?live.length:'—';id('fleetOffline').textContent=connected?off:'—';id('fleetBattery').textContent=connected?low.length:'—';id('fleetSelected').textContent=state.selected.length;
 if(!connected||!state.devices.some(d=>online(d)&&state.selected.includes(deviceId(d))))['btnLaunch','btnInstall','btnPush'].forEach(n=>{id(n).disabled=true;});
 id('fleetHeadline').textContent=!connected?'Console disconnected':!state.devices.length?'Connect your first headset':live.length+' headset'+(live.length===1?'':'s')+' online';
 id('fleetHint').textContent=!connected?'Controls are unavailable until the server reconnects.':!state.devices.length?'Open STYLY-MDM Client in the headset. Use the connection checklist below.':low.length?'Charge low-battery headsets before the next session.':off?'Wake offline headsets and check their connection.':'Choose the headsets for your next action.';
 const selected=state.devices.filter(d=>state.selected.includes(deviceId(d))),names=selected.map(d=>d.label||deviceId(d)),ready=selected.filter(online).length;
 const recordTargets=connected?selected.filter(online):[],recordIds=new Set(recordTargets.map(deviceId));
 for(const key of recordingStates.keys())if(!recordIds.has(key))recordingStates.delete(key);
 for(const key of recordIds)if(!recordingStates.has(key))recordingStates.set(key,{state:'unknown',checked:0,attempted:0,loading:false,error:''});
 const observed=recordTargets.map(d=>{
 const entry=recordingStates.get(deviceId(d)),current=Date.now()-entry.checked<10000?entry.state:'unknown';
 return {current,text:(d.label||deviceId(d))+' · '+(current==='recording'?'Recording active':current==='stopped'?'Recording stopped':entry.error||'Checking recording state…')};
 });
 const recordReady=recordingAvailable&&!recordingBusy;
 id('btnRecordStart').disabled=!recordReady||!observed.some(item=>item.current==='stopped');
 id('btnRecordStop').disabled=!recordReady||!observed.some(item=>item.current==='recording');
 id('recordingState').textContent=!recordTargets.length?'Select one or more online PICO headsets to check recording state.':observed.map(item=>item.text).join('\n');
 queueMicrotask(checkRecordingStates);
 id('btnOpenUrl').disabled=!connected||!browserAvailable||browserBusy||ready===0;
 id('btnOpenUrl').textContent=browserBusy?'Opening URL…':ready>1?`Open URL on ${ready} headsets`:'Open URL on headset';
 id('operatorUrl').disabled=browserBusy;
 id('operatorSelection').textContent=selected.length?`${ready} online selected · ${names.slice(0,3).join(', ')}${names.length>3?' + '+(names.length-3)+' more':''}${ready<selected.length?' · '+(selected.length-ready)+' offline will be skipped':''}`:'Select a room or headset on the left.';
 id('stepConnect').classList.toggle('step-complete',live.length>0);id('stepSelect').classList.toggle('step-complete',ready>0);
 document.querySelectorAll('#targetsBody .selbox').forEach(box=>{box.tabIndex=0;box.setAttribute('role','checkbox');box.setAttribute('aria-checked',String(box.classList.contains('on')));const d=state.devices.find(d=>deviceId(d)===box.dataset.id);box.setAttribute('aria-label',d?'Select headset '+(d.label||deviceId(d)):'Select visible headsets');});
 document.querySelectorAll('[data-row-id]').forEach(row=>{const d=state.devices.find(d=>deviceId(d)===row.dataset.rowId);const sub=row.querySelector('.dev-sub');if(d&&sub)sub.textContent=[deviceId(d),d.model,d.ip].filter(Boolean).join(' · ');});
 const empty=id('targetsBody').querySelector('.empty');
 if(empty&&!state.devices.length&&!empty.querySelector('a')){empty.replaceChildren();const title=document.createElement('strong');title.textContent='No headsets connected yet';const p=document.createElement('p');p.textContent='Open the MDM client in each headset, then connect it to this PC.';const a=document.createElement('a');a.href='/guide#connect';a.textContent='Connection quick start ↗';empty.append(title,p,a);}
 }
 id('targetsBody').addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.classList.contains('selbox')){e.preventDefault();e.target.click();}});
 document.addEventListener('venue:state',e=>{state=e.detail;queueMicrotask(refresh);});
 document.querySelector('.actions').addEventListener('input',()=>queueMicrotask(refresh));
 id('devSearch').addEventListener('input',()=>queueMicrotask(refresh));
 id('devStatusFilter').addEventListener('click',()=>queueMicrotask(refresh));
 new MutationObserver(refresh).observe(id('connText'),{childList:true,subtree:true,characterData:true});
 fetch('/api/open-url').then(response=>{if(!response.ok)throw new Error();return response.json();}).then(result=>{
 browserAvailable=result.available;id('browserResult').textContent=result.available?'Wireless ADB must be enabled and authorized.':'Browser controls need the ADB tools on this PC. Ask your technician to add them.';refresh();
 }).catch(()=>{id('browserResult').textContent='Could not check browser controls. Reload the page to try again.';});
 id('operatorUrl').addEventListener('input',()=>id('operatorUrl').setCustomValidity(''));
 id('operatorBrowser').addEventListener('submit',async event=>{
 event.preventDefault();if(id('btnOpenUrl').disabled||browserBusy)return;
 const url=id('operatorUrl').value.trim();
 if(!/^https?:\/\//i.test(url)){id('operatorUrl').setCustomValidity('Enter an http:// or https:// URL.');id('operatorUrl').reportValidity();return;}
 const selected=state.devices.filter(d=>state.selected.includes(deviceId(d)));
 const targets=selected.filter(online).map(d=>({device_id:deviceId(d),name:d.label||deviceId(d)}));
 if(!targets.length||id('connText').textContent!=='Connected')return;
 const skipped=selected.length-targets.length,results=targets.map(()=>null);
 let next=0;
 function showResults(){
 const completed=results.filter(Boolean),sent=completed.filter(result=>result.ok).length;
 const summary=completed.length===targets.length?`URL requests complete · ${sent} sent · ${completed.length-sent} failed`:`Opening browsers · ${completed.length}/${targets.length} complete`;
 id('browserResult').textContent=summary+(skipped?` · ${skipped} offline skipped`:'')+'\n'+targets.map((target,index)=>target.name+' · '+(results[index]?.message||'Waiting…')).join('\n');
 }
 async function openNext(){
 while(next<targets.length){
 const index=next++,target=targets[index];
 try{
 const response=await fetch('/api/open-url',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({device_id:target.device_id,url})});
 const result=await response.json();if(!response.ok)throw new Error(result.error||'Browser request failed.');
 results[index]={ok:true,message:result.message};
 }catch(error){results[index]={ok:false,message:error.message};}
 showResults();
 }
 }
 browserBusy=true;refresh();showResults();
 try{await Promise.all(Array.from({length:Math.min(4,targets.length)},openNext));}
 finally{browserBusy=false;refresh();}
 });
 fetch('/api/screen-recording').then(response=>{if(!response.ok)throw new Error();return response.json();}).then(result=>{
 recordingAvailable=result.available;id('recordingResult').textContent=result.available?'Wireless ADB must be enabled and authorized.':'Recording tools are not installed on this PC. See the screen recording setup guide.';refresh();
 }).catch(()=>{id('recordingResult').textContent='Could not check recording tools. Reload the page to try again.';});
 function checkRecordingStates(){
 if(task!=='recording'||document.hidden||!recordingAvailable||recordingBusy||id('connText').textContent!=='Connected')return;
 for(const [target,entry] of [...recordingStates].sort((a,b)=>a[1].attempted-b[1].attempted)){
 if(recordingLoading>=4)break;
 if(!entry.loading&&Date.now()-entry.attempted>=5000)checkRecordingState(target,entry);
 }
 }
 async function checkRecordingState(target,entry){
 const revision=recordingRevision;recordingLoading++;entry.loading=true;entry.attempted=Date.now();
 try{
 const response=await fetch('/api/screen-recording?device_id='+encodeURIComponent(target),{cache:'no-store'});
 const result=await response.json();if(!response.ok)throw new Error(result.error||'Recording state unavailable.');
 if(!['recording','stopped'].includes(result.state))throw new Error('Recording state unavailable.');
 if(recordingStates.get(target)===entry&&revision===recordingRevision){entry.state=result.state;entry.error='';entry.checked=Date.now();}
 }catch(error){if(recordingStates.get(target)===entry&&revision===recordingRevision){entry.state='unknown';entry.error=error.message;entry.checked=0;}}
 finally{recordingLoading--;entry.loading=false;refresh();}
 }
 setInterval(()=>{if(task==='recording')refresh();},1500);
 async function setRecording(action){
 if(id(action==='start'?'btnRecordStart':'btnRecordStop').disabled||recordingBusy)return;
 const selected=state.devices.filter(d=>state.selected.includes(deviceId(d)));
 const targets=selected.filter(online).map(d=>({device_id:deviceId(d),name:d.label||deviceId(d)}));
 if(!targets.length||id('connText').textContent!=='Connected')return;
 const skipped=selected.length-targets.length,results=targets.map(()=>null),expected=action==='start'?'recording':'stopped';
 let next=0;
 function showResults(){
 const completed=results.filter(Boolean),confirmed=completed.filter(result=>result.ok).length;
 const summary=completed.length===targets.length?`${action==='start'?'Start':'Stop'} complete · ${confirmed} confirmed · ${completed.length-confirmed} failed`:`${action==='start'?'Starting':'Stopping'} recording · ${completed.length}/${targets.length} complete`;
 id('recordingResult').textContent=summary+(skipped?` · ${skipped} offline skipped`:'')+'\n'+targets.map((target,index)=>target.name+' · '+(results[index]?.message||'Waiting…')).join('\n');
 }
 async function recordNext(){
 while(next<targets.length){
 const index=next++,target=targets[index];
 try{
 const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);const requestId=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
 const response=await fetch('/api/screen-recording',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({device_id:target.device_id,action,request_id:requestId})});
 const result=await response.json();if(!response.ok)throw new Error(result.error||'Recording request failed.');
 if(result.status!=='confirmed'||result.state!==expected)throw new Error('Recording state was not confirmed. Check the headset before retrying.');
 results[index]={ok:true,message:result.message};
 if(recordingStates.has(target.device_id))recordingStates.set(target.device_id,{state:result.state,checked:Date.now(),attempted:Date.now(),loading:false,error:''});
 }catch(error){
 results[index]={ok:false,message:error.message};
 if(recordingStates.has(target.device_id))recordingStates.set(target.device_id,{state:'unknown',checked:0,attempted:Date.now(),loading:false,error:error.message});
 }
 showResults();
 }
 }
 recordingBusy=true;recordingRevision++;refresh();showResults();
 try{await Promise.all(Array.from({length:Math.min(4,targets.length)},recordNext));}
 finally{recordingBusy=false;refresh();}
 }
 id('btnRecordStart').addEventListener('click',()=>setRecording('start'));
 id('btnRecordStop').addEventListener('click',()=>setRecording('stop'));
 const dialog=id('operatorConfirm');function cancel(){pending=null;dialog.close();}
 id('operatorCancel').addEventListener('click',cancel);dialog.addEventListener('cancel',()=>{pending=null;});
 id('operatorSend').addEventListener('click',()=>{
 const selected=state.devices.filter(d=>state.selected.includes(deviceId(d))&&online(d));
 if(!pending||pending.disabled||id('connText').textContent!=='Connected'||!selected.length||JSON.stringify(selected.map(deviceId))!==dialog.dataset.targets){cancel();return;}
 const button=pending;pending=null;dialog.close();bypass=true;try{button.click();}finally{bypass=false;}
 });
 ['btnLaunch','btnInstall','btnPush'].forEach(key=>id(key).addEventListener('click',e=>{
 if(bypass)return;e.preventDefault();e.stopImmediatePropagation();
 const selected=state.devices.filter(d=>state.selected.includes(deviceId(d))&&online(d));if(!selected.length||id('connText').textContent!=='Connected')return;
 id('operatorConfirmTitle').textContent={btnLaunch:'Open app',btnInstall:'Install app',btnPush:'Send files'}[key]+' on '+selected.length+' headset'+(selected.length===1?'?':'s?');
 id('operatorConfirmApp').textContent=key==='btnLaunch'?id('launchPkg').value:key==='btnInstall'?id('apkName').textContent:id('pushDest').value;
 id('operatorConfirmTargets').replaceChildren(...selected.map(d=>{const p=document.createElement('p');p.textContent=d.label||deviceId(d);return p;}));
 const skipped=state.selected.length-selected.length;id('operatorConfirmNote').textContent=skipped?skipped+' offline headset(s) will be skipped.':'Only the headsets listed above will receive this command.';
 id('operatorSend').textContent='Confirm and '+{btnLaunch:'open',btnInstall:'install',btnPush:'send'}[key];pending=id(key);dialog.dataset.targets=JSON.stringify(selected.map(deviceId));dialog.showModal();
 },true));
 useJeru();id('tabDevices').click();refresh();
});
