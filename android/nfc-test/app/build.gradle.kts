plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.test.nfctest"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.test.nfctest"
        minSdk = 28
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        debug   { isMinifyEnabled = false }
        release { isMinifyEnabled = false }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    // classes.jar del panel — copiar a app/libs/classes.jar
    compileOnly(fileTree("libs") { include("*.jar") })
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
}
