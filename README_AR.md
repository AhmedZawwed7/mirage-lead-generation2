# Mirage Leads Hunter

نسخة ويب أولية قابلة للتشغيل بواجهة عربية RTL.

## التشغيل المحلي
1. استخدم Python 3.10 أو أحدث.
2. نفّذ: pip install -r requirements.txt
3. انسخ .env.example واضبط SECRET_KEY وMIRAGE_ADMIN_PASSWORD بقيم قوية.
4. شغّل python app.py ثم افتح /login.

## الوظائف الموجودة حاليًا
- لوحة مؤشرات وقاعدة بيانات SQLite.
- بحث DuckDuckGo واستخراج بيانات التواصل العامة.
- تحقق مبدئي من عناوين IP العامة قبل زيارة المواقع.
- منع تكرار الهاتف والموقع.
- حالات العملاء وتعيين مسؤول متابعة.
- تصدير CSV مع حماية من CSV Formula Injection.

## غير مكتمل بعد
لا توجد تكاملات Google Ads أو Meta أو TikTok أو WhatsApp Business API، ولا PostgreSQL أو أدوار مستخدمين متعددة. نتائج البحث تعتمد على مزود البحث وإتاحة المواقع ولا يوجد ضمان لاستخراج كل الشركات. لا ترفع الأسرار إلى GitHub.
