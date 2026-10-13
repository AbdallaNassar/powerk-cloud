const ICON={
 plug:'<path d="M9 7V3M15 7V3M7 7h10v4a5 5 0 0 1-10 0V7zM12 16v5"/>',
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 cal:'<rect x="4" y="5" width="16" height="15" rx="3"/><path d="M4 10h16M9 3v4M15 3v4"/>',
 cycle:'<path d="M20 12a8 8 0 0 1-14 5.3M4 12a8 8 0 0 1 14-5.3M18 3v4h-4M6 21v-4h4"/>',
 chart:'<path d="M5 20V11M10.5 20V5M16 20v-6M21 20H3"/>',
 bell:'<path d="M6 16V11a6 6 0 1 1 12 0v5l2 2H4l2-2zM10 20a2 2 0 0 0 4 0"/>',
 gear:'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
 pen:'<path d="M4 20h4L19 9l-4-4L4 16v4zM14 6l4 4"/>',
 power:'<path d="M12 3v8M6.3 6.3a8 8 0 1 0 11.4 0"/>',
 trash:'<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',
 warn:'<path d="M12 3l10 18H2L12 3zM12 10v4M12 17.5v.5"/>',
 info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
 wifi:'<path d="M2 9a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0M12 19.5v.5"/>',
 send:'<path d="M21 3L10 14M21 3l-7 18-4-7-7-4 18-7z"/>',
};
const ic=(n,c='i')=>`<svg class="${c}" viewBox="0 0 24 24" aria-hidden=true>${ICON[n]}</svg>`;

