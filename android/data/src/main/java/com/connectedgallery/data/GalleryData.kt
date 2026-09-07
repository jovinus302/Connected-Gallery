package com.connectedgallery.data

import com.connectedgallery.domain.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

@Singleton class GalleryData @Inject constructor(private val db:GalleryDatabase,private val media:MediaLibrary,private val api:PcApi):GalleryRepository {
 private val cache=db.cache();private val json=api.json
 private val sessionId=UUID.randomUUID().toString()
 private val syncLock=Mutex()
 @Volatile private var activeRun:String?=null
 override val photos=cache.photos().map { rows -> rows.map { json.decodeFromString<Photo>(it.value) }.sortedByDescending { it.captured_at } }
 override suspend fun refreshAndSync(progress:(String)->Unit)=syncLock.withLock {
  progress("내 사진을 불러오고 있어요")
  val latest=media.list();val old=photos.first();val ids=latest.map { it.id }.toSet()
  val removed=old.filter { it.id !in ids }.map { it.id }
  val pending=(cache.get("deleted")?.let { json.decodeFromString<List<String>>(it) }?:emptyList())+removed
  cache.put(CacheEntry("deleted",json.encodeToString(pending.distinct())))
  if(removed.isNotEmpty()) { cache.clear("result:%");cache.remove("journey");cache.remove("spaces") }
  for(id in removed) { cache.remove("photo:$id");cache.remove("analysis:$id") }
  val oldById=old.associateBy { it.id }
  for(p in latest) if(oldById[p.id]?.version!=p.version) { cache.remove("analysis:${p.id}");cache.clear("result:%") }
  cache.putAll(latest.map { CacheEntry("photo:${it.id}",json.encodeToString(it)) })
  val reply=api.call("/assets/sync","POST",buildJsonObject { put("assets",json.encodeToJsonElement(latest));put("deleted_ids",json.encodeToJsonElement(pending.distinct())) })
  cache.remove("deleted")
  val need=reply["need_preview"]!!.jsonArray.map { it.jsonPrimitive.content }.toSet()
  val snapshot=reply["analyses"]?.jsonArray?.associateBy { it.jsonObject["photo_id"]!!.jsonPrimitive.content }
  val active=reply["active_analysis_ids"]?.jsonArray?.map { it.jsonPrimitive.content }?.toSet()?:emptySet()
  val prepared=mutableListOf<CacheEntry>()
  for((index,p) in latest.withIndex()) {
   if(p.id in need) {
    val bytes=try { media.preview(p) } catch(e:CancellationException){throw e} catch(_:Exception){progress("읽을 수 없는 사진 한 장을 건너뛰었어요");continue}
    api.upload(p.id,bytes)
   }
   progress("사진 동기화 ${index+1} / ${latest.size}")
   val analysis=if(snapshot!=null)snapshot[p.id]?.jsonObject else api.call("/assets/${p.id}/analysis")
   if(analysis==null || analysis["pending"]?.jsonPrimitive?.booleanOrNull==true) {
    if(p.id in active)continue
    api.call("/runs","POST",buildJsonObject { put("role","analyst");put("photo_ids",json.encodeToJsonElement(listOf(p.id)));put("idempotency_key","analysis-${p.id}-${p.version}") })
   } else prepared.add(CacheEntry("analysis:${p.id}",analysis.toString()))
  }
  cache.putAll(prepared)
  progress("${latest.size}장의 사진을 준비했어요. 사진을 열어 탐색해 보세요")
 }
 override suspend fun analysis(photoId:String):Analysis {
  val cached=cache.get("analysis:$photoId")
  try {
   val value=api.call("/assets/$photoId/analysis").toString()
   cache.put(CacheEntry("analysis:$photoId",value));return json.decodeFromString(value)
  } catch(e:CancellationException) { throw e } catch(e:Exception) {
   return cached?.let { json.decodeFromString(it) }?:Analysis(photoId,pending=true)
  }
 }
 override suspend fun explore(input:ExploreInput,onUpdate:(ExplorationResult)->Unit):ExplorationResult {
  val key="result:exclude-anchor-v2:"+json.encodeToString(input.copy(request_revision=0))
  try {
   val health=api.call("/health")
   val revision=health["revision"]!!.jsonPrimitive.content+":"+(health["agent_spec"]?.jsonPrimitive?.content?:"0")
   if(cache.get("server-revision")!=revision) { cache.clear("result:%");cache.put(CacheEntry("server-revision",revision)) }
  } catch(e:CancellationException){throw e} catch(_:Exception){}
  val cached=cache.get(key)?.let { json.decodeFromString<ExplorationResult>(it) }
   ?.takeIf { result -> result.items.none { it.photo_id==input.anchor.photo_id } }
  cached?.let(onUpdate)
  var rid:String?=null
  try {
   input.anchor.box?.let { box ->
    photos.first().find { it.id==input.anchor.photo_id }?.let { photo ->
     val bytes=media.preview(photo,box)
     api.call("/assets/${photo.id}/region-preview","POST",buildJsonObject { put("box",json.encodeToJsonElement(box));put("jpeg_base64",android.util.Base64.encodeToString(bytes,android.util.Base64.NO_WRAP)) })
    }
   }
   val created=api.call("/runs","POST",buildJsonObject { put("role","explorer");put("explore",json.encodeToJsonElement(input));put("idempotency_key",UUID.randomUUID().toString()) })
   rid=created["id"]!!.jsonPrimitive.content;activeRun=rid
   var cursor=0L
   while(currentCoroutineContext().isActive) {
    val events=api.call("/runs/$rid/events?after=$cursor")
    cursor=events["cursor"]!!.jsonPrimitive.long
    events["events"]!!.jsonArray.forEach { e -> if(e.jsonObject["kind"]!!.jsonPrimitive.content=="results") onUpdate(json.decodeFromJsonElement(e.jsonObject["data"]!!)) }
    val state=api.call("/runs/$rid")
    val status=state["status"]!!.jsonPrimitive.content
    if(status in listOf("completed","incomplete")) {
     val result=json.decodeFromJsonElement<ExplorationResult>(state["result"]!!).let { if(status=="incomplete")it.copy(complete=false) else it }
     if(status=="completed") cache.put(CacheEntry(key,json.encodeToString(result)))
     onUpdate(result);return result
    }
    if(status in listOf("failed","cancelled")) error("탐색을 마치지 못했어요. 다시 시도해 주세요")
    delay(500)
   }
   throw CancellationException()
  } catch(e:CancellationException) { throw e } catch(e:Exception) { if(cached!=null)return cached;throw e }
  finally {
   if(rid!=null) withContext(NonCancellable) { runCatching { api.call("/runs/$rid/cancel","POST") } }
   if(activeRun==rid) activeRun=null
  }
 }
 override suspend fun cancelExploration() { activeRun?.let { runCatching { api.call("/runs/$it/cancel","POST") } } }
 override suspend fun saveJourney(journey:Journey) { cache.put(CacheEntry("journey",json.encodeToString(journey))) }
 override suspend fun loadJourney():Journey=cache.get("journey")?.let { json.decodeFromString(it) }?:Journey()
 override suspend fun feedback(kind:String,photoId:String?,regionId:String?,value:String) {
  api.call("/feedback","POST",buildJsonObject { put("kind",kind);put("value",value);photoId?.let { put("photo_id",it) };regionId?.let { put("region_id",it) } })
 }
 override suspend fun metric(name:String,value:String) {
  val data=buildJsonObject { put("name",name);put("value",value);put("at",System.currentTimeMillis()) }
  runCatching { api.call("/feedback","POST",buildJsonObject { put("kind","metric");put("session_id",sessionId);put("value",data.toString()) }) }
 }
}
