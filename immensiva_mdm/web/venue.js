document.addEventListener('DOMContentLoaded',()=>{
 const id=n=>document.getElementById(n);
 id('venueDevices').addEventListener('click',()=>id('tabDevices').click());
 id('venueRooms').addEventListener('click',()=>id('btnManageGroups').click());
 id('venueJeru').addEventListener('click',()=>{
   const section=document.querySelector('[data-cmd="launch"]');section.classList.remove('collapsed');
   id('launchPkg').value='com.fifthyang.lordlyrical';id('launchPkg').dispatchEvent(new Event('input',{bubbles:true}));
   section.scrollIntoView({block:'nearest',behavior:'smooth'});id('launchPkg').focus();
 });
 if(!['127.0.0.1','localhost','::1'].includes(location.hostname))id('venueShow').hidden=true;
});