const T={
 en:{tabs:['Outlets','Rules','Energy','Alerts','Settings'],
  addStrip:'Add a strip',claimCode:'7-character code',claimHelp:'Enter the last 7 characters of the setup Wi-Fi name TONLY_TAP_XXXXXXX, or the code on the strip label. The strip must be connected to this server.',
  claimStart:'Continue',claimPress:'Press any physical button on the strip within 60 seconds.',claimWarning:'Pressing a button switches an outlet; you can switch it back.',
  claimDone:'Strip added',claimExpired:'Time expired. Start again when you are next to the strip.',claimRemaining:n=>`${n} seconds remaining`,tryAgain:'Try again',close:'Close',
  roles:{owner:'Owner',control:'Control',viewer:'Viewer'},people:'People',share:'Share',shareHelp:'Enter a registered account’s phone number.',shareSaved:'Access updated if the account is registered.',
  remove:'Remove',transfer:'Transfer ownership',transferConfirm:p=>`Transfer ownership to ${p}? You will become a controller.`,unclaim:'Unclaim strip',unclaimHelp:'Everyone will lose access. Names, rules and history are kept.',
  typeName:'Type the strip name to confirm',nameMismatch:'The name does not match.',leave:'Leave strip',leaveConfirm:'Leave this strip? The owner will need to share it with you again.',
  stripSettings:'Strip settings',alertPrefs:'Alerts from each strip',alertPrefsHelp:'Choose which events reach your notification channels.',actor:'Actor',actorNames:{legacy:'Shared token',rule:'Rule',strip:'Strip'},
  eventNames:{offline:'Offline',online:'Online',temp_high:'Temperature',power_high:'Power limit',budget:'Budget',rule_fired:'Rule ran',rule_skipped:'Rule skipped',rule_failed:'Rule failed',autooff:'Auto-off',onoff:'Switch activity',name_changed:'Names changed',rule_created:'Rule added',rule_updated:'Rule changed',rule_deleted:'Rule removed'},
  login:'Sign in',register:'Create account',phone:'Phone number',password:'Password',showPassword:'Show',hidePassword:'Hide',
  loginHelp:'Sign in to control your strips.',registerHelp:'Your phone number is your username. No text message or verification is needed.',
  phoneHelp:'Use + and your country code, or an Egyptian mobile number starting with 01.',passwordHelp:'Use 10–128 characters. Avoid common passwords and your phone number.',
  needAccount:'Create an account',haveAccount:'Already have an account? Sign in',logout:'Sign out',account:'Account',
  changePassword:'Change password',currentPassword:'Current password',newPassword:'New password',passwordChanged:'Password changed. Your other sessions have been signed out.',
  sessions:'Active sessions',thisSession:'This session',sessionCreated:'Signed in',sessionUsed:'Last used',unknownDevice:'Unknown device',
  sessionExpired:'Your session ended. Please sign in again.',networkError:'Could not reach the server. Try again.',
  legacyAccount:'Connected with a shared token. Sign in with an account to manage your password and sessions.',
  authErrors:{'wrong phone or password':'Wrong phone number or password.','phone already registered':'This phone number is already registered.',
    'invalid phone number':'Enter an international number with +, or an 11-digit Egyptian mobile number.',
    'password must be 10-128 characters':'Use a password with 10–128 characters.','password must be 1-128 characters':'Enter your password (up to 128 characters).',
    'password is too common or matches phone':'Choose a less common password that is different from your phone number.',
    'registration is closed':'Registration is closed on this server.','CSRF token required':'Reload the page and try again.',
    'no unclaimed online strip with this code':'No unclaimed online strip has this code. Check the code and connection.',
    'claim already pending':'Someone is already claiming this strip. Try again after 60 seconds.','code must be 7 hex characters':'Enter 7 characters using 0–9 and A–F.',
    'forbidden':'Your role does not allow this action.','unknown strip':'This strip is not available to your account.'},
  now:'Using now',outlet:'Outlet',allOn:'All on',allOff:'All off',online:'Online',offline:'Offline',on:'On',off:'Off',sending:'Switching…',today:'Today',month:'This month',stripInfo:'Strip info',conn:'Connection',wifi:'Wi-Fi signal',wifiLv:['Excellent','Good','Weak','Very weak — the strip may drop'],wifiHelp:'The closer the number is to zero, the stronger the signal.',ipAddr:'Address on your network',model:'Model',fw:'Firmware version',mac:'Device ID (MAC)',
  rename:'Rename',stripName:'Strip name',outletName:'Outlet name',resetHint:'Leave empty for the default name.',save:'Save',cancel:'Cancel',
  noStrip:'No strip connected yet',noStripBody:'Provision the strip with this server’s IP, then power-cycle it.',notConfirmed:'Sent, but the strip did not confirm',
  rules:'Rules',rulesEmpty:'No rules yet. Rules run on the server, even while your phone is off.',newRule:'New rule',kinds:{schedule:'Schedule',timer:'Timer',cycle:'Cycle',autooff:'Auto-off'},
  at:'At',action:'Action',turnOn:'Turn on',turnOff:'Turn off',inMin:'In (minutes)',onMin:'On (min)',offMin:'Off (min)',belowW:'Below (W)',forMin:'For (min)',label:'Label (optional)',
  outlets:'Outlets',days:['Mon','Tue','Wed','Thu','Fri','Sat','Sun'],repeat:'Repeat',everyDay:'Every day',allOutlets:'All outlets',addRule:'Add rule',added:'Rule added',delRule:'Delete this rule?',next:'next',
  cycleDesc:(a,b)=>`${a} min on / ${b} min off`,autoDesc:(w,m)=>`Off below ${w} W for ${m} min`,timerAt:t=>`at ${t}`,nowPhase:p=>`now ${p}`,strip:'Strip',
  ranges:[['day','24 h'],['week','7 days'],['month','30 days'],['year','12 months']],budget:'Monthly budget',noBudget:'No monthly budget set. Add one in Settings.',ofBudget:(p,b)=>`${p}% of ${b}`,
  estimate:'Estimated from the strip’s own meter, not an electricity bill.',at_price:p=>`at ${p}/kWh`,byOutlet:'By outlet',
  alerts:'Alerts & activity',alertsEmpty:'Nothing has happened yet.',
  cost:'Cost',price:'Price per kWh',currency:'Currency',budgetF:'Monthly budget (empty = off)',limits:'Limits',tempMax:'Max outlet temperature (°C)',powerMax:'Max total power (W)',
  push:'Push notifications',pushHelp:'ntfy: subscribe to a long, random topic in the ntfy app and paste its URL. Telegram: a bot token from @BotFather and your chat id.',
  ntfy:'ntfy topic URL',tgToken:'Telegram bot token',tgChat:'Telegram chat id',tgSaved:'Saved — type to replace',clearTg:'Remove token',sendTest:'Send test',saved:'Saved',
  sentVia:s=>`Sent via ${s}`,noChannel:'No push channel configured',failed:'failed',appearance:'Appearance',language:'Language',theme:'Theme',themes:{kraft:'Kraft paper',clean:'White & blue',night:'Chalkboard'},scheme:'Light or dark',schemes:{auto:'System',light:'Light',dark:'Dark'},
  ev:{offline:'Strip went offline',online:'Strip is back online',temp_high:p=>`Temperature high: ${p.temp_c} °C`,power_high:p=>`Total power high: ${p.watts} W`,
   budget:p=>`Monthly budget ${p.pct}% used`,rule_fired:p=>`Rule ran: switched ${p.on?'on':'off'}`,rule_skipped:'Rule skipped: strip offline',rule_failed:'Rule sent but not confirmed',autooff:p=>`Auto-off at ${p.watts} W`},
  alarm:{temp_high:'Hot',power_high:'Power high'}},
 ar:{tabs:['الفيش','القواعد','الاستهلاك','التنبيهات','الإعدادات'],
  addStrip:'إضافة مشترك',claimCode:'الكود المكوّن من 7 حروف وأرقام',claimHelp:'اكتب آخر 7 حروف وأرقام من اسم شبكة الإعداد TONLY_TAP_XXXXXXX، أو الكود على ملصق المشترك. لازم المشترك يكون متصل بالسيرفر ده.',
  claimStart:'متابعة',claimPress:'اضغط أي زر فعلي على المشترك خلال 60 ثانية.',claimWarning:'الضغط على الزر بيشغّل أو بيطفي فيشة؛ تقدر ترجعها لحالتها بعدها.',
  claimDone:'المشترك اتضاف',claimExpired:'الوقت خلص. جرّب تاني وإنت جنب المشترك.',claimRemaining:n=>`فاضل ${n} ثانية`,tryAgain:'جرّب تاني',close:'إغلاق',
  roles:{owner:'مالك',control:'متحكم',viewer:'مشاهد'},people:'الأشخاص',share:'مشاركة',shareHelp:'اكتب رقم موبايل حساب مسجّل.',shareSaved:'تم تحديث الوصول لو الحساب مسجّل.',
  remove:'إزالة',transfer:'نقل الملكية',transferConfirm:p=>`تنقل الملكية لـ ${p}؟ دورك هيبقى متحكم.`,unclaim:'فك ربط المشترك',unclaimHelp:'كل الأشخاص هيفقدوا الوصول. الأسماء والقواعد وسجل الاستهلاك هيفضلوا محفوظين.',
  typeName:'اكتب اسم المشترك للتأكيد',nameMismatch:'الاسم مش مطابق.',leave:'مغادرة المشترك',leaveConfirm:'تغادر المشترك؟ المالك هيحتاج يشاركه معاك تاني.',
  stripSettings:'إعدادات المشترك',alertPrefs:'تنبيهات كل مشترك',alertPrefsHelp:'اختار الأحداث اللي توصلك على قنوات الإشعارات.',actor:'بواسطة',actorNames:{legacy:'التوكن المشترك',rule:'قاعدة',strip:'المشترك'},
  eventNames:{offline:'فصل الاتصال',online:'رجوع الاتصال',temp_high:'الحرارة',power_high:'حد القدرة',budget:'الميزانية',rule_fired:'تنفيذ قاعدة',rule_skipped:'تخطي قاعدة',rule_failed:'فشل قاعدة',autooff:'إطفاء تلقائي',onoff:'تشغيل وإطفاء',name_changed:'تغيير الأسماء',rule_created:'إضافة قاعدة',rule_updated:'تعديل قاعدة',rule_deleted:'حذف قاعدة'},
  login:'تسجيل الدخول',register:'إنشاء حساب',phone:'رقم الموبايل',password:'كلمة المرور',showPassword:'إظهار',hidePassword:'إخفاء',
  loginHelp:'سجّل دخولك عشان تتحكم في المشتركات.',registerHelp:'رقم موبايلك هو اسم حسابك. مش محتاج رسالة أو كود تأكيد.',
  phoneHelp:'اكتب + وكود الدولة، أو رقم موبايل مصري بيبدأ بـ 01.',passwordHelp:'من 10 لـ 128 حرف. اختار كلمة مش شائعة ومختلفة عن رقم موبايلك.',
  needAccount:'إنشاء حساب جديد',haveAccount:'عندك حساب؟ سجّل دخولك',logout:'تسجيل الخروج',account:'الحساب',
  changePassword:'تغيير كلمة المرور',currentPassword:'كلمة المرور الحالية',newPassword:'كلمة المرور الجديدة',passwordChanged:'كلمة المرور اتغيرت. تم تسجيل الخروج من الجلسات التانية.',
  sessions:'الجلسات النشطة',thisSession:'الجلسة دي',sessionCreated:'وقت الدخول',sessionUsed:'آخر استخدام',unknownDevice:'جهاز غير معروف',
  sessionExpired:'جلستك انتهت. سجّل دخولك تاني.',networkError:'مش قادرين نوصل للسيرفر. جرّب تاني.',
  legacyAccount:'متصل بتوكن مشترك. سجّل بحساب عشان تدير كلمة المرور والجلسات.',
  authErrors:{'wrong phone or password':'رقم الموبايل أو كلمة المرور غلط.','phone already registered':'رقم الموبايل ده مسجّل بالفعل.',
    'invalid phone number':'اكتب رقم دولي بيبدأ بـ +، أو رقم موبايل مصري من 11 رقم.',
    'password must be 10-128 characters':'كلمة المرور لازم تكون من 10 لـ 128 حرف.','password must be 1-128 characters':'اكتب كلمة المرور (لحد 128 حرف).',
    'password is too common or matches phone':'اختار كلمة مرور مش شائعة ومختلفة عن رقم موبايلك.',
    'registration is closed':'التسجيل مقفول على السيرفر ده.','CSRF token required':'حدّث الصفحة وجرّب تاني.',
    'no unclaimed online strip with this code':'مفيش مشترك متصل وغير مربوط بالكود ده. راجع الكود والاتصال.',
    'claim already pending':'في حد بيحاول يربط المشترك ده. جرّب بعد 60 ثانية.','code must be 7 hex characters':'اكتب 7 حروف وأرقام من 0–9 وA–F.',
    'forbidden':'دورك مش بيسمح بالخطوة دي.','unknown strip':'المشترك ده مش متاح لحسابك.'},
  now:'الاستهلاك دلوقتي',outlet:'فيشة',allOn:'شغّل الكل',allOff:'اطفي الكل',online:'متصل',offline:'غير متصل',on:'شغالة',off:'طافية',sending:'بيتنفذ…',today:'النهارده',month:'الشهر ده',stripInfo:'معلومات المشترك',conn:'الاتصال',wifi:'إشارة الواي فاي',wifiLv:['ممتازة','كويسة','ضعيفة شوية','ضعيفة — ممكن يفصل'],wifiHelp:'كل ما الرقم يقرب من الصفر، الإشارة بتبقى أقوى.',ipAddr:'عنوانه على الشبكة',model:'الموديل',fw:'إصدار البرنامج اللي جواه',mac:'رقم الجهاز (MAC)',
  rename:'تغيير الاسم',stripName:'اسم المشترك',outletName:'اسم الفيشة',resetHint:'سيبه فاضي للاسم الافتراضي.',save:'حفظ',cancel:'إلغاء',
  noStrip:'مفيش مشترك متصل لسه',noStripBody:'اعمل تهيئة للمشترك بعنوان السيرفر ده، وبعدين افصله ووصله تاني.',notConfirmed:'الأمر اتبعت بس المشترك ما أكدش',
  rules:'القواعد',rulesEmpty:'مفيش قواعد لسه. القواعد بتشتغل على السيرفر حتى لو الموبايل مقفول.',newRule:'قاعدة جديدة',kinds:{schedule:'جدول',timer:'مؤقت',cycle:'دورة',autooff:'إطفاء تلقائي'},
  at:'الساعة',action:'الأمر',turnOn:'تشغيل',turnOff:'إطفاء',inMin:'بعد (دقيقة)',onMin:'تشغيل (دقيقة)',offMin:'إطفاء (دقيقة)',belowW:'أقل من (واط)',forMin:'لمدة (دقيقة)',label:'اسم القاعدة (اختياري)',
  outlets:'الفيش',days:['الاتنين','التلات','الأربع','الخميس','الجمعة','السبت','الحد'],repeat:'التكرار',everyDay:'كل يوم',allOutlets:'كل الفيش',addRule:'إضافة القاعدة',added:'القاعدة اتضافت',delRule:'تمسح القاعدة دي؟',next:'الجاية',
  cycleDesc:(a,b)=>`${a} دقيقة شغال / ${b} دقيقة طافي`,autoDesc:(w,m)=>`يطفي لو أقل من ${w} واط لمدة ${m} دقيقة`,timerAt:t=>`الساعة ${t}`,nowPhase:p=>`دلوقتي ${p==='on'?'شغال':'طافي'}`,strip:'المشترك',
  ranges:[['day','24 ساعة'],['week','7 أيام'],['month','30 يوم'],['year','12 شهر']],budget:'الميزانية الشهرية',noBudget:'مفيش ميزانية شهرية. ضيفها من الإعدادات.',ofBudget:(p,b)=>`${p}% من ${b}`,
  estimate:'تقدير من عداد المشترك نفسه، مش فاتورة الكهربا.',at_price:p=>`بسعر ${p} للكيلوواط ساعة`,byOutlet:'حسب الفيشة',
  alerts:'التنبيهات والنشاط',alertsEmpty:'مفيش حاجة حصلت لسه.',
  cost:'التكلفة',price:'سعر الكيلوواط ساعة',currency:'العملة',budgetF:'الميزانية الشهرية (فاضي = مقفولة)',limits:'الحدود',tempMax:'أقصى حرارة للفيشة (°م)',powerMax:'أقصى قدرة إجمالية (واط)',
  push:'إشعارات الموبايل',pushHelp:'ntfy: اشترك في topic طويل وعشوائي من تطبيق ntfy والصق اللينك. تيليجرام: توكن البوت من ‎@BotFather‎ ورقم المحادثة.',
  ntfy:'لينك topic في ntfy',tgToken:'توكن بوت تيليجرام',tgChat:'رقم محادثة تيليجرام',tgSaved:'محفوظ — اكتب عشان تغيّره',clearTg:'امسح التوكن',sendTest:'ابعت تجربة',saved:'اتحفظ',
  sentVia:s=>`اتبعت عن طريق ${s}`,noChannel:'مفيش قناة إشعارات متظبطة',failed:'فشل',appearance:'الشكل',language:'اللغة',theme:'الثيم',themes:{kraft:'ورق كرافت',clean:'أبيض وأزرق',night:'سبورة'},scheme:'فاتح ولا غامق',schemes:{auto:'زي الجهاز',light:'فاتح',dark:'غامق'},
  ev:{offline:'المشترك فصل',online:'المشترك رجع',temp_high:p=>`حرارة عالية: ${p.temp_c} °م`,power_high:p=>`القدرة الإجمالية عالية: ${p.watts} واط`,
   budget:p=>`استهلكت ${p.pct}% من الميزانية الشهرية`,rule_fired:p=>`قاعدة اتنفذت: ${p.on?'تشغيل':'إطفاء'}`,rule_skipped:'قاعدة اتلغت: المشترك مش متصل',rule_failed:'قاعدة اتبعتت بس ما اتأكدتش',autooff:p=>`إطفاء تلقائي عند ${p.watts} واط`},
  alarm:{temp_high:'سخنة',power_high:'حمل عالي'}},
};
const TABS=['plugs','rules','energy','alerts','settings'], TAB_ICONS=['plug','clock','chart','bell','gear'];
const store={get:k=>{try{return localStorage.getItem(k)}catch(e){return null}},set:(k,v)=>{try{localStorage.setItem(k,v)}catch(e){}}};
let lang=store.get('powerk-lang')||((navigator.language||'').startsWith('ar')?'ar':'en');
const THEMES=['kraft','clean','night'];
let theme=THEMES.includes(store.get('powerk-theme'))?store.get('powerk-theme'):'kraft';
let scheme=store.get('powerk-scheme')||'auto';
let tab=TABS.includes(location.hash.slice(1))?location.hash.slice(1):'plugs';
let S=null, range='week', energyMac=null, ruleKind='schedule', pending={};
let claimState=null, claimBusy=false, peopleMac=null, peopleList=[];
let signedIn=false, currentUser=null, authMode='login', authMessage='', authEpoch=0, sessionVersion=0, refreshPromise=null, pollBusy=false;
let liveSocket=null, liveReady=false, liveRetry=0, liveTimer=null, liveWatchdog=null, liveDetails=null, stateRevision=0, refreshQueued=false, pollPatches=null;
const t=()=>T[lang];
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>'&#'+c.charCodeAt(0)+';');   // names, model, fw, event text come from outside
async function requestJSON(p,method='GET',b){
  const headers={'X-Powerk-Client':'web'};
  if(method!=='GET'){
    headers['Content-Type']='application/json';
    const csrf=document.cookie.split(';').map(s=>s.trim()).find(s=>s.startsWith('powerk_csrf='));
    if(csrf)headers['X-CSRF-Token']=decodeURIComponent(csrf.slice('powerk_csrf='.length));
  }
  const r=await fetch(p,{method,headers,credentials:'same-origin',cache:'no-store',body:b===undefined?undefined:JSON.stringify(b)});
  const j=await r.json().catch(()=>({error:'HTTP '+r.status}));
  return {r,j};
}
async function refreshSession(version){
  if(version!==sessionVersion)return true;
  if(!refreshPromise){
    const epoch=authEpoch;
    const rotate=async()=>{
      if(epoch!==authEpoch)return false;
      // The shared lock lets another tab's refreshed cookie satisfy this request.
      if(navigator.locks){
        const {r,j}=await requestJSON('api/auth/me');
        if(epoch!==authEpoch)return false;
        if(r.ok){currentUser=j.user;sessionVersion++;return true}
        if(r.status!==401)return false;
      }
      const {r,j}=await requestJSON('api/auth/refresh','POST',{});
      if(!r.ok||epoch!==authEpoch)return false;
      currentUser=j.user;sessionVersion++;return true;
    };
    refreshPromise=(navigator.locks?navigator.locks.request('powerk-refresh',rotate):rotate()).catch(()=>false).finally(()=>{refreshPromise=null});
  }
  return refreshPromise;
}
async function api(p,method,b,allowError=false){
  const epoch=authEpoch, version=sessionVersion;
  let {r,j}=await requestJSON(p,method,b);
  if(epoch!==authEpoch)throw new Error(t().sessionExpired);
  if(r.status===401){
    if(await refreshSession(version)&&epoch===authEpoch)({r,j}=await requestJSON(p,method,b));
    if(epoch!==authEpoch)throw new Error(t().sessionExpired);
    if(r.status===401){showAuth('login',signedIn?t().sessionExpired:'');throw new Error(t().sessionExpired)}
  }
  if(epoch!==authEpoch)throw new Error(t().sessionExpired);
  if(!r.ok||(!allowError&&j.error))throw new Error(t().authErrors[j.error]||j.error||('HTTP '+r.status));
  return j;
}
let toastT;function toast(m){const el=$('toast');el.textContent=m;el.classList.add('show');clearTimeout(toastT);toastT=setTimeout(()=>el.classList.remove('show'),3200)}
const run=async f=>{try{await f()}catch(e){toast(e.message)}};
const label=d=>d.label||d.name, oname=o=>o.name||`${t().outlet} ${o.n}`;
const percent=v=>Number.isFinite(+v)?Math.max(0,Math.min(100,+v)):0;
const num=v=>(+v).toLocaleString('en-US',{maximumFractionDigits:2});   // Western digits in both languages, like the 30° readings
const money=(v,currency=S?.currency||'')=>`${num((+v).toFixed(2))} ${esc(currency)}`;
const canControl=d=>!!d&&(!currentUser||['owner','control'].includes(d.role));
const canOwn=d=>!!d&&(!currentUser||d.role==='owner');
const loc=()=>lang==='ar'?'ar-EG-u-nu-latn':'en-GB';
const fmtT=s=>s?new Date(s*1000).toLocaleString(loc(),{weekday:'short',hour:'2-digit',minute:'2-digit'}):'';

