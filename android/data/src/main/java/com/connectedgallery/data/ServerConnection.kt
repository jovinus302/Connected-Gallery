package com.connectedgallery.data

import android.content.Context
import android.content.pm.ApplicationInfo
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.serialization.json.*
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

class ServerEndpoint(val url:String, val token:String) {
 companion object {
  fun validated(address:String, key:String):ServerEndpoint {
   val parsed=address.trim().toHttpUrlOrNull() ?: throw IllegalArgumentException("올바른 서버 주소를 입력해 주세요")
   require(parsed.isHttps || (parsed.scheme=="http" && parsed.host in setOf("127.0.0.1","localhost"))) { "서버 주소는 HTTPS를 사용해 주세요" }
   require(parsed.username.isEmpty() && parsed.password.isEmpty() && parsed.query==null && parsed.fragment==null) { "주소에는 계정 정보나 쿼리를 넣을 수 없어요" }
   val token=key.trim()
   require(token.length>=32 && token.all { it.code in 33..126 }) { "접속 키를 확인해 주세요" }
   return ServerEndpoint(parsed.toString().trimEnd('/'),token)
  }
 }
}

@Singleton class ServerConnection @Inject constructor(@ApplicationContext private val context:Context) {
 private val prefs=context.getSharedPreferences("server-connection",Context.MODE_PRIVATE)
 private val alias="connected-gallery-server-key"
 private fun secret():SecretKey {
  val store=KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
  (store.getKey(alias,null) as? SecretKey)?.let { return it }
  return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore").apply {
   init(KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
    .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
  }.generateKey()
 }
 init {
  // Debug-only local provisioning, delivered through run-as; never an exported intent.
  val input=File(context.filesDir,"server-connection.json")
  if(context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0 && input.exists()) {
   try {
    val value=Json.parseToJsonElement(input.readText()).jsonObject
    save(ServerEndpoint.validated(value.getValue("url").jsonPrimitive.content,value.getValue("token").jsonPrimitive.content))
   } finally { input.delete() }
  }
 }
 @Synchronized fun current():ServerEndpoint? {
  val url=prefs.getString("url",null)?:return null
  return runCatching {
   val cipher=Cipher.getInstance("AES/GCM/NoPadding")
   cipher.init(Cipher.DECRYPT_MODE,secret(),GCMParameterSpec(128,Base64.decode(prefs.getString("iv",null),Base64.NO_WRAP)))
   val token=String(cipher.doFinal(Base64.decode(prefs.getString("token",null),Base64.NO_WRAP)),Charsets.UTF_8)
   ServerEndpoint.validated(url,token)
  }.getOrNull()
 }
 @Synchronized fun save(endpoint:ServerEndpoint) {
  val cipher=Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE,secret()) }
  val encrypted=cipher.doFinal(endpoint.token.toByteArray(Charsets.UTF_8))
  check(prefs.edit().putString("url",endpoint.url)
   .putString("iv",Base64.encodeToString(cipher.iv,Base64.NO_WRAP))
   .putString("token",Base64.encodeToString(encrypted,Base64.NO_WRAP)).commit()) { "서버 설정을 저장하지 못했어요" }
 }
}
