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
@Singleton class PcApi @Inject constructor(private val connection:ServerConnection) {
 val json=Json { ignoreUnknownKeys=true; encodeDefaults=true }
 private val client=OkHttpClient.Builder().connectTimeout(10,TimeUnit.SECONDS).readTimeout(50,TimeUnit.SECONDS)
  .callTimeout(60,TimeUnit.SECONDS).followRedirects(false).followSslRedirects(false).build()
 fun isConfigured()=connection.current()!=null
 private fun endpoint()=connection.current()?:throw IOException("서버 연결에서 주소와 접속 키를 설정해 주세요")
 private fun request(endpoint:ServerEndpoint,path:String)=Request.Builder().url(endpoint.url+path).header("Authorization","Bearer "+endpoint.token)
 suspend fun checkConnection(endpoint:ServerEndpoint)=withContext(Dispatchers.IO) {
  client.newCall(request(endpoint,"/manifest").build()).execute().use { response ->
   if(response.code==401)throw IOException("접속 키가 맞지 않아요")
   if(!response.isSuccessful)throw IOException("서버 응답 오류 (${response.code})")
   val manifest=json.parseToJsonElement(response.body!!.string()).jsonObject
   if(manifest["api_version"]?.jsonPrimitive?.intOrNull!=1)throw IOException("호환되는 Gallery 서버가 아니에요")
  }
 }
 suspend fun call(path:String,method:String="GET",body:JsonElement?=null):JsonObject=withContext(Dispatchers.IO) {
  val request=request(endpoint(),path)
  if(method!="GET") request.method(method,(body?.toString()?:"{}").toRequestBody("application/json".toMediaType()))
  client.newCall(request.build()).execute().use { response ->
   if(!response.isSuccessful) throw IOException("서버 응답 오류 (${response.code})")
   json.parseToJsonElement(response.body!!.string()).jsonObject
  }
 }
 suspend fun upload(id:String,bytes:ByteArray)=withContext(Dispatchers.IO) {
  val request=request(endpoint(),"/assets/$id/preview").put(bytes.toRequestBody("image/jpeg".toMediaType())).build()
  client.newCall(request).execute().use { if(!it.isSuccessful) throw IOException("사진 전송 실패 (${it.code})") }
 }
}
