package com.connectedgallery.app

import android.Manifest
import android.app.Application
import android.os.Build
import android.os.Bundle
import androidx.activity.enableEdgeToEdge
import androidx.activity.ComponentActivity
import androidx.activity.compose.*
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.connectedgallery.explore.*
import com.connectedgallery.library.LibraryScreen
import dagger.hilt.android.AndroidEntryPoint
import dagger.hilt.android.HiltAndroidApp
import javax.inject.Inject
import com.connectedgallery.data.ServerConnection
import com.connectedgallery.data.PcApi

@HiltAndroidApp class GalleryApplication:Application()
@AndroidEntryPoint class MainActivity:ComponentActivity() {
 @Inject lateinit var connection:ServerConnection
 @Inject lateinit var api:PcApi
 private val vm:GalleryViewModel by viewModels()
 override fun onStop() { super.onStop();com.connectedgallery.data.enqueueSync(this) }
 override fun onCreate(savedInstanceState:Bundle?) {
  super.onCreate(savedInstanceState);enableEdgeToEdge()
  setContent {
   val colors=darkColorScheme(primary=Color(0xFFBCF2D7),background=Color(0xFF111516),surface=Color(0xFF192020),onBackground=Color(0xFFEAF1EC))
   MaterialTheme(colorScheme=colors) {
    val photos by vm.photos.collectAsState();val journey by vm.journey.collectAsState();val status by vm.status.collectAsState()
    var showNotice by remember { mutableStateOf(false) }
    var showServer by remember { mutableStateOf(connection.current()==null) }
    if(showServer)ServerDialog(connection,api,onDismiss={showServer=false},onSaved={showServer=false;vm.refresh()})
    if(showNotice)AlertDialog(onDismissRequest={showNotice=false},title={Text("오픈소스 안내")},text={Text(remember { assets.open("NOTICE.txt").bufferedReader().use { it.readText() } },Modifier.verticalScroll(rememberScrollState()))},confirmButton={TextButton(onClick={showNotice=false}) { Text("닫기") }})
    val permissions=rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { vm.refresh() }
    DisposableEffect(Unit) {
     val observer=LifecycleEventObserver { _,event -> if(event==Lifecycle.Event.ON_RESUME)vm.refresh() }
     lifecycle.addObserver(observer);onDispose { lifecycle.removeObserver(observer) }
    }
    BackHandler(enabled=journey.current!=null) { vm.back() }
    Surface(Modifier.fillMaxSize()) {
     Column(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing)) {
      if(journey.current==null) {
       Row(Modifier.fillMaxWidth().padding(16.dp),horizontalArrangement=Arrangement.SpaceBetween) {
        Text("Connected\nGallery",style=MaterialTheme.typography.headlineMedium)
        TextButton(onClick={permissions.launch(if(Build.VERSION.SDK_INT>=34)arrayOf(Manifest.permission.READ_MEDIA_IMAGES,Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED) else if(Build.VERSION.SDK_INT>=33)arrayOf(Manifest.permission.READ_MEDIA_IMAGES) else arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE))}) { Text("사진 연결") }
       }
       Row(Modifier.padding(horizontal=16.dp)) {
        Text("내 사진",Modifier.align(androidx.compose.ui.Alignment.CenterVertically))
        Spacer(Modifier.weight(1f));TextButton(onClick={showServer=true}) { Text("서버") };TextButton(onClick={showNotice=true}) { Text("안내") };TextButton(onClick=vm::refresh) { Text("새로고침") }
       }
      }
      if(status.isNotEmpty())Text(status,Modifier.padding(horizontal=16.dp,vertical=6.dp),style=MaterialTheme.typography.bodySmall)
      if(journey.current!=null)ExploreScreen(vm,Modifier.weight(1f))
      else LibraryScreen(photos,vm::open,Modifier.weight(1f))
     }
    }
   }
  }
 }
}
