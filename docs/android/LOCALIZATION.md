# Arabic and English

`values/strings.xml` is Arabic; `values-en/strings.xml` is English. DataStore defaults to `ar` independently of the OS locale. A localized configuration context and Compose layout direction update together without restarting the activity. Theme changes likewise recompose in place.

Arabic RTL is first-class: mirrored navigation/layouts, localized account/provider/model/chat statuses, Arabic onboarding instructions and input labels. Code fences explicitly provide LTR; model IDs, API URLs and keys are technical values. Model/provider names and server conversation titles are user data, not translated resources.

Instrumentation includes RTL Arabic plus English code rendering and persistent settings checks. Run `./gradlew :app:connectedDebugAndroidTest` on a device/emulator. Local device execution status is recorded in STAGE_1_2_REPORT; having test source is not evidence that it passed.
