package com.connectedgallery.explore

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.connectedgallery.domain.*
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import javax.inject.Inject
import java.util.UUID
import kotlinx.serialization.json.*

@HiltViewModel class GalleryViewModel @Inject constructor(private val repo:GalleryRepository):ViewModel() {
 val photos=repo.photos.stateIn(viewModelScope,SharingStarted.Eagerly,emptyList())
 val journey=MutableStateFlow(Journey())
 val analysis=MutableStateFlow<Analysis?>(null)
 val status=MutableStateFlow("")
 val exploring=MutableStateFlow(false)
 private var currentView=UUID.randomUUID().toString()
 private fun viewMetric(kind:String="")=buildJsonObject { put("view_id",currentView);put("photo_id",journey.value.current?.photoId?:"");put("kind",kind) }.toString()
 private var searchJob:Job?=null;private var analysisJob:Job?=null;private var syncJob:Job?=null
 init {
  viewModelScope.launch {
   val initial=repo.photos.first();val saved=repo.loadJourney().withoutTimeFilters()
   journey.value=if(saved.current?.photoId in initial.map { it.id })saved else Journey()
   repo.saveJourney(journey.value)
   journey.value.current?.let { observeAnalysis(it.photoId) }
   repo.photos.collect { available ->
    val ids=available.map { it.id }.toSet()
    if(journey.value.current?.photoId?.let { it !in ids }==true) { searchJob?.cancel();analysisJob?.cancel();update(Journey());analysis.value=null }
   }
  }
 }
 private fun update(j:Journey) { journey.value=j;viewModelScope.launch { repo.saveJourney(j) } }
 fun refresh() {
  if(syncJob?.isActive==true)return
  syncJob=viewModelScope.launch { try { repo.refreshAndSync { status.value=it } } catch(e:CancellationException){throw e} catch(_:Exception){status.value="PC 연결을 확인해 주세요. 저장된 사진은 계속 볼 수 있어요"} }
 }
 fun open(id:String) {
  searchJob?.cancel();exploring.value=false;status.value="";update(journey.value.open(id));observeAnalysis(id)
 }
 private fun observeAnalysis(id:String) {
  analysisJob?.cancel();analysis.value=null;currentView=UUID.randomUUID().toString()
  analysisJob=viewModelScope.launch {
   while(isActive && journey.value.current?.photoId==id) {
    val a=repo.analysis(id);if(journey.value.current?.photoId==id)analysis.value=a
    if(!a.pending) { delay(2000);if(a.regions.isNotEmpty() && journey.value.current?.photoId==id)repo.metric("eligible_view",viewMetric());break }
    delay(2000)
   }
  }
 }
 fun select(anchor:SemanticAnchor) {
  if(journey.value.current?.photoId!=anchor.photo_id)return
  update(journey.value.select(anchor));viewModelScope.launch { repo.metric("object_tap",viewMetric(anchor.kind));repo.metric("hop") };runSearch()
 }
 fun retry() { runSearch() }
 private fun runSearch() {
  searchJob?.cancel()
  val j=journey.value;val query=j.current?.query?:return
  val revision=j.revision
  searchJob=viewModelScope.launch {
   exploring.value=true;status.value="연결된 사진을 찾고 있어요"
   val started=System.currentTimeMillis();var first=true
   try {
    repo.explore(query.copy(request_revision=revision)) { result ->
     if(journey.value.revision==revision)update(journey.value.accept(revision,result))
     if(first) { first=false;viewModelScope.launch { repo.metric("first_result_ms",(System.currentTimeMillis()-started).toString()) } }
    }
    repo.metric("final_result_ms",(System.currentTimeMillis()-started).toString())
    if(journey.value.revision==revision)status.value=""
   } catch(e:CancellationException){withContext(NonCancellable){repo.metric("explore_cancelled")};throw e} catch(_:Exception) {
    if(journey.value.revision==revision)status.value="탐색을 마치지 못했어요. 연결을 확인하고 다시 시도해 주세요"
   } finally { if(journey.value.revision==revision)exploring.value=false }
  }
 }
 fun back() {
  searchJob?.cancel();exploring.value=false;status.value="";viewModelScope.launch { repo.metric("back") };update(journey.value.back());journey.value.current?.let { observeAnalysis(it.photoId) }?:run { analysisJob?.cancel();analysis.value=null }
 }
 fun scroll(revision:Long,index:Int,offset:Int) { val j=journey.value;if(j.revision==revision)update(j.copy(current=j.current?.copy(scrollIndex=index,scrollOffset=offset))) }
 fun name(region:Region,value:String) { viewModelScope.launch { try { repo.feedback("person_name",photoId=region.photo_id,regionId=region.id,value=value);val refreshed=repo.analysis(region.photo_id);if(journey.value.current?.photoId==region.photo_id)analysis.value=refreshed } catch(e:CancellationException){throw e} catch(_:Exception){if(journey.value.current?.photoId==region.photo_id)status.value="PC 연결 후 이름을 저장해 주세요"} } }
}
