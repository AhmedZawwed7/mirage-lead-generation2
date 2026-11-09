# Mirage Leads Hunter

منصة ويب عربية RTL للبحث عن الشركات وإدارة العملاء المحتملين، مع صلاحيات فريق ومتابعة وتصدير.

## التشغيل المحلي
1. استخدم Python 3.10 أو أحدث.
2. نفّذ: pip install -r requirements.txt
3. انسخ .env.example واضبط SECRET_KEY عشوائيًا بطول 32 بايت على الأقل وMIRAGE_ADMIN_PASSWORD بكلمة مرور قوية وفريدة. فعّل COOKIE_SECURE=1 خلف HTTPS.
4. شغّل python app.py ثم افتح /login.

## التشغيل باستخدام Docker
1. انسخ `.env.example` إلى `.env` واضبط الأسرار.
2. شغّل `docker compose up -d --build`.
3. افتح `http://localhost:8000/login`.
4. البيانات تحفظ في Docker volume دائم باسم `mirage_data`.

تفاصيل أكثر: [دليل Docker](docs/DOCKER_RUN_AR.md).

## البحث والاستخراج
- يدعم SerpAPI عبر SERPAPI_KEY.
- يدعم Google Programmable Search عبر GOOGLE_API_KEY وGOOGLE_CX.
- يستخدم DuckDuckGo عند عدم إعداد مفاتيح مدفوعة.
- يفحص الموقع وصفحات اتصل بنا/تواصل معنا عند الحاجة.
- يجمع بيانات الاتصال المنشورة علنًا ويعطي العميل تقييمًا مبدئيًا.

## إدارة العملاء
- لوحة مؤشرات وسجل عمليات البحث.
- منع تكرار الهاتف والموقع.
- حالات العملاء: جديد، تم التواصل، مؤهل، تم البيع، مفقود، عدم التواصل.
- تعيين مسؤول وملاحظات متابعة، مع صلاحيات مختلفة للمدير والباحث وموظف المبيعات.
- تسجيل أنشطة العميل من صف العميل (مكالمة، ملاحظة، بريد، اجتماع أو WhatsApp) والرجوع إلى سجل النشاط.
- إنشاء مهام متابعة بتاريخ استحقاق وتعيينها لموظف المبيعات المسؤول، مع قائمة للمهام ومؤشرات للمهام المفتوحة والمتأخرة.
- حماية نطاق المهام: موظف المبيعات لا يرى أو يعدل مهام عميل لم يعد مسندًا إليه، والتحقق من صحة تاريخ الاستحقاق.
- فتح محادثة WhatsApp يدويًا، دون إرسال تلقائي.
- تصدير CSV وExcel.

## الأمان والحدود
- تحقق مبدئي من عناوين IP العامة قبل زيارة المواقع ومنع تحويلات غير آمنة.
- حماية CSRF وطلبات Cross-Origin، وخصائص أمان للمتصفح، وصلاحيات على مستوى API.
- لا يضمن البحث الوصول إلى كل نتائج Google أو استخراج رقم من كل موقع.
- لا توجد بعد تكاملات Google Ads أو Meta Ads أو TikTok Ads أو WhatsApp Business Cloud API.
- قاعدة البيانات الحالية SQLite؛ PostgreSQL وطابور المهام الخلفية ضمن متطلبات ما قبل الإنتاج.
- لا ترفع الأسرار أو بيانات العملاء إلى GitHub.


## استقبال Leads من الحملات
يوجد مسار استقبال موحد للـ webhooks الموثوقة:
- POST /api/webhooks/leads/google_ads
- POST /api/webhooks/leads/meta_ads
- POST /api/webhooks/leads/tiktok_ads
- أرسل رأس X-Mirage-Webhook-Token المطابق للمتغير CAMPAIGN_WEBHOOK_TOKEN.
- يجب أن تتضمن البيانات consent=true ورقم هاتف أو بريدًا، مع external_id لمنع تكرار نفس Lead من المصدر.
هذا المسار هو طبقة استقبال داخلية؛ لا يعني أن OAuth أو webhooks الرسمية من Google/Meta/TikTok قد تم ربطها. يلزم إعداد تطبيقات كل منصة والتحقق من توقيعاتها ثم تمرير البيانات إلى هذا المسار.


