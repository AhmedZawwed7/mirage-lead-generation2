# Mirage Leads Hunter

نسخة ويب أولية قابلة للتشغيل بواجهة عربية RTL.

## التشغيل المحلي
1. استخدم Python 3.10 أو أحدث.
2. نفّذ: pip install -r requirements.txt
3. انسخ .env.example واضبط SECRET_KEY عشوائيًا بطول 32 بايت على الأقل وMIRAGE_ADMIN_PASSWORD بكلمة مرور قوية وفريدة. فعّل COOKIE_SECURE=1 خلف HTTPS.
4. شغّل python app.py ثم افتح /login.

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
- تعيين مسؤول وملاحظات متابعة.
- فتح محادثة WhatsApp يدويًا، دون إرسال تلقائي.
- تصدير CSV وExcel.

## الأمان والحدود
- تحقق مبدئي من عناوين IP العامة قبل زيارة المواقع ومنع تحويلات غير آمنة.
- حماية مبدئية من طلبات Cross-Origin، وخصائص أمان للمتصفح.
- لا يضمن البحث الوصول إلى كل نتائج Google أو استخراج رقم من كل موقع.
- لا توجد بعد تكاملات Google Ads أو Meta Ads أو TikTok Ads أو WhatsApp Business Cloud API.
- لا توجد حتى الآن صلاحيات متعددة الأدوار أو PostgreSQL أو طابور مهام للبحث طويل المدة.
- لا ترفع الأسرار أو بيانات العملاء إلى GitHub.


## استقبال Leads من الحملات
يوجد مسار استقبال موحد للـ webhooks الموثوقة:
- POST /api/webhooks/leads/google_ads
- POST /api/webhooks/leads/meta_ads
- POST /api/webhooks/leads/tiktok_ads
- أرسل رأس X-Mirage-Webhook-Token المطابق للمتغير CAMPAIGN_WEBHOOK_TOKEN.
- يجب أن تتضمن البيانات consent=true ورقم هاتف أو بريدًا، مع external_id لمنع تكرار نفس Lead من المصدر.
هذا المسار هو طبقة استقبال داخلية؛ لا يعني أن OAuth أو webhooks الرسمية من Google/Meta/TikTok قد تم ربطها. يلزم إعداد تطبيقات كل منصة والتحقق من توقيعاتها ثم تمرير البيانات إلى هذا المسار.
