plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.test.nfctest"
    compileSdk = 33

    defaultConfig {
        applicationId = "com.test.nfctest"
        minSdk = 28
        targetSdk = 33
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        debug {
            isMinifyEnabled = false
        }
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    // classes.jar del panel (TvControlManager, etc.) — copiar a app/libs/
    // Disponible en el dispositivo en runtime, solo se usa para compilar
    compileOnly(fileTree(mapOf("dir" to "libs", "include" to listOf("*.jar"))))

    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
}