function setLang(l){lang=l;store.set('powerk-lang',l);document.documentElement.lang=l;document.documentElement.dir=l==='ar'?'rtl':'ltr';chrome();signedIn?draw(true):renderAuth()}
function setScheme(k){scheme=k;store.set('powerk-scheme',k);if(k==='auto')delete document.documentElement.dataset.scheme;else document.documentElement.dataset.scheme=k;paintBar()}
function setTheme(k){theme=k;store.set('powerk-theme',k);document.documentElement.dataset.theme=k;paintBar()}
function paintBar(){$('themeColor').content=getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()}
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',paintBar);
function chrome(){
  $('langBtn').textContent=lang==='ar'?'English':'عربي';
  $('nav').hidden=!signedIn;$('logoutBtn').hidden=!signedIn||!currentUser;$('logoutBtn').textContent=t().logout;
  $('nav').innerHTML=TABS.map((k,i)=>`<button ${k===tab?'aria-current=page':''} data-action="go" data-value="${esc(k)}">${ic(TAB_ICONS[i])}<span>${t().tabs[i]}</span>${k==='alerts'&&S&&S.unread_alerts?`<span class=badge>${esc(S.unread_alerts)}</span>`:''}</button>`).join('');
}
function go(k){tab=k;history.replaceState(null,'','#'+k);chrome();draw(true);scrollTo({top:0})}
async function draw(full){
  if(!signedIn)return;
  if(tab==='plugs') return plugs();
  if(!full) return;
  const f={rules,energy,alerts,settings}[tab];
  try{await f()}catch(e){if(signedIn)$('app').innerHTML=`<div class=card><div class=empty>${esc(e.message)}</div></div>`}
}

