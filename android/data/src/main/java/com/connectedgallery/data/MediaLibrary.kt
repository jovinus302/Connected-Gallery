package com.connectedgallery.data

import android.content.ContentUris
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.net.Uri
import android.provider.MediaStore
import androidx.exifinterface.media.ExifInterface
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import com.connectedgallery.domain.Photo
import com.connectedgallery.domain.RegionBox
import android.content.pm.PackageManager
import android.Manifest
import android.os.Build
import java.io.ByteArrayOutputStream
import java.time.Instant
import java.util.UUID
import javax.inject.Inject

class MediaLibrary @Inject constructor(@ApplicationContext private val context:Context) {
 private val prefs=context.getSharedPreferences("gallery-device",Context.MODE_PRIVATE)
 private val device=prefs.getString("id",null)?:UUID.randomUUID().toString().also { prefs.edit().putString("id",it).apply() }
 suspend fun list():List<Photo> = withContext(Dispatchers.IO) {
  val granted=if(Build.VERSION.SDK_INT>=33) context.checkSelfPermission(Manifest.permission.READ_MEDIA_IMAGES)==PackageManager.PERMISSION_GRANTED || (Build.VERSION.SDK_INT>=34 && context.checkSelfPermission(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)==PackageManager.PERMISSION_GRANTED) else context.checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE)==PackageManager.PERMISSION_GRANTED
  if(!granted)return@withContext emptyList()
  val fields=arrayOf(MediaStore.Images.Media._ID,MediaStore.Images.Media.DATE_TAKEN,MediaStore.Images.Media.DATE_MODIFIED,MediaStore.Images.Media.SIZE,MediaStore.Images.Media.WIDTH,MediaStore.Images.Media.HEIGHT,MediaStore.Images.Media.ORIENTATION)
  val output=mutableListOf<Photo>()
  context.contentResolver.query(MediaStore.Images.Media.EXTERNAL_CONTENT_URI,fields,null,null,"${MediaStore.Images.Media.DATE_ADDED} DESC")?.use { cursor ->
   while(cursor.moveToNext() && output.size<1000) {
    val id=cursor.getLong(0);val taken=cursor.getLong(1);val modified=cursor.getLong(2);val rotation=cursor.getInt(6)
    val width=cursor.getInt(4).coerceAtLeast(1);val height=cursor.getInt(5).coerceAtLeast(1)
    output+=Photo(id="${device}_$id",device_id=device,local_uri=ContentUris.withAppendedId(MediaStore.Images.Media.EXTERNAL_CONTENT_URI,id).toString(),version="$modified-${cursor.getLong(3)}-$taken-$rotation",captured_at=if(taken>0) Instant.ofEpochMilli(taken).toString() else Instant.ofEpochSecond(modified).toString(),time_source=if(taken>0) "media_store" else "modified",width=if(rotation%180==0) width else height,height=if(rotation%180==0) height else width,rotation=rotation)
   }
  }
  output
 }
 suspend fun preview(photo:Photo,box:RegionBox?=null):ByteArray=withContext(Dispatchers.IO) {
  val uri=Uri.parse(photo.local_uri)
  val bounds=BitmapFactory.Options().apply { inJustDecodeBounds=true }
  context.contentResolver.openInputStream(uri).use { BitmapFactory.decodeStream(it,null,bounds) }
  var sample=1
  while(maxOf(bounds.outWidth,bounds.outHeight)/sample>3072) sample*=2
  val options=BitmapFactory.Options().apply { inSampleSize=sample }
  val bitmap=context.contentResolver.openInputStream(uri).use { BitmapFactory.decodeStream(it,null,options) } ?: error("사진을 읽을 수 없어요")
  val exif=context.contentResolver.openInputStream(uri).use { stream -> stream?.let { ExifInterface(it) } }
  val matrix=Matrix().apply {
   if(exif!=null) { if(exif.isFlipped) postScale(-1f,1f);postRotate(exif.rotationDegrees.toFloat()) }
   else postRotate(photo.rotation.toFloat())
  }
  val oriented=Bitmap.createBitmap(bitmap,0,0,bitmap.width,bitmap.height,matrix,true)
  val crop=if(box==null)oriented else {
   val left=(box.x*oriented.width).toInt().coerceIn(0,oriented.width-1);val top=(box.y*oriented.height).toInt().coerceIn(0,oriented.height-1)
   Bitmap.createBitmap(oriented,left,top,(box.width*oriented.width).toInt().coerceIn(1,oriented.width-left),(box.height*oriented.height).toInt().coerceIn(1,oriented.height-top))
  }
  val ratio=(1536f/maxOf(crop.width,crop.height)).coerceAtMost(1f)
  val resized=Bitmap.createScaledBitmap(crop,(crop.width*ratio).toInt().coerceAtLeast(1),(crop.height*ratio).toInt().coerceAtLeast(1),true)
  val out=ByteArrayOutputStream();resized.compress(Bitmap.CompressFormat.JPEG,90,out)
  if(resized!==crop) resized.recycle()
  if(crop!==oriented)crop.recycle()
  if(oriented!==bitmap) oriented.recycle()
  bitmap.recycle();out.toByteArray()
 }
}
