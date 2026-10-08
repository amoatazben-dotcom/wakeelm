pluginManagement {
    repositories { google { content { includeGroupByRegex("com\\.android.*"); includeGroupByRegex("androidx.*") } }; mavenCentral(); gradlePluginPortal() }
    resolutionStrategy { eachPlugin {
        if (requested.id.id == "org.jetbrains.kotlin.plugin.serialization") useModule("org.jetbrains.kotlin:kotlin-serialization:${requested.version}")
    } }
}
dependencyResolutionManagement { repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS); repositories { google { content { includeGroupByRegex("com\\.android.*"); includeGroupByRegex("androidx.*") } }; mavenCentral() } }
rootProject.name = "WakeelmAndroid"
include(":app")