/* ---------- accounts ---------- */
function passwordField(id,label,autocomplete){
  return `<label class=f>${label}<span class=password-box><input id=${id} name=${id} type=password maxlength=128 ${autocomplete==='new-password'?'minlength=10':''} autocomplete=${autocomplete} required>
    <button class="btn plain" type=button aria-controls=${id} aria-pressed=false data-action="password-visibility" data-id="${esc(id)}">${t().showPassword}</button></span></label>`;
}
function togglePassword(id,button){const input=$(id);input.type=input.type==='password'?'text':'password';button.textContent=input.type==='password'?t().showPassword:t().hidePassword;button.setAttribute('aria-pressed',String(input.type==='text'))}
function renderAuth(){
  const L=t(), registering=authMode==='register', phone=$('authPhone')?.value||'';
  $('app').innerHTML=`<section class="card auth"><h1>${registering?L.register:L.login}</h1>
    <p class=muted>${registering?L.registerHelp:L.loginHelp}</p>
    <form id=authForm data-action="authenticate">
      <label class=f>${L.phone}<input id=authPhone name=phone type=tel inputmode=tel dir=ltr autocomplete=username maxlength=64 required value="${esc(phone)}" placeholder="+20 100 123 4567"></label>
      <p class=muted>${L.phoneHelp}</p>
      ${passwordField('authPassword',L.password,registering?'new-password':'current-password')}
      ${registering?`<p class=muted>${L.passwordHelp}</p>`:''}
      <p class=auth-error id=authError role=alert>${esc(authMessage)}</p>
      <button class="btn primary full-width" type=submit>${registering?L.register:L.login}</button>
    </form>
    <button class="btn plain auth-mode-button" data-action="show-auth" data-value="${registering?'login':'register'}">${registering?L.haveAccount:L.needAccount}</button>
    <h3 class="mt-24">${L.theme}</h3><div class=seg role=group>${THEMES.map(k=>`<button aria-pressed=${k===theme} data-action="auth-theme" data-value="${esc(k)}">${L.themes[k]}</button>`).join('')}</div>
  </section>`;
}
function showAuth(mode='login',message=''){
  stopLive();
  signedIn=false;currentUser=null;S=null;pending={};energyMac=null;authMode=mode;authMessage=message;authEpoch++;
  claimState=null;peopleMac=null;peopleList=[];
  if($('dlg').open){$('dlg').returnValue='cancel';$('dlg').close()}
  chrome();renderAuth();
}
async function submitAuth(form){
  const button=form.querySelector('[type=submit]'), epoch=authEpoch;
  const body={phone:form.elements.phone.value,password:form.elements.authPassword.value};
  button.disabled=true;$('authError').textContent='';
  try{
    const {r,j}=await requestJSON('api/auth/'+authMode,'POST',body);
    if(epoch!==authEpoch)return;
    if(!r.ok)throw new Error(t().authErrors[j.error]||j.error||('HTTP '+r.status));
    form.elements.authPassword.value='';signedIn=true;currentUser=j.user;authEpoch++;sessionVersion++;
    chrome();await refresh();await draw(true);connectLive();
  }catch(e){if(epoch===authEpoch)$('authError').textContent=e instanceof TypeError?t().networkError:e.message}
  finally{button.disabled=false}
}
async function logout(){run(async()=>{await api('api/auth/logout','POST',{});showAuth()})}
async function changePassword(form){
  const button=form.querySelector('[type=submit]'), epoch=authEpoch;
  button.disabled=true;$('passwordError').textContent='';
  try{
    await api('api/auth/password','POST',{current_password:form.elements.currentPassword.value,new_password:form.elements.newPassword.value});
    form.reset();toast(t().passwordChanged);await settings();
  }catch(e){if(epoch===authEpoch&&signedIn)$('passwordError').textContent=e.message}
  finally{button.disabled=false}
}
function signOutSession(id,current){run(async()=>{await api('api/auth/sessions/'+id,'DELETE');if(current)showAuth();else await settings()})}
function accountSettings(sessions){
  const L=t();
  if(!currentUser)return `<section class=card><h2>${L.account}</h2><p class=muted>${L.legacyAccount}</p><button class="btn plain" data-action="show-auth">${L.login}</button></section>`;
  const date=s=>new Date(s*1000).toLocaleString(loc(),{dateStyle:'medium',timeStyle:'short'});
  return `<section class=card><h2>${L.account} · <bdi>${esc(currentUser.phone)}</bdi></h2>
    <form data-action="change-password"><h3>${L.changePassword}</h3>
      ${passwordField('currentPassword',L.currentPassword,'current-password')}${passwordField('newPassword',L.newPassword,'new-password')}
      <p class=muted>${L.passwordHelp}</p><p class=auth-error id=passwordError role=alert></p>
      <button class="btn primary" type=submit>${L.changePassword}</button></form></section>
    <section class=card><h2>${L.sessions}</h2><div class=list>${sessions.map(s=>`<div class=item>
      <div class=grow><b>${s.current?L.thisSession:esc(s.user_agent||L.unknownDevice)}</b>
        ${s.current?`<span class="muted session-meta">${esc(s.user_agent||L.unknownDevice)}</span>`:''}
        <span class="muted session-meta"><bdi>${esc(s.ip)}</bdi> · ${L.sessionCreated}: ${esc(date(s.created_at))}</span>
        <span class="muted session-meta">${L.sessionUsed}: ${esc(date(s.last_used_at))}</span></div>
      <button class="btn danger" data-action="sign-out-session" data-id="${esc(s.id)}" data-current="${!!s.current}">${L.logout}</button></div>`).join('')}</div></section>`;
}

/* ---------- outlets ---------- */
function plugs(){
  const L=t();
  if(!S){$('app').innerHTML=`<div class="tiles mt-62">${'<div class=skeleton></div>'.repeat(4)}</div>`;return}
  const add=currentUser?`<button class="btn primary" data-action="open-claim">${ic('plus')}${L.addStrip}</button>`:'';
  if(!S.devices.length){$('app').innerHTML=`<div class="card mt-8"><h2>${currentUser?L.addStrip:L.noStrip}</h2><p class=muted>${currentUser?L.claimHelp:L.noStripBody}</p>${add}</div>`;return}
  $('app').innerHTML=S.devices.map(d=>{
    const alarms=(d.alarms||[]).map(a=>`<span class=pill>${ic('warn')}${L.alarm[a]||esc(a)}</span>`).join('');
    const editable=canControl(d), busy=[1,2,3,4].some(n=>(d.mac+':'+n) in pending), dis=!d.online||busy||!editable?'disabled':'';
    return `<section class="dev${d.online?'':' offline'}">
    <div class=devhead><h1>${esc(label(d))}</h1>
      ${editable?`<button class=iconbtn aria-label="${L.rename}" data-action="rename" data-mac="${esc(d.mac)}" data-outlet="0">${ic('pen')}</button>`:''}
      <span class=role>${L.roles[d.role]||L.roles.owner}</span>
      <span class="state${d.online?' on':''}">${d.online?L.online:L.offline}</span></div>
    ${alarms?`<div class="row alarms">${alarms}</div>`:''}
    <div class="card sum"><small>${L.now}</small><strong><bdi>${num(d.power_w)}<span>W</span></bdi></strong>
      <div class=mini>${d.voltage?`<span><bdi><b>${num(d.voltage)} V</b> · ${num(d.current_a)} A</bdi></span>`:''}
        <span>${L.today} <b><bdi>${num(d.today_kwh??0)} kWh</bdi></b></span><span>${L.month} <b><bdi>${money(d.month_cost??0,d.currency)}</bdi></b></span></div></div>
    <div class=tiles>${d.outlets.map(o=>{const key=d.mac+':'+o.n, pend=key in pending, on=pend?pending[key]:o.on;
      const al=(o.alarms||[]).map(a=>L.alarm[a]||a).join(' · ');
      return `<div class="tile${on?' on':''}${pend?' pending':''}">
        <button class=tap aria-pressed="${!!on}" ${d.online&&!pend&&editable?'':'disabled'} aria-busy=${pend} data-action="switch" data-mac="${esc(d.mac)}" data-outlet="${esc(o.n)}" data-on="${!o.on}">
          <span class=tname>${esc(oname(o))}<small>${pend?L.sending:on?L.on:L.off} · <bdi>${esc(o.temp_c)}°</bdi>${al?` · <span class=alarm>${esc(al)}</span>`:''}</small></span>
          <span class=tfoot><span class=tw><bdi>${num(o.power_w)}<small>W</small></bdi></span><span class=knob></span></span>
        </button>
        ${editable?`<button class=edit aria-label="${L.rename} ${esc(oname(o))}" data-action="rename" data-mac="${esc(d.mac)}" data-outlet="${esc(o.n)}">${ic('pen')}</button>`:''}</div>`}).join('')}</div>
    <div class=both><button class="btn dark" ${dis} data-action="switch" data-mac="${esc(d.mac)}" data-outlet="0" data-on="true">${ic('power')}${L.allOn}</button><button class=btn ${dis} data-action="switch" data-mac="${esc(d.mac)}" data-outlet="0" data-on="false">${L.allOff}</button></div>
    <div class="row mt-12">${canOwn(d)?`<button class="btn plain" data-action="people" data-mac="${esc(d.mac)}">${L.people}</button><button class="btn danger" data-action="unclaim" data-mac="${esc(d.mac)}">${L.unclaim}</button>`:`<button class="btn plain" data-action="leave" data-mac="${esc(d.mac)}">${L.leave}</button>`}</div>
  </section>`}).join('')+add;
}
function cmd(mac,outlet,on){
  if(!canControl(S?.devices.find(d=>d.mac===mac)))return;
  const keys=outlet?[mac+':'+outlet]:[1,2,3,4].map(n=>mac+':'+n);
  if(keys.some(k=>k in pending)) return;
  keys.forEach(k=>pending[k]=on);plugs();
  run(async()=>{try{const r=await api('api/onoff','POST',{mac,outlet,on});if(r.confirmed===false)toast(t().notConfirmed)}finally{keys.forEach(k=>delete pending[k]);await refresh()}});
}
function rename(mac,n){
  const d=S.devices.find(x=>x.mac===mac);if(!canControl(d))return;const cur=n?(d.outlets.find(o=>o.n===n).name||''):(d.label||'');
  dialogSubmit=null;
  $('dlgForm').innerHTML=`<h2 class="mb-16">${n?t().outletName:t().stripName}</h2>
    <label class=f>${n?`${t().outlet} ${n}`:esc(d.name)}<input id=dlgIn maxlength=40 value="${esc(cur)}" placeholder="${n?`${t().outlet} ${n}`:esc(d.name)}"></label>
    <p class="muted rename-hint">${t().resetHint}</p>
    <div class=both><button class="btn plain" value=cancel>${t().cancel}</button><button class="btn primary" value=ok>${t().save}</button></div>`;
  const dlg=$('dlg');dlg.returnValue='';dlg.showModal();$('dlgIn').select();
  dialogClose=()=>{if(dlg.returnValue==='ok')run(async()=>{await api('api/name','POST',{mac,outlet:n,name:$('dlgIn').value.trim()});await refresh()})};
}

