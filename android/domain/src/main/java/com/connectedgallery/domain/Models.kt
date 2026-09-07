package com.connectedgallery.domain
import kotlinx.serialization.Serializable
import kotlinx.coroutines.flow.Flow

@Serializable data class Photo(val id:String,val device_id:String="",val local_uri:String="",val version:String="",val captured_at:String?=null,val time_source:String="unknown",val width:Int=1,val height:Int=1,val rotation:Int=0,val latitude:Double?=null,val longitude:Double?=null)
@Serializable data class RegionBox(val x:Float,val y:Float,val width:Float,val height:Float) {
 fun contains(px:Float,py:Float)=px>=x && py>=y && px<=x+width && py<=y+height
}
@Serializable data class Region(val id:String,val photo_id:String,val box:RegionBox,val kind:String,val label:String,val evidence:String="")
@Serializable data class Analysis(val photo_id:String,val description:String="",val regions:List<Region> = emptyList(),val ocr:String="",val uncertainty:String="",val pending:Boolean=false)
@Serializable data class SemanticAnchor(val photo_id:String,val region_id:String?=null,val box:RegionBox?=null,val label:String="선택한 부분",val kind:String="object")
@Serializable data class ExploreInput(val anchor:SemanticAnchor,val direction:String="related",val year:Int?=null,val request_revision:Long=0)
@Serializable data class ResultItem(val photo_id:String,val reason:String="")
@Serializable data class ExplorationResult(val label:String="",val items:List<ResultItem> = emptyList(),val complete:Boolean=true)
@Serializable data class Space(val id:String,val name:String,val meaning:String,val items:List<ResultItem>)
@Serializable data class RunState(val id:String,val status:String,val result:ExplorationResult?=null,val error:String?=null)
@Serializable data class Frame(val photoId:String,val query:ExploreInput?=null,val result:ExplorationResult?=null,val scrollIndex:Int=0,val scrollOffset:Int=0)
@Serializable data class Journey(val current:Frame?=null,val history:List<Frame> = emptyList(),val revision:Long=0) {
 fun withoutTimeFilters():Journey {
  if(current?.query?.year==null && history.none { it.query?.year!=null })return this
  val nextRevision=revision+1
  fun migrate(frame:Frame)=if(frame.query?.year==null)frame else frame.copy(
   query=frame.query.copy(year=null,request_revision=nextRevision),result=null,scrollIndex=0,scrollOffset=0)
  return copy(current=current?.let(::migrate),history=history.map(::migrate),revision=nextRevision)
 }
 fun open(photoId:String)=copy(current=Frame(photoId,current?.query,current?.result),history=history+listOfNotNull(current),revision=revision+1)
 fun select(anchor:SemanticAnchor):Journey {
  val rev=revision+1
  return copy(current=current?.copy(query=ExploreInput(anchor,request_revision=rev),result=null,scrollIndex=0,scrollOffset=0),history=history+listOfNotNull(current),revision=rev)
 }
 fun modify(year:Int?,direction:String):Journey {
  val rev=revision+1
  return copy(current=current?.copy(query=current.query?.copy(year=year,direction=direction,request_revision=rev),result=null),history=history+listOfNotNull(current),revision=rev)
 }
 fun back()=copy(current=history.lastOrNull(),history=history.dropLast(1),revision=revision+1)
 fun accept(rev:Long,result:ExplorationResult)=if(rev==revision) copy(current=current?.copy(result=result)) else this
}
interface GalleryRepository {
 val photos:Flow<List<Photo>>
 suspend fun refreshAndSync(progress:(String)->Unit)
 suspend fun analysis(photoId:String):Analysis
 suspend fun explore(input:ExploreInput,onUpdate:(ExplorationResult)->Unit):ExplorationResult
 suspend fun cancelExploration()
 suspend fun spaces(refresh:Boolean=true):List<Space>
 suspend fun organize(progress:(String)->Unit)
 suspend fun saveJourney(journey:Journey)
 suspend fun loadJourney():Journey
 suspend fun feedback(kind:String,photoId:String?=null,regionId:String?=null,spaceId:String?=null,value:String="")
 suspend fun metric(name:String,value:String="")
}
