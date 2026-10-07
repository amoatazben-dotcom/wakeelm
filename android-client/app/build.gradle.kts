plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.ksp)
    alias(libs.plugins.hilt)
}
val backendUrl = providers.gradleProperty("backendUrl").orElse("https://bot-api-production-b8f0.up.railway.app/").get()
require(backendUrl.startsWith("https://") && backendUrl.endsWith("/")) { "backendUrl must be HTTPS and end in /" }
android {
    namespace = "com.wakeelm.client"
    compileSdk { version = release(37) { minorApiLevel = 2 } }
    defaultConfig {
        applicationId = "com.wakeelm.client"
        minSdk = 26
        targetSdk = 37
        versionCode = 1
        versionName = "0.1-stage12"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        buildConfigField("String", "BACKEND_URL", "\"$backendUrl\"")
    }
    buildFeatures { compose = true; buildConfig = true }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    buildTypes { release { isMinifyEnabled = true; proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt")) } }
    testOptions { unitTests.isReturnDefaultValues = true }
    lint { abortOnError = true }
}
kotlin { jvmToolchain(17) }
ksp { arg("room.schemaLocation", "$projectDir/schemas") }
dependencies {
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui); implementation(libs.compose.material3)
    implementation(libs.activity); implementation(libs.lifecycle); implementation(libs.lifecycle.runtime)
    implementation(libs.nav); implementation(libs.nav.runtime)
    implementation(libs.hilt); ksp(libs.hilt.compiler)
    implementation(libs.room); implementation(libs.room.ktx); ksp(libs.room.compiler)
    implementation(libs.datastore); implementation(libs.work)
    implementation(libs.retrofit); implementation(libs.retrofit.json)
    implementation(libs.okhttp); implementation(libs.okhttp.sse)
    implementation(libs.serialization); implementation(libs.coroutines)
    testImplementation(libs.junit); testImplementation(libs.mockwebserver); testImplementation(libs.coroutines.test)
    androidTestImplementation(platform(libs.compose.bom)); androidTestImplementation(libs.compose.test)
    androidTestImplementation(libs.android.test); androidTestImplementation(libs.android.runner)
    debugImplementation(libs.compose.tooling); debugImplementation(libs.compose.test.manifest)
}