/* ---------- ownership and sharing ---------- */
function modal(html){const dlg=$('dlg');dialogClose=null;dialogSubmit=null;$('dlgForm').innerHTML=html;if(!dlg.open)dlg.showModal()}
function claimSeconds(){return Math.max(0,Math.ceil(((claimState?.deadline||0)-Date.now())/1000))}
function claimView(){
  const L=t(), status=claimState?.status;
  if(status==='pending')return `<h2>${L.addStrip}</h2><p>${L.claimPress}</p><p class=muted>${L.claimWarning}</p><p id=claimCountdown role=status>${L.claimRemaining(claimSeconds())}</p><p class=auth-error id=claimError role=alert></p><button class="btn plain" value=cancel>${L.close}</button>`;
  if(status==='done'||status==='expired')return `<h2>${status==='done'?L.claimDone:L.claimExpired}</h2><div class="row mt-18">${status==='expired'?`<button class="btn primary" type=button data-action="retry-claim">${L.tryAgain}</button>`:''}<button class="btn plain" value=cancel>${L.close}</button></div>`;
  return `<h2>${L.addStrip}</h2><p class=muted>${L.claimHelp}</p><label class=f>${L.claimCode}<input name=code id=claimCode dir=ltr autocomplete=off pattern="[0-9A-Fa-f]{7}" minlength=7 maxlength=7 required placeholder="A1B2C3D"></label><p class=auth-error id=claimError role=alert></p><div class=both><button class="btn plain" type=button data-action="close-dialog">${L.cancel}</button><button class="btn primary" type=submit>${L.claimStart}</button></div>`;
}
function openClaim(fresh=false){
  if(!currentUser)return;
  if(fresh&&claimState?.status!=='pending')claimState=null;
  modal(claimView());
  if(!claimState){dialogSubmit=beginClaim;$('claimCode').focus()}
}
async function beginClaim(form){
  const button=form.querySelector('[type=submit]');button.disabled=true;
  try{
    const r=await api('api/strips/claim','POST',{code:form.elements.code.value.trim().toUpperCase()});
    claimState={...r,status:'pending',deadline:Date.now()+r.expires_in*1000};openClaim();
  }catch(e){if(signedIn)$('claimError').textContent=e.message}finally{button.disabled=false}
}
async function pollClaim(){
  if(!signedIn||claimState?.status!=='pending'||claimBusy)return;
  const id=claimState.claim_id;claimBusy=true;
  if($('claimCountdown'))$('claimCountdown').textContent=t().claimRemaining(claimSeconds());
  try{
    const r=await api('api/strips/claim/'+encodeURIComponent(id));
    if(claimState?.claim_id!==id)return;
    if(r.status!=='pending'){
      claimState={...claimState,...r};
      if($('dlg').open&&$('claimCountdown'))openClaim();
      if(r.status==='done'){toast(t().claimDone);await refresh()}
    }
  }catch(e){if($('claimError'))$('claimError').textContent=e.message}finally{claimBusy=false}
}
function roleOptions(role){return ['control','viewer'].map(r=>`<option value=${r} ${r===role?'selected':''}>${t().roles[r]}</option>`).join('')}
async function people(mac){
  if(!canOwn(S?.devices.find(d=>d.mac===mac)))return;
  try{
    const result=await api('api/strips/'+mac+'/access');peopleMac=mac;peopleList=result.access;
    const L=t();
    modal(`<h2>${L.people} · ${esc(label(S.devices.find(d=>d.mac===mac)))}</h2><div class=list>${peopleList.map(p=>`<div class=item><div class=grow><bdi>${esc(p.phone)}</bdi> <span class=role>${esc(L.roles[p.role]||p.role)}</span>${p.role!=='owner'?`<div class=people-actions><select aria-label="${esc(L.roles[p.role]||p.role)}" data-action="change-role" data-id="${esc(p.user_id)}">${roleOptions(p.role)}</select><button class="btn danger" type=button data-action="remove-person" data-id="${esc(p.user_id)}">${L.remove}</button><button class="btn plain" type=button data-action="transfer" data-id="${esc(p.user_id)}">${L.transfer}</button></div>`:''}</div></div>`).join('')}</div>
      <h3 class="mt-18">${L.shareHelp}</h3><label class=f>${L.phone}<input name=phone type=tel dir=ltr autocomplete=off required></label><label class=f>${L.share}<select name=role>${roleOptions('control')}</select></label><p class=auth-error id=peopleError role=alert></p><div class=both><button class="btn plain" type=button data-action="close-dialog">${L.close}</button><button class="btn primary" type=submit>${L.share}</button></div>`);
    dialogSubmit=shareStrip;
  }catch(e){toast(e.message)}
}
async function shareStrip(form){
  const mac=peopleMac, button=form.querySelector('[type=submit]');button.disabled=true;
  try{await api('api/strips/'+mac+'/access','POST',{phone:form.elements.phone.value,role:form.elements.role.value});toast(t().shareSaved);await people(mac)}
  catch(e){if($('peopleError'))$('peopleError').textContent=e.message}finally{button.disabled=false}
}
const changeRole=(id,role)=>run(async()=>{const mac=peopleMac;await api(`api/strips/${mac}/access/${id}`,'PUT',{role});await people(mac)});
const removePerson=id=>run(async()=>{const mac=peopleMac;await api(`api/strips/${mac}/access/${id}`,'DELETE');await people(mac)});
function transferStrip(id){
  const p=peopleList.find(p=>p.user_id===id), mac=peopleMac;
  if(!p||!confirm(t().transferConfirm(p.phone)))return;
  return run(async()=>{await api(`api/strips/${mac}/transfer`,'POST',{phone:p.phone});$('dlg').close();await refresh()});
}
function unclaimDialog(mac){
  const d=S?.devices.find(d=>d.mac===mac);if(!canOwn(d))return;
  const L=t();modal(`<h2>${L.unclaim} · ${esc(label(d))}</h2><p class=muted>${L.unclaimHelp}</p><label class=f>${L.typeName}<input name=confirmation autocomplete=off required></label><p class=auth-error id=unclaimError role=alert></p><div class=both><button class="btn plain" type=button data-action="close-dialog">${L.cancel}</button><button class="btn danger" type=submit>${L.unclaim}</button></div>`);
  dialogSubmit=form=>submitUnclaim(form,mac);
}
async function submitUnclaim(form,mac){
  const d=S?.devices.find(d=>d.mac===mac);
  if(!d||form.elements.confirmation.value!==label(d)){$('unclaimError').textContent=t().nameMismatch;return}
  const button=form.querySelector('[type=submit]');button.disabled=true;
  try{await api('api/strips/'+mac,'DELETE');$('dlg').close();await refresh()}
  catch(e){if($('unclaimError'))$('unclaimError').textContent=e.message}finally{button.disabled=false}
}
function leaveStrip(mac){if(confirm(t().leaveConfirm))return run(async()=>{await api(`api/strips/${mac}/leave`,'POST',{});await refresh()})}

