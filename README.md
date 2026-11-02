# notebooklm-lab — مختبر NotebookLM لصنّاع المحتوى العرب

> **English summary.** `notebooklm-lab` is **my own prototype** (author: muhamed khalifa) that sits **on top of** the third-party library
> [**notebooklm-py**](https://github.com/teng-lin/notebooklm-py) (by **Teng Lin**, MIT License) to automate Google NotebookLM:
> create a notebook, add links/files, get **cited** answers, generate an **Arabic audio overview**, briefing doc, study guide, mind map…, download everything,
> and produce an **Arabic right-to-left HTML report**. It also ships an **offline sample mode** that works with no login.
> `notebooklm-py` is an **unofficial** library that uses **undocumented Google APIs** and is **not affiliated with Google**; this repo is likewise unofficial and not affiliated with Google.
> The upstream library is installed as a **pinned dependency** (`notebooklm-py==0.8.6`); none of its code is copied here.
> Quick start (Windows PowerShell): `.\scripts\setup.ps1` → `python -m notebooklm_lab demo --open`.

---

## ١. ما هذا المشروع؟ (بتشبيه بسيط)

تخيّل أن **NotebookLM** مكتبة ذكية تقرأ كل ما تعطيها من مقالات وفيديوهات وملفات، ثم تجيب عن أسئلتك **مع ذكر المصدر**، وتستطيع أيضًا تحويل ما قرأته إلى **بودكاست صوتي** وملخصات وخرائط ذهنية.

وهذا المشروع هو **سكرتير آلي**: تعطيه قائمة روابط، فيدخل المكتبة **بمفتاحك الشخصي** (تسجيل دخولك أنت إلى حساب Google على جهازك)، ويطلب منها كل ما تحتاجه، ثم يضع لك النتائج في **مجلد مرتب** مع **تقرير عربي** تفتحه في المتصفح.

| في التشبيه | في الواقع |
|---|---|
| المكتبة الذكية | Google NotebookLM (أصبح يُسمّى Gemini Notebook منذ يوليو 2026، والمكتبة تعمل بنفس الطريقة) |
| ناقل المفتاح / طريقة الدخول | المكتبة الخارجية `notebooklm-py` (من تطوير Teng Lin) |
| السكرتير وخطة العمل | هذا المشروع `notebooklm-lab` (عملي الخاص، مبني فوقها) |
| المفتاح الشخصي | ملف جلسة الدخول على جهازك (انظر القسم ٥) |

## ٢. ⚠ تنبيهات مهمة وصريحة

* **أداة غير رسمية وغير مرتبطة بـ Google.** المكتبة التي نعتمد عليها تقول في صفحتها بوضوح: *Unofficial Library – Use at Your Own Risk*، وأنها **تستخدم واجهات Google غير الموثّقة** وقد تتوقف عن العمل في أي وقت، وأن **الاستخدام المكثف قد يُبطَّأ (rate limits)**، وأنها مناسبة **للنماذج الأولية والبحث والمشاريع الشخصية**.
* **شروط الاستخدام:** صفحة المكتبة لا تتناول شروط خدمة Google صراحةً. استخدام واجهات غير موثّقة عبر حسابك قد لا يتوافق مع شروط Google وقد يؤدي إلى تقييد الطلبات. لذلك: **استخدم حسابًا مخصصًا للتجارب إن أمكن** (توصية المكتبة نفسها للاستخدام غير المراقَب)، ولا تستخدم الأداة على نطاق واسع.
* **الوضع الحقيقي لم يُختبر بعد بحساب Google حقيقي** (الجهاز الذي بُني عليه المشروع لا يملك حساب Google). المختبَر فعليًا: الوضع التجريبي، والاختبارات، وتشغيل خادم MCP وعرض أدواته. انظر القسم ١١.
* **ملف تسجيل الدخول = مفتاح حسابك.** لا ترسله ولا ترفعه ولا تضعه في GitHub. المشروع يمنع ذلك عبر `.gitignore` وفحص أسرار آلي.

## ٣. الاعتماد على المكتبة الأصلية والترخيص (Credits)

| | |
|---|---|
| المكتبة | **notebooklm-py** — «Unofficial Python library for automating Google NotebookLM» |
| المؤلف | **Teng Lin** (والمساهمون في المستودع) |
| المستودع | https://github.com/teng-lin/notebooklm-py |
| PyPI | https://pypi.org/project/notebooklm-py/ |
| الترخيص | **MIT** (حقوق النشر © 2026 Teng Lin) |
| الإصدار المثبّت هنا | `notebooklm-py[browser,mcp]==0.8.6` |

* هذا المشروع **عملي الخاص** (© 2026 muhamed khalifa، ترخيص MIT — انظر `LICENSE`)، **مبني فوق** المكتبة ويستورد منها فقط عبر `pip`. **لم يُنسخ أي كود منها** إلى هذا المستودع، وهناك اختبار آلي يتحقق من ذلك.
* ليس لي أي انتماء إلى Google أو إلى مؤلف المكتبة، ولا يوجد تزكية منهم لهذا المشروع.

## ٤. ماذا تدعم المكتبة فعليًا؟ (حسب وثائقها، الإصدار 0.8.6)

* **الدفاتر:** إنشاء، نسخ، قائمة، إعادة تسمية، حذف.
* **المصادر:** روابط ويب، **يوتيوب**، ملفات (PDF، نص، Markdown، Word، EPUB، صوت، فيديو، صور)، Google Drive، نص ملصوق.
* **المحادثة:** أسئلة مع **استشهادات** (مراجع المصدر والمقتطف)، سجل المحادثة، حفظ الإجابة كملاحظة.
* **المخرجات (Studio):** نظرة صوتية/بودكاست (4 أنماط، 3 أطوال، **50+ لغة بينها العربية `ar_001`**)، فيديو، عرض شرائح (PDF/PPTX)، إنفوجرافيك، اختبار، بطاقات تعليمية، **تقرير** (Briefing doc / Study guide / Blog post / مخصص)، جدول بيانات، **خريطة ذهنية**.
* **التنزيل:** ملفات صوت، فيديو، PDF/PPTX، PNG، CSV، JSON، Markdown.
* **أخرى:** بحث ويب/Drive تلقائي، مشاركة، واجهة CLI، **خادم MCP جاهز**، و**مهارة (skill)** لوكلاء الذكاء الاصطناعي.

**ما يستخدمه هذا المشروع:** إنشاء دفتر ← إضافة روابط/يوتيوب/ملفات ← أسئلة بالعربية مع استشهادات ← `briefing` و`study_guide` و`mind_map` و`audio` (+ اختياري `quiz` و`flashcards` و`slide_deck`) ← تنزيل ← تقرير HTML عربي.

## ٥. التثبيت على Windows (PowerShell) — خطوة بخطوة

1. ثبّت **Python 3.10 أو أحدث** من https://www.python.org/downloads/ (فعّل خيار *Add python.exe to PATH*).
2. افتح **PowerShell** داخل مجلد المشروع (في المستكشف: اضغط Shift + كليك يمين ← *Open PowerShell window here*).
3. شغّل أداة الإعداد (تنشئ بيئة معزولة `.venv` وتثبّت المكتبات المثبّتة الإصدارات وتجري الفحوصات):

```powershell
Set-ExecutionPolicy -Scope Process Bypass     # يسمح بتشغيل السكربت لهذه النافذة فقط
.\scripts\setup.ps1
```

أو يدويًا:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pip install -e .
python -m notebooklm_lab selfcheck
```

4. جرّب **الوضع التجريبي** (لا يحتاج حسابًا):

```powershell
python -m notebooklm_lab demo --open
```

> ملاحظة: قد تظهر الحروف العربية في نافذة PowerShell القديمة مقلوبة أو متقطعة؛ هذا من الطرفية نفسها وليس من الأداة. **افتح التقرير `report.html` في المتصفح** لرؤية العربية بشكل صحيح من اليمين إلى اليسار.

## ٦. تسجيل الدخول (مرة واحدة) — كيف يعمل؟

```powershell
python -m notebooklm_lab login          # يفتح نافذة متصفح؛ سجّل دخولك إلى حساب Google الخاص بك
python -m notebooklm_lab login-check    # يتحقق أن الجلسة تعمل
```

* **تسجّل أنت بنفسك** في حساب Google الخاص بك، **على جهازك أنت**، داخل نافذة متصفح تفتحها المكتبة (Chromium). **لا يُطلب منك كتابة كلمة السر في هذه الأداة**، ولا يراها أحد غيرك.
* في أول مرة تنزّل المكتبة متصفح Chromium (حوالي **170 ميغابايت**، دون شريط تقدّم، فانتظر). إن فشل: `playwright install chromium`.
* على Windows: **لا تستخدم** الخيار `--browser-cookies chrome` (تشفير Chrome الجديد يعطّله حسب وثائق المكتبة)؛ استخدم الدخول العادي أعلاه.

### أين تُحفظ جلسة الدخول؟
* في **جهازك فقط**، افتراضيًا: `C:\Users\<اسمك>\.notebooklm\profiles\default\` وفيها:
  * `storage_state.json` — ملف الكوكيز (**هو المفتاح الحساس**).
  * `browser_profile\` — ملف المتصفح (أحجامه تظهر في الأمر أدناه).
* تستطيع تغيير المكان بالمتغير `NOTEBOOKLM_HOME`.
* **لا يُحفظ شيء من هذا داخل مجلد المشروع**، و`.gitignore` يمنع رفع أي ملف من هذا النوع.

### كيف أعرف المكان والحجم؟ وكيف أحذف الجلسة؟
```powershell
python -m notebooklm_lab session where            # المكان والحجم (لا يعرض محتوى الملفات أبدًا)
python -m notebooklm_lab session delete           # يعرض ما سيُحذف فقط
python -m notebooklm_lab session delete --yes     # يحذف الجلسة المحلية فعلًا
```
الحذف يزيل **النسخة المحلية** فقط. لإبطال الجلسة من جهة Google أيضًا افتح https://myaccount.google.com/device-activity وسجّل الخروج من الأجهزة. وحذف متصفح Chromium الذي نزّله Playwright (اختياري) يكون بحذف مجلد `ms-playwright` داخل `%LOCALAPPDATA%` عادةً.

## ٧. الاستخدام: من قائمة روابط إلى ملخص وبودكاست بالعربية

أنشئ ملف `links.txt` (سطر لكل رابط أو ملف؛ الأسطر التي تبدأ بـ `#` تُتجاهل) — انظر `examples/links.txt`:

```powershell
# الوضع الحقيقي (بعد تسجيل الدخول):
python -m notebooklm_lab digest --file links.txt --title "ملخص الأسبوع" --open

# أو روابط مباشرة + ملف محلي:
python -m notebooklm_lab digest https://example.com/article https://www.youtube.com/watch?v=VIDEO_ID .\notes.pdf

# اختيار المخرجات واللغة والأسئلة:
python -m notebooklm_lab digest --file links.txt --outputs briefing,audio,mind_map,quiz --language ar_001 --question "ما أبرز 5 أفكار لفيديو قصير؟"

# تجريبي بلا حساب (بيانات مثال فقط):
python -m notebooklm_lab digest --file links.txt --sample
```

ما الذي يحدث بالترتيب: إنشاء دفتر ← إضافة المصادر (فشل مصدر واحد لا يوقف الباقي) ← 3 أسئلة افتراضية بالعربية مع استشهادات ← توليد المخرجات وتنزيلها (فشل مخرج لا يوقف الباقي) ← كتابة `report.html` و`run.json`.

* **اللغة:** الافتراضي `ar_001` (العربية). عدّلها بـ `--language` (القائمة: `notebooklm language list`). أسئلة المحادثة تُكتب بالعربية داخل الأداة، ولا نغيّر إعداد اللغة العام لحسابك.
* **المخرجات المتاحة:** `briefing`, `study_guide`, `mind_map`, `audio`, `quiz`, `flashcards`, `slide_deck`. الافتراضي: `briefing,study_guide,mind_map,audio`.
* **الوقت:** توليد الصوت قد يستغرق عدة دقائق (المهلة حتى 20 دقيقة). **وكل توليد يستهلك حصة حسابك** في Google.

## ٧-ب. الملخص الصباحي التلقائي (`morning`)

### ماذا يفعل؟
تلصق روابط (يوتيوب أو مقالات) في ملف نصي بسيط طوال اليوم، وفي الصباح يأخذ الأمر **الروابط الجديدة فقط** ويضعها في دفتر NotebookLM باسم مؤرَّخ مثل «ملخص صباحي 2026-11-03»، ثم يُنتج:

1. **ملخصًا مكتوبًا بالعربية** (Briefing)،
2. **بودكاست صوتيًا بالعربية** (Audio Overview)،
3. **تقريرًا قصيرًا بالعربية** `morning_report.md` + تقريرًا كاملًا `report.html`،

ويحفظها كلها في **مجلد باسم تاريخ اليوم**. ويسجّل الروابط التي عولجت فلا تتكرر في اليوم التالي. إن لم تكن هناك روابط جديدة يكتب رسالة عربية ويخرج بهدوء دون أن يستهلك شيئًا من حصتك.

### كيف أضيف الروابط؟
افتح الملف `inbox.txt` (مكانه في الأسفل — يُنشأ تلقائيًا أول مرة) بالمفكرة (Notepad) وألصق **رابطًا واحدًا في كل سطر**:

```text
# هذه ملاحظة (الأسطر التي تبدأ بعلامة # تُتجاهل)
https://www.youtube.com/watch?v=VIDEO_ID
https://example.com/some-article    # يمكن كتابة ملاحظة بعد مسافة وعلامة #

```
الأسطر الفارغة تُتجاهل، والرابط المكرر يُؤخذ مرة واحدة (حتى لو كُتب بصيغتين مثل `youtu.be/ID` و`youtube.com/watch?v=ID`). **لا تحذف الروابط القديمة من الملف**، فالأداة تتذكر ما عولج. سطر غير صالح (ليس رابط http/https) يُبلَّغ عنه ويُتجاهل.

### كيف أشغّله؟
```powershell
python -m notebooklm_lab morning --sample      # تجربة كاملة بدون حساب وبدون إنترنت (بيانات مثال فقط)
python -m notebooklm_lab login                 # مرة واحدة فقط (انظر القسم ٦)
python -m notebooklm_lab morning               # التشغيل الحقيقي: الروابط الجديدة فقط
python -m notebooklm_lab morning status        # آخر تشغيل، عدد الروابط، وأين الملفات
python -m notebooklm_lab morning --open        # يفتح التقرير في المتصفح عند الانتهاء
```
* الوضع `--sample` يستخدم **ملف حالة ومجلد مخرجات منفصلين** (`morning-sample`)، فتجربته لا «تستهلك» روابطك الحقيقية.
* خيارات: `--audio-timeout 30` (دقائق الانتظار للبودكاست، الافتراضي 20)، `--max-links 20` (أقصى عدد روابط في التشغيل الواحد؛ الباقي يبقى للتشغيل التالي).
* **عند الأعطال:** انتهاء تسجيل الدخول ← رسالة واضحة (شغّل `login` من جديد) والروابط تبقى «جديدة» ولا تضيع. توليد البودكاست بطيء ← ينتظر حتى المهلة ثم يحتفظ بالملخص المكتوب ويكتب في التقرير أن الصوت لم يُنشأ. رابط واحد سيّئ ← يُتخطى والباقي يكتمل؛ ويُعاد تجريبه مرة واحدة في تشغيل لاحق ثم يُسجَّل «فاشل». كل تشغيل **يستهلك حصة حسابك في Google**.
* ملاحظة: إذا نجح الملخص المكتوب وفشل الصوت فقط، تُعتبر الروابط «معالَجة» ولا تُعاد تلقائيًا (أعد إضافة الرابط يدويًا بتعديل بسيط في الملف لو أردت إعادته: غيّر الرابط بإضافة `?x=1`، أو احذف سجله من `morning_state.json`).

### الجدولة على Windows (جهازك الشخصي) — الأساس
```powershell
python -m notebooklm_lab morning schedule --time 07:30             # يطبع الأمر فقط (لا يغيّر شيئًا)
python -m notebooklm_lab morning schedule --time 07:30 --install  # ينشئ مهمة يومية في «مجدول مهام Windows»
schtasks /Query /TN "NotebookLM-Lab Morning"                       # للتأكد من وجودها
schtasks /Run /TN "NotebookLM-Lab Morning"                         # لتجربتها الآن
python -m notebooklm_lab morning unschedule                        # لإزالتها
```
* تعمل المهمة **فقط والجهاز مفتوح وأنت مسجّل الدخول** عند الوقت المحدد؛ وإن كان مطفأً لا تُشغَّل ذلك اليوم (يمكنك تفعيل «Run task as soon as possible after a scheduled start is missed» من خصائص المهمة في برنامج Task Scheduler). ستظهر نافذة سوداء أثناء العمل وقد يستغرق البودكاست عدة دقائق.
* **استخدم نفس Python الذي ثبّتّ فيه المشروع** (إن كنت تستخدم بيئة `.venv` فشغّل أمر الجدولة من داخلها؛ الأداة تكتب مسار Python الحالي في المهمة).

### الجدولة على خادم VPS (لينكس) — cron
```bash
python -m notebooklm_lab morning schedule --time 07:30 --target cron             # يطبع سطر cron
python -m notebooklm_lab morning schedule --time 07:30 --target cron --install   # يضيفه إلى crontab
crontab -l                                                                       # للتحقق
python -m notebooklm_lab morning unschedule --target cron                        # يزيله (ولا يلمس مهام cron الأخرى)
```
سجلّ التشغيل في `morning.cron.log` و`morning.log` داخل مجلد البيانات.

> ⚠ **تنبيه تسجيل الدخول على الـ VPS:** الخادم لا يملك متصفحًا، لذلك **سجّل الدخول على جهازك (PC)** بـ `python -m notebooklm_lab login` ثم **انسخ ملف الجلسة** (`storage_state.json` داخل `~/.notebooklm/profiles/default/`، ويمكنك معرفة مكانه بـ `python -m notebooklm_lab session where`) إلى المسار نفسه على الخادم بأداة آمنة مثل `scp`. هذا الملف **يعادل كلمة سر حسابك**: لا ترفعه إلى Git ولا ترسله لأحد. وقد **تطلب Google إعادة تسجيل الدخول** بعد فترة، أو **تعتبره دخولًا مشبوهًا** (لأن الـ IP تغيّر إلى عنوان خادم) فتحجب الجلسة أو تطلب تحققًا — عندها كرّر تسجيل الدخول على الـ PC وانسخ الملف من جديد. لا تُسجّل الدخول بحسابك الأساسي المهم إن كنت قلقًا؛ ويُفضّل حساب Google مخصص لهذا الغرض.

### أين تُحفظ الملفات؟ وكيف أحذفها؟
المجلد الافتراضي (على Windows: `C:\Users\اسمك\NotebookLM-Lab`، ولينكس: `~/NotebookLM-Lab`). غيّره بـ `--data-dir` أو المتغير `NOTEBOOKLM_LAB_DATA`.

```text
NotebookLM-Lab\
├─ inbox.txt                 ← ألصق روابطك هنا
├─ morning_state.json        ← ذاكرة الروابط التي عولجت وآخر تشغيل
├─ morning.log               ← سجلّ التشغيلات
├─ morning\2026-11-03\       ← مجلد اليوم (تشغيل ثانٍ في اليوم نفسه: 2026-11-03-2)
│   ├─ morning_report.md     ← التقرير القصير بالعربية
│   ├─ report.html           ← التقرير الكامل (RTL)
│   ├─ run.json
│   └─ files\ (الملخص المكتوب + البودكاست الصوتي)
└─ morning-sample\          ← مخرجات التجربة فقط
```
* **الحذف:** احذف مجلد يوم معيّن من File Explorer، أو:
  `python -m notebooklm_lab outputs delete --all --yes --out "C:\Users\اسمك\NotebookLM-Lab\morning"`.
  لحذف «ذاكرة» الروابط (فتُعالَج الروابط من جديد) احذف `morning_state.json`. مجلد البيانات كله يمكن حذفه بأمان؛ لا يحتوي على جلسة الدخول (تلك في `~/.notebooklm`، وتُحذف بـ `session delete --yes`).
* دفاتر NotebookLM نفسها تبقى في حسابك على موقع NotebookLM حتى تحذفها من هناك.
* كل هذه الملفات **مستبعدة من Git**؛ ولا تضع روابط خاصة أو بيانات حقيقية في المستودع.

## ٨. أين تُحفظ المخرجات؟ وكم حجمها؟ وكيف أراها أو أحذفها؟

* المكان: `outputs\` داخل المجلد الذي شغّلت منه الأمر (تغييره: `--out` أو المتغير `NOTEBOOKLM_LAB_OUTPUT`). لكل تشغيل مجلد باسم الوقت، فيه `report.html` و`run.json` ومجلد `files\` للمخرجات.
* **الحجم:** النصوص (Markdown/JSON) بضعة كيلوبايت. أما **البودكاست الصوتي** فعادةً **عدة ميغابايت** (يختلف بطول الحلقة)، والفيديو/الشرائح أكبر. أمر الحجم الدقيق:

```powershell
python -m notebooklm_lab outputs where            # المكان وعدد التشغيلات والحجم الكلي
python -m notebooklm_lab outputs open             # يفتح آخر تقرير في المتصفح
python -m notebooklm_lab outputs delete --run 20261102-183000-xxxx          # يعرض ما سيُحذف
python -m notebooklm_lab outputs delete --all --yes                         # يحذف كل التشغيلات
```
* الحذف يقتصر على مجلدات التشغيل التي تحتوي `run.json` داخل مجلد المخرجات فقط. وكل المخرجات **مستبعدة من Git** (`outputs/` وملفات الصوت والفيديو).

## ٩. التكامل مع وكلاء الذكاء الاصطناعي: Claude Code و Codex و Hermes

**المكتبة تأتي بخادم MCP خاص بها** (الأمر `notebooklm-mcp`، يحتوي 38 أداة منها `notebook_create` و`source_add` و`chat_ask` و`studio_generate` و`studio_download`) **وبمهارة (skill) جاهزة**، لذلك **لم أكتب خادم MCP خاصًا بي**؛ نستعمل الخادم الأصلي كما هو، وهذا المشروع يعطيك الإعدادات الجاهزة لثلاثة وكلاء:

```powershell
python -m notebooklm_lab agents all        # يطبع الإعدادات الثلاثة، مع مسار Python الخاص بك
python -m notebooklm_lab agents claude
python -m notebooklm_lab agents codex
python -m notebooklm_lab agents hermes
python -m notebooklm_lab selfcheck --mcp   # يشغّل خادم MCP فعلًا ويعرض أدواته (بدون حساب Google)
```

الصيغ التي يطبعها الأمر (مع مسار Python لبيئتك):

| الوكيل | الإعداد |
|---|---|
| **Claude Code** | `claude mcp add notebooklm -- <python> -m notebooklm.mcp` — ومهارة المكتبة: `notebooklm skill install` |
| **Codex** | `codex mcp add notebooklm -- <python> -m notebooklm.mcp` أو في `~/.codex/config.toml`: `[mcp_servers.notebooklm]` مع `command` و`args = ["-m","notebooklm.mcp"]` — ومثبّت المهارة `notebooklm skill install` يكتب أيضًا مجلد Agent Skills العام (`~/.agents/skills`) — لم أتحقق أن نسختك من Codex تقرؤه |
| **Hermes Agent** | في `~/.hermes/config.yaml`: `mcp_servers:` ← `notebooklm:` ← `command` و`args: ["-m","notebooklm.mcp"]` ثم إعادة تشغيل Hermes |

تفاصيل أكثر وملاحظات الأمان في [`docs/AGENTS_SETUP.md`](docs/AGENTS_SETUP.md). وفي جذر المشروع ملفا `AGENTS.md` و`CLAUDE.md` يشرحان للوكلاء قواعد العمل هنا.

> **صدق الاختبار:** تم فعليًا تشغيل خادم MCP والتحقق من قائمة أدواته (38 أداة) بالـ SDK الرسمي `mcp`. **لم يتم** تشغيل Claude Code أو Codex أو Hermes نفسها ولا استدعاء أي أداة بحساب حقيقي؛ الإعدادات مبنية على وثائق كل أداة وغير مجرّبة عليها.

## ١٠. الأمان وعدم تسريب الأسرار

* `.gitignore` يغطي: `.env*` و`*.pem` و`*.key` وملفات الكوكيز و`storage_state*.json` و`master_token*.json` و`auth*.json` ومجلدات `outputs/` و`downloads/` وملفات الصوت والفيديو والكاش وبيئات `venv`.
* فحص أسرار مدمج يفحص كل ما سيُرفع (ملفات git المتتبَّعة وغير المستبعَدة): مفاتيح خاصة، رموز GitHub/AWS/Google/Slack، كوكيز Google، شكل ملف `storage_state`، كلمات سر مكتوبة، أسماء ملفات ممنوعة، ومسارات أجهزة التطوير:

```powershell
python -m notebooklm_lab secrets-scan
python -m notebooklm_lab selfcheck        # يشمل: الإصدار المثبّت، الوضع التجريبي، .gitignore، فحص الأسرار
```
* قبل أن ترفع المشروع إلى GitHub شغّل الأمرين أعلاه. القيم المكتشفة تُطبع **مخفية**.

## ١١. ما الذي تم اختباره وما الذي لم يُختبر؟

| البند | الحالة |
|---|---|
| الوضع التجريبي (`demo` و`digest --sample`) من البداية للنهاية + تقرير RTL | ✔ مُختبر آليًا ويدويًا |
| الوحدات: التصنيف، التقرير، الهروب من HTML، الأسرار، التخزين والحذف، الأوامر | ✔ اختبارات pytest |
| مسار الوضع الحقيقي مقابل **عميل مزيّف** (يتحقق أن الأداة تستدعي المكتبة بالوسائط الصحيحة: `ar_001`، `wait=True`، الصيغ…) | ✔ مُختبر، لكنه **لا يثبت** أن Google تقبل الطلبات |
| `morning`: قراءة الروابط والتكرار وملف الحالة ومسار «لا روابط جديدة» والتشغيل التجريبي الكامل مرتين (الثاني يقول لا جديد) | ✔ اختبارات pytest + تشغيل يدوي |
| `morning`: الأعطال (تسجيل دخول منتهٍ، مهلة الصوت، رابط سيّئ) | ✔ مُختبرة بواجهات مزيّفة فقط، **لا** مع Google الحقيقية |
| `morning schedule/unschedule` لـ cron: تثبيت وإزالة فعليان على Linux | ✔ جُرّبا فعليًا (لكن لم يُراقَب تشغيل cron في موعده) |
| `morning schedule --install` على **Windows** (`schtasks`) | ✘ لم يُجرَّب على Windows؛ الأمر المولَّد مغطى باختبارات نصية فقط |
| الوضع الحقيقي مع **حساب Google فعلي** (إنشاء دفتر، رفع، بودكاست عربي) — ومنه `morning` الحقيقي | ✘ **لم يُجرَّب** — يحتاج تسجيل دخولك |
| خادم MCP الأصلي يبدأ ويعرض 38 أداة | ✔ مُختبر بالـ SDK الرسمي |
| Claude Code / Codex / Hermes يستخدمونه فعليًا | ✘ لم يُجرَّب |
| سكربت `scripts/setup.ps1` على Windows | ✘ لم يُجرَّب على Windows (كُتب وفق الأوامر اليدوية المختبرة على Linux) |

تشغيل الاختبارات: `pytest -q`.

## ١٢. هيكل المشروع

```
src/notebooklm_lab/   الكود: cli, pipeline, real_backend, sample_backend, report, storage, secrets_scan, selfcheck, agents,
                      morning (الملخص الصباحي), inbox (الروابط والحالة), scheduler (schtasks/cron)
tests/                اختبارات pytest
docs/AGENTS_SETUP.md  إعداد الوكلاء ·  docs/sample_report_preview.html  معاينة تقرير تجريبي
examples/             links.txt و sample_notes.md
scripts/setup.ps1     إعداد Windows
```

## ١٣. الترخيص
هذا المشروع: MIT © 2026 muhamed khalifa (انظر `LICENSE`). المكتبة notebooklm-py: MIT © 2026 Teng Lin، وتُثبَّت كاعتماد منفصل بترخيصها الأصلي. Google وNotebookLM وGemini علامات تجارية لأصحابها.
