# تقرير تنفيذ المرحلتين 5 و6

تم تنفيذ التكاملات واختبارها محليًا. الاختبار النهائي: **199 اختبارًا ناجحًا** على Python 3.13.15، يشمل PostgreSQL 17 وRedis 7 وDocker وخادم MCP مضبوطًا يستخدم SDK الرسمي. اختبار GitHub App على حساب حي ونشر Railway لم يُنفذا؛ يلزمان إعدادات الحساب ومرحلة التشغيل التي طلب المستخدم تأجيلها.

1. **الملفات المنشأة:** القائمة التفصيلية في نهاية التقرير: وحدات GitHub/Git/MCP والتكاملات وواجهات OAuth/Webhooks وترحيل واختبارات ووثائق.
2. **الملفات المعدلة:** ربط الوحدات بالطابور والمنسق وواجهة تيليجرام والنماذج والإعدادات والترجمات والتوثيق؛ القائمة أدناه.
3. **الترحيل:** `45e2729dffcb` بعد `70b1efb2e547` يضيف ثمانية جداول: github_connections، github_repositories، repository_workspaces، mcp_servers، mcp_credentials، mcp_tools، mcp_resources، integration_oauth_states، وحقلَي AgentJob.kind/payload_encrypted. تم اختبار upgrade ثم downgrade إلى المرحلة السابقة ثم upgrade في قاعدة PostgreSQL مؤقتة مستقلة؛ و`alembic check` بلا اختلافات.
4. **المتغيرات:** تبقى TELEGRAM_BOT_TOKEN / DATABASE_URL / REDIS_URL / MASTER_ENCRYPTION_KEY متطلبات التشغيل. الاختيارية الجديدة موضحة بالكامل في `.env.example`: GITHUB_APP_ID / GITHUB_APP_PRIVATE_KEY / GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET / GITHUB_WEBHOOK_SECRET، INTEGRATIONS_CALLBACK_BASE_URL، GITHUB_WRITE_ENABLED / GITHUB_PUSH_CI_REVIEWED / GITHUB_COMMENTS_ENABLED، اسم/بريد bot، حدود Git، GIT_REQUIRE_VALIDATION، OAuth TTL، حدود/وسائل MCP، MCP_TOOL_POLICIES / MCP_OAUTH_CLIENTS، INTEGRATION_JOBS_ENABLED. لا يلزم وضعها الآن لاستكمال البناء.
5. **اللغات وبيئة التشغيل:** Python وGit موثوق على Linux؛ نفس FastAPI/aiogram/PostgreSQL/Redis. لم يُضف Rust أو TypeScript أو Go.
6. **سبب العناصر غير Python:** Git هو برنامج النظام المتخصص لمعالجة المستودعات دون إعادة تنفيذ البروتوكول والـpack/diff. لا يوجد مكوّن جديد بلغة أخرى؛ الاختيارات والأدلة والبدائل والكلفة موثقة في TECHNOLOGY_SELECTION.md.
7. **صلاحيات GitHub App:** Metadata/Actions/Checks/Statuses قراءة؛ Contents/Pull requests قراءة أو كتابة عند تفعيلها؛ Issues كتابة فقط عند تفعيل التعليقات. لا صلاحيات Workflows/Admin/Secrets/Deployments. الرموز التشغيلية مقصورة على repository ID المحدد.
8. **مصادقة GitHub:** App مفضل، ticket خاص بالمستخدم والتركيب، state وnonce وPKCE وربط callback، رمز المستخدم مشفر، صلاحية المستخدم ضمن تركيب App تُتحقق، رمز تركيب قصير العمر لا يُخزن. PAT دقيق الصلاحيات بديل؛ الرسالة تحذف قدر الإمكان والرمز يُشفّر. إعادة الربط لازمة عند انتهاء رمز مستخدم App؛ لم ينفذ تجديده الآلي.
9. **تدفق المستودع:** قائمة مملوكة وبحث/صفحات، استيراد background job، clone آمن وفهرسة Stage 3، فرع مهمة مستقل، تعديلات/فرق/rollback/validation من Stage 4، ثم نشر بالموافقات المنفصلة. قضية issue #123 تدخل سياقًا غير موثوق.
10. **حماية الفروع:** منع default/main/master والفروع المحمية، agent/* فقط، ربط الفرع بالمهمة، فحص base SHA وremote ومَلَكية الاتصال. لا merge/rebase تلقائي أو force push.
11. **Commit/push:** ملفات دقيقة، scan أسرار/artifacts، validation ناجح لنفس digest، موافقة bound إلى الملفات/head/base/connection، push لمرجع واحد وSHA نفسه وشجرة نظيفة. الرفع معطل حتى مراجعة المسؤول CI لفروع الوكيل؛ تغييرات workflow محظورة.
12. **PR:** عنوان/نص/صفة draft ضمن تفاصيل موافقة مستقلة، يتطلب SHA تم رفعه، يستهدف default branch. واجهة تيليجرام تنشئ draft؛ لا merge أو نشر إنتاج.
13. **اختبارات GitHub:** اتصال وصلاحيات/عزل/revoke، فرع وخيارات آمنة، موافقات مستقلة وتغير SHA/ملفات، validation/stale/secrets/artifacts، قضية خبيثة كسياق، توقيع webhook/idempotency، بيئة Git بلا أسرار. تجربة محلية حقيقية: clone/fetch/index/branch/commit/push مقابل bare fixture. الشبكة الحية/App لم تختبرا بمفاتيح المالك.
14. **Rust:** لم يُنفذ؛ لا دليل قياسي يبرر مكوّنًا إضافيًا. واجهة GitService تسهّل فصل runtime لاحقًا إن أثبت القياس الحاجة.
15. **MCP SDK:** الحزمة الرسمية Python mcp 1.30.0 المثبتة في uv.lock؛ jsonschema للتحقق وhttpx مع transport HTTPS آمن.
16. **الوسائل/البروتوكول:** Streamable HTTP عبر HTTPS فقط؛ تفاوض SDK وتخزين نسخة البروتوكول. لا stdio ولا SSE القديم ولا تشغيل أو تثبيت أوامر خوادم.
17. **OAuth MCP:** discovery لهوية resource/issuer، client معروف لدى المسؤول، scopes صريحة، PKCE S256، ticket/state أحادي الاستخدام وnonce cookie وTTL وربط redirect/issuer/server/user. access/refresh مشفران، expiry وتجديد مقيد بالنطاقات، منع تصعيد scopes وخلط الحسابات. الاختبار بالخادم المضبوط شمل PKCE خاطئ وتجديد فاشل.
18. **Tools/resources/prompts:** discovery وصفحات محدودة، schemas/fingerprints، تعطيل افتراضي، أدوات مراجعة تمر عبر Registry/Policy، قراءة URI وقالب مكتشف فقط؛ معاملات القوالب تُطلب من المستخدم. المخرجات والقوالب بجميع أدوارها بيانات UNTRUSTED وتخضع لتنقيح الأسرار والحجم.
19. **سياسة MCP:** READ/SEARCH مراجعة منخفضة الخطورة؛ CREATE/UPDATE/SEND عالية مع موافقة في WORKSPACE؛ مجهولة معطلة؛ shell/SSH/secrets/admin/billing/production deploy محظورة؛ قاعدة البيانات structured read فقط؛ GitHub MCP/cloud deploy providers قراءة فقط. تغيير schema/description يلزم إعادة مراجعة. ToolRouter يعرض حتى ثمانية schemas ملائمة بدل كشف الجميع.
20. **TypeScript:** لم يُنفذ؛ لا موفر مطلوب أثبت نقصًا جوهريًا في Python. لا خدمة إضافية ولا أسرار مشتركة بين runtimes.
21. **سجل التكاملات:** GitHub native منفذ؛ ملفات سياسة GitHub MCP/Supabase/Drive/Gmail/Calendar/Slack/Notion/Linear/Jira/Railway/Cloudflare/Vercel. هذه profiles لإمكانات endpoints يضيفها المستخدم، وليست حسابات متصلة أو adapters خاصة منفذة.
22. **التحقق الأمني:** 199 passed بلا skipped، تحذير deprecation واحد من FastAPI TestClient/httpx. Ruff lint/format وgit diff --check ناجحة، build wheel/sdist ناجح، migration round-trip/check ناجح. Transport اختبار TLS فعلي بشهادة اختبار موثوقة يرفض redirects ويضبط الأصل والحجم والوقت؛ SSRF الإنتاجي يرفض private/metadata/internal URLs. اختبارات SDK تمنع أدوات خطرة، إعادة استخدام/عزل الموافقات والتصعيد وتتحقق من audit. اختبارات Docker السابقة تؤكد منع الشبكة والأسرار ومسارات المضيف وتعمل بعد هذه التعديلات.
23. **Railway:** تصميم الخدمة Python bot-api + PostgreSQL + Redis + volume خاص؛ لا sidecars لغات إضافية. يلزم Git في image Linux وHTTPS callbacks. يبقى sandbox disabled حتى validator خارجي موثوق. لم يُنشأ أو يُشغل أو يُنشر أي شيء في Railway، احترامًا لتأجيل المستخدم.
24. **الفرع:** `stage-5-6-github-mcp-hybrid` في مستودع `amoatazben-dotcom/wakeelm`، مع رفع التغييرات إلى main وفق التفويض السابق بعد التحقق.
25. **قائمة commits:** تقسيم مقصود إلى foundation/schema/dependencies، native GitHub، Git runtime، MCP SDK/policy/auth، worker/registry bridge، Telegram/API، الاختبارات، التوثيق، وعقود الإدخال الصارمة. الرسائل الفعلية تُطابق القائمة في تاريخ الفرع، دون commit ضخم واحد؛ قد تختلف SHA المحلية عن المنشورة لأن النشر عبر حساب GitHub المتصل.
26. **القيود:** App/OAuth خارجي/Telegram حي لم تُختبر ببيانات إنتاج؛ لا نشر Railway. تجديد رمز مستخدم GitHub App غير منفذ ويتطلب إعادة ربط. لا OAuth dynamic registration/cross-origin issuer endpoints، لا stdio/SSE، schemas فيها refs/regex ترفض تحفظًا، database arbitrary SQL محظور حتى SELECT. كل أداة تحتاج fingerprint يراجعها مسؤول. مستودع المهمة لا يعاد استعماله لمهمة مستقلة دون استيراد جديد؛ تغير base يتطلب مراجعة جديدة. scan الأسرار تقريبي؛ CI review اعتراف مسؤول وليس تحليلًا شاملًا. `GIT_REQUIRE_VALIDATION=true` يمنع النشر على Railway حتى توفير validator. حساب GitHub Actions كان موقوفًا بسبب الفوترة في المرحلة السابقة؛ لا تعتمد نتيجة CI البعيدة بديلًا للاختبارات المحلية.
27. **المرحلة 7:** استقبال برومبتها، تجهيز validator خارجي معزول مناسب Railway، قبول حي باستخدام App/Telegram/مزود MCP يملكها المستخدم، إعداد المتغيرات عند موعد التشغيل، إدارة تجديد GitHub user tokens/تنظيف OAuth states حسب الحاجة، وإضافة adapters وصلاحيات جديدة فقط بمتطلبات ومراجعة محددة. لا نشر إنتاج تلقائي قبل اكتمال مراحل البناء المطلوبة.

## الملفات المنشأة

- `alembic/versions/45e2729dffcb_stage_5_and_6_github_mcp_oauth_.py`
- `app/api/integrations.py`
- `app/bot/handlers/integrations.py`
- `app/db/models/integrations.py`
- `app/git/__init__.py`
- `app/git/askpass.py`
- `app/git/base.py`
- `app/git/runtime.py`
- `app/git/scanner.py`
- `app/github/__init__.py`
- `app/github/connections.py`
- `app/github/repositories.py`
- `app/github/schemas.py`
- `app/github/service.py`
- `app/integrations/__init__.py`
- `app/integrations/http.py`
- `app/integrations/jobs.py`
- `app/integrations/oauth.py`
- `app/integrations/ownership.py`
- `app/integrations/registry.py`
- `app/integrations/sanitizer.py`
- `app/integrations/schemas.py`
- `app/mcp/__init__.py`
- `app/mcp/adapter.py`
- `app/mcp/client.py`
- `app/mcp/policy.py`
- `app/mcp/service.py`
- `app/tools/policy.py`
- `app/tools/router.py`
- `docs/GITHUB_APP.md`
- `docs/GITHUB_INTEGRATION.md`
- `docs/GIT_SECURITY.md`
- `docs/INTEGRATIONS.md`
- `docs/MCP.md`
- `docs/MCP_AUTH.md`
- `docs/MCP_SECURITY.md`
- `docs/REPOSITORY_AGENT.md`
- `docs/STAGE_5_6_REPORT.md`
- `docs/TECHNOLOGY_SELECTION.md`
- `tests/mcp_test_server.py`
- `tests/test_github_stage5.py`
- `tests/test_integration_routes.py`
- `tests/test_integration_transport.py`
- `tests/test_mcp_stage6.py`
- `tests/test_telegram_integrations.py`

## الملفات المعدلة

- `.env.example`
- `README.md`
- `app/agent/orchestrator.py`
- `app/agent/patches.py`
- `app/agent/planner.py`
- `app/agent/validator.py`
- `app/agent/worker.py`
- `app/bot/dispatcher.py`
- `app/bot/handlers/agent.py`
- `app/bot/handlers/start.py`
- `app/bot/handlers/workspaces.py`
- `app/bot/keyboards.py`
- `app/bot/middleware.py`
- `app/core/config.py`
- `app/core/logging.py`
- `app/db/models/__init__.py`
- `app/db/models/agent.py`
- `app/locales/ar.json`
- `app/locales/en.json`
- `app/main.py`
- `app/services/agent_service.py`
- `app/services/workspace_service.py`
- `app/tools/registry.py`
- `docs/APPROVALS.md`
- `docs/ARCHITECTURE.md`
- `docs/RAILWAY.md`
- `docs/SECURITY.md`
- `docs/TOOL_SECURITY.md`
- `pyproject.toml`
- `requirements.txt`
- `uv.lock`

## رسائل commits المنشورة

- `feat: add owned integration schema and secure transport foundation`
- `feat: add bounded credential-safe Git runtime and repository scanning`
- `feat: add GitHub App connections and approved repository workflow`
- `feat: add reviewed MCP SDK capabilities and scoped OAuth`
- `feat: bridge GitHub and MCP into existing jobs and approval engine`
- `feat: add private Telegram integration flows and signed callbacks`
- `test: verify GitHub MCP OAuth and transport security`
- `docs: document stages 5 and 6 architecture setup and verified limits`
- `feat: finalize strict integration tool input contracts`