## خصائص النسخة الأصلية — التوسعة الحالية
- صفحات مستقلة: البحث، العملاء، WhatsApp Sender، Email Sender، النشاط، الإحصائيات.
- البحث المتقدم يقبل عدة دول في نفس العملية، مع عدد مستهدف من 1 إلى 1000.
- محركات البحث المتاحة: DuckDuckGo بدون مفتاح، Google Web وGoogle Maps وBing عبر SerpAPI. ويمكن تشغيل Google Web عبر GOOGLE_API_KEY وGOOGLE_CX. يتم منع التكرار بالهاتف والبريد والموقع.
- تظهر روابط Google Maps في صفحة العملاء. بيانات الأنشطة من خرائط Google تحتاج SERPAPI_KEY، وليست كل نتائج Google Maps مضمونة.
- Email Sender يدعم SMTP، اختبار الاتصال، متغيرات {company} و{city}، ولا يحفظ كلمة مرور SMTP.
- WhatsApp Sender منطق DoDo/WhatsApp Web مع ربط QR، اختيار العملاء، نص مخصص، مرفق حتى 16MB، تأخير عشوائي، استراحة دفعات، حد يومي، إيقاف، وتسجيل النتائج. يتطلب تشغيل التطبيق محلياً على Windows مع Chrome وPlaywright؛ لا يعمل داخل Vercel Serverless.
- لا تنقل مجلد wa_profile إلى GitHub أو Vercel؛ يحتوي جلسة WhatsApp خاصة. كما لا تُرسل إلى العملاء الذين حالتهم optout.

### مفاتيح البحث
أضف SERPAPI_KEY في Vercel Environment Variables لتفعيل Google وGoogle Maps وBing. DuckDuckGo متاح دون مفتاح. Google Programmable Search يستخدم GOOGLE_API_KEY وGOOGLE_CX.

### تشغيل WhatsApp محلياً
على جهاز Windows: `pip install -r requirements-local.txt` ثم `playwright install chromium`. شغّل التطبيق محلياً وافتح `/whatsapp` واضغط ربط WhatsApp لمسح QR. مجلد الجلسة محلي ومستبعد من Git.


## استعادة خصائص النسخة المرفوعة
الواجهة الجديدة تفصل صفحات البحث والعملاء ومرسل WhatsApp ومرسل البريد والنشاط والإحصائيات. البحث المتقدم يسمح بتحديد عدة دول وعدد نتائج مستهدف، ويدعم Google Web وGoogle Maps وBing وYahoo وYandex وDuckDuckGo وفق مفاتيح المزود المتاحة. بيانات Google Maps وGoogle/Bing/Yahoo/Yandex عبر SerpAPI تحتاج SERPAPI_KEY؛ Google Web يدعم أيضاً GOOGLE_API_KEY وGOOGLE_CX. لا يمكن لأي محرك إرجاع كل صفحات الإنترنت دون حدود أو ضمان التغطية.

مرسل البريد يستخدم SMTP ويختبر الاتصال ويخصص {company} و{city}، ولا يحفظ كلمة مرور SMTP. مرسل WhatsApp المحلي يدعم ربط QR عبر WhatsApp Web، الرسائل المخصصة، المرفقات حتى 16MB، التأخير بين الرسائل، استراحة الدفعات، الحد اليومي، الإيقاف، وسجل الإرسال. يلزم Windows/Chrome وPlaywright: `pip install -r requirements-local.txt` ثم `playwright install chromium`. هذا المرسل غير متاح على Vercel Serverless. مجلد `instance/wa_profile` خاص ولا يجب رفعه إلى GitHub أو مشاركته.
