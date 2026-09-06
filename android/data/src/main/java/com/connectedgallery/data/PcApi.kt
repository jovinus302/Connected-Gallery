package com.connectedgallery.data
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton
@Singleton class PcApi @Inject constructor() {
 val json=Json { ignoreUnknownKeys=true; encodeDefaults=true }
 private val client=OkHttpClient.Builder().connectTimeout(3,TimeUnit.SECONDS).readTimeout(50,TimeUnit.SECONDS).build()
 suspend fun call(path:String,method:String="GET",body:JsonElement?=null):JsonObject=withContext(Dispatchers.IO) {
  val request=Request.Builder().url("http://127.0.0.1:8765$path")
  if(method!="GET") request.method(method,(body?.toString()?:"{}").toRequestBody("application/json".toMediaType()))
  client.newCall(request.build()).execute().use { response ->
   if(!response.isSuccessful) throw IOException("PC 응답 오류 (${response.code})")
   json.parseToJsonElement(response.body!!.string()).jsonObject
  }
 }
 suspend fun upload(id:String,bytes:ByteArray)=withContext(Dispatchers.IO) {
  val request=Request.Builder().url("http://127.0.0.1:8765/assets/$id/preview").put(bytes.toRequestBody("image/jpeg".toMediaType())).build()
  client.newCall(request).execute().use { if(!it.isSuccessful) throw IOException("사진 전송 실패 (${it.code})") }
 }
}
