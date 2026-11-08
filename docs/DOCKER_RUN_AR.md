# تشغيل Mirage باستخدام Docker

1. انسخ \`.env.example\` إلى \`.env\`.
2. ضع SECRET_KEY عشوائيًا قويًا وMIRAGE_ADMIN_PASSWORD فريدًا لا يقل عن 16 حرفًا.
3. في الإنتاج خلف HTTPS اضبط COOKIE_SECURE=1.
4. شغّل: \`docker compose up -d --build\`
5. افتح \`http://localhost:8000/login\`.
6. افحص الصحة من \`/health\`.

قاعدة SQLite تحفظ في volume باسم \`mirage_data\` ولا تضيع عند إعادة إنشاء الحاوية. خذ نسخة احتياطية من الـ volume دوريًا. لا ترفع ملف \`.env\` إلى GitHub.

**مهم:** هذا إعداد تشغيل ذاتي/اختبار. لا يُعد بديلًا عن قاعدة PostgreSQL مُدارة ونسخ احتياطي ومراقبة قبل استخدام إنتاجي واسع أو متعدد النسخ.
