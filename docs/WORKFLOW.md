# دورة البناء والنشر

المستودع المعتمد: https://github.com/amoatazben-dotcom/wakeelm

بناءً على تعليمات المستخدم، تُنفذ كل مرحلة في فرع واضح، وتُجرى الفحوص المناسبة، ثم تُرفع التغييرات إلى المستودع. النسخة الجاهزة للنشر توضع على main مع الاحتفاظ بتاريخ المراحل. لا يُعاد طلب إذن الرفع في هذه الجلسة؛ تعليمات المستخدم تشمل المراحل التالية. يُحفظ عمل المستخدم ولا يُستخدم force push لإزالة تاريخ أو تغييرات قائمة.

Railway هو وجهة النشر المطلوبة. يُربط bot-api بفرع main لتصل التغييرات التالية عبر GitHub. PostgreSQL وRedis خدمتان منفصلتان، ويستخدم polling نسخة واحدة من bot-api. يُتحقق من الحالة النهائية و/ready قبل الإعلان عن نجاح التشغيل.

## المتغيرات الحالية

| المتغير | مصدره |
| --- | --- |
| TELEGRAM_BOT_TOKEN | يضعه المستخدم من BotFather في Railway Variables |
| MASTER_ENCRYPTION_KEY | مفتاح Fernet ثابت ينشئه المستخدم ويحفظه في Railway Variables |
| DATABASE_URL | مرجع اتصال خدمة PostgreSQL في نفس مشروع Railway |
| REDIS_URL | مرجع اتصال خدمة Redis في نفس مشروع Railway |
| APP_ENV | production |
| BOT_MODE | polling |
| BOT_DEFAULT_LANGUAGE | ar |

تُولد قيمة MASTER_ENCRYPTION_KEY محليًا بواسطة:

```sh
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

يُنسخ المفتاح مباشرة إلى Railway، ويُحتفظ به عبر النشرات. لا تُرفع قيم الأسرار إلى GitHub أو ملفات الوثائق، ولا يلزم وضع مفاتيح مزودات AI في متغيرات Railway؛ يضيفها المستخدم داخل البوت.

## حالة ربط المستودع

رُفعت المرحلتان إلى main وفرع stage-1-2-foundation-provider-gateway. GitHub Actions لم يبدأ: رسالة GitHub هي “The job was not started because your account is locked due to a billing issue.” يلزم معالجة فوترة GitHub لتشغيل CI هناك. نتيجة التحقق المحلي السابقة: 89 اختبارًا ناجحًا، إضافة إلى Ruff وAlembic.

اختيار اتصال Railway وتجهيز متغيراته مؤجلان إلى نهاية البناء وفق آخر تعليمات المستخدم. لا يعطل ذلك رفع المراحل إلى GitHub.

## آخر توجيه من المستخدم

يُؤجل تشغيل أو نشر Railway حتى الانتهاء من جميع خطوات البناء والمراحل. تُرفع كل مرحلة مكتملة ومختبرة إلى GitHub فقط خلال البناء الحالي. اختيار حساب Railway ومتغيراته لا يعطل تنفيذ المراحل.
