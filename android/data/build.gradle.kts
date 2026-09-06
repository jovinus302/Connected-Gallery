plugins {
 id("com.android.library")
 id("org.jetbrains.kotlin.android")
 id("org.jetbrains.kotlin.plugin.serialization")
 id("org.jetbrains.kotlin.kapt")
 id("com.google.dagger.hilt.android")
}
android {
 namespace = "com.connectedgallery.data"
 compileSdk = 36
 defaultConfig { minSdk = 26;  }
 compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
 kotlinOptions { jvmTarget = "17" }
}
dependencies {
 implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
 implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.8.1")
 testImplementation("junit:junit:4.13.2")
 implementation(project(":domain"))
 implementation("com.google.dagger:hilt-android:2.56.2")
 kapt("com.google.dagger:hilt-compiler:2.56.2")
 implementation("androidx.room:room-runtime:2.7.1")
 implementation("androidx.room:room-ktx:2.7.1")
 kapt("androidx.room:room-compiler:2.7.1")
 implementation("androidx.work:work-runtime-ktx:2.10.1")
 implementation("androidx.exifinterface:exifinterface:1.4.1")
 implementation("com.squareup.okhttp3:okhttp:4.12.0")
}
