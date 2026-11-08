# البنية التقنية المقترحة

## المكونات
- Web UI: لوحة عربية RTL مع تبديل اللغة، بحث، دفعات، عملاء، مبيعات، تقارير وإعدادات.
- API: Flask REST API مع جلسات آمنة وصلاحيات RBAC وCSRF.
- Database: PostgreSQL دائم في بيئات التطوير والاختبار والإنتاج.
- Worker: مهام بحث واستخراج طويلة تعمل في الخلفية مع حالة تقدم وإمكانية الإيقاف وإعادة المحاولة.
- Integrations: موصلات منفصلة لمزودات البحث والبريد والإعلانات وWhatsApp Business Cloud.
- Observability: سجلات منظمة، سجل تدقيق، health endpoint ومؤشرات أخطاء المهام.

## كيانات قاعدة البيانات
users, roles, permissions, user_roles, companies, leads, lead_sources, search_batches, search_batch_items, assignments, activities, notes, tasks, campaigns, integrations, audit_logs, exports.

## قواعد البيانات المهمة
- leads.phone_normalized فريد جزئيًا عند وجود قيمة.
- lead_sources يسمح بعدة مصادر للعميل الواحد.
- كل lead مرتبط بمالك/فريق وفق سياسة الإسناد.
- search_batches يحتفظ بمعايير البحث وحالة التنفيذ والأرقام الإجمالية.
- audit_logs يسجل الفاعل والفعل والكيان والتوقيت وبيانات التغيير غير السرية.

## ضوابط أمنية
- لا أسرار داخل المستودع؛ تستخدم متغيرات بيئة/Secret Store.
- كلمات المرور تُخزن باستخدام Argon2id أو bcrypt.
- جلسات Secure/HttpOnly/SameSite مع تدوير المفتاح.
- CSRF على الطلبات المغيرة للحالة.
- صلاحيات على مستوى API، لا الواجهة فقط.
- SSRF protection: حظر localhost والشبكات الخاصة وعناوين metadata وإعادة فحص DNS بعد التحويلات، وقصر البروتوكول على HTTP/HTTPS.
- احترام robots.txt، تحديد المعدل، مهلة اتصال، حد حجم الاستجابة، وأنواع المحتوى.
- حماية التصدير من CSV formula injection.
- نسخ احتياطي واختبار استعادة PostgreSQL.
