plugins {
 id("com.android.library")
 id("org.jetbrains.kotlin.android")
 id("org.jetbrains.kotlin.plugin.serialization")
}
android {
 namespace = "com.connectedgallery.domain"
 compileSdk = 36
 defaultConfig { minSdk = 26;  }
 compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
 kotlinOptions { jvmTarget = "17" }
}
dependencies {
 implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
 implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.8.1")
 testImplementation("junit:junit:4.13.2")
}