/* ---------- rules ---------- */
function describe(r,d){
  const L=t(), outs=r.outlets.length===4?L.allOutlets:r.outlets.map(n=>{const o=d&&d.outlets.find(x=>x.n===n);return o?oname(o):`${L.outlet} ${n}`}).join('، ');
  const w=r.on?L.turnOn:L.turnOff;
  if(r.kind==='schedule') return [`${r.at} · ${w}`,`${r.days.length===7?L.everyDay:r.days.map(x=>L.days[x]).join(' ')} · ${outs}`];
  if(r.kind==='timer') return [`${L.kinds.timer} · ${w}`,`${L.timerAt(fmtT(r.fire_at))} · ${outs}`];
  if(r.kind==='cycle') return [L.cycleDesc(r.on_min,r.off_min),`${outs}${r.phase?' · '+L.nowPhase(r.phase):''}`];
  return [L.autoDesc(r.below_w,r.for_min),outs];
}
const RULE_ICON={schedule:'cal',timer:'clock',cycle:'cycle',autooff:'power'};
async function rules(){
  const L=t(), {rules}=await api('api/rules'), devs=S?S.devices:[];
  const list=rules.map(r=>{const d=devs.find(x=>x.mac===r.mac);const [a,b]=describe(r,d);
    return `<div class=item><span class=dotk>${ic(RULE_ICON[r.kind]||'clock')}</span>
      <div class=grow><b>${esc(r.label||a)}</b><span class=muted>${esc(r.label?a+' · ':'')}${esc(b)}${r.enabled&&r.next_at?` · ${L.next} ${fmtT(r.next_at)}`:''}</span></div>
      ${canControl(d)?`<button class=switch role=switch aria-checked="${!!r.enabled}" aria-label="${esc(r.label||a)}" data-action="rule-enable" data-id="${esc(r.id)}" data-enabled="${!r.enabled}"></button>
      <button class=iconbtn aria-label="${L.delRule}" data-action="rule-delete" data-id="${esc(r.id)}">${ic('trash')}</button>`:''}</div>`}).join('');
  const editable=devs.filter(canControl), d0=editable[0];
  const outs=`<div class=checks>${[1,2,3,4].map(n=>{const o=d0&&d0.outlets.find(x=>x.n===n);return `<label><input type=checkbox class=rout value=${n} ${n===1?'checked':''}><span>${esc(o?oname(o):L.outlet+' '+n)}</span></label>`}).join('')}</div>`;
  const onoff=`<label class=f>${L.action}<select id=ron><option value=1>${L.turnOn}</option><option value=0>${L.turnOff}</option></select></label>`;
  const fields={
    schedule:`<div class=grid2><label class=f>${L.at}<input id=rat type=time value="07:00"></label>${onoff}</div>
      <h3>${L.repeat}</h3><div class=checks>${L.days.map((x,i)=>`<label><input type=checkbox class=rday value=${i} checked><span>${x}</span></label>`).join('')}</div>`,
    timer:`<div class=grid2><label class=f>${L.inMin}<input id=rmin type=number inputmode=numeric min=1 max=10080 value=30></label>${onoff}</div>`,
    cycle:`<div class=grid2><label class=f>${L.onMin}<input id=ronm type=number inputmode=numeric min=1 max=1440 value=10></label><label class=f>${L.offMin}<input id=roffm type=number inputmode=numeric min=1 max=1440 value=50></label></div>`,
    autooff:`<div class=grid2><label class=f>${L.belowW}<input id=rw type=number inputmode=decimal min=0.1 step=0.1 value=3></label><label class=f>${L.forMin}<input id=rfor type=number inputmode=numeric min=1 max=1440 value=10></label></div>`,
  };
  $('app').innerHTML=`<h1 class="page-heading">${L.rules}</h1>
  <section class="card compact-card"><div class=list>${list||`<div class=empty>${L.rulesEmpty}</div>`}</div></section>
  ${editable.length?`<section class=card><h2>${L.newRule}</h2>
    <div class="seg mb-18" role=group>${Object.entries(L.kinds).map(([k,v])=>`<button aria-pressed=${k===ruleKind} data-action="rule-kind" data-value="${esc(k)}">${v}</button>`).join('')}</div>
    <label class=f>${L.strip}<select id=rmac>${editable.map(d=>`<option value="${esc(d.mac)}">${esc(label(d))}</option>`).join('')}</select></label>
    <h3>${L.outlets}</h3>${outs}${fields[ruleKind]}
    <label class=f>${L.label}<input id=rlabel maxlength=40></label>
    <button class="btn primary full-width" data-action="rule-add">${ic('plus')}${L.addRule}</button></section>`:''}`;
}
function ruleAdd(){run(async()=>{
  const v=id=>$(id)&&$(id).value, n=id=>Number(v(id));
  const r={kind:ruleKind,mac:v('rmac')||S.devices.find(canControl)?.mac,label:v('rlabel').trim(),enabled:true,outlets:[...document.querySelectorAll('.rout:checked')].map(x=>+x.value)};
  if(ruleKind==='schedule'){r.at=v('rat');r.on=v('ron')==='1';r.days=[...document.querySelectorAll('.rday:checked')].map(x=>+x.value)}
  if(ruleKind==='timer'){r.minutes=n('rmin');r.on=v('ron')==='1'}
  if(ruleKind==='cycle'){r.on_min=n('ronm');r.off_min=n('roffm')}
  if(ruleKind==='autooff'){r.below_w=n('rw');r.for_min=n('rfor')}
  await api('api/rules','POST',r);toast(t().added);rules();
})}
const ruleOn=(id,en)=>run(async()=>{await api('api/rules/'+id,'PUT',{enabled:en});rules()});
const ruleDel=id=>{if(confirm(t().delRule))run(async()=>{await api('api/rules/'+id,'DELETE');rules()})};

/* ---------- energy ---------- */
async function energy(){
  const L=t();
  if(!S||!S.devices.length){$('app').innerHTML=`<div class="card mt-8"><div class=empty>${L.noStrip}</div></div>`;return}
  if(!S.devices.some(d=>d.mac===energyMac))energyMac=S.devices[0].mac;
  const h=await api(`api/history?mac=${energyMac}&range=${range}`), d=S.devices.find(x=>x.mac===energyMac)||S.devices[0];
  const max=Math.max(...h.buckets.map(b=>b.kwh),0.001);
  const lab=s=>{const x=new Date(s*1000);return h.unit==='hour'?x.toLocaleTimeString(loc(),{hour:'2-digit'}):h.unit==='day'?x.toLocaleDateString(loc(),{day:'numeric',month:'numeric'}):x.toLocaleDateString(loc(),{month:'short'})};
  const spent=d.month_cost||0, pct=d.budget?Math.round(spent/d.budget*100):0;
  $('app').innerHTML=`<h1 class="page-heading">${L.tabs[2]}</h1>
  <section class=card>
    ${S.devices.length>1?`<label class=f>${L.strip}<select data-action="energy-strip">${S.devices.map(x=>`<option value="${esc(x.mac)}" ${x.mac===energyMac?'selected':''}>${esc(label(x))}</option>`).join('')}</select></label>`:''}
    <div class=seg role=group>${L.ranges.map(([k,v])=>`<button aria-pressed=${k===range} data-action="energy-range" data-value="${esc(k)}">${v}</button>`).join('')}</div>
    <div class=total><bdi>${num(h.total_kwh)}<span>kWh</span></bdi></div>
    <div class=muted><bdi>${money(h.total_cost,h.currency)}</bdi></div>
    <div class=bars role=img aria-label="${num(h.total_kwh)} kWh">${h.buckets.map(b=>`<div class="${b.kwh?'':'zero'}" title="${lab(b.t)}: ${esc(b.kwh)} kWh · ${esc(b.cost)}" data-height="${percent(b.kwh/max*100)}"></div>`).join('')}</div>
    <div class=axis><span>${lab(h.buckets[0].t)}</span><span>${lab(h.buckets[h.buckets.length-1].t)}</span></div>
  </section>
  <section class=card><h2>${L.byOutlet}</h2>
    <div class="legend mt-0">${h.per_outlet.map(p=>{const o=d.outlets.find(x=>x.n===p.n);return `<div><span>${esc(o?oname(o):L.outlet+' '+p.n)}</span><b><bdi>${num(p.kwh)} kWh</bdi></b></div>`}).join('')}</div>
  </section>
  <section class=card><h2>${L.month}</h2>
    <div class="total mt-4"><bdi>${money(spent,d.currency)}</bdi></div>
    <div class=muted><bdi>${num(d.month_kwh??0)} kWh</bdi> · ${L.at_price(`<bdi>${esc(d.price_kwh)} ${esc(d.currency)}</bdi>`)}</div>
    ${d.budget?`<h3 class="budget-heading">${L.budget}</h3><div class=meter><div data-width="${percent(pct)}" class="${pct>=90?'fill-bad':pct>=75?'fill-warn':'fill-ok'}"></div></div><div class=muted>${L.ofBudget(pct,`<bdi>${money(d.budget,d.currency)}</bdi>`)}</div>`:`<p class="muted estimate-copy">${L.noBudget}</p>`}
    <p class="muted estimate-copy">${L.estimate}</p></section>`;
  document.querySelectorAll('[data-height]').forEach(el=>{el.style.height=percent(el.dataset.height)+'%'});
  document.querySelectorAll('[data-width]').forEach(el=>{el.style.width=percent(el.dataset.width)+'%'});
}

