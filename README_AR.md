# Mirage Leads Hunter

نسخة ويب أولية قابلة للتشغيل بواجهة عربية RTL.

## التشغيل المحلي
1. استخدم Python 3.10 أو أحدث.
2. نفّذ: pip install -r requirements.txt
3. انسخ .env.example واضبط SECRET_KEY وMIRAGE_ADMIN_PASSWORD بقيم قوية.
4. شغّل python app.py ثم افتح /login.

## البحث
- يدعم SerpAPI عبر SERPAPI_KEY.
- يدعم Google Programmable Search عبر GOOGLE_API_KEY وGOOGLE_CX.
- يستخدم DuckDuckGo عند عدم إعداد مفاتيح مدفوعة.
- يفحص الموقع وصفحات اتصل بنا/تواصل معنا عند الحاجة.
- لا يضمن البحث الوصول إلى كل نتائج Google أو استخراج رقم من كل موقع.

## الوظائف الحالية
- لوحة مؤشرات، عمليات بحث محفوظة، وسجل العملاء.
- استخراج الهاتف والبريد من المواقع العامة.
- منع تكرار الهاتف والموقع.
- تعيين مسؤول، تغيير حالة العميل، وروابط WhatsApp يدوية.
- تصدير CSV مع الحماية من Formula Injection.
- حماية مبدئية من SSRF وطلبات Cross-Origin وخصائص أمان للمتصفح.

## غير مكتمل بعد
لا توجد تكاملات Google Ads أو Meta Ads أو TikTok Ads، ولا WhatsApp Business Cloud API أو إرسال رسائل آلي. لا توجد حتى الآن صلاحيات متعددة الأدوار أو PostgreSQL أو طابور مهام للبحث طويل المدة. لا ترفع الأسرار إلى GitHub.
