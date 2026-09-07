package com.connectedgallery.app

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.connectedgallery.data.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

@Composable fun ServerDialog(connection:ServerConnection,api:PcApi,onDismiss:()->Unit,onSaved:()->Unit) {
 val initial=remember { connection.current() }
 var address by remember { mutableStateOf(initial?.url?:"") }
 var key by remember { mutableStateOf(initial?.token?:"") }
 var busy by remember { mutableStateOf(false) }
 var error by remember { mutableStateOf("") }
 val scope=rememberCoroutineScope()
 AlertDialog(onDismissRequest={if(!busy)onDismiss()},title={Text("서버 연결")},text={
  Column(verticalArrangement=Arrangement.spacedBy(12.dp)) {
   Text("PC 서버의 주소와 접속 키를 입력하세요. PC와 서버가 실행 중이면 Wi-Fi나 모바일 데이터로 연결할 수 있어요.")
   OutlinedTextField(address,{address=it},label={Text("서버 주소")},placeholder={Text("https://gallery.example.com")},singleLine=true,enabled=!busy,modifier=Modifier.fillMaxWidth())
   OutlinedTextField(key,{key=it},label={Text("접속 키")},singleLine=true,enabled=!busy,visualTransformation=PasswordVisualTransformation(),modifier=Modifier.fillMaxWidth())
   if(error.isNotEmpty())Text(error,color=MaterialTheme.colorScheme.error)
   if(busy)Text("연결을 확인하고 있어요")
  }
 },confirmButton={TextButton(enabled=!busy,onClick={scope.launch {
  busy=true;error=""
  try {
   val endpoint=ServerEndpoint.validated(address,key)
   api.checkConnection(endpoint);connection.save(endpoint);onSaved()
  } catch(e:CancellationException){throw e} catch(e:IllegalArgumentException){error=e.message?:"입력 내용을 확인해 주세요"}
  catch(_:Exception){error="연결하지 못했어요. 서버 주소·접속 키와 PC 실행 상태를 확인해 주세요"}
  finally {busy=false}
 }}) {Text("확인 후 저장")}},dismissButton={TextButton(enabled=!busy,onClick=onDismiss){Text("취소")}})
}