/* ---------- alerts ---------- */
async function alerts(){
  const L=t(), {events}=await api('api/events?limit=100');
  if(events.length&&S&&S.unread_alerts){await api('api/events/read','POST',{through_id:events[0].id});S.unread_alerts=0;chrome()}
  const text=e=>{const f=L.ev[e.code];return f?(typeof f==='function'?f(e.params||{}):f):(L.eventNames[e.code]||e.text)};
  $('app').innerHTML=`<h1 class="page-heading">${L.alerts}</h1><section class="card compact-card"><div class=list>${events.map(e=>`
    <div class="item ev ${esc(['info','warn','alert'].includes(e.level)?e.level:'info')}"><span class=dotk>${ic(e.level==='info'?'info':'warn')}</span>
    <div class=grow><b>${esc(text(e))}</b><span class=muted>${new Date(e.ts*1000).toLocaleString(loc(),{dateStyle:'medium',timeStyle:'short'})}${e.mac?` · ${esc(label(S.devices.find(d=>d.mac===e.mac)||{name:e.mac}))}`:''}${e.outlet?` · ${L.outlet} ${esc(e.outlet)}`:''}${e.params?.actor!==undefined?` · ${L.actor}: ${esc(L.actorNames[e.params.actor]||e.params.actor)}`:''}</span></div></div>`).join('')
    ||`<div class=empty>${L.alertsEmpty}</div>`}</div></section>`;
}

/* ---------- settings ---------- */
const notificationPath=()=>currentUser?'api/me/notifications':'api/settings';
function stripFields(s,prefix){
  const L=t(), f=(k,lbl,extra='')=>`<label class=f>${lbl}<input id="${esc(prefix+k)}" ${k==='currency'?'type=text maxlength=8':'type=number inputmode=decimal'} ${extra} value="${esc(s[k]??'')}"></label>`;
  return `<div class=grid2>${f('price_kwh',L.price,'step=0.01 min=0 max=1000')}${f('currency',L.currency)}</div>${f('budget',L.budgetF,'step=0.01 min=0.01')}<h3>${L.limits}</h3><div class=grid2>${f('temp_max_c',L.tempMax,'min=30 max=120')}${f('power_max_w',L.powerMax,'min=100 max=10000')}</div>`;
}
function readStripFields(prefix){
  const g=k=>$(prefix+k).value.trim(), n=k=>g(k)===''?null:Number(g(k));
  return {currency:g('currency'),price_kwh:n('price_kwh'),budget:n('budget'),temp_max_c:n('temp_max_c'),power_max_w:n('power_max_w')};
}
const saveStripSettings=mac=>run(async()=>{await api(`api/strips/${mac}/settings`,'PUT',readStripFields('s_'+mac+'_'));toast(t().saved);await refresh()});
async function settings(){
  const L=t(), owners=currentUser?(S?.devices||[]).filter(canOwn):[];
  const [s,sessionList,perStrip]=await Promise.all([api(notificationPath()),currentUser?api('api/auth/sessions'):Promise.resolve({sessions:[]}),
    Promise.all(owners.map(async d=>[d,await api(`api/strips/${d.mac}/settings`)]))]);
  const f=(k,lbl,type='text',extra='')=>`<label class=f>${lbl}<input id=s_${k} type=${type} ${extra} value="${esc(s[k]??'')}"></label>`;
  $('app').innerHTML=`<h1 class="page-heading">${L.tabs[4]}</h1>
  ${accountSettings(sessionList.sessions)}
  <section class=card><h2>${L.appearance}</h2>
    <h3>${L.language}</h3><div class="seg mb-16" role=group>${[['ar','عربي'],['en','English']].map(([k,v])=>`<button aria-pressed=${k===lang} data-action="language" data-value="${esc(k)}">${v}</button>`).join('')}</div>
    <h3>${L.theme}</h3><div class=seg role=group>${THEMES.map(k=>`<button aria-pressed=${k===theme} data-action="theme" data-value="${esc(k)}">${L.themes[k]}</button>`).join('')}</div>
    ${theme==='clean'?`<h3 class="mt-16">${L.scheme}</h3><div class=seg role=group>${Object.entries(L.schemes).map(([k,v])=>`<button aria-pressed=${k===scheme} data-action="scheme" data-value="${esc(k)}">${v}</button>`).join('')}</div>`:''}</section>
  ${(S?S.devices:[]).map(d=>{const lv=d.rssi>=-60?0:d.rssi>=-70?1:d.rssi>=-80?2:3;
    const row=(k,v)=>`<div><span>${k}</span><b>${v}</b></div>`;
    return `<section class=card><h2>${L.stripInfo}${S.devices.length>1?' · '+esc(label(d)):''}</h2><div class="legend mt-0">
      ${row(L.conn,`<span class="${d.online?'text-ok':'text-bad'}">${d.online?L.online:L.offline}</span>`)}
      ${d.rssi?row(L.wifi,`<span class="${['text-ok','text-ok','text-warn','text-bad'][lv]}">${L.wifiLv[lv]}</span> <bdi class=muted>(${esc(d.rssi)} dBm)</bdi>`):''}
      ${d.ip?row(L.ipAddr,`<bdi>${esc(d.ip)}</bdi>`):''}${row(L.model,`<bdi>${esc(d.model)||'—'}</bdi>`)}
      ${row(L.fw,`<bdi>${esc(d.fw)||'—'}</bdi>`)}${row(L.mac,`<bdi>${esc(d.mac)}</bdi>`)}</div>
      ${d.rssi?`<p class="muted wifi-copy">${L.wifiHelp}</p>`:''}</section>`}).join('')}
  ${perStrip.map(([d,values])=>`<section class=card><h2>${L.stripSettings} · ${esc(label(d))}</h2>${stripFields(values,'s_'+d.mac+'_')}<button class="btn primary" data-action="strip-settings" data-mac="${esc(d.mac)}">${L.save}</button></section>`).join('')}
  ${!currentUser?`<section class=card><h2>${L.cost}</h2>${stripFields(s,'s_')}</section>`:''}
  <section class=card><h2 class="mb-6">${L.push}</h2><p class="muted push-help">${L.pushHelp}</p>
    ${f('ntfy_url',L.ntfy,'url','dir=ltr placeholder="https://ntfy.sh/…"')}
    <div class=grid2>${f('telegram_token',L.tgToken,'password',`dir=ltr autocomplete=off placeholder="${s.telegram_configured?L.tgSaved:''}"`)}${f('telegram_chat',L.tgChat,'text','dir=ltr inputmode=numeric')}</div>
    ${s.telegram_configured?`<button class="btn danger mb-14" data-action="clear-telegram">${ic('trash')}${L.clearTg}</button>`:''}
    <button class="btn plain full-width" data-action="test-push">${ic('send')}${L.sendTest}</button></section>
  ${currentUser?`<section class=card><h2>${L.alertPrefs}</h2><p class=muted>${L.alertPrefsHelp}</p>${(S?.devices||[]).map(d=>`<h3>${esc(label(d))}</h3><div class=checks>${Object.entries(s.alerts?.[d.mac]||{}).map(([code,enabled])=>`<label><input class=alertpref type=checkbox data-mac="${esc(d.mac)}" data-code="${esc(code)}" ${enabled?'checked':''}><span>${esc(L.eventNames[code]||code)}</span></label>`).join('')}</div>`).join('')}</section>`:''}
  <button class="btn primary full-width" data-action="save-settings">${L.save}</button>`;
}
function saveSettings(){run(async()=>{
  const g=k=>$('s_'+k).value.trim();
  const body={ntfy_url:g('ntfy_url'),telegram_chat:g('telegram_chat')};
  if(currentUser){body.alerts={};document.querySelectorAll('.alertpref').forEach(el=>{(body.alerts[el.dataset.mac]??={})[el.dataset.code]=el.checked})}
  else Object.assign(body,readStripFields('s_'));
  if(g('telegram_token')) body.telegram_token=g('telegram_token');      // empty field keeps the saved token
  await api(notificationPath(),'PUT',body);toast(t().saved);await refresh();settings();
})}
function testPush(){run(async()=>{
  const r=await api('api/alerts/test','POST',{},true);
  const L=t();toast(r.sent&&r.sent.length?L.sentVia(r.sent.join(', '))+(r.failed.length?` · ${r.failed.map(f=>f.channel+' '+L.failed).join(', ')}`:''):r.failed&&r.failed.length?r.failed.map(f=>`${f.channel}: ${f.error}`).join(' · '):L.noChannel);
})}

