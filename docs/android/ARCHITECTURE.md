# Android client architecture (stages 1–2)

`android-client/` is the single native Android application for this repository. It does not run an agent, MCP server, GitHub writer, or local AI provider engine.

One Gradle app module is intentional at this size. Packages separate `core` DTO/domain/cache/security/network/settings infrastructure, `data` repositories and sending use case, and `ui` Compose screens/StateFlow ViewModel. Hilt supplies dependencies. Composables never call Retrofit or Room. ViewModels never query the database. Navigation 3 owns a serializable back stack; bottom destinations are Home, Chats, Projects, Tasks, More. Projects and Tasks explicitly show a future-stage placeholder.

Room is the observable source for providers, models, conversations, messages, and profile. DTOs map to entities and then immutable domain models. Views load cache before refreshing the API. Provider keys never enter Room. Message bodies are AES-GCM sealed with a separate Android Keystore key. AccountGuard serializes account changes and background cache writes; logout cancels foreground generation and clears account cache/preferences.

DataStore persists language (Arabic default), theme, selected tab, onboarding, routing policy, active model ID. Routing/model cache is updated only after backend acknowledgement. WorkManager performs constrained periodic provider/conversation refresh with bounded retry. No offline generation or background replay of chargeable messages.

FastAPI's `/api/v1` endpoints share the existing Telegram user, owned ProviderService, ModelService, RoutingGateway, quota reservations, feature flags, circuit breaker, and encrypted provider storage. Conversation tables extend the existing database through one Alembic migration. Apply `alembic upgrade head` before using the branch backend. This migration adds tables without rewriting existing platform data.

The current Hilt/AGP combination uses the external Kotlin plugin and legacy Android DSL flags (`android.builtInKotlin=false`, `android.newDsl=false`). The debug build validates this combination; AGP emits migration deprecations. Move to the built-in Kotlin DSL when that Hilt integration supports it. No image loader or Rust module is added because stages 1–2 have no bitmap-loading or measured native-processing requirement.