async function refresh(){
  if(!signedIn)return;
  if(pollBusy){refreshQueued=true;return}
  pollBusy=true;
  const revision=stateRevision;
  const patches=pollPatches=new Map();
  try{
    const state=await api('api/state');
    if(revision===stateRevision)applyState(patches.size?withDevices(state,state.devices.map(d=>patches.get(d.mac)||d)):state);
  }catch(e){if(signedIn)toast(e.message)}finally{
    pollBusy=false;pollPatches=null;
    if(refreshQueued){refreshQueued=false;refresh()}
  }
}
function applyState(state){
  const access=s=>JSON.stringify((s?.devices||[]).map(d=>[d.mac,d.role]));
  const different=access(S)!==access(state);S=state;chrome();draw(different);
}
function withDevices(state,devices){
  const first=devices[0];
  if(!first)return {...state,devices,month_kwh:0,month_cost:0};
  const totals=devices.some(d=>d.currency!==first.currency)?devices.slice(0,1):devices;
  return {...state,devices,currency:first.currency,price_kwh:first.price_kwh,budget:first.budget,
    month_kwh:totals.reduce((n,d)=>n+(d.month_kwh||0),0),month_cost:totals.reduce((n,d)=>n+(d.month_cost||0),0)};
}
function stopLive(){
  clearTimeout(liveTimer);clearTimeout(liveWatchdog);clearTimeout(liveDetails);
  liveTimer=liveWatchdog=liveDetails=null;liveReady=false;liveRetry=0;stateRevision++;
  const socket=liveSocket;liveSocket=null;if(socket)socket.close();
}
function reconnectLive(){
  if(!signedIn||!currentUser||liveTimer!==null)return;
  const delay=Math.min(30000,1000*2**Math.min(liveRetry++,5))*(0.75+Math.random()*0.5);
  liveTimer=setTimeout(()=>{liveTimer=null;connectLive()},delay);
}
function connectLive(){
  if(!signedIn||!currentUser||liveSocket||typeof WebSocket!=='function')return;
  const epoch=authEpoch, version=sessionVersion;
  let socket;
  try{socket=new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+'/api/ws')}
  catch(e){reconnectLive();return}
  liveSocket=socket;
  const current=()=>liveSocket===socket&&signedIn&&epoch===authEpoch;
  const watchdog=()=>{
    clearTimeout(liveWatchdog);
    liveWatchdog=setTimeout(()=>{if(current()){liveReady=false;socket.close()}},55000);
  };
  watchdog();
  socket.onmessage=event=>{
    if(!current())return;
    let message;
    try{message=JSON.parse(event.data)}catch(e){liveReady=false;socket.close();return}
    watchdog();
    if(message.type==='state'){
      liveReady=true;liveRetry=0;stateRevision++;applyState(message);
    }else if(message.type==='strip'&&S){
      pollPatches?.set(message.strip.mac,message.strip);
      const devices=S.devices.filter(d=>d.mac!==message.strip.mac);
      const index=S.devices.findIndex(d=>d.mac===message.strip.mac);
      devices.splice(index<0?devices.length:index,0,message.strip);
      applyState(withDevices(S,devices));
    }else if(message.type==='access'){
      stateRevision++;if(S)S={...S,devices:[],unread_alerts:0};pending={};energyMac=null;
      chrome();draw(false);refresh();
    }else if(message.type==='event'||message.type==='ping'){
      if(S&&Number.isInteger(message.unread_alerts)){S.unread_alerts=message.unread_alerts;chrome()}
      if(message.type==='event'&&['alerts','rules'].includes(tab)&&liveDetails===null){
        liveDetails=setTimeout(()=>{liveDetails=null;if(current())draw(true)},2000);
      }
    }
  };
  socket.onerror=()=>{if(current()){liveReady=false;socket.close()}};
  socket.onclose=async event=>{
    if(!current())return;
    liveSocket=null;liveReady=false;clearTimeout(liveWatchdog);liveWatchdog=null;
    if(event.code===4401&&!(await refreshSession(version))){
      if(signedIn&&epoch===authEpoch)showAuth('login',t().sessionExpired);
      return;
    }
    if(signedIn&&epoch===authEpoch)reconnectLive();
  };
}
async function bootstrap(){
  const epoch=authEpoch;
  try{
    const state=await api('api/state');
    const {r,j}=await requestJSON('api/auth/me'); // A working legacy credential has no account profile.
    if(epoch!==authEpoch)return;
    S=state;currentUser=r.ok?j.user:null;signedIn=true;chrome();await draw(true);connectLive();
  }catch(e){if(epoch===authEpoch)showAuth('login',t().networkError)}
}

/* One delegated dispatcher for every interaction, including the shared dialog.
   No evaluation of attribute values; all actions are explicitly registered. */
let dialogSubmit=null, dialogClose=null;
const ACTIONS={
  'toggle-language':['click',()=>setLang(lang==='ar'?'en':'ar')],
  logout:['click',()=>logout()], go:['click',el=>go(el.dataset.value)],
  'password-visibility':['click',el=>togglePassword(el.dataset.id,el)],
  authenticate:['submit',el=>submitAuth(el)],
  'show-auth':['click',el=>showAuth(el.dataset.value||'login')],
  'auth-theme':['click',el=>{setTheme(el.dataset.value);renderAuth()}],
  'change-password':['submit',el=>changePassword(el)],
  'sign-out-session':['click',el=>signOutSession(el.dataset.id,el.dataset.current==='true')],
  'open-claim':['click',()=>openClaim(true)],
  rename:['click',el=>rename(el.dataset.mac,+el.dataset.outlet)],
  switch:['click',el=>cmd(el.dataset.mac,+el.dataset.outlet,el.dataset.on==='true')],
  people:['click',el=>people(el.dataset.mac)], unclaim:['click',el=>unclaimDialog(el.dataset.mac)],
  leave:['click',el=>leaveStrip(el.dataset.mac)],
  'retry-claim':['click',()=>{claimState=null;openClaim()}],
  'close-dialog':['click',()=>$('dlg').close()],
  'change-role':['change',el=>changeRole(+el.dataset.id,el.value)],
  'remove-person':['click',el=>removePerson(+el.dataset.id)], transfer:['click',el=>transferStrip(+el.dataset.id)],
  'rule-enable':['click',el=>ruleOn(el.dataset.id,el.dataset.enabled==='true')],
  'rule-delete':['click',el=>ruleDel(el.dataset.id)],
  'rule-kind':['click',el=>{ruleKind=el.dataset.value;return rules()}], 'rule-add':['click',()=>ruleAdd()],
  'energy-strip':['change',el=>{energyMac=el.value;return energy()}],
  'energy-range':['click',el=>{range=el.dataset.value;return energy()}],
  language:['click',el=>setLang(el.dataset.value)],
  theme:['click',el=>{setTheme(el.dataset.value);return settings()}],
  scheme:['click',el=>{setScheme(el.dataset.value);return settings()}],
  'strip-settings':['click',el=>saveStripSettings(el.dataset.mac)],
  'clear-telegram':['click',async()=>{await api(notificationPath(),'PUT',{telegram_token:''});toast(t().saved);await settings()}],
  'test-push':['click',()=>testPush()], 'save-settings':['click',()=>saveSettings()],
};
function dispatchAction(event){
  if(event.type==='close'){if(event.target===$('dlg')&&dialogClose)dialogClose();return}
  const el=event.target.closest('[data-action]');
  if(!el||el.disabled)return;
  if(el.dataset.action==='dialog'){
    if(event.type==='submit'&&dialogSubmit){event.preventDefault();run(()=>dialogSubmit(el))}
    return;
  }
  const action=Object.prototype.hasOwnProperty.call(ACTIONS,el.dataset.action)?ACTIONS[el.dataset.action]:null;
  if(!action||action[0]!==event.type)return;
  if(event.type==='submit')event.preventDefault();
  run(()=>action[1](el));
}
for(const type of ['click','change','submit','close'])document.addEventListener(type,dispatchAction,type==='close');

setTheme(theme);setScheme(scheme);setLang(lang);
bootstrap();setInterval(()=>{if(signedIn&&!document.hidden&&!liveReady)return refresh()},2000);setInterval(pollClaim,1000);
